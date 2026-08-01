from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint

from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from zatca_erpgulf.zatca_erpgulf.advance_deduction import (
    append_advance_deduction_gl_entries,
)
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import is_advance_payment_invoice


PROHIBITED_ACCOUNT_TYPES = {"Receivable", "Payable"}


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


class ZatcaSalesInvoice(SalesInvoice):
    """Sales Invoice extension for standard ZATCA advance-payment invoices."""

    def validate_income_account(self):
        if not is_advance_payment_invoice(self):
            return super().validate_income_account()

        validate_advance_income_accounts(self)

    def get_gl_entries(self, warehouse_account=None):
        gl_entries = super().get_gl_entries(warehouse_account)
        return append_advance_deduction_gl_entries(self, gl_entries)
