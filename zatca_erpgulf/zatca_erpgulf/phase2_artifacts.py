import base64
import io
import json
import xml.etree.ElementTree as ET

import frappe
import pyqrcode
from frappe.utils.file_manager import save_file


def _local_name(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _text(node):
    return (node.text or "").strip() if node is not None else ""


def _extract_response_json(full_response):
    raw = full_response or ""
    start = raw.find("{")
    if start < 0:
        return None

    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
        return obj
    except Exception:
        return None


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


def _remove_stale_qr_files(doc, keep_prefix: str) -> None:
    """Keep one authoritative Phase-2 QR attachment per Sales Invoice."""
    rows = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Sales Invoice",
            "attached_to_name": doc.name,
            "attached_to_field": "ksa_einv_qr",
        },
        fields=["name", "file_name"],
    )
    for row in rows:
        if not str(row.file_name or "").startswith(keep_prefix):
            frappe.delete_doc("File", row.name, ignore_permissions=True)


def _save_attached_file_once(file_name, content, doctype, docname, attached_to_field, is_private):
    """Save an attached file only once.

    Frappe may append a random suffix/hash to file_name when saving files.
    Therefore, we search by invoice-specific filename prefix instead of exact file_name.
    """
    if "." in file_name:
        file_prefix = file_name.rsplit(".", 1)[0]
    else:
        file_prefix = file_name

    existing = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": doctype,
            "attached_to_name": docname,
            "attached_to_field": attached_to_field,
            "file_name": ["like", file_prefix + "%"],
        },
        fields=["name", "file_url", "attached_to_field", "creation"],
        order_by="creation asc",
        limit=1,
    )

    if existing:
        file_doc = frappe.get_doc("File", existing[0].name)

        if file_doc.attached_to_field != attached_to_field:
            file_doc.attached_to_field = attached_to_field
            file_doc.save(ignore_permissions=True)

        return file_doc.file_url

    file_doc = save_file(
        file_name,
        content,
        doctype,
        docname,
        is_private=is_private,
    )
    file_doc.attached_to_field = attached_to_field
    file_doc.save(ignore_permissions=True)

    return file_doc.file_url


def ensure_phase2_sales_invoice_artifacts(doc, event=None):
    """Attach Phase-2 ZATCA XML/QR artifacts for cleared/reported Sales Invoices.

    This function must not submit/retry the invoice to ZATCA.
    It only persists local artifacts from the already-stored ZATCA response.
    """
    if getattr(doc, "doctype", None) != "Sales Invoice":
        return

    if int(getattr(doc, "docstatus", 0) or 0) != 1:
        return

    status = (doc.get("custom_zatca_status") or "").upper()

    if status not in {"CLEARED", "REPORTED"}:
        return

    full_response = doc.get("custom_zatca_full_response") or ""
    response_obj = _extract_response_json(full_response)

    if not response_obj:
        return

    cleared_invoice_b64 = response_obj.get("clearedInvoice")
    reported_invoice_b64 = response_obj.get("reportedInvoice")

    invoice_b64 = cleared_invoice_b64 or reported_invoice_b64

    if not invoice_b64:
        return

    xml_bytes = base64.b64decode(invoice_b64)

    if cleared_invoice_b64:
        xml_file_name = f"ZATCA-CLEARED-{doc.name}.xml"
    else:
        xml_file_name = f"ZATCA-REPORTED-{doc.name}.xml"

    xml_url = _save_attached_file_once(
        xml_file_name,
        xml_bytes,
        "Sales Invoice",
        doc.name,
        "custom_zatca_xml_file",
        is_private=1,
    )

    qr_payload = _extract_qr_payload_from_xml(xml_bytes)

    if not qr_payload:
        # Do not downgrade status. Just leave evidence incomplete.
        return

    qr_png = io.BytesIO()
    pyqrcode.create(qr_payload, error="L").png(qr_png, scale=4, quiet_zone=1)

    qr_prefix = "QR-Phase2-CLEARED" if cleared_invoice_b64 else "QR-Phase2-REPORTED"
    qr_file_name = f"{qr_prefix}-{doc.name}.png"
    _remove_stale_qr_files(doc, qr_prefix)

    qr_url = _save_attached_file_once(
        qr_file_name,
        qr_png.getvalue(),
        "Sales Invoice",
        doc.name,
        "ksa_einv_qr",
        is_private=0,
    )

    updates = {}

    if doc.meta.has_field("ksa_einv_qr") and doc.get("ksa_einv_qr") != qr_url:
        updates["ksa_einv_qr"] = qr_url

    # Preserve authoritative status. Never downgrade CLEARED/REPORTED to Phase-1.
    if cleared_invoice_b64 and status != "CLEARED":
        updates["custom_zatca_status"] = "CLEARED"
    elif reported_invoice_b64 and status != "REPORTED":
        updates["custom_zatca_status"] = "REPORTED"

    if updates:
        frappe.db.set_value(
            "Sales Invoice",
            doc.name,
            updates,
            update_modified=False,
        )
