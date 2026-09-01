from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.advance_lifecycle import (
    ACCEPTED_ZATCA_ADVANCE_STATUSES,
    is_accepted_advance_sales_invoice,
)
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    PHASE_2_VALUE,
    is_advance_payment_invoice,
    is_zatca_invoice_enabled,
    resolve_zatca_phase,
    supports_advance_deduction_schema,
)

ZATCA_ADVANCE_VAT_DEDUCTION_MARKER = "[ZATCA Advance VAT Deduction]"
DETAIL_FIELD = "custom_zatca_advance_deduction_details"
DETAIL_DOCTYPE = "ZATCA Sales Invoice Advance Deduction"
AMOUNT_TOLERANCE = Decimal("0.01")


def q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _is_return_invoice(doc) -> bool:
    return int(getattr(doc, "is_return", 0) or 0) == 1


def _row_value(row, fieldname, default=None):
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(fieldname, default)
    return getattr(row, fieldname, default)


def _detail_rows(doc) -> list:
    getter = getattr(doc, "get", None)
    if callable(getter):
        return list(getter(DETAIL_FIELD, []) or [])
    return list(getattr(doc, DETAIL_FIELD, []) or [])


def _set_row_value(row, fieldname, value) -> None:
    setter = getattr(row, "set", None)
    if callable(setter):
        setter(fieldname, value)
    else:
        setattr(row, fieldname, value)


def _is_zatca_advance_vat_deduction_tax(row) -> bool:
    return ZATCA_ADVANCE_VAT_DEDUCTION_MARKER in str(getattr(row, "description", "") or "")


def _remove_existing_zatca_advance_vat_deduction_rows(doc) -> None:
    taxes = []
    for row in doc.get("taxes", []) or []:
        if not _is_zatca_advance_vat_deduction_tax(row):
            taxes.append(row)

    doc.set("taxes", taxes)


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

    invoice_rate = q2(getattr(sales_invoice_doc, "conversion_rate", 1) or 1)
    advance_rate = q2(getattr(advance, "conversion_rate", 1) or 1)
    if invoice_rate != advance_rate:
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} exchange rate is {1}, but this "
                "Sales Invoice exchange rate is {2}."
            ).format(advance.name, advance_rate, invoice_rate)
        )


def _advance_taxable_amount(advance) -> Decimal:
    net_total = getattr(advance, "net_total", None)
    return q2(net_total if net_total is not None else getattr(advance, "total", 0))


def _tax_amount_after_discount(tax) -> Decimal:
    amount = getattr(tax, "tax_amount_after_discount_amount", None)
    return q2(amount if amount is not None else getattr(tax, "tax_amount", 0))


def _advance_tax_amount(advance) -> Decimal:
    tax_rows = [
        tax
        for tax in advance.get("taxes", []) or []
        if str(getattr(tax, "account_head", "") or "").strip()
    ]
    if tax_rows:
        return q2(sum((_tax_amount_after_discount(tax) for tax in tax_rows), Decimal("0.00")))
    return q2(getattr(advance, "total_taxes_and_charges", 0))


def _advance_total_amount(advance) -> Decimal:
    """Return the actual receivable total after ERPNext currency rounding."""
    if not int(getattr(advance, "disable_rounded_total", 0) or 0):
        rounded_total = q2(getattr(advance, "rounded_total", 0))
        if rounded_total:
            return rounded_total
    return q2(getattr(advance, "grand_total", 0))


def _submitted_credit_note_total(advance_invoice: str) -> Decimal:
    rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 1,
            "return_against": advance_invoice,
        },
        fields=["grand_total"],
    )
    return q2(sum((abs(q2(_row_value(row, "grand_total", 0))) for row in rows), Decimal("0.00")))


def _submitted_final_allocation_total(
    advance_invoice: str,
    *,
    exclude_sales_invoice: str | None = None,
) -> Decimal:
    if not supports_advance_deduction_schema():
        return Decimal("0.00")

    exclude_sql = ""
    if exclude_sales_invoice:
        exclude_sql = " and parent_invoice.name != %s"

    result = frappe.db.sql(
        f"""
        select coalesce(sum(detail.allocated_total_amount), 0)
          from `tab{DETAIL_DOCTYPE}` detail
          inner join `tabSales Invoice` parent_invoice
                  on parent_invoice.name = detail.parent
                 and detail.parenttype = 'Sales Invoice'
                 and detail.parentfield = %s
         where detail.advance_invoice = %s
           and parent_invoice.docstatus = 1
           {exclude_sql}
        """,
        [DETAIL_FIELD, advance_invoice]
        + ([exclude_sales_invoice] if exclude_sales_invoice else []),
    )
    return q2(result[0][0] if result else 0)


def get_advance_available_amount(
    advance,
    *,
    exclude_sales_invoice: str | None = None,
) -> Decimal:
    if not supports_advance_deduction_schema():
        return Decimal("0.00")

    available = (
        _advance_total_amount(advance)
        - _submitted_credit_note_total(advance.name)
        - _submitted_final_allocation_total(
            advance.name,
            exclude_sales_invoice=exclude_sales_invoice,
        )
    )
    return max(q2(available), Decimal("0.00"))


def _advance_marker_field() -> str:
    meta = frappe.get_meta("Sales Invoice")
    return (
        "is_advance_payment"
        if meta.has_field("is_advance_payment")
        else "custom_is_advance_payment"
    )


def populate_zatca_advance_deductions(sales_invoice_doc) -> list:
    """Rebuild ZATCA deductions independently of standard cash advances.

    ERPNext calls ``set_advances`` only when Allocate Advances Automatically is
    enabled. The Sales Invoice override calls this function after ERPNext has
    completed its standard allocation. Eligibility here depends on accepted
    ZATCA advance Sales Invoices and their unused tax-inclusive balance; it does
    not depend on Payment Entry allocation state.
    """
    if not supports_advance_deduction_schema(sales_invoice_doc):
        return []

    if (
        _is_return_invoice(sales_invoice_doc)
        or is_advance_payment_invoice(sales_invoice_doc)
        or not getattr(sales_invoice_doc, "meta", None)
        or not sales_invoice_doc.meta.has_field(DETAIL_FIELD)
    ):
        return []

    sales_invoice_doc.set(DETAIL_FIELD, [])

    remaining_final_total = q2(getattr(sales_invoice_doc, "grand_total", 0))
    if remaining_final_total <= 0:
        return []

    company = str(getattr(sales_invoice_doc, "company", "") or "").strip()
    customer = str(getattr(sales_invoice_doc, "customer", "") or "").strip()
    currency = str(getattr(sales_invoice_doc, "currency", "") or "").strip()
    if not company or not customer or not currency:
        return []

    candidates = frappe.get_list(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            _advance_marker_field(): 1,
            "custom_zatca_status": [
                "in",
                sorted(ACCEPTED_ZATCA_ADVANCE_STATUSES),
            ],
            "company": company,
            "customer": customer,
            "currency": currency,
        },
        fields=["name"],
        order_by="posting_date asc, posting_time asc, name asc",
        limit_page_length=0,
    )

    populated_rows = []
    current_invoice = str(getattr(sales_invoice_doc, "name", "") or "").strip()
    final_rate = q2(getattr(sales_invoice_doc, "conversion_rate", 1) or 1)

    for candidate in candidates:
        if remaining_final_total <= 0:
            break

        advance_invoice = str(_row_value(candidate, "name", "") or "").strip()
        if not advance_invoice or advance_invoice == current_invoice:
            continue

        advance = frappe.get_doc("Sales Invoice", advance_invoice)
        if not is_accepted_advance_sales_invoice(advance):
            continue

        if (
            getattr(advance, "company", None) != company
            or getattr(advance, "customer", None) != customer
            or getattr(advance, "currency", None) != currency
            or q2(getattr(advance, "conversion_rate", 1) or 1) != final_rate
        ):
            continue

        available = get_advance_available_amount(
            advance,
            exclude_sales_invoice=current_invoice or None,
        )
        allocated_total = min(available, remaining_final_total)
        if allocated_total <= 0:
            continue

        row = sales_invoice_doc.append(
            DETAIL_FIELD,
            {
                "payment_entry": str(advance.get("custom_zatca_payment_entry") or "").strip() or None,
                "advance_invoice": advance_invoice,
                "advance_invoice_date": advance.get("posting_date"),
                "advance_status": advance.get("custom_zatca_status"),
                "currency": advance.get("currency"),
                "advance_total_amount": float(_advance_total_amount(advance)),
                "advance_taxable_amount": float(_advance_taxable_amount(advance)),
                "advance_tax_amount": float(_advance_tax_amount(advance)),
                "allocated_total_amount": float(allocated_total),
            },
        )
        populated_rows.append(row)
        remaining_final_total = q2(remaining_final_total - allocated_total)

    return populated_rows


def _lock_advance_invoice(advance_invoice: str) -> None:
    frappe.db.sql(
        "select name from `tabSales Invoice` where name = %s for update",
        advance_invoice,
    )


def _allocate_proportionally(total: Decimal, components: list[Decimal]) -> list[Decimal]:
    total = q2(total)
    source_total = sum(components, Decimal("0.00"))
    if total <= 0 or source_total <= 0:
        return [Decimal("0.00") for _ in components]

    allocated: list[Decimal] = []
    running = Decimal("0.00")
    for index, component in enumerate(components):
        if index == len(components) - 1:
            value = q2(total - running)
        else:
            value = q2(total * component / source_total)
            running += value
        allocated.append(value)
    return allocated


def _source_income_breakdown(advance, allocated_taxable: Decimal) -> list[dict]:
    source_rows = []
    for item in advance.get("items", []) or []:
        amount = q2(getattr(item, "net_amount", 0) or getattr(item, "amount", 0))
        if amount <= 0:
            continue
        account = str(getattr(item, "income_account", "") or "").strip()
        if not account:
            frappe.throw(
                _("Advance payment Sales Invoice {0} has an item without an Income Account.").format(
                    advance.name
                )
            )
        source_rows.append(
            {
                "account": account,
                "cost_center": getattr(item, "cost_center", None),
                "project": getattr(item, "project", None),
                "source_amount": amount,
            }
        )

    accounts = {row["account"] for row in source_rows}
    if not source_rows or len(accounts) != 1:
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} must contain one Income Account "
                "across all positive item rows."
            ).format(advance.name)
        )

    amounts = _allocate_proportionally(
        allocated_taxable,
        [row["source_amount"] for row in source_rows],
    )
    for row, amount in zip(source_rows, amounts):
        row["allocated_amount"] = amount
    return source_rows


def _source_tax_breakdown(advance, allocated_tax: Decimal) -> list[dict]:
    if allocated_tax <= 0:
        return []

    grouped: dict[tuple[str, str | None], Decimal] = defaultdict(Decimal)
    for tax in advance.get("taxes", []) or []:
        amount = _tax_amount_after_discount(tax)
        account = str(getattr(tax, "account_head", "") or "").strip()
        if amount > 0 and account:
            grouped[(account, getattr(tax, "cost_center", None))] += amount

    source_total = q2(sum(grouped.values(), Decimal("0.00")))
    expected_tax = _advance_tax_amount(advance)
    if not grouped or abs(source_total - expected_tax) > AMOUNT_TOLERANCE:
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} VAT amount cannot be mapped "
                "completely to its tax accounts."
            ).format(advance.name)
        )

    keys = list(grouped)
    amounts = _allocate_proportionally(
        allocated_tax,
        [q2(grouped[key]) for key in keys],
    )
    return [
        {
            "account": account,
            "cost_center": cost_center,
            "allocated_amount": amount,
        }
        for (account, cost_center), amount in zip(keys, amounts)
    ]


def _source_rounding_breakdown(advance, allocated_rounding: Decimal) -> list[dict]:
    allocated_rounding = q2(allocated_rounding)
    if not allocated_rounding:
        return []

    account = frappe.get_cached_value(
        "Company", advance.company, "round_off_account"
    )
    if not account:
        frappe.throw(
            _(
                "Company {0} requires a Round Off Account to allocate advance payment invoice {1}."
            ).format(advance.company, advance.name)
        )

    return [
        {
            "account": account,
            "cost_center": frappe.get_cached_value(
                "Company", advance.company, "round_off_cost_center"
            ),
            "allocated_amount": allocated_rounding,
        }
    ]


def _validate_and_enrich_row(
    sales_invoice_doc,
    row,
    *,
    lock: bool,
) -> dict:
    advance_invoice = str(_row_value(row, "advance_invoice", "") or "").strip()
    if not advance_invoice:
        frappe.throw(
            _("Row {0}: Advance Payment Invoice is required.").format(
                _row_value(row, "idx", "?")
            )
        )

    if advance_invoice == getattr(sales_invoice_doc, "name", None):
        frappe.throw(_("A Sales Invoice cannot allocate itself as an advance payment invoice."))

    if lock:
        _lock_advance_invoice(advance_invoice)

    if not frappe.db.exists("Sales Invoice", advance_invoice):
        frappe.throw(_("Sales Invoice not found: {0}").format(advance_invoice))

    advance = frappe.get_doc("Sales Invoice", advance_invoice)
    if not is_accepted_advance_sales_invoice(advance):
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} must be submitted, marked as an "
                "advance payment invoice, and have REPORTED, CLEARED, or Phase-1 "
                "QR Generated status."
            ).format(advance_invoice)
        )

    _validate_same_party_and_currency(sales_invoice_doc, advance)

    requested_total = q2(_row_value(row, "allocated_total_amount", 0))
    if requested_total <= 0:
        frappe.throw(
            _("Row {0}: Applied Total Incl. VAT must be greater than zero.").format(
                _row_value(row, "idx", "?")
            )
        )

    available = get_advance_available_amount(
        advance,
        exclude_sales_invoice=getattr(sales_invoice_doc, "name", None),
    )
    if requested_total > available + AMOUNT_TOLERANCE:
        frappe.throw(
            _(
                "Row {0}: Applied amount {1} exceeds the available balance {2} "
                "of advance payment Sales Invoice {3}."
            ).format(
                _row_value(row, "idx", "?"),
                requested_total,
                available,
                advance_invoice,
            )
        )

    advance_total = _advance_total_amount(advance)
    advance_taxable = _advance_taxable_amount(advance)
    advance_tax = _advance_tax_amount(advance)
    if advance_total <= 0 or advance_taxable <= 0:
        frappe.throw(
            _("Advance payment Sales Invoice {0} total must be greater than zero.").format(
                advance_invoice
            )
        )

    ratio = requested_total / advance_total
    allocated_taxable = q2(advance_taxable * ratio)
    allocated_tax = q2(advance_tax * ratio)
    allocated_rounding = q2(requested_total - allocated_taxable - allocated_tax)

    payment_entry = str(advance.get("custom_zatca_payment_entry") or "").strip()
    values = {
        "payment_entry": payment_entry or None,
        "advance_invoice_date": advance.get("posting_date"),
        "advance_status": advance.get("custom_zatca_status"),
        "currency": advance.get("currency"),
        "advance_total_amount": float(advance_total),
        "advance_taxable_amount": float(advance_taxable),
        "advance_tax_amount": float(advance_tax),
        "allocated_total_amount": float(requested_total),
        "allocated_taxable_amount": float(allocated_taxable),
        "allocated_tax_amount": float(allocated_tax),
        "remarks": _("Available after this allocation: {0}").format(
            q2(available - requested_total)
        ),
    }
    for fieldname, value in values.items():
        _set_row_value(row, fieldname, value)

    return {
        "advance": advance,
        "advance_invoice": advance_invoice,
        "allocated_total_amount": requested_total,
        "allocated_taxable_amount": allocated_taxable,
        "allocated_tax_amount": allocated_tax,
        "income_breakdown": _source_income_breakdown(advance, allocated_taxable),
        "tax_breakdown": _source_tax_breakdown(advance, allocated_tax),
        "rounding_breakdown": _source_rounding_breakdown(advance, allocated_rounding),
    }


def _clear_advance_deduction_derived_fields(doc) -> None:
    field_defaults = {
        "custom_zatca_prepaid_amount": 0.0,
        "custom_zatca_advance_deducted_taxable_amount": 0.0,
        "custom_zatca_advance_deducted_vat_amount": 0.0,
        "custom_zatca_advance_deduction_count": 0,
    }

    for fieldname, value in field_defaults.items():
        if hasattr(doc, fieldname):
            setattr(doc, fieldname, value)


def _validate_sales_invoice_advance_deductions(doc, *, lock: bool) -> list[dict]:
    if not supports_advance_deduction_schema(doc):
        if getattr(doc, "flags", None):
            doc.flags.zatca_direct_advance_rows = []
        return []

    if int(getattr(doc, "docstatus", 0) or 0) == 2:
        return []

    rows = _detail_rows(doc)

    # Remove draft residue created by the superseded Payment Entry implementation.
    tax_count_before = len(doc.get("taxes", []) or [])
    _remove_existing_zatca_advance_vat_deduction_rows(doc)
    if len(doc.get("taxes", []) or []) != tax_count_before and hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()

    if _is_return_invoice(doc):
        if rows:
            frappe.throw(
                _(
                    "ZATCA advance deductions cannot be applied directly to a return "
                    "or credit note. Remove the ZATCA advance deduction rows; "
                    "advance reversal is handled separately."
                )
            )
        _clear_advance_deduction_derived_fields(doc)
        return []

    if is_advance_payment_invoice(doc) and rows:
        frappe.throw(
            _(
                "A Sales Invoice cannot be both an advance payment invoice and a "
                "final invoice that deducts an earlier ZATCA advance. Clear the "
                "advance-payment marker or remove the ZATCA advance deduction rows."
            )
        )

    seen: set[str] = set()
    active_rows: list[dict] = []
    references = [
        str(_row_value(row, "advance_invoice", "") or "").strip()
        for row in rows
    ]
    if lock:
        for reference in sorted({value for value in references if value}):
            _lock_advance_invoice(reference)

    for row in rows:
        reference = str(_row_value(row, "advance_invoice", "") or "").strip()
        if reference and reference in seen:
            frappe.throw(
                _("Advance payment Sales Invoice {0} may appear only once in the deduction table.").format(
                    reference
                )
            )
        if reference:
            seen.add(reference)
        active_rows.append(_validate_and_enrich_row(doc, row, lock=False))

    total_taxable = q2(sum((row["allocated_taxable_amount"] for row in active_rows), Decimal("0.00")))
    total_tax = q2(sum((row["allocated_tax_amount"] for row in active_rows), Decimal("0.00")))
    total_inclusive = q2(sum((row["allocated_total_amount"] for row in active_rows), Decimal("0.00")))

    final_tax_inclusive = q2(getattr(doc, "grand_total", 0))
    if active_rows and total_inclusive > final_tax_inclusive + AMOUNT_TOLERANCE:
        frappe.throw(
            _(
                "ZATCA advance deduction cannot exceed the Sales Invoice total including VAT. "
                "Advance total {0}, Sales Invoice total {1}."
            ).format(total_inclusive, final_tax_inclusive)
        )

    if hasattr(doc, "custom_zatca_prepaid_amount"):
        doc.custom_zatca_prepaid_amount = float(total_inclusive)

    if hasattr(doc, "custom_zatca_advance_deducted_taxable_amount"):
        doc.custom_zatca_advance_deducted_taxable_amount = float(total_taxable)

    if hasattr(doc, "custom_zatca_advance_deducted_vat_amount"):
        doc.custom_zatca_advance_deducted_vat_amount = float(total_tax)

    if hasattr(doc, "custom_zatca_advance_deduction_count"):
        doc.custom_zatca_advance_deduction_count = len(active_rows)

    if not getattr(doc, "flags", None):
        doc.flags = frappe._dict()
    doc.flags.zatca_direct_advance_rows = active_rows
    return active_rows


def validate_sales_invoice_advance_deductions(doc, event=None) -> None:
    _validate_sales_invoice_advance_deductions(doc, lock=False)


def validate_sales_invoice_advance_deductions_on_submit(doc, event=None) -> None:
    """Recheck available balances under row locks immediately before submission."""
    _validate_sales_invoice_advance_deductions(doc, lock=True)


def get_direct_advance_deduction_rows(sales_invoice_doc, strict: bool = False) -> list[dict]:
    if not supports_advance_deduction_schema(sales_invoice_doc):
        return []

    if not _detail_rows(sales_invoice_doc):
        return []
    return _validate_sales_invoice_advance_deductions(
        sales_invoice_doc,
        lock=False,
    )


def get_direct_advance_prepaid_amount(sales_invoice_doc, strict: bool = False) -> Decimal:
    rows = get_direct_advance_deduction_rows(sales_invoice_doc, strict=strict)
    return q2(sum((row["allocated_total_amount"] for row in rows), Decimal("0.00")))


def append_advance_deduction_gl_entries(sales_invoice_doc, gl_entries: list) -> list:
    """Append the accounting release for directly allocated advance invoices.

    The original advance invoice credited its selected advance-income account and
    its VAT account. The final invoice therefore debits those same accounts and
    credits the customer's receivable by the applied tax-inclusive amount.
    """
    if not supports_advance_deduction_schema(sales_invoice_doc):
        return gl_entries

    if _is_return_invoice(sales_invoice_doc) or is_advance_payment_invoice(sales_invoice_doc):
        return gl_entries

    rows = getattr(
        getattr(sales_invoice_doc, "flags", None),
        "zatca_direct_advance_rows",
        None,
    )
    if rows is None:
        rows = get_direct_advance_deduction_rows(sales_invoice_doc, strict=False)
    if not rows:
        return gl_entries

    from erpnext.accounts.utils import get_account_currency

    company_currency = str(getattr(sales_invoice_doc, "company_currency", "") or "")
    invoice_currency = str(getattr(sales_invoice_doc, "currency", "") or "")
    conversion_rate = q2(getattr(sales_invoice_doc, "conversion_rate", 1) or 1)
    party_account_currency = str(
        getattr(sales_invoice_doc, "party_account_currency", "") or company_currency
    )

    def account_amount(account: str, transaction_amount: Decimal) -> tuple[Decimal, Decimal]:
        base_amount = q2(transaction_amount * conversion_rate)
        currency = get_account_currency(account)
        if currency == company_currency:
            return base_amount, base_amount
        if currency == invoice_currency:
            return base_amount, transaction_amount
        frappe.throw(
            _(
                "Account {0} currency {1} must match either Company Currency {2} "
                "or Sales Invoice Currency {3} for an advance deduction."
            ).format(account, currency, company_currency, invoice_currency)
        )

    custom_entries = []
    for allocation in rows:
        allocation_start = len(custom_entries)
        debit_accounts: list[str] = []

        for component in allocation["income_breakdown"]:
            amount = q2(component["allocated_amount"])
            if amount <= 0:
                continue
            account = component["account"]
            base_amount, amount_in_account_currency = account_amount(account, amount)
            debit_accounts.append(account)
            custom_entries.append(
                sales_invoice_doc.get_gl_dict(
                    {
                        "account": account,
                        "against": sales_invoice_doc.customer,
                        "debit": float(base_amount),
                        "debit_in_account_currency": float(amount_in_account_currency),
                        "debit_in_transaction_currency": float(amount),
                        "cost_center": component.get("cost_center"),
                        "project": component.get("project"),
                        "remarks": _("Advance allocation from {0}").format(
                            allocation["advance_invoice"]
                        ),
                    },
                    get_account_currency(account),
                    item=sales_invoice_doc,
                )
            )

        for component in allocation["tax_breakdown"]:
            amount = q2(component["allocated_amount"])
            if amount <= 0:
                continue
            account = component["account"]
            base_amount, amount_in_account_currency = account_amount(account, amount)
            debit_accounts.append(account)
            custom_entries.append(
                sales_invoice_doc.get_gl_dict(
                    {
                        "account": account,
                        "against": sales_invoice_doc.customer,
                        "debit": float(base_amount),
                        "debit_in_account_currency": float(amount_in_account_currency),
                        "debit_in_transaction_currency": float(amount),
                        "cost_center": component.get("cost_center"),
                        "remarks": _("Advance VAT allocation from {0}").format(
                            allocation["advance_invoice"]
                        ),
                    },
                    get_account_currency(account),
                    item=sales_invoice_doc,
                )
            )

        for component in allocation.get("rounding_breakdown", []):
            signed_amount = q2(component["allocated_amount"])
            if not signed_amount:
                continue
            account = component["account"]
            amount = abs(signed_amount)
            base_amount, amount_in_account_currency = account_amount(account, amount)
            values = {
                "account": account,
                "against": sales_invoice_doc.customer,
                "cost_center": component.get("cost_center"),
                "remarks": _("Advance rounding allocation from {0}").format(
                    allocation["advance_invoice"]
                ),
            }
            if signed_amount > 0:
                debit_accounts.append(account)
                values.update(
                    {
                        "debit": float(base_amount),
                        "debit_in_account_currency": float(amount_in_account_currency),
                        "debit_in_transaction_currency": float(amount),
                    }
                )
            else:
                values.update(
                    {
                        "credit": float(base_amount),
                        "credit_in_account_currency": float(amount_in_account_currency),
                        "credit_in_transaction_currency": float(amount),
                    }
                )
            custom_entries.append(
                sales_invoice_doc.get_gl_dict(
                    values,
                    get_account_currency(account),
                    item=sales_invoice_doc,
                )
            )

        gross_amount = q2(allocation["allocated_total_amount"])
        base_gross = q2(gross_amount * conversion_rate)
        allocation_entries = custom_entries[allocation_start:]
        base_net_debit = q2(
            sum(
                (
                    q2(entry.get("debit", 0)) - q2(entry.get("credit", 0))
                    for entry in allocation_entries
                ),
                Decimal("0.00"),
            )
        )
        base_rounding_delta = q2(base_gross - base_net_debit)
        if base_rounding_delta and allocation_entries:
            last_debit = next(
                (
                    entry
                    for entry in reversed(allocation_entries)
                    if q2(entry.get("debit", 0)) > 0
                ),
                None,
            )
            if not last_debit:
                frappe.throw(_("Advance deduction could not balance its base-currency entries."))
            last_debit["debit"] = float(
                q2(last_debit.get("debit", 0)) + base_rounding_delta
            )
            if last_debit.get("account_currency") == company_currency:
                last_debit["debit_in_account_currency"] = last_debit["debit"]

        if party_account_currency == company_currency:
            credit_in_account_currency = base_gross
        elif party_account_currency == invoice_currency:
            credit_in_account_currency = gross_amount
        else:
            frappe.throw(
                _(
                    "Customer account currency {0} must match either Company Currency {1} "
                    "or Sales Invoice Currency {2} for an advance deduction."
                ).format(party_account_currency, company_currency, invoice_currency)
            )

        custom_entries.append(
            sales_invoice_doc.get_gl_dict(
                {
                    "account": sales_invoice_doc.debit_to,
                    "party_type": "Customer",
                    "party": sales_invoice_doc.customer,
                    "against": ", ".join(sorted(set(debit_accounts))),
                    "credit": float(base_gross),
                    "credit_in_account_currency": float(credit_in_account_currency),
                    "credit_in_transaction_currency": float(gross_amount),
                    "against_voucher_type": "Sales Invoice",
                    "against_voucher": allocation["advance_invoice"],
                    "cost_center": getattr(sales_invoice_doc, "cost_center", None),
                    "project": getattr(sales_invoice_doc, "project", None),
                    "remarks": _("Advance payment applied from {0}").format(
                        allocation["advance_invoice"]
                    ),
                },
                party_account_currency,
                item=sales_invoice_doc,
            )
        )

    sales_invoice_doc.set_transaction_currency_and_rate_in_gl_map(custom_entries)
    gl_entries.extend(custom_entries)
    return gl_entries


def validate_advance_payment_invoice_cancellation(doc, event=None) -> None:
    """Do not cancel an advance while a submitted final invoice consumes it."""
    if not supports_advance_deduction_schema(doc) or not is_advance_payment_invoice(doc):
        return

    allocated = _submitted_final_allocation_total(str(getattr(doc, "name", "") or ""))
    if allocated > Decimal("0.00"):
        frappe.throw(
            _(
                "Advance payment Sales Invoice {0} is used by submitted final invoices "
                "for {1}. Cancel those final invoices first."
            ).format(doc.name, allocated)
        )


@frappe.whitelist()
def get_advance_allocation_details(advance_invoice: str, final_invoice: str | None = None):
    if not supports_advance_deduction_schema():
        return {}

    advance_invoice = str(advance_invoice or "").strip()
    if not advance_invoice or not frappe.db.exists("Sales Invoice", advance_invoice):
        frappe.throw(_("Sales Invoice not found: {0}").format(advance_invoice))

    advance = frappe.get_doc("Sales Invoice", advance_invoice)
    if not frappe.has_permission("Sales Invoice", "read", doc=advance):
        frappe.throw(_("Not permitted to read Sales Invoice {0}.").format(advance_invoice), frappe.PermissionError)
    if not is_accepted_advance_sales_invoice(advance):
        frappe.throw(_("Sales Invoice {0} is not an accepted advance payment invoice.").format(advance_invoice))

    return {
        "payment_entry": advance.get("custom_zatca_payment_entry"),
        "advance_invoice_date": advance.get("posting_date"),
        "advance_status": advance.get("custom_zatca_status"),
        "currency": advance.get("currency"),
        "advance_total_amount": float(_advance_total_amount(advance)),
        "advance_taxable_amount": float(_advance_taxable_amount(advance)),
        "advance_tax_amount": float(_advance_tax_amount(advance)),
        "available_amount": float(
            get_advance_available_amount(
                advance,
                exclude_sales_invoice=str(final_invoice or "").strip() or None,
            )
        ),
    }


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_available_advance_invoice_query(
    doctype,
    txt,
    searchfield,
    start,
    page_len,
    filters,
):
    """Link query for accepted advance invoices with a remaining direct balance."""
    if not supports_advance_deduction_schema():
        return []

    filters = frappe._dict(filters or {})
    # Never broaden an incomplete parent form into an all-customer query.
    if not str(filters.get("company") or "").strip() or not str(filters.get("customer") or "").strip():
        return []
    marker_field = _advance_marker_field()

    query_filters = {
        "docstatus": 1,
        "is_return": 0,
        marker_field: 1,
        "custom_zatca_status": [
            "in",
            sorted(ACCEPTED_ZATCA_ADVANCE_STATUSES),
        ],
        "name": ["like", f"%{txt}%"],
    }
    for fieldname in ("company", "customer", "currency"):
        if filters.get(fieldname):
            query_filters[fieldname] = filters[fieldname]

    start = max(int(start or 0), 0)
    page_len = max(int(page_len or 20), 1)
    candidates = frappe.get_list(
        "Sales Invoice",
        filters=query_filters,
        fields=["name", "posting_date", "grand_total", "currency"],
        order_by="posting_date desc, name desc",
        start=0,
        page_length=max((start + page_len) * 5, 20),
    )

    result = []
    for candidate in candidates:
        advance = frappe.get_doc("Sales Invoice", candidate.name)
        available = get_advance_available_amount(
            advance,
            exclude_sales_invoice=filters.get("final_invoice") or None,
        )
        if available <= Decimal("0.00"):
            continue
        result.append(
            (
                candidate.name,
                candidate.posting_date,
                float(available),
                candidate.currency,
            )
        )
        if len(result) >= start + page_len:
            break

    return result[start : start + page_len]


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

    company_doc = frappe.get_cached_doc("Company", doc.company)
    if is_zatca_invoice_enabled(company_doc) and resolve_zatca_phase(company_doc) == PHASE_2_VALUE:
        # Phase-2 QR must come from the returned ZATCA XML artifact.
        return

    if not supports_advance_deduction_schema(doc):
        return

    if int(getattr(doc, "docstatus", 0) or 0) != 1:
        return

    if not doc.meta.has_field("ksa_einv_qr"):
        return

    # Final/subsequent invoices must retain their normal Phase-1/Phase-2 QR.
    # The advance-aware QR is only valid for an initial advance invoice; older
    # runs could have attached it to a final invoice with deduction rows.
    if not is_advance_payment_invoice(doc):
        stale_rows = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": doc.name,
                "attached_to_field": "ksa_einv_qr",
                "file_name": ["like", "QR-ZATCA-Advance-Aware-%"],
            },
            fields=["name"],
        )
        for row in stale_rows:
            frappe.delete_doc("File", row.name, ignore_permissions=True)

        current_qr = str(doc.get("ksa_einv_qr") or "")
        if current_qr and "QR-ZATCA-Advance-Aware-" in current_qr:
            valid_rows = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Sales Invoice",
                    "attached_to_name": doc.name,
                    "attached_to_field": "ksa_einv_qr",
                    "file_name": ["like", "QR-%"],
                },
                fields=["file_url"],
                order_by="creation asc",
                limit=1,
            )
            replacement = valid_rows[0].file_url if valid_rows else ""
            if replacement:
                frappe.db.set_value(
                    "Sales Invoice", doc.name, "ksa_einv_qr", replacement, update_modified=False
                )
                doc.ksa_einv_qr = replacement
        return

    advance_taxable = flt(doc.get("custom_zatca_advance_deducted_taxable_amount") or 0)
    if advance_taxable <= 0:
        return

    current_qr = str(doc.get("ksa_einv_qr") or "")
    # A submitted advance invoice already receives its authoritative Phase-1
    # or Phase-2 QR. Never create a second advance-aware QR beside it.
    if current_qr and not force:
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
