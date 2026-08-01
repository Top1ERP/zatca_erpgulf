import json
import frappe
from frappe.tests.utils import FrappeTestCase

from zatca_erpgulf.setup_customizations import (
    force_sales_invoice_zatca_field_order_property_setter,
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
