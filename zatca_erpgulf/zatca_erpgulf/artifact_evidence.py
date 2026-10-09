"""Read-only issuance evidence; never sign, allocate, submit, or repair XML.

This is an internal identity/ambiguity check, not XSD, signature, invoice-hash,
QR, or remote-acceptance validation. Fingerprints describe exact input bytes,
not the transformed digest that ZATCA uses for the invoice.
"""

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass, field
from uuid import UUID

from lxml import etree


MAX_XML_BYTES = 5 * 1024 * 1024
NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}
SHA256_URI = "http://www.w3.org/2001/04/xmlenc#sha256"
UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
UUID_PLACEHOLDERS = {"", "not submitted", "not submitted.", "none", "null", "false", "0"}


class ArtifactEvidenceError(ValueError):
    """Static machine code only: XML/parser exceptions may contain private data."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _RejectExternalResources(etree.Resolver):
    """Do not fall through to libxml's default filesystem/network resolver."""

    def resolve(self, url, public_id, context):
        raise ArtifactEvidenceError("xml_external_resource")


@dataclass(frozen=True)
class ArtifactEvidence:
    invoice_id: str
    uuid: str
    icv: int
    seller_tax_id: str
    file_sha256: str
    byte_length: int
    invoice_digest: str = field(repr=False)
    previous_hash: str = field(repr=False)
    qr_present: bool = False


@dataclass(frozen=True)
class SavedInvoiceIdentity:
    """Explicit non-secret projection; do not pass an entire Company/credential DTO."""

    doctype: str
    invoice_name: str
    company_name: str
    seller_tax_id: str
    environment: str
    uuid: object
    icv: object
    issuing_unit: str
    status: str


def _one_node(parent, xpath, code):
    nodes = parent.xpath(xpath, namespaces=NS)
    if len(nodes) != 1:
        raise ArtifactEvidenceError(code)
    return nodes[0]


def _one_text(parent, xpath, code):
    node = _one_node(parent, xpath, code)
    if len(node) or not (node.text or "").strip():
        raise ArtifactEvidenceError(code)
    return node.text.strip()


def _additional_reference(root, label, code):
    references = root.xpath(
        "./cac:AdditionalDocumentReference[cbc:ID=$label]", namespaces=NS, label=label
    )
    if len(references) != 1:
        raise ArtifactEvidenceError(code)
    reference = references[0]
    if _one_text(reference, "./cbc:ID", code) != label:
        raise ArtifactEvidenceError(code)
    return reference


def _uuid(value):
    if not isinstance(value, str) or not UUID_PATTERN.fullmatch(value.strip()):
        raise ValueError("Invalid UUID format.")
    return str(UUID(value.strip()))


def parse_diagnostic_icv(value, *, allow_zero=False):
    """Bound read-only integer parsing; zero is valid only for a counter position."""
    text = str(value).strip()
    # Bound diagnostic integer parsing, independently of live counter policy.
    if isinstance(value, bool) or len(text) > 64 or not re.fullmatch(r"[0-9]+", text):
        raise ValueError("Invalid ICV format.")
    parsed = int(text)
    if parsed < 0 or (parsed == 0 and not allow_zero):
        raise ValueError("ICV must be positive.")
    return parsed


def _base64(value, code, *, length=None):
    # XML whitespace is allowed within binary values; no reserialization occurs.
    compact = "".join(value.split())
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error):
        raise ArtifactEvidenceError(code) from None
    if not decoded or (length is not None and len(decoded) != length):
        raise ArtifactEvidenceError(code)
    return compact


def inspect_invoice_artifact(content):
    """Extract unambiguous issuance metadata from bounded, namespace-aware bytes.

    Reject DTDs/entities, ambiguous root values/references, and wrong roots.
    Never use the first arbitrary UUID, CompanyID, or DigestValue in a document.
    Bytes preserve XML encoding declarations and the evidence fingerprint.
    """
    if not isinstance(content, bytes):
        raise ArtifactEvidenceError("xml_bytes_required")
    if not content or len(content) > MAX_XML_BYTES:
        raise ArtifactEvidenceError("xml_size")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False,
        recover=False, huge_tree=False,
    )
    parser.resolvers.add(_RejectExternalResources())
    try:
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError:
        raise ArtifactEvidenceError("xml_syntax") from None
    if root.getroottree().docinfo.doctype:
        raise ArtifactEvidenceError("xml_doctype")
    if any(root.iter(etree.Entity)):
        raise ArtifactEvidenceError("xml_entity")
    if root.tag != f"{{{NS['ubl']}}}Invoice":
        raise ArtifactEvidenceError("xml_root")
    invoice_id = _one_text(root, "./cbc:ID", "invoice_id")
    uuid_text = _one_text(root, "./cbc:UUID", "invoice_uuid")
    try:
        _uuid(uuid_text)
    except ValueError:
        raise ArtifactEvidenceError("invoice_uuid_format") from None
    icv_text = _one_text(
        _additional_reference(root, "ICV", "invoice_icv"), "./cbc:UUID", "invoice_icv"
    )
    try:
        icv = parse_diagnostic_icv(icv_text)
    except ValueError:
        raise ArtifactEvidenceError("invoice_icv_format") from None
    supplier = _one_node(root, "./cac:AccountingSupplierParty", "seller_tax_id")
    party = _one_node(supplier, "./cac:Party", "seller_tax_id")
    tax_scheme = _one_node(
        party, "./cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']", "seller_tax_id"
    )
    if _one_text(tax_scheme, "./cac:TaxScheme/cbc:ID", "seller_tax_id") != "VAT":
        raise ArtifactEvidenceError("seller_tax_id")
    seller_tax_id = _one_text(tax_scheme, "./cbc:CompanyID", "seller_tax_id")
    references = root.xpath(".//ds:Reference[@Id='invoiceSignedData']", namespaces=NS)
    if len(references) != 1:
        raise ArtifactEvidenceError("invoice_digest_reference")
    reference = references[0]
    methods = reference.xpath("./ds:DigestMethod", namespaces=NS)
    if len(methods) != 1 or methods[0].get("Algorithm") != SHA256_URI:
        raise ArtifactEvidenceError("invoice_digest_method")
    digest = _base64(
        _one_text(reference, "./ds:DigestValue", "invoice_digest"),
        "invoice_digest_format", length=32,
    )
    previous_hash = _base64(
        _one_text(
            _additional_reference(root, "PIH", "previous_hash"),
            "./cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
            "previous_hash",
        ),
        "previous_hash_format",
    )
    qr_references = root.xpath(
        "./cac:AdditionalDocumentReference[cbc:ID='QR']", namespaces=NS
    )
    if len(qr_references) > 1:
        raise ArtifactEvidenceError("qr_ambiguous")
    qr = []
    if qr_references:
        _one_text(qr_references[0], "./cbc:ID", "qr_ambiguous")
        qr = qr_references[0].xpath(
            "./cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces=NS
        )
        if len(qr) > 1:
            raise ArtifactEvidenceError("qr_ambiguous")
    return ArtifactEvidence(
        invoice_id, uuid_text, icv, seller_tax_id,
        hashlib.sha256(content).hexdigest(), len(content), digest, previous_hash,
        bool(qr and (qr[0].text or "").strip()),
    )


def compare_saved_identity(saved, evidence):
    """Return reconciliation codes, never choose/rewrite a UUID or counter."""
    issues = []
    if evidence.invoice_id != saved.invoice_name:
        issues.append("invoice_id_mismatch")
    if not saved.seller_tax_id:
        issues.append("saved_tax_id_missing")
    elif evidence.seller_tax_id != saved.seller_tax_id.strip():
        issues.append("seller_tax_id_mismatch")
    stored_uuid = str(saved.uuid or "").strip()
    if stored_uuid.lower() in UUID_PLACEHOLDERS:
        issues.append("saved_uuid_missing")
    else:
        try:
            matched = _uuid(stored_uuid) == _uuid(evidence.uuid)
        except ValueError:
            issues.append("saved_uuid_invalid")
        else:
            if not matched:
                issues.append("saved_uuid_mismatch")
    if saved.icv is None or saved.icv == "":
        issues.append("saved_icv_missing")
    else:
        try:
            matched = parse_diagnostic_icv(saved.icv) == evidence.icv
        except ValueError:
            issues.append("saved_icv_invalid")
        else:
            if not matched:
                issues.append("saved_icv_mismatch")
    if not saved.issuing_unit.strip():
        issues.append("saved_unit_missing")
    if saved.environment not in ("Sandbox", "Simulation", "Production"):
        issues.append("saved_environment_unknown")
    return tuple(issues)
