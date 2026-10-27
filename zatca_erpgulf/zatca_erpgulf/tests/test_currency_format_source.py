"""Explicit format-profile metadata and bounded native source contracts."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

from pymysql.constants import FIELD_TYPE as FT
import pytest

from zatca_erpgulf.zatca_erpgulf import currency_format_source as source
from zatca_erpgulf.zatca_erpgulf import source_metadata as schema
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.calculation_precision import FieldPrecisionResolution
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import declarations, upstream16

NOW = datetime(2026, 10, 27, 18, 0, 0)


def scenario(*, currency="SAR", flag="1", language_format="#,###.##", currency_format="#.########"):
    language = "ar"
    observations, raw_metas = {}, {}
    for doctype in source._types(language, currency):
        fieldname = source.FLAG if doctype == "System Settings" else "number_format"
        raw = AppliedMeta(doctype, (fieldname,))
        raw.definitions[fieldname].values.update(fieldtype="Check" if doctype == "System Settings" else "Select")
        raw_metas[doctype] = raw
        observations[doctype] = observed_metadata(raw, profile=schema.FORMAT_PROFILE)
    records = {"Language": [(language, NOW, language_format)], "System Settings": [("System Settings", source.FLAG, flag)]}
    if currency is not None: records["Currency"] = [(currency, NOW, currency_format)]
    connection = SimpleNamespace(queries=[], records=records, hook=None, autocommit=(0,), error=None,
        commit=Mock(), rollback=Mock(), close=Mock(), value_code=FT.BLOB, singleton_nonempty=True)
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            connection.queries.append((sql, params))
            if connection.error: raise connection.error
            if sql == "SELECT @@session.autocommit": return
            table = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
            doctype = "System Settings" if table == "Singles" else table
            if table == "Singles" and "`field`=%s" not in sql:
                self.rows = (("System Settings",),) if connection.singleton_nonempty else ()
                return
            full = "CASE WHEN" in sql
            if connection.hook: connection.hook(doctype, full)
            self.rows = []
            self.description = [("id", FT.VAR_STRING, None, None, 140, 0, True)] * 2
            if full: self.description.append(("value", connection.value_code, None, None, 65535, 0, True))
            self.description.append(("length", FT.LONG, None, None, 20, 0, True))
            for first, second, value in connection.records[doctype]:
                length = None if value is None else len((value if type(value) is str else str(value)).encode())
                projected = (first, second, value if length is None or length <= source.MAX_VALUE_BYTES else None, length)
                self.rows.append(projected if full else (first, second, length))
            self.rows = tuple(self.rows)
        def fetchone(self): return connection.autocommit
        def fetchall(self): return self.rows
    connection.cursor = Mock(side_effect=Cursor)
    return SimpleNamespace(language=language, currency=currency, records=records, connection=connection,
        observations=observations, raw_metas=raw_metas,
        metas={name: row.applied for name, row in observations.items()})


def reader(case, monkeypatch):
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.observations[meta.name]
    provider.require_unchanged.return_value = None
    monkeypatch.setattr(source, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return source.MariaDBCurrencyFormatReader(case.connection), provider


def load(case, handle):
    return handle.load_for_update(case.language, currency=case.currency, applied_metadata=case.metas)


def failure(call, code="currency_format_source_read"):
    with pytest.raises(source.CurrencyFormatSourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


@pytest.mark.parametrize("flag", [None, "", "0", "1"])
@pytest.mark.parametrize("language_format", [None, "", "#,###.###"])
@pytest.mark.parametrize("currency_format", [None, "", "#.########"])
def test_raw_typed_source_builds_exact_v16_context_without_cleanup(monkeypatch, flag, language_format, currency_format):
    case = scenario(flag=flag, language_format=language_format, currency_format=currency_format)
    handle, provider = reader(case, monkeypatch)
    result = load(case, handle)
    handle.require_unchanged(result)
    result.require_context_match(result.context)
    assert result.context.language_number_format == language_format
    assert result.context.currency_number_format == currency_format
    assert result.context.use_currency_format is (flag == "1")
    assert provider.load_for_update.call_count == 6
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))
    assert "PARTIAL" in repr(result) and "SAR" not in repr(result)
    with pytest.raises(FrozenInstanceError): result.language = "en"
    for value in (result, handle):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(value)
    body = json.loads(result._payload)
    singleton = next(row for row in body["records"] if row["doctype"] == "System Settings")
    assert "modified" not in singleton and singleton["value"] == financial._scalar(flag)


@pytest.mark.parametrize("flag", [None, "", "0", "1"])
def test_no_currency_is_explicit_and_enabled_override_requires_a_resolved_currency(monkeypatch, flag):
    case = scenario(currency=None, flag=flag)
    handle, _ = reader(case, monkeypatch)
    if flag == "1": failure(lambda: load(case, handle))
    else:
        result = load(case, handle)
        assert result.context.currency is None and result.context.currency_number_format is None
        assert not any("FROM `tabCurrency`" in sql for sql, _ in case.connection.queries)


@pytest.mark.parametrize("doctype", tuple(schema.FORMAT_FIELDS))
def test_new_metadata_profile_is_explicit_and_keeps_the_legacy_catalog(doctype):
    case = scenario()
    projected = case.metas[doctype]
    assert projected.profile == schema.FORMAT_PROFILE
    assert tuple(projected._fields) == schema.FORMAT_FIELDS[doctype]
    if doctype == "Language":
        with pytest.raises(schema.SourceMetadataError): schema.project_source_metadata(case.raw_metas[doctype], base_fields={})
        assert "Language" not in schema.SOURCE_FIELDS
    else:
        legacy = project(case.raw_metas[doctype])
        assert legacy.profile == schema.PROFILE and legacy.sha256 != projected.sha256
        assert not legacy.has_field(source.FLAG) if doctype == "System Settings" else legacy.has_field("number_format")


@pytest.mark.parametrize("changed", ["flag_value", "language_value", "currency_value", "revision", "null_to_blank", "membership"])
def test_repeat_detects_format_or_singleton_changes_without_a_fake_parent_revision(monkeypatch, changed):
    case = scenario(flag=None)
    handle, _ = reader(case, monkeypatch)
    observed = load(case, handle)
    if changed == "flag_value": case.records["System Settings"][0] = ("System Settings", source.FLAG, "1")
    elif changed == "language_value": case.records["Language"][0] = ("ar", NOW, "#.###")
    elif changed == "currency_value": case.records["Currency"][0] = ("SAR", NOW, "#.###")
    elif changed == "revision": case.records["Language"][0] = ("ar", NOW + timedelta(seconds=1), "#,###.##")
    elif changed == "null_to_blank": case.records["System Settings"][0] = ("System Settings", source.FLAG, "")
    else: case.records["System Settings"] = []
    failure(lambda: handle.require_unchanged(observed), "currency_format_source_changed")


@pytest.mark.parametrize("fault", ["missing", "duplicate", "identity", "flag", "oversize", "binary", "timestamp", "sql_type", "metadata_profile", "metadata_extra", "metadata_missing", "metadata_fieldtype"])
def test_ambiguous_or_incompatible_sources_fail_closed_without_fallback(monkeypatch, fault):
    case = scenario()
    if fault == "missing": case.records["System Settings"] = []
    elif fault == "duplicate": case.records["System Settings"] *= 2
    elif fault == "identity": case.records["Language"][0] = ("AR", NOW, "#,###.##")
    elif fault == "flag": case.records["System Settings"][0] = ("System Settings", source.FLAG, "false")
    elif fault == "oversize": case.records["Currency"][0] = ("SAR", NOW, "ع" * 2049)
    elif fault == "binary": case.records["Currency"][0] = ("SAR", NOW, b"#,###.##")
    elif fault == "timestamp": case.records["Language"][0] = ("ar", None, "#,###.##")
    elif fault == "sql_type": case.connection.value_code = FT.LONG
    elif fault == "metadata_profile": case.metas["Currency"] = project(case.raw_metas["Currency"])
    elif fault == "metadata_extra": case.metas["Company"] = project(AppliedMeta("Company", ()))
    elif fault == "metadata_missing": case.metas.pop("Currency")
    else:
        raw = case.raw_metas["System Settings"]
        raw.definitions[source.FLAG].values["fieldtype"] = "Data"
        case.metas["System Settings"] = schema.project_source_metadata(raw, base_fields={}, profile=schema.FORMAT_PROFILE)
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))
    failure(lambda: load(case, handle), "currency_format_source_transaction_unusable")


def test_oversize_preflight_never_projects_values_and_full_growth_is_masked(monkeypatch):
    case = scenario(currency_format="X" * 4097)
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))
    assert not any("CASE WHEN" in sql for sql, _ in case.connection.queries)
    case = scenario()
    def mutate(doctype, full):
        if doctype == "Currency" and full: case.records[doctype][0] = ("SAR", NOW, "PRIVATE" * 1000)
    case.connection.hook = mutate
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))


@pytest.mark.parametrize("fault", ["profile", "identity", "metadata", "fake_revision", "type", "derived_context"])
def test_reconstruction_and_cache_match_revalidate_exact_private_parents(monkeypatch, fault):
    case = scenario()
    handle, _ = reader(case, monkeypatch)
    result = load(case, handle)
    body = json.loads(result._payload)
    if fault == "profile": body["profile"] = "OTHER"
    elif fault == "identity": body["language"] = "en"
    elif fault == "metadata": body["metadata"][0][1] = "f" * 64
    elif fault == "fake_revision": body["records"][-1]["modified"] = financial._scalar(NOW)
    elif fault == "type": body["records"][0]["sql_type"][0] = FT.LONG
    else:
        object.__setattr__(result, "context", replace(result.context, language="en"))
        failure(lambda: result.require_context_match(result.context), "currency_format_source_cache_mismatch")
        return
    failure(lambda: replace(result, _payload=financial._canonical(body)), "currency_format_source_rows")


def test_real_precision_consumer_uses_native_context_without_reinterpreting_money(monkeypatch):
    case = scenario(language_format="#.###", currency_format="#.########")
    handle, _ = reader(case, monkeypatch)
    result = load(case, handle)
    meta, defaults = declarations(values={})
    assert FieldPrecisionResolution(meta, "grand_total", defaults, 16, result.context).precision == 8
    failure(lambda: result.require_context_match(replace(result.context, currency_number_format="#.###")),
        "currency_format_source_cache_mismatch")


@pytest.mark.parametrize("interrupt", [False, True])
def test_failure_or_interruption_poison_the_reader_and_keep_caller_ownership(monkeypatch, interrupt):
    case = scenario()
    handle, _ = reader(case, monkeypatch)
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE-DRIVER")
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case, handle)
    else: failure(lambda: load(case, handle))
    failure(lambda: load(case, handle), "currency_format_source_transaction_unusable")
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))


@pytest.mark.parametrize("doctype,variant,expected", [
    ("Sales Invoice", "empty", "b4fb6b3c86a657fdf7ddd7951239b73553d12d667bf7b481aa38a736a49525e9"),
    ("Sales Invoice", "full", "944f97d09b6c4a73b2ddcecc723e08b69f72f1a3b3ac04d56aa4e313b655f6d9"),
    ("System Settings", "empty", "d27e552d847bc9355ded775d86db9c4abc90fe6ac6314ce6c71e2597278f857c"),
    ("System Settings", "full", "e2f53f2cef3825a3a2808bb8941deb3c8681b8becef4bf2e4967a21588dbc10d"),
    ("Currency", "empty", "ad6657e9b95b2f265c27d57975ca5941cc295ff79846d9cbd0722e7cb33fd876"),
    ("Currency", "full", "95bf428b590f3ef0e8955048239dd4075fb3dde688de7ea1c70a4c2367fa94b4"),
])
def test_legacy_applied_metadata_keeps_fixed_preincrement_hashes(doctype, variant, expected):
    # Captured from committed 8b504a8, not regenerated from the new implementation.
    raw = AppliedMeta(doctype, () if variant == "empty" else schema.SOURCE_FIELDS[doctype])
    assert project(raw).sha256 == expected


def test_profiles_cannot_be_mixed_by_the_shared_customization_matcher():
    from zatca_erpgulf.zatca_erpgulf.metadata_reconciliation import (
        reconcile_field_customizations, MetadataReconciliationError,
    )
    case = scenario()
    with pytest.raises(MetadataReconciliationError):
        reconcile_field_customizations(project(case.raw_metas["Currency"]), case.metas["Currency"],
            custom_fields=[], property_setters=[])


def test_format_read_view_only_exposes_its_explicit_selected_fields():
    case = scenario()
    doc = SimpleNamespace(doctype="Language", name="ar", get=lambda name: "#,###.##" if name == "number_format" else "PRIVATE")
    view = schema.SourceDocumentView(doc, case.metas["Language"])
    assert view.get("number_format") == "#,###.##"
    with pytest.raises(schema.SourceMetadataError): view.get("api_secret")
    object.__setattr__(case.metas["Language"], "profile", schema.PROFILE)
    with pytest.raises(ValueError): schema._pin_metadata(case.metas["Language"])


def test_opt_in_missing_check_requires_nonempty_storage_and_retains_absence(monkeypatch):
    case = scenario(flag="0")
    handle, _ = reader(case, monkeypatch)
    present = load(case, handle)
    compatible = load(case, source.MariaDBCurrencyFormatReader(case.connection, allow_missing_check=True))
    assert (compatible._payload, compatible.sha256) == (present._payload, present.sha256)
    case.records["System Settings"] = []
    opted = source.MariaDBCurrencyFormatReader(case.connection, allow_missing_check=True)
    observed = load(case, opted)
    assert observed.context.use_currency_format is False
    body = json.loads(observed._payload)
    assert body["profile"] == source.ABSENT_PROFILE
    assert body["records"][-1]["value"] == ["absent"]
    assert body["records"][-1]["singleton_nonempty"] is True
    opted.require_unchanged(observed)
    case.records["System Settings"] = [("System Settings", source.FLAG, "0")]
    failure(lambda: opted.require_unchanged(observed), "currency_format_source_changed")


def test_empty_singleton_is_not_hydrated_from_defaults(monkeypatch):
    case = scenario()
    case.records["System Settings"] = []
    case.connection.singleton_nonempty = False
    reader(case, monkeypatch)
    handle = source.MariaDBCurrencyFormatReader(case.connection, allow_missing_check=True)
    failure(lambda: load(case, handle))


def test_absence_profile_refuses_fabricated_or_missing_witness(monkeypatch):
    case = scenario()
    case.records["System Settings"] = []
    reader(case, monkeypatch)
    handle = source.MariaDBCurrencyFormatReader(case.connection, allow_missing_check=True)
    observed = load(case, handle)
    body = json.loads(observed._payload)
    body["records"][-1]["singleton_nonempty"] = False
    failure(lambda: replace(observed, _payload=financial._canonical(body)), "currency_format_source_rows")


@pytest.mark.parametrize("major", [15, 16])
def test_inspected_framework_numeric_fix_sets_a_missing_check_to_zero(upstream16, major):
    import frappe
    from frappe.model.base_document import BaseDocument
    values = {"existing_setting": "SYNTHETIC"}
    definition = frappe._dict(fieldname=source.FLAG, fieldtype="Check", default="1")
    doc = SimpleNamespace(meta=SimpleNamespace(get=lambda *args: [definition]),
        get=values.get, set=values.__setitem__, docstatus=0)
    if major == 15:
        BaseDocument._fix_numeric_types(doc)
    else:
        upstream16["numeric_fieldtypes"] = ("Check", "Int", "Float", "Currency", "Percent")
        upstream16["_fix_numeric_types"](doc)
    assert values[source.FLAG] == 0 and type(values[source.FLAG]) is int
    assert values["existing_setting"] == "SYNTHETIC"
