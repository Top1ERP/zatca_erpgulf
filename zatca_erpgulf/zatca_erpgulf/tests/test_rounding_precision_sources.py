"""Precision reuse after checked sources, with independently validating APIs."""

from dataclasses import replace

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_format_access as formats
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _child_type
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import scenario, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding_formats import scenario as format_case, target
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator, untouched


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("child", [False, True])
def test_checked_kernel_matches_independent_financial_precision(defaults_operator, monkeypatch, major, doctype, child):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype)
    selected = ("items", "items-1", "amount") if child else (None, None, "grand_total")
    result = capture(case, major, selected)
    fieldtype = _child_type(doctype, "items") if child else doctype
    expected = result.numeric.financial.resolve_precision(fieldtype, selected[2])
    assert result.precision == expected and result.precision.sha256 == expected.sha256
    assert result.precision.metadata._payload == expected.metadata._payload
    assert result.precision.defaults._payload == expected.defaults._payload
    assert case.factory.call_count == 1
    untouched(defaults_operator, case)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scope", ["invoice", "company"])
@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("cached", [False, True])
def test_checked_format_precision_and_cache_match_independent_apis(defaults_operator, monkeypatch,
        doctype, scope, child, cached):
    case = format_case(defaults_operator, monkeypatch, doctype=doctype, scope=scope)
    selected = target(scope, child)
    currency = "SAR" if scope == "company" else "USD"
    if cached:
        defaults_operator.runtime.local.field_currency = {(doctype, case.invoice.name): {selected[2]: currency}}
    result = capture(case, target=selected)
    expected = result.formats.resolve_precision(selected[2], parentfield=selected[0])
    assert result.precision == expected and result.precision.sha256 == expected.sha256
    result.formats.require_field_currency_match(selected[2], currency, parentfield=selected[0])
    assert result.formats.financial == result.numeric.financial
    assert case.factory.call_count == 1
    untouched(defaults_operator, case)


def test_independent_financial_precision_rechecks_after_an_earlier_success(defaults_operator, monkeypatch):
    result = capture(scenario(defaults_operator, monkeypatch))
    financial = replace(result.numeric.financial)
    financial.resolve_precision("Sales Invoice", "grand_total")
    object.__setattr__(financial.financial, "sha256", "f" * 64)
    with pytest.raises(access.CalculationDefaultsAccessError) as caught:
        financial.resolve_precision("Sales Invoice", "grand_total")
    assert str(caught.value) == "calculation_financial_precision" and caught.value.__context__ is None


def test_independent_format_apis_recheck_after_an_earlier_success(defaults_operator, monkeypatch):
    result = capture(format_case(defaults_operator, monkeypatch))
    source = replace(result.formats)
    source.resolve_precision("grand_total")
    source.require_field_currency_match("grand_total", source.formats.currency)
    object.__setattr__(source.formats, "sha256", "f" * 64)
    for operation in (lambda: source.resolve_precision("grand_total"),
            lambda: source.require_field_currency_match("grand_total", source.formats.currency)):
        with pytest.raises(formats.CalculationFormatAccessError) as caught:
            operation()
        assert caught.value.__context__ is None
