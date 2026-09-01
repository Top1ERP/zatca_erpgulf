from types import SimpleNamespace
from unittest.mock import patch

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_value, get_compat_value


class _Meta:
    def __init__(self, fields):
        self.fields = set(fields)

    def get_field(self, fieldname):
        return object() if fieldname in self.fields else None


class _Doc(SimpleNamespace):
    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)


def _doc(fields, **values):
    return _Doc(doctype="Customer", meta=_Meta(fields), **values)


def test_primary_alias_wins_even_when_false():
    doc = _doc({"custom_b2c", "b2c"}, custom_b2c=0, b2c=1)
    with patch("zatca_erpgulf.ksa_compliance.field_compat.field_exists", return_value=True):
        assert get_alias_value("customer_b2c", doc, 9) == 0


def test_legacy_alias_is_used_when_primary_absent():
    doc = _doc({"b2c"}, b2c=1)
    def exists(doctype, fieldname):
        return fieldname == "b2c"
    with patch("zatca_erpgulf.ksa_compliance.field_compat.field_exists", side_effect=exists):
        assert get_alias_value("customer_b2c", doc, 0) == 1


def test_missing_alias_returns_default():
    doc = _doc(set())
    with patch("zatca_erpgulf.ksa_compliance.field_compat.field_exists", return_value=False):
        assert get_compat_value(doc, ("missing_a", "missing_b"), "fallback") == "fallback"


def test_unn_alias_group_preserves_primary_priority():
    doc = _doc({"custom_unified_national_number", "unn"}, custom_unified_national_number="", unn="7123456789")
    with patch("zatca_erpgulf.ksa_compliance.field_compat.field_exists", return_value=True):
        assert get_alias_value("customer_unn", doc, "fallback") == ""


def test_unn_validation_allows_blank_and_validates_supplied_saudi_value():
    from zatca_erpgulf.zatca_erpgulf import customer_validation

    customer = _doc({"custom_unified_national_number"}, custom_unified_national_number="7123456789")
    with patch.object(customer_validation, "_", side_effect=lambda message: message), patch.object(
        customer_validation, "_customer_country", return_value="SA"
    ), patch.object(
        customer_validation, "get_alias_value", side_effect=lambda key, doc, default=None: {
            "customer_unn": doc.get("custom_unified_national_number", default),
            "customer_b2c": 1,
        }.get(key, default),
    ):
        assert customer_validation._buyer_errors(customer, {"phase": "Phase-2", "enabled": False}) == ([], [])

        customer.custom_unified_national_number = "6123456789"
        errors, warnings = customer_validation._buyer_errors(customer, {"phase": "Phase-2", "enabled": False})
        assert errors and "UNN (700)" in errors[0]
        assert warnings == []

        customer.custom_unified_national_number = ""
        assert customer_validation._buyer_errors(customer, {"phase": "Phase-2", "enabled": False}) == ([], [])
