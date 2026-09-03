from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.accounts.utils import get_currency_precision

from zatca_erpgulf.ksa_compliance.tax_templates import make_template_name
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    is_advance_payment_invoice,
    supports_advance_deduction_schema,
    supports_advance_payment_entry_link,
)


VAT_RATE = Decimal("15")
KSA_VAT_TEMPLATE_TITLE = "KSA VAT 15%"
ADVANCE_ITEM_NAME = "Advance Payment"
DEFAULT_UOM = "Nos"
PAYMENT_ENTRY_AMOUNT_LIMIT_FIELD = "custom_enforce_zatca_payment_entry_amount_limit"


def _payment_entry_amount_limit_enabled(company: str) -> bool:
    """Return the opt-in Company gate for the Payment Entry upper-limit check."""
    if not company:
        return False
    try:
        if not frappe.get_meta("Company").has_field(PAYMENT_ENTRY_AMOUNT_LIMIT_FIELD):
            return False
        return bool(cint(frappe.db.get_value("Company", company, PAYMENT_ENTRY_AMOUNT_LIMIT_FIELD) or 0))
    except Exception:
        return False


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _quantum(precision: int) -> Decimal:
    return Decimal("1").scaleb(-max(cint(precision), 0))


def _rounded(value: Any, precision: int) -> Decimal:
    return _decimal(value).quantize(_quantum(precision), rounding=ROUND_HALF_UP)


def split_tax_inclusive_amount(
    gross_amount: Any,
    tax_rate: Any = VAT_RATE,
    precision: int = 2,
) -> dict[str, Decimal]:
    """Split a tax-inclusive amount without losing the original gross total."""
    gross = _rounded(gross_amount, precision)
    rate = _decimal(tax_rate)

    if gross <= 0:
        raise ValueError("Gross amount must be greater than zero.")
    if rate < 0:
        raise ValueError("Tax rate cannot be negative.")

    divisor = Decimal("1") + (rate / Decimal("100"))
    taxable = _rounded(gross / divisor, precision)
    tax = gross - taxable

    return {
        "gross": gross,
        "taxable": taxable,
        "tax": tax,
        "rate": rate,
    }


def _payment_entry_mapping(payment_entry) -> dict[str, Any]:
    """Return the customer-side amount and exchange rate for a Receive entry."""
    return {
        "company": payment_entry.company,
        "customer": payment_entry.party,
        "posting_date": payment_entry.posting_date,
        "currency": payment_entry.paid_from_account_currency,
        "gross_amount": _decimal(payment_entry.paid_amount),
        "base_gross_amount": _decimal(payment_entry.base_paid_amount),
        "conversion_rate": _decimal(payment_entry.source_exchange_rate),
        "received_amount": _decimal(payment_entry.received_amount),
        "base_received_amount": _decimal(payment_entry.base_received_amount),
        "target_exchange_rate": _decimal(payment_entry.target_exchange_rate),
    }


def _money_tolerance(precision: int) -> Decimal:
    return _quantum(precision) / Decimal("2")


def _amounts_match(left: Any, right: Any, precision: int) -> bool:
    return abs(_decimal(left) - _decimal(right)) <= _money_tolerance(precision)


def _invoice_payment_total(invoice) -> Decimal:
    """Return the receivable total used by ERPNext after currency rounding."""
    if not cint(invoice.get("disable_rounded_total")):
        rounded_total = _decimal(invoice.get("rounded_total"))
        if rounded_total:
            return rounded_total
    return _decimal(invoice.get("grand_total"))


def _currency_precision() -> int:
    return cint(get_currency_precision() or 2)


def _has_nonzero_payment_entry_tax(payment_entry, precision: int) -> bool:
    if not _amounts_match(
        getattr(payment_entry, "total_taxes_and_charges", 0), 0, precision
    ):
        return True
    if not _amounts_match(
        getattr(payment_entry, "base_total_taxes_and_charges", 0), 0, precision
    ):
        return True

    return bool(getattr(payment_entry, "taxes", None) or [])


def _validate_payment_entry_identity(payment_entry) -> dict[str, Any]:
    precision = _currency_precision()

    if cint(payment_entry.docstatus) != 1:
        frappe.throw(
            _("Payment Entry must be submitted before creating an advance payment invoice.")
        )
    if payment_entry.payment_type != "Receive":
        frappe.throw(_("Only Receive Payment Entries can create advance payment invoices."))
    if payment_entry.party_type != "Customer" or not payment_entry.party:
        frappe.throw(_("Payment Entry must have Party Type Customer and a Customer."))
    if not payment_entry.company:
        frappe.throw(_("Company is required on Payment Entry."))

    mapping = _payment_entry_mapping(payment_entry)
    if mapping["gross_amount"] <= 0:
        frappe.throw(_("Payment Entry paid amount must be greater than zero."))
    if not mapping["currency"]:
        frappe.throw(_("Customer account currency is required on Payment Entry."))
    if mapping["conversion_rate"] <= 0:
        frappe.throw(_("Payment Entry source exchange rate must be greater than zero."))

    if _has_nonzero_payment_entry_tax(payment_entry, precision):
        frappe.throw(
            _(
                "VAT must be recorded only on the advance Sales Invoice. Remove taxes from the Payment Entry first."
            )
        )

    return mapping


def _validate_payment_entry_source(payment_entry) -> dict[str, Any]:
    precision = _currency_precision()
    mapping = _validate_payment_entry_identity(payment_entry)

    if not _amounts_match(
        getattr(payment_entry, "total_allocated_amount", 0), 0, precision
    ):
        frappe.throw(
            _(
                "Payment Entry cannot be used because some or all of its amount is already allocated."
            )
        )

    if not _amounts_match(
        getattr(payment_entry, "unallocated_amount", 0),
        mapping["gross_amount"],
        precision,
    ):
        frappe.throw(
            _(
                "The full Payment Entry paid amount must remain unallocated before creating an advance payment invoice."
            )
        )

    return mapping


def _is_allowed_final_invoice_allocation(reference_name: str, advance_invoice: str) -> bool:
    if not reference_name or not supports_advance_deduction_schema():
        return False

    if cint(frappe.db.get_value("Sales Invoice", reference_name, "docstatus") or 0) != 1:
        return False

    return bool(
        frappe.db.exists(
            "ZATCA Sales Invoice Advance Deduction",
            {
                "parent": reference_name,
                "parenttype": "Sales Invoice",
                "parentfield": "custom_zatca_advance_deduction_details",
                "advance_invoice": advance_invoice,
            },
        )
    )


def _validate_existing_link_allocations(payment_entry, sales_invoice_name: str) -> None:
    for row in getattr(payment_entry, "references", None) or []:
        if not _decimal(getattr(row, "allocated_amount", 0)):
            continue
        if (
            getattr(row, "reference_doctype", None) == "Sales Invoice"
            and _is_allowed_final_invoice_allocation(
                str(getattr(row, "reference_name", "") or ""),
                sales_invoice_name,
            )
        ):
            continue
        frappe.throw(
            _(
                "The Payment Entry linked to advance payment Sales Invoice {0} may be "
                "allocated only to a submitted final Sales Invoice that consumes that advance."
            ).format(sales_invoice_name)
        )


def _sales_invoice_link_field_exists() -> bool:
    return supports_advance_payment_entry_link()


def get_active_standard_advance_invoice(payment_entry_name: str, exclude: str = "") -> str:
    if not payment_entry_name or not _sales_invoice_link_field_exists():
        return ""

    filters: dict[str, Any] = {
        "custom_zatca_payment_entry": payment_entry_name,
        "docstatus": ["<", 2],
    }
    if exclude:
        filters["name"] = ["!=", exclude]

    return (
        frappe.db.get_value(
            "Sales Invoice",
            filters,
            "name",
            order_by="creation asc",
        )
        or ""
    )


def ensure_payment_entry_has_no_active_standard_advance_invoice(
    payment_entry_name: str,
    exclude: str = "",
) -> None:
    if not supports_advance_payment_entry_link():
        return

    if payment_entry_name and frappe.db.exists("Payment Entry", payment_entry_name):
        frappe.db.sql(
            "select name from `tabPayment Entry` where name = %s for update",
            payment_entry_name,
        )

    existing = get_active_standard_advance_invoice(payment_entry_name, exclude=exclude)
    if existing:
        frappe.throw(
            _("Payment Entry {0} is already linked to active Sales Invoice {1}.").format(
                payment_entry_name,
                existing,
            )
        )


def _get_preferred_deferred_revenue_account(company_doc) -> str:
    company_meta = frappe.get_meta("Company")
    if not company_meta.has_field("default_deferred_revenue_account"):
        return ""

    account = getattr(company_doc, "default_deferred_revenue_account", None)
    if not account:
        return ""

    return account


def _ensure_standard_advance_payment_item() -> None:
    if frappe.db.exists("Item", ADVANCE_ITEM_NAME):
        return

    from zatca_erpgulf.setup_customizations import ensure_advance_payment_item

    ensure_advance_payment_item()
    if not frappe.db.exists("Item", ADVANCE_ITEM_NAME):
        frappe.throw(
            _(
                "Item {0} could not be created. Verify that the standard UOM and Item Group exist."
            ).format(ADVANCE_ITEM_NAME)
        )


def _get_ksa_vat_15_template(company_doc):
    canonical_name = make_template_name(KSA_VAT_TEMPLATE_TITLE, company_doc)
    template_name = canonical_name if frappe.db.exists(
        "Sales Taxes and Charges Template", canonical_name
    ) else frappe.db.get_value(
        "Sales Taxes and Charges Template",
        {
            "company": company_doc.name,
            "title": KSA_VAT_TEMPLATE_TITLE,
            "disabled": 0,
        },
        "name",
    )

    if not template_name:
        frappe.throw(
            _(
                "KSA VAT 15% Sales Taxes and Charges Template is missing for "
                "Company {0}. Use Create Tax Template from the Company form first."
            ).format(company_doc.name)
        )

    template = frappe.get_doc("Sales Taxes and Charges Template", template_name)
    active_rows = [row for row in template.taxes if flt(row.rate)]
    if (
        cint(getattr(template, "disabled", 0))
        or template.company != company_doc.name
        or len(active_rows) != 1
        or active_rows[0].charge_type != "On Net Total"
        or _decimal(active_rows[0].rate) != VAT_RATE
        or not active_rows[0].account_head
    ):
        frappe.throw(
            _(
                "Sales Taxes and Charges Template {0} must contain one enabled On Net Total VAT row at 15%."
            ).format(template.name)
        )

    return template


def _copy_tax_template_rows(invoice, tax_template) -> None:
    invoice.taxes_and_charges = tax_template.name
    invoice.set("taxes", [])

    for source_row in tax_template.taxes:
        values = source_row.as_dict() if hasattr(source_row, "as_dict") else dict(source_row)
        for key in ("name", "parent", "parentfield", "parenttype", "doctype", "idx"):
            values.pop(key, None)
        values["included_in_print_rate"] = 0
        values["tax_amount"] = 0
        values["base_tax_amount"] = 0
        invoice.append("taxes", values)


def _set_advance_marker(invoice) -> None:
    if invoice.meta.has_field("is_advance_payment"):
        invoice.is_advance_payment = 1
        return
    if invoice.meta.has_field("custom_is_advance_payment"):
        invoice.custom_is_advance_payment = 1
        return

    frappe.throw(_("Advance payment marker is missing from Sales Invoice."))


def _copy_customer_zatca_fields(invoice, customer_name: str) -> None:
    """Copy customer identity fields into an auto-created advance invoice.

    ERPNext's fetch fields are not guaranteed to run when a document is built
    server-side.  Sites also have legacy Arabic-name field variants, so resolve
    the first populated source and only write fields that exist on the invoice.
    """
    customer = frappe.get_cached_doc("Customer", customer_name)
    if invoice.meta.has_field("tax_id"):
        invoice.tax_id = str(getattr(customer, "tax_id", "") or "").strip()

    arabic_name = ""
    for fieldname in (
        "customer_name_in_arabic",
        "custom_customer_name_in_arabic",
        "zatca_customer_name_in_arabic",
    ):
        if getattr(customer, fieldname, None):
            arabic_name = str(getattr(customer, fieldname)).strip()
            if arabic_name:
                break

    if arabic_name:
        for fieldname in (
            "customer_name_in_arabic",
            "custom_customer_name_in_arabic",
            "zatca_customer_name_in_arabic",
        ):
            if invoice.meta.has_field(fieldname):
                setattr(invoice, fieldname, arabic_name)


def _require_create_permissions(payment_entry) -> None:
    if not frappe.has_permission("Payment Entry", "read", doc=payment_entry):
        frappe.throw(_("Not permitted to read this Payment Entry."), frappe.PermissionError)
    if not frappe.has_permission("Sales Invoice", "create"):
        frappe.throw(_("Not permitted to create Sales Invoice."), frappe.PermissionError)


def _build_advance_sales_invoice(payment_entry, mapping: dict[str, Any]):
    company_doc = frappe.get_cached_doc("Company", mapping["company"])
    deferred_account = _get_preferred_deferred_revenue_account(company_doc)
    tax_template = _get_ksa_vat_15_template(company_doc)

    if not frappe.db.exists("UOM", DEFAULT_UOM):
        frappe.throw(_("Standard UOM {0} is missing.").format(DEFAULT_UOM))
    _ensure_standard_advance_payment_item()

    item_disabled = cint(frappe.db.get_value("Item", ADVANCE_ITEM_NAME, "disabled") or 0)
    if item_disabled:
        frappe.throw(_("Item {0} is disabled.").format(ADVANCE_ITEM_NAME))

    precision = _currency_precision()
    split = split_tax_inclusive_amount(mapping["gross_amount"], VAT_RATE, precision)
    translated_item_name = _(ADVANCE_ITEM_NAME)

    invoice = frappe.new_doc("Sales Invoice")
    invoice.company = mapping["company"]
    invoice.customer = mapping["customer"]
    invoice.posting_date = mapping["posting_date"]
    invoice.currency = mapping["currency"]
    invoice.conversion_rate = flt(mapping["conversion_rate"])
    invoice.custom_zatca_payment_entry = payment_entry.name
    invoice.set_posting_time = 1
    invoice.update_stock = 0

    _set_advance_marker(invoice)
    invoice.run_method("set_missing_values")
    _copy_customer_zatca_fields(invoice, mapping["customer"])
    if invoice.meta.has_field("disable_rounded_total"):
        invoice.disable_rounded_total = 0

    invoice.company = mapping["company"]
    invoice.customer = mapping["customer"]
    invoice.posting_date = mapping["posting_date"]
    invoice.currency = mapping["currency"]
    invoice.conversion_rate = flt(mapping["conversion_rate"])
    invoice.custom_zatca_payment_entry = payment_entry.name

    invoice.append(
        "items",
        {
            "item_code": ADVANCE_ITEM_NAME,
            "item_name": translated_item_name,
            "description": translated_item_name,
            "qty": 1,
            "uom": DEFAULT_UOM,
            "conversion_factor": 1,
            "rate": flt(split["taxable"]),
            "price_list_rate": flt(split["taxable"]),
            "income_account": deferred_account or None,
            "cost_center": getattr(company_doc, "cost_center", None),
        },
    )
    _copy_tax_template_rows(invoice, tax_template)
    invoice.run_method("calculate_taxes_and_totals")

    if not _amounts_match(_invoice_payment_total(invoice), split["gross"], precision):
        frappe.throw(
            _(
                "Generated advance invoice payable total {0} does not match Payment Entry amount {1}."
            ).format(_invoice_payment_total(invoice), split["gross"])
        )

    return invoice


@frappe.whitelist()
def create_advance_sales_invoice_from_payment_entry(payment_entry_name: str) -> dict:
    if not supports_advance_payment_entry_link():
        return {}

    if not payment_entry_name:
        frappe.throw(_("Payment Entry name is required."))

    payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
    _require_create_permissions(payment_entry)
    mapping = _validate_payment_entry_source(payment_entry)
    ensure_payment_entry_has_no_active_standard_advance_invoice(payment_entry.name)

    invoice = _build_advance_sales_invoice(payment_entry, mapping)
    return invoice.as_dict()


def validate_sales_invoice_payment_entry_link(doc, event=None) -> None:
    if not supports_advance_payment_entry_link(doc):
        return

    payment_entry_name = doc.get("custom_zatca_payment_entry")
    if not payment_entry_name:
        return

    if not is_advance_payment_invoice(doc):
        frappe.throw(
            _("ZATCA Payment Entry can be linked only to an advance payment invoice.")
        )

    payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
    mapping = _validate_payment_entry_identity(payment_entry)
    _validate_existing_link_allocations(payment_entry, doc.name or "")
    ensure_payment_entry_has_no_active_standard_advance_invoice(
        payment_entry_name,
        exclude=doc.name or "",
    )

    if doc.company != mapping["company"]:
        frappe.throw(_("Sales Invoice Company must match Payment Entry Company."))
    if doc.customer != mapping["customer"]:
        frappe.throw(_("Sales Invoice Customer must match Payment Entry Customer."))

    precision = _currency_precision()
    if doc.currency != mapping["currency"]:
        frappe.throw(
            _("Sales Invoice currency must match the Payment Entry customer account currency.")
        )
    if not _amounts_match(doc.conversion_rate, mapping["conversion_rate"], 9):
        frappe.throw(_("Sales Invoice exchange rate must match Payment Entry source exchange rate."))
    invoice_total = _invoice_payment_total(doc)
    if (
        _payment_entry_amount_limit_enabled(doc.company)
        and mapping["gross_amount"] > invoice_total + _money_tolerance(precision)
    ):
        frappe.throw(
            _(
                "ZATCA Payment Entry amount {0} cannot be greater than the Sales Invoice total including VAT {1}."
            ).format(mapping["gross_amount"], invoice_total)
        )

    if not _amounts_match(invoice_total, mapping["gross_amount"], precision):
        frappe.throw(_("Sales Invoice payable total must match the full Payment Entry paid amount."))


def validate_payment_entry_advance_allocations(doc, event=None) -> None:
    """Protect a linked payment from allocation to its advance or unrelated invoices."""
    if not supports_advance_payment_entry_link():
        return

    advance_invoice = get_active_standard_advance_invoice(str(getattr(doc, "name", "") or ""))
    if advance_invoice:
        _validate_existing_link_allocations(doc, advance_invoice)
