"""Shared financial graph ACL plus original/fresh invoice Check getters."""

import copy
from dataclasses import replace
from datetime import timedelta
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_invoice_rounding_access as controls
from zatca_erpgulf.zatca_erpgulf import invoice_rounding_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_rounding_source import scenario as source_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_access import saved_graph
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


def bind_controls(case, operator):
    saved_graph(operator, case)
    root = case.invoice.doctype
    case.control_definitions = {name: Document(**definition.values, permlevel=0)
        for name, definition in case.data.own_raw.definitions.items()}
    def get(name):
        if (root, name) in case.field_overrides: return case.field_overrides[root, name]
        if name in source.FIELDS: return case.control_definitions.get(name)
        if name in case.definitions: return case.definitions[name]
        return case.data.metas[root].get_field(name)
    meta = case.normal_metas[root]
    meta.name, meta.issingle, meta.istable = root, 0, 0
    meta.get_field, meta.has_field = get, lambda name: get(name) is not None
    for name in source.CHECKS:
        value = case.data.records["header"][0].get(name)
        if name in case.control_definitions: setattr(case.invoice, name, value or 0)
    case.control_metadata = Mock(side_effect=lambda scope, types: {root: case.data.own.applied})
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=case.parent_kind, applied_metadata_reader=case.metadata_provider,
        invoice_rounding_metadata_reader=case.control_metadata)
    return case


def scenario(operator, monkeypatch, *, parent_kind="site", **options):
    data = source_case(monkeypatch, **options)
    case = defaults_case(operator, doctype=data.doctype, parent_kind=parent_kind, docstatus=1)
    case.parent_kind = parent_kind
    bind(case, data, operator)
    data.observations = case.observations
    bind_controls(case, operator)
    default_cursor, native_cursor = case.database.cursor, data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            self.current = native_cursor() if any(marker in sql for marker in (
                "OCTET_LENGTH(", "information_schema.COLUMNS", "ORDER BY BINARY `name` LIMIT")) else default_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    monkeypatch.setattr(access, "MariaDBMetadataSourceReader", Mock(return_value=data.metadata_reader))
    return case


def capture(case, major=16):
    return case.service.capture_invoice_rounding_context(case.invoice.name,
        doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", [(), source.FIELDS, ("rounding_adjustment", "rounded_total")])
def test_graph_controls_getters_and_defaults_share_one_owned_pipeline(defaults_operator, monkeypatch, doctype, major, present):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, present=present)
    result = capture(case, major)
    assert type(result) is controls.SavedInvoiceRoundingContext
    assert result.controls.financial == result.financial.financial
    assert result.controls.consolidated is False
    assert result.checks == tuple((name, 0 if name in present else None) for name in source.CHECKS)
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    assert case.control_metadata.call_count == 2
    assert tuple(name for name, _ in result.tables) == ("items", "taxes")
    assert not hasattr(result, "disabled")
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["invoice", "company", "role", "table", "child", "other_child", "control_field", "financial_field"])
def test_all_returned_graph_and_control_reads_precede_all_providers(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied == "role": defaults_operator.runtime.get_roles.return_value = []
    elif denied == "control_field": case.control_definitions["is_consolidated"].permlevel = 1
    elif denied == "financial_field":
        case.field_overrides[case.invoice.doctype, "grand_total"] = Document(fieldtype="Currency", permlevel=1)
    else:
        identity = {"invoice": (case.invoice.doctype, case.invoice.name), "company": ("Company", case.company.name),
            "table": ("Sales Invoice Item", None), "child": ("Sales Invoice Item", "items-1"),
            "other_child": ("Sales Taxes and Charges", "taxes-1")}[denied]
        defaults_operator.denied.add(identity)
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.control_metadata): callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["control_first", "control_last", "root_last", "cache_first", "cache_last", "close"])
@pytest.mark.parametrize("changed", ["getter", "permission", "field", "definition", "child", "owner"])
def test_callbacks_and_cleanup_cannot_hide_control_or_graph_drift(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "getter": case.invoice.is_consolidated = 1
        elif changed == "permission": defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        elif changed == "field": case.control_definitions["is_consolidated"].permlevel = 1
        elif changed == "definition": case.control_definitions["is_consolidated"].default = "1"
        elif changed == "child": case.refs["items"].clear()
        else: case.invoice.modified += timedelta(seconds=1)
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        callback = case.control_metadata if boundary.startswith("control") else case.metadata_provider if boundary == "root_last" else case.cache
        original = callback.side_effect or (lambda *args: callback.return_value)
        when = 1 if boundary.endswith("first") else 4 if boundary == "root_last" else 2
        def supplied(*args):
            result = original(*args)
            if callback.call_count == when: mutate()
            return result
        callback.side_effect = supplied
    denied = changed in ("permission", "field")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


def test_initial_authorized_getter_view_cannot_be_replaced_by_a_fresh_equal_document(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    original = case.invoice
    def close():
        fresh = copy.copy(original)
        fresh.is_consolidated = 0
        defaults_operator.documents[fresh.doctype, fresh.name] = fresh
        original.is_consolidated = 1
    case.database.close.side_effect = close
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("value", [None, False, "0", 0.0, 2])
def test_noncanonical_normal_getter_is_not_fixed_or_coerced(defaults_operator, monkeypatch, value):
    case = scenario(defaults_operator, monkeypatch)
    case.invoice.is_consolidated = value
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()
    case.control_metadata.assert_not_called()


def test_control_inspection_does_not_read_normal_money_getters(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    old = case.invoice.get
    def get(name, *args):
        if name in ("rounded_total", "rounding_adjustment"): raise AssertionError("No ORM money conversion")
        return old(name, *args)
    case.invoice.get = get
    assert capture(case).controls.consolidated is False


@pytest.mark.parametrize("fault", ["controls", "tables", "checks", "financial"])
def test_protected_result_refuses_dropped_or_rebound_sources(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    replacement = {"controls": None} if fault == "controls" else {"tables": ()} if fault == "tables" else {"checks": ()} if fault == "checks" else {"financial": object()}
    with pytest.raises(controls.CalculationChildAccessError): replace(result, **replacement)
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)


def test_old_financial_operation_does_not_invoke_the_new_provider(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    result = case.service.capture_financial_context(case.invoice.name, doctype=case.invoice.doctype, erp_major=15)
    assert type(result) is access.SavedCalculationFinancialRead
    case.control_metadata.assert_not_called()


def test_empty_tax_table_still_requires_table_read_before_callbacks(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.refs["taxes"].clear()
    case.data.records["taxes"].clear()
    defaults_operator.denied.add(("Sales Taxes and Charges", None))
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.control_metadata): callback.assert_not_called()


def test_absent_check_metadata_cannot_certify_an_in_memory_zero_attribute(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, present=())
    case.invoice.is_consolidated = 0
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()
    case.control_metadata.assert_not_called()


def test_wrong_normal_metadata_identity_is_refused_before_callbacks(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.invoice.meta.name = "POS Invoice"
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()
    case.control_metadata.assert_not_called()


@pytest.mark.parametrize("major,parent_kind", [(True,"site"), ("16","site"), (17,"site"), (15,"global"), (16,"user")])
def test_unreviewed_version_or_scope_never_invokes_providers(defaults_operator, monkeypatch, major, parent_kind):
    case = scenario(defaults_operator, monkeypatch, parent_kind=parent_kind)
    with pytest.raises(InspectionFailed): capture(case, major)
    for callback in (case.factory, case.cache, case.metadata_provider, case.control_metadata): callback.assert_not_called()
