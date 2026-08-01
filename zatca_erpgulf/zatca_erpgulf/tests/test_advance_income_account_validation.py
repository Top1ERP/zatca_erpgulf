from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.overrides.sales_invoice import validate_advance_income_accounts


class _Row:
    def __init__(self, idx: int, income_account: str = ""):
        self.idx = idx
        self.income_account = income_account


class _Invoice:
    def __init__(self, *accounts: str):
        self.company = "Test Company"
        self.items = [
            _Row(idx, account)
            for idx, account in enumerate(accounts, start=1)
        ]

    def get(self, fieldname):
        return getattr(self, fieldname, None)


def _database_values(
    *,
    preferred: str = "Customer Advances - TC",
    ordinary: str = "Sales - TC",
    account_overrides: dict | None = None,
):
    account_overrides = account_overrides or {}

    def get_value(doctype, name, fields, as_dict=False):
        if doctype == "Company":
            return frappe._dict(
                default_deferred_revenue_account=preferred,
                default_income_account=ordinary,
            )

        if doctype == "Account":
            values = {
                "company": "Test Company",
                "is_group": 0,
                "disabled": 0,
                "freeze_account": "No",
                "account_type": "",
            }
            values.update(account_overrides.get(name, {}))
            return frappe._dict(values)

        raise AssertionError(f"Unexpected DocType: {doctype}")

    return get_value


class TestAdvanceIncomeAccountValidation(FrappeTestCase):
    def test_company_preferred_account_replaces_ordinary_default(self):
        invoice = _Invoice("Sales - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(),
        ):
            validate_advance_income_accounts(invoice)

        self.assertEqual(invoice.items[0].income_account, "Customer Advances - TC")

    def test_manual_account_is_preserved(self):
        invoice = _Invoice("Manual Advance Account - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(),
        ):
            validate_advance_income_accounts(invoice)

        self.assertEqual(invoice.items[0].income_account, "Manual Advance Account - TC")

    def test_missing_company_default_allows_manual_account(self):
        invoice = _Invoice("Manual Advance Account - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(preferred=""),
        ):
            validate_advance_income_accounts(invoice)

    def test_missing_account_is_blocked_when_company_default_is_empty(self):
        invoice = _Invoice("")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(preferred=""),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "choose an Income Account"):
                validate_advance_income_accounts(invoice)

    def test_company_default_income_account_is_blocked(self):
        invoice = _Invoice("Sales - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(preferred=""),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "cannot be used"):
                validate_advance_income_accounts(invoice)

    def test_multiple_accounts_are_blocked(self):
        invoice = _Invoice("Advance A - TC", "Advance B - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "same Income Account"):
                validate_advance_income_accounts(invoice)

    def test_account_from_another_company_is_blocked(self):
        invoice = _Invoice("Other Company Advance")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(
                account_overrides={
                    "Other Company Advance": {"company": "Other Company"}
                }
            ),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "does not belong"):
                validate_advance_income_accounts(invoice)

    def test_group_account_is_blocked(self):
        invoice = _Invoice("Advance Group - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(
                account_overrides={"Advance Group - TC": {"is_group": 1}}
            ),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "group account"):
                validate_advance_income_accounts(invoice)

    def test_disabled_account_is_blocked(self):
        invoice = _Invoice("Disabled Advance - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(
                account_overrides={"Disabled Advance - TC": {"disabled": 1}}
            ),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "disabled"):
                validate_advance_income_accounts(invoice)

    def test_frozen_account_is_blocked(self):
        invoice = _Invoice("Frozen Advance - TC")

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
            side_effect=_database_values(
                account_overrides={"Frozen Advance - TC": {"freeze_account": "Yes"}}
            ),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "frozen"):
                validate_advance_income_accounts(invoice)

    def test_receivable_and_payable_accounts_are_blocked(self):
        for account_type in ("Receivable", "Payable"):
            with self.subTest(account_type=account_type):
                invoice = _Invoice(f"{account_type} - TC")
                with patch(
                    "zatca_erpgulf.overrides.sales_invoice.frappe.db.get_value",
                    side_effect=_database_values(
                        account_overrides={
                            f"{account_type} - TC": {"account_type": account_type}
                        }
                    ),
                ):
                    with self.assertRaisesRegex(
                        frappe.ValidationError,
                        "Receivable and Payable",
                    ):
                        validate_advance_income_accounts(invoice)
