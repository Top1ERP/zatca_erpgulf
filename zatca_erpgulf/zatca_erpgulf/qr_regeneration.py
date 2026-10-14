"""Permissioned QR preservation/review, not speculative artifact reconstruction.

Public names remain compatible. No file content reads, relinking, generation,
invoice/File writes or transaction ownership. Missing originals require a future
authenticated artifact provider, never filename/date/status or current settings.
"""

from collections.abc import Mapping

import frappe
from frappe import _
from frappe.permissions import has_permission

from .permission_compat import saved_row_has_permission
from .qr_attachment_policy import (
    FILE_FIELDS, MAX_FILE_OBSERVATIONS, QRAttachmentPolicyError, decide_qr_recovery,
)
from .zatca_runtime import is_zatca_invoice_enabled


DENIED_MESSAGE = "You do not have permission to inspect or regenerate this invoice QR code."
ATTACHMENT_FIELDS = FILE_FIELDS
REVIEW_MESSAGE = "QR recovery requires a verified original artifact. No QR file was changed."
PRESERVED_MESSAGE = "The existing invoice QR reference was preserved. No file was changed."


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


def _owned_file(doc, row, user):
    if not isinstance(row, Mapping) or any(field not in row for field in ATTACHMENT_FIELDS):
        _deny()
    saved = _saved("File", row["name"], user)
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
        order_by="name asc",
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


@frappe.whitelist()
def get_qr_regeneration_state(invoice_number):
    doc, company, user = _context(invoice_number)
    state = _regeneration_state(doc, company, user)
    _same_actor(user)
    return state


def _regeneration_state(doc, company, user):
    """No current time/Tax ID/phase can prove a historical artifact's origin."""
    if int(doc.docstatus or 0) != 1:
        return {"eligible": False, "action": "UNAVAILABLE", "reason": _("The invoice must be submitted first.")}
    if not is_zatca_invoice_enabled(company):
        return {"eligible": False, "action": "UNAVAILABLE", "reason": _("ZATCA E-Invoicing is disabled for this Company.")}
    files = _attached_qr_files(doc, user)
    try:
        decision = decide_qr_recovery(doctype=doc.doctype, invoice_name=doc.name,
            current_url=doc.get("ksa_einv_qr"), saved_status=doc.get("custom_zatca_status"), rows=tuple(files))
    except QRAttachmentPolicyError:
        action = "REVIEW"
    else:
        action = decision.action
    # No verified artifact provider is installed at this button. Do not expose
    # a generation action or treat a preserved link as authenticated QR content.
    return {"eligible": False, "action": action,
        "reason": _(PRESERVED_MESSAGE if action == "PRESERVE" else REVIEW_MESSAGE)}


@frappe.whitelist(methods=["POST"])
def regenerate_qr(invoice_number):
    """Idempotently preserve or require review; never reconstruct a missing QR.

    Keep the existing Invoice write boundary on this POST action. No File write
    is needed because this implementation cannot change any stored attachment.
    """
    doc, company, user = _context(invoice_number, write=True)
    state = _regeneration_state(doc, company, user)
    _same_actor(user)
    if state.get("action") != "PRESERVE":
        frappe.throw(state.get("reason") or _(REVIEW_MESSAGE))
    return {"status": "preserved", "file_url": doc.get("ksa_einv_qr"), "message": _(PRESERVED_MESSAGE)}
