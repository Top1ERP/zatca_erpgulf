"""Synthetic original-XML observations and legacy gaps; no tenant or authority."""

from dataclasses import FrozenInstanceError
import hashlib
from datetime import timedelta
from unittest.mock import Mock

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import advance_reference as reference
from zatca_erpgulf.zatca_erpgulf import create_xml_final_part as legacy
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import MAX_XML_BYTES, NS


INVOICE_ID = "ADV-SYNTHETIC-001"
UUID = "abcdef12-1234-4123-8123-123456789abc"
SELLER = "300000000000003"


def sample(*, day="2026-09-27", clock="09:05:42Z", invoice_id=INVOICE_ID, uuid=UUID, seller=SELLER, code="386"):
    root = etree.Element("{" + NS["ubl"] + "}Invoice", nsmap={None: NS["ubl"], "cbc": NS["cbc"], "cac": NS["cac"]})
    for name, text in (("ID", invoice_id), ("UUID", uuid), ("IssueDate", day), ("IssueTime", clock), ("InvoiceTypeCode", code)):
        etree.SubElement(root, "{" + NS["cbc"] + "}" + name).text = text
    supplier = etree.SubElement(root, "{" + NS["cac"] + "}AccountingSupplierParty")
    party = etree.SubElement(supplier, "{" + NS["cac"] + "}Party")
    tax = etree.SubElement(party, "{" + NS["cac"] + "}PartyTaxScheme")
    etree.SubElement(tax, "{" + NS["cbc"] + "}CompanyID").text = seller
    scheme = etree.SubElement(tax, "{" + NS["cac"] + "}TaxScheme")
    etree.SubElement(scheme, "{" + NS["cbc"] + "}ID").text = "VAT"
    return root


def xml(root=None, *, encoding="UTF-8"):
    return etree.tostring(sample() if root is None else root, encoding=encoding, xml_declaration=True)


def inspect(content, **expected):
    return reference.inspect_advance_reference(content, expected_invoice_id=expected.get("invoice_id", INVOICE_ID),
        expected_uuid=expected.get("uuid", UUID), expected_seller_tax_id=expected.get("seller", SELLER))


@pytest.mark.parametrize("clock", ["00:00:00", "09:05:42", "09:05:42Z", "09:05:42+03:00", "00:01:02-02:00", "23:59:59.123456Z", "00:00:00+14:00", "00:00:00-14:00", "09:05:42-00:00"])
@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16"])
def test_preserves_original_clock_without_utc_or_current_settings_reinterpretation(clock, encoding):
    content = xml(sample(clock=clock), encoding=encoding)
    value = inspect(content)
    assert (value.issue_date, value.issue_time) == ("2026-09-27", clock)
    assert (value.invoice_id, value.uuid, value.seller_tax_id, value.document_type_code) == (INVOICE_ID, UUID, SELLER, "386")
    assert value.file_sha256 == hashlib.sha256(content).hexdigest() and value.byte_length == len(content)
    assert content == xml(sample(clock=clock), encoding=encoding)


def test_uuid_case_comparison_preserves_original_text_and_frozen_private_repr():
    value = inspect(xml(sample(uuid=UUID.upper())))
    assert value.uuid == UUID.upper()
    assert INVOICE_ID not in repr(value) and UUID.upper() not in repr(value) and SELLER not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.issue_time = "00:00:00"


@pytest.mark.parametrize("field,value,code", [
    ("invoice_id", "OTHER", "reference_invoice_id_mismatch"),
    ("uuid", "00000000-0000-0000-0000-000000000000", "reference_uuid_mismatch"),
    ("seller", "300000000000013", "reference_seller_tax_id_mismatch"),
    ("code", "388", "reference_type"), ("code", "381", "reference_type"), ("code", "383", "reference_type"),
])
def test_identity_or_not_advance_mismatch_is_static(field, value, code):
    with pytest.raises(reference.AdvanceReferenceError) as error:
        inspect(xml(sample(**{field: value})))
    assert str(error.value) == code and error.value.__context__ is None


@pytest.mark.parametrize("field", ["ID", "UUID", "IssueDate", "IssueTime", "InvoiceTypeCode"])
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "nested", "blank", "whitespace", "unqualified", "only_nested"])
def test_ambiguous_or_non_root_metadata_is_rejected(field, mutation):
    root = sample()
    node = root.find("cbc:" + field, NS)
    if mutation in ("missing", "only_nested"):
        root.remove(node)
        if mutation == "only_nested":
            etree.SubElement(root, "{" + NS["cac"] + "}DocumentReference").append(node)
    elif mutation == "duplicate":
        etree.SubElement(root, node.tag).text = node.text
    elif mutation == "nested":
        etree.SubElement(node, "extra").text = "PRIVATE-RAW"
    elif mutation == "blank":
        node.text = ""
    elif mutation == "whitespace":
        node.text = " " + node.text
    else:
        node.tag = field
    with pytest.raises(reference.AdvanceReferenceError) as error:
        inspect(xml(root))
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("clock", ["9:05:42", "09:05", "24:00:00", "23:60:00", "23:59:60", "09:05:42z", "09:05:42.1234567Z", "09:05:42,123Z", "09:05:42+14:01", "09:05:42-15:00", "09:05:42+03:60", "09:05:42+0300", "PRIVATE-RAW-TIME"])
def test_invalid_or_unsupported_clock_never_becomes_midnight(clock):
    with pytest.raises(reference.AdvanceReferenceError) as error:
        inspect(xml(sample(clock=clock)))
    assert str(error.value) == "reference_clock" and error.value.__context__ is None


@pytest.mark.parametrize("day", ["2026-02-29", "2026-13-01", "20260927", "2026-W39-7", "PRIVATE-DATE"])
def test_invalid_calendar_never_gets_today(day):
    with pytest.raises(reference.AdvanceReferenceError) as error:
        inspect(xml(sample(day=day)))
    assert str(error.value) == "reference_clock" and error.value.__context__ is None


@pytest.mark.parametrize("field,bad_values", [("invoice_id", [None, False, "", " X ", "X\nY", "x" * 141]),
    ("uuid", [None, False, "", "PRIVATE-UUID", UUID.replace("-", ""), " " + UUID]),
    ("seller", [None, False, 300000000000003, "PRIVATE-TAX", "٣" * 15, "3" * 16])])
def test_explicit_expected_identity_required_before_xml_parse(monkeypatch, field, bad_values):
    parser = Mock(side_effect=AssertionError("No parse before explicit expected identity"))
    monkeypatch.setattr(reference, "parse_diagnostic_xml", parser)
    for value in bad_values:
        with pytest.raises(reference.AdvanceReferenceError) as error:
            inspect(b"PRIVATE-XML", **{field: value})
        assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    parser.assert_not_called()


@pytest.mark.parametrize("mutation", ["supplier_duplicate", "party_duplicate", "vat_duplicate", "company_duplicate", "scheme_duplicate", "tax_id_duplicate", "nested_seller", "nonvat", "blank"])
def test_supplier_vat_metadata_cannot_select_arbitrary_first_match(mutation):
    root = sample()
    supplier = root.find("cac:AccountingSupplierParty", NS)
    party = supplier.find("cac:Party", NS)
    tax = party.find("cac:PartyTaxScheme", NS)
    scheme = tax.find("cac:TaxScheme", NS)
    if mutation == "supplier_duplicate":
        etree.SubElement(root, supplier.tag)
    elif mutation == "party_duplicate":
        etree.SubElement(supplier, party.tag)
    elif mutation == "vat_duplicate":
        duplicate = etree.fromstring(etree.tostring(tax))
        party.append(duplicate)
    elif mutation == "company_duplicate":
        etree.SubElement(tax, "{" + NS["cbc"] + "}CompanyID").text = SELLER
    elif mutation == "scheme_duplicate":
        tax.append(etree.fromstring(etree.tostring(scheme)))
    elif mutation == "tax_id_duplicate":
        etree.SubElement(scheme, "{" + NS["cbc"] + "}ID").text = "VAT"
    elif mutation == "nested_seller":
        party.remove(tax)
        etree.SubElement(party, "extra").append(tax)
    elif mutation == "nonvat":
        scheme[0].text = "OTHER"
    else:
        tax[0].text = ""
    with pytest.raises(reference.AdvanceReferenceError) as error:
        inspect(xml(root))
    assert str(error.value) == "reference_seller_tax_id"


@pytest.mark.parametrize("content,code", [("<Invoice/>", "xml_bytes_required"), (b"", "xml_size"),
    (b"x" * (MAX_XML_BYTES + 1), "xml_size"), (b"<Invoice>PRIVATE-XML", "xml_syntax"),
    (b"<Invoice/>", "xml_root"),
    (b'<!DOCTYPE Invoice [<!ENTITY private SYSTEM "file:///tmp/never-read">]><Invoice>&private;</Invoice>', "xml_doctype")])
def test_bounded_shared_parser_static_errors_no_resolution(content, code):
    with pytest.raises(reference.AdvanceReferenceError) as error:
        inspect(content)
    assert str(error.value) == code and error.value.__context__ is None


def test_no_erp_clock_or_current_timezone_dependency(monkeypatch):
    import frappe
    forbidden = Mock(side_effect=AssertionError("No site/clock/persistence dependency"))
    for name in ("get_doc", "get_cached_doc", "get_system_settings", "init", "connect"):
        monkeypatch.setattr(frappe, name, forbidden)
    value = inspect(xml(sample(clock="00:05:42+03:00")))
    assert value.issue_date == "2026-09-27" and value.issue_time == "00:05:42+03:00"
    forbidden.assert_not_called()


@pytest.mark.parametrize("bad_time", [None, "PRIVATE-INVALID-TIME"])
def test_characterize_legacy_missing_invalid_time_invents_midnight(bad_time):
    # This asserts the existing defect, NOT desired behavior or a runtime fix.
    assert legacy.get_time_string(bad_time) == "00:00:00"


def test_characterize_legacy_duration_wraps_and_drops_explicit_offset():
    assert legacy.get_time_string(timedelta(days=1, hours=1)) == "01:00:00"
    assert legacy.get_time_string("09:05:42+03:00") == "09:05:42"


def test_characterize_direct_reference_rejects_valid_zero_duration(monkeypatch):
    import xml.etree.ElementTree as ET
    from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document
    row = Document(advance_invoice=INVOICE_ID, allocated_total_amount=1,
        allocated_taxable_amount=1, allocated_tax_amount=0)
    advance = Document(name=INVOICE_ID, posting_date="2026-09-27", posting_time=timedelta(0))
    invoice = Document(currency="SAR", custom_zatca_advance_deduction_details=[row])
    monkeypatch.setattr(legacy, "supports_advance_deduction_schema", lambda doc: True)
    monkeypatch.setattr(legacy.frappe, "get_doc", lambda *args: advance)
    monkeypatch.setattr(legacy, "_", lambda text: text)
    def fail(text):
        raise ValueError(text)
    monkeypatch.setattr(legacy.frappe, "throw", fail)
    root = ET.Element("Invoice")
    with pytest.raises(ValueError, match="missing its authoritative issue date/time"):
        legacy._append_direct_advance_reference_lines(root, invoice)
    assert list(root) == []
