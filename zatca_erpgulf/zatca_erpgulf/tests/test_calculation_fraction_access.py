"""Ordinary saved READ protects the exact Currency API projection, not defaults."""

import copy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_fraction_access as fraction
from zatca_erpgulf.zatca_erpgulf.source_metadata import PROPERTIES
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_fraction_source import scenario as source_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_access import saved_graph
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


def bind_fraction(case, operator):
    """Independent normal-document views plus trusted server API callbacks."""
    case.data.own = SimpleNamespace(applied=case.data.metas[case.data.metas[case.invoice.doctype].get_field("items").options])
    saved_graph(operator, case)
    root = case.invoice.doctype
    definition = case.data.metas[root].get_field("currency")
    case.link = Document(fieldname="currency", permlevel=0, **{name: definition.get(name) for name in PROPERTIES})
    normal = case.normal_metas[root]
    original = normal.get_field
    normal.name, normal.issingle, normal.istable = root, 0, 0
    normal.get_field = lambda name: case.link if name == "currency" else original(name)
    normal.has_field = lambda name: normal.get_field(name) is not None
    case.invoice.currency = case.data.records["header"][0]["currency"]
    case.fraction_definition = Document(permlevel=0,
        **case.data.raw_fraction.definitions[fraction.FIELD].values)
    meta = Document(name="Currency", issingle=0, istable=0,
        get_field=lambda name: case.fraction_definition if name == fraction.FIELD else None,
        has_field=lambda name: name == fraction.FIELD, get_permlevel_access=Mock(return_value=[0]))
    case.currency = Document(doctype="Currency", name=case.invoice.currency,
        modified=case.data.currency_rows[0]["modified"], meta=meta,
        save=Mock(), db_set=Mock(), check_permission=Mock())
    original_get = case.currency.get
    def get(name, *args):
        if name == fraction.FIELD: raise AssertionError("Document defaults must not replace DB API value")
        return original_get(name, *args)
    case.currency.get = get
    operator.documents["Currency", case.currency.name] = case.currency
    raw = case.data.currency_rows[0]["value"]
    case.api_fraction = 0.0 if raw is None else float(raw)
    case.fraction_metadata = Mock(side_effect=lambda scope, types: {"Currency": case.data.fraction.applied})
    case.fraction_cache = Mock(side_effect=lambda scope, currency: case.api_fraction)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=case.parent_kind, applied_metadata_reader=case.metadata_provider,
        fraction_metadata_reader=case.fraction_metadata, fraction_cache_reader=case.fraction_cache)
    return case


def scenario(operator, monkeypatch, *, parent_kind="site", **options):
    data = source_case(monkeypatch, **options)
    case = defaults_case(operator, doctype=data.doctype, parent_kind=parent_kind, docstatus=1)
    case.parent_kind = parent_kind
    bind(case, data, operator)
    data.observations = case.observations
    bind_fraction(case, operator)
    default_cursor, native_cursor = case.database.cursor, data.connection.cursor
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            self.current = native_cursor() if any(marker in sql for marker in (
                "OCTET_LENGTH(", "ORDER BY BINARY `name` LIMIT")) else default_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    monkeypatch.setattr(access, "MariaDBMetadataSourceReader", Mock(return_value=data.metadata_reader))
    return case


def capture(case, major=16):
    return case.service.capture_currency_fraction_context(case.invoice.name, doctype=case.invoice.doctype, erp_major=major)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("value", [None, Decimal("0.000000000"), Decimal("0.050000000"), -0.0])
def test_permissioned_native_fraction_uses_one_owned_financial_pipeline(defaults_operator, monkeypatch, doctype, major, value):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, value=value)
    defaults_operator.denied.add(("System Settings", None))  # Unused method/locale settings.
    result = capture(case, major)
    assert type(result) is fraction.SavedCurrencyFractionContext
    assert result.financial.financial == result.fraction.financial
    assert result.invoice_currency == case.invoice.currency == result.related[0].name
    assert result.fraction.effective_fraction.hex() == case.api_fraction.hex()
    assert tuple(name for name, _ in result.tables) == ("items", "taxes")
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    assert case.fraction_metadata.call_count == 2 and case.fraction_cache.call_count == 3
    assert all(call.args == (case.scope, case.invoice.currency) for call in case.fraction_cache.call_args_list)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["invoice", "company", "role", "table", "child", "other_child", "currency", "fraction_field", "link_field", "financial_field"])
def test_all_record_table_row_and_field_reads_precede_callbacks(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied == "role": defaults_operator.runtime.get_roles.return_value = []
    elif denied == "fraction_field": case.fraction_definition.permlevel = 1
    elif denied == "link_field": case.link.permlevel = 1
    elif denied == "financial_field": case.field_overrides[case.invoice.doctype, "grand_total"] = Document(fieldtype="Currency", permlevel=1)
    else:
        identity = {"invoice": (case.invoice.doctype, case.invoice.name), "company": ("Company", case.company.name),
            "table": ("Sales Invoice Item", None), "child": ("Sales Invoice Item", "items-1"),
            "other_child": ("Sales Taxes and Charges", "taxes-1"), "currency": ("Currency", case.currency.name)}[denied]
        defaults_operator.denied.add(identity)
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.fraction_metadata, case.fraction_cache): callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("boundary", ["fraction_first", "fraction_last", "api_first", "api_last", "root_last", "close"])
@pytest.mark.parametrize("changed", ["currency", "permission", "field", "definition", "child", "revision"])
def test_callbacks_and_close_cannot_hide_original_or_fresh_access_drift(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    def mutate():
        if changed == "currency": case.invoice.currency = "USD"
        elif changed == "permission": defaults_operator.denied.add(("Currency", case.currency.name))
        elif changed == "field": case.fraction_definition.permlevel = 1
        elif changed == "definition": case.fraction_definition.default = "1"
        elif changed == "child": case.refs["items"].clear()
        else: case.currency.modified += timedelta(seconds=1)
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        callback = case.fraction_metadata if boundary.startswith("fraction") else case.fraction_cache if boundary.startswith("api") else case.metadata_provider
        original = callback.side_effect
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


@pytest.mark.parametrize("value", [None, "0.05", Decimal("0.05"), 0, True, float("nan"), float("inf"), 0.06])
def test_consumed_api_projection_requires_exact_finite_float(defaults_operator, monkeypatch, value):
    case = scenario(defaults_operator, monkeypatch)
    case.api_fraction = value
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


def test_api_projection_cannot_change_signed_zero(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, value=-0.0)
    case.api_fraction = 0.0
    with pytest.raises(InspectionFailed): capture(case)


@pytest.mark.parametrize("target", ["invoice", "currency"])
def test_fresh_equal_document_cannot_hide_drift_in_original_authorized_object(defaults_operator, monkeypatch, target):
    case = scenario(defaults_operator, monkeypatch)
    original = getattr(case, target)
    def close():
        fresh = copy.copy(original)
        defaults_operator.documents[fresh.doctype, fresh.name] = fresh
        if target == "invoice": original.currency = "USD"
        else:
            original.meta = copy.copy(original.meta)
            original.meta.name = "Company"
    case.database.close.side_effect = close
    with pytest.raises(InspectionFailed): capture(case)


@pytest.mark.parametrize("fault", ["fraction", "tables", "related", "financial", "invoice_currency"])
def test_protected_context_refuses_dropped_or_rebound_sources(defaults_operator, monkeypatch, fault):
    result = capture(scenario(defaults_operator, monkeypatch))
    value = () if fault in ("tables", "related") else "USD" if fault == "invoice_currency" else None
    with pytest.raises(fraction.CalculationFormatAccessError): replace(result, **{fault: value})
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)


@pytest.mark.parametrize("major,parent_kind", [(True,"site"), ("16","site"), (17,"site"), (15,"global"), (16,"user")])
def test_unreviewed_version_or_scope_refused_without_callbacks(defaults_operator, monkeypatch, major, parent_kind):
    case = scenario(defaults_operator, monkeypatch, parent_kind=parent_kind)
    with pytest.raises(InspectionFailed): capture(case, major)
    for callback in (case.factory, case.cache, case.metadata_provider, case.fraction_metadata, case.fraction_cache): callback.assert_not_called()


def test_old_financial_operation_does_not_require_fraction_dependencies(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    result = case.service.capture_financial_context(case.invoice.name, erp_major=15)
    assert type(result) is access.SavedCalculationFinancialRead
    case.fraction_metadata.assert_not_called()
    case.fraction_cache.assert_not_called()


def test_explicitly_authorized_higher_field_level_is_supported(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.link.permlevel = case.fraction_definition.permlevel = 2
    case.invoice.meta.get_permlevel_access.return_value = [0, 2]
    case.currency.meta.get_permlevel_access.return_value = [0, 2]
    assert capture(case).fraction.effective_fraction == 0.05


@pytest.mark.parametrize("changed", ["link_target", "link_type", "link_default", "root_identity", "currency_identity", "currency_fieldname"])
def test_normal_metadata_must_match_native_selected_definitions(defaults_operator, monkeypatch, changed):
    case = scenario(defaults_operator, monkeypatch)
    if changed == "link_target": case.link.options = "Company"
    elif changed == "link_type": case.link.fieldtype = "Data"
    elif changed == "link_default": case.link.default = "USD"
    elif changed == "root_identity": case.invoice.meta.name = "POS Invoice"
    elif changed == "currency_identity": case.currency.meta.name = "Company"
    else: case.fraction_definition.fieldname = "number_format"
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()


def test_normal_currency_revision_must_match_native_record(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.currency.modified += timedelta(seconds=1)
    with pytest.raises(InspectionFailed): capture(case)
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2


@pytest.mark.parametrize("boundary", [1, 2, 3])
def test_api_drift_at_each_capture_boundary_is_refused(defaults_operator, monkeypatch, boundary):
    case = scenario(defaults_operator, monkeypatch)
    case.fraction_cache.side_effect = lambda *args: 0.1 if case.fraction_cache.call_count == boundary else case.api_fraction
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_fraction_interrupts_keep_priority_and_owned_cleanup(defaults_operator, monkeypatch, error):
    case = scenario(defaults_operator, monkeypatch)
    case.fraction_cache.side_effect = error("synthetic interruption")
    with pytest.raises(error): capture(case)
    assert case.database.rollback.call_count == 2
    case.database.close.assert_called_once()
    assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
