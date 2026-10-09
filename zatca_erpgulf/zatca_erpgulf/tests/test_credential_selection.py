"""Credential ownership regressions using ephemeral keys and mocked saved records.

No site, customer certificate, key, database write, or network is used. Digest
tests preserve the existing serialization algorithm; they are not SDK approval.
"""

import base64
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from lxml import etree

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_group
from zatca_erpgulf.zatca_erpgulf import credential_settings as settings
from zatca_erpgulf.zatca_erpgulf import qr_timestamp
from zatca_erpgulf.zatca_erpgulf import sign_invoice as invoices
from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES
from zatca_erpgulf.zatca_erpgulf.credential_material import (
    CredentialConfigurationError, authorization_for_owner, certificate_value,
    use_linked_company,
)


class Document(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class ValidationError(Exception):
    pass


def fail(message, *args, **kwargs):
    raise ValidationError(str(message))


@pytest.fixture(scope="module")
def materials():
    """Create unrelated test-only key pairs; never serialize them to disk."""
    result = []
    for number in range(1, 4):
        key = ec.generate_private_key(ec.SECP256K1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"TEST ONLY {number}")])
        cert = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(number)
            .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2030, 1, 1))
            .sign(key, hashes.SHA256())
        )
        result.append(Document(
            cert=cert, text=base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode(),
            pem=key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode(),
        ))
    return result


@pytest.fixture
def boundary(monkeypatch, materials):
    def owner(doctype, name, material, **kwargs):
        return Document(
            doctype=doctype, name=name, custom_certificate=material.text,
            custom_private_key=material.pem, custom_basic_auth_from_csid=f"{name}-compliance",
            custom_basic_auth_from_production=f"{name}-production",
            custom_final_auth_csid=f"{name}-device-production", save=Mock(), db_set=Mock(), **kwargs,
        )

    company = owner("Company", "A", materials[0], abbr="TC", tax_id="TEST-VAT", custom_select="Production")
    linked = owner("Company", "B", materials[1], tax_id="TEST-VAT")
    device = owner("ZATCA Multiple Setting", "DEVICE", materials[2],
                   custom_linked_doctype="A", custom__use_company_certificate__keys=0)
    sales = Document(doctype="Sales Invoice", name="SI", company="A", custom_zatca_pos_name="DEVICE")
    pos = Document(doctype="POS Invoice", name="PI", company="A", custom_zatca_pos_name="DEVICE")
    docs = {(doc.doctype, doc.name): doc for doc in (company, linked, device, sales, pos)}

    def get_doc(doctype, name):
        if doctype == "Company" and isinstance(name, dict):
            assert name == {"abbr": "TC"}
            return company
        return docs[doctype, name]

    frappe = SimpleNamespace(
        get_doc=Mock(side_effect=get_doc), throw=fail, ValidationError=ValidationError,
        db=SimpleNamespace(get_value=Mock(return_value="A"), commit=Mock()), msgprint=Mock(),
    )
    for module in (settings, client, invoices):
        monkeypatch.setattr(module, "frappe", frappe)
        monkeypatch.setattr(module, "_", lambda message: message)
    request = Mock(return_value=SimpleNamespace(
        status_code=200, json=lambda: {"validationResults": {"status": "PASS", "errorMessages": []}},
    ))
    monkeypatch.setattr(client.requests, "request", request)
    monkeypatch.setattr(client, "get_compliance_api_url", lambda *args: "https://example.invalid/compliance/invoices")
    monkeypatch.setattr(client, "xml_base64_decode", lambda *args: "TEST XML")
    monkeypatch.setattr(client, "create_public_key", Mock(side_effect=AssertionError("No writes allowed")))
    return Document(company=company, linked=linked, device=device, sales=sales, pos=pos,
                    frappe=frappe, request=request)


@pytest.mark.parametrize("value, expected", [(None, False), (False, False), (0, False), ("0", False),
                                           (" 0 ", False), ("", False), (True, True), (1, True), ("1", True)])
def test_checkbox_false_is_not_lost(value, expected):
    assert use_linked_company(value) is expected


@pytest.mark.parametrize("value", ["False", "true", 2, [], {}])
def test_unknown_checkbox_values_are_not_truthy_fallbacks(value):
    with pytest.raises(CredentialConfigurationError, match="link_flag"):
        use_linked_company(value)


@pytest.mark.parametrize("source_name", [None, "company", "sales", "pos", "device"])
@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("wire_format", ["doc", "dict", "json"])
def test_all_sources_resolve_saved_owners(boundary, source_name, linked, wire_format):
    b = boundary
    b.device.custom__use_company_certificate__keys = "1" if linked else "0"
    b.device.custom_linked_doctype = "B" if linked else "A"
    source = getattr(b, source_name) if source_name else None
    expected = b.company if source_name in (None, "company") else b.linked if linked else b.device
    if source is not None and wire_format != "doc":
        source = {"doctype": source.doctype, "name": source.name,
                  "custom_private_key": "UNTRUSTED", "custom_zatca_pos_name": "UNTRUSTED"}
        if wire_format == "json":
            source = json.dumps(source)
    owner = settings.resolve_credential_owner("TC", source)
    assert (owner.doctype, owner.name) == (expected.doctype, expected.name)
    assert settings.get_signing_certificate("TC", source) == expected.custom_certificate
    assert settings.get_api_authorization("TC", source, purpose="compliance").header == (
        "Basic " + expected.custom_basic_auth_from_csid
    )
    with pytest.raises(TypeError):
        owner.values["custom_private_key"] = "replacement"
    assert "PRIVATE KEY" not in repr(owner)


@pytest.mark.parametrize("source", ["bad json", "[]", {}, {"doctype": "User", "name": "A"},
                                  {"doctype": "Company", "name": 42}, {"doctype": "Company", "name": " "}])
def test_invalid_source_rejected(boundary, source):
    with pytest.raises(ValidationError, match="saved Company"):
        settings.resolve_credential_owner("TC", source)
    boundary.request.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice", "Company"])
def test_cross_company_sources_rejected(boundary, doctype):
    source = boundary.linked if doctype == "Company" else boundary.sales if doctype == "Sales Invoice" else boundary.pos
    source.company = "B"
    with pytest.raises(ValidationError, match="does not belong"):
        settings.resolve_credential_owner("TC", source)


@pytest.mark.parametrize("vat", ["", None, "DIFFERENT"])
@pytest.mark.parametrize("use_company", [0, 1])
def test_linked_taxpayer_guard_applies_to_both_modes(boundary, vat, use_company):
    boundary.device.custom_linked_doctype = "B"
    boundary.device.custom__use_company_certificate__keys = use_company
    boundary.linked.tax_id = vat
    with pytest.raises(ValidationError, match="matching nonempty"):
        settings.resolve_credential_owner("TC", boundary.device)


def test_missing_link_rejected(boundary):
    boundary.device.custom_linked_doctype = None
    with pytest.raises(ValidationError, match="valid linked company"):
        settings.resolve_credential_owner("TC", boundary.sales)


@pytest.mark.parametrize("source_name, fieldname", [
    ("company", "custom_basic_auth_from_production"), ("device", "custom_final_auth_csid"),
])
def test_production_has_dedicated_field_without_compliance_fallback(boundary, source_name, fieldname):
    source = getattr(boundary, source_name)
    auth = settings.get_api_authorization("TC", source, purpose="production")
    assert auth.fieldname == fieldname
    assert auth.header == "Basic " + getattr(source, fieldname)
    assert getattr(source, fieldname) not in repr(auth)
    setattr(source, fieldname, "")
    with pytest.raises(ValidationError, match="another purpose cannot be used"):
        settings.get_api_authorization("TC", source, purpose="production")


@pytest.mark.parametrize("value", [" secret-token ", "Basic secret-token", "basic secret-token", " BASIC secret-\ntoken "])
def test_authorization_normalizes_without_exposing_secrets(boundary, value):
    boundary.company.custom_basic_auth_from_csid = value
    auth = settings.get_api_authorization("TC", purpose="compliance")
    assert auth.header == "Basic secret-token"
    assert "secret-token" not in repr(auth)


@pytest.mark.parametrize("value", [None, "", "Basic ", 123])
def test_missing_compliance_never_uses_production(boundary, value):
    boundary.company.custom_basic_auth_from_csid = value
    with pytest.raises(ValidationError, match="another purpose cannot be used"):
        settings.get_api_authorization("TC", purpose="compliance")


def test_unknown_auth_purpose_rejected(boundary):
    with pytest.raises(CredentialConfigurationError, match="purpose"):
        authorization_for_owner(settings.resolve_credential_owner("TC"), "clearance")


@pytest.mark.parametrize("spelling", ["legacy", "canonical", "both"])
def test_certificate_alias_policy_preserves_legacy_bytes(boundary, spelling):
    value = boundary.device.custom_certificate
    boundary.device.custom_certficate = "\n" + value[:64] + "\n" + value[64:] + "\n" if spelling != "canonical" else None
    if spelling == "legacy":
        boundary.device.custom_certificate = None
    expected = (boundary.device.custom_certficate or value).strip()
    assert settings.get_signing_certificate("TC", boundary.device) == expected
    assert get_alias_group("multiple_setting_certificate")["canonical"] == "custom_certificate"


def test_conflicting_certificate_fields_stop_signing_without_overwrite(boundary):
    boundary.device.custom_certficate = boundary.company.custom_certificate
    with pytest.raises(ValidationError, match="contain different values"):
        client.digital_signature("ab" * 32, "TC", boundary.sales)
    assert boundary.device.custom_certficate == boundary.company.custom_certificate
    boundary.device.save.assert_not_called()


@pytest.mark.parametrize("values", [{}, {"certificate": 42}, {"certificate": " \n "}])
def test_invalid_certificate_field_rejected(values):
    with pytest.raises(CredentialConfigurationError, match="certificate"):
        certificate_value(values, ("certificate",))


@pytest.mark.parametrize("source_name, index", [("company", 0), ("sales", 2), ("pos", 2), ("device", 2), ("linked", 1)])
def test_real_signing_qr_and_digest_use_one_owner_policy_without_writes(boundary, materials, source_name, index):
    if source_name == "linked":
        boundary.device.custom__use_company_certificate__keys = 1
        boundary.device.custom_linked_doctype = "B"
        source = boundary.device
    else:
        source = getattr(boundary, source_name)
    material = materials[index]
    signature = client.digital_signature("ab" * 32, "TC", source)
    material.cert.public_key().verify(base64.b64decode(signature), bytes.fromhex("ab" * 32), ec.ECDSA(hashes.SHA256()))
    expected_digest = base64.b64encode(hashlib.sha256(material.text.encode()).hexdigest().encode()).decode()
    assert client.certificate_hash("TC", source) == expected_digest
    assert client.extract_certificate_details("TC", source) == (f"CN=TEST ONLY {index + 1}", index + 1)
    assert client.tag8_publickey("TC", source) == material.cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    assert client.tag9_signature_ecdsa("TC", source) == material.cert.signature
    client.create_public_key.assert_not_called()
    boundary.frappe.db.commit.assert_not_called()
    for doc in (boundary.company, boundary.linked, boundary.device):
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()


@pytest.mark.parametrize("value, message", [("mismatch", "does not match"), (None, "private key"), ("invalid", "private key")])
def test_bad_key_rejected_before_signing(boundary, value, message):
    boundary.device.custom_private_key = boundary.company.custom_private_key if value == "mismatch" else value
    with pytest.raises(ValidationError, match=message):
        client.digital_signature("ab" * 32, "TC", boundary.sales)


def test_malformed_certificate_is_safe_error(boundary):
    boundary.company.custom_certificate = "SECRET-NOT-A-CERTIFICATE"
    with pytest.raises(ValidationError, match="valid saved ZATCA certificate") as error:
        settings.get_signing_key("TC")
    assert "SECRET-NOT-A-CERTIFICATE" not in str(error.value)


@pytest.mark.parametrize("source_name", ["company", "sales", "pos", "device"])
@pytest.mark.parametrize("linked", [False, True])
def test_real_compliance_boundary_uses_selected_owner(boundary, source_name, linked):
    boundary.device.custom__use_company_certificate__keys = int(linked)
    boundary.device.custom_linked_doctype = "B" if linked else "A"
    source = getattr(boundary, source_name)
    expected = boundary.company if source_name == "company" else boundary.linked if linked else boundary.device
    client.compliance_api_call("test-uuid", "test-hash", "unused.xml", "TC", source)
    assert boundary.request.call_args.kwargs["headers"]["Authorization"] == "Basic " + expected.custom_basic_auth_from_csid
    assert boundary.request.call_args.kwargs["url"].endswith("/compliance/invoices")


def test_missing_compliance_auth_cannot_send_http(boundary):
    boundary.device.custom_basic_auth_from_csid = ""
    with pytest.raises(ValidationError, match="another purpose cannot be used"):
        client.compliance_api_call("test-uuid", "test-hash", "unused.xml", "TC", boundary.device)
    boundary.request.assert_not_called()


def test_ubl_certificate_population_preserves_selected_content(boundary):
    from zatca_erpgulf.zatca_erpgulf.createxml import xml_tags

    root = etree.fromstring(ET.tostring(xml_tags()))
    namespaces = {key: value for node in root.iter() for key, value in node.nsmap.items() if key}
    xml = client.populate_the_ubl_extensions_output(
        etree.tostring(root).decode(), "signature", namespaces, "properties-hash", "invoice-hash", "TC", boundary.device,
    )
    result = etree.fromstring(xml.encode())
    assert result.find(".//ds:X509Certificate", namespaces).text == boundary.device.custom_certificate
    assert result.find(".//ds:SignatureValue", namespaces).text == "signature"


@pytest.mark.parametrize("validation_type", COMPLIANCE_TYPES)
def test_six_synthetic_documents_prepare_locally_without_saving_keys(boundary, monkeypatch, validation_type):
    address = Document(address_line1="Test Street", address_line2="Test District", city="Riyadh",
                       custom_building_number="1234", pincode="12345", state="")
    monkeypatch.setattr(invoices, "_onboarding_address", lambda *args: address)
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", lambda: "Asia/Riyadh")
    invoice_uuid, invoice_hash, xml = invoices._prepare_signed_onboarding_document(boundary.company, validation_type)
    root = etree.fromstring(xml.encode())
    namespaces = {key: value for node in root.iter() for key, value in node.nsmap.items() if key}
    assert root.find("cbc:UUID", namespaces).text == invoice_uuid
    assert root.find(".//ds:X509Certificate", namespaces).text == boundary.company.custom_certificate
    assert len(base64.b64decode(invoice_hash)) == 32
    qr = root.find("cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces)
    assert len(base64.b64decode(qr.text)) > 100
    boundary.request.assert_not_called()
    boundary.company.save.assert_not_called()
    boundary.company.db_set.assert_not_called()
    boundary.frappe.db.commit.assert_not_called()


def test_configuration_errors_have_arabic_translations(boundary):
    path = Path(__file__).resolve().parents[2] / "translations" / "ar.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        translations = {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}
    for code in ("source", "company", "linked_company", "taxpayer", "link_flag", "certificate",
                 "certificate_conflict", "private_key", "key_mismatch", "purpose", "authorization"):
        with pytest.raises(ValidationError) as error:
            settings._throw_configuration_error(CredentialConfigurationError(code))
        assert any("\u0600" <= char <= "\u06ff" for char in translations[str(error.value)])
