"""Shared XML fragments with no ERP reads, identity allocation or side effects.

These helpers preserve the legacy element order and placeholder QR. The signing
pipeline must still replace that placeholder before producing a final artifact.
An absent previous hash is never evidence that this is a new issuing chain.
"""

import base64
import hashlib
import xml.etree.ElementTree as ET

from zatca_erpgulf.zatca_erpgulf.compliance_types import compliance_document_type


MISSING_PREVIOUS_HASH = (
    "The selected ZATCA issuing unit has no previous invoice hash. Review chain "
    "initialization or restore its verified history before generating XML. "
    "An empty field does not authorize starting or resetting a chain."
)
QR_PLACEHOLDER = "GsiuvGjvchjbFhibcDhjv1886G"
# BR-KSA-26, XML Implementation Standard v1.2, page 54: encode the
# hexadecimal SHA-256 representation of the ASCII character zero, not an
# empty string, the raw zero character, or the 32-byte binary digest.
INITIAL_PREVIOUS_HASH = base64.b64encode(hashlib.sha256(b"0").hexdigest().encode("ascii")).decode("ascii")


def previous_hash_value(value):
    """Require a configured hash without normalizing or inventing its bytes.

    This is a presence boundary, not hash-format or chain-provenance validation.
    Initial-chain policy and historic continuity need separate verified evidence.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(MISSING_PREVIOUS_HASH)
    return value


def append_invoice_metadata(invoice, document_id, invoice_uuid, issue_timestamp):
    """Append already-selected identity/time, retaining both adapters' ordering.

    Callers resolve and validate time and identity before invoking this builder.
    They retain ownership of live UUID persistence and non-production isolation.
    """
    issue_date, issue_time = issue_timestamp.split("T", 1)
    for tag, value in (
        ("ProfileID", "reporting:1.0"), ("ID", str(document_id)),
        ("UUID", invoice_uuid), ("IssueDate", issue_date), ("IssueTime", issue_time),
    ):
        ET.SubElement(invoice, "cbc:" + tag).text = value
    return invoice


def append_compliance_type(invoice, compliance_type):
    """Use the same six-type sample contract as automatic onboarding.

    Reject an invalid sample selector before appending any XML. This helper is
    deliberately not an ordinary invoice-type or advance-payment type resolver.
    """
    spec = compliance_document_type(compliance_type)
    element = ET.SubElement(invoice, "cbc:InvoiceTypeCode", name=spec.type_name)
    element.text = spec.document_code
    return invoice


def append_additional_references(invoice, previous_hash):
    """Append shared PIH/QR/signature references without reading or moving PIH."""
    previous_hash = previous_hash_value(previous_hash)
    for reference_id, content in (("PIH", previous_hash), ("QR", QR_PLACEHOLDER)):
        reference = ET.SubElement(invoice, "cac:AdditionalDocumentReference")
        ET.SubElement(reference, "cbc:ID").text = reference_id
        attachment = ET.SubElement(reference, "cac:Attachment")
        ET.SubElement(
            attachment, "cbc:EmbeddedDocumentBinaryObject", mimeCode="text/plain",
        ).text = content
    signature = ET.SubElement(invoice, "cac:Signature")
    ET.SubElement(signature, "cbc:ID").text = "urn:oasis:names:specification:ubl:signature:Invoice"
    ET.SubElement(signature, "cbc:SignatureMethod").text = "urn:oasis:names:specification:ubl:dsig:enveloped:xades"
    return invoice
