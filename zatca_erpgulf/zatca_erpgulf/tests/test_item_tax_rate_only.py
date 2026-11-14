"""Shared rate-only selection, unchanged full API and actual consumer parity."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance import tax_details as tax
from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as sales, pos_final, posxml, xml_tax_data
from zatca_erpgulf.zatca_erpgulf.tests.test_sales_item_builder_parity import source as sales_source
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_item_builder_parity import advance_source, prepare
from zatca_erpgulf.zatca_erpgulf.tests.test_v15_tax_key_lookup import (
    Tracked, sample, MODES,
)

REFERENCE = Path(__file__).parent / "fixtures" / "item_tax_detail_cf26483.py"
REFERENCE_SHA256 = "8cddf9e41c9cc1892a5dbfb8b6f8147277eb9089eaa2e541c24194d75fc99a8d"


def parent_function():
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(tax))
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace["get_item_tax_detail"]


def native_outcome(operation, doc, item):
    try:
        result = operation(doc, item)
    except Exception as error:
        return "error", type(error), str(error)
    values = result if isinstance(result, tuple) else (result,)
    return "value", tuple((type(value), value.hex()) for value in values)


@pytest.mark.parametrize("shape", ["list", "long", "short", "empty", "invalid", "bad-number"])
@pytest.mark.parametrize("raw_kind", ["json", "dict"])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("key_case", ["code", "name", "missing", "collision"])
@pytest.mark.parametrize("rate_policy", ["legacy", "invoice", "item", "zero"])
def test_v15_full_api_is_exact_and_rate_only_removes_only_line_amount_reads(
    monkeypatch, shape, raw_kind, currency, key_case, rate_policy,
):
    doc, item, trace, _ = sample(shape, raw_kind, currency, key_case, rate_policy)
    original = tax._line_tax_amount
    retired = []
    def observe(*args):
        before = len(trace)
        try:
            return original(*args)
        finally:
            retired.extend(range(before, len(trace)))
    monkeypatch.setattr(tax, "_line_tax_amount", observe)
    parent = parent_function()
    expected = native_outcome(parent, doc, item)
    expected_reads = trace[:]
    remaining_reads = [read for i, read in enumerate(trace) if i not in retired]
    trace.clear()
    assert native_outcome(tax.get_item_tax_detail, doc, item) == expected
    assert trace == expected_reads
    trace.clear()
    monkeypatch.setattr(tax, "_line_tax_amount", Mock(side_effect=AssertionError("Finite rate-only must not calculate unused amount")))
    assert native_outcome(tax.get_item_tax_rate, doc, item) == ("value", (expected[1][1],))
    assert trace == remaining_reads


@pytest.mark.parametrize("rows", ["matched", "zero", "unmatched", "blank-name", "multiple", "empty", "none", "absent"])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("net", [None, 0, 100, -100])
def test_v16_full_contract_authority_and_rate_only_remaining_reads(monkeypatch, rows, currency, net):
    trace = []
    doc = Tracked("doc", trace, currency=currency,
        taxes=[Tracked("tax", trace, rate=5, item_wise_tax_detail='{"ITEM":[15,99]}')])
    item = Tracked("item", trace, name="ROW", item_code="ITEM", idx=1,
                   base_net_amount=net, net_amount=net)
    if rows == "empty":
        doc["item_wise_tax_details"] = []
    elif rows == "none":
        doc["item_wise_tax_details"] = None
    elif rows != "absent":
        doc["item_wise_tax_details"] = [Tracked("detail-1", trace,
            item_row="OTHER" if rows == "unmatched" else "ROW", amount=99,
            rate=0 if rows == "zero" else 10)]
        if rows == "multiple":
            doc["item_wise_tax_details"].append(Tracked("detail-2", trace, item_row="ROW", amount=99, rate=5))
        if rows == "blank-name":
            item["name"] = ""
    original = tax._line_tax_amount
    retired = []
    def observe(*args):
        start = len(trace)
        try:
            return original(*args)
        finally:
            retired.extend(range(start, len(trace)))
    monkeypatch.setattr(tax, "_line_tax_amount", observe)
    expected = native_outcome(parent_function(), doc, item)
    expected_reads = trace[:]
    remaining = [read for i, read in enumerate(trace) if i not in retired]
    trace.clear()
    assert native_outcome(tax.get_item_tax_detail, doc, item) == expected
    assert trace == expected_reads
    trace.clear()
    monkeypatch.setattr(tax, "_line_tax_amount", Mock(side_effect=AssertionError("Unexpected finite amount work")))
    assert native_outcome(tax.get_item_tax_rate, doc, item) == ("value", (expected[1][1],))
    assert trace == remaining


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("bad_net", [10 ** 400, Decimal("Infinity")])
def test_finite_rate_lookup_does_not_validate_unused_net_amount(major, bad_net):
    doc = {"currency": "SAR", "taxes": [{"rate": 15, "item_wise_tax_detail": '{"ITEM":[15,1.5]}'}]}
    if major == 16:
        doc["item_wise_tax_details"] = [{"item_row": "ROW", "rate": 15, "amount": 1.5}]
    item = {"name": "ROW", "item_code": "ITEM", "base_net_amount": bad_net}
    assert native_outcome(parent_function(), doc, item)[0] == "error"
    assert native_outcome(tax.get_item_tax_detail, doc, item) == native_outcome(parent_function(), doc, item)
    assert tax.get_item_tax_rate(doc, item) == 15.0


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("rate", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("has_net", [False, True])
def test_nonfinite_rate_preserves_old_line_calculation_boundary(major, rate, has_net):
    doc = {"currency": "SAR", "taxes": [{"rate": rate, "item_wise_tax_detail": json.dumps({"ITEM": [rate, 1.5]})}]}
    if major == 16:
        doc["item_wise_tax_details"] = [{"item_row": "ROW", "rate": rate, "amount": 1.5}]
    item = {"name": "ROW", "item_code": "ITEM"}
    if has_net:
        item["base_net_amount"] = 100
    expected = native_outcome(parent_function(), doc, item)
    assert native_outcome(tax.get_item_tax_detail, doc, item) == expected
    actual = native_outcome(tax.get_item_tax_rate, doc, item)
    if expected[0] == "error":
        assert actual == expected
    else:
        assert actual == ("value", (expected[1][1],))


@pytest.mark.parametrize("major", [15, 16])
def test_payload_amount_conversion_errors_remain_for_both_apis(major):
    doc = {"taxes": [{"item_wise_tax_detail": json.dumps({"ITEM": [15, 10 ** 400]})}]}
    if major == 16:
        doc["item_wise_tax_details"] = [{"item_row": "ROW", "rate": 15, "amount": 10 ** 400}]
    item = {"name": "ROW", "item_code": "ITEM"}
    expected = native_outcome(parent_function(), doc, item)
    assert expected[0] == "error"
    assert native_outcome(tax.get_item_tax_detail, doc, item) == expected
    assert native_outcome(tax.get_item_tax_rate, doc, item) == expected


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("rate", [15.0, float("inf"), float("nan")])
def test_real_consumer_results_and_errors_match_full_parent_rate(
    advance_source, monkeypatch, mode, major, currency, negative, rate,
):
    s = advance_source
    doc = prepare(s, route="legacy" if mode == "advance-items" else "none",
                  erp_major=major, currency=currency)
    doc.company, doc.pos_profile = "SYNTHETIC", "POS"
    doc.taxes[0].rate = rate
    doc.taxes[0].item_wise_tax_detail = json.dumps({"ITEM": [rate, 99]})
    for row in getattr(doc, "item_wise_tax_details", []):
        row.rate = rate
    for item in doc.items:
        item.item_tax_rate = json.dumps({"VAT": rate})
        item.price_list_rate, item.discount_amount, item.rate = 2.5, .5, 2.0
        if negative:
            for field in ("qty", "amount", "base_amount", "net_amount", "base_net_amount"):
                setattr(item, field, -abs(getattr(item, field)))
    s.records.update({
        ("POS Profile", "POS"): s.document("profile", taxes_and_charges="VAT"),
        ("Sales Taxes and Charges Template", "VAT"): s.document("invoice-template", taxes=[s.document("invoice-tax", included_in_print_rate=0)]),
        ("Company", "SYNTHETIC"): s.document("company", custom_submit_line_item_discount_to_zatca=0),
    })
    if mode == "pos-items":
        from zatca_erpgulf.zatca_erpgulf.tests.test_pos_financial_xml import rate_consumer_invoice
        doc, records = rate_consumer_invoice(major, currency, negative=negative, rate=rate)
        s.records.update(records)
    modules = (sales, pos_final, posxml, xml_tax_data)
    for module in modules:
        monkeypatch.setattr(module, "frappe", s.runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    original = parent_function()
    results = []
    for lookup in (lambda doc, item, **kwargs: original(doc, item)[1], tax.get_item_tax_rate):
        for module in modules:
            monkeypatch.setattr(module, "get_item_tax_rate", lookup)
        s.runtime.get_doc.reset_mock()
        s.runtime.get_installed_apps.reset_mock()
        try:
            if mode.endswith("items"):
                root = ET.Element("Invoice")
                operation = {"sales-items": sales.item_data, "advance-items": sales.item_data_advance_invoice,
                             "pos-items": pos_final.item_data}[mode]
                assert operation(root, doc) is root
                value = ET.tostring(root)
            elif mode == "sales-total":
                value = xml_tax_data.get_tax_total_from_items(doc)
            elif mode == "pos-total":
                value = posxml.get_tax_total_from_items(doc)
            elif mode == "nominal-rate":
                value = sales._nominal_tax_rate_without_template(doc, doc.items[0])
            elif mode == "nominal-breakdown":
                value = sales._nominal_breakdown_without_template(doc)
            else:
                value = xml_tax_data._get_item_tax_rate_without_template(doc, doc.items[0])
        except Exception as error:
            outcome = "error", type(error), str(error)
        else:
            outcome = "value", type(value), repr(value)
        results.append((outcome, s.runtime.get_doc.call_args_list[:], s.runtime.get_installed_apps.call_args_list[:]))
    assert results[0] == results[1]
    if rate == float("inf"):
        assert results[1][0][0] == "error", "Do not remove inherited Infinity rejection"
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    s.runtime.db.commit.assert_not_called()
    s.runtime.db.set_value.assert_not_called()
    if mode == "pos-items" and rate != rate:
        # Both reader variants reach the same strict POS source guard. Each
        # separately invoked operation records one English diagnostic.
        assert s.runtime.log_error.call_count == 2
        assert s.runtime.log_error.call_args_list[0] == s.runtime.log_error.call_args_list[1]
        assert s.runtime.log_error.call_args.kwargs["message"].startswith("invalid_source:")
    else:
        s.runtime.log_error.assert_not_called()
    s.runtime.msgprint.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("helper", ["nominal", "sales-fallback"])
def test_selected_zero_no_longer_falls_back_to_invoice_rate(
    advance_source, monkeypatch, major, helper,
):
    s = advance_source
    doc = prepare(s, erp_major=major)
    for item in doc.items:
        item.item_tax_rate = '{"VAT":0}'
    for row in getattr(doc, "item_wise_tax_details", []):
        row.rate = 0
    assert tax.get_item_tax_rate(doc, doc.items[0]) == 0.0
    old = parent_function()
    module = sales if helper == "nominal" else xml_tax_data
    operation = sales._nominal_tax_rate_without_template if helper == "nominal" else xml_tax_data._get_item_tax_rate_without_template
    results = []
    for lookup in (lambda doc, item, **kwargs: old(doc, item)[1], tax.get_item_tax_rate):
        monkeypatch.setattr(module, "get_item_tax_rate", lookup)
        results.append(operation(doc, doc.items[0]))
    # The native selector remains zero; both consumer bindings now preserve it.
    # Exact pre-fix consumer functions are exercised independently at208.
    assert results == [Decimal("0.00"), Decimal("0.00")]
    s.runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()
