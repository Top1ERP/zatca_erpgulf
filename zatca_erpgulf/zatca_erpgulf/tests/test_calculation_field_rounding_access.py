"""Same-owned field/source/owner-cache composition with synthetic documents."""

from dataclasses import replace, FrozenInstanceError
from decimal import Decimal
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_field_rounding_access as selected
from zatca_erpgulf.zatca_erpgulf import rounding_setting_source as setting_sql
from zatca_erpgulf.zatca_erpgulf.calculation_rounding import METHODS
from zatca_erpgulf.zatca_erpgulf.child_field_currency import ABSENT
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import scenario as numeric_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_rounding_access import bind_rounding
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import row as default_row
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, untouched, one_failure, InspectionFailed, PermissionDenied,
)

TARGETS = ((None, None, "grand_total"), ("items", "items-1", "amount"), ("taxes", "taxes-1", "tax_amount"))


def configure(case, operator, **options):
    bind_rounding(case, operator, **options)
    case.invoice.precision = Mock(side_effect=AssertionError("must not populate owner precision"))
    for doc in (*case.saved.values(), *(row for refs in case.refs.values() for row in refs)):
        doc.precision = Mock(side_effect=AssertionError("must not call child precision"))
    return case


def scenario(operator, monkeypatch, **options):
    setting = {name: options.pop(name) for name in ("value", "missing") if name in options}
    case = numeric_case(operator, monkeypatch, **options)
    financial_cursor = case.database.cursor
    configure(case, operator, **setting)
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement, params=()):
            self.current = case.round_data.connection.cursor() if "FROM `tabSingles`" in statement else financial_cursor()
            self.current.execute(statement, params)
        def fetchone(self): return self.current.fetchone()
        def fetchall(self): return self.current.fetchall()
        @property
        def description(self): return self.current.description
    case.database.cursor = Mock(side_effect=Cursor)
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.round_observation
    monkeypatch.setattr(setting_sql, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return case


def capture(case, major=16, target=TARGETS[0]):
    parentfield, row_name, fieldname = target
    return case.service.capture_field_rounding_context(case.invoice.name, fieldname,
        erp_major=major, doctype=case.invoice.doctype, parentfield=parentfield, row_name=row_name)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("method", sorted(METHODS))
def test_value_defaults_method_and_owner_cache_share_one_owned_pipeline(defaults_operator, monkeypatch, doctype, major, target, cached, method):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype, value=method)
    if cached:
        case.invoice._precision = {target[0] or "main": {target[2]: 2}}
    result = capture(case, major, target)
    assert type(result) is selected.SavedFieldRoundingRead
    assert result.method.context == result.numeric.financial.context
    assert result.method.erp_major == result.numeric.view.financial.financial.erp_major == major
    assert result.precision.precision == 2 and result.method.method == method
    assert result.target == (target[0] or "header", target[1] or case.invoice.name, target[2])
    result.require_result_match(8.7 if target[0] is None else 1.0)
    assert result.cache[1] == (("int", "2") if cached else ABSENT)
    assert case.factory.call_count == 1 and case.database.rollback.call_count == 2
    assert type(case.invoice.grand_total) is Decimal
    case.invoice.precision.assert_not_called()
    assert ("_precision" in vars(case.invoice)) is cached
    untouched(defaults_operator, case)


@pytest.mark.parametrize("denied", ["root", "company", "table", "child", "numeric_field", "system", "system_field", "role"])
def test_graph_and_system_read_precede_all_providers(defaults_operator, monkeypatch, denied):
    case = scenario(defaults_operator, monkeypatch)
    if denied == "role": defaults_operator.runtime.get_roles.return_value = []
    elif denied == "system_field": case.round_df.permlevel = 1
    elif denied == "numeric_field":
        case.field_overrides[case.invoice.doctype, "grand_total"] = Document(fieldtype="Currency", permlevel=1)
    else:
        identity = {"root": (case.invoice.doctype, case.invoice.name), "company": ("Company", case.company.name),
            "table": ("Sales Invoice Item", None), "child": ("Sales Invoice Item", "items-1"),
            "system": ("System Settings", "System Settings")}[denied]
        defaults_operator.denied.add(identity)
    with pytest.raises(PermissionDenied): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.round_metadata, case.round_cache): callback.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("target", [(None, "other", "grand_total"), ("items", None, "amount"),
    ("items", "unknown", "amount"), ("payments", "payments-1", "amount"),
    ("unknown", "row", "amount"), (None, None, "company"), (None, None, "not_a_field"), (False, None, "grand_total")])
def test_invalid_or_nonnumeric_selection_never_reaches_providers(defaults_operator, monkeypatch, target):
    case = scenario(defaults_operator, monkeypatch)
    with pytest.raises(InspectionFailed): capture(case, target=target)
    for callback in (case.factory, case.cache, case.metadata_provider, case.round_metadata): callback.assert_not_called()


@pytest.mark.parametrize("slot", [None, True, "2", 2.0, 3])
@pytest.mark.parametrize("target", TARGETS[:2])
def test_existing_wrong_precision_is_refused_without_repair(defaults_operator, monkeypatch, slot, target):
    case = scenario(defaults_operator, monkeypatch)
    case.invoice._precision = {target[0] or "main": {target[2]: slot}}
    with pytest.raises(InspectionFailed): capture(case, target=target)
    assert case.invoice._precision[target[0] or "main"][target[2]] is slot
    case.invoice.precision.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


def test_parent_child_bucket_wins_over_direct_child_or_parent_main_cache(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.invoice._precision = {"items": {"amount": 2}, "main": {"amount": 99}, "taxes": {"amount": 98}}
    case.saved["items", "items-1"]._precision = {"main": {"amount": 97}}
    result = capture(case, target=TARGETS[1])
    assert result.precision.precision == 2
    result.require_result_match(1.0)


@pytest.mark.parametrize("boundary", ["method_metadata", "method_cache", "financial_metadata", "defaults_cache", "close"])
@pytest.mark.parametrize("changed", ["slot", "bucket", "container", "warmup", "amount", "permission"])
def test_callbacks_and_cleanup_cannot_hide_owner_cache_or_source_drift(defaults_operator, monkeypatch, boundary, changed):
    case = scenario(defaults_operator, monkeypatch)
    if changed != "warmup": case.invoice._precision = {"main": {"grand_total": 2}}
    def mutate():
        if changed == "slot": case.invoice._precision["main"]["grand_total"] = 3
        elif changed == "bucket": case.invoice._precision["main"] = {"grand_total": 2}
        elif changed == "container": case.invoice._precision = {"main": {"grand_total": 2}}
        elif changed == "warmup": case.invoice._precision = {"main": {"grand_total": 2}}
        elif changed == "amount": case.invoice.grand_total = Decimal("8.7")
        else: defaults_operator.denied.add(("System Settings", "System Settings"))
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        callback = {"method_metadata": case.round_metadata, "method_cache": case.round_cache,
            "financial_metadata": case.metadata_provider, "defaults_cache": case.cache}[boundary]
        original = callback.side_effect
        def invoke(*args):
            result = original(*args) if original else callback.return_value
            if callback.call_count == (2 if boundary in ("method_metadata", "defaults_cache") else 4 if boundary == "financial_metadata" else 2): mutate()
            return result
        callback.side_effect = invoke
    with pytest.raises(PermissionDenied if changed == "permission" else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if changed == "permission" else access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("major", [True, "16", 17])
def test_bad_versions_fail_before_any_provider(defaults_operator, monkeypatch, major):
    case = scenario(defaults_operator, monkeypatch)
    with pytest.raises(InspectionFailed): capture(case, major)
    case.factory.assert_not_called()
    case.metadata_provider.assert_not_called()


def test_protected_result_refuses_cross_context_and_tampered_or_equivalent_types(defaults_operator, monkeypatch):
    result = capture(scenario(defaults_operator, monkeypatch))
    assert "8.7" not in repr(result) and result.numeric.view.financial.financial.name not in repr(result)
    with pytest.raises(FrozenInstanceError): result.rounded_value = 0
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    for changes in (dict(numeric=None), dict(target=("header", "other", "grand_total")),
            dict(owner_document=True), dict(cache=((ABSENT, ABSENT), ("int", "2"))),
            dict(method=replace(result.method, erp_major=15))):
        with pytest.raises(selected.FieldRoundingAccessError): replace(result, **changes)
    with pytest.raises(selected.FieldRoundingAccessError): result.require_result_match(Decimal("8.7"))
    object.__setattr__(result, "rounded_value", 0.0)
    with pytest.raises(selected.FieldRoundingAccessError): result.require_result_match(0.0)


def test_old_numeric_capture_does_not_consume_owner_precision_or_system_setting(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.invoice._precision = object()
    defaults_operator.denied.add(("System Settings", "System Settings"))
    assert case.service.capture_numeric_context(case.invoice.name, erp_major=16).view.stage == "SAVED"
    case.round_metadata.assert_not_called()
    case.round_cache.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
def test_null_is_rounded_to_zero_without_changing_saved_native_value(defaults_operator, monkeypatch, major):
    case = scenario(defaults_operator, monkeypatch, value="Commercial Rounding")
    case.data.records["header"][0]["grand_total"] = case.invoice.grand_total = None
    result = capture(case, major)
    result.require_result_match(0.0)
    assert case.invoice.grand_total is None
    with pytest.raises(selected.FieldRoundingAccessError): result.require_result_match(-0.0)
    with pytest.raises(selected.FieldRoundingAccessError): result.require_result_match(0)
    object.__setattr__(result, "rounded_value", -0.0)
    with pytest.raises(selected.FieldRoundingAccessError): result.require_result_match(-0.0)


@pytest.mark.parametrize("value,missing", [(None, False), ("", False), (None, True)])
def test_empty_or_absent_method_retains_native_witness_with_legacy_fallback(defaults_operator, monkeypatch, value, missing):
    case = scenario(defaults_operator, monkeypatch, value=value, missing=missing)
    result = capture(case)
    assert result.method.origin == "LEGACY_DEFAULT"
    assert result.method.rounding.stored is not missing
    result.require_result_match(8.7)


@pytest.mark.parametrize("malformed", [None, {"main": None}, {"main": []}, []])
def test_malformed_owner_cache_is_not_ignored(defaults_operator, monkeypatch, malformed):
    case = scenario(defaults_operator, monkeypatch)
    case.invoice._precision = malformed
    with pytest.raises(InspectionFailed): capture(case)
    case.factory.assert_not_called()
    assert case.invoice._precision is malformed


@pytest.mark.parametrize("major", [15, 16])
def test_missing_v16_currency_precision_does_not_guess_uncaptured_formats(defaults_operator, monkeypatch, major):
    case = scenario(defaults_operator, monkeypatch)
    case.database.defaults = [default_row(value="")]
    case.cache.return_value = {"currency_precision": ""}
    if major == 15:
        capture(case, major).require_result_match(8.7)
    else:
        with pytest.raises(InspectionFailed): capture(case, major)
        one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    case.invoice.precision.assert_not_called()


@pytest.mark.parametrize("parent_kind", ["global", "user"])
def test_non_site_scope_cannot_supply_financial_rounding_defaults(defaults_operator, monkeypatch, parent_kind):
    case = scenario(defaults_operator, monkeypatch, parent_kind=parent_kind)
    with pytest.raises(InspectionFailed): capture(case)
    for callback in (case.factory, case.cache, case.metadata_provider, case.round_metadata): callback.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
def test_float_precision_does_not_acquire_unused_currency_fallback(defaults_operator, monkeypatch, major):
    case = scenario(defaults_operator, monkeypatch)
    case.database.defaults = [default_row(value="")]
    case.cache.return_value = {"currency_precision": ""}
    case.invoice._precision = {"items": {"qty": 3}}
    result = capture(case, major, ("items", "items-1", "qty"))
    assert result.precision.precision == 3
    result.require_result_match(1.0)


@pytest.mark.parametrize("interrupted", [KeyboardInterrupt, SystemExit])
def test_method_callback_interrupt_retains_cleanup_and_is_not_a_popup(defaults_operator, monkeypatch, interrupted):
    case = scenario(defaults_operator, monkeypatch)
    case.round_cache.side_effect = interrupted
    with pytest.raises(interrupted): capture(case)
    case.database.close.assert_called_once()
    assert defaults_operator.runtime.message_log == ["EXISTING-PARENT-MESSAGE"]
