from types import SimpleNamespace
from unittest.mock import patch

from zatca_erpgulf.zatca_erpgulf import customer_address


def _address(name, *, primary=0, disabled=0):
    return SimpleNamespace(
        name=name,
        is_primary_address=primary,
        disabled=disabled,
    )


def test_invoice_address_has_priority_without_modifying_documents():
    invoice = SimpleNamespace(customer_address="Invoice Address")
    customer = SimpleNamespace(name="Customer 1", customer_primary_address="Primary Address")
    docs = {"Invoice Address": _address("Invoice Address")}

    with patch.object(customer_address.frappe, "get_doc", side_effect=lambda dt, name: docs[name]):
        with patch.object(customer_address.frappe, "db", SimpleNamespace(exists=lambda *args, **kwargs: True)):
            resolved, source = customer_address.resolve_customer_address(invoice, customer)

    assert resolved.name == "Invoice Address"
    assert source == "Sales Invoice.customer_address"
    assert invoice.customer_address == "Invoice Address"


def test_customer_primary_address_is_used_when_invoice_address_is_missing():
    invoice = SimpleNamespace(customer_address=None)
    customer = SimpleNamespace(name="Customer 1", customer_primary_address="Primary Address")
    docs = {"Primary Address": _address("Primary Address")}

    with patch.object(customer_address.frappe, "get_doc", side_effect=lambda dt, name: docs[name]):
        with patch.object(customer_address.frappe, "db", SimpleNamespace(exists=lambda *args, **kwargs: True)):
            resolved, source = customer_address.resolve_customer_address(invoice, customer)

    assert resolved.name == "Primary Address"
    assert source == "Customer.customer_primary_address"


def test_dynamic_link_falls_back_to_oldest_when_no_primary_exists():
    invoice = SimpleNamespace(customer_address=None)
    customer = SimpleNamespace(name="Customer 1", customer_primary_address=None)
    docs = {
        "Old Address": _address("Old Address"),
        "New Address": _address("New Address"),
    }
    linked = ["Old Address", "New Address"]

    with patch.object(customer_address.frappe, "get_doc", side_effect=lambda dt, name: docs[name]):
        with patch.object(customer_address.frappe, "get_all", return_value=linked):
            with patch.object(customer_address.frappe, "db", SimpleNamespace(exists=lambda *args, **kwargs: True)):
                resolved, source = customer_address.resolve_customer_address(invoice, customer)

    assert resolved.name == "Old Address"
    assert source == "Customer Dynamic Link"


def test_dynamic_link_prefers_primary_address():
    invoice = SimpleNamespace(customer_address=None)
    customer = SimpleNamespace(name="Customer 1", customer_primary_address=None)
    docs = {
        "Primary Address": _address("Primary Address", primary=1),
    }
    linked = ["Primary Address"]

    with patch.object(customer_address.frappe, "get_doc", side_effect=lambda dt, name: docs[name]):
        with patch.object(customer_address.frappe, "get_all", return_value=linked):
            with patch.object(customer_address.frappe, "db", SimpleNamespace(exists=lambda *args, **kwargs: True)):
                resolved, source = customer_address.resolve_customer_address(invoice, customer)

    assert resolved.name == "Primary Address"
    assert source == "Customer Dynamic Link (primary)"
