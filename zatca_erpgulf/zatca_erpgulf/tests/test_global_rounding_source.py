"""Native Check projection and actual15/pinned16 API behavior, synthetic only."""

import ast
import __future__
from collections import defaultdict
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

from frappe.database import database as framework_database
from frappe.utils import data as framework_data
from pymysql.constants import FIELD_TYPE as FT
import pytest

from zatca_erpgulf.zatca_erpgulf import global_rounding_source as source
from zatca_erpgulf.zatca_erpgulf import currency_format_source as transport
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf import source_metadata as schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import erp_major, case
from zatca_erpgulf.zatca_erpgulf.tests.test_rounded_total_control import declaration
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_settings_observation import capture as capture_settings
from zatca_erpgulf.zatca_erpgulf.rounded_total_control import RoundedTotalControl


def scenario(*, raw="0", missing=False, default="1"):
    meta = AppliedMeta(source.DOCTYPE, (source.FIELD,))
    meta.definitions[source.FIELD].values.update(fieldtype="Check", default=default)
    selected = observed_metadata(meta, profile=schema.GLOBAL_ROUNDING_PROFILE)
    connection = SimpleNamespace(queries=[], rows=[] if missing else [(source.DOCTYPE, source.FIELD, raw)],
        autocommit=(0,), error=None, hook=None, value_code=FT.BLOB,
        commit=Mock(), rollback=Mock(), close=Mock())
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement, params=()):
            connection.queries.append((statement, params))
            if connection.error: raise connection.error
            if statement == "SELECT @@session.autocommit": return
            assert "FROM `tabSingles`" in statement and params == (source.DOCTYPE, source.FIELD, 2)
            full = "CASE WHEN" in statement
            if connection.hook: connection.hook(full)
            self.description = [("id", FT.VAR_STRING, None, None, 140, 0, True)] * 2
            if full: self.description.append(("value", connection.value_code, None, None, 65535, 0, True))
            self.description.append(("length", FT.LONG, None, None, 20, 0, True))
            self.rows = []
            for doctype, fieldname, value in connection.rows:
                size = None if value is None else len(str(value).encode())
                bounded = value if size is None or size <= transport.MAX_VALUE_BYTES else None
                self.rows.append((doctype, fieldname, bounded, size) if full else (doctype, fieldname, size))
            self.rows = tuple(self.rows)
        def fetchone(self): return connection.autocommit
        def fetchall(self): return self.rows
    connection.cursor = Mock(side_effect=Cursor)
    return SimpleNamespace(raw=meta, metadata=selected, connection=connection)


def reader(case, monkeypatch):
    metadata_reader = Mock()
    metadata_reader.load_for_update.return_value = case.metadata
    monkeypatch.setattr(source, "MariaDBMetadataSourceReader", Mock(return_value=metadata_reader))
    return source.MariaDBGlobalRoundingReader(case.connection), metadata_reader


def load(case, handle):
    return handle.load_for_update(applied_metadata=case.metadata.applied)


def failure(call, code="global_rounding_read"):
    with pytest.raises(source.GlobalRoundingSourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


@pytest.mark.parametrize("raw,missing", [(None, True), (None, False), ("", False), ("0", False), ("1", False)])
@pytest.mark.parametrize("default", [None, "0", "1"])
def test_exact_raw_and_normalized_api_projection_without_defaults_or_cleanup(monkeypatch, raw, missing, default):
    case = scenario(raw=raw, missing=missing, default=default)
    handle, metadata = reader(case, monkeypatch)
    observed = load(case, handle)
    assert type(observed.value) is int and observed.value == (1 if raw == "1" else 0)
    assert observed.stored is not missing
    assert json.loads(observed._payload)["record"]["value"] == (["absent"] if missing else financial._scalar(raw))
    handle.require_unchanged(observed)
    observed.require_cache_match(observed.value)
    failure(lambda: observed.require_cache_match(1 - observed.value), "global_rounding_cache_mismatch")
    assert metadata.require_unchanged.call_count == 2
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))
    assert not any("singleton_nonempty" in name for name in json.loads(observed._payload)["record"])
    for value in (observed, handle):
        assert "Global Defaults" not in repr(value)
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(value)
    with pytest.raises(FrozenInstanceError): observed.value = 1


def test_equal_effective_values_retain_different_storage_identity(monkeypatch):
    digests = set()
    for raw, missing in [(None, True), (None, False), ("", False), ("0", False)]:
        case = scenario(raw=raw, missing=missing)
        handle, _ = reader(case, monkeypatch)
        observed = load(case, handle)
        assert observed.value == 0
        digests.add(observed.sha256)
    assert len(digests) == 4


@pytest.mark.parametrize("cached", [None, "", "0", "1", False, True, 0.0, 1.0, -1, 2, object()])
@pytest.mark.parametrize("raw", ["0", "1"])
def test_cache_requires_the_exact_cast_api_type(monkeypatch, raw, cached):
    case = scenario(raw=raw)
    handle, _ = reader(case, monkeypatch)
    observed = load(case, handle)
    failure(lambda: observed.require_cache_match(cached), "global_rounding_cache_mismatch")


@pytest.mark.parametrize("changed", ["value", "null_to_blank", "membership", "absent_to_null", "metadata"])
def test_same_branch_drift_still_invalidates_native_evidence(monkeypatch, changed):
    case = scenario(raw=None, missing=changed == "absent_to_null")
    handle, metadata = reader(case, monkeypatch)
    observed = load(case, handle)
    if changed == "value": case.connection.rows[0] = (source.DOCTYPE, source.FIELD, "1")
    elif changed == "null_to_blank": case.connection.rows[0] = (source.DOCTYPE, source.FIELD, "")
    elif changed == "membership": case.connection.rows.clear()
    elif changed == "absent_to_null": case.connection.rows.append((source.DOCTYPE, source.FIELD, None))
    else: metadata.require_unchanged.side_effect = ValueError("PRIVATE-METADATA")
    failure(lambda: handle.require_unchanged(observed), "global_rounding_changed")
    failure(lambda: load(case, handle), "global_rounding_transaction_unusable")


@pytest.mark.parametrize("fault", ["duplicate", "doctype_case", "field_case", "oversize", "binary", "integer",
    "sql_type", "absent_sql_type", "autocommit", "autocommit_bool", "metadata_type", "metadata_profile", "metadata_absent"])
def test_bad_source_is_never_defaulted_and_failure_poisons_reader(monkeypatch, fault):
    case = scenario(missing=fault == "absent_sql_type")
    if fault == "duplicate": case.connection.rows *= 2
    elif fault == "doctype_case": case.connection.rows[0] = ("global defaults", source.FIELD, "0")
    elif fault == "field_case": case.connection.rows[0] = (source.DOCTYPE, "Disable_Rounded_Total", "0")
    elif fault == "oversize": case.connection.rows[0] = (source.DOCTYPE, source.FIELD, "ع" * 2049)
    elif fault == "binary": case.connection.rows[0] = (source.DOCTYPE, source.FIELD, b"0")
    elif fault == "integer": case.connection.rows[0] = (source.DOCTYPE, source.FIELD, 0)
    elif fault in ("sql_type", "absent_sql_type"): case.connection.value_code = FT.LONG
    elif fault.startswith("autocommit"): case.connection.autocommit = (True,) if fault.endswith("bool") else (1,)
    elif fault == "metadata_type":
        case.raw.definitions[source.FIELD].values["fieldtype"] = "Int"
        case.metadata = observed_metadata(case.raw, profile=schema.GLOBAL_ROUNDING_PROFILE)
    elif fault == "metadata_profile": case.metadata = observed_metadata(case.raw)
    else:
        case.raw.definitions.clear()
        case.metadata = observed_metadata(case.raw, profile=schema.GLOBAL_ROUNDING_PROFILE)
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))
    failure(lambda: load(case, handle), "global_rounding_transaction_unusable")
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))
    if fault == "oversize": assert not any("CASE WHEN" in sql for sql, _ in case.connection.queries)


@pytest.mark.parametrize("raw", ["false", "true", "False", "01", " 1", "1.0", "2", "-1", "PRIVATE-INVALID", "0\0"])
def test_noncanonical_storage_is_refused_instead_of_permissively_cast(monkeypatch, raw):
    case = scenario(raw=raw)
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))


@pytest.mark.parametrize("fault", ["profile", "metadata", "fake_witness", "fake_modified", "field", "sql_type", "raw_type", "derived"])
def test_reconstruction_and_cache_comparison_revalidate_private_parents(monkeypatch, fault):
    case = scenario()
    handle, _ = reader(case, monkeypatch)
    observed = load(case, handle)
    body = json.loads(observed._payload)
    if fault == "derived":
        object.__setattr__(observed, "value", 1)
        failure(lambda: observed.require_cache_match(1), "global_rounding_cache_mismatch")
        return
    if fault == "profile": body["profile"] = "OTHER"
    elif fault == "metadata": body["metadata_sha256"] = "f" * 64
    elif fault == "fake_witness": body["record"]["singleton_nonempty"] = True
    elif fault == "fake_modified": body["record"]["modified"] = ["null"]
    elif fault == "field": body["record"]["field"] = "api_secret"
    elif fault == "sql_type": body["record"]["sql_type"][0] = FT.LONG
    else: body["record"]["value"] = financial._scalar(0)
    failure(lambda: replace(observed, _payload=financial._canonical(body)), "global_rounding_rows")


@pytest.mark.parametrize("interrupt", [False, True])
def test_driver_errors_are_sanitized_and_interrupts_keep_priority(monkeypatch, interrupt):
    case = scenario()
    handle, _ = reader(case, monkeypatch)
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE-DRIVER")
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case, handle)
    else: failure(lambda: load(case, handle))
    failure(lambda: load(case, handle), "global_rounding_transaction_unusable")


@pytest.mark.parametrize("doctype,name,field", [(source.DOCTYPE, "OTHER", source.FIELD),
    (source.DOCTYPE, source.DOCTYPE, "rounding_method"), (source.DOCTYPE, source.DOCTYPE, transport.FLAG),
    ("Company", "TEST", source.FIELD), ("System Settings", "System Settings", source.FIELD)])
def test_shared_transport_cannot_select_unreviewed_field_pairs(doctype, name, field):
    connection = SimpleNamespace(cursor=Mock())
    handle = transport.MariaDBCurrencyFormatReader(connection)
    cursor = Mock()
    with pytest.raises(ValueError): handle._select(cursor, doctype, name, full=False, singleton_field=field)
    cursor.execute.assert_not_called()


def test_narrow_metadata_does_not_expand_legacy_global_catalog():
    case = scenario()
    assert tuple(case.metadata.applied._fields) == (source.FIELD,)
    assert case.metadata.applied != project(case.raw)
    assert schema.PROFILE_FIELDS[schema.PROFILE] is schema.SOURCE_FIELDS


@pytest.fixture(scope="module")
def single_value16(upstream16):
    record = json.loads(Path(__file__).with_name("frappe16_precision_oracle.json").read_text())
    file = record["files"]["database/database.py"]
    assert file["sha256"] == "dc9fe0620ab7ceb300bee2b5da5c247d8979727139c785bb591e0a54e3bebf15"
    assert "MIT" in file["source_notice"]
    class DependenciesOnly(ast.NodeTransformer):
        def visit_ImportFrom(self, node): return None
    tree = DependenciesOnly().visit(ast.parse(file["excerpts"]["get_single_value"]))
    ast.fix_missing_locations(tree)
    namespace = dict(upstream16)
    namespace["cast_fieldtype"] = namespace["cast"]
    exec(compile(tree, "pinned-frappe16/database/database.py", "exec",
        flags=__future__.annotations.compiler_flag), namespace)
    return namespace


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("raw,missing", [(None, True), (None, False), ("", False), ("0", False), ("1", False)])
def test_missing_and_stored_values_match_the_real_api_cast(monkeypatch, single_value16, major, raw, missing):
    query = Mock()
    query.run.return_value = [] if missing else [(raw,)]
    definition = SimpleNamespace(fieldtype="Check", default="1")
    runtime = SimpleNamespace(qb=SimpleNamespace(get_query=Mock(return_value=query)),
        get_meta=Mock(return_value=SimpleNamespace(get_field=Mock(return_value=definition))))
    db = SimpleNamespace(value_cache=defaultdict(dict))
    if major == 15:
        monkeypatch.setattr(framework_database, "frappe", runtime)
        monkeypatch.setattr(framework_database, "cast_fieldtype",
            lambda kind, value: framework_data.cast_fieldtype(kind, value, show_warning=False))
        method = framework_database.Database.get_single_value
    else:
        monkeypatch.setitem(single_value16, "frappe", runtime)
        method = single_value16["get_single_value"]
    expected = method(db, source.DOCTYPE, source.FIELD)
    case = scenario(raw=raw, missing=missing)
    handle, _ = reader(case, monkeypatch)
    observed = load(case, handle)
    assert type(expected) is int and expected == observed.value
    observed.require_cache_match(expected)
    assert method(db, source.DOCTYPE, source.FIELD) == expected
    assert query.run.call_count == 1  # Real method cache hit, no invented defaults.


@pytest.mark.parametrize("raw,missing", [(None, True), (None, False), ("", False), ("0", False), ("1", False)])
def test_consumed_control_binds_normalized_native_global_value(case, monkeypatch, raw, missing):
    data = scenario(raw=raw, missing=missing)
    handle, _ = reader(data, monkeypatch)
    observed = load(data, handle)
    settings = declaration(case, has_flag=False, global_flag=observed.value)
    control = RoundedTotalControl(settings, False)
    observed.require_control_match(control)
    assert control.disable_value == tuple(financial._scalar(observed.value))
    case.records[source.DOCTYPE, source.DOCTYPE].disable_rounded_total = 1 - observed.value
    wrong = RoundedTotalControl(capture_settings(case), False)
    failure(lambda: observed.require_control_match(wrong), "global_rounding_control_mismatch")


@pytest.mark.parametrize("fault", ["invoice_field", "no_rounded_field", "consolidated", "raw_null", "bool", "tampered"])
def test_unused_or_unnormalized_declarations_cannot_claim_global_source_evidence(case, monkeypatch, fault):
    data = scenario(raw=None)
    handle, _ = reader(data, monkeypatch)
    observed = load(data, handle)
    options = dict(has_flag=False, global_flag=0)
    if fault == "invoice_field": options["has_flag"] = True
    elif fault == "no_rounded_field": options["rounded_field"] = False
    elif fault == "consolidated": options["adjustment"] = 1
    elif fault == "raw_null": options["global_flag"] = None
    elif fault == "bool": options["global_flag"] = False
    control = RoundedTotalControl(declaration(case, **options), fault == "consolidated")
    if fault == "tampered": object.__setattr__(control, "disabled", True)
    failure(lambda: observed.require_control_match(control), "global_rounding_control_mismatch")


@pytest.mark.parametrize("major", [15, 16])
def test_a_real_stale_api_cache_is_refused_without_refresh(monkeypatch, single_value16, major):
    query = Mock()
    runtime = SimpleNamespace(qb=SimpleNamespace(get_query=Mock(return_value=query)))
    db = SimpleNamespace(value_cache={source.DOCTYPE: {source.FIELD: 0}})
    if major == 15:
        monkeypatch.setattr(framework_database, "frappe", runtime)
        method = framework_database.Database.get_single_value
    else:
        monkeypatch.setitem(single_value16, "frappe", runtime)
        method = single_value16["get_single_value"]
    cached = method(db, source.DOCTYPE, source.FIELD)
    query.run.assert_not_called()
    runtime.qb.get_query.assert_not_called()
    data = scenario(raw="1")
    handle, _ = reader(data, monkeypatch)
    observed = load(data, handle)
    failure(lambda: observed.require_cache_match(cached), "global_rounding_cache_mismatch")
    assert db.value_cache[source.DOCTYPE][source.FIELD] == 0
