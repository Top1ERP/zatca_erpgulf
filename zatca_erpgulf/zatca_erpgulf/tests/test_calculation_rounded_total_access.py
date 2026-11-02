"""Consumed settings, controller guard order and one owned saved-source read."""

import copy
from dataclasses import replace
from decimal import Decimal
import json
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_rounded_total_access as selected
from zatca_erpgulf.zatca_erpgulf import invoice_rounding_source, currency_fraction_source, global_rounding_source, rounding_setting_source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _scalar
from zatca_erpgulf.zatca_erpgulf.calculation_rounding import METHODS, LEGACY_METHOD
from zatca_erpgulf.zatca_erpgulf.source_metadata import INVOICE_ROUNDING_PROFILE, CURRENCY_FRACTION_PROFILE, GLOBAL_ROUNDING_PROFILE, ROUNDING_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_invoice_rounding_access import scenario as root_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_fraction_access import bind_fraction
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_fraction_source import scenario as fraction_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_global_rounding_access import bind_global
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_rounding_access import bind_rounding
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, untouched, PermissionDenied, InspectionFailed,
)


def configure(case, operator, fraction_data, *, global_value="0"):
    root = case.invoice.doctype
    case.control_observation = case.data.own
    raw = case.data.raw_metas[root]
    raw.definitions["currency"].values.update(fieldtype="Link", options="Currency")
    case.data.metas[root], case.observations[root] = project(raw), observed_metadata(raw)
    case.applied[root] = case.data.metas[root]
    case.data.raw_fraction, case.data.fraction = fraction_data.raw_fraction, fraction_data.fraction
    case.data.currency_rows = fraction_data.currency_rows
    bind_fraction(case, operator)
    normal_get = case.invoice.meta.get_field
    case.invoice.meta.get_field = lambda name: case.control_definitions.get(name) if name in invoice_rounding_source.FIELDS else normal_get(name)
    case.invoice.rounding_adjustment = case.data.records["header"][0].get("rounding_adjustment")
    bind_global(case, operator, raw=global_value)
    bind_rounding(case, operator)
    case.control_metadata = Mock(side_effect=lambda *args: {root: case.control_observation.applied})
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        applied_metadata_reader=case.metadata_provider, invoice_rounding_metadata_reader=case.control_metadata,
        global_rounding_metadata_reader=case.global_metadata, global_rounding_cache_reader=case.global_cache,
        fraction_metadata_reader=case.fraction_metadata, fraction_cache_reader=case.fraction_cache,
        rounding_metadata_reader=case.round_metadata, rounding_cache_reader=case.round_cache)
    return case


def scenario(operator, monkeypatch, *, global_value="0", fraction=Decimal("0.050000000"), **options):
    case = root_case(operator, monkeypatch, **options)
    root_cursor = case.database.cursor
    fraction_data = fraction_case(monkeypatch, value=fraction)
    configure(case, operator, fraction_data, global_value=global_value)
    case.data.observations = case.observations
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            if "FROM `tabCurrency`" in sql: self.current = fraction_data.connection.cursor()
            elif "FROM `tabSingles`" in sql:
                self.current = (case.global_data.connection if params[0] == "Global Defaults" else case.round_data.connection).cursor()
            else: self.current = root_cursor()
            self.current.execute(sql, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    metadata = {INVOICE_ROUNDING_PROFILE: case.control_observation, CURRENCY_FRACTION_PROFILE: case.data.fraction,
        GLOBAL_ROUNDING_PROFILE: case.global_observation, ROUNDING_PROFILE: case.round_observation}
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: metadata[meta.profile] if meta.profile in metadata else case.observations[meta.name]
    for module in (access, financial_source_sql, invoice_rounding_source, currency_fraction_source, global_rounding_source, rounding_setting_source):
        monkeypatch.setattr(module, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return case


def capture(case, major=16):
    return case.service.capture_rounded_total_context(case.invoice.name, erp_major=major, doctype=case.invoice.doctype)


CASES = (
    (1, 0, invoice_rounding_source.FIELDS, "1", "PRESERVE_CONSOLIDATED_ADJUSTMENT", None),
    (0, 0, ("is_consolidated", "rounding_adjustment"), "1", "NO_ROUNDED_TOTAL_FIELD", None),
    (0, 1, invoice_rounding_source.FIELDS, "0", "DISABLED", "INVOICE_FIELD"),
    (0, 0, invoice_rounding_source.FIELDS, "1", "CURRENCY_FRACTION_THEN_FIELD_PRECISION", "INVOICE_FIELD"),
    (0, 0, ("is_consolidated", "rounding_adjustment", "rounded_total"), "1", "DISABLED", "GLOBAL_DEFAULTS"),
    (0, 0, ("is_consolidated", "rounding_adjustment", "rounded_total"), "0", "CURRENCY_FRACTION_THEN_FIELD_PRECISION", "GLOBAL_DEFAULTS"),
    (0, 0, ("rounding_adjustment", "rounded_total"), "1", "DISABLED", "GLOBAL_DEFAULTS"),
    (0, 0, ("rounding_adjustment", "rounded_total"), "0", "CURRENCY_FRACTION_THEN_FIELD_PRECISION", "GLOBAL_DEFAULTS"),
)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("consolidated,disabled,present,global_value,branch,origin", CASES)
def test_controller_order_consumes_exact_sources_on_one_handle(defaults_operator, monkeypatch, doctype, major, consolidated, disabled, present, global_value, branch, origin):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, consolidated=consolidated,
        disabled=disabled, present=present, global_value=global_value)
    result = capture(case, major)
    assert type(result) is selected.SavedRoundedTotalContext
    assert (result.selection.branch, result.selection.disable_origin) == (branch, origin)
    active = branch == "CURRENCY_FRACTION_THEN_FIELD_PRECISION"
    method_needed = active or branch == "DISABLED" and major == 16
    assert (result.global_context is not None) == (origin == "GLOBAL_DEFAULTS")
    assert (result.fraction_context is not None) == active
    assert (result.method_context is not None) == method_needed
    for callback in (case.fraction_metadata, case.fraction_cache):
        assert callback.called == active
    for callback in (case.round_metadata, case.round_cache):
        assert callback.called == method_needed
    assert case.global_metadata.called == (origin == "GLOBAL_DEFAULTS")
    assert case.global_cache.called == (origin == "GLOBAL_DEFAULTS")
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    if branch == "DISABLED":
        assert result.selection.zero_fields == (("rounded_total", "base_rounded_total", "rounding_adjustment") if major == 15 else ("rounded_total", "rounding_adjustment"))
    untouched(defaults_operator, case)


@pytest.mark.parametrize("fraction", [None, Decimal("0.000000000"), Decimal("0.050000000")])
def test_zero_and_positive_fraction_both_require_final_method(defaults_operator, monkeypatch, fraction):
    case = scenario(defaults_operator, monkeypatch, fraction=fraction)
    result = capture(case)
    assert result.method_context is not None
    assert result.selection.branch == ("CURRENCY_FRACTION_THEN_FIELD_PRECISION" if fraction else "WHOLE_UNIT_THEN_FIELD_PRECISION")
    assert result.selection.controls.financial.financial._payload == result.invoice.financial.financial.financial._payload


@pytest.mark.parametrize("boundary", ["control_last", "fraction_last", "method_last", "close"])
@pytest.mark.parametrize("changed", ["getter", "permission", "child", "fraction_permission"])
def test_cross_source_callbacks_and_close_recheck_original_guard_and_permissions(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch, consolidated=1)
    case.data.records["header"][0]["rounding_adjustment"] = Decimal("0.000000000")
    case.invoice.rounding_adjustment = Decimal("0.000000000")
    def mutate():
        if changed == "getter": case.invoice.rounding_adjustment = Decimal("0.01")
        elif changed == "permission": defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        elif changed == "child": case.refs["items"].clear()
        else: defaults_operator.denied.add(("Currency", "SAR"))
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        callback = {"control_last": case.control_metadata, "fraction_last": case.fraction_metadata, "method_last": case.round_metadata}[boundary]
        original = callback.side_effect
        def read(*args):
            value = original(*args)
            if callback.call_count == 2: mutate()
            return value
        callback.side_effect = read
    denied = changed in ("permission", "fraction_permission")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)


def test_unused_adjustment_getter_and_denied_related_settings_are_not_read(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, disabled=1)
    original = case.invoice.get
    def get(name, *args):
        if name == "rounding_adjustment": raise AssertionError("Unused money getter")
        return original(name, *args)
    case.invoice.get = get
    for dt in ("Currency", "System Settings", "Global Defaults"): defaults_operator.denied.add((dt, "SAR" if dt == "Currency" else dt))
    assert capture(case, 15).selection.branch == "DISABLED"


@pytest.mark.parametrize("dependency", ["currency", "system", "global"])
def test_selected_related_read_precedes_its_own_providers(defaults_operator, monkeypatch, dependency):
    present = tuple(name for name in invoice_rounding_source.FIELDS if name != "disable_rounded_total")
    case = scenario(defaults_operator, monkeypatch, present=present)
    dt, name = ("Currency", "SAR") if dependency == "currency" else (("System Settings", "System Settings") if dependency == "system" else ("Global Defaults", "Global Defaults"))
    defaults_operator.denied.add((dt, name))
    with pytest.raises(PermissionDenied): capture(case)
    callbacks = (case.global_metadata, case.global_cache, case.factory) if dependency == "global" else (case.fraction_metadata, case.fraction_cache, case.round_metadata, case.round_cache)
    for callback in callbacks: callback.assert_not_called()


@pytest.mark.parametrize("value", [True, "0", float("nan"), float("inf"), object()])
def test_invalid_consumed_money_guard_is_refused_without_repair(defaults_operator, monkeypatch, value):
    case = scenario(defaults_operator, monkeypatch, consolidated=1)
    case.invoice.rounding_adjustment = value
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()


def test_guard_witness_is_not_an_amount_equality_claim(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, consolidated=1)
    case.invoice.rounding_adjustment = Decimal("2.50")
    result = capture(case)
    assert result.selection.branch == "PRESERVE_CONSOLIDATED_ADJUSTMENT"
    assert result.selection.adjustment == ("decimal", "2.50")
    assert dict(json.loads(result.selection.controls._payload)["fields"])["rounding_adjustment"] == ["decimal", "0.010000000"]
    assert "NOT money" in repr(result)


@pytest.mark.parametrize("fault", ["selection", "global_context", "fraction_context", "method_context", "invoice"])
def test_result_refuses_dropped_or_rebound_sources(defaults_operator, monkeypatch, fault):
    present = tuple(name for name in invoice_rounding_source.FIELDS if name != "disable_rounded_total")
    result = capture(scenario(defaults_operator, monkeypatch, present=present))
    with pytest.raises(selected.RoundingSelectionError): replace(result, **{fault: None})
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    with pytest.raises(selected.RoundingSelectionError): replace(result.selection, fraction=None)


def test_fresh_equal_document_cannot_hide_changed_original_guard(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, consolidated=1)
    original = case.invoice
    def close():
        defaults_operator.documents[original.doctype, original.name] = copy.copy(original)
        original.rounding_adjustment = Decimal("0.02")
    case.database.close.side_effect = close
    with pytest.raises(InspectionFailed): capture(case)


@pytest.mark.parametrize("raw,getter", [(None, None), (Decimal("0.000000000"), -0.0), (Decimal("0.010000000"), 0.01)])
def test_native_and_normal_numeric_representations_prove_only_guard_truthiness(defaults_operator, monkeypatch, raw, getter):
    case = scenario(defaults_operator, monkeypatch, consolidated=1)
    case.data.records["header"][0]["rounding_adjustment"] = raw
    case.invoice.rounding_adjustment = getter
    result = capture(case)
    assert result.selection.branch == ("PRESERVE_CONSOLIDATED_ADJUSTMENT" if getter else "CURRENCY_FRACTION_THEN_FIELD_PRECISION")
    assert result.selection.adjustment == tuple(_scalar(getter))


def test_native_and_normal_guard_disagreement_never_acquires_later_settings(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, consolidated=1)
    case.invoice.rounding_adjustment = Decimal("0")
    with pytest.raises(InspectionFailed): capture(case)
    for callback in (case.fraction_metadata, case.fraction_cache, case.round_metadata, case.round_cache): callback.assert_not_called()


def test_skipped_path_needs_no_related_provider_configuration(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, disabled=1)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        applied_metadata_reader=case.metadata_provider, invoice_rounding_metadata_reader=case.control_metadata)
    assert capture(case, 15).selection.branch == "DISABLED"


def test_stale_global_api_cannot_hide_enabled_native_setting(defaults_operator, monkeypatch):
    present = tuple(name for name in invoice_rounding_source.FIELDS if name != "disable_rounded_total")
    case = scenario(defaults_operator, monkeypatch, present=present)
    case.global_api = 1
    with pytest.raises(InspectionFailed): capture(case)
    for callback in (case.fraction_metadata, case.fraction_cache, case.round_metadata, case.round_cache): callback.assert_not_called()


@pytest.mark.parametrize("major", [True, "16", 17])
def test_unreviewed_version_refused_before_metadata_and_connection(defaults_operator, monkeypatch, major):
    case = scenario(defaults_operator, monkeypatch)
    with pytest.raises(InspectionFailed): capture(case, major)
    case.factory.assert_not_called()
    case.control_metadata.assert_not_called()


def test_selected_fraction_reuses_the_already_authorized_graph(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    from zatca_erpgulf.zatca_erpgulf.calculation_child_access import FinancialGraphAccess
    original = FinancialGraphAccess.__init__
    calls = []
    def start(self, *args, **kwargs):
        calls.append(self)
        original(self, *args, **kwargs)
    monkeypatch.setattr(FinancialGraphAccess, "__init__", start)
    assert capture(case).fraction_context is not None
    assert len(calls) == 1


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_interrupt_during_conditional_acquisition_cleans_only_the_owned_handle(defaults_operator, monkeypatch, interrupt):
    case = scenario(defaults_operator, monkeypatch)
    case.round_metadata.side_effect = interrupt("synthetic interruption")
    with pytest.raises(interrupt): capture(case)
    assert case.database.rollback.call_count == 2
    case.database.close.assert_called_once()
    assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]


@pytest.mark.parametrize("method", [None, "", *sorted(METHODS)])
def test_selected_method_and_legacy_default_are_bound_without_amount_rounding(defaults_operator, monkeypatch, method):
    case = scenario(defaults_operator, monkeypatch)
    case.round_doc.rounding_method = method
    case.round_data.records["System Settings"] = [("System Settings", "rounding_method", method)]
    result = capture(case)
    assert result.selection.method == (method or LEGACY_METHOD)
    assert result.selection.method_origin == ("SYSTEM_SETTING" if method else "LEGACY_DEFAULT")


@pytest.mark.parametrize("fraction", [None, Decimal("0.050000000")])
def test_unknown_method_is_never_ignored_by_either_fraction_route(defaults_operator, monkeypatch, fraction):
    case = scenario(defaults_operator, monkeypatch, fraction=fraction)
    case.round_doc.rounding_method = "UNKNOWN-PRIVATE"
    with pytest.raises(InspectionFailed): capture(case)
    case.round_metadata.assert_not_called()


def test_v16_disabled_conversion_needs_method_but_no_currency_fraction(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, disabled=1)
    defaults_operator.denied.add(("Currency", "SAR"))
    defaults_operator.denied.add(("Global Defaults", "Global Defaults"))
    result = capture(case, 16)
    assert result.selection.branch == "DISABLED" and result.selection.rounding is not None
    assert result.fraction_context is None and result.method_context is not None
    case.fraction_metadata.assert_not_called()
    case.fraction_cache.assert_not_called()
    with pytest.raises(selected.RoundingSelectionError): replace(result.selection, rounding=None)
    with pytest.raises(selected.RoundingSelectionError): replace(result, method_context=None)


def test_v16_disabled_conversion_cannot_ignore_an_unknown_method(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch, disabled=1)
    case.round_doc.rounding_method = "UNKNOWN-PRIVATE"
    with pytest.raises(InspectionFailed): capture(case, 16)
    case.fraction_metadata.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
def test_present_null_saved_check_is_false_without_global_fallback(defaults_operator, monkeypatch, doctype, major):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, global_value="1")
    case.invoice.is_consolidated = case.invoice.disable_rounded_total = None
    result = capture(case, major)
    assert result.selection.branch == "CURRENCY_FRACTION_THEN_FIELD_PRECISION"
    assert result.selection.disabled is False and result.selection.disable_origin == "INVOICE_FIELD"
    assert all(value is None for _, value in result.invoice.checks)
    assert result.global_context is None
    case.global_metadata.assert_not_called()
    case.global_cache.assert_not_called()
    assert result.fraction_context is not None and result.method_context is not None
    assert case.invoice.is_consolidated is case.invoice.disable_rounded_total is None
