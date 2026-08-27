from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.zatca_erpgulf.xml_tax_data import (
    _get_invoice_level_zatca_tax_source,
    _get_tax_breakdown_with_template,
    _get_tax_breakdown_without_template,
)
from zatca_erpgulf.zatca_erpgulf.tax_error import (
    validate_zatca_tax_category_and_exemption_reason,
)


OUTSIDE_SCOPE = "Services outside scope of tax / Not subject to VAT"


class MockDoc(SimpleNamespace):
    """Small document-like object for local unit tests.

    Frappe documents support both attribute access and `.get()`.
    We avoid `frappe._dict` here because `doc.items` collides with dict.items().
    """

    def get(self, key, default=None):
        return getattr(self, key, default)


def _item(idx, amount, item_tax_template=None, item_code=None):
    return MockDoc(
        idx=idx,
        item_code=item_code or f"TEST-ITEM-{idx}",
        item_tax_template=item_tax_template,
        amount=amount,
        base_amount=amount,
        net_amount=amount,
        base_net_amount=amount,
    )


def _tax_row(rate=15, item_wise_tax_detail=None):
    return MockDoc(
        rate=rate,
        included_in_print_rate=0,
        item_wise_tax_detail=item_wise_tax_detail or "",
    )


def _sales_invoice(
    *,
    items=None,
    taxes_and_charges=None,
    invoice_category="Standard",
    invoice_exemption_reason=None,
    tax_rate=15,
    currency="SAR",
):
    return MockDoc(
        doctype="Sales Invoice",
        name="TEST-ZATCA-TAX-SOURCE",
        company=None,
        currency=currency,
        taxes_and_charges=taxes_and_charges,
        custom_zatca_tax_category=invoice_category,
        custom_exemption_reason_code=invoice_exemption_reason,
        custom_zatca_export_invoice=0,
        items=items or [_item(1, 100)],
        taxes=[_tax_row(tax_rate)],
    )


def _sales_tax_template(category="", exemption_reason="", tax_rate=15):
    return MockDoc(
        doctype="Sales Taxes and Charges Template",
        name="TEST-SALES-TAX-TEMPLATE",
        custom_zatca_tax_category=category,
        custom_exemption_reason_code=exemption_reason,
        taxes=[MockDoc(rate=tax_rate)],
    )


def _item_tax_template(category, exemption_reason="", tax_rate=15):
    return MockDoc(
        doctype="Item Tax Template",
        name=f"TEST-ITEM-TAX-TEMPLATE-{category}",
        custom_zatca_tax_category=category,
        custom_exemption_reason_code=exemption_reason,
        taxes=[MockDoc(tax_rate=tax_rate)],
    )


class TestZATCATaxSourcePriority(FrappeTestCase):
    def test_sales_invoice_values_override_sales_taxes_template(self):
        sales_template = _sales_tax_template(
            category="Zero Rated",
            exemption_reason="VATEX-SA-29",
            tax_rate=0,
        )
        invoice = _sales_invoice(
            taxes_and_charges=sales_template.name,
            invoice_category="Standard",
            invoice_exemption_reason="VATEX-SA-OOS",
            tax_rate=0,
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.xml_tax_data.frappe.get_doc",
            return_value=sales_template,
        ):
            category, exemption_reason = _get_invoice_level_zatca_tax_source(invoice)

        self.assertEqual(category, "Standard")
        self.assertEqual(exemption_reason, "VATEX-SA-OOS")

    def test_sales_invoice_fallback_used_when_sales_template_has_no_zatca_category(self):
        sales_template = _sales_tax_template(category="", exemption_reason="", tax_rate=0)
        invoice = _sales_invoice(
            taxes_and_charges=sales_template.name,
            invoice_category=OUTSIDE_SCOPE,
            invoice_exemption_reason="VATEX-SA-OOS",
            tax_rate=0,
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.xml_tax_data.frappe.get_doc",
            return_value=sales_template,
        ):
            category, exemption_reason = _get_invoice_level_zatca_tax_source(invoice)

        self.assertEqual(category, OUTSIDE_SCOPE)
        self.assertEqual(exemption_reason, "VATEX-SA-OOS")

    def test_tax_breakdown_without_item_template_prefers_invoice_source(self):
        sales_template = _sales_tax_template(
            category="Zero Rated",
            exemption_reason="VATEX-SA-29",
            tax_rate=0,
        )
        invoice = _sales_invoice(
            items=[_item(1, 100), _item(2, 50)],
            taxes_and_charges=sales_template.name,
            invoice_category="Standard",
            tax_rate=0,
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.xml_tax_data.frappe.get_doc",
            return_value=sales_template,
        ):
            breakdown = _get_tax_breakdown_without_template(invoice)

        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0]["zatca_tax_category"], "Standard")
        self.assertIsNone(breakdown[0]["exemption_reason_code"])
        self.assertEqual(breakdown[0]["taxable_amount"], Decimal("150.00"))
        self.assertEqual(breakdown[0]["tax_amount"], Decimal("0.00"))
        self.assertEqual(breakdown[0]["tax_rate"], Decimal("0.00"))

    def test_tax_breakdown_with_item_template_groups_by_item_template_source(self):
        templates = {
            "ITT-STANDARD": _item_tax_template("Standard", "", 15),
            "ITT-OOS": _item_tax_template(OUTSIDE_SCOPE, "VATEX-SA-OOS", 0),
        }
        invoice = _sales_invoice(
            items=[
                _item(1, 100, item_tax_template="ITT-STANDARD"),
                _item(2, 50, item_tax_template="ITT-OOS"),
            ],
            invoice_category="Exempted",
            invoice_exemption_reason="VATEX-SA-EDU",
            tax_rate=15,
        )

        def fake_get_doc(doctype, name):
            self.assertEqual(doctype, "Item Tax Template")
            return templates[name]

        with patch(
            "zatca_erpgulf.zatca_erpgulf.xml_tax_data.frappe.get_doc",
            side_effect=fake_get_doc,
        ):
            breakdown = _get_tax_breakdown_with_template(invoice)

        by_category = {row["zatca_tax_category"]: row for row in breakdown}

        self.assertEqual(set(by_category), {"Standard", OUTSIDE_SCOPE})

        self.assertEqual(by_category["Standard"]["taxable_amount"], Decimal("100.00"))
        self.assertEqual(by_category["Standard"]["tax_amount"], Decimal("15.00"))
        self.assertEqual(by_category["Standard"]["tax_rate"], Decimal("15.00"))
        self.assertEqual(by_category["Standard"].get("exemption_reason_code") or "", "")

        self.assertEqual(by_category[OUTSIDE_SCOPE]["taxable_amount"], Decimal("50.00"))
        self.assertEqual(by_category[OUTSIDE_SCOPE]["tax_amount"], Decimal("0.00"))
        self.assertEqual(by_category[OUTSIDE_SCOPE]["tax_rate"], Decimal("0.00"))
        self.assertEqual(by_category[OUTSIDE_SCOPE]["exemption_reason_code"], "VATEX-SA-OOS")

    def test_mixed_item_tax_template_rows_are_rejected(self):
        invoice = _sales_invoice(
            items=[
                _item(1, 100, item_tax_template="ITT-STANDARD"),
                _item(2, 50, item_tax_template=None),
            ],
            invoice_category="Standard",
            tax_rate=15,
        )

        with self.assertRaises(Exception) as context:
            validate_zatca_tax_category_and_exemption_reason(
                invoice,
                company_doc=None,
                enforce_source_consistency=False,
            )

        message = str(context.exception)

        # Keep this assertion language-independent because some sites
        # return translated validation messages.
        self.assertIn("Item Tax Template", message)
        self.assertIn("2", message)
