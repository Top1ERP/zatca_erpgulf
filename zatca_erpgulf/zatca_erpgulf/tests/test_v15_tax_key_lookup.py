"""Selected JSON-key folding against exact parent tax functions; offline only."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance import tax_details as tax
from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as sales
from zatca_erpgulf.zatca_erpgulf import pos_final, posxml, xml_tax_data
from zatca_erpgulf.zatca_erpgulf.tests.test_sales_item_builder_parity import source as sales_source
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_item_builder_parity import advance_source, prepare


REFERENCE = Path(__file__).parent / "fixtures" / "v15_tax_reads_76d3e9f.py"
REFERENCE_SHA256 = "829ae04da3ff81e3f8f360cde614e71f2099e7d568b41074596fb96fe9a380e8"


def parent_functions():
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(tax))
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace


class Tracked(dict):
    def __init__(self, role, trace, **values):
        super().__init__(values)
        self.role, self.trace = role, trace

    def get(self, key, default=None):
        self.trace.append((self.role, key))
        return super().get(key, default)


def sample(shape, raw_kind, currency, key_case, rate_policy):
    trace = []
    item = Tracked("item", trace, name="ROW", idx=1, item_code="ITEM", item_name="خدمة",
                   base_net_amount=100, net_amount=20.15)
    if key_case == "name":
        item["item_code"] = ""
        key = "خدمة"
    elif key_case == "collision":
        item["item_code"] = "8"
        key = "8"
    elif key_case == "missing":
        item["item_code"] = "MISSING"
        key = "MISSING"
    else:
        key = "ITEM"
    value = {"list": [15, 99], "long": {"tax_rate": 15, "tax_amount": 99},
             "short": {"rate": 15, "amount": 99}, "empty": [],
             "invalid": "invalid", "bad-number": ["invalid", None]}[shape]
    mapping = {"OTHER": [7, 77], "1": [10, 88]}
    if key_case != "missing":
        mapping[key] = value
    rows = []
    for index in range(2):
        raw = json.dumps(mapping) if raw_kind == "json" else deepcopy(mapping)
        row = Tracked("tax-" + str(index), trace, account_head="VAT", item_wise_tax_detail=raw)
        if rate_policy == "invoice":
            row["rate"] = 5
        rows.append(row)
    if rate_policy in ("item", "zero"):
        item["item_tax_rate"] = json.dumps({"VAT": 5 if rate_policy == "item" else 0})
    doc = Tracked("doc", trace, currency=currency, taxes=rows)
    return doc, item, trace, len(mapping) * len(rows)


@pytest.mark.parametrize("shape", ["list", "long", "short", "empty", "invalid", "bad-number"])
@pytest.mark.parametrize("raw_kind", ["json", "dict"])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("key_case", ["code", "name", "missing", "collision"])
@pytest.mark.parametrize("rate_policy", ["legacy", "invoice", "item", "zero"])
def test_native_amount_rate_reads_and_selected_work_match_parent(
    monkeypatch, shape, raw_kind, currency, key_case, rate_policy,
):
    doc, item, trace, full_count = sample(shape, raw_kind, currency, key_case, rate_policy)
    normalizer = Mock(wraps=tax._normalise_v15_value)
    monkeypatch.setattr(tax, "_normalise_v15_value", normalizer)
    parent = parent_functions()
    expected = parent["get_item_tax_detail"](doc, item)
    expected_reads = trace[:]
    assert normalizer.call_count == full_count
    trace.clear()
    normalizer.reset_mock()
    actual = tax.get_item_tax_detail(doc, item)
    assert tuple(value.hex() for value in actual) == tuple(value.hex() for value in expected)
    assert trace == expected_reads
    count = full_count if raw_kind == "dict" else 0 if key_case == "missing" else 2
    assert normalizer.call_count == count


@pytest.mark.parametrize("raw", [None, "", "null", "[]", "not-json", b'{"ITEM":[15,99]}',
                                  '{"ITEM":[15,99]}', {"ITEM": [15, 99]},
                                  '{"ITEM":[15,1],"ITEM":[5,2]}'])
def test_full_fold_default_and_invalid_raw_inputs_keep_parent_contract(raw):
    doc = {"taxes": [{"item_wise_tax_detail": raw}]}
    parent = parent_functions()
    assert tax._v15_details(doc) == parent["_v15_details"](doc)
    assert tax.get_item_tax_detail(doc, {"item_code": "ITEM"}) == parent["get_item_tax_detail"](doc, {"item_code": "ITEM"})


@pytest.mark.parametrize("pairs", [
    [(1, [5, 1]), ("1", [10, 2])], [("1", [10, 2]), (1, [5, 1])],
    [(None, [5, 1]), ("None", [10, 2])], [(True, [5, 1]), ("True", [10, 2])],
])
def test_direct_dict_nonstring_key_collisions_keep_complete_fold(pairs):
    raw = dict(pairs)
    key = str(pairs[0][0])
    doc = {"taxes": [{"item_wise_tax_detail": raw}]}
    parent = parent_functions()
    assert tax._v15_details(doc, item_key=key) == parent["_v15_details"](doc)
    assert tax.get_item_tax_detail(doc, {"item_code": key}) == parent["get_item_tax_detail"](doc, {"item_code": key})


@pytest.mark.parametrize("raw_kind", ["json", "dict"])
def test_unrelated_overflow_is_retired_only_for_the_json_selected_key(raw_kind):
    mapping = {"ITEM": [15, 1.5], "OTHER": [15, 10 ** 400]}
    raw = json.dumps(mapping) if raw_kind == "json" else mapping
    doc = {"taxes": [{"item_wise_tax_detail": raw}]}
    parent = parent_functions()
    with pytest.raises(OverflowError):
        parent["get_item_tax_detail"](doc, {"item_code": "ITEM"})
    if raw_kind == "json":
        assert tax.get_item_tax_detail(doc, {"item_code": "ITEM"}) == (1.5, 15.0)
    else:
        with pytest.raises(OverflowError):
            tax.get_item_tax_detail(doc, {"item_code": "ITEM"})
    # Requested bad values and the explicit full fold still fail normally.
    with pytest.raises(OverflowError):
        tax.get_item_tax_detail(doc, {"item_code": "OTHER"})
    with pytest.raises(OverflowError):
        tax._v15_details(doc)


@pytest.mark.parametrize("rows", [None, [], [{"item_row": "ROW", "rate": 0, "amount": 0}],
                                  [{"item_row": "OTHER", "rate": 15, "amount": 99}],
                                  [{"item_row": "ROW", "rate": 10, "amount": 99},
                                   {"item_row": "ROW", "rate": 5, "amount": 99}]])
def test_v16_presence_zero_unmatched_and_multiple_rows_remain_authoritative(rows):
    doc = {"currency": "SAR", "item_wise_tax_details": rows,
           "taxes": [{"rate": 5, "item_wise_tax_detail": '{"ITEM":[15,99]}'}]}
    item = {"name": "ROW", "item_code": "ITEM", "base_net_amount": 100}
    assert tax.get_item_tax_detail(doc, item) == parent_functions()["get_item_tax_detail"](doc, item)


MODES = ("sales-items", "advance-items", "pos-items", "sales-total", "pos-total",
         "nominal-rate", "nominal-breakdown", "sales-fallback-rate")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("raw_kind", ["json", "dict"])
def test_actual_sales_pos_nominal_and_totals_keep_parent_outputs_and_reads(
    advance_source, monkeypatch, mode, erp_major, currency, negative, raw_kind,
):
    s = advance_source
    doc = prepare(s, route="legacy" if mode == "advance-items" else "none",
                  erp_major=erp_major, currency=currency)
    doc.company, doc.pos_profile = "SYNTHETIC", "POS"
    if raw_kind == "dict":
        doc.taxes[0].item_wise_tax_detail = json.loads(doc.taxes[0].item_wise_tax_detail)
    for item in doc.items:
        item.price_list_rate, item.discount_amount, item.rate = 2.5, .5, 2.0
        if negative:
            for field in ("qty", "amount", "base_amount", "net_amount", "base_net_amount"):
                setattr(item, field, -abs(getattr(item, field)))
    s.records.update({
        ("POS Profile", "POS"): s.document("profile", taxes_and_charges="VAT"),
        ("Sales Taxes and Charges Template", "VAT"): s.document("invoice-template", taxes=[s.document("invoice-tax", included_in_print_rate=0)]),
        ("Company", "SYNTHETIC"): s.document("company", custom_submit_line_item_discount_to_zatca=0),
    })
    for module in (pos_final, posxml, xml_tax_data):
        monkeypatch.setattr(module, "frappe", s.runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    reference = parent_functions()
    reference["_line_tax_amount"] = lambda *args: 0.0
    # Rate consumers skip line-net calculation but retain v16 payload amounts.
    # These remaining-read cases own untracked v16 amount fields; the exact207
    # parent suite independently verifies both retained and skipped fields.
    parent_rate = lambda doc, item, **kwargs: reference["get_item_tax_detail"](doc, item)[1]
    outputs = []
    for lookup in (parent_rate, tax.get_item_tax_rate):
        for module in (sales, pos_final, posxml, xml_tax_data):
            monkeypatch.setattr(module, "get_item_tax_rate", lookup)
        s.trace.clear()
        s.runtime.get_doc.reset_mock()
        s.runtime.get_installed_apps.reset_mock()
        if mode.endswith("items"):
            root = ET.Element("Invoice")
            operation = {"sales-items": sales.item_data, "advance-items": sales.item_data_advance_invoice,
                         "pos-items": pos_final.item_data}[mode]
            assert operation(root, doc) is root
            result = ET.tostring(root)
        elif mode == "sales-total":
            result = xml_tax_data.get_tax_total_from_items(doc)
        elif mode == "pos-total":
            result = posxml.get_tax_total_from_items(doc)
        elif mode == "nominal-rate":
            result = sales._nominal_tax_rate_without_template(doc, doc.items[0])
        elif mode == "nominal-breakdown":
            result = sales._nominal_breakdown_without_template(doc)
        else:
            result = xml_tax_data._get_item_tax_rate_without_template(doc, doc.items[0])
        outputs.append((type(result), result, s.trace[:], s.runtime.get_doc.call_args_list[:],
                        s.runtime.get_installed_apps.call_args_list[:]))
    assert outputs[0] == outputs[1]
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    s.runtime.db.commit.assert_not_called()
    s.runtime.db.set_value.assert_not_called()
    s.runtime.log_error.assert_not_called()
    s.runtime.msgprint.assert_not_called()


def test_custom_decoder_mapping_keeps_full_fold(monkeypatch):
    class ParsedDict(dict):
        pass
    parsed = ParsedDict(ITEM=[15, 1.5], OTHER=[5, 2])
    monkeypatch.setattr(tax.json, "loads", lambda value: parsed)
    normalizer = Mock(wraps=tax._normalise_v15_value)
    monkeypatch.setattr(tax, "_normalise_v15_value", normalizer)
    doc = {"taxes": [{"item_wise_tax_detail": "synthetic-decoder-input"}]}
    assert tax._v15_details(doc, item_key="ITEM") == parent_functions()["_v15_details"](doc)
    assert normalizer.call_count == 4


@pytest.mark.parametrize("key", ["", 0, "0", "  ", "خدمة"])
def test_empty_numeric_whitespace_and_unicode_keys_keep_exact_matching(key):
    raw = json.dumps({str(key): [5, 2], "OTHER": [15, 99]})
    doc = {"taxes": [{"item_wise_tax_detail": raw}]}
    item = {"item_code": key}
    assert tax.get_item_tax_detail(doc, item) == parent_functions()["get_item_tax_detail"](doc, item) == (2.0, 5.0)
