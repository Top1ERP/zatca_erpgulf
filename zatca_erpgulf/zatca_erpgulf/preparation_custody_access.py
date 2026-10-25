"""Uninstalled saved-WRITE encrypted preparation custody and local recovery.

No sealer, builder, raw original export, HTTP, provider installation or borrowed
parent commit. Supplied keys and evidence remain audited server dependencies.
The caller keeps its exact sealed input on uncertainty; no automatic resealing.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import _discard, _verify_rows
from .compliance_capture import _owned_transaction
from .credential_bundle_access import CredentialStorageScope
from .preparation_custody import (
    MariaDBPreparationCustodyRepository, PreparationOriginalCipher, SealedPreparationOriginal,
    sealed_preparation_sha256,
)
from .preparation_hold import MariaDBPreparationHoldRepository
from .preparation_recovery_access import (
    PreparationRecoveryAccessError, RetainedPreparationOriginal, SavedPreparationRecoveryService,
    _SavedRecoverySource, _guard_original_source, _submitted_selection, _validated_parts,
)
from .preparation_review_access import FALSE_FLAGS
from .primary_receipt_access import _owned_saved_receipt_connection


DENIED_MESSAGE = "You do not have permission to store or retrieve encrypted ZATCA preparation originals. Keep the exact sealed original; do not regenerate or resend automatically."
FAILED_MESSAGE = "Encrypted ZATCA preparation custody could not be confirmed. Keep the exact sealed original for review; do not reseal, regenerate or resend automatically."
TITLE = "ZATCA preparation custody"
MESSAGES = MappingProxyType({
    "PREPARATION_CUSTODY_STORED_LOCAL_NO_REPLAY": "The exact encrypted original was stored or matched locally. The preparation hold was not completed by this operation and no request was sent.",
    "PREPARATION_CUSTODY_UNCONFIRMED_NO_REBUILD": "Encrypted storage could not be confirmed and may already contain the original. Keep the exact sealed original; do not reseal, regenerate or resend automatically.",
})


class PreparationCustodyAccessError(PreparationRecoveryAccessError):
    """Static internal errors; never expose raw originals or resource details."""


@dataclass(frozen=True, repr=False)
class PreparationCustodyResources:
    """Explicit scoped keyring, NOT a vault/tenant/provider provenance claim."""

    scope: CredentialStorageScope
    cipher: PreparationOriginalCipher = field(repr=False)

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.cipher) is not PreparationOriginalCipher:
            raise PreparationCustodyAccessError("preparation_custody_resources")
        self.scope.__post_init__()

    def __repr__(self):
        return "<PreparationCustodyResources protected scoped dependencies>"

    def __reduce__(self):
        raise TypeError("preparation_custody_resources_not_serializable")


class _SavedCustodySource(_SavedRecoverySource):
    ERROR = PreparationCustodyAccessError
    ERROR_PREFIX = "preparation_custody"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        return frappe, _, has_permission, None


def _projection(completed):
    return {"state": "PREPARATION_CUSTODY_STORED_LOCAL_NO_REPLAY" if completed else
        "PREPARATION_CUSTODY_UNCONFIRMED_NO_REBUILD", "local_transaction_completed": completed,
        **{name: False for name in FALSE_FLAGS}}


def present_preparation_custody(report, translate):
    if type(report) is not dict or not callable(translate) or type(report.get("local_transaction_completed")) is not bool:
        raise PreparationCustodyAccessError("preparation_custody_report")
    expected = _projection(report["local_transaction_completed"])
    if (set(report) != set(expected) or report.get("state") != expected["state"]
        or any(report[name] is not value for name, value in expected.items() if name != "state")):
        raise PreparationCustodyAccessError("preparation_custody_report")
    return {"title": translate(TITLE), "message": translate(MESSAGES[expected["state"]]),
        "indicator": "blue" if expected["local_transaction_completed"] else "orange"}


class SavedPreparationCustodyService:
    """Submitted saved WRITE/related READ before scoped keys or archive SQL.

    stage stores ciphertext only; load returns protected ciphertext only.
    persist_from_custody decrypts internally and delegates to exact local
    recovery, checking the SAME immutable ciphertext in its write transaction.
    No method grants rebuilding, sending, original export or manual hold release.
    """

    def __init__(self, scope, key_provider, source_evidence_guard, connection_factory):
        if not callable(key_provider) or not callable(source_evidence_guard):
            raise PreparationCustodyAccessError("preparation_custody_dependencies")
        self._policy = _SavedCustodySource(scope, connection_factory)
        self._keys, self._evidence = key_provider, source_evidence_guard

    def __repr__(self):
        return "<SavedPreparationCustodyService permissioned encrypted local custody>"

    def __reduce__(self):
        raise TypeError("preparation_custody_service_not_serializable")

    def _selection(self, invoice_name, doctype, sealed=None):
        policy = self._policy
        actor = policy._actor()
        if sealed is not None:
            if type(sealed) is not SealedPreparationOriginal:
                raise PreparationCustodyAccessError("preparation_custody_input")
            sealed.__post_init__()
            if (sealed.site, sealed.storage_namespace) != (policy._scope.site, policy._scope.storage_namespace):
                raise PreparationCustodyAccessError("preparation_custody_scope")
        selected = _submitted_selection(policy, invoice_name, doctype, actor)
        recheck = selected[-1]
        recheck()
        resources = self._keys(policy._scope)
        if type(resources) is not PreparationCustodyResources:
            raise PreparationCustodyAccessError("preparation_custody_resources")
        resources.__post_init__()
        if resources.scope != policy._scope:
            raise PreparationCustodyAccessError("preparation_custody_scope")
        recheck()
        return selected, resources.cipher

    def _guard(self, selected, sealed, retained, pinned, binding, connection=None):
        # Authenticate/decode once at entry, then pin the entire envelope and
        # an independent validated original. Repeating decryption/XML parsing
        # cannot strengthen this binding; source/ACL/evidence still recheck.
        # Storage repositories separately authenticate every loaded envelope.
        if sealed_preparation_sha256(sealed) != binding:
            raise PreparationCustodyAccessError("preparation_custody_input_drift")
        _guard_original_source(self._policy, retained, pinned, selected, self._evidence, connection)
        if sealed_preparation_sha256(sealed) != binding:
            raise PreparationCustodyAccessError("preparation_custody_input_drift")

    def stage(self, invoice_name, sealed, *, doctype="Sales Invoice"):
        """Own ciphertext storage only; do not complete or release a hold."""
        try:
            selected, cipher = self._selection(invoice_name, doctype, sealed)
            retained = cipher.open(sealed)
            pinned = RetainedPreparationOriginal(*_validated_parts(retained))
            binding = sealed_preparation_sha256(sealed)
            def guard(connection=None):
                self._guard(selected, sealed, retained, pinned, binding, connection)
            guard()
            def work(connection):
                guard(connection)
                stored = MariaDBPreparationCustodyRepository(connection, self._policy._scope.storage_namespace, cipher).stage(sealed)
                if stored != sealed:
                    raise PreparationCustodyAccessError("preparation_custody_conflict")
                guard(connection)
            try:
                _owned_transaction(lambda: _owned_saved_receipt_connection(self._policy, selected[-1]), work)
            except frappe.PermissionError:
                raise
            except Exception:
                completed = False  # Commit may have succeeded; never reseal/retry.
            else:
                completed = True
            guard()
            return _projection(completed)
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        self._fail(denied)

    def load(self, invoice_name, *, doctype="Sales Invoice"):
        """Protected ciphertext ONLY; never expose as an operator RPC result."""
        return self._load_protected(invoice_name, doctype)[0]

    def _load_protected(self, invoice_name, doctype):
        connection, failure, cleanup_failure = None, None, None
        try:
            selected, cipher = self._selection(invoice_name, doctype)
            invoice, company, _owner, rows, _records, recheck = selected
            connection = _owned_saved_receipt_connection(self._policy, recheck)
            _verify_rows(connection, rows)
            recheck()
            hold = MariaDBPreparationHoldRepository(connection, self._policy._scope.storage_namespace).load_for_source(
                doctype, company.name, invoice.name)
            if hold is None:
                raise PreparationCustodyAccessError("preparation_custody_missing_hold")
            sealed = MariaDBPreparationCustodyRepository(connection, self._policy._scope.storage_namespace, cipher).load(hold.hold_id)
            retained = cipher.open(sealed)
            if retained.scope != self._policy._scope or retained.hold.ticket != hold.ticket:
                raise PreparationCustodyAccessError("preparation_custody_binding")
            pinned = RetainedPreparationOriginal(*_validated_parts(retained))
            binding = sealed_preparation_sha256(sealed)
            self._guard(selected, sealed, retained, pinned, binding, connection)
        except BaseException as error:
            failure = error
        finally:
            if connection is not None:
                cleanup_failure = _discard(connection)
        if failure is None and cleanup_failure is None:
            try:
                self._guard(selected, sealed, retained, pinned, binding)
                return sealed, retained, cipher
            except BaseException as error:
                failure = error
        for error in (failure, cleanup_failure):
            if error is not None and not isinstance(error, Exception):
                raise error
        self._fail(isinstance(failure, frappe.PermissionError))

    def persist_from_custody(self, invoice_name, *, doctype="Sales Invoice"):
        """Fresh-process internal decryption; no plaintext export or HTTP."""
        sealed, retained, cipher = self._load_protected(invoice_name, doctype)
        binding = sealed_preparation_sha256(sealed)
        def evidence(scope, rows, original, *, connection=None):
            if original != retained or sealed_preparation_sha256(sealed) != binding:
                raise PreparationCustodyAccessError("preparation_custody_binding")
            if connection is not None:
                # Source -> chain -> hold -> ciphertext, matching stage/load.
                MariaDBPreparationHoldRepository(connection, scope.storage_namespace).load(original.hold)
                exact = MariaDBPreparationCustodyRepository(connection, scope.storage_namespace, cipher).load(original.hold.hold_id)
                if exact != sealed:
                    raise PreparationCustodyAccessError("preparation_custody_conflict")
            return self._evidence(scope, rows, original, connection=connection)
        return SavedPreparationRecoveryService(self._policy._scope, evidence, self._policy._connect).persist(
            invoice_name, retained, doctype=doctype)

    @staticmethod
    def _fail(denied):
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
            frappe.PermissionError if denied else frappe.ValidationError)
