"""Explicit LOCAL primary receipt persistence, never a dispatch/retry service.

No runtime hook, endpoint, transport, clock, connection discovery or schema setup.
An authorized server must supply a reviewed owned connection factory and exact
previously-started journal. Supplied scope/bytes do not prove their provenance.
Never log, queue, pickle or expose these protected objects to an operator.
"""

from dataclasses import dataclass, field

from .compliance_capture import _owned_transaction
from .dispatch_journal import MAX_EVENTS, DispatchEvent, DispatchJournal, append_dispatch_event
from .issuance_candidate import PreparedIssuanceCandidate, _canonical_uuid
from .journal_repository import MariaDBJournalRepository
from .journal_storage import (
    decode_candidate_context, decode_dispatch_event,
    encode_candidate_context, encode_dispatch_event,
)


class PrimaryReceiptError(ValueError):
    """Static internal code only; no body, driver, key or source details."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _validate_retained(receipt):
    """Rebuild exact contracts before SQL; declarations are not authentication."""
    try:
        if type(receipt) is not RetainedPrimaryReceipt:
            raise ValueError
        _canonical_uuid(receipt.storage_namespace, "receipt_namespace")
        before, event = receipt.before, receipt.response_event
        if (type(before) is not DispatchJournal or type(event) is not DispatchEvent
                or type(before.candidate) is not PreparedIssuanceCandidate
                or type(before.events) is not tuple or not 1 <= len(before.events) < MAX_EVENTS):
            raise ValueError
        candidate = decode_candidate_context(encode_candidate_context(before.candidate), before.candidate.xml_bytes)
        events = tuple(decode_dispatch_event(encode_dispatch_event(item), item.response_bytes) for item in before.events)
        rebuilt = DispatchJournal(candidate, events)
        response = decode_dispatch_event(encode_dispatch_event(event), event.response_bytes)
        if (rebuilt != before or response != event or event.kind != "HTTP_RESPONSE"
                or before.state not in ("IN_FLIGHT_OBSERVED", "OUTCOME_UNKNOWN")):
            raise ValueError
        after = append_dispatch_event(rebuilt, response)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PrimaryReceiptError("primary_receipt_input")
    return after


@dataclass(frozen=True)
class RetainedPrimaryReceipt:
    """Exact caller-retained response for one existing attempt, NOT a receipt proof.

    The same event ID/sequence/time/bytes must be retained across uncertain local
    commits. Never obtain a new timestamp/event or resend to recreate this input.
    This memory object is not crash-proof storage or a later-retry authorization.
    """

    storage_namespace: str = field(repr=False)
    before: DispatchJournal = field(repr=False)
    response_event: DispatchEvent = field(repr=False)

    def __post_init__(self):
        _validate_retained(self)

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptError("primary_receipt_not_pickleable")


@dataclass(frozen=True)
class PrimaryReceiptResult:
    """Protected local observation; neither state grants replay or acceptance."""

    state: str
    receipt: RetainedPrimaryReceipt = field(repr=False)

    def __post_init__(self):
        if type(self.state) is not str or self.state not in (
            "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY", "RECEIPT_STORED_OBSERVATION_NO_REPLAY",
        ):
            raise PrimaryReceiptError("primary_receipt_result")
        _validate_retained(self.receipt)

    def diagnostic_projection(self):
        """No IDs, raw bytes or protected source; not a permissioned public API."""
        return {"state": self.state,
            "local_transaction_completed": self.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY",
            "provider_origin_verified": False, "source_snapshot_verified": False,
            "credential_epoch_verified": False, "remote_receipt_verified": False,
            "remote_acceptance_verified": False, "dispatch_authorized": False, "replay_authorized": False}

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptError("primary_receipt_not_pickleable")


class PrimaryReceiptPersistence:
    """Persist/redeliver exact retained HTTP observations in ONE owned transaction.

    The factory must return a fresh owned non-autocommit connection, never the
    ambient Frappe handle. An optional exact-source guard must return literal
    True before and after append. Dependency origin/ownership is not proven here.
    Existing journal storage performs fixed SQL/row locks/CAS and never sends.
    """

    def __init__(self, storage_namespace, *, connection_factory, source_guard=None):
        try:
            _canonical_uuid(storage_namespace, "receipt_namespace")
            if not callable(connection_factory) or (source_guard is not None and not callable(source_guard)):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReceiptError("primary_receipt_dependencies")
        self._namespace, self._factory, self._guard = storage_namespace, connection_factory, source_guard

    def __repr__(self):
        return "PrimaryReceiptPersistence(<protected explicit local dependencies>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptError("primary_receipt_not_pickleable")

    def persist(self, receipt):
        """Never create a start, replace bytes, adjust sequence/time or retry HTTP.

        Unknown acquire/SQL/guard/commit/close returns an unconfirmed observation
        retaining the EXACT input. Commit AND close must finish to report local
        completion; a failed acknowledgment may still have committed. Explicit
        local redelivery is idempotent only for identical stored evidence.
        BaseException interruptions propagate after owned cleanup; retain input.
        """
        after = _validate_retained(receipt)
        if receipt.storage_namespace != self._namespace:
            raise PrimaryReceiptError("primary_receipt_scope")

        def work(connection):
            if self._guard is not None and self._guard(connection, receipt) is not True:
                raise PrimaryReceiptError("primary_receipt_source_guard")
            if _validate_retained(receipt) != after:
                raise PrimaryReceiptError("primary_receipt_journal_conflict")
            repository = MariaDBJournalRepository(connection, self._namespace)
            before = repository.load(receipt.before.candidate.key_sha256)
            # Only the exact predecessor or exact already-stored response is
            # eligible. A late UNKNOWN/different response is not silently folded
            # into another revision and must be reviewed separately.
            if before != receipt.before and before != after:
                raise PrimaryReceiptError("primary_receipt_journal_conflict")
            stored = repository.append(receipt.before.candidate.key_sha256, receipt.response_event,
                expected_journal_sha256=receipt.before.journal_sha256)
            if stored != after:
                raise PrimaryReceiptError("primary_receipt_journal_conflict")
            if self._guard is not None and self._guard(connection, receipt) is not True:
                raise PrimaryReceiptError("primary_receipt_source_guard")
            if _validate_retained(receipt) != after:
                raise PrimaryReceiptError("primary_receipt_journal_conflict")

        try:
            _owned_transaction(self._factory, work)
        except Exception:
            state = "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
        else:
            state = "RECEIPT_STORED_OBSERVATION_NO_REPLAY"
        return PrimaryReceiptResult(state, receipt)
