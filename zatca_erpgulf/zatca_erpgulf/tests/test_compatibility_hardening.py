from __future__ import annotations

import inspect
import unittest
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from zatca_erpgulf.zatca_erpgulf import advance_credit_note
from zatca_erpgulf.zatca_erpgulf import advance_deduction
from zatca_erpgulf.zatca_erpgulf import advance_lifecycle
from zatca_erpgulf.zatca_erpgulf import advance_payment_entry
from zatca_erpgulf.zatca_erpgulf import create_xml_final_part
from zatca_erpgulf.zatca_erpgulf import sign_invoice
from zatca_erpgulf.zatca_erpgulf import tax_error
from zatca_erpgulf.zatca_erpgulf import zatca_runtime
from zatca_erpgulf.overrides import sales_invoice as sales_invoice_override


class _Meta:
    def __init__(self, fields=()):
        self.fields = set(fields)

    def has_field(self, fieldname):
        return fieldname in self.fields


class _Doc(SimpleNamespace):
    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def set(self, fieldname, value):
        setattr(self, fieldname, value)
        return value


def _raise_validation(message, *args, **kwargs):
    raise frappe.ValidationError(str(message))


@contextmanager
def _runtime_environment(meta_fields, table_columns, physical_tables):
    metas = {doctype: _Meta(fields) for doctype, fields in meta_fields.items()}
    db = SimpleNamespace(
        exists=MagicMock(
            side_effect=lambda doctype, name: bool(
                doctype == "DocType" and name in metas
            )
        ),
        table_exists=MagicMock(side_effect=lambda doctype: doctype in physical_tables),
        get_table_columns=MagicMock(
            side_effect=lambda doctype: list(table_columns.get(doctype, ()))
        ),
    )
    with (
        patch.object(zatca_runtime.frappe, "db", db),
        patch.object(
            zatca_runtime.frappe,
            "get_meta",
            side_effect=lambda doctype: metas[doctype],
        ),
    ):
        yield db


def _complete_runtime_schema():
    parent_fields = set(zatca_runtime.ADVANCE_DEDUCTION_PARENT_FIELDS)
    parent_fields.update(
        {
            "is_advance_payment",
            zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
        }
    )
    parent_columns = set(zatca_runtime.ADVANCE_DEDUCTION_PARENT_DB_FIELDS)
    parent_columns.update(
        {
            "is_advance_payment",
            zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
        }
    )
    return (
        {
            "Sales Invoice": parent_fields,
            zatca_runtime.ADVANCE_DEDUCTION_CHILD_DOCTYPE: set(
                zatca_runtime.ADVANCE_DEDUCTION_CHILD_FIELDS
            ),
        },
        {
            "Sales Invoice": parent_columns,
            zatca_runtime.ADVANCE_DEDUCTION_CHILD_DOCTYPE: set(
                zatca_runtime.ADVANCE_DEDUCTION_CHILD_DB_FIELDS
            ),
        },
        {"Sales Invoice", zatca_runtime.ADVANCE_DEDUCTION_CHILD_DOCTYPE},
    )


class TestERPNext16ClassContract(unittest.TestCase):
    def test_sales_invoice_override_inherits_erpnext_controller(self):
        self.assertTrue(issubclass(sales_invoice_override.ZatcaSalesInvoice, sales_invoice_override.SalesInvoice))

class TestRuntimeCapabilities(unittest.TestCase):
    def test_primary_marker_metadata_and_column_are_supported(self):
        with _runtime_environment(
            {"Sales Invoice": {"is_advance_payment"}},
            {"Sales Invoice": {"is_advance_payment"}},
            {"Sales Invoice"},
        ):
            self.assertTrue(zatca_runtime.supports_advance_payment_marker())

    def test_primary_marker_does_not_fall_back_to_valid_legacy_marker(self):
        with _runtime_environment(
            {
                "Sales Invoice": {
                    "is_advance_payment",
                    "custom_is_advance_payment",
                }
            },
            {
                "Sales Invoice": {
                    "custom_is_advance_payment"
                }
            },
            {"Sales Invoice"},
        ):
            self.assertFalse(zatca_runtime.supports_advance_payment_marker())

    def test_only_legacy_marker_metadata_and_column_are_supported(self):
        with _runtime_environment(
            {
                "Sales Invoice": {
                    "custom_is_advance_payment"
                }
            },
            {
                "Sales Invoice": {
                    "custom_is_advance_payment"
                }
            },
            {"Sales Invoice"},
        ):
            self.assertTrue(zatca_runtime.supports_advance_payment_marker())

    def test_no_valid_marker_is_not_supported(self):
        with _runtime_environment(
            {"Sales Invoice": set()},
            {"Sales Invoice": set()},
            {"Sales Invoice"},
        ):
            self.assertFalse(zatca_runtime.supports_advance_payment_marker())

    def test_payment_entry_link_requires_marker_metadata_and_column(self):
        with _runtime_environment(
            {
                "Sales Invoice": {
                    "is_advance_payment",
                    zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
                }
            },
            {
                "Sales Invoice": {
                    "is_advance_payment",
                    zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
                }
            },
            {"Sales Invoice"},
        ):
            self.assertTrue(zatca_runtime.supports_advance_payment_entry_link())

    def test_payment_entry_link_metadata_without_column_is_not_supported(self):
        with _runtime_environment(
            {
                "Sales Invoice": {
                    "is_advance_payment",
                    zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
                }
            },
            {"Sales Invoice": {"is_advance_payment"}},
            {"Sales Invoice"},
        ):
            self.assertFalse(zatca_runtime.supports_advance_payment_entry_link())

    def test_payment_entry_link_without_marker_is_not_supported(self):
        with _runtime_environment(
            {
                "Sales Invoice": {
                    zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD
                }
            },
            {
                "Sales Invoice": {
                    zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD
                }
            },
            {"Sales Invoice"},
        ):
            self.assertFalse(zatca_runtime.supports_advance_payment_entry_link())

    def test_complete_advance_deduction_schema_is_supported(self):
        meta_fields, columns, tables = _complete_runtime_schema()
        with _runtime_environment(meta_fields, columns, tables):
            self.assertTrue(zatca_runtime.supports_advance_deduction_schema())

    def test_missing_parent_metadata_field_is_not_supported(self):
        meta_fields, columns, tables = _complete_runtime_schema()
        meta_fields["Sales Invoice"].remove(
            "custom_zatca_advance_deduction_count"
        )
        with _runtime_environment(meta_fields, columns, tables):
            self.assertFalse(zatca_runtime.supports_advance_deduction_schema())

    def test_missing_parent_physical_column_is_not_supported(self):
        meta_fields, columns, tables = _complete_runtime_schema()
        columns["Sales Invoice"].remove(
            "custom_zatca_advance_deduction_count"
        )
        with _runtime_environment(meta_fields, columns, tables):
            self.assertFalse(zatca_runtime.supports_advance_deduction_schema())

    def test_missing_child_doctype_is_not_supported(self):
        meta_fields, columns, tables = _complete_runtime_schema()
        meta_fields.pop(zatca_runtime.ADVANCE_DEDUCTION_CHILD_DOCTYPE)
        with _runtime_environment(meta_fields, columns, tables):
            self.assertFalse(zatca_runtime.supports_advance_deduction_schema())

    def test_missing_physical_child_table_is_not_supported(self):
        meta_fields, columns, tables = _complete_runtime_schema()
        tables.remove(zatca_runtime.ADVANCE_DEDUCTION_CHILD_DOCTYPE)
        with _runtime_environment(meta_fields, columns, tables):
            self.assertFalse(zatca_runtime.supports_advance_deduction_schema())

    def test_missing_child_metadata_field_is_not_supported(self):
        meta_fields, columns, tables = _complete_runtime_schema()
        meta_fields[zatca_runtime.ADVANCE_DEDUCTION_CHILD_DOCTYPE].remove(
            "remarks"
        )
        with _runtime_environment(meta_fields, columns, tables):
            self.assertFalse(zatca_runtime.supports_advance_deduction_schema())

    def test_missing_child_sql_column_is_not_supported(self):
        meta_fields, columns, tables = _complete_runtime_schema()
        columns[zatca_runtime.ADVANCE_DEDUCTION_CHILD_DOCTYPE].remove(
            "allocated_tax_amount"
        )
        with _runtime_environment(meta_fields, columns, tables):
            self.assertFalse(zatca_runtime.supports_advance_deduction_schema())


class TestAdvanceDeductionSQLBoundary(unittest.TestCase):
    def test_capability_false_returns_zero_without_sql(self):
        db = SimpleNamespace(sql=MagicMock())
        with (
            patch.object(
                advance_deduction,
                "supports_advance_deduction_schema",
                return_value=False,
            ),
            patch.object(advance_deduction.frappe, "db", db),
        ):
            result = advance_deduction._submitted_final_allocation_total(
                "ADV-0001"
            )

        self.assertEqual(result, Decimal("0.00"))
        db.sql.assert_not_called()

    def test_capability_true_preserves_sql_total(self):
        db = SimpleNamespace(sql=MagicMock(return_value=[[Decimal("125.50")]]))
        with (
            patch.object(
                advance_deduction,
                "supports_advance_deduction_schema",
                return_value=True,
            ),
            patch.object(advance_deduction.frappe, "db", db),
        ):
            result = advance_deduction._submitted_final_allocation_total(
                "ADV-0001"
            )

        self.assertEqual(result, Decimal("125.50"))
        db.sql.assert_called_once()


class TestAdvanceDeductionConsumers(unittest.TestCase):
    def test_capability_false_skips_all_optional_consumers(self):
        doc = MagicMock()
        doc.doctype = "Sales Invoice"
        doc.flags = SimpleNamespace()
        gl_entries = [{"account": "Receivable"}]
        db = SimpleNamespace(
            sql=MagicMock(),
            set_value=MagicMock(),
        )

        with (
            patch.object(
                advance_deduction,
                "supports_advance_deduction_schema",
                return_value=False,
            ),
            patch.object(advance_deduction.frappe, "db", db),
            patch.object(
                advance_deduction.frappe, "get_list", return_value=[]
            ) as get_list,
            patch.object(
                advance_deduction.frappe, "get_doc"
            ) as get_doc,
            patch.object(
                advance_deduction.frappe, "get_cached_doc",
                return_value=SimpleNamespace(),
            ) as get_cached_doc,
        ):
            self.assertEqual(
                advance_deduction.populate_zatca_advance_deductions(doc), []
            )
            self.assertEqual(
                advance_deduction._validate_sales_invoice_advance_deductions(
                    doc,
                    lock=False,
                ),
                [],
            )
            self.assertEqual(
                advance_deduction.get_direct_advance_deduction_rows(doc), []
            )
            self.assertIs(
                advance_deduction.append_advance_deduction_gl_entries(
                    doc, gl_entries
                ),
                gl_entries,
            )
            allocation_details = inspect.unwrap(
                advance_deduction.get_advance_allocation_details
            )
            self.assertEqual(allocation_details("ADV-0001"), {})
            search = inspect.unwrap(
                advance_deduction.get_available_advance_invoice_query
            )
            self.assertEqual(
                search(
                    "Sales Invoice",
                    "ADV",
                    "name",
                    0,
                    20,
                    {"company": "Company"},
                ),
                [],
            )
            self.assertIsNone(
                advance_deduction.ensure_final_sales_invoice_qr_for_print(doc)
            )

        doc.get.assert_not_called()
        doc.set.assert_not_called()
        doc.append.assert_not_called()
        get_list.assert_not_called()
        get_doc.assert_not_called()
        db.sql.assert_not_called()
        db.set_value.assert_not_called()

    def test_capability_true_preserves_return_invoice_validation(self):
        doc = _Doc(
            doctype="Sales Invoice",
            docstatus=0,
            is_return=1,
            taxes=[],
            custom_zatca_advance_deduction_details=[
                _Doc(advance_invoice="ADV-0001")
            ],
            flags=SimpleNamespace(),
            meta=_Meta(),
        )
        with (
            patch.object(
                advance_deduction,
                "supports_advance_deduction_schema",
                return_value=True,
            ),
            patch.object(
                advance_deduction.frappe,
                "throw",
                side_effect=_raise_validation,
            ),
            patch.object(
                advance_deduction,
                "_",
                side_effect=lambda message: message,
            ),
        ):
            with self.assertRaises(frappe.ValidationError):
                advance_deduction._validate_sales_invoice_advance_deductions(
                    doc,
                    lock=False,
                )


class TestAdvanceCreditNoteCompatibility(unittest.TestCase):
    def test_missing_capability_skips_lock_and_child_sql_but_keeps_validation(self):
        advance_doc = _Doc(
            name="ADV-0001",
            company="Company",
            customer="Customer",
            currency="SAR",
            grand_total=Decimal("1000"),
            rounded_total=Decimal("0"),
        )
        credit_doc = _Doc(
            name="CN-0002",
            company="Company",
            customer="Customer",
            currency="SAR",
            grand_total=Decimal("-300"),
            rounded_total=Decimal("0"),
            docstatus=1,
        )
        old_credit = _Doc(
            grand_total=Decimal("-800"),
            rounded_total=Decimal("0"),
        )
        db = SimpleNamespace(sql=MagicMock())

        with (
            patch.object(
                advance_credit_note,
                "supports_advance_deduction_schema",
                return_value=False,
            ),
            patch.object(
                advance_credit_note,
                "get_advance_sales_invoice_from_return",
                return_value=advance_doc,
            ),
            patch.object(
                advance_credit_note,
                "_get_submitted_credit_notes",
                return_value=[old_credit],
            ),
            patch.object(
                advance_deduction,
                "supports_advance_deduction_schema",
                return_value=False,
            ),
            patch.object(
                advance_deduction, "_lock_advance_invoice"
            ) as lock_invoice,
            patch.object(advance_deduction.frappe, "db", db),
            patch.object(
                advance_credit_note.frappe,
                "format_value",
                side_effect=lambda value, *args, **kwargs: str(value),
            ),
            patch.object(
                advance_credit_note.frappe,
                "throw",
                side_effect=_raise_validation,
            ),
            patch.object(
                advance_credit_note,
                "_",
                side_effect=lambda message: message,
            ),
        ):
            with self.assertRaises(frappe.ValidationError):
                advance_credit_note.validate_advance_credit_note_against_original(credit_doc)

        lock_invoice.assert_not_called()
        db.sql.assert_not_called()


class TestXmlSignAndTaxCompatibility(unittest.TestCase):
    def test_xml_direct_rows_are_ignored_without_capability(self):
        invoice = _Doc(
            custom_zatca_advance_deduction_details=[
                _Doc(advance_invoice="ADV-0001")
            ]
        )
        with patch.object(
            create_xml_final_part,
            "supports_advance_deduction_schema",
            return_value=False,
        ):
            self.assertEqual(
                create_xml_final_part._direct_advance_rows(invoice), []
            )

    def test_signing_uses_regular_xml_branch_without_capability(self):
        class StopAfterBranch(Exception):
            pass

        invoice = object()
        sales_doc = _Doc(
            doctype="Sales Invoice",
            name="SINV-0001",
            company="Company",
            customer="Customer",
            custom_zatca_export_invoice=0,
            custom_zatca_nominal_invoice=0,
            custom_zatca_advance_deduction_details=[
                _Doc(advance_invoice="ADV-0001")
            ],
            is_return=0,
        )
        customer = _Doc(custom_b2c=0)
        db = SimpleNamespace(
            exists=MagicMock(return_value=True),
            get_value=MagicMock(return_value="Standard"),
        )

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(sign_invoice.frappe, "db", db)
            )
            stack.enter_context(
                patch.object(
                    sign_invoice.frappe,
                    "get_doc",
                    return_value=customer,
                )
            )
            stack.enter_context(
                patch.object(
                    sign_invoice.frappe,
                    "get_installed_apps",
                    return_value=[],
                )
            )
            stack.enter_context(
                patch.object(
                    sign_invoice,
                    "supports_advance_deduction_schema",
                    return_value=False,
                )
            )
            stack.enter_context(
                patch.object(
                    sign_invoice,
                    "salesinvoice_data",
                    return_value=(invoice, "UUID-1", sales_doc),
                )
            )
            stack.enter_context(
                patch.object(sign_invoice, "xml_tags", return_value=invoice)
            )
            for function_name in (
                "invoice_typecode_standard",
                "doc_reference",
                "additional_reference",
                "company_data",
                "customer_data",
                "delivery_and_payment_means",
                "add_document_level_discount_with_tax",
                "tax_data",
            ):
                stack.enter_context(
                    patch.object(
                        sign_invoice,
                        function_name,
                        side_effect=lambda current, *args, **kwargs: current,
                    )
                )
            regular_items = stack.enter_context(
                patch.object(
                    sign_invoice,
                    "item_data",
                    side_effect=StopAfterBranch,
                )
            )
            advance_items = stack.enter_context(
                patch.object(sign_invoice, "item_data_advance_invoice")
            )

            with self.assertRaises(StopAfterBranch):
                inspect.unwrap(sign_invoice.zatca_call)(
                    "SINV-0001",
                    any_item_has_tax_template=False,
                )

        regular_items.assert_called_once()
        advance_items.assert_not_called()

    def test_tax_deduction_exception_is_disabled_without_capability(self):
        invoice = _Doc(
            custom_zatca_nominal_invoice=0,
            custom_zatca_export_invoice=0,
            custom_zatca_prepaid_amount=Decimal("100"),
            custom_zatca_advance_deduction_count=1,
        )
        with patch.object(
            tax_error,
            "supports_advance_deduction_schema",
            return_value=False,
        ):
            self.assertFalse(
                tax_error._has_allowed_zero_tax_standard_exception(invoice)
            )

    def test_tax_nominal_and_export_exceptions_are_unchanged(self):
        nominal = _Doc(
            custom_zatca_nominal_invoice=1,
            custom_zatca_export_invoice=0,
        )
        export = _Doc(
            custom_zatca_nominal_invoice=0,
            custom_zatca_export_invoice=1,
        )
        with patch.object(
            tax_error,
            "supports_advance_deduction_schema",
            return_value=False,
        ):
            self.assertTrue(
                tax_error._has_allowed_zero_tax_standard_exception(nominal)
            )
            self.assertTrue(
                tax_error._has_allowed_zero_tax_standard_exception(export)
            )


class TestSalesInvoiceOverrideCompatibility(unittest.TestCase):
    @staticmethod
    def _advance_doc():
        return _Doc(
            meta=_Meta(
                {
                    "remarks",
                    "allocate_advances_automatically",
                    "advances",
                    "custom_zatca_advance_deduction_details",
                    "custom_zatca_prepaid_amount",
                    "custom_zatca_advance_deduction_count",
                    "custom_zatca_advance_deducted_taxable_amount",
                    "custom_zatca_advance_deducted_vat_amount",
                }
            ),
            remarks="",
            allocate_advances_automatically=1,
            advances=[_Doc(reference_name="PE-0001")],
            custom_zatca_advance_deduction_details=[
                _Doc(advance_invoice="ADV-0001")
            ],
            custom_zatca_prepaid_amount=Decimal("10"),
            custom_zatca_advance_deduction_count=1,
            custom_zatca_advance_deducted_taxable_amount=Decimal("8.70"),
            custom_zatca_advance_deducted_vat_amount=Decimal("1.30"),
        )

    def test_capability_false_keeps_standard_normalization_only(self):
        doc = self._advance_doc()
        deduction_rows = doc.custom_zatca_advance_deduction_details

        with (
            patch.object(
                sales_invoice_override,
                "is_advance_payment_invoice",
                return_value=True,
            ),
            patch.object(
                sales_invoice_override,
                "supports_advance_deduction_schema",
                return_value=False,
            ),
            patch.object(
                sales_invoice_override,
                "_",
                side_effect=lambda message: message,
            ),
        ):
            sales_invoice_override.normalize_advance_payment_invoice(doc)

        self.assertIn("Advance Payment Invoice", doc.remarks)
        self.assertEqual(doc.allocate_advances_automatically, 0)
        self.assertEqual(doc.advances, [])
        self.assertIs(doc.custom_zatca_advance_deduction_details, deduction_rows)
        self.assertEqual(doc.custom_zatca_prepaid_amount, Decimal("10"))
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 1)
        self.assertEqual(
            doc.custom_zatca_advance_deducted_taxable_amount, Decimal("8.70")
        )
        self.assertEqual(doc.custom_zatca_advance_deducted_vat_amount, Decimal("1.30"))

    def test_get_gl_entries_accepts_v15_and_v16_parameter_names(self):
        signature = inspect.signature(sales_invoice_override.ZatcaSalesInvoice.get_gl_entries)
        self.assertIn("inventory_account_map", signature.parameters)
        self.assertIn("kwargs", signature.parameters)

    def test_capability_true_preserves_deduction_cleanup(self):
        doc = self._advance_doc()

        with (
            patch.object(
                sales_invoice_override,
                "is_advance_payment_invoice",
                return_value=True,
            ),
            patch.object(
                sales_invoice_override,
                "supports_advance_deduction_schema",
                return_value=True,
            ),
            patch.object(
                sales_invoice_override,
                "_",
                side_effect=lambda message: message,
            ),
        ):
            sales_invoice_override.normalize_advance_payment_invoice(doc)

        self.assertEqual(doc.advances, [])
        self.assertEqual(doc.custom_zatca_advance_deduction_details, [])
        self.assertEqual(doc.custom_zatca_prepaid_amount, 0)
        self.assertEqual(doc.custom_zatca_advance_deduction_count, 0)
        self.assertEqual(doc.custom_zatca_advance_deducted_taxable_amount, 0)
        self.assertEqual(doc.custom_zatca_advance_deducted_vat_amount, 0)


class TestPaymentEntryCompatibility(unittest.TestCase):
    def test_capability_false_skips_active_link_query_and_lock(self):
        db = SimpleNamespace(
            get_value=MagicMock(),
            sql=MagicMock(),
        )
        with (
            patch.object(
                advance_payment_entry,
                "supports_advance_payment_entry_link",
                return_value=False,
            ),
            patch.object(advance_payment_entry.frappe, "db", db),
        ):
            self.assertEqual(
                advance_payment_entry.get_active_standard_advance_invoice(
                    "PE-0001"
                ),
                "",
            )
            self.assertIsNone(
                advance_payment_entry.ensure_payment_entry_has_no_active_standard_advance_invoice(
                    "PE-0001"
                )
            )

        db.get_value.assert_not_called()
        db.sql.assert_not_called()

    def test_capability_false_create_returns_empty_without_loading_document(self):
        with (
            patch.object(
                advance_payment_entry,
                "supports_advance_payment_entry_link",
                return_value=False,
            ),
            patch.object(
                advance_payment_entry.frappe, "get_doc"
            ) as get_doc,
        ):
            self.assertEqual(
                inspect.unwrap(
                    advance_payment_entry.create_advance_sales_invoice_from_payment_entry
                )(
                    "PE-0001"
                ),
                {},
            )

        get_doc.assert_not_called()

    def test_capability_false_validation_is_no_op(self):
        doc = MagicMock()
        with (
            patch.object(
                advance_payment_entry,
                "supports_advance_payment_entry_link",
                return_value=False,
            ),
            patch.object(
                advance_payment_entry.frappe, "get_doc"
            ) as get_doc,
        ):
            self.assertIsNone(
                advance_payment_entry.validate_sales_invoice_payment_entry_link(
                    doc
                )
            )

        doc.get.assert_not_called()
        get_doc.assert_not_called()

    def test_lifecycle_non_strict_is_none_and_strict_reports_unavailable_schema(self):
        with (
            patch.object(
                advance_lifecycle,
                "supports_advance_payment_entry_link",
                return_value=False,
            ),
            patch.object(
                advance_lifecycle.frappe,
                "throw",
                side_effect=_raise_validation,
            ),
            patch.object(
                advance_lifecycle,
                "_",
                side_effect=lambda message: message,
            ),
        ):
            self.assertIsNone(
                advance_lifecycle.get_advance_sales_invoice_for_payment_entry(
                    "ADV-0001",
                    strict=False,
                )
            )
            with self.assertRaisesRegex(
                frappe.ValidationError, "missing or unavailable"
            ):
                advance_lifecycle.get_advance_sales_invoice_for_payment_entry(
                    "ADV-0001",
                    strict=True,
                )

    def test_capability_true_preserves_active_link_query(self):
        db = SimpleNamespace(
            get_value=MagicMock(return_value="ADV-0001"),
        )
        with (
            patch.object(
                advance_payment_entry,
                "supports_advance_payment_entry_link",
                return_value=True,
            ),
            patch.object(advance_payment_entry.frappe, "db", db),
        ):
            self.assertEqual(
                advance_payment_entry.get_active_standard_advance_invoice(
                    "PE-0001"
                ),
                "ADV-0001",
            )

        db.get_value.assert_called_once()

    def test_capability_true_preserves_link_validation(self):
        doc = _Doc(
            meta=_Meta(
                {zatca_runtime.ADVANCE_PAYMENT_ENTRY_LINK_FIELD}
            ),
            custom_zatca_payment_entry="PE-0001",
        )
        with (
            patch.object(
                advance_payment_entry,
                "supports_advance_payment_entry_link",
                return_value=True,
            ),
            patch.object(
                advance_payment_entry,
                "is_advance_payment_invoice",
                return_value=False,
            ),
            patch.object(
                advance_payment_entry.frappe,
                "throw",
                side_effect=_raise_validation,
            ),
            patch.object(
                advance_payment_entry,
                "_",
                side_effect=lambda message: message,
            ),
        ):
            with self.assertRaises(frappe.ValidationError):
                advance_payment_entry.validate_sales_invoice_payment_entry_link(
                    doc
                )


if __name__ == "__main__":
    unittest.main()
