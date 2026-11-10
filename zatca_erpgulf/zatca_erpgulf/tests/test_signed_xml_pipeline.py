"""Offline signing parity with the former sequence and ephemeral certificates.

The small reference below freezes the pre-extraction algorithm from f29bdde.
ECDSA is randomized: reuse each test-only signature for the same input during
the comparison, then independently verify it with the selected public key.
These checks preserve existing behavior; they are not ZATCA SDK acceptance.
"""

import base64
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from lxml import etree

from zatca_erpgulf.zatca_erpgulf import sign_invoice as invoices
from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES
from zatca_erpgulf.zatca_erpgulf.signed_xml_pipeline import (
    SignedInvoiceXml, SigningTools, encode_qr_payload, sign_invoice_xml,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import (
    Document, boundary, materials,
)


def previous_sequence(xml, abbr, source, tools):
    """Frozen former Sales/POS sequence, including ordered list-based TLV."""
    removed = tools.removetags(xml)
    canonical = tools.canonicalize_xml(removed)
    digest, encoded_hash = tools.getinvoicehash(canonical)
    signature = tools.digital_signature(digest, abbr, source)
    issuer, serial = tools.extract_certificate_details(abbr, source)
    certificate_hash = tools.certificate_hash(abbr, source)
    modified, namespaces, signing_time = tools.signxml_modify(abbr, xml, source)
    properties_hash = tools.generate_signed_properties_hash(
        signing_time, issuer, serial, certificate_hash,
    )
    signed = tools.populate_the_ubl_extensions_output(
        modified, signature, namespaces, properties_hash, encoded_hash, abbr, source,
    )
    tags = tools.generate_tlv_xml(signed, abbr, source)
    chunks = []
    for tag, value in tags.items():
        chunks.append(tools.get_tlv_for_value(tag, value))
    qr = base64.b64encode(b"".join(chunks)).decode("utf-8")
    return encoded_hash, qr, tools.update_qr_toxml(signed, qr, abbr)


def decode_tags(payload):
    """Decode the existing TLV representation without using the new encoder."""
    data, result = base64.b64decode(payload), []
    while data:
        tag, length = data[:2]
        start = 2
        if (length == 255 and len(data) > 3
                and 256 <= int.from_bytes(data[2:4], "big") <= len(data) - 4):
            length, start = int.from_bytes(data[2:4], "big"), 4
        result.append((tag, data[start:start + length]))
        data = data[start + length:]
    return result


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("owner,index", [("company", 0), ("device", 2), ("linked", 1)])
@pytest.mark.parametrize("validation_type", COMPLIANCE_TYPES)
def test_real_xml_qr_and_selected_certificate_match_former_sequence(
    boundary, materials, monkeypatch, doctype, owner, index, validation_type,
):
    b = boundary
    source = b.sales if doctype == "Sales Invoice" else b.pos
    source.custom_zatca_invoice_type = validation_type
    if owner == "company":
        source.custom_zatca_pos_name = None
    elif owner == "linked":
        b.device.custom_linked_doctype = b.linked.name
        b.device.custom__use_company_certificate__keys = 1
    b.company.company_name = "شركة الاختبار"
    address = Document(address_line1="Test Street", address_line2="Test District", city="Riyadh",
                       custom_building_number="1234", pincode="12345", state="")
    monkeypatch.setattr(invoices, "_onboarding_address", lambda *args: address)
    instant = datetime(2026, 11, 10, 9, 5, 42, tzinfo=timezone.utc)
    monkeypatch.setattr(client, "datetime", SimpleNamespace(utcnow=lambda: instant.replace(tzinfo=None)))
    _uuid, xml = invoices._build_onboarding_invoice_xml(
        b.company, validation_type, issue_instant=instant,
    )
    signatures = {}

    def repeat_signature(digest, abbr, doc):
        key = digest, abbr, id(doc)
        if key not in signatures:
            signatures[key] = client.digital_signature(digest, abbr, doc)
        return signatures[key]

    tools = replace(SigningTools.from_namespace(vars(client)), digital_signature=repeat_signature)
    expected_hash, expected_qr, expected_xml = previous_sequence(xml, "TC", source, tools)
    actual = sign_invoice_xml(xml, "TC", source, tools=tools)
    assert (actual.encoded_hash, actual.qr_payload, actual.xml) == (expected_hash, expected_qr, expected_xml)
    root = etree.fromstring(actual.xml.encode())
    namespaces = {key: value for node in root.iter() for key, value in node.nsmap.items() if key}
    selected = materials[index]
    assert root.find(".//ds:X509Certificate", namespaces).text == selected.text
    reference = root.find(".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", namespaces)
    assert reference.text == actual.encoded_hash
    qr_node = root.find("cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces)
    assert qr_node.text == actual.qr_payload
    tags = dict(decode_tags(actual.qr_payload))
    assert tags[1] == "شركة الاختبار".encode()
    assert tags[3] == b"2026-11-10T09:05:42Z"
    assert tags[6] == actual.encoded_hash.encode()
    signature = root.find(".//ds:SignatureValue", namespaces).text
    assert tags[7] == signature.encode()
    assert (9 in tags) == validation_type.startswith("Simplified")
    selected.cert.public_key().verify(
        base64.b64decode(signature), base64.b64decode(actual.encoded_hash), ec.ECDSA(hashes.SHA256()),
    )
    # Existing final formatter is outside the shared sequence in both paths.
    assert client.format_zatca_signed_xml(actual.xml) == client.format_zatca_signed_xml(expected_xml)
    assert len(signatures) == 1
    b.request.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    for record in (b.company, b.device, b.linked):
        record.save.assert_not_called()
        record.db_set.assert_not_called()


def mock_tools():
    namespace = {item.name: Mock(name=item.name) for item in fields(SigningTools)}
    namespace["getinvoicehash"].return_value = ("digest", "encoded-hash")
    namespace["extract_certificate_details"].return_value = ("issuer", "serial")
    namespace["signxml_modify"].return_value = ("modified", {}, "time")
    namespace["generate_tlv_xml"].return_value = {1: "seller", 8: b"key"}
    namespace["get_tlv_for_value"].return_value = b"tag"
    namespace["update_qr_toxml"].return_value = "final-xml"
    return namespace


@pytest.mark.parametrize("failed", [item.name for item in fields(SigningTools)])
def test_each_stage_failure_stops_later_work_without_wrapping(failed):
    namespace = mock_tools()
    sentinel = ValueError("synthetic-stage-failure")
    namespace[failed].side_effect = sentinel
    with pytest.raises(ValueError) as raised:
        sign_invoice_xml("input", "TC", object(), tools=SigningTools.from_namespace(namespace))
    assert raised.value is sentinel
    ordered = [item.name for item in fields(SigningTools)]
    for later in ordered[ordered.index(failed) + 1:]:
        namespace[later].assert_not_called()


def test_functions_are_bound_per_invocation_without_namespace_or_owner_retention():
    namespace = mock_tools()
    secret = object()
    namespace.update(private_key=secret, invoice=secret)
    first = SigningTools.from_namespace(namespace)
    first_updater = namespace["update_qr_toxml"]
    namespace["update_qr_toxml"] = Mock(return_value="changed")
    second = SigningTools.from_namespace(namespace)
    assert first.update_qr_toxml is first_updater
    assert second.update_qr_toxml is namespace["update_qr_toxml"]
    assert set(vars(first)) == {item.name for item in fields(SigningTools)}
    assert all(value is not secret for value in vars(first).values())
    with pytest.raises(FrozenInstanceError):
        first.update_qr_toxml = namespace["update_qr_toxml"]


@pytest.mark.parametrize("invalid", [None, "secret-marker", 1])
def test_incomplete_or_noncallable_tools_fail_before_any_operation(invalid):
    namespace = mock_tools()
    namespace["update_qr_toxml"] = invalid
    with pytest.raises(TypeError, match="^invalid_signing_tools$"):
        SigningTools.from_namespace(namespace)
    for operation in namespace.values():
        if isinstance(operation, Mock):
            operation.assert_not_called()


@pytest.mark.parametrize("values", [{}, {9: b"\x00\xff", 1: "شركة", 6: "encoded-digest"},
                                  {1: "x" * 254}, {1: "x" * 255}, {1: "x" * 256}, {1: "ع" * 128}])
def test_qr_encoding_keeps_order_utf8_binary_and_existing_long_string_policy(values):
    expected = base64.b64encode(b"".join(client.get_tlv_for_value(k, v) for k, v in values.items())).decode()
    assert encode_qr_payload(values, client.get_tlv_for_value) == expected
    assert decode_tags(expected) == [(k, v.encode() if isinstance(v, str) else v) for k, v in values.items()]


def test_artifact_repr_does_not_disclose_invoice_or_qr_content():
    artifact = SignedInvoiceXml("private-hash", "private-qr", "private-xml")
    assert repr(artifact) == "<SignedInvoiceXml protected local artifact>"
    with pytest.raises(FrozenInstanceError):
        artifact.xml = "changed"
