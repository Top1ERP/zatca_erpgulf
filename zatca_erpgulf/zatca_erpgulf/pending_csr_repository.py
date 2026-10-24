"""Explicit-transaction immutable pending CSR staging; no runtime installation.

No source/ACL/provider discovery, active pointer, SQL DDL, begin/commit/rollback,
HTTP, clock, retry or credential migration. Every error poisons this handle:
the caller must roll back its whole transaction and discard the repository.
"""

import hashlib

from zatca_erpgulf.zatca_erpgulf.csr_draft import CSRPreparationContext
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope
from zatca_erpgulf.zatca_erpgulf.pending_csr_binding import (
    MAX_BINDING_BYTES, PendingCSRBindingRecord, decode_binding_record,
)
from zatca_erpgulf.zatca_erpgulf.pending_csr import (
    MAX_MANIFEST_BYTES, MAX_PLAINTEXT_BYTES, PendingCSRCipher, PendingCSRStorageError,
    SealedPendingCSR, validate_namespace,
)


class MariaDBPendingCSRRepository:
    def __init__(self, connection, storage_namespace, cipher):
        validate_namespace(storage_namespace)
        valid = False
        try:
            valid = type(cipher) is PendingCSRCipher and callable(getattr(connection, "cursor", None))
        except Exception:
            pass
        if not valid:
            raise PendingCSRStorageError("cipher")
        self._connection, self._namespace, self._cipher = connection, storage_namespace, cipher
        self._failed = False

    def __repr__(self):
        return "MariaDBPendingCSRRepository(<caller-owned staging transaction>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRStorageError("not_pickleable")

    def _run_operation(self, worker, *arguments):
        """Normalize outside the catch; generator contexts can restore raw errors."""
        if self._failed:
            raise PendingCSRStorageError("transaction_unusable")
        code = None
        try:
            return worker(*arguments)
        except PendingCSRStorageError as error:
            self._failed = True
            code = error.code.removeprefix("pending_csr_")
        except Exception as error:
            self._failed = True
            arguments = BaseException.args.__get__(error, type(error))
            number = arguments[0] if arguments else None
            code = {1062: "unique_conflict", 1205: "lock_timeout", 1213: "deadlock"}.get(number, "database_error") if type(number) is int else "database_error"
        except BaseException:
            self._failed = True
            raise
        if code is not None:
            raise PendingCSRStorageError(code)

    @staticmethod
    def _transaction(cursor):
        cursor.execute("SELECT @@session.autocommit")
        if cursor.fetchone() != (0,):
            raise PendingCSRStorageError("autocommit")

    def stage(self, sealed):
        """Stage once or accept exact redelivery, never reseal/overwrite/commit."""
        return self._run_operation(self._stage, sealed)

    def _stage(self, sealed):
        if type(sealed) is not SealedPendingCSR or sealed.storage_namespace != self._namespace:
            raise PendingCSRStorageError("envelope")
        self._cipher.open(sealed)
        context = sealed.manifest.context
        with self._connection.cursor() as cursor:
            self._transaction(cursor)
            self._insert_envelope(cursor, sealed, redelivery=True)
            stored = self._load(cursor, context.draft_id, missing_code="identity_collision")
            if stored != sealed:
                raise PendingCSRStorageError("draft_conflict")
            return stored

    def _insert_envelope(self, cursor, sealed, *, redelivery):
        context = sealed.manifest.context
        cursor.execute(
            "INSERT INTO zatca_pending_csr_v1 "
            "(storage_namespace,draft_id,slot_sha256,flow_id,manifest_bytes,manifest_sha256,key_id,nonce,ciphertext) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            + (" ON DUPLICATE KEY UPDATE draft_id=draft_id" if redelivery else ""),
            (self._namespace, context.draft_id, context.slot.sha256, context.flow_id,
             sealed.manifest_bytes, sealed.manifest_sha256, sealed.key_id, sealed.nonce, sealed.ciphertext),
        )

    def stage_bound(self, binding, original):
        """Stage a NEW envelope/history pair or accept an existing EXACT pair.

        Never backfill an unbound envelope or repair an orphan history row. A
        race after absent reads must win a plain INSERT or fail, not silently
        adopt another writer's envelope. Caller owns whole-transaction rollback.
        This records supplied declarations, not saved-source/ACL provenance.
        """
        return self._run_operation(self._stage_bound, binding, original, False)

    def create_bound(self, binding, original):
        """Initial capture only: never recapture even an exact existing pair."""
        return self._run_operation(self._stage_bound, binding, original, True)

    def _stage_bound(self, binding, original, require_new):
        expected = PendingCSRBindingRecord.capture(binding, original)
        if original.storage_namespace != self._namespace:
            raise PendingCSRStorageError("binding")
        original = SealedPendingCSR(original.storage_namespace, original.manifest_bytes,
                                    original.key_id, original.nonce, original.ciphertext)
        self._cipher.open(original)
        context = expected.binding.manifest.context
        with self._connection.cursor() as cursor:
            self._transaction(cursor)
            envelope = self._load(cursor, context.draft_id, allow_missing=True)
            record = self._load_binding(cursor, context.draft_id, allow_missing=True)
            if (envelope is None) != (record is None):
                raise PendingCSRStorageError("binding_unpaired")
            if require_new and envelope is not None:
                raise PendingCSRStorageError("binding_exists")
            if envelope is None:
                self._insert_envelope(cursor, original, redelivery=False)
                encoded = expected.encode()
                cursor.execute(
                    "INSERT INTO zatca_pending_csr_source_binding_v1 "
                    "(storage_namespace,draft_id,slot_sha256,flow_id,site,binding_bytes,binding_sha256,envelope_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (self._namespace, context.draft_id, context.slot.sha256, context.flow_id,
                     expected.binding.scope.site, encoded, hashlib.sha256(encoded).hexdigest(), expected.envelope_sha256),
                )
                envelope = self._load(cursor, context.draft_id)
                record = self._load_binding(cursor, context.draft_id)
            if envelope != original or record.encode() != expected.encode() or not record.matches(envelope):
                raise PendingCSRStorageError("binding_conflict")
            return record.binding

    def load_binding(self, scope, context):
        """Load ONE exact paired declaration; no latest, backfill or public export."""
        return self._run_operation(self._load_bound, scope, context)

    def _load_bound(self, scope, context):
        if type(scope) is not CredentialStorageScope or scope.storage_namespace != self._namespace:
            raise PendingCSRStorageError("binding")
        scope.__post_init__()
        self._validate_context(context)
        with self._connection.cursor() as cursor:
            self._transaction(cursor)
            envelope = self._load(cursor, context.draft_id)
            record = self._load_binding(cursor, context.draft_id)
            if record.binding.scope != scope or record.binding.manifest.context != context:
                raise PendingCSRStorageError("context")
            if not record.matches(envelope):
                raise PendingCSRStorageError("binding_conflict")
            return record.binding

    def _load_binding(self, cursor, draft_id, *, allow_missing=False):
        cursor.execute(
            "SELECT slot_sha256,flow_id,site,SUBSTRING(binding_bytes,1,%s),binding_sha256,envelope_sha256 "
            "FROM zatca_pending_csr_source_binding_v1 WHERE storage_namespace=%s AND draft_id=%s FOR UPDATE",
            (MAX_BINDING_BYTES + 1, self._namespace, draft_id),
        )
        row = cursor.fetchone()
        if row is None:
            if allow_missing:
                return None
            raise PendingCSRStorageError("binding_missing")
        if type(row) is not tuple or len(row) != 6:
            raise PendingCSRStorageError("row_format")
        slot, flow, site, encoded, fingerprint, envelope_fingerprint = row
        record = decode_binding_record(encoded)
        context = record.binding.manifest.context
        if (record.binding.scope.storage_namespace != self._namespace or context.draft_id != draft_id
                or context.slot.sha256 != slot or context.flow_id != flow or record.binding.scope.site != site
                or hashlib.sha256(encoded).hexdigest() != fingerprint or record.envelope_sha256 != envelope_fingerprint):
            raise PendingCSRStorageError("row_binding")
        return record

    def load(self, context):
        """Exact declared context only, not latest/owner/environment fallback."""
        return self._run_operation(self._load_context, context)

    def observe(self, original):
        """Compare retained ciphertext without inserting or returning stored data.

        Absence is only an actual empty exact SELECT, never a caught SQL, key,
        authentication or decoding failure. A different valid envelope is a
        conflict, even when its decrypted material happens to be identical.
        The caller owns rollback/close and must not treat absence as retry consent.
        """
        return self._run_operation(self._observe, original)

    def _observe(self, original):
        if type(original) is not SealedPendingCSR or original.storage_namespace != self._namespace:
            raise PendingCSRStorageError("envelope")
        original = SealedPendingCSR(original.storage_namespace, original.manifest_bytes,
                                    original.key_id, original.nonce, original.ciphertext)
        self._cipher.open(original)  # Validate the retained input even when absent.
        with self._connection.cursor() as cursor:
            self._transaction(cursor)
            stored = self._load(cursor, original.manifest.context.draft_id, allow_missing=True)
            if stored is None:
                return "ABSENT_OBSERVED"
            return "EXACT_OBSERVED" if stored == original else "CONFLICT_OBSERVED"

    @staticmethod
    def _validate_context(context):
        valid = False
        try:
            if type(context) is CSRPreparationContext:
                context.__post_init__()
                valid = True
        except Exception:
            pass
        if not valid:
            raise PendingCSRStorageError("context")

    def _load_context(self, context):
        self._validate_context(context)
        with self._connection.cursor() as cursor:
            self._transaction(cursor)
            sealed = self._load(cursor, context.draft_id)
            if sealed.manifest.context != context:
                raise PendingCSRStorageError("context")
            return sealed

    def _load(self, cursor, draft_id, *, missing_code="missing", allow_missing=False):
        cursor.execute(
            "SELECT slot_sha256,flow_id,SUBSTRING(manifest_bytes,1,%s),manifest_sha256,key_id,nonce,"
            "SUBSTRING(ciphertext,1,%s) FROM zatca_pending_csr_v1 "
            "WHERE storage_namespace=%s AND draft_id=%s FOR UPDATE",
            (MAX_MANIFEST_BYTES + 1, MAX_PLAINTEXT_BYTES + 17, self._namespace, draft_id),
        )
        row = cursor.fetchone()
        if row is None:
            if allow_missing:
                return None
            raise PendingCSRStorageError(missing_code)
        if type(row) is not tuple or len(row) != 7:
            raise PendingCSRStorageError("row_format")
        slot, flow, metadata, fingerprint, key_id, nonce, ciphertext = row
        sealed = SealedPendingCSR(self._namespace, metadata, key_id, nonce, ciphertext)
        context = sealed.manifest.context
        if (context.draft_id != draft_id or context.slot.sha256 != slot
                or context.flow_id != flow or sealed.manifest_sha256 != fingerprint):
            raise PendingCSRStorageError("row_binding")
        self._cipher.open(sealed)
        return sealed
