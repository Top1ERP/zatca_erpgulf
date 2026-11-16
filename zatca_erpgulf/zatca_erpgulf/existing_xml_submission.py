"""One local review for existing-XML metadata mismatch, before transport.

Runtime and translation are injected from each caller's existing bindings. This
is not a permission check, authenticated source snapshot or receipt assessment.
"""

import frappe

from .existing_xml_binding import REVIEW, existing_xml_binding_issue
from .invoice_payload import read_invoice_payload


class ExistingXmlSubmissionError(frappe.ValidationError):
    """Bypass legacy API/wrapper failure writers; retain no XML or parser error."""

    def __init__(self, code):
        self.code = code
        self.diagnostic_logged = False
        super().__init__(REVIEW)

    def __str__(self):
        # Frappe may localize args for display; diagnostics stay canonical.
        return REVIEW


def read_bound_invoice_payload(uuid, invoice_hash, path, *, read_xml, runtime, translate):
    """Retain first-read exceptions; reject mismatching captured content once.

    The current authorization resolver still runs before this check in callers.
    The normal request dict uses exactly the checked Base64 observation. No local
    invoice/File/PIH/counter write is performed for this review.
    """
    payload = read_invoice_payload(uuid, invoice_hash, path, read_xml=read_xml)
    code = existing_xml_binding_issue(payload)
    if code is not None:
        error = ExistingXmlSubmissionError(code)
        runtime.log_error(title="ZATCA existing XML review", message=f"{code}: {REVIEW}")
        error.diagnostic_logged = True
        runtime.throw(translate(REVIEW), exc=error)
        raise error  # Preserve the failure if a replacement throw returns.
    return payload
