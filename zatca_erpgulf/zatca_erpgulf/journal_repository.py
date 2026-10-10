"""Explicit MariaDB storage boundary, not a live Frappe service or dispatcher.

The caller supplies a dedicated transactional DB-API connection and namespace.
No connection discovery, schema installation, begin/commit/rollback, HTTP, clock,
credential lookup, counter allocation or invoice/PIH writes occur here. Roll back
the WHOLE transaction and discard this repository after any operation error.
Never hold its row locks while sending HTTP. No current runtime path uses it.
"""

from contextlib import contextmanager
from uuid import UUID

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import MAX_XML_BYTES
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import (
    DispatchEvent, DispatchJournal, DispatchJournalError, append_dispatch_event,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    IssuanceContractError, PreparedIssuanceCandidate, _canonical_uuid, _sha256,
    compare_prepared_candidates,
)
from zatca_erpgulf.zatca_erpgulf.journal_storage import (
    JournalStorageError, decode_candidate_context, decode_dispatch_event,
    encode_candidate_context, encode_dispatch_event,
)
from zatca_erpgulf.zatca_erpgulf.response_json import MAX_RESPONSE_BYTES


def _reference(value, code, validator):
    try:
        validator(value, code)
    except IssuanceContractError:
        raise JournalStorageError(code) from None


class MariaDBJournalRepository:
    """Serialize a single candidate's append-only observed journal, not a lease.

    Row locks plus expected journal hash prevent stale competing event appends.
    Identity unique keys reject UUID/ICV reuse, but do not allocate identity or
    prove chain mapping. Returning a journal does not prove the caller committed.
    SQL identifiers are fixed; scope names and other values are parameters.
    Rehearsal DDL is not a schema installer, hook or production migration.
    """

    def __init__(self, connection, storage_namespace):
        _reference(storage_namespace, "repository_namespace", _canonical_uuid)
        self._connection = connection
        self._namespace = storage_namespace
        self._failed = False

    @contextmanager
    def _preflight(self):
        """Invalid arguments also poison an already used transaction handle."""
        if self._failed:
            raise JournalStorageError("repository_transaction_unusable")
        try:
            yield
        except JournalStorageError:
            self._failed = True
            raise

    @contextmanager
    def _operation(self):
        if self._failed:
            raise JournalStorageError("repository_transaction_unusable")
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT @@session.autocommit")
                if cursor.fetchone() != (0,):
                    raise JournalStorageError("repository_autocommit")
                yield cursor
        except JournalStorageError:
            self._failed = True
            raise
        except (DispatchJournalError, IssuanceContractError) as error:
            self._failed = True
            raise JournalStorageError(error.code) from None
        except Exception as error:
            self._failed = True
            number = error.args[0] if error.args else None
            code = {
                1062: "repository_unique_conflict", 1205: "repository_lock_timeout",
                1213: "repository_deadlock",
            }.get(number, "repository_database_error") if type(number) is int else "repository_database_error"
            raise JournalStorageError(code) from None

    def put(self, candidate):
        """Insert once or compare the existing record; never replace issued bytes.

        The duplicate clause only writes the same primary key to itself. Other
        unique-key conflicts cannot update evidence and fail explicit comparison.
        Caller rollback remains mandatory on conflicts/deadlocks/unknown commit.
        """
        with self._preflight():
            if type(candidate) is not PreparedIssuanceCandidate:
                raise JournalStorageError("repository_candidate")
            context_bytes = encode_candidate_context(candidate)
        empty = DispatchJournal(candidate)
        scope, artifact = candidate.context.scope, candidate.artifact
        with self._operation() as cursor:
            cursor.execute(
                "INSERT INTO zatca_issuance_candidate_v1 "
                "(storage_namespace, key_sha256, manifest_sha256, context_bytes, xml_bytes, "
                "file_sha256, environment, chain_id, invoice_uuid, icv, journal_sha256, revision) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0) "
                "ON DUPLICATE KEY UPDATE key_sha256=key_sha256",
                (self._namespace, candidate.key_sha256, candidate.manifest_sha256, context_bytes,
                 candidate.xml_bytes, artifact.file_sha256, scope.environment, scope.chain_id,
                 str(UUID(artifact.uuid)), str(artifact.icv), empty.journal_sha256),
            )
            journal = self._load(cursor, candidate.key_sha256, missing_code="repository_identity_collision")
            if compare_prepared_candidates(journal.candidate, candidate):
                raise JournalStorageError("repository_candidate_conflict")
            return journal

    def load(self, key_sha256):
        """Lock and reconstruct exact stored evidence; no current settings input."""
        with self._preflight():
            _reference(key_sha256, "repository_key", _sha256)
        with self._operation() as cursor:
            return self._load(cursor, key_sha256)

    def _load(self, cursor, key_sha256, *, missing_code="repository_missing"):
        cursor.execute(
            "SELECT manifest_sha256, context_bytes, SUBSTRING(xml_bytes,1,%s), file_sha256, "
            "environment, chain_id, invoice_uuid, icv, journal_sha256, revision, attempt_id "
            "FROM zatca_issuance_candidate_v1 WHERE storage_namespace=%s AND key_sha256=%s FOR UPDATE",
            (MAX_XML_BYTES + 1, self._namespace, key_sha256),
        )
        row = cursor.fetchone()
        if row is None:
            raise JournalStorageError(missing_code)
        if type(row) is not tuple or len(row) != 11:
            raise JournalStorageError("repository_row_format")
        manifest, context, xml, file_hash, environment, chain, uuid, icv, journal_hash, revision, attempt_id = row
        candidate = decode_candidate_context(context, xml)
        scope, artifact = candidate.context.scope, candidate.artifact
        if (
            candidate.key_sha256 != key_sha256 or candidate.manifest_sha256 != manifest
            or artifact.file_sha256 != file_hash or scope.environment != environment
            or scope.chain_id != chain or str(UUID(artifact.uuid)) != uuid or str(artifact.icv) != icv
        ):
            raise JournalStorageError("repository_candidate_fingerprint")
        cursor.execute(
            "SELECT sequence, event_id, payload_bytes, SUBSTRING(response_bytes,1,%s) "
            "FROM zatca_dispatch_event_v1 WHERE storage_namespace=%s AND key_sha256=%s "
            "ORDER BY sequence LIMIT 4 FOR UPDATE",
            (MAX_RESPONSE_BYTES + 1, self._namespace, key_sha256),
        )
        events = []
        for event_row in cursor.fetchall():
            if type(event_row) is not tuple or len(event_row) != 4:
                raise JournalStorageError("repository_row_format")
            sequence, event_id, payload, response = event_row
            event = decode_dispatch_event(payload, response)
            if event.sequence != sequence or event.event_id != event_id:
                raise JournalStorageError("repository_event_fingerprint")
            events.append(event)
        journal = DispatchJournal(candidate, tuple(events))
        expected_attempt = events[0].attempt_id if events else None
        if (
            type(revision) is not int or revision != len(events)
            or journal.journal_sha256 != journal_hash or attempt_id != expected_attempt
        ):
            raise JournalStorageError("repository_journal_fingerprint")
        return journal

    def append(self, key_sha256, event, *, expected_journal_sha256):
        """Append under a row lock/CAS; identical event redelivery is idempotent.

        A stale hash cannot append new facts. Equal event-ID repeats return the
        already stored history even after a later receipt; changed facts conflict.
        No second attempt, retry permission or automatic response-based PIH write.
        """
        with self._preflight():
            _reference(key_sha256, "repository_key", _sha256)
            _reference(expected_journal_sha256, "repository_expected_journal", _sha256)
            if type(event) is not DispatchEvent:
                raise JournalStorageError("repository_event")
        with self._operation() as cursor:
            before = self._load(cursor, key_sha256)
            # Validate duplicate-ID facts before CAS, preserving local idempotence.
            recorded = next((item for item in before.events if item.event_id == event.event_id), None)
            if recorded is not None:
                if recorded != event:
                    raise JournalStorageError("event_id_conflict")
                return before
            if before.journal_sha256 != expected_journal_sha256:
                raise JournalStorageError("repository_stale_journal")
            after = append_dispatch_event(before, event)
            cursor.execute(
                "INSERT INTO zatca_dispatch_event_v1 "
                "(storage_namespace,key_sha256,sequence,event_id,payload_bytes,response_bytes) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (self._namespace, key_sha256, event.sequence, event.event_id,
                 encode_dispatch_event(event), event.response_bytes),
            )
            cursor.execute(
                "UPDATE zatca_issuance_candidate_v1 SET journal_sha256=%s,revision=%s,attempt_id=%s "
                "WHERE storage_namespace=%s AND key_sha256=%s AND journal_sha256=%s AND revision=%s",
                (after.journal_sha256, len(after.events), after.events[0].attempt_id,
                 self._namespace, key_sha256, before.journal_sha256, len(before.events)),
            )
            if cursor.rowcount != 1:
                raise JournalStorageError("repository_compare_and_swap")
            return after
