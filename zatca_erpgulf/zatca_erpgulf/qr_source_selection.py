"""Exact journal-bound Phase-2 QR observations, NOT authenticated recovery.

Reporting uses the prepared request; clearance uses the matching returned XML.
No latest/name/status fallback, ORM, content reads, images, signing or dispatch.
Consistent supplied bytes are not proof of origin, persistence or acceptance.
"""

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
from uuid import UUID

from .artifact_evidence import ArtifactEvidenceError, NS, parse_diagnostic_xml
from .dispatch_journal import DispatchJournal, DispatchJournalError
from .issuance_candidate import IssuanceContractError, PreparationContext, _canonical_uuid, _sha256
from .issue_timestamp import IssueTimestampError, parse_issue_datetime
from .response_assessment import CLEARANCE, REPORTING, ResponseAssessment, ResponseAssessmentError


MAX_QR_BASE64_CHARS = 16 * 1024


class QRSourceSelectionError(ValueError):
    """Static codes only; no XML/QR/receipt/identity/parser representation."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _one(parent, xpath, code):
    nodes = parent.xpath(xpath, namespaces=NS)
    if len(nodes) != 1:
        raise QRSourceSelectionError(code)
    return nodes[0]


def _text(node, code, maximum):
    value = node.text
    if len(node) or type(value) is not str or not 0 < len(value) <= maximum or value != value.strip():
        raise QRSourceSelectionError(code)
    return value


def _clock(content):
    root = parse_diagnostic_xml(content)
    day = _text(_one(root, "./cbc:IssueDate", "qr_source_date"), "qr_source_date", 10)
    clock = _text(_one(root, "./cbc:IssueTime", "qr_source_time"), "qr_source_time", 32)
    # Validate without supplying a current timezone or normalizing historical text.
    parse_issue_datetime(day, clock)
    return day, clock


def _payload(content):
    root = parse_diagnostic_xml(content)
    reference = _one(root, "./cac:AdditionalDocumentReference[cbc:ID='QR']", "qr_source_reference")
    if _text(_one(reference, "./cbc:ID", "qr_source_reference"), "qr_source_reference", 2) != "QR":
        raise QRSourceSelectionError("qr_source_reference")
    attachment = _one(reference, "./cac:Attachment", "qr_source_attachment")
    node = _one(attachment, "./cbc:EmbeddedDocumentBinaryObject", "qr_source_payload")
    payload = _text(node, "qr_source_payload", MAX_QR_BASE64_CHARS)
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        invalid = True
    else:
        invalid = not decoded or base64.b64encode(decoded).decode("ascii") != payload
    if invalid:
        raise QRSourceSelectionError("qr_source_base64")
    # Base64 is a bounded lexical observation, NOT TLV/signature/QR validation.
    return payload, len(decoded)


def _select(source):
    if type(source.journal) is not DispatchJournal or type(source.expected_context) is not PreparationContext:
        raise QRSourceSelectionError("qr_source_binding")
    _sha256(source.expected_journal_sha256, "qr_source_revision")
    _canonical_uuid(source.expected_uuid, "qr_source_uuid")
    if type(source.expected_icv) is not int or not 1 <= source.expected_icv < 10**64:
        raise QRSourceSelectionError("qr_source_icv")
    journal = DispatchJournal(source.journal.candidate, source.journal.events)
    candidate = journal.candidate
    if journal.journal_sha256 != source.expected_journal_sha256:
        raise QRSourceSelectionError("qr_source_revision_mismatch")
    if candidate.context != source.expected_context:
        raise QRSourceSelectionError("qr_source_context_mismatch")
    if str(UUID(candidate.artifact.uuid)) != source.expected_uuid or candidate.artifact.icv != source.expected_icv:
        raise QRSourceSelectionError("qr_source_identity_mismatch")
    endpoint = candidate.context.route.endpoint
    if endpoint not in (REPORTING, CLEARANCE):
        raise QRSourceSelectionError("qr_source_operation")
    assessment = ResponseAssessment(journal)
    expected_outcome = "REPORTING_ACCEPTANCE_MATCHED" if endpoint == REPORTING else "CLEARANCE_ACCEPTANCE_MATCHED"
    if assessment.issues or assessment.outcome != expected_outcome:
        raise QRSourceSelectionError("qr_source_response_unconfirmed")
    original_clock = _clock(candidate.xml_bytes)
    if assessment.returned_xml is not None and _clock(assessment.returned_xml) != original_clock:
        raise QRSourceSelectionError("qr_source_returned_clock_mismatch")
    if endpoint == CLEARANCE:
        if assessment.returned_xml is None:
            raise QRSourceSelectionError("qr_source_returned_missing")
        kind, content = "CLEARANCE_RETURNED_XML", assessment.returned_xml
    else:
        kind, content = "REPORTING_REQUEST_XML", candidate.xml_bytes
    payload, decoded_length = _payload(content)
    return kind, content, payload, decoded_length, original_clock, assessment


@dataclass(frozen=True, repr=False)
class ArchivedQRSource:
    """Derived exact-byte evidence, never a permission or recovery capability.

    Server providers must eventually bind saved source/owner, site/namespace,
    committed record revision and authenticated receipt origin. This class cannot
    establish those facts or authorize export, attachment, generation or replay.
    """

    journal: DispatchJournal = field(repr=False)
    expected_context: PreparationContext = field(repr=False)
    expected_uuid: str = field(repr=False)
    expected_icv: int = field(repr=False)
    expected_journal_sha256: str
    source_kind: str = field(init=False)
    xml_bytes: bytes = field(init=False, repr=False)
    qr_payload: str = field(init=False, repr=False)
    decoded_qr_byte_length: int = field(init=False)
    issue_date: str = field(init=False, repr=False)
    issue_time: str = field(init=False, repr=False)
    xml_sha256: str = field(init=False)
    qr_payload_sha256: str = field(init=False)
    assessment_sha256: str = field(init=False)
    has_warnings: bool = field(init=False)

    def __post_init__(self):
        try:
            result = _select(self)
        except (ArtifactEvidenceError, DispatchJournalError, IssuanceContractError,
                IssueTimestampError, ResponseAssessmentError) as error:
            failure = error.code
        else:
            failure = None
        if failure is not None:
            raise QRSourceSelectionError(failure)  # No private exception context.
        kind, content, payload, decoded_length, clock, assessment = result
        for name, value in (
            ("source_kind", kind), ("xml_bytes", content), ("qr_payload", payload),
            ("decoded_qr_byte_length", decoded_length), ("issue_date", clock[0]), ("issue_time", clock[1]),
            ("xml_sha256", hashlib.sha256(content).hexdigest()),
            ("qr_payload_sha256", hashlib.sha256(payload.encode("ascii")).hexdigest()),
            ("assessment_sha256", assessment.assessment_sha256), ("has_warnings", assessment.has_warnings),
        ):
            object.__setattr__(self, name, value)

    def __repr__(self):
        return "ArchivedQRSource(<unverified exact-byte observations>)"

    def __reduce_ex__(self, protocol):
        raise QRSourceSelectionError("qr_source_not_pickleable")

    def diagnostic_projection(self):
        """Hashes/lengths only; exact-file hashes are NOT ZATCA invoice digests."""
        return {
            "schema_version": 1, "outcome": "ARCHIVED_QR_SOURCE_CONSISTENCY_MATCHED",
            "source_kind": self.source_kind, "journal_sha256": self.expected_journal_sha256,
            "assessment_sha256": self.assessment_sha256, "xml_sha256": self.xml_sha256,
            "qr_payload_sha256": self.qr_payload_sha256, "xml_byte_length": len(self.xml_bytes),
            "decoded_qr_byte_length": self.decoded_qr_byte_length, "has_warnings": self.has_warnings,
            **{name: False for name in (
                "source_provenance_verified", "permission_verified", "persistence_verified",
                "remote_acceptance_verified", "signature_verified", "invoice_hash_verified",
                "business_data_verified", "qr_verified", "recovery_authorized", "dispatch_authorized",
                "replay_authorized",
            )},
        }
