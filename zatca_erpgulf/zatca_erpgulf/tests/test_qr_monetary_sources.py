"""Monetary QR source evidence; no tenant, actual image, signer or authority.

Frozen222 adapters retain their original source formulas. Generated financial
XML is unsigned and mocked keys are not certificate/signature acceptance.
"""
import base64
import copy
from decimal import Decimal
import hashlib
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from zatca_erpgulf.ksa_compliance.qr_amounts import (
    CAC, CBC, QRAmountError, REVIEW, phase1_document_amounts, phase2_xml_amounts,
)
from zatca_erpgulf.zatca_erpgulf import (
    advance_deduction, create_qr, sign_invoice, sign_invoice_first as phase2,
    posxml, pos_final, createxml, create_xml_final_part as sales, xml_tax_data,
)
from zatca_erpgulf.zatca_erpgulf.qr_encoding import encode_qr_payload
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import fixture_data, input_snapshot, render
from zatca_erpgulf.zatca_erpgulf.tests.test_declared_vat_xml import setup
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr, xml_qr, qr_tags, tlv_values
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, ValidationError

PARENT = Path(__file__).with_name("fixtures") / "qr_amount_adapters_82c19b6.py"
PARENT_SHA = "876daaa1b6d6b402431da3e575cc7e8e8be5f486217c97a5a4a0f9130dd41335"


def previous(module, name):
    raw = PARENT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PARENT_SHA
    namespace = dict(vars(module))
    exec(compile(raw, str(PARENT), "exec"), namespace)
    return namespace[name]


def set_currency(root, code):
    root.find(CBC + "DocumentCurrencyCode").text = code
    root.find(CAC + "LegalMonetaryTotal").find(CBC + "PayableAmount").set("currencyID", code)
    next(node for node in root.findall(CAC + "TaxTotal") if node.find(CAC + "TaxSubtotal") is not None).find(CBC + "TaxAmount").set("currencyID", code)


@pytest.mark.parametrize("currency", ["SAR", "USD", "EUR"])
@pytest.mark.parametrize("representation", [int, float, Decimal, str])
@pytest.mark.parametrize("returned", [False, True])
def test_phase1_reads_one_document_currency_pair_without_base_or_adjustment_math(currency, representation, returned):
    sign = -1 if returned else 1
    doc = Document(currency=currency, grand_total=representation(115 * sign),
        total_taxes_and_charges=representation(15 * sign), is_return=int(returned),
        base_grand_total="NOT A QR SOURCE", base_total_taxes_and_charges="NOT A QR SOURCE",
        rounded_total="NOT A QR SOURCE", paid_amount=115, outstanding_amount=0,
        custom_zatca_advance_deducted_taxable_amount=100)
    before = input_snapshot(doc)
    result = phase1_document_amounts(doc)
    assert (result.currency, result.invoice_total, result.vat_total) == (currency, "115.00", "15.00")
    assert input_snapshot(doc) == before


@pytest.mark.parametrize("field", ["grand_total", "total_taxes_and_charges"])
@pytest.mark.parametrize("bad", [None, "", True, "PRIVATE-INVALID", "NaN", "Infinity", "1E+4", "1,000.00", "1.001", -1])
def test_phase1_invalid_money_is_not_replaced_by_zero_base_or_another_field(field, bad):
    doc = Document(currency="SAR", grand_total=115, total_taxes_and_charges=15,
                   base_grand_total=115, base_total_taxes_and_charges=15)
    setattr(doc, field, bad)
    with pytest.raises(QRAmountError) as caught: phase1_document_amounts(doc)
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("discount", [False, True])
def test_frozen_phase1_source_deltas_and_artifact_boundaries(local_qr, route, currency, returned, discount):
    doc, app, payloads, saver = local_qr
    sign, fx = (-1 if returned else 1), (1 if currency == "SAR" else Decimal("3.75"))
    doc.currency, doc.is_return = currency, int(returned)
    doc.total, doc.net_total = 100 * sign, (80 if discount else 100) * sign
    doc.discount_amount = 20 if discount else 0
    doc.total_taxes_and_charges = (12 if discount else 15) * sign
    doc.grand_total = doc.net_total + doc.total_taxes_and_charges
    doc.base_grand_total = doc.grand_total * fx
    doc.base_total, doc.base_net_total = doc.total * fx, doc.net_total * fx
    doc.base_total_taxes_and_charges = doc.total_taxes_and_charges * fx
    doc.conversion_rate, doc.custom_zatca_advance_deducted_taxable_amount = fx, 20
    doc.doctype = "POS Invoice" if route == "pos" else "Sales Invoice"
    module = advance_deduction if route == "advance" else create_qr
    method = "ensure_final_sales_invoice_qr_for_print" if route == "advance" else "create_qr_code"
    results = []
    before = (doc.grand_total, doc.total_taxes_and_charges, doc.base_grand_total)
    for operation in (previous(module, method), getattr(module, method)):
        doc.ksa_einv_qr, doc.custom_zatca_status = None, "Not Submitted"
        payloads.clear()
        operation(doc)
        results.append(tlv_values(payloads[0]))
        assert before == (doc.grand_total, doc.total_taxes_and_charges, doc.base_grand_total)
    assert {key: results[0][key] for key in (1, 2, 3)} == {key: results[1][key] for key in (1, 2, 3)}
    assert results[1][4] == ("92.00" if discount else "115.00")
    assert results[1][5] == ("12.00" if discount else "15.00")
    if route == "advance":
        expected_old = doc.net_total - 20 + doc.total_taxes_and_charges
        if currency != "SAR": expected_old *= fx
        # The parent deliberately used flt/native rounding. Literal normal
        # examples below independently expose its prepayment and FX error.
        assert Decimal(results[0][4]) == Decimal(str(expected_old)).quantize(Decimal(".01"))
    else:
        assert Decimal(results[0][4]) == doc.base_grand_total
    app.db.commit.assert_not_called()
    app.delete_doc.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


def test_literal_old_advance_and_foreign_ordinary_values_are_reviewable(local_qr):
    doc, app, payloads, _ = local_qr
    doc.currency, doc.conversion_rate = "USD", Decimal("3.75")
    doc.total = doc.net_total = Decimal(100)
    doc.total_taxes_and_charges, doc.grand_total = Decimal(15), Decimal(115)
    doc.base_total = doc.base_net_total = Decimal(375)
    doc.base_total_taxes_and_charges, doc.base_grand_total = Decimal("56.25"), Decimal("431.25")
    doc.custom_zatca_advance_deducted_taxable_amount = 20
    previous(create_qr, "create_qr_code")(doc)
    assert tlv_values(payloads[-1])[4] == "431.25"
    doc.ksa_einv_qr = None
    previous(advance_deduction, "ensure_final_sales_invoice_qr_for_print")(doc)
    assert tlv_values(payloads[-1])[4] == "356.25"
    doc.ksa_einv_qr = None
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc)
    assert (tlv_values(payloads[-1])[4], tlv_values(payloads[-1])[5]) == ("115.00", "15.00")


@pytest.mark.parametrize("currency", ["SAR", "USD", "EUR"])
@pytest.mark.parametrize("summary_first", [False, True])
@pytest.mark.parametrize("payable", ["0.00", "80.25", "115.00"])
def test_phase2_uses_payable_and_document_vat_before_prepayment_regardless_of_order(xml_qr, currency, summary_first, payable):
    set_currency(xml_qr, currency)
    xml_qr.find(CAC + "LegalMonetaryTotal").find(CBC + "PayableAmount").text = payable
    extra = etree.Element(CAC + "TaxTotal")
    etree.SubElement(extra, CBC + "TaxAmount", currencyID="SAR").text = "56.25"
    if summary_first: xml_qr.insert(0, extra)
    else: xml_qr.append(extra)
    before = etree.tostring(xml_qr)
    values = qr_tags(xml_qr)
    assert (values[4], values[5]) == (payable, "1.50")
    assert etree.tostring(xml_qr) == before


def test_frozen_phase2_first_tax_error_does_not_change_payable_mapping(xml_qr):
    set_currency(xml_qr, "USD")
    xml_qr.find(CAC + "LegalMonetaryTotal").find(CBC + "PayableAmount").text = "80.25"
    tax = etree.Element(CAC + "TaxTotal")
    etree.SubElement(tax, CBC + "TaxAmount", currencyID="SAR").text = "56.25"
    xml_qr.insert(0, tax)
    text = etree.tostring(xml_qr).decode()
    source = Document(doctype="Sales Invoice")
    old = previous(phase2, "generate_tlv_xml")(text, "TEST", source)
    new = phase2.generate_tlv_xml(text, "TEST", source)
    assert old[4] == new[4] == "80.25"
    assert old[5] == "56.25" and new[5] == "1.50"
    for tag in (1, 2, 3, 6, 7, 8): assert old[tag] == new[tag]


FAULTS = ["currency-missing", "currency-duplicate", "currency-invalid", "legal-duplicate",
    "payable-missing", "payable-duplicate", "payable-empty", "payable-child", "payable-currency",
    "payable-negative", "payable-nan", "payable-precision", "payable-exponent",
    "vat-missing", "vat-duplicate", "vat-empty", "vat-child", "vat-currency", "vat-negative",
    "tax-missing", "tax-duplicate", "tax-no-subtotal"]


@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("language", ["en", "ar"])
def test_phase2_ambiguous_or_invalid_money_fails_once_before_key_access(xml_qr, monkeypatch, fault, language):
    legal = xml_qr.find(CAC + "LegalMonetaryTotal")
    payable = legal.find(CBC + "PayableAmount")
    tax = xml_qr.find(CAC + "TaxTotal")
    vat = tax.find(CBC + "TaxAmount")
    code = xml_qr.find(CBC + "DocumentCurrencyCode")
    if fault == "currency-missing": xml_qr.remove(code)
    elif fault == "currency-duplicate": xml_qr.append(copy.deepcopy(code))
    elif fault == "currency-invalid": code.text = "PRIVATE-CURRENCY"
    elif fault == "legal-duplicate": xml_qr.append(copy.deepcopy(legal))
    elif fault == "payable-missing": legal.remove(payable)
    elif fault == "payable-duplicate": legal.append(copy.deepcopy(payable))
    elif fault == "payable-empty": payable.text = " "
    elif fault == "payable-child": etree.SubElement(payable, CBC + "ID").text = "PRIVATE-CHILD"
    elif fault == "payable-currency": payable.set("currencyID", "USD")
    elif fault == "payable-negative": payable.text = "-1"
    elif fault == "payable-nan": payable.text = "NaN"
    elif fault == "payable-precision": payable.text = "1.001"
    elif fault == "payable-exponent": payable.text = "1E+2"
    elif fault == "vat-missing": tax.remove(vat)
    elif fault == "vat-duplicate": tax.append(copy.deepcopy(vat))
    elif fault == "vat-empty": vat.text = None
    elif fault == "vat-child": etree.SubElement(vat, CBC + "ID")
    elif fault == "vat-currency": vat.set("currencyID", "USD")
    elif fault == "vat-negative": vat.text = "-1"
    elif fault == "tax-missing": xml_qr.remove(tax)
    elif fault == "tax-duplicate": xml_qr.append(copy.deepcopy(tax))
    else: tax.remove(tax.find(CAC + "TaxSubtotal"))
    app = phase2.frappe
    app.throw = Mock(side_effect=app.throw)
    monkeypatch.setattr(phase2, "_", lambda text: "AR:" + text if language == "ar" else text)
    before = etree.tostring(xml_qr)
    with pytest.raises(ValidationError) as caught: qr_tags(xml_qr)
    assert str(caught.value) == ("AR:" if language == "ar" else "") + REVIEW
    assert "PRIVATE" not in str(caught.value)
    app.throw.assert_called_once()
    app.log_error.assert_called_once()
    assert "PRIVATE" not in app.log_error.call_args.kwargs["message"]
    phase2.tag8_publickey.assert_not_called()
    phase2.tag9_signature_ecdsa.assert_not_called()
    assert etree.tostring(xml_qr) == before


@pytest.mark.parametrize("xml", ["<Invoice>", '<!DOCTYPE Invoice [<!ENTITY probe "PRIVATE-ENTITY">]><Invoice/>',
    '<!DOCTYPE Invoice SYSTEM "https://example.invalid/PRIVATE-DTD"><Invoice/>'])
def test_bad_xml_and_doctype_are_not_resolved_or_logged_with_input(xml_qr, xml):
    app = phase2.frappe
    app.throw = Mock(side_effect=app.throw)
    with pytest.raises(ValidationError, match=REVIEW):
        phase2.generate_tlv_xml(xml, "TEST", Document())
    app.throw.assert_called_once()
    assert "PRIVATE" not in app.log_error.call_args.kwargs["message"]
    phase2.tag8_publickey.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("family", ["sales", "nominal", "pos"])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("template", [False, True])
@pytest.mark.parametrize("returned", [False, True])
def test_actual_financial_builders_supply_qr_monetary_pair_without_sar_mixing(
    xml_qr, monkeypatch, major, family, currency, template, returned,
):
    doc, records, _ = fixture_data("item-template-mixed-rates" if template else "invoice-template-15", major, currency, True)
    doc.custom_zatca_nominal_invoice = int(family == "nominal")
    if family == "pos": doc.doctype = "POS Invoice"
    if returned:
        doc.is_return = 1
        for item in doc.items:
            for field in ("qty", "net_amount", "base_net_amount"):
                setattr(item, field, -getattr(item, field))
        for field in ("net_total", "base_net_total", "grand_total", "rounded_total", "total_taxes_and_charges", "base_total_taxes_and_charges"):
            setattr(doc, field, -getattr(doc, field))
    setup(monkeypatch, records)
    financial = render(doc, template, family, dict(discount=vars(posxml if family == "pos" else createxml),
        tax=vars(pos_final if family == "pos" and template else posxml if family == "pos" else sales if family == "nominal" else xml_tax_data),
        items=vars(pos_final if family == "pos" else sales)))
    for node in list(xml_qr):
        if node.tag in (CAC + "TaxTotal", CAC + "LegalMonetaryTotal"): xml_qr.remove(node)
    xml_qr.find(CBC + "DocumentCurrencyCode").text = currency
    for node in etree.fromstring(ET.tostring(financial)):
        if node.tag in (CAC + "TaxTotal", CAC + "LegalMonetaryTotal"): xml_qr.append(copy.deepcopy(node))
    before = etree.tostring(xml_qr)
    values = qr_tags(xml_qr)
    expected_vat = abs(Decimal(str(doc.total_taxes_and_charges)))
    assert Decimal(values[5]) == expected_vat
    assert Decimal(values[4]) == (expected_vat if family == "nominal" else abs(Decimal(str(doc.grand_total))))
    # Run the real encoder as well; this does not validate the mocked keys or
    # missing signature nodes. Decode the existing TLV wire format, not an image.
    payload = base64.b64decode(encode_qr_payload(values, phase2.get_tlv_for_value))
    decoded, offset = {}, 0
    while offset < len(payload):
        tag, size = payload[offset:offset+2]
        decoded[tag] = payload[offset+2:offset+2+size]
        offset += 2 + size
    assert decoded[4].decode() == values[4] and decoded[5].decode() == values[5]
    assert etree.tostring(xml_qr) == before


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("language", ["en", "ar"])
@pytest.mark.parametrize("fault", ["missing-total", "negative", "precision", "currency", "boolean-tax"])
def test_phase1_source_failure_is_translated_once_before_image_or_file_creation(local_qr, monkeypatch, route, language, fault):
    import csv
    doc, app, payloads, saver = local_qr
    if fault == "missing-total": doc.grand_total = None
    elif fault == "negative": doc.grand_total = -115
    elif fault == "precision": doc.grand_total = "115.001"
    elif fault == "currency": doc.currency = "PRIVATE-CURRENCY"
    else: doc.total_taxes_and_charges = True
    catalog = dict(csv.reader((Path(__file__).parents[2] / "translations/ar.csv").open()))
    translate = lambda text: catalog.get(text, text) if language == "ar" else text
    for module in (create_qr, advance_deduction): monkeypatch.setattr(module, "_", translate)
    app.throw = Mock(side_effect=app.throw)
    doc.doctype = "POS Invoice" if route == "pos" else "Sales Invoice"
    operation = advance_deduction.ensure_final_sales_invoice_qr_for_print if route == "advance" else create_qr.create_qr_code
    with pytest.raises(ValidationError) as caught: operation(doc)
    assert str(caught.value) == translate(REVIEW)
    app.throw.assert_called_once()
    app.log_error.assert_called_once()
    assert "PRIVATE" not in app.log_error.call_args.kwargs["message"]
    assert not payloads and doc.ksa_einv_qr is None
    saver.assert_not_called()
    app.db.set_value.assert_not_called()
    app.db.commit.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
def test_owned_existing_qr_is_not_revalidated_or_rewritten_from_new_money_policy(local_qr, route):
    from zatca_erpgulf.zatca_erpgulf.tests.test_qr_attachment_policy import row
    doc, app, payloads, saver = local_qr
    doc.doctype = "POS Invoice" if route == "pos" else "Sales Invoice"
    doc.ksa_einv_qr, doc.custom_zatca_status = "/files/OLD.png", "Phase-1 QR Generated"
    app.get_all.return_value = [row(doctype=doc.doctype)]
    doc.currency, doc.grand_total, doc.posting_time = "PRIVATE-INVALID", None, None
    operation = advance_deduction.ensure_final_sales_invoice_qr_for_print if route == "advance" else create_qr.create_qr_code
    operation(doc)
    assert doc.ksa_einv_qr == "/files/OLD.png" and not payloads
    app.log_error.assert_not_called()
    app.db.set_value.assert_not_called()
    app.delete_doc.assert_not_called()
    saver.assert_not_called()
