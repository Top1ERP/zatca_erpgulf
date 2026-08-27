from __future__ import annotations

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    is_advance_payment_invoice,
    supports_advance_payment_entry_link,
)


SALES_INVOICE_DOCTYPE = "Sales Invoice"
PAYMENT_ENTRY_FIELD = "custom_zatca_payment_entry"
ACCEPTED_ZATCA_ADVANCE_STATUSES = {
    "REPORTED",
    "CLEARED",
    "PHASE 1 QR CREATED",
    "PHASE-1 QR GENERATED",
}


def normalize_zatca_status(value) -> str:
    return str(value or "").strip().upper()


def get_sales_invoice_zatca_status(invoice) -> str:
    return normalize_zatca_status(invoice.get("custom_zatca_status"))


def is_accepted_advance_sales_invoice(invoice) -> bool:
    return (
        getattr(invoice, "doctype", None) == SALES_INVOICE_DOCTYPE
        and int(getattr(invoice, "docstatus", 0) or 0) == 1
        and is_advance_payment_invoice(invoice)
        and get_sales_invoice_zatca_status(invoice)
        in ACCEPTED_ZATCA_ADVANCE_STATUSES
    )


def get_advance_sales_invoice_for_payment_entry(
    payment_entry_name: str,
    *,
    strict: bool = False,
    require_accepted: bool = True,
):
    payment_entry_name = str(payment_entry_name or "").strip()
    if not payment_entry_name:
        return None

    if not supports_advance_payment_entry_link():
        if strict:
            frappe.throw(
                _("Sales Invoice field {0} is missing or unavailable.").format(PAYMENT_ENTRY_FIELD)
            )
        return None

    names = frappe.get_all(
        SALES_INVOICE_DOCTYPE,
        filters={
            PAYMENT_ENTRY_FIELD: payment_entry_name,
            "docstatus": ["!=", 2],
        },
        pluck="name",
        order_by="creation asc, name asc",
        limit_page_length=2,
    )

    if not names:
        return None

    if len(names) > 1:
        frappe.throw(
            _(
                "Payment Entry {0} is linked to more than one active advance payment "
                "Sales Invoice: {1}."
            ).format(payment_entry_name, ", ".join(names))
        )

    invoice = frappe.get_doc(SALES_INVOICE_DOCTYPE, names[0])

    if not is_advance_payment_invoice(invoice):
        if strict:
            frappe.throw(
                _(
                    "Sales Invoice {0}, linked to Payment Entry {1}, is not marked "
                    "as an advance payment invoice."
                ).format(invoice.name, payment_entry_name)
            )
        return None

    if require_accepted and not is_accepted_advance_sales_invoice(invoice):
        if strict:
            frappe.throw(
                _(
                    "Advance payment Sales Invoice {0} has status '{1}' and docstatus "
                    "{2}. Only submitted invoices with REPORTED, CLEARED, or "
                    "Phase-1 QR Generated status can be deducted."
                ).format(
                    invoice.name,
                    invoice.get("custom_zatca_status"),
                    invoice.docstatus,
                )
            )
        return None

    return invoice


def get_advance_sales_invoice_from_return(return_doc, *, strict: bool = False):
    if int(getattr(return_doc, "is_return", 0) or 0) != 1:
        return None

    reference = str(getattr(return_doc, "return_against", "") or "").strip()
    if not reference:
        if strict:
            frappe.throw(
                _("Return Against is required for a Sales Invoice credit note.")
            )
        return None

    if not frappe.db.exists(SALES_INVOICE_DOCTYPE, reference):
        if strict:
            frappe.throw(_("Sales Invoice not found: {0}").format(reference))
        return None

    invoice = frappe.get_doc(SALES_INVOICE_DOCTYPE, reference)
    if not is_advance_payment_invoice(invoice):
        return None

    if strict and not is_accepted_advance_sales_invoice(invoice):
        frappe.throw(
            _(
                "Original advance payment Sales Invoice {0} must be submitted and "
                "have REPORTED, CLEARED, or Phase-1 QR Generated status before "
                "creating a credit note."
            ).format(reference)
        )

    return invoice
