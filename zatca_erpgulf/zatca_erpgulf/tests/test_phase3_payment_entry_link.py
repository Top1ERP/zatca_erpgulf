from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.setup_customizations import CRITICAL_CUSTOM_FIELDS
from zatca_erpgulf.zatca_erpgulf.advance_payment_entry import (
    _amounts_match,
    _get_active_legacy_advance_invoice,
    _payment_entry_mapping,
    _validate_existing_link_allocations,
    _validate_payment_entry_source,
    get_active_standard_advance_invoice,
    split_tax_inclusive_amount,
    validate_sales_invoice_payment_entry_link,
)


class _Meta:
    def __init__(self, fields=()):
        self.fields = set(fields)

    def has_field(self, fieldname):
        return fieldname in self.fields


class _Doc(SimpleNamespace):
    def __init__(self, *, fields=(), **values):
        super().__init__(**values)
        self.meta = _Meta(fields)

    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)


def _payment_entry(**overrides):
    values = {
        "doctype": "Payment Entry",
        "name": "ACC-PAY-2026-00001",
        "docstatus": 1,
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": "Test Customer",
        "company": "Test Company",
        "posting_date": "2026-08-01",
        "paid_from_account_currency": "SAR",
        "paid_to_account_currency": "SAR",
        "paid_amount": 115,
        "base_paid_amount": 115,
        "received_amount": 115,
        "base_received_amount": 115,
        "source_exchange_rate": 1,
        "target_exchange_rate": 1,
        "total_allocated_amount": 0,
        "unallocated_amount": 115,
        "total_taxes_and_charges": 0,
        "base_total_taxes_and_charges": 0,
        "taxes": [],
        "custom_zatca_advance_tax_invoice": "",
    }
    values.update(overrides)
    return _Doc(
        fields={"custom_zatca_advance_tax_invoice"},
        **values,
    )


def _link_definition():
    return next(
        row
        for row in CRITICAL_CUSTOM_FIELDS["Sales Invoice"]
        if row["fieldname"] == "custom_zatca_payment_entry"
    )


class TestPhase3PaymentEntryFieldMetadata(FrappeTestCase):
    def test_pay_m_001_fieldname(self):
        self.assertEqual(_link_definition()["fieldname"], "custom_zatca_payment_entry")

    def test_pay_m_002_fieldtype(self):
        self.assertEqual(_link_definition()["fieldtype"], "Link")

    def test_pay_m_003_options(self):
        self.assertEqual(_link_definition()["options"], "Payment Entry")

    def test_pay_m_004_allow_on_submit(self):
        self.assertEqual(_link_definition()["allow_on_submit"], 1)

    def test_pay_m_005_no_copy(self):
        self.assertEqual(_link_definition()["no_copy"], 1)

    def test_pay_m_006_not_required(self):
        self.assertEqual(_link_definition()["reqd"], 0)

    def test_pay_m_007_advance_only_visibility(self):
        expression = _link_definition()["depends_on"]
        self.assertIn("is_advance_payment", expression)
        self.assertIn("custom_is_advance_payment", expression)

    def test_pay_m_008_single_definition(self):
        definitions = [
            row
            for row in CRITICAL_CUSTOM_FIELDS["Sales Invoice"]
            if row["fieldname"] == "custom_zatca_payment_entry"
        ]
        self.assertEqual(len(definitions), 1)


class TestPhase3InclusiveVatMath(FrappeTestCase):
    def test_splits_115_into_100_and_15(self):
        split = split_tax_inclusive_amount(115)
        self.assertEqual(str(split["taxable"]), "100.00")
        self.assertEqual(str(split["tax"]), "15.00")
        self.assertEqual(split["taxable"] + split["tax"], split["gross"])

    def test_rounding_keeps_original_gross(self):
        split = split_tax_inclusive_amount("100.00")
        self.assertEqual(split["taxable"] + split["tax"], split["gross"])

    def test_three_decimal_currency_keeps_original_gross(self):
        split = split_tax_inclusive_amount("100.001", precision=3)
        self.assertEqual(split["taxable"] + split["tax"], split["gross"])

    def test_zero_gross_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            split_tax_inclusive_amount(0)

    def test_negative_tax_rate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            split_tax_inclusive_amount(100, tax_rate=-1)

    def test_amount_match_allows_sub_precision_noise(self):
        self.assertTrue(_amounts_match("100.00", "100.004", 2))

    def test_amount_match_rejects_one_precision_unit(self):
        self.assertFalse(_amounts_match("100.00", "100.01", 2))


class TestPhase3PaymentEntryMapping(FrappeTestCase):
    def test_receive_mapping_uses_customer_side_paid_amount(self):
        mapping = _payment_entry_mapping(
            _payment_entry(
                paid_from_account_currency="USD",
                paid_to_account_currency="SAR",
                paid_amount=100,
                received_amount=375,
                base_paid_amount=375,
                source_exchange_rate=3.75,
                target_exchange_rate=1,
            )
        )
        self.assertEqual(mapping["currency"], "USD")
        self.assertEqual(mapping["gross_amount"], 100)
        self.assertEqual(mapping["conversion_rate"], 3.75)
        self.assertEqual(mapping["received_amount"], 375)

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_submitted_fully_unallocated_receive_entry_is_allowed(self, _precision):
        mapping = _validate_payment_entry_source(_payment_entry())
        self.assertEqual(mapping["gross_amount"], 115)

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_draft_payment_entry_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "must be submitted"):
            _validate_payment_entry_source(_payment_entry(docstatus=0))

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_pay_payment_entry_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "Only Receive"):
            _validate_payment_entry_source(_payment_entry(payment_type="Pay"))

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_non_customer_payment_entry_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "Party Type Customer"):
            _validate_payment_entry_source(_payment_entry(party_type="Supplier"))

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_zero_paid_amount_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "greater than zero"):
            _validate_payment_entry_source(
                _payment_entry(paid_amount=0, base_paid_amount=0, unallocated_amount=0)
            )

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_zero_source_exchange_rate_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "exchange rate"):
            _validate_payment_entry_source(_payment_entry(source_exchange_rate=0))

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_partial_allocation_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "already allocated"):
            _validate_payment_entry_source(
                _payment_entry(total_allocated_amount=15, unallocated_amount=100)
            )

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_inconsistent_unallocated_amount_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "full Payment Entry"):
            _validate_payment_entry_source(_payment_entry(unallocated_amount=114))

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_payment_entry_vat_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "VAT must be recorded only"):
            _validate_payment_entry_source(
                _payment_entry(total_taxes_and_charges=15, base_total_taxes_and_charges=15)
            )

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_payment_entry_tax_child_amount_is_blocked(self, _precision):
        with self.assertRaisesRegex(frappe.ValidationError, "VAT must be recorded only"):
            _validate_payment_entry_source(
                _payment_entry(taxes=[SimpleNamespace(tax_amount=1, base_tax_amount=1)])
            )


class TestPhase3DuplicateAndLegacyGuards(FrappeTestCase):
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_meta")
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.get_value")
    def test_active_standard_invoice_is_found(self, get_value, get_meta):
        get_meta.return_value = _Meta({"custom_zatca_payment_entry"})
        get_value.return_value = "SINV-ADV-0001"
        self.assertEqual(
            get_active_standard_advance_invoice("ACC-PAY-0001"),
            "SINV-ADV-0001",
        )
        filters = get_value.call_args.args[1]
        self.assertEqual(filters["docstatus"], ["<", 2])

    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_meta")
    def test_missing_link_field_returns_no_duplicate(self, get_meta):
        get_meta.return_value = _Meta()
        self.assertEqual(get_active_standard_advance_invoice("ACC-PAY-0001"), "")

    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_meta")
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.exists")
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.get_value")
    def test_active_legacy_invoice_is_found(self, get_value, exists, get_meta):
        get_meta.return_value = _Meta({"custom_zatca_advance_tax_invoice"})
        exists.return_value = True
        get_value.return_value = 0
        self.assertEqual(
            _get_active_legacy_advance_invoice(
                _payment_entry(custom_zatca_advance_tax_invoice="ZADV-0001")
            ),
            "ZADV-0001",
        )

    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_meta")
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.exists")
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.get_value")
    def test_cancelled_legacy_invoice_allows_recreation(self, get_value, exists, get_meta):
        get_meta.return_value = _Meta({"custom_zatca_advance_tax_invoice"})
        exists.return_value = True
        get_value.return_value = 2
        self.assertEqual(
            _get_active_legacy_advance_invoice(
                _payment_entry(custom_zatca_advance_tax_invoice="ZADV-0001")
            ),
            "",
        )

    def test_allocation_to_linked_sales_invoice_is_allowed(self):
        payment_entry = _payment_entry(
            references=[
                SimpleNamespace(
                    reference_doctype="Sales Invoice",
                    reference_name="SINV-ADV-0001",
                    allocated_amount=115,
                )
            ]
        )
        _validate_existing_link_allocations(payment_entry, "SINV-ADV-0001")

    def test_allocation_to_another_document_is_blocked(self):
        payment_entry = _payment_entry(
            references=[
                SimpleNamespace(
                    reference_doctype="Sales Invoice",
                    reference_name="SINV-OTHER-0001",
                    allocated_amount=10,
                )
            ]
        )
        with self.assertRaisesRegex(frappe.ValidationError, "only the linked"):
            _validate_existing_link_allocations(payment_entry, "SINV-ADV-0001")


class TestPhase3SalesInvoiceLinkValidation(FrappeTestCase):
    def _invoice(self, **overrides):
        values = {
            "doctype": "Sales Invoice",
            "name": "SINV-ADV-0001",
            "docstatus": 0,
            "is_advance_payment": 1,
            "custom_zatca_payment_entry": "ACC-PAY-2026-00001",
            "company": "Test Company",
            "customer": "Test Customer",
            "currency": "SAR",
            "conversion_rate": 1,
            "grand_total": 115,
        }
        values.update(overrides)
        return _Doc(
            fields={"custom_zatca_payment_entry", "is_advance_payment"},
            **values,
        )

    def test_standalone_advance_invoice_without_link_is_allowed(self):
        validate_sales_invoice_payment_entry_link(
            self._invoice(custom_zatca_payment_entry="")
        )

    def test_ordinary_invoice_cannot_link_payment_entry(self):
        with self.assertRaisesRegex(frappe.ValidationError, "only to an advance"):
            validate_sales_invoice_payment_entry_link(
                self._invoice(is_advance_payment=0)
            )

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._ensure_no_active_legacy_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.ensure_payment_entry_has_no_active_standard_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._validate_payment_entry_identity"
    )
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_doc")
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_matching_link_is_allowed(
        self,
        _precision,
        get_doc,
        validate_source,
        _standard_guard,
        _legacy_guard,
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        validate_sales_invoice_payment_entry_link(self._invoice())

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._ensure_no_active_legacy_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.ensure_payment_entry_has_no_active_standard_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._validate_payment_entry_identity"
    )
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_doc")
    def test_company_mismatch_is_blocked(
        self,
        get_doc,
        validate_source,
        _standard_guard,
        _legacy_guard,
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "Company must match"):
            validate_sales_invoice_payment_entry_link(
                self._invoice(company="Other Company")
            )

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._ensure_no_active_legacy_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.ensure_payment_entry_has_no_active_standard_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._validate_payment_entry_identity"
    )
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_doc")
    def test_customer_mismatch_is_blocked(
        self,
        get_doc,
        validate_source,
        _standard_guard,
        _legacy_guard,
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "Customer must match"):
            validate_sales_invoice_payment_entry_link(
                self._invoice(customer="Other Customer")
            )

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._ensure_no_active_legacy_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.ensure_payment_entry_has_no_active_standard_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._validate_payment_entry_identity"
    )
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_doc")
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_currency_mismatch_is_blocked(
        self,
        _precision,
        get_doc,
        validate_source,
        _standard_guard,
        _legacy_guard,
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "currency must match"):
            validate_sales_invoice_payment_entry_link(self._invoice(currency="USD"))

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._ensure_no_active_legacy_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.ensure_payment_entry_has_no_active_standard_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._validate_payment_entry_identity"
    )
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_doc")
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_exchange_rate_mismatch_is_blocked(
        self,
        _precision,
        get_doc,
        validate_source,
        _standard_guard,
        _legacy_guard,
    ):
        get_doc.return_value = _payment_entry(source_exchange_rate=3.75)
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "exchange rate must match"):
            validate_sales_invoice_payment_entry_link(
                self._invoice(conversion_rate=1)
            )

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._ensure_no_active_legacy_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.ensure_payment_entry_has_no_active_standard_advance_invoice"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._validate_payment_entry_identity"
    )
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_doc")
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._currency_precision",
        return_value=2,
    )
    def test_grand_total_mismatch_is_blocked(
        self,
        _precision,
        get_doc,
        validate_source,
        _standard_guard,
        _legacy_guard,
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "grand total must match"):
            validate_sales_invoice_payment_entry_link(self._invoice(grand_total=100))
