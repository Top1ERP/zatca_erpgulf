"""Local QR recovery/regeneration for submitted Sales Invoices.

This module never calls ZATCA. It repairs an unlinked existing QR attachment,
or rebuilds one from the stored Phase-1 invoice values / Phase-2 XML artifact.
"""

import base64
import io

import frappe
import pyqrcode
from frappe import _
from frappe.utils.file_manager import get_file_path, save_file

from .create_qr import create_qr_code
from .phase2_artifacts import _extract_qr_payload_from_xml
from .zatca_runtime import PHASE_2_VALUE, is_zatca_invoice_enabled, resolve_zatca_phase


def _invoice(name):
    return frappe.get_doc("Sales Invoice", name)


def _attached_qr_files(doc):
    return frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Sales Invoice", "attached_to_name": doc.name},
        fields=["name", "file_name", "file_url", "attached_to_field", "creation"],
        order_by="creation desc",
    )


def _is_qr_name(file_name):
    name = str(file_name or "").upper()
    return name.startswith("QR-") or name.startswith("QR_") or "QR" in name


def _set_qr_link(doc, file_doc):
    file_doc.attached_to_field = "ksa_einv_qr"
    file_doc.save(ignore_permissions=True)
    frappe.db.set_value("Sales Invoice", doc.name, "ksa_einv_qr", file_doc.file_url, update_modified=False)
    return file_doc.file_url


def _phase2_payload(doc):
    rows = frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Sales Invoice", "attached_to_name": doc.name},
        fields=["file_url", "file_name"],
        order_by="creation desc",
    )
    for row in rows:
        name = str(row.file_name or "").upper()
        if "XML" not in name:
            continue
        try:
            content = get_file_path(row.file_url)
            with open(content, "rb") as handle:
                payload = _extract_qr_payload_from_xml(handle.read())
            if payload:
                return payload, row.file_name
        except Exception:
            continue
    return None, None


def _attach_payload(doc, payload, prefix):
    image = io.BytesIO()
    pyqrcode.create(payload, error="L").png(image, scale=4, quiet_zone=4)
    file_name = f"{prefix}-{doc.name}.png"
    file_doc = save_file(file_name, image.getvalue(), "Sales Invoice", doc.name, is_private=0)
    return _set_qr_link(doc, file_doc)


@frappe.whitelist()
def get_qr_regeneration_state(invoice_number):
    doc = _invoice(invoice_number)
    if int(doc.docstatus or 0) != 1:
        return {"eligible": False, "reason": _("The invoice must be submitted first.")}
    company = frappe.get_cached_doc("Company", doc.company)
    if not is_zatca_invoice_enabled(company):
        return {"eligible": False, "reason": _("ZATCA E-Invoicing is disabled for this Company.")}
    if not doc.posting_date or not doc.posting_time or not company.get("tax_id"):
        return {"eligible": False, "reason": _("Invoice date, time, and Company Tax ID are required.")}
    # An existing QR can always be repaired or relinked, even when a Phase-2
    # invoice was generated during Phase-1 and has no signed XML artifact.
    existing_qr = doc.get("ksa_einv_qr")
    attached_qr = any(_is_qr_name(row.file_name) for row in _attached_qr_files(doc))
    if (existing_qr and frappe.db.exists("File", {"file_url": existing_qr})) or attached_qr:
        return {"eligible": True}
    phase1_generated = str(doc.get("custom_zatca_status") or "").upper().startswith("PHASE-1")
    if resolve_zatca_phase(company) == PHASE_2_VALUE and not phase1_generated:
        payload, _xml_name = _phase2_payload(doc)
        if not payload:
            return {"eligible": False, "reason": _("A stored signed ZATCA XML/QR payload is required for Phase-2 regeneration.")}
    return {"eligible": True}


@frappe.whitelist()
def regenerate_qr(invoice_number):
    """Repair or regenerate the invoice QR locally; never submit to ZATCA."""
    doc = _invoice(invoice_number)
    state = get_qr_regeneration_state(invoice_number)
    if not state.get("eligible"):
        frappe.throw(state.get("reason") or _("This invoice cannot generate a QR code."))

    files = [row for row in _attached_qr_files(doc) if _is_qr_name(row.file_name)]
    if files:
        file_doc = frappe.get_doc("File", files[0].name)
        url = _set_qr_link(doc, file_doc)
        frappe.db.commit()
        return {"status": "relinked", "file_url": url, "message": _("Existing QR code was linked back to the invoice.")}

    company = frappe.get_cached_doc("Company", doc.company)
    phase1_generated = str(doc.get("custom_zatca_status") or "").upper().startswith("PHASE-1")
    if resolve_zatca_phase(company) == PHASE_2_VALUE and not phase1_generated:
        payload, xml_name = _phase2_payload(doc)
        prefix = "QR-Phase2-CLEARED" if "CLEARED" in str(xml_name).upper() else "QR-Phase2-REPORTED"
        url = _attach_payload(doc, payload, prefix)
    else:
        frappe.db.set_value("Sales Invoice", doc.name, "ksa_einv_qr", None, update_modified=False)
        doc.ksa_einv_qr = None
        create_qr_code(doc)
        url = doc.get("ksa_einv_qr")
    frappe.db.commit()
    return {"status": "generated", "file_url": url, "message": _("QR code was regenerated locally.")}
