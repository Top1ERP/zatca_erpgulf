"""Saved root/child/reference numeric getters on the shared owned pipeline."""

import copy
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_numeric_access as numeric
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import scenario as financial_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_access import saved_graph
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


def bind_numeric(case, operator):
    case.data.own = SimpleNamespace(applied=case.data.metas[financial._child_type(case.invoice.doctype, "items")])
    saved_graph(operator, case)
    for name, value in case.data.records["header"][0].items(): setattr(case.invoice, name, value)
    for name, meta in case.normal_metas.items():
        meta.name = name
        meta.has_field = lambda field, meta=meta: meta.get_field(field) is not None
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=getattr(case,"parent_kind","site"), applied_metadata_reader=case.metadata_provider)
    return case


def scenario(operator, monkeypatch, **options):
    return bind_numeric(financial_case(operator, monkeypatch, **options), operator)


def capture(case, major=16):
    return case.service.capture_numeric_context(case.invoice.name, doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("optional", [True, False])
def test_authorized_saved_getters_match_native_header_and_children_on_one_pipeline(defaults_operator, monkeypatch, doctype, major, optional):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, optional=optional)
    result = capture(case, major)
    assert type(result) is numeric.SavedFinancialNumericRead
    assert result.view.financial == result.financial.financial and result.view.stage == "SAVED"
    assert len(result.tables) == (5 if optional else 2)
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    assert case.metadata_provider.call_count == 4
    assert type(case.invoice.grand_total) is Decimal
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["root", "company", "table", "child", "field", "role"])
def test_all_returned_financial_reads_precede_metadata_and_owned_sql(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied == "role": defaults_operator.runtime.get_roles.return_value = []
    elif denied == "field": case.field_overrides[case.invoice.doctype,"grand_total"] = Document(fieldtype="Currency", permlevel=1)
    else:
        identity = {"root": (case.invoice.doctype,case.invoice.name), "company": ("Company",case.company.name),
            "table": ("Sales Invoice Item",None), "child": ("Sales Invoice Item","items-1")}[denied]
        defaults_operator.denied.add(identity)
    with pytest.raises(PermissionDenied): capture(case)
    case.factory.assert_not_called()
    case.cache.assert_not_called()
    case.metadata_provider.assert_not_called()


@pytest.mark.parametrize("boundary", ["metadata_first", "metadata_last", "cache_last", "close"])
@pytest.mark.parametrize("changed", ["header", "child", "reference", "permission", "membership"])
def test_callbacks_and_close_cannot_hide_saved_view_or_access_drift(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def change():
        if changed == "header": case.invoice.grand_total = Decimal("8.7")
        elif changed == "child": case.saved["items","items-1"].amount = Decimal("2.000000000")
        elif changed == "reference": case.refs["items"][0].amount = Decimal("2.000000000")
        elif changed == "permission": defaults_operator.denied.add(("Sales Invoice Item","items-1"))
        else: case.refs["taxes"].clear()
    if boundary == "close": case.database.close.side_effect = change
    else:
        callback = case.metadata_provider if boundary.startswith("metadata") else case.cache
        old = callback.side_effect or (lambda *args: callback.return_value)
        def read(*args):
            result = old(*args)
            if callback.call_count == (1 if boundary.endswith("first") else 4 if boundary == "metadata_last" else 2): change()
            return result
        callback.side_effect = read
    denied = changed == "permission"
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("view", ["saved", "reference"])
def test_initial_inconsistent_child_view_is_not_replaced_by_fresh_native_data(defaults_operator, monkeypatch, view):
    case = scenario(defaults_operator, monkeypatch)
    doc = case.saved["items","items-1"] if view == "saved" else case.refs["items"][0]
    doc.amount = 1.0
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()


def test_fresh_equal_parent_cannot_hide_changed_original_getter(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    original = case.invoice
    def close():
        defaults_operator.documents[original.doctype,original.name] = copy.copy(original)
        original.grand_total = Decimal("8.7")
    case.database.close.side_effect = close
    with pytest.raises(InspectionFailed): capture(case)


@pytest.mark.parametrize("fault", ["financial", "view", "tables"])
def test_saved_result_reconstruction_refuses_dropped_sources(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    with pytest.raises(numeric.FinancialNumericViewError): replace(result, **{fault: () if fault == "tables" else None})


def test_older_financial_operation_does_not_read_money_getters(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    original = case.invoice.get
    def get(name, *args):
        if name == "grand_total": raise AssertionError("Unused numeric getter")
        return original(name, *args)
    case.invoice.get = get
    assert type(case.service.capture_financial_context(case.invoice.name, erp_major=15)) is access.SavedCalculationFinancialRead


@pytest.mark.parametrize("major,parent", [(True,"site"),("16","site"),(17,"site"),(15,"global"),(16,"user")])
def test_unreviewed_versions_and_non_site_defaults_are_refused_before_providers(defaults_operator, monkeypatch, major, parent):
    case = scenario(defaults_operator, monkeypatch, parent_kind=parent)
    with pytest.raises(InspectionFailed): capture(case, major)
    case.factory.assert_not_called()
    case.metadata_provider.assert_not_called()


@pytest.mark.parametrize("boundary", ["metadata_last", "close"])
@pytest.mark.parametrize("changed", ["precision", "kind"])
def test_selected_normal_definitions_are_pinned_through_cleanup(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    df = case.data.metas[case.invoice.doctype].get_field("grand_total")
    from zatca_erpgulf.zatca_erpgulf.source_metadata import PROPERTIES
    replacement = Document(fieldname="grand_total", **{name: df.get(name) for name in PROPERTIES})
    if changed == "precision": replacement.precision = "3"
    else: replacement.fieldtype = "Float"
    def change(): case.field_overrides[case.invoice.doctype,"grand_total"] = replacement
    if boundary == "close": case.database.close.side_effect = change
    else:
        old = case.metadata_provider.side_effect
        def read(*args):
            value = old(*args)
            if case.metadata_provider.call_count == 4: change()
            return value
        case.metadata_provider.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_interrupt_after_numeric_capture_preserves_cleanup_priority(defaults_operator, monkeypatch, interrupt):
    case = scenario(defaults_operator, monkeypatch)
    case.cache.side_effect = interrupt("synthetic interruption")
    with pytest.raises(interrupt): capture(case)
    assert case.database.rollback.call_count == 2
    case.database.close.assert_called_once()
