"""Explicit Linux/Unix MariaDB provider for LOCAL receipt storage, not installed.

No tenant/config/password discovery, arbitrary connector, TCP/TLS fallback,
reconnect, schema provisioning, authority I/O or receipt authenticity claim.
Server-owned configuration/credential custody/registration must be audited.
"""

from dataclasses import dataclass, field
import os
import re
import socket
import stat
import struct

import pymysql

from .credential_bundle_access import CredentialStorageScope
from .issuance_candidate import _canonical_uuid


LOCK_WAIT_SECONDS = 1


class ReceiptProviderError(ValueError):
    """Static internal code only; never expose credentials/paths/driver errors."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class ReceiptDatabaseBinding:
    """Explicit provisioning declaration, NOT proof of correct tenant origin."""

    scope: CredentialStorageScope
    unix_socket: str = field(repr=False)
    socket_device: int
    socket_inode: int
    socket_uid: int
    database: str = field(repr=False)
    server_id: int
    registration_id: str

    def __post_init__(self):
        try:
            if type(self.scope) is not CredentialStorageScope:
                raise ValueError
            self.scope.__post_init__()
            if (type(self.unix_socket) is not str or not self.unix_socket.startswith("/")
                    or os.path.normpath(self.unix_socket) != self.unix_socket
                    or len(self.unix_socket.encode("utf-8")) > 100
                    or any(ord(char) < 32 or ord(char) == 127 for char in self.unix_socket)
                    or type(self.database) is not str or re.fullmatch(r"[A-Za-z0-9_]{1,64}", self.database) is None):
                raise ValueError
            if (any(type(value) is not int for value in (self.socket_device, self.socket_inode, self.socket_uid, self.server_id))
                    or self.socket_device < 0 or self.socket_inode <= 0
                    or not 0 <= self.socket_uid < 2**32 or not 0 <= self.server_id < 2**32):
                raise ValueError
            _canonical_uuid(self.registration_id, "receipt_provider_registration")
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ReceiptProviderError("receipt_provider_binding")

    def __repr__(self):
        return "ReceiptDatabaseBinding(<explicit protected provisioning declaration>)"

    def __reduce_ex__(self, protocol):
        raise ReceiptProviderError("receipt_provider_not_pickleable")


@dataclass(frozen=True, repr=False)
class ReceiptDatabaseCredentials:
    """Ephemeral local DB login, never an invoice/CSID credential or UI payload."""

    user: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self):
        if (type(self.user) is not str or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.user) is None
                or type(self.password) is not str or len(self.password) > 4096 or "\x00" in self.password):
            raise ReceiptProviderError("receipt_provider_credentials")

    def __repr__(self):
        return "ReceiptDatabaseCredentials(<protected ephemeral local login>)"

    def __reduce_ex__(self, protocol):
        raise ReceiptProviderError("receipt_provider_not_pickleable")


def _check_socket(binding):
    """Exact provisioned pathname/inode/owner, not directory or symlink fallback."""
    current = os.lstat(binding.unix_socket)
    if (os.path.realpath(binding.unix_socket) != binding.unix_socket
            or not stat.S_ISSOCK(current.st_mode)
            or (current.st_dev, current.st_ino, current.st_uid) != (
                binding.socket_device, binding.socket_inode, binding.socket_uid)):
        raise ReceiptProviderError("receipt_provider_socket")


def _peer_pid(raw, binding):
    """Validate the owned local peer BEFORE setting any SQL session options."""
    _check_socket(binding)
    peer = raw._sock  # Provider owns a directly created PyMySQL connection.
    if peer.family != socket.AF_UNIX or peer.getpeername() != binding.unix_socket:
        raise ReceiptProviderError("receipt_provider_peer")
    pid, uid, _gid = struct.unpack("iII", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if pid <= 0 or uid != binding.socket_uid:
        raise ReceiptProviderError("receipt_provider_peer")
    return pid


def _set_owned_lock_waits(raw, binding):
    """Set fixed SESSION-only waits on a newly created owned connection.

    Never change GLOBAL variables or an ambient handle. This bounds individual
    row/metadata lock waits, not total transaction time or statement cancellation.
    Rejection after handoff poisons the handle rather than silently repairing it.
    """
    _peer_pid(raw, binding)
    with raw.cursor() as cursor:
        cursor.execute("SET SESSION innodb_lock_wait_timeout=1")
        cursor.execute("SET SESSION lock_wait_timeout=1")


def _check_connection(raw, binding):
    """Check owned peer, bounded waits, target and locked registration.

    Fixed read-only probes; never repair registration or changed wait settings.
    A matching marker does not attest authority response or tenant provenance.
    """
    pid = _peer_pid(raw, binding)
    with raw.cursor() as cursor:
        cursor.execute("SELECT @@session.innodb_lock_wait_timeout,@@session.lock_wait_timeout")
        waits = cursor.fetchone()
        if (type(waits) is not tuple or len(waits) != 2
                or any(type(value) is not int or value != LOCK_WAIT_SECONDS for value in waits)):
            raise ReceiptProviderError("receipt_provider_lock_waits")
        cursor.execute("SELECT DATABASE(),@@server_id,@@session.autocommit,CONNECTION_ID()")
        row = cursor.fetchone()
        if (type(row) is not tuple or len(row) != 4 or row[:3] != (binding.database, binding.server_id, 0)
                or type(row[1]) is not int or type(row[2]) is not int or type(row[3]) is not int or row[3] <= 0):
            raise ReceiptProviderError("receipt_provider_target")
        cursor.execute("SELECT site,registration_id FROM zatca_receipt_storage_binding_v1 "
            "WHERE storage_namespace=%s FOR UPDATE", (binding.scope.storage_namespace,))
        if cursor.fetchone() != (binding.scope.site, binding.registration_id):
            raise ReceiptProviderError("receipt_provider_registration")
    return row[3], pid


class _OwnedReceiptConnection:
    """Narrow owner handle: recheck before cursors/commit; always allow cleanup.

    Not a SQL sandbox. Only reviewed fixed-query writers may use returned cursors;
    arbitrary SQL/DDL could bypass transaction guarantees. No ping/reconnect or
    raw-handle delegation. Failed identity checks poison this handle permanently.
    """

    def __init__(self, raw, binding):
        self._raw, self._binding, self._failed, self._closed = raw, binding, False, False
        self._session = None

    def __repr__(self):
        return "OwnedReceiptConnection(<protected pinned local transaction>)"

    def __reduce_ex__(self, protocol):
        raise ReceiptProviderError("receipt_provider_not_pickleable")

    @property
    def closed(self):
        return self._closed

    def _check(self):
        if self._closed or self._failed:
            raise ReceiptProviderError("receipt_provider_unusable")
        try:
            self._binding.__post_init__()
            session = _check_connection(self._raw, self._binding)
            if self._session is not None and session != self._session:
                raise ReceiptProviderError("receipt_provider_session")
            self._session = session
        except Exception:
            self._failed = True
        if self._failed:
            raise ReceiptProviderError("receipt_provider_check")

    def cursor(self):
        self._check()
        return self._raw.cursor()

    def commit(self):
        self._check()
        try:
            self._raw.commit()  # Unknown commit is NOT retried on this handle.
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        if self._failed:
            raise ReceiptProviderError("receipt_provider_commit")

    def rollback(self):
        self._raw.rollback()  # Owned cleanup remains possible after failed checks.

    def close(self):
        self._closed = True
        self._raw.close()


class UnixPrimaryReceiptProvider:
    """Server-configured callable for the permissioned service, NOT activated.

    Constructs a fresh driver connection itself. No caller/raw connection factory
    or ambient Frappe handle can be supplied. Explicit local credentials are
    requested only after scope/socket checks; no DSN/config/secret discovery.
    The provider owns acquisition failure cleanup; returned handles are caller-
    owned. Configuration correctness and account least privilege remain audits.
    """

    def __init__(self, binding, credentials_provider):
        if type(binding) is not ReceiptDatabaseBinding or not callable(credentials_provider):
            raise ReceiptProviderError("receipt_provider_dependencies")
        binding.__post_init__()
        self._binding, self._credentials = binding, credentials_provider

    def __repr__(self):
        return "UnixPrimaryReceiptProvider(<explicit protected local dependencies>)"

    def __reduce_ex__(self, protocol):
        raise ReceiptProviderError("receipt_provider_not_pickleable")

    def __call__(self, scope):
        owned, failure = None, None
        try:
            self._binding.__post_init__()
            if type(scope) is not CredentialStorageScope or scope != self._binding.scope:
                raise ReceiptProviderError("receipt_provider_scope")
            _check_socket(self._binding)  # Reject wrong target before secrets/connect.
            credentials = self._credentials(scope)
            if type(credentials) is not ReceiptDatabaseCredentials:
                raise ReceiptProviderError("receipt_provider_credentials")
            credentials.__post_init__()
            raw = pymysql.connect(unix_socket=self._binding.unix_socket, database=self._binding.database,
                user=credentials.user, password=credentials.password, autocommit=False, charset="utf8mb4",
                connect_timeout=5, read_timeout=5, write_timeout=5, local_infile=False, read_default_file=None)
            owned = _OwnedReceiptConnection(raw, self._binding)
            _set_owned_lock_waits(raw, self._binding)
            owned._check()
            return owned
        except BaseException as error:
            failure = error
        if owned is not None:
            for cleanup in (owned.rollback, owned.close):
                try:
                    cleanup()
                except BaseException as error:
                    if not isinstance(error, Exception) and isinstance(failure, Exception):
                        failure = error
        if not isinstance(failure, Exception):
            raise failure
        raise ReceiptProviderError("receipt_provider_acquisition")
