"""Validation for credit notes against standard advance-payment Sales Invoices."""

import frappe
from frappe import _
from frappe.utils import flt

from zatca_erpgulf.zatca_erpgulf.advance_lifecycle import (
    get_advance_sales_invoice_from_return,
)


SALES_INVOICE_DOCTYPE = "Sales Invoice"
AMOUNT_TOLERANCE = 0.01


def _get_money(value):
    return flt(value or 0)


def _get_invoice_total(doc_or_row):
    value = _get_money(getattr(doc_or_row, "grand_total", 0))
    if not value and hasattr(doc_or_row, "get"):
        value = _get_money(doc_or_row.get("grand_total"))

    if not value:
        value = _get_money(getattr(doc_or_row, "rounded_total", 0))
    if not value and hasattr(doc_or_row, "get"):
        value = _get_money(doc_or_row.get("rounded_total"))

    return abs(value)


def _get_submitted_credit_notes(reference, exclude_name=None):
    rows = frappe.get_all(
        SALES_INVOICE_DOCTYPE,
        filters={
            "docstatus": 1,
            "is_return": 1,
            "return_against": reference,
        },
        fields=[
            "name",
            "grand_total",
            "rounded_total",
            "posting_date",
            "posting_time",
            "modified",
        ],
        order_by="posting_date desc, posting_time desc, modified desc",
    )

    if exclude_name:
        rows = [row for row in rows if row.name != exclude_name]

    return rows


def _validate_party_and_currency(credit_note, advance_invoice):
    if credit_note.company != advance_invoice.company:
        frappe.throw(
            _(
                "Credit note company must match the original advance payment "
                "Sales Invoice company."
            )
        )

    if credit_note.customer != advance_invoice.customer:
        frappe.throw(
            _(
                "Credit note customer must match the original advance payment "
                "Sales Invoice customer."
            )
        )

    if (
        credit_note.currency
        and advance_invoice.currency
        and credit_note.currency != advance_invoice.currency
    ):
        frappe.throw(
            _(
                "Credit note currency must match the original advance payment "
                "Sales Invoice currency."
            )
        )


def validate_advance_credit_note_against_original(doc, event=None):
    """Validate a return only when return_against points to an advance invoice."""
    advance_invoice = get_advance_sales_invoice_from_return(doc, strict=True)
    if not advance_invoice:
        return

    _validate_party_and_currency(doc, advance_invoice)

    original_total = _get_invoice_total(advance_invoice)
    current_total = _get_invoice_total(doc)

    if original_total <= 0:
        frappe.throw(
            _(
                "Original advance payment Sales Invoice total amount must be "
                "greater than zero."
            )
        )

    if current_total <= 0:
        frappe.throw(_("Advance credit note total amount must be greater than zero."))

    previous_total = sum(
        _get_invoice_total(row)
        for row in _get_submitted_credit_notes(
            advance_invoice.name,
            exclude_name=getattr(doc, "name", None),
        )
    )

    # A credit note may reverse only the portion that has not already been
    # consumed by submitted final invoices. This uses the direct-allocation
    # child table and is deliberately independent of Payment Entry.
    from zatca_erpgulf.zatca_erpgulf.advance_deduction import (
        _lock_advance_invoice,
        _submitted_final_allocation_total,
    )

    if int(getattr(doc, "docstatus", 0) or 0) == 1:
        _lock_advance_invoice(advance_invoice.name)

    allocated_total = float(
        _submitted_final_allocation_total(advance_invoice.name)
    )

    total_after_current = previous_total + allocated_total + current_total
    if total_after_current > original_total + AMOUNT_TOLERANCE:
        remaining = max(original_total - previous_total - allocated_total, 0)
        frappe.throw(
            _(
                "Total advance credit notes cannot exceed the original advance "
                "payment Sales Invoice balance after submitted final-invoice "
                "allocations. Remaining amount: {0}"
            ).format(
                frappe.format_value(remaining, {"fieldtype": "Currency"})
            )
        )
