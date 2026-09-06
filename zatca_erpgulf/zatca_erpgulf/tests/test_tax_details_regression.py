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

