"""Internal permissioned encrypted LOCAL custody; no HTTP or runtime activation.

Protected server dependencies/input/output ONLY, never whitelist or JSON-export.
Current saved-source permissions do not attest historical source/epoch/transport.
The caller must retain its EXACT sealed input even after denial or interruption.
"""

from dataclasses import dataclass, field
import hashlib

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import _discard, _verify_rows
from .compliance_capture import _owned_transaction
from .credential_bundle import _key_id
from .credential_bundle_access import CredentialStorageScope
from .issuance_candidate import _fingerprint, _sha256
from .primary_receipt_access import (
    PrimaryReceiptAccessError, PrimaryReceiptBinding, _SavedPrimaryReceiptSource,
    _bind_retained_primary_receipt, _owned_saved_receipt_connection,
)
from .primary_receipt_custody import (
    MariaDBPrimaryReceiptCustodyRepository, PrimaryReceiptCustodyCipher,
    SealedPrimaryReceipt, encode_retained_receipt,
)


DENIED_MESSAGE = "You do not have permission to store or retrieve staged ZATCA receipt custody."
FAILED_MESSAGE = "Staged ZATCA receipt custody access failed. Keep the original sealed receipt and do not resend automatically. No new request was sent."


class PrimaryReceiptCustodyAccessError(PrimaryReceiptAccessError):
    """Static internal codes only, translated at the permission boundary."""


@dataclass(frozen=True, repr=False)
class PrimaryReceiptCustodyBinding(PrimaryReceiptBinding):
    """Exact server-selected receipt/key declaration, not a latest-record lookup."""

    receipt_sha256: str
    custody_key_id: str
    ERROR = PrimaryReceiptCustodyAccessError
    ERROR_PREFIX = "receipt_custody_access"

    def __post_init__(self):
        super().__post_init__()
        _sha256(self.receipt_sha256, "receipt_custody_access_payload")
        _key_id(self.custody_key_id)


@dataclass(frozen=True, repr=False)
class PrimaryReceiptCustodyKeys:
    """Explicit scoped key resource, NOT provenance, discovery or a live vault."""

    scope: CredentialStorageScope
    key_id: str
    cipher: PrimaryReceiptCustodyCipher = field(repr=False)

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.cipher) is not PrimaryReceiptCustodyCipher:
            raise PrimaryReceiptCustodyAccessError("receipt_custody_access_keys")
        self.scope.__post_init__()
        _key_id(self.key_id)

    def __repr__(self):
        return "PrimaryReceiptCustodyKeys(<protected scoped dependencies>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptCustodyAccessError("receipt_custody_access_not_pickleable")


def _check_envelope(binding, sealed):
    if type(sealed) is not SealedPrimaryReceipt:
        raise PrimaryReceiptCustodyAccessError("receipt_custody_access_input")
    sealed.__post_init__()
    if (sealed.storage_namespace != binding.scope.storage_namespace
            or sealed.candidate_sha256 != _fingerprint(binding.context.scope.key_projection())
            or sealed.attempt_id != binding.attempt_id or sealed.predecessor_sha256 != binding.journal_sha256
            or sealed.receipt_sha256 != binding.receipt_sha256 or sealed.key_id != binding.custody_key_id):
        raise PrimaryReceiptCustodyAccessError("receipt_custody_access_binding")


@dataclass(frozen=True, repr=False)
class PrimaryReceiptCustodyResult:
    """Protected envelope only; no decrypted data or remote/replay permission."""

    state: str
    sealed: SealedPrimaryReceipt = field(repr=False)

    def __post_init__(self):
        if (type(self.state) is not str or self.state not in (
                "CUSTODY_COMMIT_UNCONFIRMED_NO_REPLAY", "CUSTODY_STORED_OBSERVATION_NO_REPLAY",
                "CUSTODY_READ_OBSERVATION_NO_REPLAY") or type(self.sealed) is not SealedPrimaryReceipt):
            raise PrimaryReceiptCustodyAccessError("receipt_custody_access_result")
        self.sealed.__post_init__()

    def diagnostic_projection(self):
        return {"state": self.state,
            "local_transaction_completed": self.state == "CUSTODY_STORED_OBSERVATION_NO_REPLAY",
            "provider_origin_verified": False, "historical_source_verified": False,
            "credential_epoch_verified": False, "remote_receipt_verified": False,
            "remote_acceptance_verified": False, "dispatch_authorized": False, "replay_authorized": False}

    def __repr__(self):
        return "PrimaryReceiptCustodyResult(<protected local observation>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptCustodyAccessError("receipt_custody_access_not_pickleable")


class _SavedCustodySource(_SavedPrimaryReceiptSource):
    BINDING_TYPE = PrimaryReceiptCustodyBinding
    ERROR = PrimaryReceiptCustodyAccessError
    ERROR_PREFIX = "receipt_custody_access"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        # Repository is unused by saved-row selection; no inherited inspect API
        # is exposed through the service. Keep dependencies explicit and local.
        return frappe, _, has_permission, None


class SavedPrimaryReceiptCustodyService:
    """Saved invoice WRITE/related READ + exact binding BEFORE keys/owned SQL.

    No sealer, key/DB discovery, raw plaintext export or mutable current-settings
    fallback. Read returns protected CIPHERTEXT, never plaintext. Server callers
    retain custody of their input; no result implies durable retry blocking.
    """

    def __init__(self, scope, lookup_provider, key_provider, connection_factory):
        if not callable(key_provider):
            raise PrimaryReceiptCustodyAccessError("receipt_custody_access_dependencies")
        self._policy = _SavedCustodySource(scope, lookup_provider, connection_factory)
        self._keys = key_provider

    def __repr__(self):
        return "SavedPrimaryReceiptCustodyService(<permissioned encrypted local custody>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptCustodyAccessError("receipt_custody_access_not_pickleable")

    def _selection(self, invoice_name, doctype, sealed=None):
        policy = self._policy
        actor = policy._actor()
        if sealed is not None:
            if type(sealed) is not SealedPrimaryReceipt:
                raise PrimaryReceiptCustodyAccessError("receipt_custody_access_input")
            sealed.__post_init__()
            if sealed.storage_namespace != policy._scope.storage_namespace:
                raise PrimaryReceiptCustodyAccessError("receipt_custody_access_scope")
        binding, rows, recheck = policy._saved_binding(invoice_name, doctype, actor)
        binding.__post_init__()
        if sealed is not None:
            _check_envelope(binding, sealed)
        recheck()
        resources = self._keys(policy._scope)
        if type(resources) is not PrimaryReceiptCustodyKeys:
            raise PrimaryReceiptCustodyAccessError("receipt_custody_access_keys")
        resources.__post_init__()
        if resources.scope != policy._scope or resources.key_id != binding.custody_key_id:
            raise PrimaryReceiptCustodyAccessError("receipt_custody_access_keys")
        recheck()
        return binding, rows, recheck, resources.cipher

    @staticmethod
    def _authenticate(binding, cipher, sealed):
        _check_envelope(binding, sealed)
        retained = cipher.open(sealed)
        _bind_retained_primary_receipt(binding, retained)
        if hashlib.sha256(encode_retained_receipt(retained)).hexdigest() != binding.receipt_sha256:
            raise PrimaryReceiptCustodyAccessError("receipt_custody_access_payload")

    @staticmethod
    def _guard(connection, rows, recheck):
        recheck()
        _verify_rows(connection, rows)
        recheck()

    def stage(self, invoice_name, sealed, *, doctype="Sales Invoice"):
        """Store the EXACT original envelope, never seal/reseal or send HTTP.

        Unknown acquired/SQL/commit/close returns the same envelope. Source/ACL
        denial after a completed commit refuses disclosure but cannot undo it;
        the caller MUST keep original input independently, not reconstruct it.
        """
        try:
            if sealed is None:
                self._policy._actor()
                raise PrimaryReceiptCustodyAccessError("receipt_custody_access_input")
            binding, rows, recheck, cipher = self._selection(invoice_name, doctype, sealed)
            self._authenticate(binding, cipher, sealed)
            recheck()
            def work(connection):
                self._guard(connection, rows, recheck)
                stored = MariaDBPrimaryReceiptCustodyRepository(connection, self._policy._scope.storage_namespace, cipher).stage(sealed)
                if stored != sealed:
                    raise PrimaryReceiptCustodyAccessError("receipt_custody_access_conflict")
                self._guard(connection, rows, recheck)
            try:
                _owned_transaction(lambda: _owned_saved_receipt_connection(self._policy, recheck), work)
            except Exception:
                state = "CUSTODY_COMMIT_UNCONFIRMED_NO_REPLAY"
            else:
                state = "CUSTODY_STORED_OBSERVATION_NO_REPLAY"
            recheck()
            return PrimaryReceiptCustodyResult(state, sealed)
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        self._fail(denied)

    def load(self, invoice_name, *, doctype="Sales Invoice"):
        """Exact server lookup; rollback/close and final ACL BEFORE disclosure.

        No commit, plaintext/JSON export, newest-attempt selection or acceptance
        inference. Any cleanup uncertainty refuses even ciphertext disclosure.
        """
        connection, failure, cleanup_failure = None, None, None
        try:
            binding, rows, recheck, cipher = self._selection(invoice_name, doctype)
            connection = _owned_saved_receipt_connection(self._policy, recheck)
            self._guard(connection, rows, recheck)
            key = _fingerprint(binding.context.scope.key_projection())
            sealed = MariaDBPrimaryReceiptCustodyRepository(connection, self._policy._scope.storage_namespace, cipher).load(key, binding.attempt_id)
            self._authenticate(binding, cipher, sealed)
            self._guard(connection, rows, recheck)
        except BaseException as error:
            failure = error
        finally:
            if connection is not None:
                cleanup_failure = _discard(connection)
        if failure is None and cleanup_failure is None:
            try:
                recheck()
                return PrimaryReceiptCustodyResult("CUSTODY_READ_OBSERVATION_NO_REPLAY", sealed)
            except BaseException as error:
                failure = error
        for error in (failure, cleanup_failure):
            if error is not None and not isinstance(error, Exception):
                raise error
        self._fail(isinstance(failure, frappe.PermissionError))

    @staticmethod
    def _fail(denied):
        # Called outside exception handlers: no raw parser/SQL/provider context.
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
            frappe.PermissionError if denied else frappe.ValidationError)
