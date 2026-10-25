"""Uninstalled caller-transaction chain/artifact repository, not a dispatcher.

Only explicit owned connections/namespaces. No site discovery, schema setup,
begin/commit/rollback, active Company fields or HTTP. Any failure requires whole
transaction rollback and a fresh handle; uncertain commits require exact review,
never regeneration or automatic replay. Enrollment provenance remains external.
"""

import json
from contextlib import contextmanager

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    DeclaredCredentialEpoch, _canonical_uuid, _fingerprint, compare_prepared_candidates,
    preparation_source_sha256,
)
from zatca_erpgulf.zatca_erpgulf.issuing_chain import (
    DeclaredChainRegistration, IssuingChainError, IssuingChainState, _check,
    MAX_CHAIN_ICV, initialize_declared_chain, record_generated_candidate,
    validate_chain_candidate, validate_chain_context,
)
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.journal_storage import JournalStorageError
from zatca_erpgulf.zatca_erpgulf.response_json import parse_wire_response


MAX_STATE_BYTES = 16384
REGISTRATION_FIELDS = (
    "chain_id", "registration_id", "company_name", "seller_tax_id", "environment",
    "credential_epoch", "enrollment_evidence_sha256", "origin",
)
EPOCH_FIELDS = (
    "owner_doctype", "owner_name", "version_id", "certificate_der_sha256",
    "public_key_sha256", "purpose",
)
STATE_FIELDS = (
    "schema_version", "registration", "last_icv", "previous_hash",
    "tail_key_sha256", "tail_manifest_sha256",
)


def encode_chain_state(state):
    if type(state) is not IssuingChainState:
        raise IssuingChainError("chain_state")
    content = json.dumps(state.storage_projection(), sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")
    if len(content) > MAX_STATE_BYTES:
        raise IssuingChainError("chain_payload_size")
    return content


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise IssuingChainError("chain_payload_fields")


def decode_chain_state(content):
    """Reconstruct exact declarations without today's source/settings lookup."""
    if type(content) is not bytes or not content or len(content) > MAX_STATE_BYTES:
        raise IssuingChainError("chain_payload_size")
    try:
        body = parse_wire_response(content)
        _keys(body, STATE_FIELDS)
        if type(body["schema_version"]) is not int or body["schema_version"] != 1:
            raise IssuingChainError("chain_payload_version")
        values = dict(body["registration"])
        _keys(body["registration"], REGISTRATION_FIELDS)
        _keys(values["credential_epoch"], EPOCH_FIELDS)
        values["credential_epoch"] = DeclaredCredentialEpoch(**values["credential_epoch"])
        registration = DeclaredChainRegistration(**values)
        return IssuingChainState(registration, body["last_icv"], body["previous_hash"],
            body["tail_key_sha256"], body["tail_manifest_sha256"])
    except IssuingChainError:
        raise
    except (ArtifactEvidenceError, TypeError, ValueError, KeyError):
        raise IssuingChainError("chain_payload_invalid") from None


class MariaDBIssuingChainRepository:
    """Atomically stage the exact original plus its next chain position.

    This repository records generated candidates, independent of HTTP acceptance.
    The caller owns commit/custody/signature validation; declarations and SQL do
    not establish authenticated enrollment or authority acceptance. No existing
    runtime generator, credential activator, worker or counter uses this class.
    """

    def __init__(self, connection, storage_namespace):
        _check(storage_namespace, "chain_namespace", _canonical_uuid)
        self._connection = connection
        self._namespace = storage_namespace
        self._failed = False
        self._artifacts = MariaDBJournalRepository(connection, storage_namespace)

    @contextmanager
    def _guard(self):
        if self._failed:
            raise IssuingChainError("chain_transaction_unusable")
        try:
            yield
        except IssuingChainError:
            self._failed = True
            raise
        except JournalStorageError as error:
            self._failed = True
            raise IssuingChainError("chain_artifact_" + error.code) from None
        except Exception as error:
            self._failed = True
            number = error.args[0] if error.args else None
            code = {1062: "chain_unique_conflict", 1205: "chain_lock_timeout", 1213: "chain_deadlock"}.get(
                number, "chain_database_error") if type(number) is int else "chain_database_error"
            raise IssuingChainError(code) from None
        except BaseException:
            self._failed = True
            raise

    @contextmanager
    def _cursor(self):
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            if cursor.fetchone() != (0,):
                raise IssuingChainError("chain_autocommit")
            yield cursor

    def _load(self, cursor, registration):
        cursor.execute(
            "SELECT registration_id,environment,certificate_sha256,SUBSTRING(payload_bytes,1,%s),"
            "state_sha256,last_icv FROM zatca_issuing_chain_v1 "
            "WHERE storage_namespace=%s AND chain_id=%s FOR UPDATE",
            (MAX_STATE_BYTES + 1, self._namespace, registration.chain_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise IssuingChainError("chain_missing")
        if type(row) is not tuple or len(row) != 6:
            raise IssuingChainError("chain_row_format")
        saved_id, environment, certificate, payload, digest, last_icv = row
        state = decode_chain_state(payload)
        if state.registration != registration:
            raise IssuingChainError("chain_registration_conflict")
        if (saved_id != registration.registration_id or environment != registration.environment
            or certificate != registration.credential_epoch.certificate_der_sha256
            or digest != state.state_sha256 or last_icv != str(state.last_icv)):
            raise IssuingChainError("chain_row_fingerprint")
        if state.last_icv:
            tail = self._artifacts.load(state.tail_key_sha256).candidate
            validate_chain_candidate(registration, tail)
            if (tail.manifest_sha256 != state.tail_manifest_sha256 or tail.artifact.icv != state.last_icv
                or tail.artifact.invoice_digest != state.previous_hash):
                raise IssuingChainError("chain_tail_conflict")
        else:
            # Missing chain state cannot adopt previously staged artifacts as
            # genesis, nor repair an unbound partial record by advancing it.
            cursor.execute(
                "SELECT key_sha256 FROM zatca_issuance_candidate_v1 WHERE storage_namespace=%s "
                "AND environment=%s AND chain_id=%s LIMIT 1 FOR UPDATE",
                (self._namespace, registration.environment, registration.chain_id),
            )
            if cursor.fetchone() is not None:
                raise IssuingChainError("chain_unbound_candidate")
        return state

    def create(self, registration):
        """Insert explicit genesis once; equal redelivery never resets a head."""
        with self._guard():
            initial = initialize_declared_chain(registration)
            with self._cursor() as cursor:
                cursor.execute(
                    "INSERT INTO zatca_issuing_chain_v1 "
                    "(storage_namespace,chain_id,registration_id,environment,certificate_sha256,"
                    "payload_bytes,state_sha256,last_icv) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE chain_id=chain_id",
                    (self._namespace, registration.chain_id, registration.registration_id,
                     registration.environment, registration.credential_epoch.certificate_der_sha256,
                     encode_chain_state(initial), initial.state_sha256, "0"),
                )
                return self._load(cursor, registration)

    def load(self, registration):
        """Lock and compare explicit registration; no latest/owner discovery."""
        with self._guard():
            if type(registration) is not DeclaredChainRegistration:
                raise IssuingChainError("chain_registration")
            with self._cursor() as cursor:
                return self._load(cursor, registration)

    def record(self, expected_state, candidate):
        """CAS on the retained predecessor and preserve exact redelivery bytes.

        An exact already-bound original may be reviewed after later issuance,
        without allocating a new identity or moving the current chain backward.
        A stale competing new candidate requires rollback/review, not HTTP retry.
        """
        return self._record(expected_state, candidate)

    def _record(self, expected_state, candidate, preparation_hold_id=None):
        """Held completion uses its already validated hold; not an RPC capability."""
        with self._guard():
            after = record_generated_candidate(expected_state, candidate)
            with self._cursor() as cursor:
                current = self._load(cursor, expected_state.registration)
                self._preparation_available(cursor, candidate.context, preparation_hold_id)
                if current.state_sha256 != expected_state.state_sha256:
                    if candidate.artifact.icv > current.last_icv:
                        raise IssuingChainError("chain_stale_state")
                    if not self._has_candidate(cursor, candidate.key_sha256):
                        raise IssuingChainError("chain_stale_state")
                    original = self._artifacts.load(candidate.key_sha256).candidate
                    if compare_prepared_candidates(original, candidate):
                        raise IssuingChainError("chain_redelivery_conflict")
                    return current
                if self._has_candidate(cursor, candidate.key_sha256):
                    raise IssuingChainError("chain_unbound_candidate")
                journal = self._artifacts.put(candidate)
                if journal.events:
                    raise IssuingChainError("chain_candidate_already_attempted")
                cursor.execute(
                    "UPDATE zatca_issuing_chain_v1 SET payload_bytes=%s,state_sha256=%s,last_icv=%s "
                    "WHERE storage_namespace=%s AND chain_id=%s AND state_sha256=%s AND last_icv=%s",
                    (encode_chain_state(after), after.state_sha256, str(after.last_icv), self._namespace,
                     expected_state.registration.chain_id, expected_state.state_sha256, str(expected_state.last_icv)),
                )
                if cursor.rowcount != 1:
                    raise IssuingChainError("chain_compare_and_swap")
                return after

    def begin_preparation(self, registration, context):
        """Lock an existing head and refuse a previously prepared source key.

        No allocation or durable reservation occurs here. The same caller-owned
        transaction must remain open through building, custody and record().
        Existing originals require exact review, never a replacement builder.
        """
        with self._guard():
            validate_chain_context(registration, context)
            with self._cursor() as cursor:
                before = self._load(cursor, registration)
                self._preparation_available(cursor, context)
                key = _fingerprint(context.scope.key_projection())
                if self._has_candidate(cursor, key):
                    raise IssuingChainError("chain_original_requires_review")
                if before.last_icv == MAX_CHAIN_ICV:
                    raise IssuingChainError("chain_counter_exhausted")
                return before

    def invalidate(self):
        """Block this handle after an external preparation failure; owner rolls back."""
        self._failed = True

    def _preparation_available(self, cursor, context, allowed_hold_id=None):
        """All cooperating writers honor chain AND permanent saved-source holds.

        The held repository validates full ticket/original identity before using
        allowed_hold_id. Python private methods do not sandbox arbitrary SQL.
        Missing/corrupt rehearsal schema fails closed, never skips this check.
        """
        # Two bounded unique-index point lookups, not a history-wide OR/sort.
        for column, value in (("active_chain_id", context.scope.chain_id),
                              ("source_sha256", preparation_source_sha256(context.scope))):
            cursor.execute("SELECT hold_id FROM zatca_preparation_hold_v1 "
                "WHERE storage_namespace=%s AND " + column + "=%s LIMIT 1 FOR UPDATE",
                (self._namespace, value))
            row = cursor.fetchone()
            if row is None:
                continue
            if type(row) is not tuple or len(row) != 1:
                raise IssuingChainError("preparation_hold_row")
            if allowed_hold_id is None or row != (allowed_hold_id,):
                raise IssuingChainError("preparation_held_requires_review")

    def _has_candidate(self, cursor, key_sha256):
        cursor.execute(
            "SELECT key_sha256 FROM zatca_issuance_candidate_v1 "
            "WHERE storage_namespace=%s AND key_sha256=%s FOR UPDATE",
            (self._namespace, key_sha256),
        )
        return cursor.fetchone() is not None
