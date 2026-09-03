import json

from zatca_erpgulf.ksa_compliance.tax_details import get_item_tax_detail


def test_v15_json_tax_details():
    doc = {
        "items": [{"name": "row-1", "item_code": "ITEM-1", "idx": 1}],
        "taxes": [{"item_wise_tax_detail": json.dumps({"ITEM-1": [15, 12.5]})}],
    }
    assert get_item_tax_detail(doc, doc["items"][0]) == (12.5, 15.0)


def test_v16_child_table_uses_item_row_reference():
    doc = {
        "items": [{"name": "row-1", "item_code": "ITEM-1", "idx": 1}, {"name": "row-2", "item_code": "ITEM-2", "idx": 2}],
        "item_wise_tax_details": [
            {"item_row": "row-1", "tax_row": "tax-1", "rate": 15, "amount": 12.5},
            {"item_row": "row-2", "tax_row": "tax-1", "rate": 15, "amount": 25},
        ],
    }
    assert get_item_tax_detail(doc, doc["items"][0]) == (12.5, 15.0)
    assert get_item_tax_detail(doc, doc["items"][1]) == (25.0, 15.0)


def test_v16_child_table_supports_multiple_tax_rows():
    doc = {
        "items": [{"name": "row-1", "item_code": "ITEM-1", "idx": 1}],
        "item_wise_tax_details": [
            {"item_row": "row-1", "tax_row": "tax-1", "rate": 10, "amount": 10},
            {"item_row": "row-1", "tax_row": "tax-2", "rate": 5, "amount": 5},
        ],
    }
    assert get_item_tax_detail(doc, doc["items"][0]) == (15.0, 15.0)
