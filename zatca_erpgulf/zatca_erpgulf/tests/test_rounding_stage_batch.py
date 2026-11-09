"""Checked shared-stage reconstruction; no shortcuts for supplied evidence."""

from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_rounding_stage as stages
from zatca_erpgulf.zatca_erpgulf.calculation_field_rounding_access import SavedFieldRoundingRead
from zatca_erpgulf.zatca_erpgulf.calculation_numeric_access import SavedFinancialNumericRead
from zatca_erpgulf.zatca_erpgulf.calculation_field_rounding_access import _result_tag
from zatca_erpgulf.zatca_erpgulf.tests.test_rounding_stage import scenario, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator, untouched


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("child", [False, True])
def test_stage_matches_independent_field_constructors_and_owns_fresh_sources(defaults_operator, monkeypatch,
        major, doctype, child):
    case = scenario(defaults_operator, monkeypatch, doctype=doctype)
    source = capture(case, major, names=("amount", "net_amount") if child else ("grand_total", "net_total"), child=child)
    pinned = stages.pin_stage(source)
    for supplied, field in zip(source.fields, pinned.fields):
        independent = SavedFieldRoundingRead(supplied.numeric, supplied.method, supplied.target,
            supplied.owner_document, supplied.cache, supplied.formats, supplied.currency_cache, supplied.company_cache)
        assert field == independent and field.precision.sha256 == independent.precision.sha256
        assert _result_tag(field.rounded_value) == _result_tag(independent.rounded_value)
        assert field.numeric is pinned.numeric and field.method is pinned.method
        assert field is not supplied and field.numeric is not supplied.numeric
    assert case.factory.call_count == 1
    untouched(defaults_operator, case)


@pytest.mark.parametrize("fault", ["numeric_digest", "method_major", "metadata_flag", "tables", "owner",
    "precision_type", "result_type", "precision_slot", "unused_currency_cache", "target"])
def test_a_sibling_cannot_substitute_changed_sources_types_or_results(defaults_operator, monkeypatch, fault):
    source = capture(scenario(defaults_operator, monkeypatch))
    field = replace(source.fields[0])  # Independent ordinary constructor first.
    if fault == "numeric_digest": object.__setattr__(field.numeric.view, "sha256", "f" * 64)
    elif fault == "method_major": object.__setattr__(field.method, "erp_major", 16.0)
    elif fault == "metadata_flag":
        metadata = field.numeric.view.financial.metadata[0].applied
        object.__setattr__(metadata, "issingle", int(metadata.issingle))
    elif fault == "tables": object.__setattr__(field.numeric, "tables", tuple(reversed(field.numeric.tables)))
    elif fault == "owner": object.__setattr__(field, "owner_document", True)
    elif fault == "precision_type": object.__setattr__(field.precision, "precision", float(field.precision.precision))
    elif fault == "result_type": object.__setattr__(field, "rounded_value", Decimal(str(field.rounded_value)))
    elif fault == "precision_slot": object.__setattr__(field, "cache", (field.cache[0], ("int", "9")))
    elif fault == "unused_currency_cache": object.__setattr__(field, "currency_cache", ("str", "SAR"))
    else: object.__setattr__(field, "target", ("header", "OTHER", "grand_total"))
    with pytest.raises(stages.RoundingStageError) as caught:
        replace(source, fields=(field, *source.fields[1:]))
    assert str(caught.value) == "rounding_stage_result" and caught.value.__context__ is None


def test_root_is_revalidated_on_every_new_stage_pin(defaults_operator, monkeypatch):
    source = capture(scenario(defaults_operator, monkeypatch))
    stages.pin_stage(source)
    object.__setattr__(source.numeric.view.financial, "sha256", "f" * 64)
    with pytest.raises(stages.RoundingStageError): stages.pin_stage(source)


def test_derived_metadata_cache_is_rebuilt_without_repairing_the_supplied_object(defaults_operator, monkeypatch):
    source = capture(scenario(defaults_operator, monkeypatch))
    native = source.numeric.view.financial
    metadata = next(row.applied for row in native.metadata if row.applied.name == native.financial.doctype)
    definition = metadata.get_field("grand_total")
    original = definition.get("precision")
    object.__setattr__(definition, "_values", MappingProxyType(dict(definition._values, precision=99)))
    pinned = stages.pin_stage(source)
    fresh = next(row.applied for row in pinned.numeric.view.financial.metadata if row.applied.name == metadata.name)
    assert fresh.get_field("grand_total").get("precision") == original
    assert definition.get("precision") == 99
    assert pinned.fields[0].precision.precision == source.fields[0].precision.precision


def test_float_zero_sign_is_checked_after_recomputation(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    case.invoice.grand_total = case.data.records["header"][0]["grand_total"] = Decimal("0.000000000")
    source = capture(case)
    field = replace(source.fields[0])
    assert type(field.rounded_value) is float and field.rounded_value == 0.0
    object.__setattr__(field, "rounded_value", -field.rounded_value)
    with pytest.raises(stages.RoundingStageError): replace(source, fields=(field, *source.fields[1:]))


def test_complete_stage_reconstructs_one_numeric_root(defaults_operator, monkeypatch):
    source = capture(scenario(defaults_operator, monkeypatch))
    calls = []
    original = SavedFinancialNumericRead.__post_init__
    def count(value):
        calls.append(True)
        return original(value)
    monkeypatch.setattr(SavedFinancialNumericRead, "__post_init__", count)
    stages.pin_stage(source)
    assert calls == [True]
