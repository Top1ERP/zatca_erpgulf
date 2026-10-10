"""Pure single-attempt event journal, not a dispatcher or acceptance validator.

Events are unverified observations. No HTTP receipt (including 200/409) grants
acceptance/replay, no timeout replaces issuance identity, and no in-memory state
proves a durable lease or transaction. Runtime adapters do not use this contract.
"""

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from zatca_erpgulf.zatca_erpgulf.response_json import MAX_RESPONSE_BYTES
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    IssuanceContractError, PreparedIssuanceCandidate,
    _canonical_uuid, _fingerprint, _sha256,
)


SCHEMA_VERSION = 1
MAX_EVENTS = 3  # Start, optional unknown outcome, optional late response.
EVENT_KINDS = {"ATTEMPT_STARTED", "TRANSPORT_UNKNOWN", "HTTP_RESPONSE"}
UNKNOWN_CAUSES = {"TIMEOUT", "CONNECTION_ERROR", "WORKER_INTERRUPTION"}


class DispatchJournalError(ValueError):
    """Static internal code; do not expose raw responses or exception messages."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _reference(value, code, validator):
    """Reuse the candidate's bounded reference policy, without a second resolver."""
    try:
        validator(value, code)
    except IssuanceContractError:
        raise DispatchJournalError(code) from None


@dataclass(frozen=True)
class DispatchEvent:
    """Bound one observation to an explicit attempt and unchanged candidate.

    UTC timestamps are provided by a future service, never obtained here. Bodies
    are exact immutable bytes with no decoding, normalization or JSON inference.
    Unknown transport events contain a static cause, never a raw exception.
    """

    event_id: str
    attempt_id: str
    sequence: int
    occurred_at: datetime
    kind: str
    key_sha256: str
    manifest_sha256: str
    http_status: int | None = None
    response_bytes: bytes | None = field(default=None, repr=False)
    request_id: str | None = None
    unknown_cause: str | None = None
    response_sha256: str | None = field(init=False)
    response_byte_length: int = field(init=False)

    def __post_init__(self):
        _reference(self.event_id, "event_id", _canonical_uuid)
        _reference(self.attempt_id, "attempt_id", _canonical_uuid)
        _reference(self.key_sha256, "event_key_fingerprint", _sha256)
        _reference(self.manifest_sha256, "event_manifest_fingerprint", _sha256)
        if type(self.sequence) is not int or not 1 <= self.sequence <= MAX_EVENTS:
            raise DispatchJournalError("event_sequence")
        if type(self.occurred_at) is not datetime or self.occurred_at.tzinfo is not timezone.utc:
            raise DispatchJournalError("event_utc_timestamp")
        if not isinstance(self.kind, str) or self.kind not in EVENT_KINDS:
            raise DispatchJournalError("event_kind")
        response_hash, response_size = None, 0
        if self.kind == "HTTP_RESPONSE":
            if type(self.http_status) is not int or not 200 <= self.http_status <= 599:
                raise DispatchJournalError("event_http_status")
            if not isinstance(self.response_bytes, bytes):
                raise DispatchJournalError("event_response_bytes")
            if len(self.response_bytes) > MAX_RESPONSE_BYTES:
                raise DispatchJournalError("event_response_size")
            if self.request_id is not None:
                _reference(self.request_id, "event_request_id", _canonical_uuid)
            if self.unknown_cause is not None:
                raise DispatchJournalError("event_fields_conflict")
            response_hash = hashlib.sha256(self.response_bytes).hexdigest()
            response_size = len(self.response_bytes)
        else:
            if any(value is not None for value in (self.http_status, self.response_bytes, self.request_id)):
                raise DispatchJournalError("event_fields_conflict")
            if self.kind == "TRANSPORT_UNKNOWN":
                if not isinstance(self.unknown_cause, str) or self.unknown_cause not in UNKNOWN_CAUSES:
                    raise DispatchJournalError("event_unknown_cause")
            elif self.unknown_cause is not None:
                raise DispatchJournalError("event_fields_conflict")
        object.__setattr__(self, "response_sha256", response_hash)
        object.__setattr__(self, "response_byte_length", response_size)

    def diagnostic_projection(self):
        """Non-secret observations only; never use these as verification claims."""
        return {
            "event_id": self.event_id, "attempt_id": self.attempt_id,
            "sequence": self.sequence, "occurred_at": self.occurred_at.isoformat(),
            "kind": self.kind, "key_sha256": self.key_sha256,
            "manifest_sha256": self.manifest_sha256, "http_status": self.http_status,
            "request_id": self.request_id, "unknown_cause": self.unknown_cause,
            "response_sha256": self.response_sha256,
            "response_byte_length": self.response_byte_length,
        }


@dataclass(frozen=True)
class DispatchJournal:
    """Validate one append-only attempt sequence against one prepared candidate.

    No second start is admitted here. Future retry/reconciliation and persisted
    cross-attempt coordination are separate, mandatory contracts. Constructing a
    fresh empty journal never grants permission to submit that candidate again.
    """

    candidate: PreparedIssuanceCandidate = field(repr=False)
    events: tuple = field(default=(), repr=False)
    state: str = field(init=False)
    active_attempt_id: str | None = field(init=False)
    journal_sha256: str = field(init=False)

    def __post_init__(self):
        if type(self.candidate) is not PreparedIssuanceCandidate:
            raise DispatchJournalError("journal_candidate")
        if type(self.events) is not tuple or len(self.events) > MAX_EVENTS:
            raise DispatchJournalError("journal_events")
        state, attempt_id, active_attempt = "PREPARED_CANDIDATE", None, None
        previous_time, event_ids = None, set()
        for expected_sequence, event in enumerate(self.events, start=1):
            if type(event) is not DispatchEvent:
                raise DispatchJournalError("journal_event")
            if event.event_id in event_ids:
                raise DispatchJournalError("event_id_duplicate")
            event_ids.add(event.event_id)
            if event.sequence != expected_sequence:
                raise DispatchJournalError("event_sequence_gap")
            if previous_time is not None and event.occurred_at < previous_time:
                raise DispatchJournalError("event_time_order")
            previous_time = event.occurred_at
            if event.key_sha256 != self.candidate.key_sha256:
                raise DispatchJournalError("event_key_mismatch")
            if event.manifest_sha256 != self.candidate.manifest_sha256:
                raise DispatchJournalError("event_manifest_mismatch")
            if event.kind == "ATTEMPT_STARTED":
                if active_attempt is not None:
                    raise DispatchJournalError("attempt_in_flight")
                if attempt_id is not None:
                    raise DispatchJournalError("attempt_reconciliation_required")
                attempt_id = active_attempt = event.attempt_id
                state = "IN_FLIGHT_OBSERVED"
                continue
            if attempt_id is None:
                raise DispatchJournalError("attempt_not_started")
            if event.attempt_id != attempt_id:
                raise DispatchJournalError("event_attempt_mismatch")
            if state in ("HTTP_RESPONSE_OBSERVED", "AUTHORIZATION_FAILURE_OBSERVED"):
                raise DispatchJournalError("response_already_recorded")
            if event.kind == "TRANSPORT_UNKNOWN":
                if state == "OUTCOME_UNKNOWN":
                    raise DispatchJournalError("unknown_outcome_already_recorded")
                state = "OUTCOME_UNKNOWN"
            else:
                # A late response may follow UNKNOWN; the earlier event remains.
                # Status alone does not establish validation/remote acceptance.
                state = (
                    "AUTHORIZATION_FAILURE_OBSERVED" if event.http_status in (401, 403)
                    else "HTTP_RESPONSE_OBSERVED"
                )
            active_attempt = None
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "active_attempt_id", active_attempt)
        object.__setattr__(self, "journal_sha256", _fingerprint({
            "schema_version": SCHEMA_VERSION, "key_sha256": self.candidate.key_sha256,
            "manifest_sha256": self.candidate.manifest_sha256,
            "events": [event.diagnostic_projection() for event in self.events],
        }))

    def diagnostic_projection(self):
        """A memory-only trace, not a SQL lease, accepted status or retry policy."""
        return {
            "schema_version": SCHEMA_VERSION, "state": self.state,
            "active_attempt_id": self.active_attempt_id,
            "key_sha256": self.candidate.key_sha256,
            "manifest_sha256": self.candidate.manifest_sha256,
            "journal_sha256": self.journal_sha256,
            "events": [event.diagnostic_projection() for event in self.events],
            "persistence_verified": False, "lease_verified": False,
            "remote_acceptance_verified": False, "dispatch_authorized": False,
            "replay_authorized": False,
        }


def append_dispatch_event(journal, event):
    """Return a new validated history; equal event-ID repeats are idempotent.

    A repeated ID with changed contents is a conflict, not an overwrite. This
    local rule does not replace SQL uniqueness, a durable log or a dispatch lock.
    """
    if type(journal) is not DispatchJournal or type(event) is not DispatchEvent:
        raise DispatchJournalError("journal_append")
    for recorded in journal.events:
        if recorded.event_id == event.event_id:
            if recorded != event:
                raise DispatchJournalError("event_id_conflict")
            return journal
    return replace(journal, events=journal.events + (event,))
