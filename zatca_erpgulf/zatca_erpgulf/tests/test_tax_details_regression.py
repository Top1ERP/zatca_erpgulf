import json
import unittest

from zatca_erpgulf.ksa_compliance.tax_details import get_item_tax_detail


class TestTaxDetailsRegression(unittest.TestCase):
    def test_v15_item_code_does_not_collide_with_other_row_idx(self):
        doc = {
            "taxes": [
                {
                    "item_wise_tax_detail": json.dumps(
                        {"8": [15, 1275], "1": [15, 975]}
                    )
                }
            ]
        }
        first_item = {"name": "row-1", "item_code": "8", "idx": 1}
        second_item = {"name": "row-2", "item_code": "1", "idx": 2}

        self.assertEqual(get_item_tax_detail(doc, first_item), (1275.0, 15.0))
        self.assertEqual(get_item_tax_detail(doc, second_item), (975.0, 15.0))

    def test_v15_falls_back_to_item_name_only_when_item_code_is_missing(self):
        doc = {
            "taxes": [
                {
                    "item_wise_tax_detail": json.dumps(
                        {"Service without code": [5, 10]}
                    )
                }
            ]
        }
        item = {
            "name": "row-1",
            "item_code": "",
            "item_name": "Service without code",
            "idx": 1,
        }

        self.assertEqual(get_item_tax_detail(doc, item), (10.0, 5.0))

    def test_v15_invoice_level_tax_uses_each_duplicate_row_net(self):
        """The legacy map aggregates duplicate keys; XML tax must not."""
        doc = {
            "currency": "SAR",
            "taxes": [
                {
                    "account_head": "VAT - CO",
                    "rate": 15,
                    "item_wise_tax_detail": json.dumps({"ITEM-1": [15, 105]}),
                }
            ],
        }
        first_item = {
            "name": "row-1",
            "item_code": "ITEM-1",
            "item_name": "Repeated item",
            "base_net_amount": 100,
            "idx": 1,
        }
        second_item = {
            "name": "row-2",
            "item_code": "ITEM-1",
            "item_name": "Repeated item",
            "base_net_amount": 600,
            "idx": 2,
        }

        self.assertEqual(get_item_tax_detail(doc, first_item), (15.0, 15.0))
        self.assertEqual(get_item_tax_detail(doc, second_item), (90.0, 15.0))

    def test_v16_empty_tax_detail_table_uses_invoice_level_rate(self):
        doc = {
            "currency": "SAR",
            "item_wise_tax_details": [],
            "taxes": [{"rate": 15}],
        }
        item = {"name": "row-1", "item_code": "ITEM-1", "base_net_amount": 100}

        self.assertEqual(get_item_tax_detail(doc, item), (15.0, 15.0))

    def test_v16_matches_only_child_row_name_not_idx_or_item_code(self):
        doc = {
            "item_wise_tax_details": [
                {
                    "item_row": "row-1",
                    "tax_row": "tax-1",
                    "rate": 15,
                    "amount": 1275,
                },
                {
                    "item_row": "row-2",
                    "tax_row": "tax-1",
                    "rate": 15,
                    "amount": 975,
                },
            ]
        }
        first_item = {"name": "row-1", "item_code": "8", "idx": 1}
        second_item = {"name": "row-2", "item_code": "1", "idx": 2}

        self.assertEqual(get_item_tax_detail(doc, first_item), (1275.0, 15.0))
        self.assertEqual(get_item_tax_detail(doc, second_item), (975.0, 15.0))

    def test_v16_duplicate_rows_use_their_own_net_amounts(self):
        doc = {
            "currency": "SAR",
            "item_wise_tax_details": [
                {"item_row": "row-1", "rate": 15, "amount": 999},
                {"item_row": "row-2", "rate": 15, "amount": 999},
            ],
        }
        first_item = {"name": "row-1", "item_code": "ITEM-1", "base_net_amount": 100}
        second_item = {"name": "row-2", "item_code": "ITEM-1", "base_net_amount": 200}

        self.assertEqual(get_item_tax_detail(doc, first_item), (15.0, 15.0))
        self.assertEqual(get_item_tax_detail(doc, second_item), (30.0, 15.0))

    def test_v16_zero_tax_row_is_authoritative_when_matched(self):
        doc = {
            "item_wise_tax_details": [
                {
                    "item_row": "row-1",
                    "tax_row": "tax-1",
                    "rate": 0,
                    "amount": 0,
                }
            ],
            "taxes": [
                {"item_wise_tax_detail": json.dumps({"ITEM-1": [15, 150]})}
            ],
        }
        item = {"name": "row-1", "item_code": "ITEM-1", "idx": 1}

        self.assertEqual(get_item_tax_detail(doc, item), (0.0, 0.0))

    def test_v16_table_does_not_fall_back_to_stale_v15_json_for_unmatched_item(self):
        doc = {
            "item_wise_tax_details": [
                {
                    "item_row": "row-2",
                    "tax_row": "tax-1",
                    "rate": 15,
                    "amount": 975,
                }
            ],
            "taxes": [
                {"item_wise_tax_detail": json.dumps({"ITEM-1": [15, 150]})}
            ],
        }
        item = {"name": "row-1", "item_code": "ITEM-1", "idx": 1}

        self.assertEqual(get_item_tax_detail(doc, item), (0.0, 0.0))

