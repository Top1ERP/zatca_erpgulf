"""Declared control plans versus installed15/pinned16, using synthetic data."""

import ast
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, FloatOperation, localcontext
import hashlib
import inspect
import json
from pathlib import Path
import pickle
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from frappe.utils import data as framework_data

from zatca_erpgulf.zatca_erpgulf import rounded_total_control as policy
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_settings_observation import scenario, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import erp_major, case

ERP16_COMMIT = "ade850bbd6a7412e9994a9637d2c5c713771632a"


@pytest.fixture(scope="module")
def erp16():
    record = json.loads(Path(__file__).with_name("erpnext16_rounded_total_oracle.json").read_text())
    assert record["commit"] == ERP16_COMMIT
    assert "GNU GENERAL PUBLIC LICENSE" in record["license"] and "Version 3" in record["license"]
    assert hashlib.sha256(record["license"].encode()).hexdigest() == record["files"]["license.txt"]["sha256"]
    namespace = {}
    for data in record["files"].values():
        for name, source in data.get("excerpts", {}).items():
            exec(compile(source, "pinned-erpnext16/" + name, "exec"), namespace)
    return record, namespace


def declaration(case, *, flag=0, global_flag=1, profile_flag=1, has_flag=True,
        rounded_field=True, adjustment=Decimal("0.00"), fraction=Decimal("0.01"), method=None):
    # Independent invoice/Company/global/profile currencies expose wrong lookup.
    scenario(case, distinct=True)
    case.doc.disable_rounded_total = flag
    case.doc.rounding_adjustment = adjustment
    if not has_flag: case.doc.meta.fields.remove("disable_rounded_total")
    if not rounded_field: case.doc.meta.fields.remove("rounded_total")
    # Refresh the exact declared parent after changing invoice fields/presence.
    from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import capture as financial
    from zatca_erpgulf.zatca_erpgulf.issuing_settings_observation import capture_issuing_settings_observation
    case.financial = financial(case)
    case.settings = capture_issuing_settings_observation(case.financial, records={
        ("Company", case.company.name): case.company})
    case.records["Global Defaults", "Global Defaults"].disable_rounded_total = global_flag
    case.records["POS Profile", case.doc.pos_profile].disable_rounded_total = profile_flag
    case.records["Currency", case.doc.currency].smallest_currency_fraction_value = fraction
    case.records["System Settings", "System Settings"].rounding_method = method
    return capture(case)


def controller(case, erp16, monkeypatch, settings, consolidated=False):
    header = dict(json.loads(settings.settings.financial._payload)["header"])
    global_value = next(row for row in json.loads(settings._payload)["records"] if row["doctype"] == "Global Defaults")
    global_value = dict(global_value["header"])["disable_rounded_total"]
    from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _validate_scalar
    runtime = SimpleNamespace(db=SimpleNamespace(get_single_value=Mock(return_value=_validate_scalar(global_value, absent=True))))
    if case.erp_major == 15:
        import erpnext.controllers.accounts_controller as accounts
        import erpnext.controllers.taxes_and_totals as totals
        monkeypatch.setattr(accounts, "frappe", runtime)
        disable, update = AccountsController.is_rounded_total_disabled, calculate_taxes_and_totals.set_rounded_total
        monkeypatch.setattr(totals, "round_based_on_smallest_currency_fraction", Mock(return_value=Decimal("10.00")))
        monkeypatch.setattr(totals, "flt", lambda value, precision: value)
        rounded = totals.round_based_on_smallest_currency_fraction
    else:
        namespace = erp16[1]
        monkeypatch.setitem(namespace, "frappe", runtime)
        monkeypatch.setitem(namespace, "round_based_on_smallest_currency_fraction", Mock(return_value=Decimal("10.00")))
        monkeypatch.setitem(namespace, "flt", lambda value, precision: value)
        disable, update = namespace["is_rounded_total_disabled"], namespace["set_rounded_total"]
        rounded = namespace["round_based_on_smallest_currency_fraction"]
    present = {name for name, value in header.items() if value != ["absent"]}
    values = dict(disable_rounded_total=case.doc.disable_rounded_total,
        rounded_total=Decimal("9.99"), base_rounded_total=Decimal("19.98"),
        rounding_adjustment=case.doc.rounding_adjustment, base_rounding_adjustment=Decimal("0.26"),
        grand_total=Decimal("10.12"), currency=case.doc.currency, is_consolidated=consolidated)
    doc = SimpleNamespace(**values)
    doc.get = lambda name: vars(doc).get(name)
    doc.meta = SimpleNamespace(get_field=lambda name: object() if name in present else None)
    doc.precision = Mock(return_value=2)
    doc.is_rounded_total_disabled = Mock(side_effect=lambda: disable(doc))
    conversion = Mock()
    calculation = SimpleNamespace(doc=doc, _set_in_company_currency=conversion)
    return SimpleNamespace(doc=doc, run=lambda: update(calculation), disabled=lambda: disable(doc),
        global_lookup=runtime.db.get_single_value, rounded=rounded, conversion=conversion)


@pytest.mark.parametrize("flag", [None, 0, 1, False, True])
@pytest.mark.parametrize("global_flag,profile_flag", [(0, 1), (1, 0), (1, 1)])
def test_invoice_field_presence_wins_over_global_and_profile(case, erp16, monkeypatch, flag, global_flag, profile_flag):
    settings = declaration(case, flag=flag, global_flag=global_flag, profile_flag=profile_flag)
    before = settings._payload, case.financial._payload, case.doc.grand_total
    result = policy.RoundedTotalControl(settings, False)
    actual = controller(case, erp16, monkeypatch, settings)
    assert result.disabled is bool(actual.disabled()) and result.disabled is bool(flag)
    assert result.disable_origin == "INVOICE_FIELD"
    actual.global_lookup.assert_not_called()
    result.require_disable_cache_match(flag)
    assert (settings._payload, case.financial._payload, case.doc.grand_total) == before
    assert type(case.doc.grand_total) is Decimal


@pytest.mark.parametrize("global_flag", [None, 0, 1, False, True])
def test_only_absent_invoice_field_selects_global_default(case, erp16, monkeypatch, global_flag):
    settings = declaration(case, has_flag=False, global_flag=global_flag, profile_flag=1)
    result = policy.RoundedTotalControl(settings, False)
    actual = controller(case, erp16, monkeypatch, settings)
    assert result.disabled is bool(actual.disabled())
    assert result.disable_origin == "GLOBAL_DEFAULTS"
    actual.global_lookup.assert_called_once_with("Global Defaults", "disable_rounded_total")
    result.require_disable_cache_match(global_flag)


@pytest.mark.parametrize("flag,consolidated,adjustment,rounded_field", [
    (1, False, Decimal("0"), True), (0, False, Decimal("0"), True),
    (0, True, Decimal("0.13"), True), (1, True, Decimal("-0.13"), False),
    (0, True, Decimal("0"), True), (0, False, Decimal("0"), False),
])
def test_versioned_zero_and_conversion_plans_match_real_controller(case, erp16, monkeypatch, flag, consolidated, adjustment, rounded_field):
    settings = declaration(case, flag=flag, adjustment=adjustment, rounded_field=rounded_field)
    result = policy.RoundedTotalControl(settings, consolidated)
    actual = controller(case, erp16, monkeypatch, settings, consolidated)
    actual.run()
    if result.branch in ("PRESERVE_CONSOLIDATED_ADJUSTMENT", "NO_ROUNDED_TOTAL_FIELD"):
        assert actual.doc.rounded_total == Decimal("9.99")
        actual.doc.is_rounded_total_disabled.assert_not_called()
        actual.rounded.assert_not_called()
        actual.conversion.assert_not_called()
        result.require_disable_cache_match(object())
    else:
        for name in result.zero_fields: assert getattr(actual.doc, name) == 0
        if result.base_conversion_fields:
            actual.conversion.assert_called_once_with(actual.doc, list(result.base_conversion_fields))
        else:
            actual.conversion.assert_not_called()
        if result.disabled:
            actual.rounded.assert_not_called()
            assert actual.doc.base_rounding_adjustment == Decimal("0.26")
        else: actual.rounded.assert_called_once_with(Decimal("10.12"), case.doc.currency, 2)


class Route(Exception):
    pass


def fraction_oracle(case, upstream16, monkeypatch, fraction):
    class InvalidMethod(Exception): pass
    def fail(*args, **kwargs): raise InvalidMethod
    runtime = SimpleNamespace(db=SimpleNamespace(get_value=Mock(return_value=fraction)),
        get_system_settings=Mock(return_value="UNKNOWN"), InvalidRoundingMethod=InvalidMethod,
        throw=fail, _=lambda text: text)
    namespace = vars(framework_data) if case.erp_major == 15 else upstream16
    monkeypatch.setitem(namespace, "frappe", runtime)
    return namespace, runtime, InvalidMethod


@pytest.mark.parametrize("fraction", [None, 0, 0.0, Decimal("0.00"), 1, 0.05, Decimal("0.0100"),
    Decimal("1e-64"), Decimal("9" * 64 + "E+64"), 10**63, 5e-324])
def test_fraction_routing_uses_invoice_currency_and_preserves_config_scalar(case, upstream16, monkeypatch, fraction):
    settings = declaration(case, fraction=fraction)
    result = policy.RoundedTotalControl(settings, False)
    namespace, runtime, _ = fraction_oracle(case, upstream16, monkeypatch, fraction)
    def stop(route):
        def call(*args): raise Route(route)
        return call
    monkeypatch.setitem(namespace, "remainder", stop("CURRENCY_FRACTION_THEN_FIELD_PRECISION"))
    monkeypatch.setitem(namespace, "rounded", stop("WHOLE_UNIT_THEN_FIELD_PRECISION"))
    with pytest.raises(Route) as caught:
        namespace["round_based_on_smallest_currency_fraction"](10.12, "SAR", 2)
    assert result.branch == str(caught.value) and result.currency == "SAR"
    runtime.db.get_value.assert_called_once_with("Currency", "SAR", "smallest_currency_fraction_value", cache=True)
    assert result.method == "Banker's Rounding (legacy)"
    assert result.settings._payload == settings._payload


def test_nonzero_fraction_still_consumes_system_method_in_final_normalization(case, upstream16, monkeypatch):
    settings = declaration(case, fraction=Decimal("0.01"), method="UNKNOWN")
    with pytest.raises(policy.RoundedTotalControlError): policy.RoundedTotalControl(settings, False)
    namespace, runtime, invalid = fraction_oracle(case, upstream16, monkeypatch, Decimal("0.01"))
    monkeypatch.setitem(namespace, "remainder", lambda *args: 0)
    with pytest.raises(invalid): namespace["round_based_on_smallest_currency_fraction"](10.12, "SAR", 2)
    runtime.get_system_settings.assert_called_once_with("rounding_method")


@pytest.mark.parametrize("fraction", ["0.01", False, Decimal("-0.01")])
def test_unsupported_fraction_values_are_refused_without_guessing(case, fraction):
    with pytest.raises(policy.RoundedTotalControlError, match="^rounded_total_control$"):
        policy.RoundedTotalControl(declaration(case, fraction=fraction), False)


def test_unused_setting_dependencies_are_not_interpreted(case):
    settings = declaration(case, flag=1, fraction="UNKNOWN", method="UNKNOWN", global_flag="UNKNOWN")
    result = policy.RoundedTotalControl(settings, False)
    assert result.branch == "DISABLED" and result.method is None and result.currency is None
    preserved = policy.RoundedTotalControl(declaration(case, has_flag=False, adjustment=Decimal("0.12"),
        fraction="UNKNOWN", method="UNKNOWN", global_flag="UNKNOWN"), True)
    assert preserved.branch == "PRESERVE_CONSOLIDATED_ADJUSTMENT"


@pytest.mark.parametrize("value", [None, 0, 1, "0", "1"])
def test_consolidated_flag_must_be_explicit_boolean_not_guessed_from_old_snapshot(case, value):
    with pytest.raises(policy.RoundedTotalControlError): policy.RoundedTotalControl(declaration(case), value)


def test_controls_and_digest_do_not_depend_on_decimal_context_or_rewrite_amounts(case):
    settings = declaration(case, fraction=0.05)
    expected = policy.RoundedTotalControl(settings, False)
    with localcontext() as context:
        context.prec = 2
        context.traps[FloatOperation] = True
        observed = policy.RoundedTotalControl(settings, False)
    assert observed == expected and observed.sha256 == expected.sha256
    assert type(case.doc.grand_total) is Decimal


def test_source_and_cache_comparisons_keep_zero_null_bool_and_presence_distinct(case):
    result = policy.RoundedTotalControl(declaration(case, flag=0), False)
    for value in (None, False, "0", 1):
        with pytest.raises(policy.RoundedTotalControlError, match="^rounded_total_disable_cache_mismatch$"):
            result.require_disable_cache_match(value)
    other = policy.RoundedTotalControl(declaration(case, flag=None), False)
    assert result.disabled == other.disabled and result.sha256 != other.sha256
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    with pytest.raises(FrozenInstanceError): result.branch = "DISABLED"
    with pytest.raises(policy.RoundedTotalControlError): replace(result, settings=object())
    object.__setattr__(result, "disabled", True)
    with pytest.raises(policy.RoundedTotalControlError): result.require_disable_cache_match(0)


def test_absent_global_control_is_not_invented_as_zero_when_it_is_required(case):
    declaration(case, has_flag=False)
    case.records["Global Defaults", "Global Defaults"].meta.fields.remove("disable_rounded_total")
    with pytest.raises(policy.RoundedTotalControlError): policy.RoundedTotalControl(capture(case), False)


def test_missing_rounded_field_bypasses_unused_malformed_setting_values(case):
    result = policy.RoundedTotalControl(declaration(case, rounded_field=False,
        flag="UNKNOWN", global_flag="UNKNOWN", fraction="UNKNOWN", method="UNKNOWN"), False)
    assert result.branch == "NO_ROUNDED_TOTAL_FIELD"
    assert result.disabled is None and result.method is None and result.currency is None
    result.require_disable_cache_match(object())


def test_consolidation_guard_needs_proved_adjustment_even_if_rounded_field_is_absent(case):
    declaration(case, rounded_field=False)
    case.doc.meta.fields.remove("rounding_adjustment")
    from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import capture as financial
    from zatca_erpgulf.zatca_erpgulf.issuing_settings_observation import capture_issuing_settings_observation
    case.financial = financial(case)
    case.settings = capture_issuing_settings_observation(case.financial, records={("Company", case.company.name): case.company})
    with pytest.raises(policy.RoundedTotalControlError): policy.RoundedTotalControl(capture(case), True)


def test_returns_keep_negative_financial_values_without_changing_the_control_rule(case):
    normal = policy.RoundedTotalControl(declaration(case), False)
    case.doc.is_return, case.doc.grand_total = 1, Decimal("-10.12")
    returned = policy.RoundedTotalControl(declaration(case), False)
    assert returned.branch == normal.branch and returned.currency == normal.currency
    assert returned.sha256 != normal.sha256
    assert case.doc.grand_total == Decimal("-10.12") and type(case.doc.grand_total) is Decimal


def test_backend_pos_copy_lists_do_not_override_final_invoice_disable_flag(erp16):
    from erpnext.accounts.doctype.pos_invoice.pos_invoice import POSInvoice
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
    record = erp16[0]
    for method, filename in ((POSInvoice.set_pos_fields, "erpnext/accounts/doctype/pos_invoice/pos_invoice.py"),
            (SalesInvoice.set_pos_fields, "erpnext/accounts/doctype/sales_invoice/sales_invoice.py")):
        source = textwrap.dedent(inspect.getsource(method))
        loops = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name) and node.target.id == "fieldname"
            and isinstance(node.iter, (ast.Tuple, ast.List))]
        fields = next(ast.literal_eval(node.iter) for node in loops if "apply_discount_on" in ast.literal_eval(node.iter))
        assert "disable_rounded_total" not in fields
        assert "disable_rounded_total" not in record["files"][filename]["pos_copy_fields"]
        assert "currency" in fields and "currency" in record["files"][filename]["pos_copy_fields"]


@pytest.mark.parametrize("profile_flag", [None, 0, 1, "0", "1"])
def test_pos_merge_assignment_is_a_separate_input_step_before_final_invoice_controls(case, erp16, profile_flag):
    filename = "erpnext/accounts/doctype/pos_invoice_merge_log/pos_invoice_merge_log.py"
    if case.erp_major == 16:
        snippet = erp16[0]["files"][filename]["merge_disable_assignment"]
    else:
        import erpnext
        source = (Path(erpnext.__file__).parent.parent / filename).read_text()
        node = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Attribute) and target.attr == "disable_rounded_total" for target in node.targets))
        snippet = ast.get_source_segment(source, node)
    invoice = SimpleNamespace(pos_profile="SYNTHETIC-POS")
    lookup = Mock(return_value=profile_flag)
    exec(compile(snippet, "synthetic-pos-merge-assignment", "exec"), dict(invoice=invoice,
        cint=framework_data.cint, frappe=SimpleNamespace(db=SimpleNamespace(get_value=lookup))))
    lookup.assert_called_once_with("POS Profile", "SYNTHETIC-POS", "disable_rounded_total")
    settings = declaration(case, flag=invoice.disable_rounded_total, profile_flag=profile_flag,
        global_flag=1, adjustment=Decimal("0"))
    result = policy.RoundedTotalControl(settings, True)
    assert result.disabled is bool(framework_data.cint(profile_flag))
    assert result.disable_origin == "INVOICE_FIELD"
