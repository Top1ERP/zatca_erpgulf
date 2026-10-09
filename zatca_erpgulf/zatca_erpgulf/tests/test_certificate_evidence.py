"""Synthetic public certificates only; no real signing/acceptance fixtures."""

import base64
import copy
import hashlib
from dataclasses import FrozenInstanceError
from datetime import datetime

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import certificate_evidence as evidence
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import artifact_root, xml_bytes


def node(parent, namespace, tag, text=None, **attributes):
    element = etree.SubElement(parent, f"{{{evidence.CERTIFICATE_NS[namespace]}}}{tag}", **attributes)
    element.text = text
    return element


@pytest.fixture(scope="module")
def certificates():
    key, other_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PRIVATE-DN-NOT-TO-EXPOSE")])

    def build(key, serial):
        cert = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(serial)
            .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2030, 1, 1))
            .sign(key, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.DER)

    return build(key, 1), build(key, 2), build(other_key, 3)


def certificate_root(der, *, text=None):
    root = artifact_root()
    signature = root.find("ds:Signature", namespaces=evidence.CERTIFICATE_NS)
    root.remove(signature)
    signature.set("Id", "signature")
    extension = node(node(root, "ext", "UBLExtensions"), "ext", "UBLExtension")
    document_signatures = node(node(extension, "ext", "ExtensionContent"), "sig", "UBLDocumentSignatures")
    information = node(document_signatures, "sac", "SignatureInformation")
    information.append(signature)
    ref = signature.xpath("./ds:SignedInfo/ds:Reference[@Id='invoiceSignedData']", namespaces=evidence.CERTIFICATE_NS)[0]
    ref.set("URI", "")
    # Deliberately not a valid XML signature; observation must not certify it.
    node(signature, "ds", "SignatureValue", "NOT-A-VALID-SIGNATURE")
    data = node(node(signature, "ds", "KeyInfo"), "ds", "X509Data")
    node(data, "ds", "X509Certificate", base64.b64encode(der).decode() if text is None else text)
    return root


def find(root, path):
    return root.xpath(path, namespaces=evidence.CERTIFICATE_NS)[0]


def signature(root):
    return find(root, evidence.SIGNATURE_PATH)


def cert_node(root):
    return find(signature(root), "./ds:KeyInfo/ds:X509Data/ds:X509Certificate")


def inspect(root):
    return evidence.inspect_embedded_certificate(xml_bytes(root))


def assert_code(root, code):
    with pytest.raises(ArtifactEvidenceError) as error:
        inspect(root)
    assert error.value.code == code
    assert str(error.value) == code


def test_fingerprint_only_immutable_projection(certificates):
    der = certificates[0]
    root = certificate_root(der)
    before = xml_bytes(root)
    found = inspect(root)
    cert = x509.load_der_x509_certificate(der)
    spki = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert found.der_sha256 == hashlib.sha256(der).hexdigest()
    assert found.public_key_sha256 == hashlib.sha256(spki).hexdigest()
    assert found.element_text_sha256 == hashlib.sha256(cert_node(root).text.encode()).hexdigest()
    assert found.der_byte_length == len(der)
    assert "PRIVATE-DN" not in repr(found)
    assert base64.b64encode(der).decode() not in repr(found)
    assert xml_bytes(root) == before
    with pytest.raises(FrozenInstanceError):
        found.der_sha256 = "changed"


def test_renewed_certificate_can_share_public_key_without_sharing_version(certificates):
    first, renewed, different = [inspect(certificate_root(der)) for der in certificates]
    assert first.der_sha256 != renewed.der_sha256
    assert first.public_key_sha256 == renewed.public_key_sha256
    assert first.public_key_sha256 != different.public_key_sha256


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16", "UTF-16LE"])
def test_declared_xml_encoding_does_not_change_der_fingerprint(certificates, encoding):
    root = certificate_root(certificates[0])
    content = etree.tostring(root, encoding=encoding, xml_declaration=True)
    assert evidence.inspect_embedded_certificate(content).der_sha256 == hashlib.sha256(certificates[0]).hexdigest()


@pytest.mark.parametrize("whitespace", [" ", "\t", "\r", "\n", "\r\n", " \n\t"])
def test_xml_whitespace_has_same_der_but_different_element_text(certificates, whitespace):
    root = certificate_root(certificates[0])
    plain = inspect(root)
    text = cert_node(root).text
    cert_node(root).text = whitespace + whitespace.join(text[i:i + 20] for i in range(0, len(text), 20)) + whitespace
    wrapped = inspect(root)
    assert wrapped.der_sha256 == plain.der_sha256
    assert wrapped.public_key_sha256 == plain.public_key_sha256
    assert wrapped.element_text_sha256 != plain.element_text_sha256


@pytest.mark.parametrize("text,code", [
    ("", "certificate_value"), (" ", "certificate_size"),
    ("NOT-BASE64", "certificate_base64"), ("123", "certificate_base64"),
    ("-----BEGIN CERTIFICATE-----", "certificate_base64"),
    ("AA==\u00a0", "certificate_base64"), ("AA==\u0085", "certificate_base64"),
    ("اختبار", "certificate_base64"), ("AA==junk", "certificate_base64"),
    ("A" * (evidence.MAX_CERTIFICATE_TEXT_BYTES + 1), "certificate_size"),
    (base64.b64encode(b"x" * (evidence.MAX_CERTIFICATE_DER_BYTES + 1)).decode(), "certificate_size"),
    (base64.b64encode(b"not a certificate PRIVATE-DN").decode(), "certificate_der"),
])
def test_invalid_bounded_certificate_values_are_static(certificates, text, code):
    assert_code(certificate_root(certificates[0], text=text), code)


def test_certificate_element_must_be_scalar(certificates):
    root = certificate_root(certificates[0])
    node(cert_node(root), "ds", "Certificate", "private text")
    assert_code(root, "certificate_value")


@pytest.mark.parametrize("id_value", [None, "", "has spaces", "#signature", "أ", "s" * 129])
def test_missing_or_unsafe_signature_id(certificates, id_value):
    root = certificate_root(certificates[0])
    if id_value is None:
        signature(root).attrib.pop("Id")
    else:
        signature(root).set("Id", id_value)
    assert_code(root, "certificate_signature_id")


@pytest.mark.parametrize("attribute", ["Id", "ID", "id"])
def test_duplicated_signature_ids_are_ambiguous(certificates, attribute):
    root = certificate_root(certificates[0])
    node(root, "cbc", "Note", "not a signature", **{attribute: "signature"})
    assert_code(root, "certificate_signature_id_ambiguous")


@pytest.mark.parametrize("kind", ["nested_signature", "second_signature", "outside_certificate", "duplicate_certificate", "wrong_location"])
def test_signature_and_certificate_location_ambiguity(certificates, kind):
    root = certificate_root(certificates[0])
    target = signature(root)
    if kind == "nested_signature":
        node(root, "cac", "Attachment").append(copy.deepcopy(target))
        code = "certificate_signature_ambiguous"
    elif kind == "second_signature":
        target.getparent().append(copy.deepcopy(target))
        code = "certificate_signature_location"
    elif kind == "outside_certificate":
        root.append(copy.deepcopy(cert_node(root)))
        code = "certificate_value_ambiguous"
    elif kind == "duplicate_certificate":
        cert_node(root).getparent().append(copy.deepcopy(cert_node(root)))
        code = "certificate_value"
    else:
        target.getparent().remove(target)
        root.append(target)
        code = "certificate_signature_location"
    assert_code(root, code)


@pytest.mark.parametrize("path,code", [
    ("./ds:SignedInfo", "certificate_signed_info"),
    ("./ds:KeyInfo", "certificate_key_info"),
    ("./ds:KeyInfo/ds:X509Data", "certificate_x509_data"),
    ("./ds:KeyInfo/ds:X509Data/ds:X509Certificate", "certificate_value"),
    ("./ds:SignedInfo/ds:Reference[@Id='invoiceSignedData']", "certificate_invoice_reference"),
])
@pytest.mark.parametrize("action", ["remove", "duplicate"])
def test_required_structure_is_unique(certificates, path, code, action):
    root = certificate_root(certificates[0])
    target = find(signature(root), path)
    if action == "remove":
        target.getparent().remove(target)
    else:
        target.getparent().append(copy.deepcopy(target))
    assert_code(root, code)


@pytest.mark.parametrize("uri", [None, "#another-document", "https://remote.invalid/invoice"])
def test_invoice_reference_cannot_select_other_content(certificates, uri):
    root = certificate_root(certificates[0])
    target = find(signature(root), "./ds:SignedInfo/ds:Reference[@Id='invoiceSignedData']")
    if uri is None:
        target.attrib.pop("URI")
    else:
        target.set("URI", uri)
    assert_code(root, "certificate_invoice_reference")


@pytest.mark.parametrize("content,code", [
    ("<Invoice/>", "xml_bytes_required"), (b"", "xml_size"),
    (b"not xml PRIVATE-DN", "xml_syntax"), (b"<Invoice/>", "xml_root"),
    (b'<!DOCTYPE Invoice [<!ENTITY x "private">]><Invoice/>', "xml_doctype"),
])
def test_certificate_reader_uses_shared_safe_xml_boundary(content, code):
    with pytest.raises(ArtifactEvidenceError) as error:
        evidence.inspect_embedded_certificate(content)
    assert error.value.code == code


@pytest.mark.parametrize("error", [ValueError("PRIVATE-DN"), TypeError("PRIVATE-DN"), UnsupportedAlgorithm("PRIVATE-DN")])
def test_parser_exceptions_never_expose_certificate_contents(certificates, monkeypatch, error):
    monkeypatch.setattr(evidence.x509, "load_der_x509_certificate", lambda der: (_ for _ in ()).throw(error))
    assert_code(certificate_root(certificates[0]), "certificate_der")


def test_der_trailing_bytes_are_not_fingerprinted_as_a_verified_prefix(certificates):
    root = certificate_root(certificates[0] + b"trailing")
    with pytest.raises(ArtifactEvidenceError) as error:
        inspect(root)
    assert error.value.code in ("certificate_der", "certificate_der_representation")
