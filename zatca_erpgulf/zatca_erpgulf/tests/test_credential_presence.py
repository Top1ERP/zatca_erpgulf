"""Pure field-shape observations; no framework, credential parsing or resources."""

from types import MappingProxyType

import pytest

from zatca_erpgulf.zatca_erpgulf.credential_presence import classify_saved_credential_presence as classify


FIELDS = ("custom_first", "custom_second")


class Opaque:
    def __str__(self):
        raise AssertionError("No private value coercion")

    def __bool__(self):
        raise AssertionError("No private value truth test")


@pytest.mark.parametrize("value,status", [(None, "EMPTY"), ("", "EMPTY"), (" ", "PRESENT"),
    ("********", "PRESENT"), ("INVALID-TEST-MATERIAL", "PRESENT"), ("اختبار", "PRESENT"),
    (False, "UNKNOWN"), (True, "UNKNOWN"), (0, "UNKNOWN"), (1, "UNKNOWN"),
    (b"", "UNKNOWN"), ([], "UNKNOWN"), ({}, "UNKNOWN"), pytest.param(Opaque(), "UNKNOWN", id="opaque")])
@pytest.mark.parametrize("field", FIELDS)
def test_literal_presence_does_not_parse_normalize_or_copy_material(value, status, field):
    values = dict.fromkeys(FIELDS)
    values[field] = value
    assert classify(values, FIELDS) == status
    assert values[field] is value


@pytest.mark.parametrize("fields", [None, [], (), ("duplicate", "duplicate"), ("",), (" a",),
    ("a-b",), ("عربي",), ("x" * 141,), (None,), tuple("field_" + str(i) for i in range(17))])
def test_unbounded_or_unsupported_registry_is_unknown(fields):
    assert classify({}, fields) == "UNKNOWN"


@pytest.mark.parametrize("values", [None, [], {}, {"custom_first": None},
    {"custom_first": None, "custom_second": None, "extra": None},
    {"custom_first": None, 1: None}, MappingProxyType(dict.fromkeys(FIELDS))])
def test_only_an_exact_app_owned_projection_is_accepted(values):
    assert classify(values, FIELDS) == "UNKNOWN"


def test_dict_subclasses_are_not_used_as_lazy_credential_projections():
    class Lazy(dict):
        def values(self):
            raise AssertionError("No unowned projection traversal")
    assert classify(Lazy.fromkeys(FIELDS), FIELDS) == "UNKNOWN"


def test_unknown_state_is_not_hidden_by_another_present_field():
    assert classify({"custom_first": "TEST-PRESENT", "custom_second": Opaque()}, FIELDS) == "UNKNOWN"
