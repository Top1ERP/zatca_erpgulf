"""Local QR recovery/regeneration for submitted Sales Invoices.

This module never calls ZATCA. It repairs an unlinked existing QR attachment,
or rebuilds one from the stored Phase-1 invoice values / Phase-2 XML artifact.
Saved-row access is checked before artifact use, content reads or writes.
Legacy artifact selection and transaction ownership still need separate review.
"""

from collections.abc import Mapping
import io

import frappe
import pyqrcode
from frappe import _
from frappe.permissions import has_permission
from frappe.utils.file_manager import get_file_path, save_file

from .create_qr import create_qr_code
from .phase2_artifacts import _extract_qr_payload_from_xml
from .permission_compat import saved_row_has_permission
from .qr_attachment_policy import FILE_FIELDS, MAX_FILE_OBSERVATIONS
from .zatca_runtime import PHASE_2_VALUE, is_zatca_invoice_enabled, resolve_zatca_phase


DENIED_MESSAGE = "You do not have permission to inspect or regenerate this invoice QR code."
ATTACHMENT_FIELDS = (*FILE_FIELDS, "creation")


def _valid_name(value):
    return (type(value) is str and 0 < len(value) <= 140 and value == value.strip()
        and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _deny():
    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)


def _actor():
    user = getattr(frappe.session, "user", None)
    if not _valid_name(user) or user == "Guest":
        _deny()
    return user


def _same_actor(user):
    if _actor() != user:
        _deny()


def _saved(doctype, name, user, *, write=False):
    """Load exact saved rows, never request-supplied documents/permission flags.

    Direct quiet permission-engine checks avoid Document.ignore_permissions and
    select the inspected v15/v16 signature without retry. Missing/mismatched
    identities, ACL faults and false-like results share one redacted denial.
    """
    _same_actor(user)
    if not _valid_name(name):
        _deny()
    try:
        doc = frappe.get_doc(doctype, name)
        allowed = doc.doctype == doctype and doc.name == name
        for operation in (("read", "write") if write else ("read",)):
            if not allowed:
                break
            allowed = saved_row_has_permission(has_permission, doctype, operation, doc=doc, user=user)
            _same_actor(user)
    except Exception:
        allowed = False
    _same_actor(user)
    if not allowed:
        _deny()  # Outside the handler: no private loader/ACL error context.
    return doc


def _context(name, *, write=False):
    user = _actor()
    doc = _saved("Sales Invoice", name, user, write=write)
    # Do not reuse a cached Company document as the authorization subject.
    company = _saved("Company", doc.get("company"), user)
    return doc, company, user


def _owned_file(doc, row, user, *, write=False):
    if not isinstance(row, Mapping) or any(field not in row for field in ATTACHMENT_FIELDS):
        _deny()
    saved = _saved("File", row["name"], user, write=write)
    if (saved.get("attached_to_doctype") != doc.doctype or saved.get("attached_to_name") != doc.name
            or any(saved.get(field) != row[field] for field in ATTACHMENT_FIELDS)):
        _deny()
    return saved


def _attached_qr_files(doc, user):
    _same_actor(user)
    rows = frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Sales Invoice", "attached_to_name": doc.name},
        fields=list(ATTACHMENT_FIELDS),
        order_by="creation desc",
        limit_page_length=MAX_FILE_OBSERVATIONS + 1,
    )
    if not isinstance(rows, (tuple, list)) or len(rows) > MAX_FILE_OBSERVATIONS:
        _deny()
    # Fail closed, do not silently filter an unreadable candidate then choose a
    # different artifact. This bounded projection is NOT an authority ranking.
    for row in rows:
        _owned_file(doc, row, user)
    _same_actor(user)
    return rows


def _is_qr_name(file_name):
    name = str(file_name or "").upper()
    return name.startswith("QR-") or name.startswith("QR_") or "QR" in name


def _set_qr_link(doc, file_doc, user):
    saved = _saved("File", file_doc.name, user, write=True)
    if (saved.get("attached_to_doctype") != doc.doctype or saved.get("attached_to_name") != doc.name
            or saved.get("file_url") != file_doc.file_url):
        _deny()
    file_doc = saved
    file_doc.attached_to_field = "ksa_einv_qr"
    file_doc.save(ignore_permissions=True)
    _same_actor(user)
    frappe.db.set_value("Sales Invoice", doc.name, "ksa_einv_qr", file_doc.file_url, update_modified=False)
    return file_doc.file_url


def _phase2_payload(doc, user):
    rows = _attached_qr_files(doc, user)
    for row in rows:
        name = str(row.file_name or "").upper()
        if "XML" not in name:
            continue
        # Keep access denial OUTSIDE the legacy parser's exception fallback.
        _owned_file(doc, row, user)
        try:
            content = get_file_path(row.file_url)
            with open(content, "rb") as handle:
                payload = _extract_qr_payload_from_xml(handle.read())
        except Exception:
            payload = None
        _same_actor(user)
        if payload:
            return payload, row.file_name
    return None, None


def _attach_payload(doc, payload, prefix, user):
    image = io.BytesIO()
    pyqrcode.create(payload, error="L").png(image, scale=4, quiet_zone=4)
    file_name = f"{prefix}-{doc.name}.png"
    file_doc = save_file(file_name, image.getvalue(), "Sales Invoice", doc.name, is_private=0)
    return _set_qr_link(doc, file_doc, user)


@frappe.whitelist()
def get_qr_regeneration_state(invoice_number):
    doc, company, user = _context(invoice_number)
    state = _regeneration_state(doc, company, user)
    _same_actor(user)
    return state


def _regeneration_state(doc, company, user):
    """Internal preview using the already authorized saved context, not a reload."""
    if int(doc.docstatus or 0) != 1:
        return {"eligible": False, "reason": _("The invoice must be submitted first.")}
    if not is_zatca_invoice_enabled(company):
        return {"eligible": False, "reason": _("ZATCA E-Invoicing is disabled for this Company.")}
    if not doc.posting_date or not doc.posting_time or not company.get("tax_id"):
        return {"eligible": False, "reason": _("Invoice date, time, and Company Tax ID are required.")}
    # Legacy eligibility remains separate from authorization/provenance. These
    # filename/link hints do not prove a QR is safe to repair or replace.
    existing_qr = doc.get("ksa_einv_qr")
    files = _attached_qr_files(doc, user)
    attached_qr = any(_is_qr_name(row.file_name) for row in files)
    # Global URL existence is not a same-invoice access/ownership observation.
    if (existing_qr and any(row.file_url == existing_qr for row in files)) or attached_qr:
        return {"eligible": True}
    phase1_generated = str(doc.get("custom_zatca_status") or "").upper().startswith("PHASE-1")
    if resolve_zatca_phase(company) == PHASE_2_VALUE and not phase1_generated:
        payload, _xml_name = _phase2_payload(doc, user)
        if not payload:
            return {"eligible": False, "reason": _("A stored signed ZATCA XML/QR payload is required for Phase-2 regeneration.")}
    return {"eligible": True}


@frappe.whitelist(methods=["POST"])
def regenerate_qr(invoice_number):
    """Repair or regenerate the invoice QR locally; never submit to ZATCA."""
    doc, company, user = _context(invoice_number, write=True)
    state = _regeneration_state(doc, company, user)
    _same_actor(user)
    if not state.get("eligible"):
        frappe.throw(state.get("reason") or _("This invoice cannot generate a QR code."))

    files = [row for row in _attached_qr_files(doc, user) if _is_qr_name(row.file_name)]
    if files:
        file_doc = _owned_file(doc, files[0], user, write=True)
        url = _set_qr_link(doc, file_doc, user)
        _same_actor(user)
        frappe.db.commit()
        return {"status": "relinked", "file_url": url, "message": _("Existing QR code was linked back to the invoice.")}

    phase1_generated = str(doc.get("custom_zatca_status") or "").upper().startswith("PHASE-1")
    if resolve_zatca_phase(company) == PHASE_2_VALUE and not phase1_generated:
        payload, xml_name = _phase2_payload(doc, user)
        prefix = "QR-Phase2-CLEARED" if "CLEARED" in str(xml_name).upper() else "QR-Phase2-REPORTED"
        url = _attach_payload(doc, payload, prefix, user)
    else:
        frappe.db.set_value("Sales Invoice", doc.name, "ksa_einv_qr", None, update_modified=False)
        doc.ksa_einv_qr = None
        create_qr_code(doc)
        url = doc.get("ksa_einv_qr")
    _same_actor(user)
    frappe.db.commit()
    return {"status": "generated", "file_url": url, "message": _("QR code was regenerated locally.")}
