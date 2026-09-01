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
