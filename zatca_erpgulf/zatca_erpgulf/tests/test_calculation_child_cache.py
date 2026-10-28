"""Selected real-shaped local cache inspection; synthetic saved objects only."""

from copy import deepcopy
from dataclasses import replace
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_child_cache as cache
from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access import scenario
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, untouched, one_failure, InspectionFailed, PermissionDenied,
)


def capture(case, major=15):
    return case.service.capture_child_cached_context(case.invoice.name, "items", "items-1", "amount",
        doctype=case.invoice.doctype, erp_major=major)


def documents(case):
    return case.saved["items", "items-1"], case.refs["items"][0]


def set_currency(operator, case, row_value="EUR", parent_value=None):
    dt = case.data.own.applied.name
    values = {(dt, "items-1"): {"amount": row_value}}
    if parent_value is not None: values[dt, case.invoice.name] = {"amount": parent_value}
    operator.runtime.local.field_currency = values
    return values


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", [False, True])
def test_snapshot_preserves_absence_or_existing_slots_without_calling_precision(defaults_operator, monkeypatch, major, present):
    case = scenario(defaults_operator, monkeypatch)
    direct, reference = documents(case)
    for doc in (direct, reference): doc.precision = Mock(side_effect=AssertionError("must not populate cache"))
    if present:
        values = set_currency(defaults_operator, case)
        for doc in (direct, reference): doc._precision = {"main": {"amount": 2}, "unrelated": {"secret": "UNSELECTED"}}
        before = deepcopy(values)
    result = capture(case, major)
    assert type(result) is cache.SavedChildCacheRead
    assert result.resolve_currency().currency == "EUR" and result.resolve_precision().precision == 2
    assert result.precisions == ((("int", "2"),) * 2 if present else (cache.ABSENT,) * 2)
    assert result.documents == (id(direct), id(reference))
    if present: assert defaults_operator.runtime.local.field_currency == before
    else:
        assert not hasattr(defaults_operator.runtime.local, "field_currency")
        assert all("_precision" not in vars(doc) for doc in (direct, reference))
    for doc in (direct, reference): doc.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("fault", ["wrong_currency", "blocked_null", "blocked_blank", "numeric_bool", "numeric_text", "numeric_stale", "null_precision", "null_bucket"])
def test_stale_or_malformed_caches_are_refused_without_repair(defaults_operator, monkeypatch, fault):
    case = scenario(defaults_operator, monkeypatch)
    direct, reference = documents(case)
    if fault.startswith("numeric"):
        direct._precision = {"main": {"amount": True if fault == "numeric_bool" else "2" if fault == "numeric_text" else 3}}
    elif fault == "null_precision": reference._precision = None
    elif fault == "null_bucket": direct._precision = {"main": None}
    else:
        dt = case.data.own.applied.name
        defaults_operator.runtime.local.field_currency = {(dt, case.invoice.name): {"amount":
            "SAR" if fault == "wrong_currency" else None if fault == "blocked_null" else ""}}
    before = deepcopy(getattr(defaults_operator.runtime.local, "field_currency", None))
    with pytest.raises(InspectionFailed): capture(case)
    assert getattr(defaults_operator.runtime.local, "field_currency", None) == before
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    assert case.database.close.call_count == 1


@pytest.mark.parametrize("boundary", ["defaults_second", "metadata_last", "close"])
@pytest.mark.parametrize("change", ["valid_warmup", "stale", "precision", "replace"])
def test_selected_cache_drift_is_rejected_even_when_new_values_are_numerically_correct(defaults_operator, monkeypatch, boundary, change):
    case = scenario(defaults_operator, monkeypatch)
    set_currency(defaults_operator, case)
    def mutate():
        dt = case.data.own.applied.name
        if change == "valid_warmup": documents(case)[0]._precision = {"main": {"amount": 2}}
        elif change == "precision": documents(case)[1]._precision = {"main": {"amount": 3}}
        elif change == "replace": defaults_operator.runtime.local.field_currency = deepcopy(defaults_operator.runtime.local.field_currency)
        else: defaults_operator.runtime.local.field_currency[dt, "items-1"]["amount"] = "SAR"
    if boundary == "close": case.database.close.side_effect = mutate
    else:
        provider = case.cache if boundary == "defaults_second" else case.metadata_provider
        original = provider.side_effect or (lambda *args: provider.return_value)
        def read(*args):
            result = original(*args)
            if provider.call_count == (2 if boundary == "defaults_second" else 4): mutate()
            return result
        provider.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)


def test_unrelated_cache_slots_and_parent_doctype_are_not_selected(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    defaults_operator.runtime.local.field_currency = {(case.invoice.doctype, case.invoice.name): {"amount": "OTHER"},
        (case.data.own.applied.name, "OTHER-ROW"): {"amount": "PRIVATE-UNSELECTED"}}
    result = capture(case)
    assert result.currencies == (cache.ABSENT, cache.ABSENT)
    assert "PRIVATE" not in repr(result)


def test_no_cache_sampling_precedes_normal_read(defaults_operator, monkeypatch):
    case = scenario(defaults_operator, monkeypatch)
    defaults_operator.runtime.local.field_currency = object()
    defaults_operator.denied.add((case.data.own.applied.name, "items-1"))
    with pytest.raises(PermissionDenied): capture(case)
    case.factory.assert_not_called()
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)


def test_protected_observation_reconstruction_does_not_accept_invented_slots(defaults_operator, monkeypatch):
    result = capture(scenario(defaults_operator, monkeypatch))
    with pytest.raises(cache.CalculationChildAccessError): replace(result, currencies=(("str", "SAR"), cache.ABSENT))
    with pytest.raises(cache.CalculationChildAccessError): replace(result, precisions=(("int", "3"), cache.ABSENT))
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
