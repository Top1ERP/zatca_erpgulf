"""Pure wire boundaries and real mocked adapters, never tenant or authority I/O.

Amount checks characterize the existing ordinary/advance formulas and formatting;
they are not tax/accounting acceptance or a change to those formulas.
"""

import base64
import csv
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_deduction, create_qr, qr_encoding, signed_xml_pipeline
from zatca_erpgulf.zatca_erpgulf.qr_encoding import (
    PHASE1_QR_VALUE_ERROR, Phase1QREncodingError, encode_phase1_qr,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr, tlv_values
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError


FIELDS = ("seller_name", "vat_number", "timestamp", "invoice_total", "vat_total")


def values():
    return dict(zip(FIELDS, ("A", "B", "C", "D", "E")))


def test_known_wire_bytes_and_empty_fields_are_not_invented_or_reformatted():
    assert encode_phase1_qr(**values()) == "AQFBAgFCAwFDBAFEBQFF"
    assert base64.b64decode(encode_phase1_qr(**dict.fromkeys(FIELDS, ""))) == bytes.fromhex("01000200030004000500")


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("text,length", [
    pytest.param("", 0, id="empty"),
    pytest.param("x" * 255, 255, id="ascii255"),
    pytest.param("ع" * 127 + "x", 255, id="arabic255"),
    pytest.param("😀" * 63 + "abc", 255, id="emoji255"),
])
def test_each_field_counts_utf8_bytes_and_keeps_exact_content(field, text, length):
    inputs = values()
    inputs[field] = text
    payload = encode_phase1_qr(**inputs)
    decoded = tlv_values(payload)
    assert list(decoded) == [1, 2, 3, 4, 5]
    assert decoded[FIELDS.index(field) + 1] == text
    raw = base64.b64decode(payload)
    position = sum(2 + len(inputs[name].encode()) for name in FIELDS[:FIELDS.index(field)])
    assert raw[position:position + 2] == bytes([FIELDS.index(field) + 1, length])
    assert raw[position + 2:position + 2 + length] == text.encode()


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("text", [
    pytest.param("x" * 256, id="ascii256"),
    pytest.param("ع" * 128, id="arabic256"),
    pytest.param("😀" * 64, id="emoji256"),
    pytest.param("private-marker\ud800", id="surrogate"),
    pytest.param(None, id="none"),
    pytest.param(0, id="integer"),
    pytest.param(False, id="boolean"),
    pytest.param(b"private-marker", id="bytes"),
])
def test_rejected_fields_have_only_english_code_and_tag_without_exception_context(field, text):
    inputs = values()
    inputs[field] = text
    with pytest.raises(Phase1QREncodingError) as raised:
        encode_phase1_qr(**inputs)
    assert raised.value.code == "phase1_qr_encoding"
    assert raised.value.args == ("phase1_qr_encoding",)
    assert raised.value.tag == FIELDS.index(field) + 1
    assert raised.value.__context__ is None
    assert "private-marker" not in str(raised.value)


def test_length_bound_is_per_field_and_never_applied_to_the_whole_payload():
    payload = encode_phase1_qr(**dict.fromkeys(FIELDS, "x" * 255))
    assert len(base64.b64decode(payload)) == 5 * (2 + 255)
    assert list(tlv_values(payload).values()) == ["x" * 255] * 5


@pytest.mark.parametrize("field", FIELDS)
def test_obviously_oversized_text_is_not_encoded_first(field):
    class MustNotEncode(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("Oversized input must not allocate an encoded copy")

    inputs = values()
    inputs[field] = MustNotEncode("x" * 256)
    with pytest.raises(Phase1QREncodingError) as raised:
        encode_phase1_qr(**inputs)
    assert raised.value.tag == FIELDS.index(field) + 1


def test_wire_encoder_preserves_numeric_strings_whitespace_and_scales():
    payload = encode_phase1_qr(seller_name="  شركة  ", vat_number=" 0123 ", timestamp=" unchanged ",
                               invoice_total="-0.000", vat_total="1.2300")
    assert list(tlv_values(payload).values()) == ["  شركة  ", " 0123 ", " unchanged ", "-0.000", "1.2300"]


def run_route(doc, route):
    if route == "advance":
        advance_deduction.ensure_final_sales_invoice_qr_for_print(doc)
    else:
        doc.doctype = "POS Invoice" if route == "pos" else "Sales Invoice"
        create_qr.create_qr_code(doc)


def previous_phase1_payload(seller, vat, timestamp, invoice_total, vat_total):
    """Freeze former ordinary hex assembly; VAT in parity fixtures is ASCII."""
    chunks = []
    for tag, text in enumerate((seller, vat, timestamp, invoice_total, vat_total), 1):
        length = len(text) if tag == 2 else len(text.encode())
        chunks.append(bytes([tag]).hex() + bytes([length]).hex() + text.encode().hex())
    return base64.b64encode(bytes.fromhex("".join(chunks))).decode()


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("discount", [False, True])
@pytest.mark.parametrize("negative", [False, True])
def test_adapter_wire_parity_preserves_existing_fx_discount_sign_and_formatting(
    local_qr, route, foreign, discount, negative,
):
    doc, runtime, payloads, saver = local_qr
    sign = -1 if negative else 1
    doc.is_return = int(negative)
    doc.discount_amount = 2 if discount else 0
    doc.total, doc.net_total = 10 * sign, 8 * sign
    doc.total_taxes_and_charges = 1.5 * sign
    if foreign:
        doc.currency, doc.conversion_rate = "USD", 3.75
        doc.base_total, doc.base_net_total, doc.base_total_taxes_and_charges = 37.5 * sign, 30 * sign, 5.625 * sign
    else:
        doc.base_total, doc.base_net_total, doc.base_total_taxes_and_charges = doc.total, doc.net_total, doc.total_taxes_and_charges
    doc.base_grand_total = ((34.5 if discount else 43.125) if foreign else (9.2 if discount else 11.5)) * sign
    before = (doc.total, doc.net_total, doc.base_total, doc.base_net_total, doc.base_grand_total,
              doc.total_taxes_and_charges, doc.base_total_taxes_and_charges, doc.conversion_rate,
              doc.custom_zatca_advance_deducted_taxable_amount)
    run_route(doc, route)
    assert len(payloads) == 1
    if route == "advance":
        totals = {
            (False, False, False): "9.50", (False, True, False): "7.50",
            (False, False, True): "-13.50", (False, True, True): "-11.50",
            (True, False, False): "35.62", (True, True, False): "28.12",
            (True, False, True): "-50.62", (True, True, True): "-43.12",
        }
        total = totals[foreign, discount, negative]
        tax = ("-5.62" if negative else "5.62") if foreign else ("-1.50" if negative else "1.50")
        saver.assert_called_once()
    else:
        total, tax = str(doc.base_grand_total), str(doc.total_taxes_and_charges)
        saver.assert_not_called()
    expected = previous_phase1_payload("شركة اختبار", "300000000000003", "2026-09-27T06:05:42Z", total, tax)
    assert payloads == [expected]
    assert before == (doc.total, doc.net_total, doc.base_total, doc.base_net_total, doc.base_grand_total,
                      doc.total_taxes_and_charges, doc.base_total_taxes_and_charges, doc.conversion_rate,
                      doc.custom_zatca_advance_deducted_taxable_amount)
    runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("language", ["en", "ar"])
@pytest.mark.parametrize("field,tag", [("seller", 1), ("vat", 2)])
@pytest.mark.parametrize("bad_value", [pytest.param("x" * 256, id="ascii256"),
                                       pytest.param("ع" * 128, id="arabic256"),
                                       pytest.param("private-marker\ud800", id="surrogate")])
def test_adapters_show_one_localized_error_before_image_or_file_writes(
    local_qr, monkeypatch, route, language, field, tag, bad_value,
):
    doc, runtime, payloads, saver = local_qr
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open(newline="") as stream:
        catalog = dict(csv.reader(stream))
    translate = lambda message: catalog.get(message, message) if language == "ar" else message
    for module in (create_qr, advance_deduction):
        monkeypatch.setattr(module, "_", translate)
    company = runtime.get_cached_doc("Company", doc.company)
    if field == "seller":
        company.company_name_in_arabic = bad_value
    else:
        company.tax_id = bad_value
        runtime.db.get_value.return_value = bad_value
    original = runtime.throw
    runtime.throw = Mock(side_effect=original)
    with pytest.raises(ValidationError) as raised:
        run_route(doc, route)
    expected = translate(PHASE1_QR_VALUE_ERROR).format(tag)
    assert str(raised.value) == expected
    assert (expected != PHASE1_QR_VALUE_ERROR.format(tag)) == (language == "ar")
    assert "private-marker" not in str(raised.value)
    assert raised.value.__context__ is None
    runtime.throw.assert_called_once_with(expected)
    assert not payloads and doc.ksa_einv_qr is None
    saver.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.delete_doc.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    doc.notify_update.assert_not_called()


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
def test_non_ascii_vat_text_is_serialized_with_its_byte_length_without_claiming_valid_tax_id(local_qr, route):
    doc, runtime, payloads, _ = local_qr
    company = runtime.get_cached_doc("Company", doc.company)
    company.tax_id = "٣٠٠"
    runtime.db.get_value.return_value = company.tax_id
    run_route(doc, route)
    assert tlv_values(payloads[0])[2] == "٣٠٠"
    # UTF-8 is two bytes per digit here; the previous ordinary path wrote 3.
    raw = base64.b64decode(payloads[0])
    seller_size = raw[1]
    assert raw[2 + seller_size:4 + seller_size] == bytes([2, 6])


def test_phase2_compatibility_import_is_the_same_shared_wire_encoder():
    assert signed_xml_pipeline.encode_qr_payload is qr_encoding.encode_qr_payload


def test_encoding_layer_has_no_framework_signing_image_or_file_dependency():
    import ast
    tree = ast.parse(Path(qr_encoding.__file__).read_text())
    imports = [node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)]
    assert imports == ["base64"]
    assert not any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree))
