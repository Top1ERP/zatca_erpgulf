from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.setup_customizations import CRITICAL_CUSTOM_FIELDS
from zatca_erpgulf.zatca_erpgulf.advance_payment_entry import (
    _amounts_match,
    _build_advance_sales_invoice,
    _ensure_standard_advance_payment_item,
    _invoice_payment_total,
    _payment_entry_mapping,
    _validate_existing_link_allocations,
    _validate_payment_entry_source,
    get_active_standard_advance_invoice,
    split_tax_inclusive_amount,
    validate_payment_entry_advance_allocations,
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
    }
    values.update(overrides)
    return _Doc(
        fields=set(),
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

    def test_invoice_payment_total_uses_enabled_currency_rounding(self):
        invoice = _Doc(
            fields=set(),
            disable_rounded_total=0,
            rounded_total=10,
            grand_total=10.01,
        )
        self.assertEqual(_invoice_payment_total(invoice), Decimal("10"))

    def test_invoice_payment_total_uses_grand_total_when_rounding_is_disabled(self):
        invoice = _Doc(
            fields=set(),
            disable_rounded_total=1,
            rounded_total=10,
            grand_total=10.01,
        )
        self.assertEqual(_invoice_payment_total(invoice), Decimal("10.01"))

    @patch("zatca_erpgulf.setup_customizations.ensure_advance_payment_item")
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.exists",
        side_effect=[False, True],
    )
    def test_missing_standard_item_is_created_lazily(self, exists, ensure_item):
        _ensure_standard_advance_payment_item()
        ensure_item.assert_called_once_with()
        self.assertEqual(exists.call_count, 2)

    @patch("zatca_erpgulf.setup_customizations.ensure_advance_payment_item")
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.exists",
        return_value=True,
    )
    def test_existing_standard_item_is_not_modified(self, _exists, ensure_item):
        _ensure_standard_advance_payment_item()
        ensure_item.assert_not_called()


class TestPhase3PaymentEntryMapping(FrappeTestCase):
    def test_build_enables_standard_rounding_after_missing_values(self):
        invoice = _Doc(
            fields={"disable_rounded_total", "is_advance_payment"},
            disable_rounded_total=1,
            rounded_total=0,
            grand_total=0,
        )
        invoice.items = []
        invoice.taxes = []
        invoice.append = lambda _fieldname, values: invoice.items.append(values)

        def run_method(method):
            if method == "set_missing_values":
                invoice.disable_rounded_total = 1
            elif method == "calculate_taxes_and_totals":
                invoice.grand_total = 10.01
                invoice.rounded_total = 10

        invoice.run_method = run_method
        payment_entry = _payment_entry(
            paid_amount=10,
            base_paid_amount=10,
            received_amount=10,
            base_received_amount=10,
            unallocated_amount=10,
        )
        mapping = _payment_entry_mapping(payment_entry)

        with patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.new_doc",
            return_value=invoice,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.get_cached_doc",
            return_value=SimpleNamespace(cost_center="Main - TC"),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._get_preferred_deferred_revenue_account",
            return_value="",
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._get_ksa_vat_15_template",
            return_value=SimpleNamespace(),
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._ensure_standard_advance_payment_item"
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.exists",
            return_value=True,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.get_value",
            return_value=0,
        ), patch(
            "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._copy_tax_template_rows"
        ):
            result = _build_advance_sales_invoice(payment_entry, mapping)

        self.assertIs(result, invoice)
        self.assertEqual(invoice.disable_rounded_total, 0)
        self.assertEqual(_invoice_payment_total(invoice), Decimal("10"))

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


class TestPhase3DuplicateAndAllocationGuards(FrappeTestCase):
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.supports_advance_payment_entry_link",
        return_value=True,
    )
    @patch("zatca_erpgulf.zatca_erpgulf.advance_payment_entry.frappe.db.get_value")
    def test_active_standard_invoice_is_found(self, get_value, _supports_link):
        get_value.return_value = "SINV-ADV-0001"
        self.assertEqual(
            get_active_standard_advance_invoice("ACC-PAY-0001"),
            "SINV-ADV-0001",
        )
        filters = get_value.call_args.args[1]
        self.assertEqual(filters["docstatus"], ["<", 2])

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.supports_advance_payment_entry_link",
        return_value=False,
    )
    def test_missing_link_field_returns_no_duplicate(self, _supports_link):
        self.assertEqual(get_active_standard_advance_invoice("ACC-PAY-0001"), "")



    def test_allocation_to_linked_advance_invoice_is_blocked(self):
        payment_entry = _payment_entry(
            references=[
                SimpleNamespace(
                    reference_doctype="Sales Invoice",
                    reference_name="SINV-ADV-0001",
                    allocated_amount=115,
                )
            ]
        )
        with self.assertRaisesRegex(frappe.ValidationError, "allocated only"):
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
        with self.assertRaisesRegex(frappe.ValidationError, "allocated only"):
            _validate_existing_link_allocations(payment_entry, "SINV-ADV-0001")

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._is_allowed_final_invoice_allocation",
        return_value=True,
    )
    def test_allocation_to_consuming_submitted_final_invoice_is_allowed(self, _allowed):
        payment_entry = _payment_entry(
            references=[
                SimpleNamespace(
                    reference_doctype="Sales Invoice",
                    reference_name="SINV-FINAL-0001",
                    allocated_amount=115,
                )
            ]
        )
        _validate_existing_link_allocations(payment_entry, "SINV-ADV-0001")

    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry._validate_existing_link_allocations"
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.get_active_standard_advance_invoice",
        return_value="SINV-ADV-0001",
    )
    @patch(
        "zatca_erpgulf.zatca_erpgulf.advance_payment_entry.supports_advance_payment_entry_link",
        return_value=True,
    )
    def test_payment_entry_hook_uses_sales_invoice_schema_capability(
        self, _supports_link, _get_active, validate_allocations
    ):
        payment_entry = _payment_entry()
        validate_payment_entry_advance_allocations(payment_entry)
        validate_allocations.assert_called_once_with(payment_entry, "SINV-ADV-0001")


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
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        validate_sales_invoice_payment_entry_link(self._invoice())

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
    def test_currency_rounded_total_matches_payment_entry(
        self,
        _precision,
        get_doc,
        validate_source,
        _standard_guard,
    ):
        get_doc.return_value = _payment_entry(
            paid_amount=10,
            base_paid_amount=10,
            received_amount=10,
            base_received_amount=10,
        )
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        validate_sales_invoice_payment_entry_link(
            self._invoice(
                grand_total=10.01,
                rounded_total=10,
                disable_rounded_total=0,
            )
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
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "Company must match"):
            validate_sales_invoice_payment_entry_link(
                self._invoice(company="Other Company")
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
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "Customer must match"):
            validate_sales_invoice_payment_entry_link(
                self._invoice(customer="Other Customer")
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
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "currency must match"):
            validate_sales_invoice_payment_entry_link(self._invoice(currency="USD"))

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
    ):
        get_doc.return_value = _payment_entry(source_exchange_rate=3.75)
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "exchange rate must match"):
            validate_sales_invoice_payment_entry_link(
                self._invoice(conversion_rate=1)
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
    ):
        get_doc.return_value = _payment_entry()
        validate_source.return_value = _payment_entry_mapping(get_doc.return_value)
        with self.assertRaisesRegex(frappe.ValidationError, "payable total must match"):
            validate_sales_invoice_payment_entry_link(self._invoice(grand_total=100))
