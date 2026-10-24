"""Explicit-transaction immutable pending CSR staging; no runtime installation.

No source/ACL/provider discovery, active pointer, SQL DDL, begin/commit/rollback,
HTTP, clock, retry or credential migration. Every error poisons this handle:
the caller must roll back its whole transaction and discard the repository.
"""

from zatca_erpgulf.zatca_erpgulf.csr_draft import CSRPreparationContext
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
            cursor.execute(
                "INSERT INTO zatca_pending_csr_v1 "
                "(storage_namespace,draft_id,slot_sha256,flow_id,manifest_bytes,manifest_sha256,key_id,nonce,ciphertext) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE draft_id=draft_id",
                (self._namespace, context.draft_id, context.slot.sha256, context.flow_id,
                 sealed.manifest_bytes, sealed.manifest_sha256, sealed.key_id, sealed.nonce, sealed.ciphertext),
            )
            stored = self._load(cursor, context.draft_id, missing_code="identity_collision")
            if stored != sealed:
                raise PendingCSRStorageError("draft_conflict")
            return stored

    def load(self, context):
        """Exact declared context only, not latest/owner/environment fallback."""
        return self._run_operation(self._load_context, context)

    def _load_context(self, context):
        valid = False
        try:
            if type(context) is CSRPreparationContext:
                context.__post_init__()
                valid = True
        except Exception:
            pass
        if not valid:
            raise PendingCSRStorageError("context")
        with self._connection.cursor() as cursor:
            self._transaction(cursor)
            sealed = self._load(cursor, context.draft_id)
            if sealed.manifest.context != context:
                raise PendingCSRStorageError("context")
            return sealed

    def _load(self, cursor, draft_id, *, missing_code="missing"):
        cursor.execute(
            "SELECT slot_sha256,flow_id,SUBSTRING(manifest_bytes,1,%s),manifest_sha256,key_id,nonce,"
            "SUBSTRING(ciphertext,1,%s) FROM zatca_pending_csr_v1 "
            "WHERE storage_namespace=%s AND draft_id=%s FOR UPDATE",
            (MAX_MANIFEST_BYTES + 1, MAX_PLAINTEXT_BYTES + 17, self._namespace, draft_id),
        )
        row = cursor.fetchone()
        if row is None:
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
