from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801 import (
    LEGACY_DOCTYPE,
    _assert_no_legacy_data,
)
from zatca_erpgulf.setup_customizations import (
    CRITICAL_CUSTOM_FIELDS,
    OBSOLETE_LEGACY_ADVANCE_FIELDS,
)
from zatca_erpgulf.zatca_erpgulf.advance_lifecycle import (
    get_advance_sales_invoice_for_payment_entry,
    get_advance_sales_invoice_from_return,
    is_accepted_advance_sales_invoice,
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


def _advance_invoice(**overrides):
    values = {
        "doctype": "Sales Invoice",
        "name": "SINV-ADV-TEST",
        "docstatus": 1,
        "is_advance_payment": 1,
        "custom_zatca_status": "REPORTED",
    }
    values.update(overrides)
    return _Doc(fields={"is_advance_payment"}, **values)


class TestLegacyAdvanceLifecycle(FrappeTestCase):
    def test_submitted_standard_advance_statuses_are_accepted(self):
        for status in (
            "REPORTED",
            "CLEARED",
            "PHASE 1 QR CREATED",
            "Phase-1 QR Generated",
        ):
            with self.subTest(status=status):
                self.assertTrue(
                    is_accepted_advance_sales_invoice(
                        _advance_invoice(custom_zatca_status=status)
                    )
                )

    def test_draft_or_unmarked_invoice_is_not_accepted(self):
        self.assertFalse(is_accepted_advance_sales_invoice(_advance_invoice(docstatus=0)))
        self.assertFalse(
            is_accepted_advance_sales_invoice(_advance_invoice(is_advance_payment=0))
        )

    @patch("frappe.get_doc")
    @patch("frappe.get_all")
    @patch("frappe.get_meta")
    def test_payment_entry_resolves_one_standard_advance_invoice(
        self,
        get_meta,
        get_all,
        get_doc,
    ):
        get_meta.return_value = _Meta({"custom_zatca_payment_entry"})
        get_all.return_value = ["SINV-ADV-TEST"]
        get_doc.return_value = _advance_invoice()

        invoice = get_advance_sales_invoice_for_payment_entry("ACC-PAY-TEST")

        self.assertEqual(invoice.name, "SINV-ADV-TEST")
        self.assertEqual(
            get_all.call_args.kwargs["filters"]["custom_zatca_payment_entry"],
            "ACC-PAY-TEST",
        )

    @patch("frappe.get_all", return_value=["SINV-ADV-1", "SINV-ADV-2"])
    @patch("frappe.get_meta", return_value=_Meta({"custom_zatca_payment_entry"}))
    def test_duplicate_active_invoices_are_blocked(self, _get_meta, _get_all):
        with self.assertRaisesRegex(frappe.ValidationError, "more than one active"):
            get_advance_sales_invoice_for_payment_entry("ACC-PAY-TEST")

    @patch("frappe.get_doc")
    @patch("frappe.db.exists", return_value=True)
    def test_return_against_resolves_standard_advance_invoice(self, _exists, get_doc):
        get_doc.return_value = _advance_invoice()
        return_doc = _Doc(
            doctype="Sales Invoice",
            is_return=1,
            return_against="SINV-ADV-TEST",
        )

        invoice = get_advance_sales_invoice_from_return(return_doc, strict=True)

        self.assertEqual(invoice.name, "SINV-ADV-TEST")


class TestLegacyAdvanceRetirementPatch(FrappeTestCase):
    def test_obsolete_fields_are_not_recreated_by_setup(self):
        for doctype, obsolete_fields in OBSOLETE_LEGACY_ADVANCE_FIELDS.items():
            active_fields = {
                row["fieldname"] for row in CRITICAL_CUSTOM_FIELDS.get(doctype, [])
            }
            self.assertTrue(active_fields.isdisjoint(obsolete_fields))

    @patch(
        "zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801._column_exists",
        return_value=False,
    )
    @patch(
        "zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801._count_rows",
        return_value=0,
    )
    @patch(
        "zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801._table_exists",
        return_value=True,
    )
    def test_empty_legacy_table_passes_guard(self, _table_exists, _count_rows, _column_exists):
        _assert_no_legacy_data()

    @patch(
        "zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801._column_exists",
        return_value=False,
    )
    @patch(
        "zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801._count_rows",
        return_value=1,
    )
    @patch(
        "zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801._table_exists",
        return_value=True,
    )
    def test_nonempty_legacy_table_stops_patch(
        self,
        _table_exists,
        _count_rows,
        _column_exists,
    ):
        with self.assertRaisesRegex(frappe.ValidationError, LEGACY_DOCTYPE):
            _assert_no_legacy_data()
