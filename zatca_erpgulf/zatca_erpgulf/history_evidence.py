"""Stored response/counter observations, never submission or migration authority.

Do not reuse these diagnostics as an HTTP acceptance contract. Historical text
does not independently establish the endpoint, HTTP result, or credential epoch.
"""

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass, field

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import (
    MAX_XML_BYTES, ArtifactEvidenceError, parse_diagnostic_icv,
)
from zatca_erpgulf.zatca_erpgulf.response_json import MAX_RESPONSE_BYTES, response_decoder


RESPONSE_LABELS = (
    "ZATCA Response:", "استجابة هيئة الزكاة والضريبة والجمارك (ZATCA):",
)
DISPLAY_SPACING = re.compile(r"(?:\s|<br\s*/?>)*", flags=re.IGNORECASE)


@dataclass(frozen=True)
class ResponseObservation:
    format: str
    outcome: str
    issues: tuple
    text_sha256: str = ""
    byte_length: int = 0
    # XML is handed to the same bounded inspector, never printed in a report.
    xml_candidates: tuple = field(default=(), repr=False)


def _response_object(text):
    """Parse one object or a known legacy display wrapper, not arbitrary JSON."""
    value = text.strip()
    source_format = "JSON"
    if not value.startswith(("{", "[")):
        matches = [(label, value.count(label)) for label in RESPONSE_LABELS]
        if sum(count for _, count in matches) != 1:
            raise ArtifactEvidenceError("response_wrapper")
        label = next(label for label, count in matches if count)
        prefix, value = value.split(label, 1)
        if any(c in prefix for c in "{}[]"):
            raise ArtifactEvidenceError("response_wrapper")
        value = value[DISPLAY_SPACING.match(value).end():]
        source_format = "LEGACY_DISPLAY"
    decoder = response_decoder()
    try:
        body, end = decoder.raw_decode(value)
    except (json.JSONDecodeError, RecursionError):
        raise ArtifactEvidenceError("response_json") from None
    if not isinstance(body, dict):
        raise ArtifactEvidenceError("response_object")
    if not DISPLAY_SPACING.fullmatch(value[end:]):
        raise ArtifactEvidenceError("response_trailing_data")
    return body, source_format


def _response_xml(value):
    if not isinstance(value, str) or not value.strip():
        raise ArtifactEvidenceError("response_xml_type")
    compact = "".join(value.split())
    if len(compact) > 4 * ((MAX_XML_BYTES + 2) // 3):
        raise ArtifactEvidenceError("response_xml_size")
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error):
        raise ArtifactEvidenceError("response_xml_base64") from None
    if not decoded or len(decoded) > MAX_XML_BYTES:
        raise ArtifactEvidenceError("response_xml_size")
    return decoded


def inspect_stored_response(value, saved_status):
    """Observe declared outcomes and decoded XML without trusting display labels."""
    if value is None or value == "":
        return ResponseObservation("MISSING", "UNCONFIRMED", ("response_missing",))
    if isinstance(value, bytes):
        if len(value) > MAX_RESPONSE_BYTES:
            return ResponseObservation("INVALID", "UNCONFIRMED", ("response_size",))
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return ResponseObservation("INVALID", "UNCONFIRMED", ("response_encoding",))
    elif isinstance(value, str):
        text = value
    else:
        return ResponseObservation("INVALID", "UNCONFIRMED", ("response_type",))
    # Check characters first to avoid encoding an unbounded field.
    if len(text) > MAX_RESPONSE_BYTES:
        return ResponseObservation("INVALID", "UNCONFIRMED", ("response_size",))
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return ResponseObservation("INVALID", "UNCONFIRMED", ("response_encoding",))
    if len(raw) > MAX_RESPONSE_BYTES:
        return ResponseObservation("INVALID", "UNCONFIRMED", ("response_size",))
    fingerprint, size = hashlib.sha256(raw).hexdigest(), len(raw)
    if text.strip().lower() in ("", "not submitted", "not submitted."):
        return ResponseObservation("MISSING", "UNCONFIRMED", ("response_missing",), fingerprint, size)
    try:
        body, source_format = _response_object(text)
    except ArtifactEvidenceError as exc:
        return ResponseObservation("INVALID", "UNCONFIRMED", (exc.code,), fingerprint, size)

    issues, xml = [], []
    validation = body.get("validationResults")
    valid = isinstance(validation, dict)
    errors = validation.get("errorMessages") if valid else None
    error_list = isinstance(errors, list) and all(isinstance(error, dict) for error in errors)
    other_lists_valid = valid and all(
        name not in validation or (
            isinstance(validation[name], list)
            and all(isinstance(entry, dict) for entry in validation[name])
        ) for name in ("infoMessages", "warningMessages")
    )
    validated = (
        valid and validation.get("status") in ("PASS", "WARNING")
        and error_list and not errors and other_lists_valid
    )
    rejected = valid and validation.get("status") == "ERROR" and error_list and bool(errors)
    reporting_status, clearance_status = body.get("reportingStatus"), body.get("clearanceStatus")
    known_outcomes = (
        reporting_status in (None, "REPORTED", "NOT_REPORTED")
        and clearance_status in (None, "CLEARED", "NOT_CLEARED")
    )
    reported, cleared = reporting_status == "REPORTED", clearance_status == "CLEARED"
    outcome = "UNCONFIRMED"
    if not known_outcomes:
        issues.append("response_outcome_unknown")
    elif reported and cleared:
        issues.append("response_outcome_ambiguous")
    elif validated and (reported or cleared):
        outcome = "OBSERVED_REPORTED" if reported else "OBSERVED_CLEARED"
    elif rejected and not reported and not cleared:
        outcome = "OBSERVED_REJECTED"
        issues.append("response_validation_rejected")
    else:
        issues.append("response_validation_unconfirmed")
    if outcome in ("OBSERVED_REPORTED", "OBSERVED_CLEARED"):
        if saved_status != outcome.removeprefix("OBSERVED_"):
            issues.append("saved_status_response_mismatch")
    elif saved_status in ("REPORTED", "CLEARED"):
        issues.append("saved_status_response_unconfirmed")
    for fieldname in ("reportedInvoice", "clearedInvoice"):
        value = body.get(fieldname)
        if value is None or (isinstance(value, str) and not value.strip()):
            if fieldname == "clearedInvoice" and outcome == "OBSERVED_CLEARED":
                issues.append("response_cleared_xml_missing")
            continue
        if (
            (fieldname == "clearedInvoice" and outcome == "OBSERVED_REPORTED")
            or (fieldname == "reportedInvoice" and outcome == "OBSERVED_CLEARED")
        ):
            issues.append("response_xml_outcome_mismatch")
        try:
            xml.append((fieldname, _response_xml(value)))
        except ArtifactEvidenceError as exc:
            issues.append(exc.code)
    return ResponseObservation(source_format, outcome, tuple(issues), fingerprint, size, tuple(xml))


def compare_counter_evidence(saved, values, expected_key):
    """Check a historical Production-purpose counter; never compute from secrets."""
    issues = []
    if values.get("company") != saved.company_name:
        issues.append("counter_company_mismatch")
    if values.get("issuing_unit") != saved.issuing_unit:
        issues.append("counter_unit_mismatch")
    # This legacy column is a document purpose, not the selected API environment.
    if values.get("environment") != "Production":
        issues.append("counter_purpose_mismatch")
    if values.get("name") != expected_key or values.get("counter_key") != expected_key:
        issues.append("counter_key_mismatch")
    if values.get("active") in (0, "0", False):
        issues.append("counter_inactive")
    elif values.get("active") not in (1, "1", True):
        issues.append("counter_active_invalid")
    try:
        position = parse_diagnostic_icv(values.get("last_issued_icv"), allow_zero=True)
    except ValueError:
        issues.append("counter_position_invalid")
        position = None
    try:
        invoice_icv = parse_diagnostic_icv(saved.icv)
    except ValueError:
        issues.append("saved_icv_invalid")
        invoice_icv = None
    if position is not None and invoice_icv is not None:
        if position < invoice_icv:
            issues.append("counter_below_invoice")
        elif position == invoice_icv:
            if values.get("last_invoice") != saved.invoice_name:
                issues.append("counter_tail_invoice_mismatch")
            if values.get("last_invoice_doctype") != saved.doctype:
                issues.append("counter_tail_doctype_mismatch")
    return tuple(issues)
