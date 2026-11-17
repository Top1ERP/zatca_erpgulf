"""Bounded lexical XML/QR readers shared by retained native and legacy views.

These helpers do not establish TLV validity, signatures, acceptance or file
provenance. They preserve historical text and never calculate a current clock.
"""

import base64
import binascii

from .artifact_evidence import NS, parse_diagnostic_xml
from .issue_timestamp import parse_issue_datetime


MAX_QR_BASE64_CHARS = 16 * 1024


class QRXMLContractError(ValueError):
    """Static codes only; no XML/QR/receipt/identity/parser representation."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _one(parent, xpath, code):
    nodes = parent.xpath(xpath, namespaces=NS)
    if len(nodes) != 1:
        raise QRXMLContractError(code)
    return nodes[0]


def _text(node, code, maximum):
    value = node.text
    if len(node) or type(value) is not str or not 0 < len(value) <= maximum or value != value.strip():
        raise QRXMLContractError(code)
    return value


def _clock(content):
    root = parse_diagnostic_xml(content)
    day = _text(_one(root, "./cbc:IssueDate", "qr_source_date"), "qr_source_date", 10)
    clock = _text(_one(root, "./cbc:IssueTime", "qr_source_time"), "qr_source_time", 32)
    # Validate without supplying a current timezone or normalizing historical text.
    parse_issue_datetime(day, clock)
    return day, clock


def _payload(content, *, maximum=MAX_QR_BASE64_CHARS):
    root = parse_diagnostic_xml(content)
    reference = _one(root, "./cac:AdditionalDocumentReference[cbc:ID='QR']", "qr_source_reference")
    if _text(_one(reference, "./cbc:ID", "qr_source_reference"), "qr_source_reference", 2) != "QR":
        raise QRXMLContractError("qr_source_reference")
    attachment = _one(reference, "./cac:Attachment", "qr_source_attachment")
    node = _one(attachment, "./cbc:EmbeddedDocumentBinaryObject", "qr_source_payload")
    payload = _text(node, "qr_source_payload", maximum)
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        invalid = True
    else:
        invalid = not decoded or base64.b64encode(decoded).decode("ascii") != payload
    if invalid:
        raise QRXMLContractError("qr_source_base64")
    # Base64 is a bounded lexical observation, NOT TLV/signature/QR validation.
    return payload, len(decoded)
