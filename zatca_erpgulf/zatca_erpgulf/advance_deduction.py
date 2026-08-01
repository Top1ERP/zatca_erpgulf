from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.advance_lifecycle import (
    get_advance_sales_invoice_for_payment_entry,
)
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import is_advance_payment_invoice

ZATCA_ADVANCE_VAT_DEDUCTION_MARKER = "[ZATCA Advance VAT Deduction]"


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
        or 0
    )
    return q2(amount)


def _is_return_invoice(doc) -> bool:
    return int(getattr(doc, "is_return", 0) or 0) == 1


def _get_positive_zatca_advance_allocations(doc) -> list:
    """Return positive advance rows linked to standard advance Sales Invoices."""
    allocations = []

    for row in doc.get("advances", []) or []:
        if _get_advance_row_allocated_amount(row) <= Decimal("0.00"):
            continue

        payment_entry = _get_advance_row_reference_name(row)
        if not payment_entry:
            continue

        if get_advance_sales_invoice_for_payment_entry(
            payment_entry,
            require_accepted=False,
        ):
            allocations.append(row)

    return allocations


def _is_zatca_advance_vat_deduction_tax(row) -> bool:
    return ZATCA_ADVANCE_VAT_DEDUCTION_MARKER in str(getattr(row, "description", "") or "")


def _remove_existing_zatca_advance_vat_deduction_rows(doc) -> None:
    taxes = []
    for row in doc.get("taxes", []) or []:
        if not _is_zatca_advance_vat_deduction_tax(row):
            taxes.append(row)

    doc.set("taxes", taxes)


def _get_positive_invoice_vat_amount(doc) -> Decimal:
    total = Decimal("0.00")
    for row in doc.get("taxes", []) or []:
        if _is_zatca_advance_vat_deduction_tax(row):
            continue

        amount = q2(getattr(row, "tax_amount", 0))
        if amount > Decimal("0.00"):
            total += amount

    return q2(total)


def _get_default_vat_tax_row(doc):
    for row in doc.get("taxes", []) or []:
        if _is_zatca_advance_vat_deduction_tax(row):
            continue

        amount = q2(getattr(row, "tax_amount", 0))
        account = getattr(row, "account_head", None)
        if account and amount > Decimal("0.00"):
            return row

    return None


def _get_advance_doc(payment_entry: str, strict: bool = False):
    return get_advance_sales_invoice_for_payment_entry(
        payment_entry,
        strict=strict,
    )


def _validate_same_party_and_currency(sales_invoice_doc, advance) -> None:
    if advance.company and advance.company != sales_invoice_doc.company:
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} belongs to company {1}, but this Sales Invoice belongs to {2}."
            ).format(advance.name, advance.company, sales_invoice_doc.company)
        )

    if advance.customer and advance.customer != sales_invoice_doc.customer:
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} belongs to customer {1}, but this Sales Invoice belongs to {2}."
            ).format(advance.name, advance.customer, sales_invoice_doc.customer)
        )

    invoice_currency = getattr(sales_invoice_doc, "currency", None)
    advance_currency = getattr(advance, "currency", None)
    if invoice_currency and advance_currency and invoice_currency != advance_currency:
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} currency is {1}, but this Sales Invoice currency is {2}."
            ).format(advance.name, advance_currency, invoice_currency)
        )


def _allocated_amounts_from_advance(row_allocated_amount: Decimal, advance) -> dict:
    advance_taxable = q2(
        getattr(advance, "net_total", 0) or getattr(advance, "total", 0)
    )
    advance_tax = q2(getattr(advance, "total_taxes_and_charges", 0))
    advance_total = q2(
        getattr(advance, "rounded_total", 0) or getattr(advance, "grand_total", 0)
    )

    if advance_total <= Decimal("0.00"):
        frappe.throw(_("Advance payment Sales Invoice {0} total amount must be greater than zero.").format(advance.name))

    if advance_taxable <= Decimal("0.00"):
        frappe.throw(_("Advance payment Sales Invoice {0} taxable amount must be greater than zero.").format(advance.name))

    requested = q2(row_allocated_amount)
    if requested <= Decimal("0.00"):
        return {
            "allocated_taxable_amount": Decimal("0.00"),
            "allocated_tax_amount": Decimal("0.00"),
            "allocated_total_amount": Decimal("0.00"),
        }

    # Standard ERPNext allocated amount should be taxable amount.
    # If a user/system passes gross amount, convert it proportionally.
    if requested > advance_taxable:
        requested_total = min(requested, advance_total)
        ratio = requested_total / advance_total
        allocated_taxable = q2(advance_taxable * ratio)
        allocated_tax = q2(advance_tax * ratio)
    else:
        allocated_taxable = min(requested, advance_taxable)
        ratio = allocated_taxable / advance_taxable
        allocated_tax = q2(advance_tax * ratio)

    allocated_total = q2(allocated_taxable + allocated_tax)

    return {
        "allocated_taxable_amount": q2(allocated_taxable),
        "allocated_tax_amount": q2(allocated_tax),
        "allocated_total_amount": q2(allocated_total),
    }


def get_standard_advance_deduction_rows(sales_invoice_doc, strict: bool = False) -> list[dict]:
    rows = getattr(sales_invoice_doc, "advances", None) or []
    result: list[dict] = []

    for row in rows:
        payment_entry = _get_advance_row_reference_name(row)
        row_allocated_amount = _get_advance_row_allocated_amount(row)

        if not payment_entry:
            continue

        advance = _get_advance_doc(payment_entry, strict=strict and row_allocated_amount > Decimal("0.00"))
        if not advance:
            continue

        _validate_same_party_and_currency(sales_invoice_doc, advance)
        amounts = _allocated_amounts_from_advance(row_allocated_amount, advance)

        result.append(
            {
                "payment_entry": payment_entry,
                "advance_invoice": advance.name,
                "allocated_amount": amounts["allocated_taxable_amount"],
                "allocated_taxable_amount": amounts["allocated_taxable_amount"],
                "allocated_tax_amount": amounts["allocated_tax_amount"],
                "allocated_total_amount": amounts["allocated_total_amount"],
                "zatca_uuid": advance.get("custom_uuid"),
                "posting_date": advance.get("posting_date"),
                "advance_total_amount": q2(
                    advance.get("rounded_total") or advance.get("grand_total")
                ),
                "advance_taxable_amount": q2(
                    advance.get("net_total") or advance.get("total")
                ),
                "advance_tax_amount": q2(advance.get("total_taxes_and_charges")),
                "status": advance.get("status"),
                "zatca_status": advance.get("custom_zatca_status"),
                "tax_account": None,
                "tax_rate": Decimal("0.00"),
                "currency": advance.get("currency"),
            }
        )

    return result


def get_standard_advance_prepaid_amount(sales_invoice_doc, strict: bool = False) -> Decimal:
    return q2(
        sum(
            (
                row["allocated_total_amount"]
                for row in get_standard_advance_deduction_rows(sales_invoice_doc, strict=strict)
                if row["allocated_total_amount"] > Decimal("0.00")
            ),
            Decimal("0.00"),
        )
    )


def _sync_advance_rows_allocated_amounts(doc, active_rows: list[dict]) -> None:
    by_payment_entry = {
        row["payment_entry"]: row for row in active_rows
    }

    for adv_row in doc.get("advances", []) or []:
        payment_entry = _get_advance_row_reference_name(adv_row)
        deduction = by_payment_entry.get(payment_entry)
        if not deduction:
            continue

        taxable_amount = float(deduction["allocated_taxable_amount"])
        adv_row.allocated_amount = taxable_amount


def _sync_detail_table(doc, rows: list[dict]) -> None:
    if not doc.meta.has_field("custom_zatca_advance_deduction_details"):
        return

    doc.set("custom_zatca_advance_deduction_details", [])

    for row in rows:
        allocated_total = q2(row["allocated_total_amount"])
        remarks = ""
        if allocated_total <= Decimal("0.00"):
            remarks = _("No amount allocated yet. Set Allocated Amount to apply this advance.")

        detail = doc.append("custom_zatca_advance_deduction_details", {})
        detail.payment_entry = row["payment_entry"]
        detail.advance_invoice = row["advance_invoice"]
        detail.advance_invoice_date = row["posting_date"]
        detail.advance_status = row["zatca_status"]
        detail.currency = row["currency"]
        detail.advance_total_amount = float(row["advance_total_amount"])
        detail.advance_taxable_amount = float(row["advance_taxable_amount"])
        detail.advance_tax_amount = float(row["advance_tax_amount"])
        detail.allocated_total_amount = float(row["allocated_total_amount"])
        detail.allocated_taxable_amount = float(row["allocated_taxable_amount"])
        detail.allocated_tax_amount = float(row["allocated_tax_amount"])
        detail.remarks = remarks


def _append_negative_vat_deduction_tax_row(doc, active_rows: list[dict]) -> None:
    total_advance_tax = q2(sum((row["allocated_tax_amount"] for row in active_rows), Decimal("0.00")))
    if total_advance_tax <= Decimal("0.00"):
        return

    default_tax_row = _get_default_vat_tax_row(doc)
    if not default_tax_row:
        frappe.throw(_("Cannot add ZATCA advance VAT deduction because the Sales Invoice has no positive VAT tax row."))

    account_head = getattr(default_tax_row, "account_head", None)
    if not account_head:
        frappe.throw(_("Cannot add ZATCA advance VAT deduction because VAT account is missing."))

    description = _("ZATCA Advance VAT Deduction {0}").format(ZATCA_ADVANCE_VAT_DEDUCTION_MARKER)

    tax_row = doc.append("taxes", {})
    tax_row.charge_type = "Actual"
    tax_row.account_head = account_head
    tax_row.rate = 0
    tax_row.tax_amount = float(-total_advance_tax)
    tax_row.description = description

    if hasattr(tax_row, "add_deduct_tax"):
        tax_row.add_deduct_tax = "Add"

    for fieldname in ("cost_center", "project"):
        if hasattr(tax_row, fieldname) and hasattr(default_tax_row, fieldname):
            setattr(tax_row, fieldname, getattr(default_tax_row, fieldname))


def _clear_advance_deduction_derived_fields(doc) -> None:
    """Clear values derived from applying advances to a positive final invoice."""
    _sync_detail_table(doc, [])

    field_defaults = {
        "custom_zatca_prepaid_amount": 0.0,
        "custom_zatca_advance_deducted_taxable_amount": 0.0,
        "custom_zatca_advance_deducted_vat_amount": 0.0,
        "custom_zatca_advance_deduction_count": 0,
    }

    for fieldname, value in field_defaults.items():
        if hasattr(doc, fieldname):
            setattr(doc, fieldname, value)


def validate_sales_invoice_advance_deductions(doc, event=None) -> None:
    if int(getattr(doc, "docstatus", 0) or 0) == 2:
        return

    if _is_return_invoice(doc):
        if _get_positive_zatca_advance_allocations(doc):
            frappe.throw(
                _(
                    "ZATCA advance deductions cannot be applied directly to a return "
                    "or credit note. Remove the positive ZATCA advance allocation; "
                    "advance reversal is handled separately."
                )
            )

        _remove_existing_zatca_advance_vat_deduction_rows(doc)

        if hasattr(doc, "calculate_taxes_and_totals"):
            doc.calculate_taxes_and_totals()

        _clear_advance_deduction_derived_fields(doc)
        return

    if is_advance_payment_invoice(doc) and _get_positive_zatca_advance_allocations(doc):
        frappe.throw(
            _(
                "A Sales Invoice cannot be both an advance payment invoice and a "
                "final invoice that deducts an earlier ZATCA advance. Clear the "
                "advance-payment marker or remove the positive ZATCA advance allocation."
            )
        )

    _remove_existing_zatca_advance_vat_deduction_rows(doc)

    rows = get_standard_advance_deduction_rows(
        doc,
        strict=bool(int(getattr(doc, "docstatus", 0) or 0) == 1),
    )
    active_rows = [
        row for row in rows
        if row["allocated_total_amount"] > Decimal("0.00")
    ]

    total_taxable = q2(sum((row["allocated_taxable_amount"] for row in active_rows), Decimal("0.00")))
    total_tax = q2(sum((row["allocated_tax_amount"] for row in active_rows), Decimal("0.00")))
    total_inclusive = q2(sum((row["allocated_total_amount"] for row in active_rows), Decimal("0.00")))

    original_positive_vat = _get_positive_invoice_vat_amount(doc)
    original_tax_inclusive = q2(q2(getattr(doc, "net_total", 0)) + original_positive_vat)

    if active_rows and total_tax > original_positive_vat:
        frappe.throw(
            _(
                "ZATCA advance VAT deduction cannot exceed the Sales Invoice VAT amount. "
                "Advance VAT {0}, Sales Invoice VAT {1}."
            ).format(total_tax, original_positive_vat)
        )

    if active_rows and total_inclusive > original_tax_inclusive:
        frappe.throw(
            _(
                "ZATCA advance deduction cannot exceed the Sales Invoice total including VAT. "
                "Advance total {0}, Sales Invoice total {1}."
            ).format(total_inclusive, original_tax_inclusive)
        )

    _sync_advance_rows_allocated_amounts(doc, active_rows)
    _sync_detail_table(doc, rows)
    _append_negative_vat_deduction_tax_row(doc, active_rows)

    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()

    if hasattr(doc, "custom_zatca_prepaid_amount"):
        doc.custom_zatca_prepaid_amount = float(total_inclusive)

    if hasattr(doc, "custom_zatca_advance_deducted_taxable_amount"):
        doc.custom_zatca_advance_deducted_taxable_amount = float(total_taxable)

    if hasattr(doc, "custom_zatca_advance_deducted_vat_amount"):
        doc.custom_zatca_advance_deducted_vat_amount = float(total_tax)

    if hasattr(doc, "custom_zatca_advance_deduction_count"):
        doc.custom_zatca_advance_deduction_count = len(active_rows)


def ensure_final_sales_invoice_qr_for_print(doc, event=None, force=False):
    from frappe.utils import flt
    """Generate an advance-aware QR image into Sales Invoice.ksa_einv_qr.

    This keeps existing print formats stable because they continue using doc.ksa_einv_qr.

    Applies only when:
    - DocType is Sales Invoice.
    - Document is submitted.
    - Sales Invoice has custom_zatca_advance_deducted_taxable_amount > 0.
    - ksa_einv_qr field exists.

    The QR total is aligned with the final printed amount due after deducting
    the advance taxable amount and adding the remaining VAT.
    """
    if getattr(doc, "doctype", None) != "Sales Invoice":
        return

    if int(getattr(doc, "docstatus", 0) or 0) != 1:
        return

    if not doc.meta.has_field("ksa_einv_qr"):
        return

    advance_taxable = flt(doc.get("custom_zatca_advance_deducted_taxable_amount") or 0)
    if advance_taxable <= 0:
        return

    current_qr = str(doc.get("ksa_einv_qr") or "")
    if current_qr and "QR-ZATCA-Advance-Aware-" in current_qr and not force:
        return

    import base64
    import io
    from datetime import datetime

    import pyqrcode
    from frappe.utils import getdate, get_time
    from frappe.utils.file_manager import save_file

    company = frappe.get_doc("Company", doc.company)

    seller_name = (
        company.get("company_name_in_arabic")
        or company.get("custom_company_name_in_arabic")
        or company.company_name
    )

    vat_number = company.get("tax_id")
    if not vat_number:
        frappe.throw("Company Tax ID is required to generate ZATCA QR.")

    posting_date = getdate(doc.posting_date)
    posting_time = get_time(doc.get("posting_time") or "00:00:00")
    timestamp = datetime.combine(posting_date, posting_time).strftime("%Y-%m-%dT%H:%M:%SZ")

    conversion_rate = flt(doc.get("conversion_rate") or 1)

    taxable_source = flt(doc.get("net_total") if doc.get("discount_amount") else doc.get("total"))
    base_taxable_source = flt(doc.get("base_net_total") if doc.get("discount_amount") else doc.get("base_total"))

    base_advance_taxable = advance_taxable * conversion_rate

    final_amount_due = taxable_source - advance_taxable + flt(doc.get("total_taxes_and_charges") or 0)
    base_final_amount_due = base_taxable_source - base_advance_taxable + flt(doc.get("base_total_taxes_and_charges") or 0)

    if doc.currency == "SAR":
        qr_invoice_total = final_amount_due
        qr_vat_total = flt(doc.get("total_taxes_and_charges") or 0)
    else:
        qr_invoice_total = base_final_amount_due
        qr_vat_total = flt(doc.get("base_total_taxes_and_charges") or 0)

    def tlv(tag, value):
        value = str(value or "").encode("utf-8")
        if len(value) > 255:
            frappe.throw(f"ZATCA QR TLV value for tag {tag} is too long.")
        return bytes([tag, len(value)]) + value

    payload = base64.b64encode(
        b"".join([
            tlv(1, seller_name),
            tlv(2, vat_number),
            tlv(3, timestamp),
            tlv(4, f"{qr_invoice_total:.2f}"),
            tlv(5, f"{qr_vat_total:.2f}"),
        ])
    ).decode("utf-8")

    png = io.BytesIO()
    pyqrcode.create(payload, error="L").png(png, scale=4, quiet_zone=1)

    file_name = f"QR-ZATCA-Advance-Aware-{doc.name}.png"

    file_doc = save_file(
        file_name,
        png.getvalue(),
        "Sales Invoice",
        doc.name,
        is_private=0,
    )

    file_doc.attached_to_field = "ksa_einv_qr"
    file_doc.save(ignore_permissions=True)

    frappe.db.set_value(
        "Sales Invoice",
        doc.name,
        "ksa_einv_qr",
        file_doc.file_url,
        update_modified=False,
    )

    doc.ksa_einv_qr = file_doc.file_url
