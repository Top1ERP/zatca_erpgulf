from unittest import TestCase
from unittest.mock import patch

from zatca_erpgulf.overrides.payment_entry_dashboard import get_dashboard_data
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import ADVANCE_PAYMENT_ENTRY_LINK_FIELD


class TestPaymentEntryDashboardCompatibility(TestCase):
    @patch(
        "zatca_erpgulf.overrides.payment_entry_dashboard.supports_advance_payment_entry_link",
        return_value=False,
    )
    def test_old_schema_keeps_standard_dashboard_unchanged(self, _supports_link):
        data = {
            "fieldname": "payment_entry",
            "transactions": [{"label": "Reference", "items": ["Bank Transaction"]}],
            "non_standard_fieldnames": {},
        }

        result = get_dashboard_data(data)

        self.assertEqual(result, data)
        self.assertNotIn("Sales Invoice", result["non_standard_fieldnames"])

    @patch(
        "zatca_erpgulf.overrides.payment_entry_dashboard.supports_advance_payment_entry_link",
        return_value=True,
    )
    @patch("zatca_erpgulf.overrides.payment_entry_dashboard._", side_effect=lambda value: value)
    def test_supported_schema_adds_advance_sales_invoice_connection(self, _translate, _supports_link):
        result = get_dashboard_data(
            {
                "fieldname": "payment_entry",
                "transactions": [{"label": "Reference", "items": ["Bank Transaction"]}],
                "non_standard_fieldnames": {},
            }
        )

        self.assertEqual(
            result["non_standard_fieldnames"]["Sales Invoice"],
            ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
        )
        self.assertEqual(
            sum(
                "Sales Invoice" in (group.get("items") or [])
                for group in result["transactions"]
            ),
            1,
        )

    @patch(
        "zatca_erpgulf.overrides.payment_entry_dashboard.supports_advance_payment_entry_link",
        return_value=True,
    )
    def test_existing_sales_invoice_mapping_is_preserved(self, _supports_link):
        data = {
            "fieldname": "payment_entry",
            "transactions": [{"label": "Other", "items": ["Sales Invoice"]}],
            "non_standard_fieldnames": {"Sales Invoice": "another_payment_link"},
        }

        result = get_dashboard_data(data)

        self.assertEqual(
            result["non_standard_fieldnames"]["Sales Invoice"],
            "another_payment_link",
        )
        self.assertEqual(result["transactions"], data["transactions"])

    @patch(
        "zatca_erpgulf.overrides.payment_entry_dashboard.supports_advance_payment_entry_link",
        return_value=True,
    )
    @patch("zatca_erpgulf.overrides.payment_entry_dashboard._", side_effect=lambda value: value)
    def test_repeated_override_does_not_duplicate_connection(self, _translate, _supports_link):
        result = get_dashboard_data(get_dashboard_data({}))

        self.assertEqual(
            sum(
                "Sales Invoice" in (group.get("items") or [])
                for group in result["transactions"]
            ),
            1,
        )
