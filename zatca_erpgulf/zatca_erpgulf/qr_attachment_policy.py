"""Non-destructive ordinary QR reuse policy, not artifact authentication.

Preserve an already referenced same-invoice File URL. Never choose a newest,
first or official-prefix artifact as an implicit replacement. Read only bounded
metadata; no bytes, images, paths, ORM, filesystem, clock or authority access.
"""

from collections.abc import Mapping
from dataclasses import dataclass


MAX_FILE_OBSERVATIONS = 128
FILE_FIELDS = ("name", "file_name", "file_url", "attached_to_doctype", "attached_to_name", "attached_to_field")


class QRAttachmentPolicyError(ValueError):
    """Static code; never include file URLs, invoice names or row content."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class QRReuseDecision:
    """Internal operational decision, not a signature/QR/acceptance proof."""

    action: str
    reason: str


def _text(value, *, maximum, optional=False):
    if optional and value is None:
        return None
    if (
        type(value) is not str
        or len(value) > maximum
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise QRAttachmentPolicyError("qr_attachment_text")
    if not optional and not value:
        raise QRAttachmentPolicyError("qr_attachment_text")
    return value


def decide_qr_reuse(*, doctype, invoice_name, current_url, saved_status, rows):
    """Inspect a COMPLETE bounded invoice File projection, not URL existence.

    File ownership must match the caller's saved source identity. Filename
    prefixes only flag potential orphaned QR files for REVIEW, never prove that
    a file is authoritative. Duplicate rows for the current URL need no choice:
    preserving that reference neither deletes nor selects any individual row.
    """
    if type(doctype) is not str or doctype not in ("Sales Invoice", "POS Invoice"):
        raise QRAttachmentPolicyError("qr_attachment_doctype")
    _text(invoice_name, maximum=140)
    _text(current_url, maximum=2048, optional=True)
    _text(saved_status, maximum=140, optional=True)
    if type(rows) is not tuple:
        raise QRAttachmentPolicyError("qr_attachment_rows")
    if len(rows) > MAX_FILE_OBSERVATIONS:
        return QRReuseDecision("REVIEW", "qr_attachment_limit")
    matches_current, potential_orphans, identities = False, False, set()
    for row in rows:
        if not isinstance(row, Mapping) or any(name not in row for name in FILE_FIELDS):
            raise QRAttachmentPolicyError("qr_attachment_row")
        identity = _text(row["name"], maximum=140)
        if identity in identities:
            raise QRAttachmentPolicyError("qr_attachment_duplicate_row")
        identities.add(identity)
        _text(row["file_name"], maximum=255, optional=True)
        _text(row["file_url"], maximum=2048, optional=True)
        _text(row["attached_to_field"], maximum=140, optional=True)
        if row["attached_to_doctype"] != doctype or row["attached_to_name"] != invoice_name:
            raise QRAttachmentPolicyError("qr_attachment_owner")
        if current_url and row["file_url"] == current_url:
            matches_current = True
        if (
            row["attached_to_field"] == "ksa_einv_qr"
            or (row["file_name"] or "").upper().startswith(("QR-", "QR_"))
        ):
            potential_orphans = True
    if current_url:
        if matches_current:
            return QRReuseDecision("PRESERVE", "qr_current_owned")
        return QRReuseDecision("REVIEW", "qr_current_unresolved")
    if potential_orphans:
        return QRReuseDecision("REVIEW", "qr_unlinked_candidates")
    if (saved_status or "").upper() in ("REPORTED", "CLEARED"):
        return QRReuseDecision("REVIEW", "qr_phase2_status_without_link")
    return QRReuseDecision("GENERATE", "qr_no_stored_reference")
