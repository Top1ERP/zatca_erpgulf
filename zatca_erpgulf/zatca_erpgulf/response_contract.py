"""Shared bounded response fields; no transport, persistence or acceptance grant.

These readers are reused by native dispatch and the earlier local assessment
model. Original messages stay in the encrypted receipt; display translation is
outside this parsing boundary.
"""

import base64
import binascii

from .artifact_evidence import MAX_XML_BYTES, ArtifactEvidenceError

REPORTING = "invoices/reporting/single"
CLEARANCE = "invoices/clearance/single"

def _validation(body):
    """Return declared validation status, warning count and structural issues.

    Diagnostic messages stay in the protected receipt, not another mutable DTO.
    Optional entry fields, when present, must agree with their message category.
    """
    validation = body.get("validationResults")
    if type(validation) is not dict:
        return None, 0, ("response_validation_missing",)
    status = validation.get("status")
    issues, counts = [], {}
    if status not in ("PASS", "WARNING", "ERROR"):
        issues.append("response_validation_status")
    for name, kind, entry_status in (
        ("infoMessages", "INFO", "PASS"),
        ("warningMessages", "WARNING", "WARNING"),
        ("errorMessages", "ERROR", "ERROR"),
    ):
        entries = validation.get(name, [] if name != "errorMessages" else None)
        if type(entries) is not list or any(type(entry) is not dict for entry in entries):
            issues.append("response_validation_messages")
            continue
        counts[name] = len(entries)
        for entry in entries:
            if (
                entry.get("type", kind) != kind
                or entry.get("status", entry_status) != entry_status
                or any(type(entry[key]) is not str for key in ("code", "category", "message") if key in entry)
            ):
                issues.append("response_validation_messages")
    errors, warnings = counts.get("errorMessages", 0), counts.get("warningMessages", 0)
    if (status in ("PASS", "WARNING") and errors) or (status == "ERROR" and not errors):
        issues.append("response_validation_contradiction")
    return status, warnings, tuple(dict.fromkeys(issues))

def _outcome_issues(body, endpoint):
    reported, cleared = body.get("reportingStatus"), body.get("clearanceStatus")
    issues = []
    if reported not in (None, "REPORTED", "NOT_REPORTED") or cleared not in (None, "CLEARED", "NOT_CLEARED"):
        issues.append("response_outcome_unknown")
    if reported == "REPORTED" and cleared == "CLEARED":
        issues.append("response_outcome_ambiguous")
    if (endpoint == REPORTING and cleared is not None) or (endpoint == CLEARANCE and reported is not None):
        issues.append("response_operation_mismatch")
    return tuple(issues)

def _returned_xml(value, *, max_xml_bytes=MAX_XML_BYTES):
    """Bound strict Base64 with ASCII whitespace only; preserve decoded bytes."""
    if type(value) is not str or not value:
        raise ArtifactEvidenceError("response_xml_type")
    compact = value.translate(str.maketrans("", "", " \t\r\n"))
    if len(compact) > 4 * ((max_xml_bytes + 2) // 3):
        raise ArtifactEvidenceError("response_xml_size")
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error):
        raise ArtifactEvidenceError("response_xml_base64") from None
    if not decoded or len(decoded) > max_xml_bytes:
        raise ArtifactEvidenceError("response_xml_size")
    return decoded
