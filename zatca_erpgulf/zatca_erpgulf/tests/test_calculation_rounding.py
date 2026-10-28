"""Rounding selection versus actual15/pinned16 helpers, with synthetic inputs."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import math
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from frappe.utils import data as framework_data

from zatca_erpgulf.zatca_erpgulf import calculation_rounding as policy
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_settings_observation import scenario, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import erp_major, case


class UnknownMethod(Exception):
    pass


def declaration(case, value=None, *, present=True):
    scenario(case, pos=False)
    system = case.records["System Settings", "System Settings"]
    system.rounding_method = value
    if not present:
        system.meta.fields.remove("rounding_method")
    return capture(case)


def oracle(major, upstream16, monkeypatch, setting, *, probes):
    def fail(*args, **kwargs):
        raise UnknownMethod
    runtime = SimpleNamespace(get_system_settings=Mock(return_value=setting),
        throw=fail, InvalidRoundingMethod=UnknownMethod, _=lambda text: text)
    if major == 15:
        monkeypatch.setattr(framework_data, "frappe", runtime)
        namespace = vars(framework_data)
    else:
        namespace = upstream16
        monkeypatch.setitem(namespace, "frappe", runtime)
        monkeypatch.setitem(namespace, "math", math)
    if probes:
        for name, method in (("_bankers_rounding", "Banker's Rounding"),
                ("_bankers_rounding_legacy", policy.LEGACY_METHOD),
                ("_round_away_from_zero", "Commercial Rounding")):
            monkeypatch.setitem(namespace, name, lambda *args, method=method: method)
    return namespace["rounded"], runtime


@pytest.mark.parametrize("setting", [None, "", *sorted(policy.METHODS)])
@pytest.mark.parametrize("override", [None, "", *sorted(policy.METHODS)])
def test_selection_and_system_lookup_precedence_match_actual_framework(case, upstream16, monkeypatch, setting, override):
    observed = declaration(case, setting)
    before = observed._payload, observed.sha256, case.financial._payload, case.doc.grand_total
    result = policy.RoundingMethodResolution(observed, override)
    rounded, runtime = oracle(case.erp_major, upstream16, monkeypatch, setting, probes=True)
    assert result.method == rounded(1.25, 1, override)
    assert result.erp_major == case.erp_major
    assert result.uses_system_setting is (not bool(override))
    assert runtime.get_system_settings.call_count == (0 if override else 1)
    assert result.origin == ("EXPLICIT_OVERRIDE" if override else "SYSTEM_SETTING" if setting else "LEGACY_DEFAULT")
    assert result.settings == observed and result.settings is not observed
    assert (observed._payload, observed.sha256, case.financial._payload, case.doc.grand_total) == before
    assert type(case.doc.grand_total) is Decimal
    result.require_system_cache_match(object() if override else setting)
    for record in case.records.values():
        record.save.assert_not_called()
        record.db_set.assert_not_called()


@pytest.mark.parametrize("present,value,tag", [(False, None, ("absent",)), (True, None, ("null",)), (True, "", ("str", ""))])
def test_missing_null_and_blank_keep_distinct_source_evidence_with_same_fallback(case, present, value, tag):
    result = policy.RoundingMethodResolution(declaration(case, value, present=present))
    assert result.method == policy.LEGACY_METHOD and result.system_setting == tag
    result.require_system_cache_match(value)
    with pytest.raises(policy.RoundingMethodError, match="^calculation_rounding_cache_mismatch$"):
        result.require_system_cache_match("" if value is None else None)


def test_presence_and_override_origin_change_identity_without_rewriting_old_settings(case):
    absent = policy.RoundingMethodResolution(declaration(case, present=False))
    null = policy.RoundingMethodResolution(declaration(case))
    blank = policy.RoundingMethodResolution(declaration(case, ""))
    explicit = policy.RoundingMethodResolution(blank.settings, policy.LEGACY_METHOD)
    assert len({result.sha256 for result in (absent, null, blank, explicit)}) == 4
    assert len({result.method for result in (absent, null, blank, explicit)}) == 1
    assert blank.settings._payload == explicit.settings._payload


@pytest.mark.parametrize("setting,override", [("UNKNOWN-PRIVATE", None), (None, "UNKNOWN-PRIVATE"),
    (" banker's rounding ", None), ("0", None)])
def test_unknown_methods_are_rejected_like_framework_without_exposing_values(case, upstream16, monkeypatch, setting, override):
    rounded, _ = oracle(case.erp_major, upstream16, monkeypatch, setting, probes=True)
    with pytest.raises(UnknownMethod): rounded(1.25, 1, override)
    with pytest.raises(policy.RoundingMethodError) as caught:
        policy.RoundingMethodResolution(declaration(case, setting), override)
    assert str(caught.value) == "calculation_rounding_method" and caught.value.__context__ is None


@pytest.mark.parametrize("value", [False, 0, 2, Decimal("0"), [], {}, "X" * 4097, "PRIVATE\0VALUE"])
def test_invalid_override_types_and_bounds_are_not_coerced_to_defaults(case, value):
    with pytest.raises(policy.RoundingMethodError, match="^calculation_rounding_method$"):
        policy.RoundingMethodResolution(declaration(case), value)


@pytest.mark.parametrize("value", [False, 0, Decimal("0"), "UNKNOWN-PRIVATE"])
def test_override_does_not_consume_or_attest_unused_system_setting(case, value):
    observed = declaration(case, value)
    result = policy.RoundingMethodResolution(observed, "Commercial Rounding")
    result.require_system_cache_match(object())
    assert not result.uses_system_setting
    with pytest.raises(policy.RoundingMethodError): policy.RoundingMethodResolution(observed)


@pytest.mark.parametrize("cached", [None, "", "Commercial Rounding", False, 0])
def test_consumed_system_cache_is_compared_exactly_even_if_method_would_match(case, cached):
    result = policy.RoundingMethodResolution(declaration(case, policy.LEGACY_METHOD))
    with pytest.raises(policy.RoundingMethodError, match="^calculation_rounding_cache_mismatch$"):
        result.require_system_cache_match(cached)


def test_reconstruction_detects_tampering_and_protects_representation(case):
    result = policy.RoundingMethodResolution(declaration(case))
    assert "SYNTHETIC" not in repr(result)
    with pytest.raises(FrozenInstanceError): result.method = "Commercial Rounding"
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    with pytest.raises(policy.RoundingMethodError): replace(result, settings=object())
    object.__setattr__(result, "origin", "SYSTEM_SETTING")
    with pytest.raises(policy.RoundingMethodError, match="^calculation_rounding_cache_mismatch$"):
        result.require_system_cache_match(None)


@pytest.mark.parametrize("num,precision,expected", [
    (2.5, 0, (2, 2, 3)), (-2.5, 0, (-2, -2, -3)),
    (1.25, 1, (1.2, 1.3, 1.3)), (-1.25, 1, (-1.2, -1.2, -1.3)),
])
def test_real_helper_ties_explain_why_methods_cannot_be_replaced_by_one_decimal_rule(case, upstream16, monkeypatch, num, precision, expected):
    rounded, runtime = oracle(case.erp_major, upstream16, monkeypatch, None, probes=False)
    actual = tuple(rounded(num, precision, method) for method in
        ("Banker's Rounding", policy.LEGACY_METHOD, "Commercial Rounding"))
    assert actual == expected
    runtime.get_system_settings.assert_not_called()


def test_same_method_name_does_not_imply_identical_versioned_amount_algorithms(case, upstream16, monkeypatch):
    rounded, _ = oracle(case.erp_major, upstream16, monkeypatch, None, probes=False)
    # Synthetic IEEE-754 boundary probe, not a valid-invoice/range assertion.
    expected = 9007199254740992 if case.erp_major == 15 else 9007199254740991
    assert rounded(9007199254740991.0, 0, "Banker's Rounding") == expected
