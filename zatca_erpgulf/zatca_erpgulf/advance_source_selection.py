"""Exact archived-attempt advance source selection, NOT verified acceptance.

Reporting selects the original request; clearance selects the returned artifact.
Expected preparation context, source UUID/ICV and journal revision are explicit
server declarations. No filename/status/latest-record heuristic or fallback.
These declarations require an audited permissioned storage provider before use
in runtime settlement. A fabricated consistent journal is NOT issuance proof.
"""

from dataclasses import dataclass, field
from uuid import UUID

from zatca_erpgulf.zatca_erpgulf.advance_reference import (
    AdvanceReferenceError,
    AdvanceReferenceEvidence,
    inspect_advance_reference,
)
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import (
    DispatchJournal,
    DispatchJournalError,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    IssuanceContractError,
    PreparationContext,
    _canonical_uuid,
    _sha256,
)
from zatca_erpgulf.zatca_erpgulf.response_assessment import (
    CLEARANCE,
    REPORTING,
    ResponseAssessment,
    ResponseAssessmentError,
)


class AdvanceSourceSelectionError(ValueError):
    """Static codes; no source/context, XML or receipt content in errors."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ArchivedAdvanceSource:
    """Derived exact-byte source observation, not a settlement capability.

    Construction computes every selection field. Do not serialize this object
    generically into logs; use the metadata-only diagnostic projection instead.
    """

    journal: DispatchJournal = field(repr=False)
    expected_context: PreparationContext = field(repr=False)
    expected_uuid: str = field(repr=False)
    expected_icv: int = field(repr=False)
    expected_journal_sha256: str
    source_kind: str = field(init=False)
    xml_bytes: bytes = field(init=False, repr=False)
    reference: AdvanceReferenceEvidence = field(init=False, repr=False)
    assessment_sha256: str = field(init=False)
    has_warnings: bool = field(init=False)

    def __post_init__(self):
        # Translate internal failures only after leaving exception handlers.
        # This prevents parser/response exception context leaking private data.
        try:
            kind, content, reference, assessment = _select(self)
        except (AdvanceSourceSelectionError, AdvanceReferenceError,
                IssuanceContractError, DispatchJournalError,
                ResponseAssessmentError) as error:
            error_code = error.code
        else:
            error_code = None
        if error_code is not None:
            raise AdvanceSourceSelectionError(error_code)
        for name, value in (
            ("source_kind", kind), ("xml_bytes", content),
            ("reference", reference),
            ("assessment_sha256", assessment.assessment_sha256),
            ("has_warnings", assessment.has_warnings),
        ):
            object.__setattr__(self, name, value)

    def diagnostic_projection(self):
        """No identity/time/XML/URL/body; no verified/authorized flags."""
        return {
            "schema_version": 1,
            "outcome": "ARCHIVED_SOURCE_CONSISTENCY_MATCHED",
            "source_kind": self.source_kind,
            "journal_sha256": self.expected_journal_sha256,
            "assessment_sha256": self.assessment_sha256,
            "file_sha256": self.reference.file_sha256,
            "byte_length": self.reference.byte_length,
            "has_warnings": self.has_warnings,
            "source_provenance_verified": False,
            "permission_verified": False,
            "persistence_verified": False,
            "remote_acceptance_verified": False,
            "signature_verified": False,
            "invoice_hash_verified": False,
            "business_data_verified": False,
            "settlement_authorized": False,
            "dispatch_authorized": False,
            "replay_authorized": False,
        }


def _reference(content, selected):
    scope = selected.expected_context.scope
    return inspect_advance_reference(
        content,
        expected_invoice_id=scope.invoice_name,
        expected_uuid=selected.expected_uuid,
        expected_seller_tax_id=scope.seller_tax_id,
    )


def _select(selected):
    if type(selected.journal) is not DispatchJournal:
        raise AdvanceSourceSelectionError("advance_source_journal")
    if type(selected.expected_context) is not PreparationContext:
        raise AdvanceSourceSelectionError("advance_source_context")
    _sha256(selected.expected_journal_sha256, "advance_source_revision")
    _canonical_uuid(selected.expected_uuid, "advance_source_uuid")
    if type(selected.expected_icv) is not int or not 1 <= selected.expected_icv < 10**64:
        raise AdvanceSourceSelectionError("advance_source_icv")

    # Reconstruct event/revision observations rather than accept an independent
    # caller-provided response assessment or success-shaped outcome dictionary.
    journal = DispatchJournal(selected.journal.candidate, selected.journal.events)
    candidate = journal.candidate
    if journal.journal_sha256 != selected.expected_journal_sha256:
        raise AdvanceSourceSelectionError("advance_source_revision_mismatch")
    if candidate.context != selected.expected_context:
        raise AdvanceSourceSelectionError("advance_source_context_mismatch")
    if candidate.context.scope.doctype != "Sales Invoice":
        raise AdvanceSourceSelectionError("advance_source_doctype")
    if candidate.invoice_type_code != "386":
        raise AdvanceSourceSelectionError("advance_source_type")
    if str(UUID(candidate.artifact.uuid)) != selected.expected_uuid:
        raise AdvanceSourceSelectionError("advance_source_uuid_mismatch")
    if candidate.artifact.icv != selected.expected_icv:
        raise AdvanceSourceSelectionError("advance_source_icv_mismatch")

    endpoint = candidate.context.route.endpoint
    if endpoint not in (REPORTING, CLEARANCE):
        raise AdvanceSourceSelectionError("advance_source_operation")
    assessment = ResponseAssessment(journal)
    required_outcome = (
        "REPORTING_ACCEPTANCE_MATCHED" if endpoint == REPORTING
        else "CLEARANCE_ACCEPTANCE_MATCHED"
    )
    if assessment.issues or assessment.outcome != required_outcome:
        raise AdvanceSourceSelectionError("advance_source_response_unconfirmed")
    original_reference = _reference(candidate.xml_bytes, selected)
    returned_reference = None
    if assessment.returned_xml is not None:
        returned_reference = _reference(assessment.returned_xml, selected)
        if (returned_reference.issue_date, returned_reference.issue_time) != (
            original_reference.issue_date, original_reference.issue_time
        ):
            # Identity/hash-declaration parity alone does not detect clock drift.
            # Even equivalent instants with different lexical forms fail closed
            # until a separately reviewed historical comparison policy exists.
            raise AdvanceSourceSelectionError("advance_source_returned_clock_mismatch")
    if endpoint == CLEARANCE:
        if assessment.returned_xml is None or returned_reference is None:
            raise AdvanceSourceSelectionError("advance_source_returned_xml_missing")
        return "CLEARANCE_RETURNED_XML", assessment.returned_xml, returned_reference, assessment
    return "REPORTING_REQUEST_XML", candidate.xml_bytes, original_reference, assessment
