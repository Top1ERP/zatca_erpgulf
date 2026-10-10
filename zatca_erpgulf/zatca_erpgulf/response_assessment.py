"""Pure endpoint/receipt consistency checks, not verified remote acceptance.

A genuine expected ZATCA 200 is success; 202 is success with warnings.
This model checks unverified local observations before a future service may
record acceptance. It never changes invoice status/identity/PIH or retries.
Returned XML metadata is not signature, invoice-hash or business-data proof.
"""

import base64
import binascii
import hashlib
from dataclasses import dataclass, field

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import (
    MAX_XML_BYTES, ArtifactEvidenceError, inspect_invoice_artifact,
)
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    IssuanceContractError, _fingerprint, _invoice_classification,
)
from zatca_erpgulf.zatca_erpgulf.response_json import parse_wire_response


SCHEMA_VERSION = 1
REPORTING = "invoices/reporting/single"
CLEARANCE = "invoices/clearance/single"


class ResponseAssessmentError(ValueError):
    """Static internal code only; no raw XML, routes or response messages."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


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


def _returned_xml(value):
    """Bound strict Base64 with ASCII whitespace only; preserve decoded bytes."""
    if type(value) is not str or not value:
        raise ArtifactEvidenceError("response_xml_type")
    compact = value.translate(str.maketrans("", "", " \t\r\n"))
    if len(compact) > 4 * ((MAX_XML_BYTES + 2) // 3):
        raise ArtifactEvidenceError("response_xml_size")
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error):
        raise ArtifactEvidenceError("response_xml_base64") from None
    if not decoded or len(decoded) > MAX_XML_BYTES:
        raise ArtifactEvidenceError("response_xml_size")
    return decoded


def _xml_match(content, candidate):
    """Compare issuance metadata, not original signature/QR/certificate bytes.

    Clearance legitimately returns a different signed/QR artifact. Matching
    declared digests here does NOT verify their computation or monetary parity.
    """
    observed = inspect_invoice_artifact(content)
    code, indicator = _invoice_classification(content)
    issues = []
    for attribute in ("invoice_id", "uuid", "icv", "seller_tax_id", "invoice_digest", "previous_hash"):
        if getattr(observed, attribute) != getattr(candidate.artifact, attribute):
            issues.append("response_xml_" + attribute + "_mismatch")
    if code != candidate.invoice_type_code or indicator != candidate.invoice_type_indicator:
        issues.append("response_xml_type_mismatch")
    return tuple(issues)


def _assess(journal):
    candidate, endpoint = journal.candidate, journal.candidate.context.route.endpoint
    if not journal.events or journal.events[-1].kind != "HTTP_RESPONSE":
        outcome = "TRANSPORT_UNKNOWN" if journal.state == "OUTCOME_UNKNOWN" else "NO_RESPONSE"
        return outcome, (), 0, False, None
    receipt = journal.events[-1]
    status = receipt.http_status
    outcome = (
        "AUTHORIZATION_FAILED" if status in (401, 403) else
        "DUPLICATE_UNCONFIRMED" if status == 409 else
        "CLEARANCE_DISABLED_OBSERVED" if status == 303 and endpoint == CLEARANCE else
        "HTTP_REJECTION_OBSERVED" if status == 400 else
        "HTTP_FAILURE_OBSERVED" if status >= 500 else "UNCONFIRMED"
    )
    try:
        body = parse_wire_response(receipt.response_bytes)
    except ArtifactEvidenceError as error:
        return outcome, (error.code,), 0, status == 202, None
    validation, warnings, validation_issues = _validation(body)
    issues = list(validation_issues + _outcome_issues(body, endpoint))
    has_warnings = status == 202 or validation == "WARNING" or bool(warnings)
    accepted = body.get("reportingStatus") == "REPORTED" or body.get("clearanceStatus") == "CLEARED"
    if status not in (200, 202):
        if accepted:
            issues.append("response_http_outcome_conflict")
        if status == 303 and endpoint != CLEARANCE:
            issues.append("response_operation_mismatch")
        if status == 400 and validation == "ERROR" and not accepted and not issues:
            outcome = "VALIDATION_REJECTION_MATCHED"
        return outcome, tuple(dict.fromkeys(issues)), warnings, has_warnings, None
    if validation not in ("PASS", "WARNING"):
        issues.append("response_validation_unconfirmed")
    required_status = "reportingStatus" if endpoint == REPORTING else "clearanceStatus"
    if body.get(required_status) != ("REPORTED" if endpoint == REPORTING else "CLEARED"):
        issues.append("response_acceptance_missing")
    if "invoiceHash" in body and body["invoiceHash"] != candidate.artifact.invoice_digest:
        issues.append("response_invoice_hash_mismatch")
    required_xml = "reportedInvoice" if endpoint == REPORTING else "clearedInvoice"
    wrong_xml = "clearedInvoice" if endpoint == REPORTING else "reportedInvoice"
    if body.get(wrong_xml) is not None:
        issues.append("response_xml_operation_mismatch")
    returned = None
    if endpoint == CLEARANCE or body.get(required_xml) is not None:
        try:
            returned = _returned_xml(body.get(required_xml))
            issues.extend(_xml_match(returned, candidate))
        except (ArtifactEvidenceError, IssuanceContractError) as error:
            issues.append(error.code)
    if issues:
        return "UNCONFIRMED", tuple(dict.fromkeys(issues)), warnings, has_warnings, None
    outcome = "REPORTING_ACCEPTANCE_MATCHED" if endpoint == REPORTING else "CLEARANCE_ACCEPTANCE_MATCHED"
    return outcome, (), warnings, has_warnings, returned


@dataclass(frozen=True)
class ResponseAssessment:
    """Derived local contract match, never a caller-supplied acceptance claim.

    No raw body/message/XML/URL in repr or diagnostics. Generic dataclass
    serialization is unsuitable for logs. All verification/authority flags stay
    false, including for internally consistent 200/202 responses.
    """

    journal: DispatchJournal = field(repr=False)
    outcome: str = field(init=False)
    issues: tuple = field(init=False)
    warning_count: int = field(init=False)
    has_warnings: bool = field(init=False)
    returned_xml: bytes | None = field(init=False, repr=False)
    returned_xml_sha256: str | None = field(init=False)
    assessment_sha256: str = field(init=False)

    def __post_init__(self):
        if type(self.journal) is not DispatchJournal:
            raise ResponseAssessmentError("assessment_journal")
        outcome, issues, warnings, has_warnings, returned = _assess(self.journal)
        for name, value in (
            ("outcome", outcome), ("issues", issues), ("warning_count", warnings),
            ("has_warnings", has_warnings), ("returned_xml", returned),
            ("returned_xml_sha256", hashlib.sha256(returned).hexdigest() if returned is not None else None),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "assessment_sha256", _fingerprint(self._observations()))

    def _observations(self):
        receipt = self.journal.events[-1] if self.journal.events else None
        return {
            "schema_version": SCHEMA_VERSION, "journal_sha256": self.journal.journal_sha256,
            "event_id": receipt.event_id if receipt is not None else None,
            "outcome": self.outcome, "issues": list(self.issues),
            "warning_count": self.warning_count, "has_warnings": self.has_warnings,
            "returned_xml_sha256": self.returned_xml_sha256,
        }

    def diagnostic_projection(self):
        return {
            **self._observations(), "assessment_sha256": self.assessment_sha256,
            "remote_acceptance_verified": False, "network_provenance_verified": False,
            "signature_verified": False, "invoice_hash_verified": False,
            "business_data_verified": False, "persistence_verified": False,
            "dispatch_authorized": False, "replay_authorized": False,
        }
