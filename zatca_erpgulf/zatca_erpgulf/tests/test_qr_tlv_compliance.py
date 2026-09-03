from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import patch

from zatca_erpgulf.zatca_erpgulf.sign_invoice_first import (
    _is_simplified_document,
    get_tlv_for_value,
)


def parse_tlv(payload):
    tag, length = payload[0], payload[1]
    return tag, length, payload[2 : 2 + length]


def test_tag6_uses_base64_utf8_text():
    digest = bytes(range(32))
    encoded = base64.b64encode(digest).decode()
    tag, length, value = parse_tlv(get_tlv_for_value(6, encoded))
    assert (tag, length, value) == (6, len(encoded), encoded.encode("utf-8"))

def test_string_tlv_length_is_utf8_byte_length():
    value = "شركة"
    tag, length, encoded = parse_tlv(get_tlv_for_value(1, value))
    assert tag == 1
    assert length == len(value.encode("utf-8"))
    assert encoded == value.encode("utf-8")


def test_standard_invoice_does_not_get_tag9():
    doc = SimpleNamespace(doctype="Sales Invoice", customer="B2B")
    with patch(
        "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.frappe.get_cached_doc",
        return_value=SimpleNamespace(custom_b2c=0),
    ):
        assert _is_simplified_document(doc) is False


def test_b2c_invoice_gets_tag9():
    doc = SimpleNamespace(doctype="Sales Invoice", customer="B2C")
    with patch(
        "zatca_erpgulf.zatca_erpgulf.sign_invoice_first.frappe.get_cached_doc",
        return_value=SimpleNamespace(custom_b2c=1),
    ):
        assert _is_simplified_document(doc) is True


def test_pos_invoice_is_simplified_without_customer_lookup():
    doc = SimpleNamespace(doctype="POS Invoice")
    assert _is_simplified_document(doc) is True
