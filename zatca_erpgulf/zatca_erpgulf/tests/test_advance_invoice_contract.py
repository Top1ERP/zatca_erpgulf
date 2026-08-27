from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.overrides.sales_invoice import (
    ZatcaSalesInvoice,
    normalize_advance_payment_invoice,
    validate_invoice_type_exclusivity,
    validate_advance_payment_invoice_tax,
)
from zatca_erpgulf.zatca_erpgulf.tax_error import (
    validate_advance_payment_invoice_tax_structure,
)


class _Meta:
    def __init__(self, fields):
        self.fields = set(fields)

    def has_field(self, fieldname):
        return fieldname in self.fields


class _Invoice(SimpleNamespace):
    def __init__(self, **overrides):
        values = {
            "is_advance_payment": 1,
            "is_return": 0,
            "is_debit_note": 0,
            "remarks": "",
            "allocate_advances_automatically": 1,
            "advances": [SimpleNamespace(reference_name="ACC-PAY-1")],
            "custom_zatca_advance_deduction_details": [
                SimpleNamespace(advance_invoice="SINV-ADV-1")
            ],
            "custom_zatca_prepaid_amount": 115,
            "custom_zatca_advance_deduction_count": 1,
            "custom_zatca_advance_deducted_taxable_amount": 100,
            "custom_zatca_advance_deducted_vat_amount": 15,
            "taxes": [SimpleNamespace(tax_amount=15, base_tax_amount=15)],
            "total_taxes_and_charges": 15,
        }
        values.update(overrides)
        super().__init__(**values)
        self.meta = _Meta(values)

    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def set(self, fieldname, value):
        setattr(self, fieldname, value)


class TestAdvanceInvoiceContract(FrappeTestCase):
    def test_advance_invoice_cannot_keep_standard_or_zatca_allocations(self):
        invoice = _Invoice()
        with patch(
            "zatca_erpgulf.overrides.sales_invoice.supports_advance_deduction_schema",
            return_value=True,
        ):
            normalize_advance_payment_invoice(invoice)

        self.assertEqual(invoice.allocate_advances_automatically, 0)
        self.assertEqual(invoice.advances, [])
        self.assertEqual(invoice.custom_zatca_advance_deduction_details, [])
        self.assertEqual(invoice.custom_zatca_prepaid_amount, 0)
        self.assertEqual(invoice.custom_zatca_advance_deduction_count, 0)
        self.assertEqual(invoice.custom_zatca_advance_deducted_taxable_amount, 0)
        self.assertEqual(invoice.custom_zatca_advance_deducted_vat_amount, 0)

    def test_automatic_remarks_are_added_without_overwriting_user_text(self):
        invoice = _Invoice()
        normalize_advance_payment_invoice(invoice)
        self.assertEqual(invoice.remarks, "Advance Payment Invoice")

        invoice.remarks = "Customer requested milestone billing"
        normalize_advance_payment_invoice(invoice)
        self.assertEqual(invoice.remarks, "Customer requested milestone billing")

    def test_positive_tax_is_required(self):
        for invoice in (
            _Invoice(taxes=[], total_taxes_and_charges=0),
            _Invoice(
                taxes=[SimpleNamespace(tax_amount=0, base_tax_amount=0)],
                total_taxes_and_charges=0,
            ),
        ):
            with self.assertRaisesRegex(frappe.ValidationError, "positive tax"):
                validate_advance_payment_invoice_tax(invoice)

    def test_positive_tax_passes(self):
        validate_advance_payment_invoice_tax(_Invoice())

    def test_return_does_not_use_advance_positive_tax_validation(self):
        validate_advance_payment_invoice_tax(
            _Invoice(is_return=1, taxes=[], total_taxes_and_charges=0)
        )

    def test_paid_status_preserves_real_outstanding(self):
        invoice = _Invoice(docstatus=1, outstanding_amount=115)
        writes = []
        invoice.db_set = lambda *args, **kwargs: writes.append((args, kwargs))

        ZatcaSalesInvoice.set_status(invoice, update=True, update_modified=False)

        self.assertEqual(invoice.status, "Paid")
        self.assertEqual(invoice.outstanding_amount, 115)
        self.assertEqual(writes, [(('status', 'Paid'), {'update_modified': False})])

    def test_ordinary_invoice_is_not_changed(self):
        invoice = _Invoice(is_advance_payment=0)
        original_advances = list(invoice.advances)
        normalize_advance_payment_invoice(invoice)
        validate_advance_payment_invoice_tax(invoice)
        self.assertEqual(invoice.advances, original_advances)
        self.assertEqual(invoice.remarks, "")

    def test_each_invoice_type_is_valid_on_its_own(self):
        invoices = (
            _Invoice(is_advance_payment=1),
            _Invoice(is_advance_payment=0, is_return=1),
            _Invoice(is_advance_payment=0, is_debit_note=1),
        )

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.supports_advance_payment_marker",
            return_value=True,
        ):
            for invoice in invoices:
                with self.subTest(
                    is_return=invoice.is_return,
                    is_debit_note=invoice.is_debit_note,
                    is_advance_payment=invoice.is_advance_payment,
                ):
                    validate_invoice_type_exclusivity(invoice)

    def test_conflicting_invoice_types_are_rejected(self):
        invoices = (
            _Invoice(is_return=1),
            _Invoice(is_debit_note=1),
            _Invoice(is_return=1, is_debit_note=1),
        )

        with patch(
            "zatca_erpgulf.overrides.sales_invoice.supports_advance_payment_marker",
            return_value=True,
        ):
            for invoice in invoices:
                with self.subTest(invoice=invoice):
                    with self.assertRaisesRegex(frappe.ValidationError, "only one invoice type"):
                        validate_invoice_type_exclusivity(invoice)

    def test_old_schema_keeps_standard_invoice_type_behavior(self):
        invoice = _Invoice(is_return=1, is_debit_note=1)
        with patch(
            "zatca_erpgulf.overrides.sales_invoice.supports_advance_payment_marker",
            return_value=False,
        ):
            validate_invoice_type_exclusivity(invoice)

    def test_advance_invoice_rejects_mixed_item_tax_templates(self):
        invoice = _Invoice(
            items=[
                SimpleNamespace(item_tax_template="VAT 15"),
                SimpleNamespace(item_tax_template="VAT 5"),
            ]
        )

        def get_doc(doctype, name):
            return SimpleNamespace(
                custom_zatca_tax_category="Standard",
                taxes=[SimpleNamespace(tax_rate=15 if name == "VAT 15" else 5)],
            )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            side_effect=get_doc,
        ), self.assertRaisesRegex(frappe.ValidationError, "only one VAT category"):
            validate_advance_payment_invoice_tax_structure(invoice)

    def test_advance_invoice_rejects_mixed_template_presence(self):
        invoice = _Invoice(
            items=[
                SimpleNamespace(item_tax_template="VAT 15"),
                SimpleNamespace(item_tax_template=""),
            ]
        )
        with self.assertRaisesRegex(frappe.ValidationError, "cannot mix"):
            validate_advance_payment_invoice_tax_structure(invoice)

    def test_advance_invoice_rejects_multiple_invoice_level_rates(self):
        invoice = _Invoice(
            items=[],
            taxes_and_charges="VAT Template",
            custom_zatca_tax_category="Standard",
            taxes=[SimpleNamespace(rate=15), SimpleNamespace(rate=5)],
        )
        source = SimpleNamespace(
            name="VAT Template",
            custom_zatca_tax_category="Standard",
            custom_exemption_reason_code="",
            taxes=[SimpleNamespace(rate=15)],
        )
        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=source,
        ), self.assertRaisesRegex(frappe.ValidationError, "only one VAT rate"):
            validate_advance_payment_invoice_tax_structure(invoice)

    def test_advance_invoice_requires_invoice_level_category(self):
        invoice = _Invoice(
            items=[],
            taxes_and_charges="VAT Template",
            taxes=[SimpleNamespace(rate=15)],
        )
        source = SimpleNamespace(
            name="VAT Template",
            custom_zatca_tax_category="",
            custom_exemption_reason_code="",
            taxes=[SimpleNamespace(rate=15)],
        )
        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=source,
        ), self.assertRaisesRegex(frappe.ValidationError, "exactly one ZATCA VAT category"):
            validate_advance_payment_invoice_tax_structure(invoice)

    def test_advance_invoice_allows_one_shared_category_and_rate(self):
        invoice = _Invoice(
            items=[
                SimpleNamespace(item_tax_template="VAT 15"),
                SimpleNamespace(item_tax_template="VAT 15"),
            ]
        )
        template = SimpleNamespace(
            custom_zatca_tax_category="Standard",
            taxes=[SimpleNamespace(tax_rate=15)],
        )
        with patch(
            "zatca_erpgulf.zatca_erpgulf.tax_error.frappe.get_doc",
            return_value=template,
        ):
            validate_advance_payment_invoice_tax_structure(invoice)
