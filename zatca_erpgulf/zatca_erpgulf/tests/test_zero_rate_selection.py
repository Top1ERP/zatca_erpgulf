"""Explicit zero/missing sources and per-rate subtotals, with no site I/O."""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance import tax_details as tax
from zatca_erpgulf.zatca_erpgulf import advance_deduction, create_xml_final_part as sales, xml_tax_data as totals
from zatca_erpgulf.zatca_erpgulf.tests.test_sales_item_builder_parity import source as sales_source
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_item_builder_parity import advance_source, prepare

REFERENCE = Path(__file__).parent / "fixtures" / "zero_rate_consumers_cc4918b.py"
REFERENCE_SHA256 = "11ec5d35448644f86bfde04028be4547538c789d2cee28c2aed66c88e89270d7"
D = Decimal
# Independent literal totals, not expectations computed through the new buckets.
PATTERNS = [
    ([0, 0], [(0, "3.04", "0.00", "0.00")]),
    ([0, 15], [(0, "1.01", "0.00", "0.00"), (15, "2.03", "0.30", "1.14")]),
    ([15, 0], [(15, "1.01", "0.15", "0.57"), (0, "2.03", "0.00", "0.00")]),
    ([5, 15], [(5, "1.01", "0.05", "0.19"), (15, "2.03", "0.30", "1.14")]),
    ([15, 15], [(15, "3.04", "0.46", "1.71")]),
    ([5, 5], [(5, "3.04", "0.15", "0.57")]),
    ([0, 5, 15], [(0, "1.01", "0.00", "0.00"), (5, "2.03", "0.10", "0.38"), (15, "3.07", "0.46", "1.73")]),
    ([15, 5, 15], [(15, "4.08", "0.61", "2.30"), (5, "2.03", "0.10", "0.38")]),
]


def parent_namespace():
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(sales))
    namespace.update(vars(totals))
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace


def make_invoice(s, rates, major=15, currency="SAR", negative=False, category="Standard"):
    doc = prepare(s, erp_major=major, currency=currency)
    doc.items = []
    sign, fx = (-1 if negative else 1), (3.75 if currency == "USD" else 1)
    for index, rate in enumerate(rates, 1):
        net = (1.01, 2.03, 3.07)[index-1]
        doc.items.append(s.document("row-" + str(index), name="ROW-" + str(index), idx=index,
            item_code="ITEM", item_name="Synthetic item", description="<b>خدمة</b>",
            qty=sign, uom="PCE", amount=net * sign, base_amount=net * fx * sign,
            net_amount=net * sign, base_net_amount=net * fx * sign,
            item_tax_rate=json.dumps({"VAT": rate})))
    if major == 16:
        doc.item_wise_tax_details = [s.document("detail-" + str(i), item_row=item.name,
            rate=rate, amount=99) for i, (item, rate) in enumerate(zip(doc.items, rates))]
    doc.custom_zatca_tax_category = category
    doc.custom_exemption_reason_code = "VATEX-SA-32" if category != "Standard" else None
    doc.custom_exemption_reason = "Synthetic reason"
    doc.disable_rounded_total = 1
    # These fixtures deliberately keep the unrelated invoice rate at15.
    doc.taxes[0].rate = 15
    expected_rows = next((rows for pattern, rows in PATTERNS if pattern == rates), ())
    doc.base_total_taxes_and_charges = sum(
        (D(row[3] if currency == "USD" else row[2]) for row in expected_rows), D("0.00")
    )
    return doc


def no_writes(s, doc):
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    s.runtime.db.commit.assert_not_called()
    s.runtime.db.set_value.assert_not_called()
    s.runtime.log_error.assert_not_called()
    s.runtime.msgprint.assert_not_called()


@pytest.mark.parametrize("case", ["v15-missing", "v15-item-zero", "v15-invoice-zero", "v15-legacy-zero",
    "v15-positive", "v15-invalid-coercion", "v16-zero", "v16-unmatched", "v16-empty-missing",
    "v16-empty-zero", "v16-empty-later-positive", "v16-null-rate"])
@pytest.mark.parametrize("default", [None, "ABSENT", D("-7"), object()], ids=["none", "text", "decimal", "identity"])
def test_optional_missing_default_does_not_replace_selected_or_authoritative_zero(case, default):
    item = {"name": "ROW", "item_code": "ITEM"}
    doc = {"taxes": [{}]}
    expected, missing = 0.0, case in ("v15-missing", "v16-empty-missing")
    if case == "v15-item-zero":
        item["item_tax_rate"] = '{"VAT":0}'
        doc["taxes"][0]["rate"] = 15
    elif case == "v15-invoice-zero":
        doc["taxes"][0]["rate"] = 0
    elif case == "v15-legacy-zero":
        doc["taxes"][0]["item_wise_tax_detail"] = '{"ITEM":[0,0]}'
    elif case == "v15-positive":
        doc["taxes"][0]["rate"] = 15
        expected = 15.0
    elif case == "v15-invalid-coercion":
        item["item_tax_rate"] = '{"VAT":"invalid"}'
    elif case.startswith("v16"):
        doc["item_wise_tax_details"] = []
        if case in ("v16-zero", "v16-unmatched", "v16-null-rate"):
            doc["taxes"][0]["rate"] = 15
            doc["item_wise_tax_details"] = [{"item_row": "OTHER" if case == "v16-unmatched" else "ROW",
                "rate": None if case == "v16-null-rate" else 0, "amount": 0}]
        elif case == "v16-empty-zero":
            doc["taxes"][0]["rate"] = 0
        elif case == "v16-empty-later-positive":
            doc["taxes"] = [{"rate": None}, {"rate": 5}]
            expected = 5.0
    selected = tax.get_item_tax_rate(doc, item, default=default)
    if missing:
        assert selected is default
    else:
        assert type(selected) is float and selected == expected
    assert tax.get_item_tax_rate(doc, item) == tax.get_item_tax_detail(doc, item)[1] == expected


@pytest.mark.parametrize("helper", ["nominal", "ordinary"])
@pytest.mark.parametrize("selected", [None, "", 0, 0.0, D("0.00"), 5.0, "failure"])
def test_only_absent_or_failed_rate_read_uses_existing_invoice_fallback(advance_source, monkeypatch, helper, selected):
    s = advance_source
    doc = make_invoice(s, [0, 0])
    module = sales if helper == "nominal" else totals
    operation = sales._nominal_tax_rate_without_template if helper == "nominal" else totals._get_item_tax_rate_without_template
    reader = Mock(side_effect=ValueError("synthetic-rate-failure")) if selected == "failure" else Mock(return_value=selected)
    monkeypatch.setattr(module, "get_item_tax_rate", reader)
    result = operation(doc, doc.items[0])
    reader.assert_called_once_with(doc, doc.items[0], default=None)
    expected = D("15.00") if selected in (None, "", "failure") else D(str(selected)).quantize(D("0.01"))
    assert result == expected
    no_writes(s, doc)


@pytest.mark.parametrize("major,unmatched", [(15, False), (16, False), (16, True)])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("helper", ["nominal", "ordinary"])
def test_exact_prefixed_helper_loses_zero_but_fixed_helper_preserves_it(
    advance_source, major, currency, helper, unmatched,
):
    s = advance_source
    doc = make_invoice(s, [0, 0], major, currency, category="Zero Rated")
    if unmatched and major == 16:
        doc.item_wise_tax_details[0].item_row = "OTHER"
    name = "_nominal_tax_rate_without_template" if helper == "nominal" else "_get_item_tax_rate_without_template"
    original = parent_namespace()[name]
    current = getattr(sales if helper == "nominal" else totals, name)
    assert original(doc, doc.items[0]) == D("15.00")
    assert current(doc, doc.items[0]) == D("0.00")
    no_writes(s, doc)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("rates,expected", PATTERNS)
def test_literal_per_rate_buckets_keep_zero_separate_and_sum_physical_lines(
    advance_source, major, currency, negative, nominal, rates, expected,
):
    s = advance_source
    doc = make_invoice(s, rates, major, currency, negative)
    rows = sales._nominal_breakdown_without_template(doc) if nominal else totals._get_tax_breakdown_without_template(doc)
    assert [(row["tax_rate"], row["taxable_amount"], row["tax_amount"]) for row in rows] == [
        (D(str(rate)).quantize(D("0.01")), D(net), D(amount)) for rate, net, amount, _ in expected]
    if nominal:
        assert [row["sar_tax_amount"] for row in rows] == [D(sar if currency == "USD" else amount) for _, _, amount, sar in expected]
    assert all(row["zatca_tax_category"] == "Standard" and row["exemption_reason_code"] is None for row in rows)
    no_writes(s, doc)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("rates", [[], [15, 15], [5, 5]])
def test_empty_and_homogeneous_breakdowns_keep_reads_and_explicit_rounding_delta(
    advance_source, major, currency, nominal, rates,
):
    s = advance_source
    doc = make_invoice(s, rates, major, currency)
    name = "_nominal_breakdown_without_template" if nominal else "_get_tax_breakdown_without_template"
    old, current = parent_namespace()[name], getattr(sales if nominal else totals, name)
    s.trace.clear()
    expected = old(doc)
    reads = s.trace[:]
    s.trace.clear()
    actual = current(doc)
    if rates == [15, 15]:
        assert expected[0]["tax_amount"] == D("0.45")
        assert actual[0]["tax_amount"] == D("0.46")
        expected[0]["tax_amount"] = D("0.46")
        if nominal and currency == "SAR":
            assert expected[0]["sar_tax_amount"] == D("0.45")
            assert actual[0]["sar_tax_amount"] == D("0.46")
            expected[0]["sar_tax_amount"] = D("0.46")
    assert actual == expected and s.trace == reads
    no_writes(s, doc)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("rates,expected", PATTERNS)
def test_actual_tax_xml_has_one_subtotal_per_rate_and_consistent_document_totals(
    advance_source, monkeypatch, major, currency, nominal, rates, expected,
):
    s = advance_source
    doc = make_invoice(s, rates, major, currency, category="Zero Rated" if rates == [0, 0] else "Standard")
    monkeypatch.setattr(totals, "frappe", s.runtime)
    monkeypatch.setattr(totals, "_", lambda message, *args: message)
    monkeypatch.setattr(advance_deduction, "supports_advance_deduction_schema", lambda doc: False)
    root = ET.Element("Invoice")
    if not nominal:
        assert sales.item_data(root, doc) is root
    operation = sales.tax_data_nominal if nominal else totals.tax_data
    assert operation(root, doc) is root
    subtotals = [subtotal for total in root.findall("cac:TaxTotal") for subtotal in total.findall("cac:TaxSubtotal")]
    # Nominal's existing final OOS offset subtotal is retained separately.
    actual_rate_rows = subtotals[:-1] if nominal else subtotals
    assert [(node.find("cac:TaxCategory").find("cbc:Percent").text,
             node.find("cbc:TaxableAmount").text, node.find("cbc:TaxAmount").text) for node in actual_rate_rows] == [
        (format(D(str(rate)), ".2f"), net, amount) for rate, net, amount, _ in expected]
    tax_sum = sum(D(amount) for _, _, amount, _ in expected)
    net_sum = sum(D(net) for _, net, _, _ in expected)
    if not nominal:
        # The final group amount can differ from separately rounded line taxes.
        line_sum = sum(D(line.find("cac:TaxTotal").find("cbc:TaxAmount").text)
                       for line in root.findall("cac:InvoiceLine"))
        assert line_sum == (D("0.45") if rates == [15, 15] else tax_sum)
    legal = root.find("cac:LegalMonetaryTotal")
    assert D(legal.find("cbc:TaxInclusiveAmount").text) == (tax_sum if nominal else net_sum + tax_sum)
    assert D(legal.find("cbc:PayableAmount").text) == (tax_sum if nominal else net_sum + tax_sum)
    if rates == [0, 0]:
        assert all(node.find("cac:TaxCategory").find("cbc:ID").text == "Z" for node in actual_rate_rows)
    no_writes(s, doc)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("rates", [[], [15, 15], [5, 5]])
def test_empty_and_homogeneous_xml_retains_bytes_except_declared_rounding_delta(
    advance_source, monkeypatch, major, currency, nominal, rates,
):
    s = advance_source
    doc = make_invoice(s, rates, major, currency)
    monkeypatch.setattr(totals, "frappe", s.runtime)
    monkeypatch.setattr(totals, "_", lambda message, *args: message)
    monkeypatch.setattr(advance_deduction, "supports_advance_deduction_schema", lambda doc: False)
    module = sales if nominal else totals
    name = "_nominal_breakdown_without_template" if nominal else "_get_tax_breakdown_without_template"
    current = getattr(module, name)
    operation = sales.tax_data_nominal if nominal else totals.tax_data
    outputs = []
    for breakdown in (parent_namespace()[name], current):
        monkeypatch.setattr(module, name, breakdown)
        root = ET.Element("Invoice")
        assert operation(root, doc) is root
        outputs.append(ET.tostring(root))
    if rates == [15, 15]:
        assert outputs[0] != outputs[1]  # Group half-up replaces summed line rounding.
    else:
        assert outputs[0] == outputs[1]
    no_writes(s, doc)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("category", ["Standard", "Zero Rated", "Exempted", sales.OUTSIDE_SCOPE])
def test_zero_rate_does_not_infer_or_replace_declared_category_and_reason(
    advance_source, major, nominal, category,
):
    s = advance_source
    doc = make_invoice(s, [0, 0], major, category=category)
    doc.custom_exemption_reason_code = "DECLARED-REASON"
    rows = sales._nominal_breakdown_without_template(doc) if nominal else totals._get_tax_breakdown_without_template(doc)
    assert len(rows) == 1 and rows[0]["tax_rate"] == D("0.00")
    assert rows[0]["zatca_tax_category"] == category
    assert rows[0]["exemption_reason_code"] == (None if category == "Standard" else "DECLARED-REASON")
    no_writes(s, doc)
