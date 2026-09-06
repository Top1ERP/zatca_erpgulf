from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe.exceptions import ValidationError

from zatca_erpgulf.zatca_erpgulf.tax_error import (
    _invoice_has_tax_amount,
    validate_zatca_tax_table,
)


class MockDoc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


def _item(idx, amount, template):
    return MockDoc(
        idx=idx,
        item_code=f"ITEM-{idx}",
        item_name=f"Item {idx}",
        item_tax_template=template,
        base_net_amount=amount,
        base_amount=amount,
        net_amount=amount,
        amount=amount,
        qty=1,
    )


def _item_template(category, account, rate):
    return MockDoc(
        name=f"ITT-{account}",
        custom_zatca_tax_category=category,
        taxes=[MockDoc(tax_type=account, tax_rate=rate)],
    )


def _tax_row(account, rate, amount, **extra):
    return MockDoc(
        account_head=account,
        rate=rate,
        tax_amount_after_discount_amount=amount,
        base_tax_amount_after_discount_amount=amount,
        tax_amount=amount,
        base_tax_amount=amount,
        **extra,
    )


class TestZATCATaxTableReconciliation(TestCase):
    def _item_template_doc_map(self):
        return {
            "ITT-STANDARD": _item_template("Standard", "VAT 15", 15),
            "ITT-EXEMPT": _item_template("Exempted", "VAT Exempt", 0),
        }

    @staticmethod
    def _raise_validation(message, *args, **kwargs):
        raise ValidationError(str(message))

    def test_duplicate_account_rows_are_grouped_and_zero_category_is_required(self):
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            items=[
                _item(1, 100, "ITT-STANDARD"),
                _item(2, 200, "ITT-STANDARD"),
                _item(3, 300, "ITT-EXEMPT"),
            ],
            taxes=[
                _tax_row("VAT 15", 15, 15),
                _tax_row("VAT 15", 15, 30),
                _tax_row("VAT Exempt", 0, 0),
                _tax_row("Freight", 100, 999),
            ],
            taxes_and_charges="KSA VAT 15",
        )
        templates = self._item_template_doc_map()

        def get_doc(doctype, name):
            self.assertEqual(doctype, "Item Tax Template")
            return templates[name]

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            side_effect=get_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            side_effect=lambda account, cache=None: account != "Freight",
        ):
            validate_zatca_tax_table(doc)


    def test_unexpected_tax_accounts_are_rejected(self):
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            items=[_item(1, 100, "ITT-STANDARD")],
            taxes=[
                _tax_row("VAT 15", 0, 15),
                _tax_row("VAT 5", 5, 5),
                _tax_row("VAT Exempt", 0, 0),
            ],
            taxes_and_charges="KSA VAT 15",
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=_item_template("Standard", "VAT 15", 15),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.throw",
            side_effect=self._raise_validation,
        ):
            with self.assertRaises(ValidationError) as context:
                validate_zatca_tax_table(doc)

        message = str(context.exception)
        self.assertIn("Unexpected Sales Taxes and Charges row", message)
        self.assertIn("VAT 5", message)
        self.assertIn("VAT Exempt", message)

    def test_missing_zero_category_row_is_rejected(self):
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            items=[_item(1, 100, "ITT-EXEMPT")],
            taxes=[],
            taxes_and_charges="KSA VAT Exempted",
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=_item_template("Exempted", "VAT Exempt", 0),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.throw",
            side_effect=self._raise_validation,
        ):
            with self.assertRaises(ValidationError) as context:
                validate_zatca_tax_table(doc)

        self.assertIn("VAT Exempt", str(context.exception))
        self.assertIn("zero-value", str(context.exception))

    def test_amount_mismatch_uses_after_discount_amount_not_cumulative_total(self):
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            items=[_item(1, 100, "ITT-STANDARD")],
            taxes=[
                _tax_row(
                    "VAT 15",
                    15,
                    20,
                    total=9999,
                )
            ],
            taxes_and_charges="KSA VAT 15",
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=_item_template("Standard", "VAT 15", 15),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.throw",
            side_effect=self._raise_validation,
        ):
            with self.assertRaises(ValidationError) as context:
                validate_zatca_tax_table(doc)

        message = str(context.exception)
        self.assertIn("expected 15.00", message)
        self.assertIn("found 20.00", message)
        self.assertIn("Tax totals and non-tax rows are ignored.", message)


    def test_tax_table_validation_can_be_disabled_per_company(self):
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            items=[_item(1, 100, "ITT-STANDARD")],
            taxes=[_tax_row("VAT 15", 15, 20)],
            taxes_and_charges="KSA VAT 15",
        )
        company_doc = MockDoc(custom_enforce_zatca_tax_table_validation=0)

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=_item_template("Standard", "VAT 15", 15),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.throw",
        ) as throw:
            validate_zatca_tax_table(doc, company_doc=company_doc)

        throw.assert_not_called()


    def test_positive_tax_rate_field_is_ignored_when_amount_is_correct(self):
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            items=[_item(1, 100, "ITT-STANDARD")],
            # ERPNext can show rate 0 after a discount although the tax amount
            # remains correct. The amount must be the authoritative check.
            taxes=[_tax_row("VAT 15", 0, 15)],
            taxes_and_charges="KSA VAT 15",
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=_item_template("Standard", "VAT 15", 15),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            return_value=True,
        ):
            validate_zatca_tax_table(doc)

    def test_zero_tax_rate_is_still_enforced(self):
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            items=[_item(1, 100, "ITT-EXEMPT")],
            taxes=[_tax_row("VAT Exempt", 5, 0)],
            taxes_and_charges="KSA VAT Exempted",
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=_item_template("Exempted", "VAT Exempt", 0),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.throw",
            side_effect=self._raise_validation,
        ):
            with self.assertRaises(ValidationError) as context:
                validate_zatca_tax_table(doc)

        self.assertIn("Tax rate mismatch", str(context.exception))

    def test_invoice_level_template_path_ignores_non_tax_rows(self):
        sales_template = MockDoc(
            name="KSA VAT 15",
            custom_zatca_tax_category="Standard",
            custom_exemption_reason_code="",
            taxes=[
                MockDoc(
                    account_head="VAT 15",
                    charge_type="On Net Total",
                    rate=15,
                )
            ],
        )
        doc = MockDoc(
            doctype="Sales Invoice",
            currency="SAR",
            custom_zatca_tax_category="Standard",
            custom_exemption_reason_code="",
            items=[
                _item(1, 100, None),
                _item(2, 200, None),
            ],
            taxes=[_tax_row("VAT 15", 15, 45), _tax_row("Expense", 100, 500)],
            taxes_and_charges=sales_template.name,
        )

        def get_doc(doctype, name):
            self.assertEqual(doctype, "Sales Taxes and Charges Template")
            return sales_template

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            side_effect=get_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._get_sales_taxes_template_doc",
            return_value=sales_template,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            side_effect=lambda account, cache=None: account != "Expense",
        ):
            validate_zatca_tax_table(doc)

    def test_non_tax_total_does_not_count_as_vat(self):
        doc = MockDoc(
            taxes=[_tax_row("Expense", 100, 50)],
            total_taxes_and_charges=50,
        )
        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error._is_tax_account",
            return_value=False,
        ):
            self.assertFalse(_invoice_has_tax_amount(doc))
