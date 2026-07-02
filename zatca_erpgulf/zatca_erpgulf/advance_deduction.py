from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _


ACCEPTED_ZATCA_ADVANCE_STATUSES = {"REPORTED", "CLEARED"}


def q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def normalize_status(value) -> str:
    return str(value or "").strip().upper()


def _get_advance_row_reference_name(row) -> str:
    return (
        getattr(row, "reference_name", None)
        or getattr(row, "reference", None)
        or getattr(row, "payment_entry", None)
        or ""
    )


def _get_advance_row_allocated_amount(row) -> Decimal:
    amount = (
        getattr(row, "allocated_amount", None)
        or getattr(row, "advance_amount", None)
        or 0
    )
    return q2(amount)


def _get_linked_zatca_advance_invoice(payment_entry: str) -> str:
    if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
        return ""

    meta = frappe.get_meta("Payment Entry")
    if not meta.has_field("custom_zatca_advance_tax_invoice"):
        return ""

    return frappe.db.get_value(
        "Payment Entry",
        payment_entry,
        "custom_zatca_advance_tax_invoice",
    ) or ""


def get_standard_advance_deduction_rows(sales_invoice_doc, strict: bool = False) -> list[dict]:
    rows = getattr(sales_invoice_doc, "advances", None) or []
    result: list[dict] = []

    for row in rows:
        payment_entry = _get_advance_row_reference_name(row)
        allocated_amount = _get_advance_row_allocated_amount(row)

        if not payment_entry or allocated_amount <= Decimal("0.00"):
            continue

        advance_tax_invoice = _get_linked_zatca_advance_invoice(payment_entry)
        if not advance_tax_invoice:
            continue

        if not frappe.db.exists("ZATCA Advance Tax Invoice", advance_tax_invoice):
            frappe.throw(
                _(
                    f"Payment Entry {payment_entry} is linked to missing "
                    f"ZATCA Advance Tax Invoice {advance_tax_invoice}."
                )
            )

        advance = frappe.db.get_value(
            "ZATCA Advance Tax Invoice",
            advance_tax_invoice,
            [
                "company",
                "customer",
                "zatca_uuid",
                "posting_date",
                "total_amount",
                "status",
                "zatca_status",
            ],
            as_dict=True,
        )

        if advance.get("company") and advance.get("company") != sales_invoice_doc.company:
            frappe.throw(
                _(
                    f"ZATCA Advance Tax Invoice {advance_tax_invoice} belongs to company "
                    f"{advance.get('company')}, but this Sales Invoice belongs to "
                    f"{sales_invoice_doc.company}."
                )
            )

        if advance.get("customer") and advance.get("customer") != sales_invoice_doc.customer:
            frappe.throw(
                _(
                    f"ZATCA Advance Tax Invoice {advance_tax_invoice} belongs to customer "
                    f"{advance.get('customer')}, but this Sales Invoice belongs to "
                    f"{sales_invoice_doc.customer}."
                )
            )

        zatca_status = normalize_status(advance.get("zatca_status"))
        if zatca_status not in ACCEPTED_ZATCA_ADVANCE_STATUSES:
            if strict:
                frappe.throw(
                    _(
                        f"Payment Entry {payment_entry} is linked to ZATCA Advance Tax Invoice "
                        f"{advance_tax_invoice}, but its ZATCA status is '{advance.get('zatca_status')}'. "
                        f"Only REPORTED or CLEARED advance tax invoices can be deducted in the final invoice XML."
                    )
                )
            continue

        result.append(
            {
                "payment_entry": payment_entry,
                "advance_tax_invoice": advance_tax_invoice,
                "allocated_amount": allocated_amount,
                "zatca_uuid": advance.get("zatca_uuid"),
                "posting_date": advance.get("posting_date"),
                "advance_total_amount": q2(advance.get("total_amount")),
                "status": advance.get("status"),
                "zatca_status": advance.get("zatca_status"),
            }
        )

    return result


def get_standard_advance_prepaid_amount(sales_invoice_doc, strict: bool = False) -> Decimal:
    return q2(
        sum(
            (row["allocated_amount"] for row in get_standard_advance_deduction_rows(sales_invoice_doc, strict=strict)),
            Decimal("0.00"),
        )
    )


def validate_sales_invoice_advance_deductions(doc, event=None) -> None:
    # Draft/UI summary: do not block for non-accepted advances; just do not count them.
    rows = get_standard_advance_deduction_rows(doc, strict=False)
    total = q2(sum((row["allocated_amount"] for row in rows), Decimal("0.00")))

    if hasattr(doc, "custom_zatca_prepaid_amount"):
        doc.custom_zatca_prepaid_amount = float(total)

    if hasattr(doc, "custom_zatca_advance_deduction_count"):
        doc.custom_zatca_advance_deduction_count = len(rows)

    invoice_total = q2(getattr(doc, "grand_total", 0) or getattr(doc, "rounded_total", 0))
    if total > Decimal("0.00") and invoice_total > Decimal("0.00") and total > invoice_total:
        frappe.throw(
            _(
                f"ZATCA prepaid amount cannot exceed Sales Invoice grand total. "
                f"Prepaid amount is {total}, grand total is {invoice_total}."
            )
        )
