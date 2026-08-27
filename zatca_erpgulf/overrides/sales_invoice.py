from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from zatca_erpgulf.zatca_erpgulf.advance_deduction import (
    append_advance_deduction_gl_entries,
    populate_zatca_advance_deductions,
)
from zatca_erpgulf.zatca_erpgulf import (
    advance_credit_note,
    advance_deduction,
    advance_payment_entry,
    tax_error,
)
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    is_advance_payment_invoice,
    supports_advance_deduction_schema,
    supports_advance_payment_marker,
)


PROHIBITED_ACCOUNT_TYPES = {"Receivable", "Payable"}
ADVANCE_REMARKS = {"Advance Payment Invoice", "فاتورة الدفعة المقدمة"}
ADVANCE_ALLOCATION_TOTAL_FIELDS = (
    "custom_zatca_prepaid_amount",
    "custom_zatca_advance_deduction_count",
    "custom_zatca_advance_deducted_taxable_amount",
    "custom_zatca_advance_deducted_vat_amount",
)


def _company_accounts(company: str) -> dict[str, str]:
    values = frappe.db.get_value(
        "Company",
        company,
        ["default_deferred_revenue_account", "default_income_account"],
        as_dict=True,
    )
    return values or {}


def _account_details(account: str) -> dict[str, Any]:
    values = frappe.db.get_value(
        "Account",
        account,
        [
            "company",
            "is_group",
            "disabled",
            "freeze_account",
            "account_type",
        ],
        as_dict=True,
    )
    return values or {}


def _set_preferred_account_on_unresolved_rows(
    invoice,
    preferred_account: str,
    default_income_account: str,
) -> None:
    if not preferred_account:
        return

    for item in invoice.get("items") or []:
        current_account = str(getattr(item, "income_account", "") or "").strip()
        if not current_account or current_account == default_income_account:
            item.income_account = preferred_account


def validate_advance_income_accounts(invoice) -> None:
    """Validate the posting account used by a standard advance Sales Invoice.

    The account is intentionally stored in Sales Invoice Item.income_account.
    ERPNext's deferred-revenue scheduler is not enabled by this feature.
    """
    if not invoice.company:
        frappe.throw(_("Company is required on an advance payment invoice."))

    company_accounts = _company_accounts(invoice.company)
    preferred_account = str(
        company_accounts.get("default_deferred_revenue_account") or ""
    ).strip()
    default_income_account = str(
        company_accounts.get("default_income_account") or ""
    ).strip()

    _set_preferred_account_on_unresolved_rows(
        invoice,
        preferred_account,
        default_income_account,
    )

    selected_accounts: set[str] = set()
    for item in invoice.get("items") or []:
        account = str(getattr(item, "income_account", "") or "").strip()
        if not account:
            frappe.throw(
                _(
                    "Row {0}: choose an Income Account for the advance payment. "
                    "You may configure Default Deferred Revenue Account in Company "
                    "Accounts or select another account manually."
                ).format(getattr(item, "idx", "?"))
            )

        if default_income_account and account == default_income_account:
            frappe.throw(
                _(
                    "Row {0}: Company Default Income Account {1} cannot be used for "
                    "an advance payment invoice. Configure Default Deferred Revenue "
                    "Account or choose another account manually."
                ).format(getattr(item, "idx", "?"), frappe.bold(account))
            )

        details = _account_details(account)
        if not details:
            frappe.throw(
                _("Row {0}: Account {1} does not exist.").format(
                    getattr(item, "idx", "?"),
                    frappe.bold(account),
                )
            )
        if details.get("company") != invoice.company:
            frappe.throw(
                _("Row {0}: Account {1} does not belong to Company {2}.").format(
                    getattr(item, "idx", "?"),
                    frappe.bold(account),
                    frappe.bold(invoice.company),
                )
            )
        if cint(details.get("is_group")):
            frappe.throw(
                _("Row {0}: Account {1} is a group account.").format(
                    getattr(item, "idx", "?"),
                    frappe.bold(account),
                )
            )
        if cint(details.get("disabled")):
            frappe.throw(
                _("Row {0}: Account {1} is disabled.").format(
                    getattr(item, "idx", "?"),
                    frappe.bold(account),
                )
            )
        if str(details.get("freeze_account") or "").strip() == "Yes":
            frappe.throw(
                _("Row {0}: Account {1} is frozen.").format(
                    getattr(item, "idx", "?"),
                    frappe.bold(account),
                )
            )
        if str(details.get("account_type") or "").strip() in PROHIBITED_ACCOUNT_TYPES:
            frappe.throw(
                _(
                    "Row {0}: Receivable and Payable accounts cannot be used as the "
                    "advance payment Income Account."
                ).format(getattr(item, "idx", "?"))
            )

        selected_accounts.add(account)

    if len(selected_accounts) > 1:
        frappe.throw(
            _(
                "All Item rows in one advance payment invoice must use the same "
                "Income Account. Create separate advance invoices when multiple "
                "accounts are required."
            )
        )


def normalize_advance_payment_invoice(invoice) -> None:
    """Apply the non-allocation contract of an advance payment invoice."""
    if not is_advance_payment_invoice(invoice):
        return

    if getattr(invoice, "remarks", None) in (None, "", *ADVANCE_REMARKS):
        invoice.remarks = _("Advance Payment Invoice")

    if getattr(invoice, "meta", None) and invoice.meta.has_field("allocate_advances_automatically"):
        invoice.allocate_advances_automatically = 0
    if getattr(invoice, "meta", None) and invoice.meta.has_field("advances"):
        invoice.set("advances", [])

    if not supports_advance_deduction_schema(invoice):
        return
    if getattr(invoice, "meta", None) and invoice.meta.has_field(
        "custom_zatca_advance_deduction_details"
    ):
        invoice.set("custom_zatca_advance_deduction_details", [])

    for fieldname in ADVANCE_ALLOCATION_TOTAL_FIELDS:
        if getattr(invoice, "meta", None) and invoice.meta.has_field(fieldname):
            setattr(invoice, fieldname, 0)


def validate_invoice_type_exclusivity(invoice) -> None:
    """Allow only one of return, debit note, or advance-payment modes."""
    if not supports_advance_payment_marker(invoice):
        return

    selected_types = sum(
        (
            bool(cint(getattr(invoice, "is_return", 0))),
            bool(cint(getattr(invoice, "is_debit_note", 0))),
            is_advance_payment_invoice(invoice),
        )
    )
    if selected_types > 1:
        frappe.throw(
            _(
                "Select only one invoice type: Is Return (Credit Note), "
                "Is Rate Adjustment Entry (Debit Note), or Is Advance Payment Invoice."
            )
        )


def validate_advance_payment_invoice_tax(invoice) -> None:
    """Require a real positive tax amount on every advance payment invoice."""
    if cint(getattr(invoice, "is_return", 0)) or not is_advance_payment_invoice(invoice):
        return

    positive_rows = [
        row
        for row in (invoice.get("taxes") or [])
        if flt(getattr(row, "tax_amount", 0)) > 0
        or flt(getattr(row, "base_tax_amount", 0)) > 0
    ]
    if not positive_rows or flt(getattr(invoice, "total_taxes_and_charges", 0)) <= 0:
        frappe.throw(
            _(
                "An advance payment invoice must contain a positive tax. "
                "Add a valid Taxes and Charges row before saving."
            )
        )


def _naming_series_options(invoice) -> list[str]:
    """Return configured Sales Invoice naming-series options when available."""
    try:
        field = invoice.meta.get_field("naming_series") if getattr(invoice, "meta", None) else None
        options = getattr(field, "options", "") or ""
        return [line.strip() for line in str(options).split("\n") if line.strip()]
    except Exception:
        return []


def validate_advance_payment_naming_series(invoice) -> None:
    """Require advance invoices to use an ADV- naming series when configured."""
    if not is_advance_payment_invoice(invoice):
        return

    options = _naming_series_options(invoice)
    advance_options = [option for option in options if option.upper().startswith("ADV-")]
    if not advance_options:
        frappe.throw(
            _(
                "Advance Payment Invoice requires an ADV- naming series. "
                "Add an ADV- series in Sales Invoice naming settings before saving."
            )
        )

    series = str(getattr(invoice, "naming_series", "") or "").strip()
    if not series.upper().startswith("ADV-"):
        frappe.throw(
            _("Advance Payment Invoice must use an ADV- naming series. Select an ADV- series before saving.")
        )


def _append_zatca_error(invoice, exc) -> None:
    message = str(exc).strip()
    if not message:
        return
    errors = getattr(invoice.flags, "zatca_validation_errors", [])
    if message not in errors:
        errors.append(message)
    invoice.flags.zatca_validation_errors = errors


def _raise_zatca_errors(invoice) -> None:
    errors = list(dict.fromkeys(getattr(invoice.flags, "zatca_validation_errors", []) or []))
    if not errors:
        return
    message = "\n".join(f"• {error}" for error in errors)
    frappe.throw(message, title=_("ZATCA validation errors"))


def validate_zatca_sales_invoice(doc, event=None) -> None:
    """Run independent ZATCA save validators and report every failure together."""
    doc.flags.zatca_validation_errors = list(
        dict.fromkeys(getattr(doc.flags, "zatca_validation_errors", []) or [])
    )
    validators = (
        validate_invoice_type_exclusivity,
        validate_advance_payment_naming_series,
        validate_advance_payment_invoice_tax,
        tax_error.validate_negative_item_values_on_save,
        advance_payment_entry.validate_sales_invoice_payment_entry_link,
        advance_deduction.validate_sales_invoice_advance_deductions,
        advance_credit_note.validate_advance_credit_note_against_original,
    )
    for validator in validators:
        try:
            validator(doc, event) if validator in (
                tax_error.validate_negative_item_values_on_save,
                advance_payment_entry.validate_sales_invoice_payment_entry_link,
                advance_deduction.validate_sales_invoice_advance_deductions,
                advance_credit_note.validate_advance_credit_note_against_original,
            ) else validator(doc)
        except frappe.ValidationError as exc:
            _append_zatca_error(doc, exc)
    _raise_zatca_errors(doc)


def validate_zatca_sales_invoice_before_submit(doc, event=None) -> None:
    """Aggregate independent ZATCA before-submit validators."""
    doc.flags.zatca_validation_errors = list(
        dict.fromkeys(getattr(doc.flags, "zatca_validation_errors", []) or [])
    )
    for validator in (
        tax_error.validate_sales_invoice_taxes,
        advance_deduction.validate_sales_invoice_advance_deductions_on_submit,
        advance_credit_note.validate_advance_credit_note_against_original,
    ):
        try:
            validator(doc, event)
        except frappe.ValidationError as exc:
            _append_zatca_error(doc, exc)
    _raise_zatca_errors(doc)


class ZatcaSalesInvoice(SalesInvoice):
    """Sales Invoice extension for standard ZATCA advance-payment invoices."""

    def before_naming(self):
        """Populate abbreviation and select the first ADV- series for advance invoices."""
        if is_advance_payment_invoice(self):
            options = [option for option in _naming_series_options(self) if option.upper().startswith("ADV-")]
            current = str(getattr(self, "naming_series", "") or "").strip()
            if options and not current.upper().startswith("ADV-"):
                self.naming_series = options[0]
        if not getattr(self, "meta", None) or not self.meta.has_field("abbr"):
            return
        if getattr(self, "abbr", None) or not getattr(self, "company", None):
            return
        try:
            self.abbr = frappe.db.get_value("Company", self.company, "abbr") or ""
        except Exception:
            return

    def validate_income_account(self):
        if not is_advance_payment_invoice(self):
            return super().validate_income_account()

        try:
            validate_advance_income_accounts(self)
        except frappe.ValidationError as exc:
            errors = getattr(self.flags, "zatca_validation_errors", [])
            errors.append(str(exc))
            self.flags.zatca_validation_errors = errors

    @frappe.whitelist()
    def set_advances(self):
        """Run ERPNext cash allocation, then independent ZATCA allocation."""
        if is_advance_payment_invoice(self):
            normalize_advance_payment_invoice(self)
            return

        super().set_advances()
        populate_zatca_advance_deductions(self)

    def set_status(self, update=False, status=None, update_modified=True):
        """Keep the operational status closed without changing ledger outstanding."""
        if cint(getattr(self, "docstatus", 0)) == 1 and is_advance_payment_invoice(self):
            self.status = "Paid"
            if update:
                self.db_set("status", "Paid", update_modified=update_modified)
            return

        return super().set_status(
            update=update,
            status=status,
            update_modified=update_modified,
        )

    def set_indicator(self):
        if cint(getattr(self, "docstatus", 0)) == 1 and is_advance_payment_invoice(self):
            self.indicator_title = _("Paid")
            self.indicator_color = "green"
            return

        return super().set_indicator()

    def get_gl_entries(self, warehouse_account=None):
        gl_entries = super().get_gl_entries(warehouse_account)
        return append_advance_deduction_gl_entries(self, gl_entries)

    def validate(self):
        normalize_advance_payment_invoice(self)
        self.flags.zatca_validation_errors = []
        super().validate()
        normalize_advance_payment_invoice(self)
