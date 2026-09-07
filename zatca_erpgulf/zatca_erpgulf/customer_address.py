"""Resolve the customer address used by ZATCA invoice flows.

ERPNext populates ``Sales Invoice.customer_address`` from the customer's
default linked address.  Older ZATCA paths, however, read only
``Customer.customer_primary_address``.  Keeping the resolution here makes the
signing, XML, POS, and validation paths use the same address without changing
the invoice or the Customer record.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_value
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import is_zatca_invoice_enabled


def _value(doc: Any, fieldname: str, default: Any = None) -> Any:
    """Read a field from a Frappe document or a dict-like object."""
    getter = getattr(doc, "get", None)
    if callable(getter):
        return getter(fieldname, default)
    return getattr(doc, fieldname, default)


def _customer_name(customer_doc: Any) -> str:
    return str(_value(customer_doc, "name", "") or "").strip()


def _load_address(name: Any, *, require_active: bool = False, require_customer: str = ""):
    """Load one address candidate and reject deleted/invalid references."""
    name = str(name or "").strip()
    if not name:
        return None

    try:
        address = frappe.get_doc("Address", name)
    except (frappe.DoesNotExistError, frappe.ValidationError):
        return None

    if require_active and cint(_value(address, "disabled", 0) or 0):
        return None

    if require_customer:
        linked = frappe.db.exists(
            "Dynamic Link",
            {
                "parent": address.name,
                "parenttype": "Address",
                "link_doctype": "Customer",
                "link_name": require_customer,
            },
        )
        if not linked:
            return None

    return address


def _linked_address_names(customer_name: str) -> list[str]:
    """Return active customer addresses: primary first, then oldest first."""
    if not customer_name:
        return []

    try:
        rows = frappe.get_all(
            "Address",
            filters=[
                ["Dynamic Link", "link_doctype", "=", "Customer"],
                ["Dynamic Link", "link_name", "=", customer_name],
                ["disabled", "=", 0],
            ],
            pluck="name",
            order_by="is_primary_address DESC, creation ASC, name ASC",
        ) or []
        return [
            str(_value(row, "name", row) or "").strip()
            for row in rows
            if str(_value(row, "name", row) or "").strip()
        ]
    except Exception:
        # Keep the resolver compatible with older Frappe query builders.  The
        # fallback still preserves the same primary/creation ordering in
        # Python when an older database adapter rejects the compound order.
        try:
            rows = frappe.get_all(
                "Address",
                filters=[
                    ["Dynamic Link", "link_doctype", "=", "Customer"],
                    ["Dynamic Link", "link_name", "=", customer_name],
                    ["disabled", "=", 0],
                ],
                fields=["name", "is_primary_address", "creation"],
            )
        except Exception:
            return []

        rows = sorted(
            rows or [],
            key=lambda row: (
                -cint(_value(row, "is_primary_address", 0) or 0),
                str(_value(row, "creation", "") or ""),
                str(_value(row, "name", "") or ""),
            ),
        )
        return [str(_value(row, "name", "") or "").strip() for row in rows if _value(row, "name")]


def resolve_customer_address(sales_invoice_doc: Any, customer_doc: Any):
    """Return ``(address_doc, source)`` using the ERPNext-compatible order.

    Resolution order:

    1. The address saved on the invoice.  It is authoritative for an existing
       invoice, so an old/disabled link is not silently replaced.
    2. ``Customer.customer_primary_address`` when it still points to an active
       address linked to this customer.
    3. Active addresses linked through Dynamic Link, ordered by
       ``is_primary_address DESC, creation ASC``.

    No document is modified by this function.
    """
    customer_name = _customer_name(customer_doc)

    invoice_address = _value(sales_invoice_doc, "customer_address")
    invoice_is_submitted = cint(_value(sales_invoice_doc, "docstatus", 0) or 0) == 1
    address = _load_address(invoice_address, require_active=not invoice_is_submitted)
    if address:
        # Draft invoices follow ERPNext's ownership rule.  For a submitted
        # invoice, preserve the address that was stored on that invoice even
        # if the Customer link was later changed or the Address was disabled.
        if invoice_is_submitted or not customer_name or frappe.db.exists(
            "Dynamic Link",
            {
                "parent": address.name,
                "parenttype": "Address",
                "link_doctype": "Customer",
                "link_name": customer_name,
            },
        ):
            return address, "Sales Invoice.customer_address"

    primary_address = _value(customer_doc, "customer_primary_address")
    address = _load_address(
        primary_address,
        require_active=True,
        require_customer=customer_name,
    )
    if address:
        return address, "Customer.customer_primary_address"

    for address_name in _linked_address_names(customer_name):
        address = _load_address(
            address_name,
            require_active=True,
            require_customer=customer_name,
        )
        if address:
            if cint(_value(address, "is_primary_address", 0) or 0):
                return address, "Customer Dynamic Link (primary)"
            return address, "Customer Dynamic Link"

    return None, None


def get_customer_address(sales_invoice_doc: Any, customer_doc: Any):
    """Return only the resolved address for callers that do not need its source."""
    address, _source = resolve_customer_address(sales_invoice_doc, customer_doc)
    return address


def validate_customer_address_for_zatca(invoice: Any, event: str | None = None):
    """Validate customer-address presence before a ZATCA invoice is submitted.

    ERPNext permits a draft Sales Invoice without a customer address.  ZATCA
    requires one for non-B2C invoices, so this preflight prevents a missing
    address from being discovered only after the document is submitted.  The
    detailed field checks remain in the XML/signing paths.
    """
    if not _value(invoice, "customer") or not _value(invoice, "company"):
        return None

    try:
        company = frappe.get_cached_doc("Company", _value(invoice, "company"))
    except Exception:
        return None

    if not is_zatca_invoice_enabled(company):
        return None

    customer = frappe.get_doc("Customer", _value(invoice, "customer"))
    if cint(get_alias_value("customer_b2c", customer, 0) or 0) == 1:
        return None

    address, source = resolve_customer_address(invoice, customer)
    if not address:
        frappe.throw(
            _(
                "As per ZATCA regulations, Customer address is mandatory for non-B2C customers."
            )
        )

    return address, source
