from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.zatca_erpgulf.advance_credit_note import (
    validate_advance_credit_note_against_original,
)
from zatca_erpgulf.zatca_erpgulf.advance_deduction import (
    ZATCA_ADVANCE_VAT_DEDUCTION_MARKER,
    validate_sales_invoice_advance_deductions,
)


class _FakeMeta:
    def __init__(self, fields=None):
        self._fields = set(fields or [])

    def has_field(self, fieldname):
        return fieldname in self._fields


class _FakeSalesInvoice:
    def __init__(
        self,
        *,
        is_return=0,
        docstatus=0,
        net_total=0,
        taxes=None,
        advances=None,
        company="Test Company",
        customer="Test Customer",
        currency="SAR",
        grand_total=0,
        custom_is_advance_credit_note=0,
        custom_advance_invoice_reference="",
    ):
        self.doctype = "Sales Invoice"
        self.name = "TEST-SINV"
        self.is_return = is_return
        self.docstatus = docstatus
        self.net_total = net_total
        self.company = company
        self.customer = customer
        self.currency = currency
        self.grand_total = grand_total
        self.rounded_total = grand_total
        self.custom_is_advance_credit_note = custom_is_advance_credit_note
        self.custom_advance_invoice_reference = custom_advance_invoice_reference
        self.taxes = list(taxes or [])
        self.advances = list(advances or [])
        self.custom_zatca_advance_deduction_details = []
        self.custom_zatca_prepaid_amount = 999.0
        self.custom_zatca_advance_deducted_taxable_amount = 999.0
        self.custom_zatca_advance_deducted_vat_amount = 999.0
        self.custom_zatca_advance_deduction_count = 99
        self.calculate_calls = 0
        self.meta = _FakeMeta(
            {
                "custom_zatca_advance_deduction_details",
            }
        )

    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def set(self, fieldname, value):
        setattr(self, fieldname, value)

    def append(self, fieldname, value):
        row = SimpleNamespace(**value)
        rows = getattr(self, fieldname, None)
        if rows is None:
            rows = []
            setattr(self, fieldname, rows)
        rows.append(row)
        return row

    def calculate_taxes_and_totals(self):
        self.calculate_calls += 1


def _tax_row(amount, *, description="", account_head="VAT - TEST"):
    return SimpleNamespace(
        tax_amount=amount,
        description=description,
        account_head=account_head,
    )


def _advance_row(payment_entry, allocated_amount):
    return SimpleNamespace(
        reference_name=payment_entry,
        allocated_amount=allocated_amount,
    )


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _deduction_row(*, taxable, tax, total, payment_entry="ACC-PAY-TEST"):
    taxable = _money(taxable)
    tax = _money(tax)
    total = _money(total)

    return {
        "payment_entry": payment_entry,
        "advance_tax_invoice": "ZADV-TEST",
        "allocated_amount": taxable,
        "allocated_taxable_amount": taxable,
        "allocated_tax_amount": tax,
        "allocated_total_amount": total,
        "zatca_uuid": None,
        "posting_date": None,
        "advance_total_amount": total,
        "advance_taxable_amount": taxable,
        "advance_tax_amount": tax,
        "status": "Final",
        "zatca_status": "PHASE 1 QR CREATED",
        "tax_account": "VAT - TEST",
        "tax_rate": 15,
        "currency": "SAR",
    }


class TestAdvanceDeductionReturnValidation(FrappeTestCase):
    def test_ordinary_return_with_negative_totals_and_no_advances_passes(self):
        marker_row = _tax_row(
            100,
            description=ZATCA_ADVANCE_VAT_DEDUCTION_MARKER,
        )
        return_vat_row = _tax_row(-5400)

        doc = _FakeSalesInvoice(
            is_return=1,
            net_total=-36000,
            taxes=[return_vat_row, marker_row],
        )

        validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.calculate_calls, 1)
        self.assertEqual(doc.taxes, [return_vat_row])
        self.assertEqual(doc.custom_zatca_advance_deduction_details, [])
        self.assertEqual(doc.custom_zatca_prepaid_amount, 0.0)
        self.assertEqual(
            doc.custom_zatca_advance_deducted_taxable_amount,
            0.0,
        )
        self.assertEqual(doc.custom_zatca_advance_deducted_vat_amount, 0.0)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 0)

    def test_return_with_zero_zatca_advance_allocation_passes(self):
        doc = _FakeSalesInvoice(
            is_return=1,
            net_total=-1000,
            taxes=[_tax_row(-150)],
            advances=[_advance_row("ACC-PAY-ZERO", 0)],
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "_get_linked_zatca_advance_invoice"
        ) as get_link:
            validate_sales_invoice_advance_deductions(doc)

        get_link.assert_not_called()
        self.assertEqual(doc.calculate_calls, 1)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 0)

    def test_return_with_positive_zatca_advance_allocation_is_blocked(self):
        doc = _FakeSalesInvoice(
            is_return=1,
            net_total=-1000,
            taxes=[_tax_row(-150)],
            advances=[_advance_row("ACC-PAY-ZATCA", 100)],
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "_get_linked_zatca_advance_invoice",
            return_value="ZADV-TEST",
        ):
            with self.assertRaisesRegex(
                frappe.ValidationError,
                "cannot be applied directly to a return or credit note",
            ):
                validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.calculate_calls, 0)

    def test_return_with_positive_non_zatca_allocation_is_not_blocked(self):
        doc = _FakeSalesInvoice(
            is_return=1,
            net_total=-1000,
            taxes=[_tax_row(-150)],
            advances=[_advance_row("ACC-PAY-ORDINARY", 100)],
        )

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "_get_linked_zatca_advance_invoice",
            return_value="",
        ):
            validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.calculate_calls, 1)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 0)

    def test_positive_invoice_with_zero_deduction_row_passes(self):
        doc = _FakeSalesInvoice(
            is_return=0,
            net_total=1000,
            taxes=[_tax_row(150)],
        )
        rows = [_deduction_row(taxable=0, tax=0, total=0)]

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "get_standard_advance_deduction_rows",
            return_value=rows,
        ):
            validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.calculate_calls, 1)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 0)
        self.assertEqual(doc.custom_zatca_prepaid_amount, 0.0)

    def test_positive_invoice_with_deduction_within_total_passes(self):
        doc = _FakeSalesInvoice(
            is_return=0,
            net_total=1000,
            taxes=[_tax_row(150)],
        )
        rows = [_deduction_row(taxable=500, tax=75, total=575)]

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "get_standard_advance_deduction_rows",
            return_value=rows,
        ):
            validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.calculate_calls, 1)
        self.assertEqual(doc.custom_zatca_prepaid_amount, 575.0)
        self.assertEqual(
            doc.custom_zatca_advance_deducted_taxable_amount,
            500.0,
        )
        self.assertEqual(doc.custom_zatca_advance_deducted_vat_amount, 75.0)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 1)

        deduction_tax_rows = [
            row
            for row in doc.taxes
            if ZATCA_ADVANCE_VAT_DEDUCTION_MARKER
            in str(getattr(row, "description", "") or "")
        ]
        self.assertEqual(len(deduction_tax_rows), 1)
        self.assertEqual(deduction_tax_rows[0].tax_amount, -75.0)

    def test_positive_invoice_with_excess_vat_is_blocked(self):
        doc = _FakeSalesInvoice(
            is_return=0,
            net_total=1000,
            taxes=[_tax_row(150)],
        )
        rows = [_deduction_row(taxable=500, tax=151, total=651)]

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "get_standard_advance_deduction_rows",
            return_value=rows,
        ):
            with self.assertRaisesRegex(
                frappe.ValidationError,
                "VAT deduction cannot exceed",
            ):
                validate_sales_invoice_advance_deductions(doc)

    def test_positive_invoice_with_excess_total_is_blocked(self):
        doc = _FakeSalesInvoice(
            is_return=0,
            net_total=1000,
            taxes=[_tax_row(150)],
        )
        rows = [_deduction_row(taxable=1100, tax=50, total=1150.01)]

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction."
            "get_standard_advance_deduction_rows",
            return_value=rows,
        ):
            with self.assertRaisesRegex(
                frappe.ValidationError,
                "deduction cannot exceed the Sales Invoice total",
            ):
                validate_sales_invoice_advance_deductions(doc)

    def test_valid_advance_credit_note_validator_remains_active(self):
        doc = _FakeSalesInvoice(
            is_return=1,
            net_total=-400,
            taxes=[_tax_row(-60)],
            grand_total=-460,
            custom_is_advance_credit_note=1,
            custom_advance_invoice_reference="ZADV-TEST",
        )
        advance_doc = SimpleNamespace(
            company=doc.company,
            customer=doc.customer,
            currency=doc.currency,
            total_amount=1000,
            zatca_status="Cleared",
            zatca_clearance_status=None,
            zatca_reporting_status=None,
        )

        validate_sales_invoice_advance_deductions(doc)

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note._get_advance_doc",
            return_value=advance_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note."
            "_get_submitted_credit_notes",
            return_value=[],
        ):
            validate_advance_credit_note_against_original(doc)

        self.assertEqual(doc.calculate_calls, 1)

    def test_excessive_advance_credit_note_remains_blocked(self):
        doc = _FakeSalesInvoice(
            is_return=1,
            net_total=-1000,
            taxes=[_tax_row(-150)],
            grand_total=-1100,
            custom_is_advance_credit_note=1,
            custom_advance_invoice_reference="ZADV-TEST",
        )
        advance_doc = SimpleNamespace(
            company=doc.company,
            customer=doc.customer,
            currency=doc.currency,
            total_amount=1000,
            zatca_status="Reported",
            zatca_clearance_status=None,
            zatca_reporting_status=None,
        )

        validate_sales_invoice_advance_deductions(doc)

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note._get_advance_doc",
            return_value=advance_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note."
            "_get_submitted_credit_notes",
            return_value=[],
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note."
            "frappe.format_value",
            return_value="0.00",
        ):
            with self.assertRaisesRegex(
                frappe.ValidationError,
                "Total advance credit notes cannot exceed",
            ):
                validate_advance_credit_note_against_original(doc)

    def test_submitted_ordinary_return_without_advances_passes(self):
        doc = _FakeSalesInvoice(
            is_return=1,
            docstatus=1,
            net_total=-2000,
            taxes=[_tax_row(-300)],
        )

        validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.calculate_calls, 1)
        self.assertEqual(doc.custom_zatca_prepaid_amount, 0.0)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 0)

    def test_ordinary_positive_invoice_without_deductions_passes(self):
        doc = _FakeSalesInvoice(
            is_return=0,
            docstatus=1,
            net_total=1000,
            taxes=[_tax_row(150)],
            advances=[],
        )

        validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.calculate_calls, 1)
        self.assertEqual(doc.custom_zatca_prepaid_amount, 0.0)
        self.assertEqual(
            doc.custom_zatca_advance_deducted_taxable_amount,
            0.0,
        )
        self.assertEqual(doc.custom_zatca_advance_deducted_vat_amount, 0.0)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 0)
