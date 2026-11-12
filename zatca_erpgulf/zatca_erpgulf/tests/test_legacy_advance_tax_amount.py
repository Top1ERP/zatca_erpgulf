"""Legacy mixed-number repair and unchanged native arithmetic, without I/O."""

from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext
import math

import pytest

from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as core
from zatca_erpgulf.zatca_erpgulf.tests.test_sales_item_builder_parity import source as sales_source
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_item_builder_parity import (
    advance_source, compare, compare_fixed_mixed_amount, prepare,
)


def old_amount(amount, rate):
    """The exact previous expression; no new helper is used by this oracle."""
    return abs(round(amount * rate / 100, 2))


def outcome(operation, amount, rate):
    try:
        value = operation(amount, rate)
    except Exception as error:
        return "error", type(error), str(error)
    return "value", type(value), value.hex() if type(value) is float else str(value)


# Compatible and malformed operands must keep their original value/type/error.
# Mixed finite pairs have separate literal expectations below.
COMPATIBLE_PAIRS = [
    (amount, rate)
    for amount in (0, 1, -1, 20.15, -50.005, Decimal("20.1500"), Decimal("-50.005"), None, "10", True)
    for rate in (0, 5, 15, Decimal("15"), None, "15", True)
    if not (type(amount) is float and type(rate) is Decimal)
]


@pytest.mark.parametrize("amount,rate", COMPATIBLE_PAIRS)
@pytest.mark.parametrize("rounding", [ROUND_HALF_EVEN, ROUND_HALF_UP])
def test_other_numeric_and_invalid_pairs_retain_old_behavior(amount, rate, rounding):
    with localcontext() as context:
        context.rounding = rounding
        assert outcome(core._legacy_advance_tax_amount, amount, rate) == outcome(old_amount, amount, rate)


@pytest.mark.parametrize("amount,rate,expected", [
    (Decimal("20.1500"), 15.0, "3.02"),
    (Decimal("-50.005"), 15.0, "7.50"),
    (Decimal("0"), 15.0, "0.00"),
    (Decimal("-0.00"), 15.0, "0.00"),
    (Decimal("9999999999999999.99"), 15.0, "1500000000000000.00"),
    (Decimal("1E-20"), 15.0, "0.00"),
    (Decimal("100.00"), 2.675, "2.68"),
    (Decimal("100.00"), 0.1, "0.10"),
    (20.15, Decimal("15.00"), "3.02"),
    (-50.005, Decimal("15.00"), "7.50"),
    (-0.0, Decimal("15"), "0.00"),
    (100.0, Decimal("2.675"), "2.68"),
])
def test_mixed_pairs_have_literal_decimal_results_without_float_projection(amount, rate, expected):
    before = str(amount), str(rate)
    with pytest.raises(TypeError):
        old_amount(amount, rate)
    result = core._legacy_advance_tax_amount(amount, rate)
    assert type(result) is Decimal
    assert str(result) == expected
    assert (str(amount), str(rate)) == before


@pytest.mark.parametrize("amount,rate,even,half_up", [
    (Decimal("2.685"), 100.0, "2.68", "2.69"),
    (2.685, Decimal("100"), "2.68", "2.69"),
    (Decimal("-2.685"), 100.0, "2.68", "2.69"),
])
def test_mixed_bridge_preserves_the_callers_decimal_rounding_context(amount, rate, even, half_up):
    for rounding, expected in ((ROUND_HALF_EVEN, even), (ROUND_HALF_UP, half_up)):
        with localcontext() as context:
            context.rounding = rounding
            context.prec = 28
            assert str(core._legacy_advance_tax_amount(amount, rate)) == expected
            assert context.rounding == rounding and context.prec == 28


@pytest.mark.parametrize("decimal", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity"), Decimal("1")])
@pytest.mark.parametrize("native", [float("nan"), float("inf"), -float("inf"), 15.0])
@pytest.mark.parametrize("reverse", [False, True])
def test_nonfinite_mixed_pairs_keep_original_errors(decimal, native, reverse):
    amount, rate = (native, decimal) if reverse else (decimal, native)
    if decimal.is_finite() and math.isfinite(native):
        assert str(core._legacy_advance_tax_amount(amount, rate)) == "0.15"
    else:
        assert outcome(core._legacy_advance_tax_amount, amount, rate) == outcome(old_amount, amount, rate)


@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("amount", [Decimal("20.1500"), Decimal("-50.005")])
def test_template_float_rate_and_decimal_amount_complete_xml(advance_source, currency, erp_major, amount):
    s = advance_source
    doc = prepare(s, route="legacy", currency=currency, erp_major=erp_major)
    s.template.taxes[0].tax_rate = 15.0
    s.legacy.custom_item[0].amount = amount
    compare_fixed_mixed_amount(s, doc, True, "3.02" if amount > 0 else "7.50")


@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("amount", [20.15, -50.005])
def test_template_decimal_rate_and_float_amount_complete_xml(advance_source, currency, erp_major, amount):
    s = advance_source
    doc = prepare(s, route="legacy", currency=currency, erp_major=erp_major)
    s.template.taxes[0].tax_rate = Decimal("15.00")
    s.legacy.custom_item[0].amount = amount
    compare_fixed_mixed_amount(s, doc, True, "3.02" if amount > 0 else "7.50")


@pytest.mark.parametrize("route", ["none", "direct", "both"])
@pytest.mark.parametrize("has_template", [False, True])
def test_unused_legacy_mixed_values_are_not_consumed(advance_source, route, has_template):
    s = advance_source
    doc = prepare(s, route=route)
    s.legacy.custom_item[0].amount = Decimal("NaN")
    outcome, *_ = compare(s, doc, has_template)
    assert outcome is None


@pytest.mark.parametrize("amount", [0.0, -0.0, 1.005, 2.675, -50.005, 9999999999.99, 1e-300])
@pytest.mark.parametrize("rate", [0.0, 0.1, 5.0, 15.0, 100.0, float("nan"), float("inf"), -float("inf")])
def test_existing_float_calculations_preserve_exact_bits(amount, rate):
    assert outcome(core._legacy_advance_tax_amount, amount, rate) == outcome(old_amount, amount, rate)


class FloatSubclass(float):
    def __str__(self):
        raise AssertionError("A custom float must not enter the text bridge")


class DecimalSubclass(Decimal):
    pass


@pytest.mark.parametrize("amount,rate", [
    (Decimal("1"), FloatSubclass(15)), (FloatSubclass(1), Decimal("15")),
    (DecimalSubclass("1"), 15.0), (1.0, DecimalSubclass("15")),
], ids=["float-subclass-rate", "float-subclass-amount", "decimal-subclass-amount", "decimal-subclass-rate"])
def test_custom_numeric_types_are_not_silently_coerced(amount, rate):
    assert outcome(core._legacy_advance_tax_amount, amount, rate) == outcome(old_amount, amount, rate)
