"""One owned root/direct-advance context; synthetic documents only."""

from dataclasses import replace
import pickle
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_advance_rounding as advance
from zatca_erpgulf.zatca_erpgulf import calculated_totals as totals
from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import scenario, configure
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, untouched, one_failure, InspectionFailed, PermissionDenied,
)


def capture(case, major=16):
    return case.service.capture_advance_rounding_context(case.invoice.name,
        erp_major=major, doctype=case.invoice.doctype)


def guard_precision(case):
    for doc in (*case.saved.values(), *(row for refs in case.refs.values() for row in refs)):
        doc.precision = Mock(side_effect=AssertionError("precision() must not run or warm a cache"))


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("cached", [False, True])
def test_configured_direct_precision_and_root_stage_share_one_handle(defaults_operator, monkeypatch, doctype, major, cached):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype)
    guard_precision(case)
    if cached:
        for key, doc in case.saved.items():
            if key[0] == "advances": doc._precision = {"main": {"allocated_amount": 2}}
        for doc in case.refs["advances"]: doc._precision = {"main": {"allocated_amount": 2}}
    result = capture(case, major)
    assert type(result) is advance.SavedAdvanceRoundingRead
    assert result.row_precisions == tuple(("advances-" + str(i + 1), 2) for i in range(3))
    assert result.fields == ()
    rows = totals.CalculationRows(result.stage.numeric.view.financial, "advances", "NUMERIC_FIXED",
        tuple((name, 1.0) for name, precision in result.row_precisions))
    calculated = totals.AdvanceAggregateCalculation(result.stage, rows, result)
    calculated.require_match(total_advance=3.0,
        setting_trace=(("rounding_method", "Commercial Rounding"),) * 4,
        precision_trace=tuple((name, "allocated_amount", 2) for name, precision in result.row_precisions)
            + ((case.invoice.name, "total_advance", 2),))
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    case.invoice.precision.assert_not_called()
    for doc in case.saved.values(): doc.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("fault", ["wrong", "bool", "null", "reference"])
def test_stale_direct_or_reference_precision_is_refused_without_repair(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    doc = case.refs["advances"][0] if fault == "reference" else case.saved["advances", "advances-1"]
    value = True if fault == "bool" else None if fault == "null" else 3
    doc._precision = {"main": {"allocated_amount": value}}
    with pytest.raises(InspectionFailed): capture(case)
    assert doc._precision["main"]["allocated_amount"] is value
    one_failure(defaults_operator, "ZATCA invoice financial data and calculation settings could not be confirmed. No settings or invoice were changed and no request was sent.")
    untouched(defaults_operator, case)


def test_empty_advance_table_does_not_require_child_sources(defaults_operator, monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import scenario as source_case
    case = configure(source_case(defaults_operator, monkeypatch), defaults_operator, advance_rows=0)
    result = capture(case)
    assert result.row_precisions == result.caches == result.fields == ()
    untouched(defaults_operator, case)


def test_group_result_is_protected_and_cannot_be_rebound(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    result = capture(case)
    assert case.invoice.name not in repr(result)
    with pytest.raises(TypeError): pickle.dumps(result)
    for changes in (dict(caches=result.caches[::-1]), dict(caches=result.caches[:1]), dict(fields=(None,))):
        with pytest.raises(advance.AdvanceRoundingError): replace(result, **changes)
    object.__setattr__(result, "row_precisions", (("advances-1", True), *result.row_precisions[1:]))
    with pytest.raises(advance.AdvanceRoundingError): result.pin()


@pytest.mark.parametrize("boundary", ["method_metadata", "defaults_cache", "close"])
@pytest.mark.parametrize("target", ["direct", "reference"])
def test_callbacks_cannot_warm_or_replace_original_precision_slots(defaults_operator, monkeypatch, boundary, target):
    case = scenario(defaults_operator, monkeypatch)
    doc = case.saved["advances", "advances-3"] if target == "direct" else case.refs["advances"][2]
    callback = {"method_metadata": case.round_metadata, "defaults_cache": case.cache, "close": case.database.close}[boundary]
    old = callback.side_effect
    def change(*args):
        result = old(*args) if old else callback.return_value
        doc._precision = {"main": {"allocated_amount": 2}}
        return result
    callback.side_effect = change
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["root", "table", "row", "field"])
def test_advance_access_denial_precedes_providers_and_sql(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied == "field":
        from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
        case.field_overrides["Sales Invoice Advance", "allocated_amount"] = Document(fieldtype="Currency", permlevel=1)
    else:
        identity = {"root": (case.invoice.doctype, case.invoice.name), "table": ("Sales Invoice Advance", None),
            "row": ("Sales Invoice Advance", "advances-3")}[denied]
        defaults_operator.denied.add(identity)
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.round_metadata): callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


def test_unused_row_currency_cache_is_not_inspected(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    defaults_operator.runtime.local.field_currency = "MALFORMED-UNUSED"
    result = capture(case)
    assert result.fields == () and result.row_precisions[0][1] == 2
    assert defaults_operator.runtime.local.field_currency == "MALFORMED-UNUSED"


@pytest.mark.parametrize("major", [15,16])
def test_primary_standard_advance_metadata_requires_party_currency(major):
    oracle = json.loads(Path(__file__).with_name("erpnext_currency_fields_oracle.json").read_text())
    source = next(row for row in oracle["sources"] if row["erp_major"] == major and row["doctype"] == "Sales Invoice Advance")
    allocated = next(row for row in source["fields"] if row["fieldname"] == "allocated_amount")
    assert allocated["options"] == "party_account_currency"


def test_configured_rows_share_one_fresh_precision_resolution(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    result = capture(case)
    calls = []
    from zatca_erpgulf.zatca_erpgulf.calculation_precision import FieldPrecisionResolution
    # Count the shared rule, not an adapter that checked header fields no longer
    # need. Both the header and configured rows still resolve fresh precision.
    original = FieldPrecisionResolution.__post_init__
    def resolve(source):
        calls.append((source.metadata.name, source.fieldname))
        return original(source)
    monkeypatch.setattr(FieldPrecisionResolution, "__post_init__", resolve)
    rebuilt = replace(result)
    assert rebuilt.row_precisions == result.row_precisions
    assert calls == [(case.invoice.doctype, "total_advance"), ("Sales Invoice Advance", "allocated_amount")]


def test_nonnumeric_allocated_field_is_refused_before_providers(defaults_operator, monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project
    from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
    from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
    case = scenario(defaults_operator, monkeypatch)
    raw = case.data.raw_metas["Sales Invoice Advance"]
    raw.definitions["allocated_amount"].values["fieldtype"] = "Data"
    case.applied[raw.name] = case.data.metas[raw.name] = project(raw)
    case.observations[raw.name] = observed_metadata(raw)
    service = case.service
    bind_numeric(case, defaults_operator)
    case.service = service
    with pytest.raises(InspectionFailed): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.round_metadata): callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
