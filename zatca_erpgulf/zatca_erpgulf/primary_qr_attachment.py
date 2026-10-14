"""Read-only ownership preflight for primary Sales/POS QR attachment.

Not a public endpoint, recovery provider, receipt validator or permission grant.
The authorized parent supplies the loaded invoice; saved-source/epoch binding
and concurrency control remain the submission service's responsibility.
"""

import frappe
from frappe import _

from .create_qr import MISSING_QR_FIELD, QR_REVIEW_REQUIRED
from .qr_attachment_policy import (
    FILE_FIELDS, MAX_FILE_OBSERVATIONS, QRAttachmentPolicyError, decide_qr_reuse,
)


def require_primary_qr_attachment(doc, *, expected_doctype=None):
    """Allow first attachment or preserve a scoped current link; reject ambiguity.

    Run before the primary API's try/error-persistence boundary, then recheck at
    attachment. This is NOT a reservation: a concurrent change after preflight
    can still fail after a request. The caller must eventually own that outcome.

    Unlike historical regeneration, a primary call already supplies a payload.
    Do not infer permission to generate, or validity, from saved status: clearance
    may already have staged CLEARED before the first QR attachment. Absence of a
    reference is only an attachment observation, never authenticated issuance.
    """
    if not hasattr(doc, "ksa_einv_qr"):
        frappe.throw(_(MISSING_QR_FIELD))
    values = dict(doctype=doc.doctype, invoice_name=doc.name,
        current_url=doc.get("ksa_einv_qr"), saved_status=None)
    invalid = expected_doctype is not None and values["doctype"] != expected_doctype
    if not invalid:
        try:
            # Validate source/link shapes before using them as ORM filters.
            decide_qr_reuse(**values, rows=())
        except QRAttachmentPolicyError:
            invalid = True
    if not invalid:
        rows = frappe.get_all("File", filters={"attached_to_doctype": values["doctype"],
            "attached_to_name": values["invoice_name"]}, fields=list(FILE_FIELDS),
            order_by="name asc", limit_page_length=MAX_FILE_OBSERVATIONS + 1)
        if type(rows) not in (list, tuple):
            invalid = True
        else:
            try:
                decision = decide_qr_reuse(**values, rows=tuple(rows))
            except QRAttachmentPolicyError:
                invalid = True
            else:
                invalid = decision.action == "REVIEW"
    if invalid:
        # Outside exception handlers: no raw row, private URL or chained cause.
        frappe.throw(_(QR_REVIEW_REQUIRED))
    return decision
