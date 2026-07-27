import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.setup_customizations import (
    force_sales_invoice_zatca_field_order_property_setter,
)
from zatca_erpgulf.zatca_erpgulf.doctype.zatca_advance_tax_invoice.zatca_advance_tax_invoice import (
    later_zadv_in_same_company_exists,
    reset_zadv_series_to_highest_existing,
    zadv_series_prefix_and_number,
)


def _assert_contiguous_sequence(testcase, order, expected):
    positions = []
    for fieldname in expected:
        testcase.assertIn(fieldname, order)
        positions.append(order.index(fieldname))

    testcase.assertEqual(
        positions,
        list(range(positions[0], positions[0] + len(expected))),
    )


class TestSalesInvoiceZATCALayoutRegression(FrappeTestCase):
    def test_sales_invoice_zatca_field_order_property_setter_keeps_approved_layout(self):
        result = force_sales_invoice_zatca_field_order_property_setter()

        self.assertFalse(result.get("skipped"))
        self.assertFalse(result.get("missing_fields"))

        property_setter = frappe.get_doc("Property Setter", "Sales Invoice-main-field_order")
        order = json.loads(property_setter.value)

        _assert_contiguous_sequence(
            self,
            order,
            [
                "column_break_14",
                "custom_zatca_status_notification",
                "is_pos",
            ],
        )

        _assert_contiguous_sequence(
            self,
            order,
            [
                "custom_section_break_gqwpx",
                "custom_zatca_tax_category",
                "custom_exemption_reason_code",
                "custom_zatca_discount_reason_code",
                "custom_zatca_discount_reason",
                "custom_submit_line_item_discount_to_zatca",
                "custom_column_break_h3ntp",
                "company_tax_id",
                "custom_uuid",
                "custom_zatca_status",
                "custom_column_break_hb6s7",
                "custom_zatca_third_party_invoice",
                "custom_zatca_nominal_invoice",
                "custom_zatca_export_invoice",
                "custom_summary_invoice",
                "custom_self_billed_invoice",
            ],
        )

        self.assertLess(order.index("custom_zatca_status_notification"), order.index("is_pos"))
        self.assertLess(order.index("company_tax_id"), order.index("custom_uuid"))

    def test_sales_invoice_meta_matches_forced_zatca_layout(self):
        force_sales_invoice_zatca_field_order_property_setter()

        meta = frappe.get_meta("Sales Invoice")
        order = [df.fieldname for df in meta.fields if df.fieldname]

        _assert_contiguous_sequence(
            self,
            order,
            [
                "custom_column_break_h3ntp",
                "company_tax_id",
                "custom_uuid",
                "custom_zatca_status",
            ],
        )


class TestZADVSeriesRegression(FrappeTestCase):
    def test_zadv_series_prefix_and_number_parses_standard_name(self):
        prefix, number = zadv_series_prefix_and_number("ZADV-SA-2026-00042")

        self.assertEqual(prefix, "ZADV-SA-2026-")
        self.assertEqual(number, 42)

    def test_later_zadv_in_same_company_exists_uses_combined_name_filters(self):
        rows = [
            SimpleNamespace(name="ZADV-SA-2026-00001"),
            SimpleNamespace(name="ZADV-SA-2026-00003"),
        ]

        with patch(
            "zatca_erpgulf.zatca_erpgulf.doctype.zatca_advance_tax_invoice.zatca_advance_tax_invoice.frappe.get_all",
            return_value=rows,
        ) as mock_get_all:
            self.assertTrue(
                later_zadv_in_same_company_exists(
                    "Square Angles Contacting Company",
                    "ZADV-SA-2026-00002",
                )
            )

        filters = mock_get_all.call_args.kwargs["filters"]

        self.assertIsInstance(filters, list)
        self.assertIn(
            ["ZATCA Advance Tax Invoice", "company", "=", "Square Angles Contacting Company"],
            filters,
        )
        self.assertIn(
            ["ZATCA Advance Tax Invoice", "name", "like", "ZADV-SA-2026-%"],
            filters,
        )
        self.assertIn(
            ["ZATCA Advance Tax Invoice", "name", "!=", "ZADV-SA-2026-00002"],
            filters,
        )

    def test_reset_zadv_series_excludes_deleted_name_and_sets_highest_existing_number(self):
        sql_calls = []

        def fake_sql(query, values=None, *args, **kwargs):
            sql_calls.append((query, values))
            if query.strip().lower().startswith("select name from `tabseries`"):
                return [("ZADV-SA-2026-",)]
            return None

        with patch(
            "zatca_erpgulf.zatca_erpgulf.doctype.zatca_advance_tax_invoice.zatca_advance_tax_invoice.frappe.get_all",
            return_value=[
                "ZADV-SA-2026-00001",
                "ZADV-SA-2026-00003",
            ],
        ) as mock_get_all, patch(
            "zatca_erpgulf.zatca_erpgulf.doctype.zatca_advance_tax_invoice.zatca_advance_tax_invoice.frappe.db.sql",
            side_effect=fake_sql,
        ):
            reset_zadv_series_to_highest_existing("ZADV-SA-2026-00004")

        filters = mock_get_all.call_args.kwargs["filters"]

        self.assertIn(
            ["ZATCA Advance Tax Invoice", "name", "like", "ZADV-SA-2026-%"],
            filters,
        )
        self.assertIn(
            ["ZATCA Advance Tax Invoice", "name", "!=", "ZADV-SA-2026-00004"],
            filters,
        )

        self.assertIn(
            (
                "update `tabSeries` set current = %s where name = %s",
                (3, "ZADV-SA-2026-"),
            ),
            sql_calls,
        )
