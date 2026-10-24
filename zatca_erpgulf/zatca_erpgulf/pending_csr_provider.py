"""Explicit single-use Unix resources for pending CSR staging, not installed.

Reuse reviewed local socket/peer/session checks; pin a distinct pending-domain
registration and storage-key ID. No site/config/credential discovery, TCP,
connector injection, reconnect, DDL, HTTP, key generation or automatic commit.
Provisioning/account privileges/key provenance remain independent audit gates.
"""

from dataclasses import dataclass, field

import pymysql

from . import primary_receipt_provider as local_sql
from .credential_bundle_access import CredentialStorageScope
from .pending_csr import PendingCSRCipher, _key_id
from .pending_csr_access import PendingCSRResources


REGISTRATION_TABLE = "zatca_pending_csr_storage_binding_v1"
ERROR_CODES = frozenset(("binding", "keys", "dependencies", "scope", "acquisition", "unavailable",
                         "unusable", "check", "cursor", "commit", "rollback", "close", "not_pickleable"))


class PendingCSRProviderError(ValueError):
    """Allowlisted static English code, never paths, keys or driver details."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in ERROR_CODES else "acquisition"
        super().__init__("pending_csr_provider_" + self.code)


@dataclass(frozen=True, repr=False)
class PendingCSRDatabaseBinding(local_sql.ReceiptDatabaseBinding):
    """Server-provisioned declaration, not independently proven tenant origin."""

    storage_key_id: str

    def __post_init__(self):
        valid = False
        try:
            super().__post_init__()
            _key_id(self.storage_key_id)
            valid = True
        except Exception:
            pass
        if not valid:
            raise PendingCSRProviderError("binding")

    def __repr__(self):
        return "PendingCSRDatabaseBinding(<protected local provisioning declaration>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRProviderError("not_pickleable")


@dataclass(frozen=True, repr=False)
class PendingCSRStorageKeys:
    """Explicit scoped cipher/key ID, not discovery or actual-key provenance."""

    scope: CredentialStorageScope
    key_id: str
    cipher: PendingCSRCipher = field(repr=False, compare=False)

    def __post_init__(self):
        valid = False
        try:
            if type(self.scope) is not CredentialStorageScope or type(self.cipher) is not PendingCSRCipher:
                raise PendingCSRProviderError("keys")
            self.scope.__post_init__()
            _key_id(self.key_id)
            self.cipher._cipher(self.key_id)  # Require explicit availability, never generate a key.
            valid = True
        except Exception:
            pass
        if not valid:
            raise PendingCSRProviderError("keys")

    def __repr__(self):
        return "PendingCSRStorageKeys(<protected scoped pending-only cipher>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRProviderError("not_pickleable")


class _OwnedPendingCSRConnection(local_sql._OwnedReceiptConnection):
    """Pinned caller-owned handle, not a SQL/ACL sandbox or commit coordinator."""

    def __repr__(self):
        return "OwnedPendingCSRConnection(<protected pinned local transaction>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRProviderError("not_pickleable")

    def _check(self):
        if self._closed or self._failed:
            raise PendingCSRProviderError("unusable")
        try:
            self._binding.__post_init__()
            session = local_sql._check_connection(self._raw, self._binding, registration_table=REGISTRATION_TABLE)
            with self._raw.cursor() as cursor:
                cursor.execute("SELECT key_id FROM zatca_pending_csr_storage_binding_v1 "
                               "WHERE storage_namespace=%s FOR UPDATE", (self._binding.scope.storage_namespace,))
                if cursor.fetchone() != (self._binding.storage_key_id,):
                    raise PendingCSRProviderError("check")
            if self._session is not None and session != self._session:
                raise PendingCSRProviderError("check")
            self._session = session
        except Exception:
            self._failed = True
        except BaseException:
            self._failed = True
            raise
        if self._failed:
            raise PendingCSRProviderError("check")

    def _call(self, operation, method):
        code = operation
        try:
            return method()
        except PendingCSRProviderError as error:
            code = error.code
        except Exception:
            pass
        except BaseException:
            self._failed = True
            raise
        self._failed = True
        raise PendingCSRProviderError(code)

    def cursor(self):
        return self._call("cursor", super().cursor)

    def commit(self):
        # Inherited commit rechecks the pinned session/marker, never retries an
        # unknown outcome. It does NOT authorize current source/ACL activation.
        return self._call("commit", super().commit)

    def rollback(self):
        if self._closed:
            raise PendingCSRProviderError("unusable")
        return self._call("rollback", self._raw.rollback)

    def close(self):
        if self._closed:
            return None
        self._closed = True
        return self._call("close", self._raw.close)


class UnixPendingCSRResourceProvider:
    """Single-use lease callable; supply only to the saved-source service.

    Credentials use the shared explicit local DB-login contract. Keys are asked
    for only after the pending registration/target is checked. The provider owns
    failed acquisition cleanup; a successful handoff is caller-owned, including
    after the service later denies access. Retain this lease and original sealed
    draft; the caller must explicitly roll back/close on service failure.
    """

    def __init__(self, binding, credentials_provider, key_provider):
        if (type(binding) is not PendingCSRDatabaseBinding or not callable(credentials_provider)
                or not callable(key_provider)):
            raise PendingCSRProviderError("dependencies")
        binding.__post_init__()
        self._binding, self._credentials, self._keys = binding, credentials_provider, key_provider
        self._state, self._resources = "NEW", None
        self._transaction_owner = None

    def __repr__(self):
        return "UnixPendingCSRResourceProvider(<single-use protected local lease>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRProviderError("not_pickleable")

    @property
    def resources(self):
        """Protected server handoff for explicit caller cleanup, never UI/JSON."""
        if self._state != "HANDED_OFF":
            raise PendingCSRProviderError("unavailable")
        return self._resources

    def __call__(self, scope):
        if self._transaction_owner is not None:
            if self._state == "ACQUIRING":
                self._state = "FAILED"
            raise PendingCSRProviderError("unusable")
        return self._acquire(scope)

    def _claim_for_transaction(self, owner):
        """Exclusive internal lifecycle claim; no IO or borrowed-handle cleanup."""
        if type(owner) is not object or self._state != "NEW" or self._transaction_owner is not None:
            raise PendingCSRProviderError("unusable")
        self._transaction_owner = owner

    def _acquire_for_transaction(self, scope, owner):
        if owner is not self._transaction_owner or self._transaction_owner is None:
            raise PendingCSRProviderError("unusable")
        return self._acquire(scope)

    def _acquire(self, scope):
        if self._state != "NEW":
            if self._state == "ACQUIRING":
                self._state = "FAILED"
            raise PendingCSRProviderError("unusable")
        self._state = "ACQUIRING"
        owned, failure = None, None
        try:
            self._binding.__post_init__()
            if type(scope) is not CredentialStorageScope or scope != self._binding.scope:
                raise PendingCSRProviderError("scope")
            scope.__post_init__()
            local_sql._check_socket(self._binding)  # Scope/socket before any login secret.
            credentials = self._credentials(scope)
            if type(credentials) is not local_sql.ReceiptDatabaseCredentials:
                raise PendingCSRProviderError("acquisition")
            credentials.__post_init__()
            if self._state != "ACQUIRING":
                raise PendingCSRProviderError("unusable")
            raw = pymysql.connect(unix_socket=self._binding.unix_socket, database=self._binding.database,
                user=credentials.user, password=credentials.password, autocommit=False, charset="utf8mb4",
                connect_timeout=5, read_timeout=5, write_timeout=5, local_infile=False, read_default_file=None)
            owned = _OwnedPendingCSRConnection(raw, self._binding)
            local_sql._set_owned_lock_waits(raw, self._binding)
            owned._check()
            if self._state != "ACQUIRING":
                raise PendingCSRProviderError("unusable")
            keys = self._keys(scope)
            if type(keys) is not PendingCSRStorageKeys:
                raise PendingCSRProviderError("keys")
            keys.__post_init__()
            if keys.scope != scope or keys.key_id != self._binding.storage_key_id or self._state != "ACQUIRING":
                raise PendingCSRProviderError("keys")
            owned._check()  # Recheck peer/session/marker after the trusted key callback.
            result = PendingCSRResources(scope, keys.key_id, owned, keys.cipher)
            self._resources, self._state = result, "HANDED_OFF"
            return result
        except BaseException as error:
            failure = error
        self._state = "FAILED"
        if owned is not None:
            # Only the freshly created handle is touched. Attempt BOTH cleanup
            # operations; preserve interruptions without exposing raw diagnostics.
            for cleanup in (owned.rollback, owned.close):
                try:
                    cleanup()
                except BaseException as error:
                    if not isinstance(error, Exception) and isinstance(failure, Exception):
                        failure = error
        if not isinstance(failure, Exception):
            raise failure
        raise PendingCSRProviderError("acquisition")
