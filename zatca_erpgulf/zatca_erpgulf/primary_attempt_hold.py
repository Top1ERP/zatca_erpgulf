"""Explicit LOCAL primary-invoice no-replay hold, NOT an activated dispatcher.

Reserve an existing empty candidate's start and one immutable logical-invoice
hold in the SAME caller-owned SQL transaction. No commit, discovery, clock,
transport, expiration/release, queue or Frappe installation occurs here. A return
value/absent row is never dispatch permission or evidence of remote non-receipt.
"""

from dataclasses import dataclass

from .dispatch_journal import DispatchJournal
from .issuance_candidate import PreparedIssuanceCandidate, _canonical_uuid, _fingerprint, _sha256
from .journal_repository import MariaDBJournalRepository
from .journal_storage import (
    decode_candidate_context, decode_dispatch_event, encode_candidate_context, encode_dispatch_event,
)


HOLD_FIELDS = ("storage_namespace", "source_sha256", "candidate_sha256", "manifest_sha256",
               "attempt_id", "started_journal_sha256")


class PrimaryAttemptHoldError(ValueError):
    """Static internal codes only, not a public SQL/parser/identity error."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _started_journal(journal):
    """Rebuild all existing contracts BEFORE SQL; declarations are not provenance."""
    try:
        if (type(journal) is not DispatchJournal or type(journal.candidate) is not PreparedIssuanceCandidate
                or type(journal.events) is not tuple or len(journal.events) != 1):
            raise ValueError
        candidate = decode_candidate_context(encode_candidate_context(journal.candidate), journal.candidate.xml_bytes)
        event = decode_dispatch_event(encode_dispatch_event(journal.events[0]), None)
        rebuilt = DispatchJournal(candidate, (event,))
        if rebuilt != journal or event.kind != "ATTEMPT_STARTED" or rebuilt.state != "IN_FLIGHT_OBSERVED":
            raise ValueError
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PrimaryAttemptHoldError("primary_hold_input")
    return rebuilt


def _source_sha256(candidate):
    """Logical saved document key; deliberately NOT a candidate/version/chain key.

    Namespace is the SQL scope, not input to this hash. Renames, source aliases
    and cross-namespace/tenant provisioning require a separate audited mapping.
    """
    scope = candidate.context.scope
    return _fingerprint({"schema_version": 1, "purpose": "primary-invoice-no-replay",
        "doctype": scope.doctype, "company": scope.company_name, "invoice": scope.invoice_name})


@dataclass(frozen=True, repr=False)
class PrimaryAttemptHold:
    """Immutable protected start binding; no lease expiry or acceptance state."""

    storage_namespace: str
    source_sha256: str
    candidate_sha256: str
    manifest_sha256: str
    attempt_id: str
    started_journal_sha256: str

    def __post_init__(self):
        try:
            for value in (self.storage_namespace, self.attempt_id):
                _canonical_uuid(value, "primary_hold_identity")
            for value in (self.source_sha256, self.candidate_sha256, self.manifest_sha256, self.started_journal_sha256):
                _sha256(value, "primary_hold_fingerprint")
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryAttemptHoldError("primary_hold_record")

    def diagnostic_projection(self):
        return {"state": "PRIMARY_INVOICE_HELD_OBSERVATION_NO_REPLAY",
            "local_commit_verified": False, "provider_origin_verified": False,
            "historical_source_verified": False, "credential_epoch_verified": False,
            "remote_receipt_verified": False, "remote_acceptance_verified": False,
            "dispatch_authorized": False, "replay_authorized": False}

    def __repr__(self):
        return "PrimaryAttemptHold(<protected immutable local start binding>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryAttemptHoldError("primary_hold_not_pickleable")


def _declaration(namespace, started):
    return PrimaryAttemptHold(namespace, _source_sha256(started.candidate), started.candidate.key_sha256,
        started.candidate.manifest_sha256, started.events[0].attempt_id, started.journal_sha256)


class MariaDBPrimaryAttemptHoldRepository:
    """Strict single-use reservation across versions within ONE explicit namespace.

    The candidate must already exist, but its journal must be exactly empty.
    A repeated reserve ALWAYS fails, even for identical input. The caller must
    roll back the WHOLE transaction/discard this repository after any failure.
    Trusted fixed-query writers only; no Python wrapper is a SQL/process sandbox.
    """

    def __init__(self, connection, storage_namespace):
        try:
            _canonical_uuid(storage_namespace, "primary_hold_namespace")
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryAttemptHoldError("primary_hold_namespace")
        self._connection, self._namespace, self._failed = connection, storage_namespace, False

    def __repr__(self):
        return "MariaDBPrimaryAttemptHoldRepository(<protected explicit local transaction>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryAttemptHoldError("primary_hold_not_pickleable")

    def _operation(self, work):
        if self._failed:
            raise PrimaryAttemptHoldError("primary_hold_transaction_unusable")
        code = None
        try:
            result = work()
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
            code = error.code if type(error) is PrimaryAttemptHoldError else "primary_hold_storage"
        if code is not None:
            raise PrimaryAttemptHoldError(code)
        return result

    @staticmethod
    def _transaction(cursor):
        cursor.execute("SELECT @@session.autocommit")
        row = cursor.fetchone()
        if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int or row != (0,):
            raise PrimaryAttemptHoldError("primary_hold_autocommit")

    def reserve(self, started_journal):
        """Append the explicit first event AND insert a STRICT immutable hold.

        No candidate/start is invented; the supplied start is rebuilt before SQL.
        Commit/close are caller duties. Uncertain commit is NOT permission to
        repeat reserve or HTTP; exact load is inspection only, never dispatch.
        """
        def work():
            started = _started_journal(started_journal)
            expected = _declaration(self._namespace, started)
            empty = DispatchJournal(started.candidate)
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                repository = MariaDBJournalRepository(self._connection, self._namespace)
                if repository.load(expected.candidate_sha256) != empty:
                    raise PrimaryAttemptHoldError("primary_hold_journal_not_empty")
                after = repository.append(expected.candidate_sha256, started.events[0],
                    expected_journal_sha256=empty.journal_sha256)
                if after != started:
                    raise PrimaryAttemptHoldError("primary_hold_start_conflict")
                cursor.execute("INSERT INTO zatca_primary_attempt_hold_v1 "
                    "(storage_namespace,source_sha256,candidate_sha256,manifest_sha256,attempt_id,started_journal_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s)", tuple(getattr(expected, name) for name in HOLD_FIELDS))
                stored = self._load(cursor, expected.source_sha256)
                if stored != expected:
                    raise PrimaryAttemptHoldError("primary_hold_conflict")
                return stored
        return self._operation(work)

    def load(self, started_journal):
        """Exact start inspection after uncertainty or later response, never a lease.

        Later UNKNOWN/HTTP events do not erase or release the original hold. No
        latest/search/current-settings fallback and no automatic repair/adoption.
        """
        def work():
            started = _started_journal(started_journal)
            expected = _declaration(self._namespace, started)
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                current = MariaDBJournalRepository(self._connection, self._namespace).load(expected.candidate_sha256)
                if current.candidate != started.candidate or current.events[:1] != started.events:
                    raise PrimaryAttemptHoldError("primary_hold_start_conflict")
                stored = self._load(cursor, expected.source_sha256)
                if stored != expected:
                    raise PrimaryAttemptHoldError("primary_hold_conflict")
                return stored
        return self._operation(work)

    def _load(self, cursor, source_sha256):
        cursor.execute("SELECT candidate_sha256,manifest_sha256,attempt_id,started_journal_sha256 "
            "FROM zatca_primary_attempt_hold_v1 WHERE storage_namespace=%s AND source_sha256=%s FOR UPDATE",
            (self._namespace, source_sha256))
        row = cursor.fetchone()
        if type(row) is not tuple or len(row) != 4:
            raise PrimaryAttemptHoldError("primary_hold_missing_or_invalid")
        return PrimaryAttemptHold(self._namespace, source_sha256, *row)
