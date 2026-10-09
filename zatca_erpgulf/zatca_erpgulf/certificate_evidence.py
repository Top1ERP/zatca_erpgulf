"""Public embedded-certificate observations, not signature or trust validation.

Never read current credentials, resolve an owner, verify acceptance, or repair
certificate-hashing/SignedProperties. A certificate in unsigned/tampered XML is
only a declaration; its fingerprint is not a verified signing-credential epoch.
"""

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import (
    NS, ArtifactEvidenceError, parse_diagnostic_xml,
)


MAX_CERTIFICATE_DER_BYTES = 64 * 1024
MAX_CERTIFICATE_TEXT_BYTES = 128 * 1024
CERTIFICATE_NS = {
    **NS,
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "sig": "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
    "sac": "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
}
SIGNATURE_PATH = (
    "./ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/"
    "sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature"
)


@dataclass(frozen=True)
class EmbeddedCertificateEvidence:
    """Fingerprint-only projection; no certificate, DN, token or key material."""

    der_sha256: str
    public_key_sha256: str
    element_text_sha256: str
    der_byte_length: int


def _one(parent, path, code):
    nodes = parent.xpath(path, namespaces=CERTIFICATE_NS)
    if len(nodes) != 1:
        raise ArtifactEvidenceError(code)
    return nodes[0]


def inspect_embedded_certificate(content):
    """Observe one certificate inside the canonical UBL signature location.

    Refuse alternate/nested signatures, duplicate IDs and unrelated certificates.
    The chosen signature must declare the unique invoiceSignedData reference.
    These structural checks are NOT a cryptographic binding verification.
    """
    root = parse_diagnostic_xml(content)
    signature = _one(root, SIGNATURE_PATH, "certificate_signature_location")
    if len(root.xpath(".//ds:Signature", namespaces=CERTIFICATE_NS)) != 1:
        raise ArtifactEvidenceError("certificate_signature_ambiguous")
    signature_id = signature.get("Id")
    if (
        not signature_id or len(signature_id) > 128
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", signature_id)
    ):
        raise ArtifactEvidenceError("certificate_signature_id")
    ids = root.xpath(
        "descendant-or-self::*[@Id=$value or @ID=$value or @id=$value]",
        value=signature_id,
    )
    if len(ids) != 1:
        raise ArtifactEvidenceError("certificate_signature_id_ambiguous")
    signed_info = _one(signature, "./ds:SignedInfo", "certificate_signed_info")
    reference = _one(
        signed_info, "./ds:Reference[@Id='invoiceSignedData']",
        "certificate_invoice_reference",
    )
    if reference.get("URI") != "" or len(root.xpath(
        ".//ds:Reference[@Id='invoiceSignedData']", namespaces=CERTIFICATE_NS
    )) != 1:
        raise ArtifactEvidenceError("certificate_invoice_reference")
    key_info = _one(signature, "./ds:KeyInfo", "certificate_key_info")
    data = _one(key_info, "./ds:X509Data", "certificate_x509_data")
    node = _one(data, "./ds:X509Certificate", "certificate_value")
    if len(root.xpath(".//ds:X509Certificate", namespaces=CERTIFICATE_NS)) != 1:
        raise ArtifactEvidenceError("certificate_value_ambiguous")
    text = node.text or ""
    if len(node) or not text:
        raise ArtifactEvidenceError("certificate_value")
    try:
        # Accept XML's four ASCII whitespace characters, not arbitrary Unicode.
        raw_text = text.encode("ascii")
        if len(raw_text) > MAX_CERTIFICATE_TEXT_BYTES:
            raise ArtifactEvidenceError("certificate_size")
        compact = re.sub(rb"[ \t\r\n]", b"", raw_text)
        der = base64.b64decode(compact, validate=True)
    except ArtifactEvidenceError:
        raise
    except (ValueError, binascii.Error):
        raise ArtifactEvidenceError("certificate_base64") from None
    if not der or len(der) > MAX_CERTIFICATE_DER_BYTES:
        raise ArtifactEvidenceError("certificate_size")
    try:
        certificate = x509.load_der_x509_certificate(der)
        # Reject a noncanonical/trailing-byte representation, not merely its prefix.
        if certificate.public_bytes(serialization.Encoding.DER) != der:
            raise ArtifactEvidenceError("certificate_der_representation")
        public_key = certificate.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except ArtifactEvidenceError:
        raise
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise ArtifactEvidenceError("certificate_der") from None
    return EmbeddedCertificateEvidence(
        hashlib.sha256(der).hexdigest(), hashlib.sha256(public_key).hexdigest(),
        hashlib.sha256(raw_text).hexdigest(), len(der),
    )
