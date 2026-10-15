"""Explicit LOCAL exact-attempt custody/journal reconciliation, never dispatch.

No Frappe endpoint, transport, key/provider discovery, new identity, schema,
clock, hold release or automatic repair. Factories/keys/guards are trusted
server dependencies; authenticate/authorize their provenance before integration.
Keep original protected inputs after every outcome, including interruptions.
"""

from dataclasses import dataclass, field

from .issuance_candidate import _canonical_uuid
from .journal_repository import MariaDBJournalRepository
from .primary_capture import PrimaryCaptureRequest, _RequestBinding, _request
from .primary_receipt_custody import (
    MariaDBPrimaryReceiptCustodyRepository, PrimaryReceiptCustodyCipher, SealedPrimaryReceipt,
)
from .primary_receipt_persistence import _validate_retained


PAIR_STATES = (
    "PAIR_MISSING_OBSERVATION_NO_REPLAY", "PAIR_MATCHED_OBSERVATION_NO_REPLAY",
    "CUSTODY_ONLY_REVIEW_NO_REPLAY", "JOURNAL_ONLY_REVIEW_NO_REPLAY", "PAIR_CONFLICT_REVIEW_NO_REPLAY",
)
RESULT_STATES = (*PAIR_STATES, "PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY",
    "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY", "PAIR_STORED_OBSERVATION_NO_REPLAY",
    "PAIR_ALREADY_STORED_OBSERVATION_NO_REPLAY")


class PrimaryReconciliationError(ValueError):
    """Static codes only, not raw protected input, SQL or cipher failures."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _references(request, sealed):
    request = _request(request)
    if type(sealed) is not SealedPrimaryReceipt:
        raise PrimaryReconciliationError("primary_pair_input")
    sealed.__post_init__()
    if (sealed.candidate_sha256 != request.started.candidate.key_sha256
            or sealed.attempt_id != request.started.events[0].attempt_id
            or sealed.predecessor_sha256 != request.started.journal_sha256):
        raise PrimaryReconciliationError("primary_pair_binding")
    return request


@dataclass(frozen=True, repr=False)
class PrimaryReconciliationResult:
    """Protected original recovery input plus bounded local observation ONLY."""

    state: str
    request: PrimaryCaptureRequest = field(repr=False)
    sealed: SealedPrimaryReceipt = field(repr=False)

    def __post_init__(self):
        if type(self.state) is not str or self.state not in RESULT_STATES:
            raise PrimaryReconciliationError("primary_pair_result")
        _references(self.request, self.sealed)

    def diagnostic_projection(self):
        return {"state": self.state, "local_transaction_completed": self.state in (
            "PAIR_STORED_OBSERVATION_NO_REPLAY", "PAIR_ALREADY_STORED_OBSERVATION_NO_REPLAY"),
            "provider_origin_verified": False, "historical_source_verified": False,
            "credential_epoch_verified": False, "transport_verified": False,
            "remote_receipt_verified": False, "remote_acceptance_verified": False,
            "dispatch_authorized": False, "replay_authorized": False}

    def __repr__(self):
        return "PrimaryReconciliationResult(<protected exact local recovery input>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReconciliationError("primary_pair_not_pickleable")


def _owned_pair_transaction(factory, work, *, persist):
    """Close/rollback BOTH even on interruption; inspect NEVER commits.

    Always clear this fresh OWNED transaction before close, including after an
    acknowledged commit. Any cleanup failure makes completion unconfirmed. A
    non-ordinary interruption takes priority over ordinary cleanup/work errors.
    Failed acquisition remains the trusted factory's cleanup responsibility.
    """
    connection = factory()
    failures, result = [], None
    try:
        if any(not callable(getattr(connection, name, None)) for name in ("cursor", "commit", "rollback", "close")):
            raise PrimaryReconciliationError("primary_pair_connection")
        result = work(connection)
        if persist:
            connection.commit()
    except BaseException as error:
        failures.append(error)
    for name in ("rollback", "close"):
        try:
            getattr(connection, name)()
        except BaseException as error:
            failures.append(error)
    if failures:
        raise next((error for error in failures if not isinstance(error, Exception)), failures[0])
    return result


class PrimaryReceiptReconciliation:
    """Explicit exact encrypted envelope + request; no candidate/start creation.

    Inspect observes the pair under existing journal/hold/request locks, then
    rolls back/closes. Persist may store BOTH absent parts atomically, or confirm
    an already identical pair. Partial/different pairs are REVIEW ONLY: never
    synthesize/reseal/overwrite their missing or conflicting half. An absent
    pair is not evidence of remote non-receipt or permission to send again.
    """

    def __init__(self, namespace, cipher, *, connection_factory, source_guard):
        try:
            _canonical_uuid(namespace, "primary_pair_namespace")
            if (type(cipher) is not PrimaryReceiptCustodyCipher
                    or not callable(connection_factory) or not callable(source_guard)):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReconciliationError("primary_pair_dependencies")
        self._namespace, self._cipher, self._factory, self._guard = namespace, cipher, connection_factory, source_guard

    def __repr__(self):
        return "PrimaryReceiptReconciliation(<protected explicit local dependencies>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReconciliationError("primary_pair_not_pickleable")

    def _input(self, supplied, sealed):
        try:
            request = _references(supplied, sealed)
            receipt = self._cipher.open(sealed)  # Authenticate BEFORE any SQL.
            if sealed.storage_namespace != self._namespace or receipt.before != request.started:
                raise ValueError
            after = _validate_retained(receipt)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReconciliationError("primary_pair_input")
        return request, receipt, after

    def _check(self, connection, request, sealed, receipt):
        if self._guard(connection, request) is not True:
            raise PrimaryReconciliationError("primary_pair_source_guard")
        rebuilt, retained, _after = self._input(request, sealed)
        if rebuilt != request or retained != receipt:
            raise PrimaryReconciliationError("primary_pair_input_changed")

    def _pair(self, connection, request, sealed, receipt, after):
        # Same candidate-first lock order as capture. Exact hold + serializer
        # binding must exist, even when BOTH response parts are absent.
        _RequestBinding(connection, self._namespace).check(request)
        current = MariaDBJournalRepository(connection, self._namespace).load(sealed.candidate_sha256)
        if current not in (receipt.before, after):
            return "PAIR_CONFLICT_REVIEW_NO_REPLAY"
        with connection.cursor() as cursor:
            # Optional presence selection is NOT an exceptional repository load:
            # do not continue a repository transaction poisoned by a missing row.
            cursor.execute("SELECT candidate_sha256 FROM zatca_primary_receipt_custody_v1 "
                "WHERE storage_namespace=%s AND candidate_sha256=%s AND attempt_id=%s FOR UPDATE",
                (self._namespace, sealed.candidate_sha256, sealed.attempt_id))
            row = cursor.fetchone()
        if row is not None:
            if type(row) is not tuple or row != (sealed.candidate_sha256,):
                raise PrimaryReconciliationError("primary_pair_custody_row")
            stored = MariaDBPrimaryReceiptCustodyRepository(connection, self._namespace, self._cipher).load(
                sealed.candidate_sha256, sealed.attempt_id)
            if stored != sealed:  # Same plaintext with a DIFFERENT seal is still a conflict.
                return "PAIR_CONFLICT_REVIEW_NO_REPLAY"
        if current == after:
            return "PAIR_MATCHED_OBSERVATION_NO_REPLAY" if row is not None else "JOURNAL_ONLY_REVIEW_NO_REPLAY"
        return "CUSTODY_ONLY_REVIEW_NO_REPLAY" if row is not None else "PAIR_MISSING_OBSERVATION_NO_REPLAY"

    def inspect(self, request, sealed):
        """Local observation only; no commit, append, stage or dispatch."""
        return self._run(request, sealed, persist=False)

    def persist(self, request, sealed):
        """Explicit LOCAL redelivery only; caller must keep ORIGINAL envelope.

        No loop/resume/transport or reseal. Unknown commit/cleanup preserves exact
        input for a separately authorized inspection, never claims non-delivery.
        """
        return self._run(request, sealed, persist=True)

    def _run(self, supplied, sealed, *, persist):
        request, receipt, after = self._input(supplied, sealed)
        def work(connection):
            self._check(connection, request, sealed, receipt)
            state = self._pair(connection, request, sealed, receipt, after)
            if persist and state == "PAIR_MISSING_OBSERVATION_NO_REPLAY":
                stored = MariaDBPrimaryReceiptCustodyRepository(connection, self._namespace, self._cipher).stage(sealed)
                journal = MariaDBJournalRepository(connection, self._namespace).append(sealed.candidate_sha256,
                    receipt.response_event, expected_journal_sha256=request.started.journal_sha256)
                if stored != sealed or journal != after:
                    raise PrimaryReconciliationError("primary_pair_storage")
                state = "PAIR_STORED_OBSERVATION_NO_REPLAY"
            elif persist and state == "PAIR_MATCHED_OBSERVATION_NO_REPLAY":
                state = "PAIR_ALREADY_STORED_OBSERVATION_NO_REPLAY"
            self._check(connection, request, sealed, receipt)
            return state
        try:
            state = _owned_pair_transaction(self._factory, work, persist=persist)
        except Exception:
            state = "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY" if persist else "PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY"
        return PrimaryReconciliationResult(state, request, sealed)
