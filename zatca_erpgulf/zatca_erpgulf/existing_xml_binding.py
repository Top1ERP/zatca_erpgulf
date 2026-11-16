"""Compare request identity with that request's captured existing XML.

No hash recomputation, signature/QR/schema/receipt verification, source reload,
filesystem lookup or identity repair. Values are compared without normalization.
"""

import base64
import binascii

from lxml import etree


INVOICE = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"
UUID = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}UUID"
REFERENCE = "{http://www.w3.org/2000/09/xmldsig#}Reference"
DIGEST = "{http://www.w3.org/2000/09/xmldsig#}DigestValue"
REVIEW = "The existing invoice XML could not be matched to the request UUID and invoice hash. No request was sent. Review the XML source before trying again."


class _RejectExternalResources(etree.Resolver):
    def resolve(self, url, public_id, context):
        raise ValueError("external_xml_resource")


def existing_xml_binding_issue(payload):
    """Return a static issue code, or None for an exact metadata match.

    Keep the original Base64 in the request. Parse its decoded bytes with a fresh
    non-recovering parser, without entities, DTD loading or external resources.
    Placeholder/format/certificate validity remains outside this narrow check.
    """
    try:
        raw = base64.b64decode(payload.invoice_base64, validate=True)
        parser = etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True, recover=False,
        )
        parser.resolvers.add(_RejectExternalResources())
        root = etree.fromstring(raw, parser)
    except (ValueError, TypeError, binascii.Error, etree.LxmlError):
        return "existing_xml_unreadable"

    if root.getroottree().docinfo.doctype or any(
        isinstance(node, etree._Entity) for node in root.iter()
    ):
        return "existing_xml_doctype"
    if root.tag != INVOICE:
        return "existing_xml_root"
    uuids = root.findall(UUID)
    references = [node for node in root.iter(REFERENCE)
                  if node.get("Id") == "invoiceSignedData"]
    if len(uuids) != 1 or len(references) != 1:
        return "existing_xml_identity_ambiguous"
    digests = references[0].findall(DIGEST)
    if len(digests) != 1:
        return "existing_xml_identity_ambiguous"
    uuid, digest = uuids[0], digests[0]
    if any(len(node) or not (node.text or "").strip() for node in (uuid, digest)):
        return "existing_xml_identity_empty"
    if not isinstance(payload.uuid, str) or not isinstance(payload.invoice_hash, str):
        return "existing_xml_request_identity"
    if uuid.text != payload.uuid or digest.text != payload.invoice_hash:
        return "existing_xml_identity_changed"
    return None
