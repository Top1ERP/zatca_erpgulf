from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.zatca_erpgulf.advance_credit_note import (
    validate_advance_credit_note_against_original,
)
from zatca_erpgulf.zatca_erpgulf.advance_deduction import (
    ZATCA_ADVANCE_VAT_DEDUCTION_MARKER,
    _advance_tax_amount,
    _advance_total_amount,
    append_advance_deduction_gl_entries,
    get_advance_available_amount,
    populate_zatca_advance_deductions,
    validate_sales_invoice_advance_deductions,
    validate_sales_invoice_advance_deductions_on_submit,
)
from zatca_erpgulf.zatca_erpgulf.create_xml_final_part import (
    _append_direct_advance_reference_lines,
)


class _Meta:
    def __init__(self, fields=()):
        self.fields = set(fields)

    def has_field(self, fieldname):
        return fieldname in self.fields


class _Row(SimpleNamespace):
    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def set(self, fieldname, value):
        setattr(self, fieldname, value)


class _Invoice:
    def __init__(
        self,
        *,
        name="SINV-FINAL",
        rows=None,
        is_return=0,
        is_advance_payment=0,
        docstatus=0,
        grand_total=2300,
        conversion_rate=1,
        taxes=None,
    ):
        self.doctype = "Sales Invoice"
        self.name = name
        self.company = "Test Company"
        self.customer = "Test Customer"
        self.currency = "SAR"
        self.company_currency = "SAR"
        self.party_account_currency = "SAR"
        self.conversion_rate = conversion_rate
        self.is_return = is_return
        self.is_advance_payment = is_advance_payment
        self.docstatus = docstatus
        self.grand_total = grand_total
        self.net_total = grand_total
        self.debit_to = "Debtors - TC"
        self.cost_center = "Main - TC"
        self.project = None
        self.taxes = list(taxes or [])
        self.advances = [_Row(reference_name="ACC-PAY-ORDINARY", allocated_amount=77)]
        self.custom_zatca_advance_deduction_details = list(rows or [])
        self.custom_zatca_prepaid_amount = 0
        self.custom_zatca_advance_deducted_taxable_amount = 0
        self.custom_zatca_advance_deducted_vat_amount = 0
        self.custom_zatca_advance_deduction_count = 0
        self.flags = SimpleNamespace()
        self.meta = _Meta({"is_advance_payment", "custom_zatca_advance_deduction_details"})
        self.calculate_calls = 0

    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def set(self, fieldname, value):
        setattr(self, fieldname, value)

    def append(self, fieldname, value):
        row = _Row(**value)
        getattr(self, fieldname).append(row)
        return row

    def calculate_taxes_and_totals(self):
        self.calculate_calls += 1

    def get_gl_dict(self, values, account_currency=None, item=None):
        return dict(values)

    def set_transaction_currency_and_rate_in_gl_map(self, entries):
        for entry in entries:
            entry["transaction_currency"] = self.currency
            entry["transaction_exchange_rate"] = self.conversion_rate


def _advance_invoice(*, name="SINV-ADV", total=1150, conversion_rate=1):
    taxable = round(total / 1.15, 2)
    tax = round(total - taxable, 2)
    return _Row(
        doctype="Sales Invoice",
        name=name,
        company="Test Company",
        customer="Test Customer",
        currency="SAR",
        conversion_rate=conversion_rate,
        docstatus=1,
        is_advance_payment=1,
        custom_zatca_status="CLEARED",
        custom_zatca_payment_entry=None,
        custom_uuid=f"UUID-{name}",
        custom_zatca_tax_category="Standard",
        posting_date="2026-08-01",
        posting_time="10:30:00",
        net_total=taxable,
        total=taxable,
        total_taxes_and_charges=tax,
        grand_total=total,
        items=[
            _Row(
                net_amount=taxable,
                amount=taxable,
                income_account="Advance Income - TC",
                cost_center="Main - TC",
                project=None,
            )
        ],
        taxes=[
            _Row(
                tax_amount_after_discount_amount=tax,
                tax_amount=tax,
                account_head="VAT 15% - TC",
                cost_center="Main - TC",
            )
        ],
        meta=_Meta({"is_advance_payment"}),
    )


def _allocation_row(amount=575, advance_invoice="SINV-ADV", idx=1):
    return _Row(
        idx=idx,
        advance_invoice=advance_invoice,
        allocated_total_amount=amount,
    )


def _local_path_text(node, *names):
    """Read literal-prefix or namespace-qualified XML children in tests."""
    current = node
    for name in names:
        current = next(
            (child for child in list(current)
             if str(child.tag).split("}", 1)[-1].split(":", 1)[-1] == name),
            None,
        )
        if current is None:
            return None
    return current.text


def _direct_validation_patches(advance, *, credit_total=0, allocated_total=0):
    return (
        patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.db.exists",
            return_value=True,
        ),
        patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_doc",
            return_value=advance,
        ),
        patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.is_accepted_advance_sales_invoice",
            return_value=True,
        ),
        patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_credit_note_total",
            return_value=credit_total,
        ),
        patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_final_allocation_total",
            return_value=allocated_total,
        ),
    )


class TestDirectAdvanceAllocation(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for target in (
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.supports_advance_deduction_schema",
            "zatca_erpgulf.zatca_erpgulf.create_xml_final_part.supports_advance_deduction_schema",
        ):
            capability = patch(target, return_value=True)
            capability.start()
            self.addCleanup(capability.stop)

    def test_direct_row_is_source_and_standard_advances_are_untouched(self):
        advance = _advance_invoice()
        row = _allocation_row(575)
        doc = _Invoice(rows=[row], grand_total=2300)
        original_advances = list(doc.advances)

        patches = _direct_validation_patches(advance)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(row.allocated_total_amount, 575.0)
        self.assertEqual(row.allocated_taxable_amount, 500.0)
        self.assertEqual(row.allocated_tax_amount, 75.0)
        self.assertEqual(doc.custom_zatca_prepaid_amount, 575.0)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 1)
        self.assertEqual(doc.advances, original_advances)
        self.assertFalse(
            any(
                ZATCA_ADVANCE_VAT_DEDUCTION_MARKER
                in str(getattr(tax, "description", "") or "")
                for tax in doc.taxes
            )
        )

    def test_advance_total_uses_enabled_rounded_total(self):
        advance = _advance_invoice(total=10)
        advance.grand_total = 10.01
        advance.rounded_total = 10
        advance.disable_rounded_total = 0
        self.assertEqual(_advance_total_amount(advance), Decimal("10.00"))

        advance.disable_rounded_total = 1
        self.assertEqual(_advance_total_amount(advance), Decimal("10.01"))

    def test_vat_uses_tax_amount_after_discount(self):
        advance = _advance_invoice(total=10)
        advance.total_taxes_and_charges = 1.31
        advance.taxes[0].tax_amount = 1.31
        advance.taxes[0].tax_amount_after_discount_amount = 1.30
        self.assertEqual(_advance_tax_amount(advance), Decimal("1.30"))

        advance.taxes[0].tax_amount_after_discount_amount = 0
        self.assertEqual(_advance_tax_amount(advance), Decimal("0.00"))

    def test_discount_rounding_keeps_full_advance_receivable_total(self):
        advance = _advance_invoice(total=10)
        advance.net_total = 8.69
        advance.total_taxes_and_charges = 1.30
        advance.grand_total = 10
        advance.rounded_total = 10
        advance.disable_rounded_total = 0
        advance.items[0].net_amount = 8.69
        advance.taxes[0].tax_amount_after_discount_amount = 1.30
        advance.taxes[0].tax_amount = 1.30

        row = _allocation_row(10)
        doc = _Invoice(rows=[row], grand_total=115)
        patches = _direct_validation_patches(advance)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_cached_value",
            side_effect=lambda _dt, _name, fieldname: {
                "round_off_account": "Round Off - TC",
                "round_off_cost_center": "Main - TC",
            }.get(fieldname),
        ):
            validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(row.advance_total_amount, 10.0)
        self.assertEqual(row.allocated_total_amount, 10.0)
        self.assertEqual(row.allocated_taxable_amount, 8.69)
        self.assertEqual(row.allocated_tax_amount, 1.30)
        direct_row = doc.flags.zatca_direct_advance_rows[0]
        self.assertEqual(
            direct_row["rounding_breakdown"][0]["allocated_amount"],
            Decimal("0.01"),
        )

    def test_available_balance_subtracts_credit_notes_and_submitted_finals(self):
        advance = _advance_invoice(total=1150)
        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_credit_note_total",
            return_value=115,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_final_allocation_total",
            return_value=230,
        ):
            self.assertEqual(get_advance_available_amount(advance), 805)

    def test_allocation_above_available_balance_is_blocked(self):
        advance = _advance_invoice(total=1150)
        doc = _Invoice(rows=[_allocation_row(806)])
        patches = _direct_validation_patches(
            advance,
            credit_total=115,
            allocated_total=230,
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with self.assertRaisesRegex(frappe.ValidationError, "exceeds the available balance"):
                validate_sales_invoice_advance_deductions(doc)

    def test_same_advance_invoice_cannot_appear_twice(self):
        advance = _advance_invoice()
        doc = _Invoice(rows=[_allocation_row(100, idx=1), _allocation_row(100, idx=2)])
        patches = _direct_validation_patches(advance)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with self.assertRaisesRegex(frappe.ValidationError, "may appear only once"):
                validate_sales_invoice_advance_deductions(doc)

    def test_same_payment_entry_may_exist_in_both_independent_tables(self):
        advance = _advance_invoice()
        advance.custom_zatca_payment_entry = "ACC-PAY-DUPLICATE"
        doc = _Invoice(rows=[_allocation_row(115)])
        doc.advances = [
            _Row(reference_name="ACC-PAY-DUPLICATE", allocated_amount=115)
        ]
        patches = _direct_validation_patches(advance)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            validate_sales_invoice_advance_deductions(doc)

        self.assertEqual(doc.advances[0].allocated_amount, 115)
        self.assertEqual(doc.custom_zatca_prepaid_amount, 115)

    def test_automatic_zatca_allocation_uses_settled_and_unsettled_advances(self):
        settled = _advance_invoice(name="SINV-ADV-SETTLED", total=345)
        settled.custom_zatca_payment_entry = "ACC-PAY-SETTLED"
        unsettled = _advance_invoice(name="SINV-ADV-UNSETTLED", total=230)
        unsettled.custom_zatca_payment_entry = "ACC-PAY-UNSETTLED"
        doc = _Invoice(rows=[_allocation_row(50)], grand_total=1000)
        original_standard_advances = list(doc.advances)

        def get_doc(_doctype, name):
            return settled if name == settled.name else unsettled

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_meta",
            return_value=_Meta({"is_advance_payment"}),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_list",
            return_value=[_Row(name=settled.name), _Row(name=unsettled.name)],
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_doc",
            side_effect=get_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.is_accepted_advance_sales_invoice",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_advance_available_amount",
            side_effect=[345, 230],
        ):
            rows = populate_zatca_advance_deductions(doc)

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row.advance_invoice for row in rows],
            [settled.name, unsettled.name],
        )
        self.assertEqual(
            [row.allocated_total_amount for row in rows],
            [345.0, 230.0],
        )
        self.assertEqual(doc.advances, original_standard_advances)

    def test_automatic_zatca_allocation_caps_at_remaining_final_total(self):
        first = _advance_invoice(name="SINV-ADV-A", total=800)
        second = _advance_invoice(name="SINV-ADV-B", total=400)
        doc = _Invoice(rows=[], grand_total=1000)

        def get_doc(_doctype, name):
            return first if name == first.name else second

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_meta",
            return_value=_Meta({"is_advance_payment"}),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_list",
            return_value=[_Row(name=first.name), _Row(name=second.name)],
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_doc",
            side_effect=get_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.is_accepted_advance_sales_invoice",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_advance_available_amount",
            side_effect=[800, 400],
        ):
            rows = populate_zatca_advance_deductions(doc)

        self.assertEqual(
            [row.allocated_total_amount for row in rows],
            [800.0, 200.0],
        )

    def test_automatic_zatca_allocation_skips_exhausted_advance(self):
        exhausted = _advance_invoice(name="SINV-ADV-USED", total=500)
        available = _advance_invoice(name="SINV-ADV-OPEN", total=300)
        doc = _Invoice(rows=[], grand_total=1000)

        def get_doc(_doctype, name):
            return exhausted if name == exhausted.name else available

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_meta",
            return_value=_Meta({"is_advance_payment"}),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_list",
            return_value=[_Row(name=exhausted.name), _Row(name=available.name)],
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_doc",
            side_effect=get_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.is_accepted_advance_sales_invoice",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.get_advance_available_amount",
            side_effect=[0, 300],
        ):
            rows = populate_zatca_advance_deductions(doc)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].advance_invoice, available.name)
        self.assertEqual(rows[0].allocated_total_amount, 300.0)

    def test_exchange_rate_must_match(self):
        advance = _advance_invoice(conversion_rate=1)
        doc = _Invoice(rows=[_allocation_row(100)], conversion_rate=2)
        patches = _direct_validation_patches(advance)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with self.assertRaisesRegex(frappe.ValidationError, "exchange rate"):
                validate_sales_invoice_advance_deductions(doc)

    def test_return_with_direct_rows_is_blocked(self):
        doc = _Invoice(rows=[_allocation_row(100)], is_return=1, grand_total=-115)
        with self.assertRaisesRegex(
            frappe.ValidationError,
            "cannot be applied directly to a return or credit note",
        ):
            validate_sales_invoice_advance_deductions(doc)

    def test_advance_invoice_cannot_also_be_a_final_invoice(self):
        doc = _Invoice(rows=[_allocation_row(100)], is_advance_payment=1)
        with self.assertRaisesRegex(
            frappe.ValidationError,
            "cannot be both an advance payment invoice and a final invoice",
        ):
            validate_sales_invoice_advance_deductions(doc)

    def test_submit_locks_references_in_stable_order(self):
        first = _advance_invoice(name="SINV-ADV-A")
        second = _advance_invoice(name="SINV-ADV-B")
        doc = _Invoice(
            rows=[
                _allocation_row(115, "SINV-ADV-B", 1),
                _allocation_row(115, "SINV-ADV-A", 2),
            ],
            docstatus=1,
        )

        def get_doc(_doctype, name):
            return first if name == first.name else second

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._lock_advance_invoice"
        ) as lock, patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.db.exists",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.frappe.get_doc",
            side_effect=get_doc,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction.is_accepted_advance_sales_invoice",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_credit_note_total",
            return_value=0,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_final_allocation_total",
            return_value=0,
        ):
            validate_sales_invoice_advance_deductions_on_submit(doc)

        self.assertEqual(
            [call.args[0] for call in lock.call_args_list],
            ["SINV-ADV-A", "SINV-ADV-B"],
        )

    def test_gl_release_debits_source_accounts_and_credits_receivable(self):
        doc = _Invoice(rows=[])
        doc.flags.zatca_direct_advance_rows = [
            {
                "advance_invoice": "SINV-ADV",
                "allocated_total_amount": 115,
                "income_breakdown": [
                    {
                        "account": "Advance Income - TC",
                        "cost_center": "Main - TC",
                        "project": None,
                        "allocated_amount": 100,
                    }
                ],
                "tax_breakdown": [
                    {
                        "account": "VAT 15% - TC",
                        "cost_center": "Main - TC",
                        "allocated_amount": 15,
                    }
                ],
            }
        ]

        entries = []
        with patch(
            "erpnext.accounts.utils.get_account_currency",
            return_value="SAR",
        ):
            append_advance_deduction_gl_entries(doc, entries)

        self.assertEqual(sum(entry.get("debit", 0) for entry in entries), 115)
        self.assertEqual(sum(entry.get("credit", 0) for entry in entries), 115)
        self.assertEqual(entries[-1]["account"], "Debtors - TC")
        self.assertEqual(entries[-1]["against_voucher"], "SINV-ADV")

    def test_rounding_residual_uses_round_off_account_not_vat(self):
        for signed_rounding, income, vat in (
            (Decimal("0.01"), Decimal("8.69"), Decimal("1.30")),
            (Decimal("-0.01"), Decimal("8.70"), Decimal("1.31")),
        ):
            with self.subTest(signed_rounding=signed_rounding):
                doc = _Invoice(rows=[])
                doc.flags.zatca_direct_advance_rows = [
                    {
                        "advance_invoice": "SINV-ADV",
                        "allocated_total_amount": Decimal("10.00"),
                        "income_breakdown": [
                            {
                                "account": "Advance Income - TC",
                                "cost_center": "Main - TC",
                                "project": None,
                                "allocated_amount": income,
                            }
                        ],
                        "tax_breakdown": [
                            {
                                "account": "VAT 15% - TC",
                                "cost_center": "Main - TC",
                                "allocated_amount": vat,
                            }
                        ],
                        "rounding_breakdown": [
                            {
                                "account": "Round Off - TC",
                                "cost_center": "Main - TC",
                                "allocated_amount": signed_rounding,
                            }
                        ],
                    }
                ]

                entries = []
                with patch(
                    "erpnext.accounts.utils.get_account_currency",
                    return_value="SAR",
                ):
                    append_advance_deduction_gl_entries(doc, entries)

                self.assertAlmostEqual(
                    sum(entry.get("debit", 0) for entry in entries),
                    sum(entry.get("credit", 0) for entry in entries),
                )
                rounding_entry = next(
                    entry for entry in entries if entry["account"] == "Round Off - TC"
                )
                if signed_rounding > 0:
                    self.assertEqual(rounding_entry["debit"], 0.01)
                    self.assertFalse(rounding_entry.get("credit"))
                else:
                    self.assertEqual(rounding_entry["credit"], 0.01)
                    self.assertFalse(rounding_entry.get("debit"))
                vat_entry = next(
                    entry for entry in entries if entry["account"] == "VAT 15% - TC"
                )
                self.assertEqual(vat_entry["debit"], float(vat))

    def test_multiple_advances_keep_separate_receivable_references(self):
        doc = _Invoice(rows=[])
        doc.flags.zatca_direct_advance_rows = [
            {
                "advance_invoice": name,
                "allocated_total_amount": amount,
                "income_breakdown": [
                    {
                        "account": "Advance Income - TC",
                        "cost_center": "Main - TC",
                        "project": None,
                        "allocated_amount": amount,
                    }
                ],
                "tax_breakdown": [],
            }
            for name, amount in (("SINV-ADV-A", 100), ("SINV-ADV-B", 50))
        ]

        entries = []
        with patch("erpnext.accounts.utils.get_account_currency", return_value="SAR"):
            append_advance_deduction_gl_entries(doc, entries)

        credits = [entry for entry in entries if entry.get("party_type") == "Customer"]
        self.assertEqual(len(credits), 2)
        self.assertEqual(
            [(entry["against_voucher"], entry["credit"]) for entry in credits],
            [("SINV-ADV-A", 100.0), ("SINV-ADV-B", 50.0)],
        )

    def test_xml_adds_one_386_reference_line_for_each_direct_allocation(self):
        first = _advance_invoice(name="SINV-ADV-A")
        second = _advance_invoice(name="SINV-ADV-B")
        doc = _Invoice(
            rows=[
                _Row(
                    advance_invoice=first.name,
                    allocated_total_amount=575,
                    allocated_taxable_amount=500,
                    allocated_tax_amount=75,
                ),
                _Row(
                    advance_invoice=second.name,
                    allocated_total_amount=230,
                    allocated_taxable_amount=200,
                    allocated_tax_amount=30,
                ),
            ]
        )
        doc.items = []
        root = ET.Element("Invoice")

        def get_doc(_doctype, name):
            return first if name == first.name else second

        with patch(
            "zatca_erpgulf.zatca_erpgulf.create_xml_final_part.frappe.get_doc",
            side_effect=get_doc,
        ):
            _append_direct_advance_reference_lines(root, doc)

        lines = [child for child in list(root) if child.tag == "cac:InvoiceLine"]
        references = [
            next(child for child in list(line) if child.tag == "cac:DocumentReference")
            for line in lines
        ]
        self.assertEqual(len(references), 2)
        self.assertEqual(
            [
                next(child for child in list(reference) if child.tag == "cbc:ID").text
                for reference in references
            ],
            [first.name, second.name],
        )
        self.assertTrue(
            all(
                next(
                    child
                    for child in list(reference)
                    if child.tag == "cbc:DocumentTypeCode"
                ).text
                == "386"
                for reference in references
            )
        )

    def test_normal_xml_builder_emits_direct_advance_lines_and_unique_ids(self):
        from zatca_erpgulf.zatca_erpgulf.create_xml_final_part import item_data

        advance = _advance_invoice(name="SINV-ADV-NORMAL")
        doc = _Invoice(rows=[_Row(advance_invoice=advance.name, allocated_total_amount=575, allocated_taxable_amount=500, allocated_tax_amount=75)])
        doc.items = []
        root = ET.Element("Invoice")

        with patch(
            "zatca_erpgulf.zatca_erpgulf.create_xml_final_part.frappe.get_doc",
            return_value=advance,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.create_xml_final_part.supports_advance_deduction_schema",
            return_value=True,
        ):
            item_data(root, doc)

        lines = root.findall("cac:InvoiceLine")
        self.assertEqual(len(lines), 1)
        self.assertEqual(_local_path_text(lines[0], "DocumentReference", "ID"), advance.name)
        self.assertEqual(_local_path_text(lines[0], "DocumentReference", "DocumentTypeCode"), "386")
        self.assertEqual(_local_path_text(lines[0], "InvoicedQuantity"), "0.000000")
        self.assertEqual(_local_path_text(lines[0], "LineExtensionAmount"), "0.00")
        self.assertEqual(_local_path_text(lines[0], "TaxTotal", "TaxAmount"), "0.00")
        self.assertEqual(_local_path_text(lines[0], "TaxTotal", "TaxSubtotal", "TaxableAmount"), "500.00")
        self.assertEqual(_local_path_text(lines[0], "TaxTotal", "TaxSubtotal", "TaxAmount"), "75.00")

    def test_adjustment_line_generation_is_idempotent(self):
        advance = _advance_invoice(name="SINV-ADV-IDEMPOTENT")
        doc = _Invoice(rows=[_Row(advance_invoice=advance.name, allocated_total_amount=575, allocated_taxable_amount=500, allocated_tax_amount=75)])
        root = ET.Element("Invoice")

        with patch(
            "zatca_erpgulf.zatca_erpgulf.create_xml_final_part.frappe.get_doc",
            return_value=advance,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.create_xml_final_part.supports_advance_deduction_schema",
            return_value=True,
        ):
            _append_direct_advance_reference_lines(root, doc)
            _append_direct_advance_reference_lines(root, doc)

        self.assertEqual(len(root.findall("cac:InvoiceLine")), 1)

    def test_normal_invoice_without_deductions_has_no_adjustment_line(self):
        doc = _Invoice(rows=[])
        root = ET.Element("Invoice")
        with patch(
            "zatca_erpgulf.zatca_erpgulf.create_xml_final_part.supports_advance_deduction_schema",
            return_value=True,
        ):
            _append_direct_advance_reference_lines(root, doc)
        self.assertEqual(root.findall("cac:InvoiceLine"), [])


class TestAdvanceCreditNoteAvailability(FrappeTestCase):
    def test_credit_note_cannot_reverse_amount_already_used_by_final_invoice(self):
        credit_note = _Invoice(
            name="SINV-CN",
            is_return=1,
            grand_total=-460,
        )
        credit_note.return_against = "SINV-ADV"
        advance = _advance_invoice(total=1150)

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note.get_advance_sales_invoice_from_return",
            return_value=advance,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note._get_submitted_credit_notes",
            return_value=[],
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_deduction._submitted_final_allocation_total",
            return_value=805,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_credit_note.frappe.format_value",
            return_value="345.00",
        ):
            with self.assertRaisesRegex(
                frappe.ValidationError,
                "balance after submitted final-invoice allocations",
            ):
                validate_advance_credit_note_against_original(credit_note)
