# advance_credit_note.py

"""Advance credit note validation and ZATCA advance invoice reversal tracking."""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime


ADVANCE_DOCTYPE = "ZATCA Advance Tax Invoice"
SALES_INVOICE_DOCTYPE = "Sales Invoice"

REVERSAL_STATUS_NOT_CANCELLED = "Not Cancelled"
REVERSAL_STATUS_PARTIALLY_CANCELLED = "Partially Cancelled"
REVERSAL_STATUS_CANCELLED = "Cancelled"

AMOUNT_TOLERANCE = 0.01


def _is_advance_credit_note(doc):
    """Return True when the Sales Invoice is an advance-payment credit note."""
    return (
        getattr(doc, "doctype", None) == SALES_INVOICE_DOCTYPE
        and cint(getattr(doc, "is_return", 0)) == 1
        and cint(getattr(doc, "custom_is_advance_credit_note", 0)) == 1
    )


def _get_advance_reference(doc):
    """Return the linked ZATCA advance invoice reference."""
    return str(getattr(doc, "custom_advance_invoice_reference", "") or "").strip()


def _get_money(value):
    """Normalize money values with ERPNext float handling."""
    return flt(value or 0)


def _get_credit_note_total(doc_or_row):
    """
    Return positive credit-note total amount in transaction currency.

    Sales return invoices usually store grand_total as negative. For validation
    and reversal tracking we compare the absolute value against the advance
    invoice total_amount.
    """
    value = _get_money(getattr(doc_or_row, "grand_total", 0))

    if not value and hasattr(doc_or_row, "get"):
        value = _get_money(doc_or_row.get("grand_total"))

    if not value:
        value = _get_money(getattr(doc_or_row, "rounded_total", 0))

    if not value and hasattr(doc_or_row, "get"):
        value = _get_money(doc_or_row.get("rounded_total"))

    return abs(value)


def _get_advance_total(advance_doc):
    """Return the original ZATCA advance invoice total amount."""
    return abs(_get_money(getattr(advance_doc, "total_amount", 0)))


def _advance_invoice_status_is_submitted(advance_doc):
    """Return True when the original advance invoice was accepted by ZATCA flow."""
    status_values = [
        getattr(advance_doc, "zatca_status", None),
        getattr(advance_doc, "zatca_clearance_status", None),
        getattr(advance_doc, "zatca_reporting_status", None),
    ]

    return any(
        str(status or "").strip().lower() in {"cleared", "reported"}
        for status in status_values
    )


def _get_advance_doc(reference):
    """Load and validate the referenced ZATCA advance invoice."""
    if not reference:
        frappe.throw(
            _(
                "Advance Invoice Reference is required when this credit note "
                "cancels or reverses a ZATCA advance payment invoice."
            )
        )

    if not frappe.db.exists(ADVANCE_DOCTYPE, reference):
        frappe.throw(_("{0} not found: {1}").format(ADVANCE_DOCTYPE, reference))

    return frappe.get_doc(ADVANCE_DOCTYPE, reference)


def _get_submitted_credit_notes(reference, exclude_name=None):
    """Return submitted Sales Invoice credit notes linked to this advance invoice."""
    rows = frappe.get_all(
        SALES_INVOICE_DOCTYPE,
        filters={
            "docstatus": 1,
            "custom_is_advance_credit_note": 1,
            "custom_advance_invoice_reference": reference,
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


def _sum_credit_note_totals(rows):
    """Sum credit note totals as positive values."""
    return sum(_get_credit_note_total(row) for row in rows)


def _validate_party_and_currency(doc, advance_doc):
    """Validate that credit note matches original advance invoice dimensions."""
    if getattr(doc, "company", None) != getattr(advance_doc, "company", None):
        frappe.throw(
            _(
                "Credit note company must match the original ZATCA advance "
                "payment invoice company."
            )
        )

    if getattr(doc, "customer", None) != getattr(advance_doc, "customer", None):
        frappe.throw(
            _(
                "Credit note customer must match the original ZATCA advance "
                "payment invoice customer."
            )
        )

    advance_currency = str(getattr(advance_doc, "currency", "") or "").strip()
    credit_currency = str(getattr(doc, "currency", "") or "").strip()

    if advance_currency and credit_currency and advance_currency != credit_currency:
        frappe.throw(
            _(
                "Credit note currency must match the original ZATCA advance "
                "payment invoice currency."
            )
        )


def validate_advance_credit_note_against_original(doc, event=None):
    """
    Validate Sales Invoice advance credit notes against the original advance invoice.

    Rules:
    - same company
    - same customer
    - same currency
    - original advance invoice must be Cleared or Reported
    - current + previous submitted credit notes must not exceed original total_amount
    """
    if not _is_advance_credit_note(doc):
        return

    reference = _get_advance_reference(doc)
    advance_doc = _get_advance_doc(reference)

    if not _advance_invoice_status_is_submitted(advance_doc):
        frappe.throw(
            _(
                "Original ZATCA advance payment invoice must be Cleared or "
                "Reported before creating a credit note."
            )
        )

    _validate_party_and_currency(doc, advance_doc)

    original_total = _get_advance_total(advance_doc)
    current_total = _get_credit_note_total(doc)

    if original_total <= 0:
        frappe.throw(
            _(
                "Original ZATCA advance payment invoice total amount must be "
                "greater than zero."
            )
        )

    if current_total <= 0:
        frappe.throw(
            _("Advance credit note total amount must be greater than zero.")
        )

    previous_credit_total = _sum_credit_note_totals(
        _get_submitted_credit_notes(reference, exclude_name=getattr(doc, "name", None))
    )

    total_after_current = previous_credit_total + current_total

    if total_after_current > original_total + AMOUNT_TOLERANCE:
        remaining = max(original_total - previous_credit_total, 0)
        frappe.throw(
            _(
                "Total advance credit notes cannot exceed the original ZATCA "
                "advance payment invoice total amount. Remaining amount: {0}"
            ).format(frappe.format_value(remaining, {"fieldtype": "Currency"}))
        )


def update_advance_invoice_reversal_status_from_sales_invoice(doc, event=None):
    """Hook entry point: update the linked advance invoice after submit/cancel."""
    if not _is_advance_credit_note(doc):
        return

    reference = _get_advance_reference(doc)
    if reference:
        update_advance_invoice_reversal_status(reference)


def update_advance_invoice_reversal_status(advance_invoice_name):
    """Recalculate and store reversal status on ZATCA Advance Tax Invoice."""
    if not frappe.db.exists(ADVANCE_DOCTYPE, advance_invoice_name):
        return

    advance_doc = frappe.get_doc(ADVANCE_DOCTYPE, advance_invoice_name)
    original_total = _get_advance_total(advance_doc)

    rows = _get_submitted_credit_notes(advance_invoice_name)
    credited_amount = _sum_credit_note_totals(rows)
    remaining_amount = max(original_total - credited_amount, 0)

    if credited_amount <= AMOUNT_TOLERANCE:
        reversal_status = REVERSAL_STATUS_NOT_CANCELLED
    elif credited_amount + AMOUNT_TOLERANCE >= original_total:
        reversal_status = REVERSAL_STATUS_CANCELLED
        remaining_amount = 0
    else:
        reversal_status = REVERSAL_STATUS_PARTIALLY_CANCELLED

    last_credit_note = rows[0].name if rows else None

    meta = frappe.get_meta(ADVANCE_DOCTYPE)
    updates = {
        "advance_reversal_status": reversal_status,
        "credited_amount": credited_amount,
        "remaining_amount": remaining_amount,
        "advance_credit_note_count": len(rows),
        "last_advance_credit_note": last_credit_note,
        "last_reversal_update_at": now_datetime(),
    }

    updates = {
        fieldname: value
        for fieldname, value in updates.items()
        if meta.has_field(fieldname)
    }

    if updates:
        frappe.db.set_value(
            ADVANCE_DOCTYPE,
            advance_invoice_name,
            updates,
            update_modified=True,
        )


def rebuild_all_advance_invoice_reversal_statuses():
    """Utility method to rebuild reversal status for all referenced advance invoices."""
    references = frappe.get_all(
        SALES_INVOICE_DOCTYPE,
        filters={
            "custom_is_advance_credit_note": 1,
            "custom_advance_invoice_reference": ["is", "set"],
        },
        pluck="custom_advance_invoice_reference",
    )

    for reference in sorted(set(filter(None, references))):
        update_advance_invoice_reversal_status(reference)

    return {"updated": len(set(filter(None, references)))}
