"""Frozen old/new Sales item builders with synthetic records and no site I/O.

Regular line bytes, read order, partial errors and direct-reference handoff are
compared. None of this is installed ERPNext, fiscal/SDK or GL acceptance.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as core
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, fail


REFERENCE = Path(__file__).parent / "fixtures" / "sales_item_builders_499d56d.py"
REFERENCE_SHA256 = "048ca8ea85f9de26744d6cf0b545cc48daecae8a74c7c73de8835c18b94db5d4"
CATEGORIES = ("Standard", core.ZERO_RATED, "Exempted", core.OUTSIDE_SCOPE)


class TrackedDocument(Document):
    def get(self, key, default=None):
        self.trace.append((self.role, key))
        return super().get(key, default)


@pytest.fixture
def source(monkeypatch):
    trace = []
    def document(role, **values):
        return TrackedDocument(role=role, trace=trace, **values)
    template = document("template", custom_zatca_tax_category="Standard", taxes=[Document(tax_rate=15)])
    advance = document("advance", doctype="Sales Invoice", name="ADV-2020", is_advance_payment=1,
        posting_date="2020-01-01", posting_time="9:05:42", custom_uuid="test-advance-uuid",
        custom_zatca_tax_category="Standard")
    records = {("Item Tax Template", "ITEM-VAT"): template, ("Sales Invoice", advance.name): advance}
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]), throw=fail,
        db=SimpleNamespace(commit=Mock(), set_value=Mock()), log_error=Mock(), msgprint=Mock())
    monkeypatch.setattr(core, "frappe", runtime)
    monkeypatch.setattr(core, "_", lambda message: message)
    monkeypatch.setattr(core, "supports_advance_deduction_schema", lambda doc: True)
    # The module is frozen test data, compiled with the same explicit synthetic
    # dependencies as the current builders. No import, Git or subprocess here.
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    reference_globals = dict(vars(core))
    # Increment205 intentionally retires this unused acquisition/serialization.
    # Parent-version tests separately execute it and prove byte/error deltas.
    reference_globals["get_tax_wise_detail"] = lambda *args: None
    exec(compile(content, str(REFERENCE), "exec"), reference_globals)
    return SimpleNamespace(trace=trace, document=document, template=template, advance=advance,
                           runtime=runtime, reference=reference_globals)


def invoice(source, *, currency="SAR", erp_major=15, quantity=3, category="Standard", direct=False, company_field=True):
    rate = 15 if category == "Standard" else 0
    source.template.custom_zatca_tax_category = category
    source.template.taxes[0].tax_rate = rate
    items = []
    for index, qty, net, base_net in ((2, quantity, 1.01, 3.79), (7, 2, 2.03, 7.61)):
        items.append(source.document("item-" + str(index), name="ROW-" + str(index), idx=index,
            item_code="ITEM", item_name="Fallback item", description="<b>خدمة &amp; مقدمة</b>",
            qty=qty, uom="PCE", amount=net + .5, base_amount=base_net + .5,
            net_amount=net, base_net_amount=base_net, item_tax_template="ITEM-VAT",
            item_tax_rate=json.dumps({"VAT": rate})))
    rows = []
    if direct:
        rows = [source.document("allocation", advance_invoice=source.advance.name,
            allocated_total_amount=11.5, allocated_taxable_amount=10, allocated_tax_amount=1.5)]
    doc = source.document("invoice", doctype="Sales Invoice", name="SYNTHETIC", currency=currency,
        custom_zatca_tax_category=category, items=items, is_return=int(quantity < 0),
        taxes=[Document(name="TAX", rate=rate, account_head="VAT", item_wise_tax_detail=json.dumps({"ITEM": [rate, 99]}))],
        custom_zatca_advance_deduction_details=rows, save=Mock(), db_set=Mock())
    if company_field:
        doc.company_currency = "SAR"
    if erp_major == 16:
        doc.item_wise_tax_details = [Document(item_row=item.name, tax_row="TAX", rate=rate, amount=99) for item in items]
    return doc


def compare(source, doc, has_template, *, make_root=None):
    method = "item_data_with_template" if has_template else "item_data"
    make_root = (lambda: ET.Element("Invoice")) if make_root is None else make_root
    expected, actual = make_root(), make_root()
    source.trace.clear()
    source.runtime.get_doc.reset_mock()
    expected_result = source.reference[method](expected, doc)
    reads, master_reads = source.trace[:], source.runtime.get_doc.call_args_list[:]
    source.trace.clear()
    source.runtime.get_doc.reset_mock()
    actual_result = getattr(core, method)(actual, doc)
    assert expected_result is expected and actual_result is actual
    assert ET.tostring(actual) == ET.tostring(expected)
    assert source.trace == reads
    assert source.runtime.get_doc.call_args_list == master_reads
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    source.runtime.db.commit.assert_not_called()
    source.runtime.db.set_value.assert_not_called()
    source.runtime.log_error.assert_not_called()
    source.runtime.msgprint.assert_not_called()
    return actual


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("quantity", [0, 1, 3, -3])
@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("company_field", [False, True])
def test_item_bytes_reads_price_quantities_and_advance_handoff_match_frozen_builders(
    source, has_template, currency, erp_major, quantity, category, direct, company_field,
):
    doc = invoice(source, currency=currency, erp_major=erp_major, quantity=quantity,
                  category=category, direct=direct, company_field=company_field)
    numeric_before = [(item.qty, item.amount, item.base_amount, item.net_amount, item.base_net_amount) for item in doc.items]
    root = compare(source, doc, has_template)
    lines = root.findall("cac:InvoiceLine")
    assert [line.find("cbc:ID").text for line in lines] == (["2", "7", "8"] if direct else ["2", "7"])
    assert lines[0].find("cbc:InvoicedQuantity").text == str(abs(quantity))
    assert lines[0].find("cac:Item").find("cbc:Name").text == "خدمة & مقدمة"
    if quantity == 0:
        assert lines[0].find("cac:Price").find("cbc:PriceAmount").text == "0.00"
    if direct:
        reference = lines[-1].find("cac:DocumentReference")
        assert reference.find("cbc:ID").text == source.advance.name
        assert reference.find("cbc:IssueDate").text == "2020-01-01"
        assert reference.find("cbc:DocumentTypeCode").text == "386"
    assert numeric_before == [(item.qty, item.amount, item.base_amount, item.net_amount, item.base_net_amount) for item in doc.items]


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("field", ["net_amount", "base_net_amount"])
def test_null_net_values_retain_the_original_source_fallback(source, has_template, currency, field):
    doc = invoice(source, currency=currency)
    setattr(doc.items[0], field, None)
    compare(source, doc, has_template)


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("case", ["name", "code", "unknown-category", "empty-template-rates", "empty-items"])
def test_existing_text_category_template_and_empty_list_behavior(source, has_template, case):
    doc = invoice(source)
    if case in ("name", "code"):
        doc.items[0].description = "<p> </p>"
        if case == "code":
            doc.items[0].item_name = ""
    elif case == "unknown-category":
        doc.custom_zatca_tax_category = source.template.custom_zatca_tax_category = "UNKNOWN"
    elif case == "empty-template-rates":
        source.template.taxes = []
    else:
        doc.items = []
    compare(source, doc, has_template)


@pytest.mark.parametrize("has_template", [False, True])
def test_existing_direct_reference_is_not_duplicated_or_fetched(source, has_template):
    doc = invoice(source, direct=True)
    def existing():
        root = ET.Element("Invoice")
        line = ET.SubElement(root, "cac:InvoiceLine")
        ET.SubElement(line, "cbc:ID").text = "40"
        reference = ET.SubElement(line, "cac:DocumentReference")
        ET.SubElement(reference, "cbc:ID").text = source.advance.name
        return root
    root = compare(source, doc, has_template, make_root=existing)
    assert len(root.findall("cac:InvoiceLine")) == 3
    assert all(call.args[0] != "Sales Invoice" for call in source.runtime.get_doc.call_args_list)


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("fault", ["missing-idx", "missing-uom", "bad-qty", "missing-category", "bad-price", "template-read"])
def test_error_type_message_and_partial_xml_match_prior_builder(source, has_template, fault, monkeypatch):
    doc = invoice(source)
    if fault == "missing-idx":
        del doc.items[0].idx
    elif fault == "missing-uom":
        del doc.items[0].uom
    elif fault == "bad-qty":
        doc.items[0].qty = "invalid"
    elif fault == "missing-category":
        delattr(source.template if has_template else doc, "custom_zatca_tax_category")
    elif fault == "bad-price":
        # Pin the same dependency fault in both the frozen and current code.
        broken = Mock(side_effect=ValueError("synthetic-price-failure"))
        monkeypatch.setattr(core, "_format_price_amount", broken)
        source.reference["_format_price_amount"] = broken
    else:
        source.runtime.get_doc.side_effect = KeyError("synthetic-template-failure")
    method = "item_data_with_template" if has_template else "item_data"
    results = []
    for operation in (source.reference[method], getattr(core, method)):
        root = ET.Element("Invoice")
        source.trace.clear()
        source.runtime.get_doc.reset_mock()
        try:
            operation(root, doc)
        except Exception as error:
            outcome = type(error), str(error)
        else:
            outcome = None
        results.append((outcome, ET.tostring(root), source.trace[:], source.runtime.get_doc.call_args_list[:]))
    assert results[0] == results[1]
    if fault != "template-read" or has_template:
        assert results[0][0] is not None
    doc.save.assert_not_called()
    source.runtime.db.commit.assert_not_called()
