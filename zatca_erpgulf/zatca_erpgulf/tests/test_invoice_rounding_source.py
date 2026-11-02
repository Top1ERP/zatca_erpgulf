"""Optional invoice controls, native overlap and separate Check normalization."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import itertools
import json
import pickle
import re
from types import SimpleNamespace
from unittest.mock import Mock

from pymysql.constants import FIELD_TYPE as FT
from frappe.model.base_document import BaseDocument
import pytest

from zatca_erpgulf.zatca_erpgulf import invoice_rounding_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.source_metadata import INVOICE_ROUNDING_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import scenario as financial_case, observed_metadata, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


def declarations(*, doctype="Sales Invoice", present=source.FIELDS, major=16, consolidated=None, disabled=None):
    case = financial_case(doctype, optional=False)
    case.major = major
    own_raw = AppliedMeta(doctype, present)
    for name in present:
        own_raw.definitions[name].values["fieldtype"] = "Check" if name in source.CHECKS else "Currency"
    for name in source.OVERLAP:
        if name in present: case.raw_metas[doctype].definitions[name] = own_raw.definitions[name]
        else: case.raw_metas[doctype].definitions.pop(name, None)
    case.metas[doctype] = project(case.raw_metas[doctype])
    case.observations[doctype] = observed_metadata(case.raw_metas[doctype])
    case.own = observed_metadata(own_raw, profile=INVOICE_ROUNDING_PROFILE)
    case.own_raw = own_raw
    values = dict(is_consolidated=consolidated, disable_rounded_total=disabled,
        rounding_adjustment=Decimal("0.010000000"), rounded_total=Decimal("8.700000000"))
    case.records["header"][0].update({name: values[name] for name in present})
    case.connection.columns = set(present)
    for name in present:
        case.connection.signatures["header", name] = ([FT.LONG, 20, 0, True] if name in source.CHECKS
            else [FT.NEWDECIMAL, 23, 9, True])
    case.connection.event = None
    return case


def scenario(monkeypatch, **options):
    case = declarations(**options)
    db = case.connection
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, args=()):
            db.queries.append((sql, args))
            if db.error: raise db.error
            if sql == "SELECT @@session.autocommit": return
            if "information_schema.COLUMNS" in sql:
                if db.event: db.event("columns", False)
                self.rows = tuple((name,) for name in sorted(db.columns))
                return
            table = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
            group = "header" if table == case.doctype else next(key for key in case.records if key != "header" and financial._child_type(case.doctype, key) == table)
            selected = tuple(dict.fromkeys(re.findall(r"OCTET_LENGTH\(`([^`]+)`\)", sql)))
            full = "CASE WHEN" in sql
            if db.event: db.event(group, full)
            ids = native.ROOT_IDS if group == "header" else native.CHILD_IDS
            self.description = [(name, FT.VAR_STRING, None, None, 140, 0, True) for name in ids]
            for name in selected:
                if full:
                    code, precision, scale, nullable = db.signatures[group, name]
                    self.description.append((name, code, None, None, precision, scale, nullable))
                self.description.append(("length", FT.LONG, None, None, 20, 0, True))
            self.rows = []
            for record in case.records[group][:args[-1]]:
                row = [record.get(name) for name in ids]
                for name in selected:
                    value = record.get(name)
                    count = None if value is None else len(str(value).encode())
                    if full: row.append(value if count is None or count <= financial.MAX_TEXT_BYTES else None)
                    row.append(count)
                self.rows.append(tuple(row))
            self.rows = tuple(self.rows)
        def fetchone(self): return db.autocommit
        def fetchall(self): return self.rows
    db.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.own if meta.profile == INVOICE_ROUNDING_PROFILE else case.observations[meta.name]
    for module in (native, source):
        monkeypatch.setattr(module, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    case.metadata_reader = provider
    case.financial = native.MariaDBInvoiceFinancialReader(db).load_for_update(case.doctype,
        case.name, erp_major=case.major, applied_metadata=case.metas)
    case.reader = source.MariaDBInvoiceRoundingReader(db)
    return case


def load(case):
    return case.reader.load_for_update(case.financial, applied_metadata=case.own.applied)


def failure(call, code="invoice_rounding_read"):
    with pytest.raises(source.InvoiceRoundingSourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


PRESENCE = tuple(tuple(name for name, on in zip(source.FIELDS, bits) if on)
    for bits in itertools.product((False, True), repeat=4))


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", PRESENCE)
def test_every_optional_membership_keeps_old_financial_bytes_and_separate_checks(monkeypatch, doctype, major, present):
    case = scenario(monkeypatch, doctype=doctype, major=major, present=present)
    original = case.financial._payload, case.financial.sha256, case.financial.financial._payload
    result = load(case)
    expected = {name: 0 if name in present else None for name in source.CHECKS}
    assert dict(result.normalized_checks) == expected and result.consolidated is False
    result.require_check_cache_match(expected)
    body = json.loads(result._payload)
    assert body["columns"] == sorted(present)
    assert dict(body["fields"])["is_consolidated"] == (["null"] if "is_consolidated" in present else ["absent"])
    assert (case.financial._payload, case.financial.sha256, case.financial.financial._payload) == original
    assert result.financial is not case.financial
    case.reader.require_unchanged(result)
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))


@pytest.mark.parametrize("consolidated,disabled", tuple(itertools.product((None, 0, 1), repeat=2)))
def test_raw_null_and_zero_have_equal_normalized_values_but_different_identity(monkeypatch, consolidated, disabled):
    case = scenario(monkeypatch, consolidated=consolidated, disabled=disabled)
    result = load(case)
    assert result.consolidated is (consolidated == 1)
    assert dict(result.normalized_checks) == dict(is_consolidated=consolidated or 0, disable_rounded_total=disabled or 0)
    fields = dict(json.loads(result._payload)["fields"])
    assert fields["is_consolidated"] == financial._scalar(consolidated)
    assert fields["rounding_adjustment"] == ["decimal", "0.010000000"]


@pytest.mark.parametrize("value", [None, False, True, "0", 0.0, 1.0, 2, -1])
def test_cache_requires_the_exact_normalized_check_projection(monkeypatch, value):
    case = scenario(monkeypatch)
    result = load(case)
    failure(lambda: result.require_check_cache_match(dict(is_consolidated=value, disable_rounded_total=0)),
        "invoice_rounding_check_cache_mismatch")


@pytest.mark.parametrize("raw", [True, "0", 0.0, 2, -1])
def test_noncanonical_native_consolidation_is_refused(monkeypatch, raw):
    case = scenario(monkeypatch, consolidated=raw)
    failure(lambda: load(case))
    failure(lambda: load(case), "invoice_rounding_transaction_unusable")


@pytest.mark.parametrize("fault", ["missing_column", "orphan_column", "column_case", "schema_type", "overlap_type", "overlap_value", "meta_type", "profile", "root_identity"])
def test_missing_or_conflicting_metadata_columns_and_overlap_fail_closed(monkeypatch, fault):
    case = scenario(monkeypatch)
    if fault == "missing_column": case.connection.columns.remove("is_consolidated")
    elif fault == "orphan_column":
        case.own_raw.definitions.pop("is_consolidated")
        case.own = observed_metadata(case.own_raw, profile=INVOICE_ROUNDING_PROFILE)
    elif fault == "column_case": case.connection.columns = (case.connection.columns - {"is_consolidated"}) | {"Is_Consolidated"}
    elif fault == "schema_type": case.connection.signatures["header", "is_consolidated"] = [FT.DOUBLE, 22, 0, True]
    elif fault == "overlap_type": case.connection.signatures["header", "disable_rounded_total"] = [FT.SHORT, 6, 0, True]
    elif fault == "overlap_value": case.records["header"][0]["rounded_total"] = Decimal("8.710000000")
    elif fault == "meta_type":
        case.own_raw.definitions["is_consolidated"].values["fieldtype"] = "Int"
        case.own = observed_metadata(case.own_raw, profile=INVOICE_ROUNDING_PROFILE)
    elif fault == "profile": case.own = case.observations[case.doctype]
    else: case.records["header"][0]["name"] = "OTHER"
    failure(lambda: load(case))


@pytest.mark.parametrize("changed", ["consolidation", "null_to_zero", "revision", "financial", "columns", "metadata"])
def test_recheck_detects_changes_even_when_effective_checks_do_not_change(monkeypatch, changed):
    case = scenario(monkeypatch)
    observed = load(case)
    if changed == "consolidation": case.records["header"][0]["is_consolidated"] = 1
    elif changed == "null_to_zero": case.records["header"][0]["is_consolidated"] = 0
    elif changed == "revision": case.records["header"][0]["modified"] += timedelta(seconds=1)
    elif changed == "financial": case.records["items"][0]["amount"] = Decimal("2.000000000")
    elif changed == "columns": case.connection.columns.remove("is_consolidated")
    else: case.metadata_reader.require_unchanged.side_effect = ValueError("PRIVATE-META")
    failure(lambda: case.reader.require_unchanged(observed), "invoice_rounding_changed")


@pytest.mark.parametrize("fault", ["profile", "metadata", "financial", "modified", "columns", "raw", "types", "extra", "derived"])
def test_reconstruction_and_cache_comparison_refuse_tampering(monkeypatch, fault):
    case = scenario(monkeypatch)
    result = load(case)
    body = json.loads(result._payload)
    if fault == "derived":
        object.__setattr__(result, "consolidated", True)
        failure(lambda: result.require_check_cache_match(dict(result.normalized_checks)), "invoice_rounding_check_cache_mismatch")
        return
    if fault == "profile": body["profile"] = "OTHER"
    elif fault == "metadata": body["metadata_sha256"] = "f" * 64
    elif fault == "financial": body["financial_sha256"] = "f" * 64
    elif fault == "modified": body["modified"] = ["null"]
    elif fault == "columns": body["columns"] = []
    elif fault == "raw": body["fields"][-1][1] = ["int", "1"]
    elif fault == "types": body["types"][-1][1][0] = FT.DOUBLE
    else: body["unexpected"] = "PRIVATE"
    failure(lambda: replace(result, _payload=financial._canonical(body)), "invoice_rounding_rows")


@pytest.mark.parametrize("interrupt", [False, True])
def test_borrowed_reader_sanitizes_driver_failures_and_preserves_ownership(monkeypatch, interrupt):
    case = scenario(monkeypatch)
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE-DRIVER")
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case)
    else: failure(lambda: load(case))
    failure(lambda: load(case), "invoice_rounding_transaction_unusable")
    for name in ("commit", "rollback", "close"): getattr(case.connection, name).assert_not_called()


def test_protected_results_are_not_serializable(monkeypatch):
    case = scenario(monkeypatch)
    result = load(case)
    for value in (result, case.reader):
        assert "SYNTHETIC" not in repr(value)
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(value)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("raw", [None, 0, 1])
@pytest.mark.parametrize("present", [(), source.FIELDS])
def test_check_projection_matches_actual15_and_pinned16_numeric_fix(monkeypatch, upstream16, major, raw, present):
    case = scenario(monkeypatch, major=major, consolidated=raw, disabled=raw, present=present)
    result = load(case)
    values = {name: raw for name in source.CHECKS if name in present}
    doc = SimpleNamespace(docstatus=0, get=values.get, set=lambda key, value: values.__setitem__(key, value),
        meta=SimpleNamespace(get=lambda *args: [SimpleNamespace(fieldname=name, fieldtype="Check")
            for name in source.CHECKS if name in present]))
    if major == 15:
        BaseDocument._fix_numeric_types(doc)
    else:
        monkeypatch.setitem(upstream16, "numeric_fieldtypes", ("Check",))
        upstream16["_fix_numeric_types"](doc)
    result.require_check_cache_match({name: doc.get(name) for name in source.CHECKS})


@pytest.mark.parametrize("field", source.CHECKS)
@pytest.mark.parametrize("raw,getter,accepted", [(None,None,True), (None,0,True), (None,1,False),
    (0,None,False), (0,0,True), (1,None,False), (1,1,True),
    (None,False,False), (None,"0",False), (None,0.0,False)])
def test_saved_view_requires_exact_native_null_for_none_without_widening_fixed_api(monkeypatch, field, raw, getter, accepted):
    case = scenario(monkeypatch, consolidated=raw, disabled=raw)
    observed = load(case)
    before = observed._payload, observed.sha256, observed.financial.financial._payload
    supplied = dict(observed.normalized_checks)
    supplied[field] = getter
    if accepted:
        observed.require_saved_check_match(supplied)
    else:
        failure(lambda: observed.require_saved_check_match(supplied), "invoice_rounding_saved_check_mismatch")
    if getter is None:
        failure(lambda: observed.require_check_cache_match(supplied), "invoice_rounding_check_cache_mismatch")
    observed.require_check_cache_match(dict(observed.normalized_checks))
    assert before == (observed._payload, observed.sha256, observed.financial.financial._payload)


@pytest.mark.parametrize("field", source.CHECKS)
def test_proved_absence_remains_none_in_both_views(monkeypatch, field):
    case = scenario(monkeypatch, present=tuple(name for name in source.FIELDS if name != field))
    observed = load(case)
    values = dict(observed.normalized_checks)
    assert values[field] is None
    observed.require_saved_check_match(values)
    observed.require_check_cache_match(values)
    values[field] = 0
    failure(lambda: observed.require_saved_check_match(values), "invoice_rounding_saved_check_mismatch")
