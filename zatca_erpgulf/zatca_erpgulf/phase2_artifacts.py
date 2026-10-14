"""Phase-2 hook preservation/review and legacy shared payload extraction.

The automatic hook never repairs artifacts from saved response text. Normal
Sales/POS signing/clearance adapters remain separate callers; their legacy XML
payload extractor below is deliberately unchanged in this bounded increment.
"""

import xml.etree.ElementTree as ET

import frappe
from frappe import _

from .qr_attachment_policy import (
    FILE_FIELDS, MAX_FILE_OBSERVATIONS, QRAttachmentPolicyError, decide_qr_recovery,
)


REVIEW_MESSAGE = "Stored Phase-2 artifacts require review. No file or invoice status was changed."


def _local_name(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _text(node):
    return (node.text or "").strip() if node is not None else ""


def _extract_qr_payload_from_xml(xml_bytes):
    root = ET.fromstring(xml_bytes)

    for adr in root.iter():
        if _local_name(adr.tag) != "AdditionalDocumentReference":
            continue

        adr_id = None
        for child in list(adr):
            if _local_name(child.tag) == "ID":
                adr_id = _text(child)
                break

        if adr_id != "QR":
            continue

        for node in adr.iter():
            if _local_name(node.tag) == "EmbeddedDocumentBinaryObject":
                payload = _text(node)
                if payload:
                    return payload

    return None


def assess_phase2_qr_reference(doc):
    """Internal metadata observation, not an artifact or acceptance capability.

    Parent hook authorization applies. No saved response, current credentials,
    File content or physical image is read. REVIEW is a diagnostic, not a reason
    to roll back an otherwise accepted invoice's parent transaction.
    """
    values = dict(doctype=doc.doctype, invoice_name=doc.name,
        current_url=doc.get("ksa_einv_qr"), saved_status=doc.get("custom_zatca_status"))
    try:
        # Validate source/link shape before using it in an ORM filter. No choice
        # is inferred from this empty projection; the scoped query follows.
        decide_qr_recovery(**values, rows=())
    except QRAttachmentPolicyError:
        action, reason = "REVIEW", "phase2_qr_metadata_invalid"
    else:
        rows = frappe.get_all("File",
            filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
            fields=list(FILE_FIELDS), order_by="name asc", limit_page_length=MAX_FILE_OBSERVATIONS + 1)
        if not isinstance(rows, (list, tuple)):
            action, reason = "REVIEW", "phase2_qr_metadata_invalid"
        else:
            try:
                decision = decide_qr_recovery(**values, rows=tuple(rows))
            except QRAttachmentPolicyError:
                action, reason = "REVIEW", "phase2_qr_metadata_invalid"
            else:
                action, reason = decision.action, decision.reason
    result = {"action": action, "reason": reason, "mutation_performed": False,
        "source_authenticated": False}
    if action == "REVIEW":
        result["message"] = _(REVIEW_MESSAGE)
    return result


def ensure_phase2_sales_invoice_artifacts(doc, event=None):
    """Observe/preserve Phase-2 references, never reconstruct or replace them.

    Keep the legacy event entry point and None return. Incomplete metadata does
    not raise a review exception, emit a modal, mutate status or take ownership
    of a parent's transaction. A future authenticated artifact service must own
    any actual repair; a saved status/response is not that authority.
    """
    if getattr(doc, "doctype", None) != "Sales Invoice":
        return

    if int(getattr(doc, "docstatus", 0) or 0) != 1:
        return

    status = doc.get("custom_zatca_status") or ""
    if type(status) is not str or status.upper() not in {"CLEARED", "REPORTED"}:
        return
    assess_phase2_qr_reference(doc)
