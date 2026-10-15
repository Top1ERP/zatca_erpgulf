"""Permissioned metadata-only LOCAL pair access, NOT runtime activation.

Server dependencies and ORIGINAL request/envelope only. Caller retains both
even after denial, interruption or uncertain commit. No sender, observer,
retainer installation, raw export, Frappe endpoint, job, UI or schema change.
Current permissions and typed declarations do not attest historical provenance.
"""

from dataclasses import dataclass
import hashlib
import json

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import _verify_rows
from .issuance_candidate import _sha256
from .primary_capture_access import PrimaryCaptureBinding, _bind_request
from .primary_receipt_access import (
    PrimaryReceiptAccessError, _SavedPrimaryReceiptSource, _owned_saved_receipt_connection,
)
from .primary_receipt_custody import AAD_FIELDS, SealedPrimaryReceipt
from .primary_receipt_custody_access import PrimaryReceiptCustodyKeys
from .primary_receipt_reconciliation import PrimaryReceiptReconciliation, PrimaryReconciliationResult, _references


DENIED_MESSAGE = "You do not have permission to inspect or persist staged ZATCA receipt pairs."
FAILED_MESSAGE = "Staged ZATCA receipt pair access failed. Keep the original request and sealed receipt. Do not resend automatically. No new request was sent."


class PrimaryReconciliationAccessError(PrimaryReceiptAccessError):
    """Static internal code, translated/redacted at the outer boundary."""


def sealed_envelope_sha256(sealed):
    """Bounded exact seal fingerprint for explicit server lookup declarations.

    This is NOT signature/AAD generation, a ciphertext codec or origin proof.
    The domain/length-framed metadata + fixed-size nonce + remaining ciphertext
    bind every envelope field, distinguishing independently sealed equal text.
    """
    if type(sealed) is not SealedPrimaryReceipt:
        raise PrimaryReconciliationAccessError("primary_pair_access_envelope")
    sealed.__post_init__()
    header = json.dumps({name: getattr(sealed, name) for name in AAD_FIELDS},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(b"zatca-primary-pair-access-envelope/v1\0" + len(header).to_bytes(8, "big")
        + header + sealed.nonce + sealed.ciphertext).hexdigest()


@dataclass(frozen=True, repr=False)
class PrimaryReconciliationBinding(PrimaryCaptureBinding):
    """Exact server-declared request/start/key/payload AND original ciphertext."""

    receipt_sha256: str
    envelope_sha256: str
    ERROR = PrimaryReconciliationAccessError
    ERROR_PREFIX = "primary_pair_access"

    def __post_init__(self):
        super().__post_init__()
        for value in (self.receipt_sha256, self.envelope_sha256):
            _sha256(value, "primary_pair_access_fingerprint")


class _SavedReconciliationSource(_SavedPrimaryReceiptSource):
    BINDING_TYPE = PrimaryReconciliationBinding
    ERROR = PrimaryReconciliationAccessError
    ERROR_PREFIX = "primary_pair_access"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        return frappe, _, has_permission, None  # Saved-row selection only.


def _bind(binding, request, sealed):
    _bind_request(binding, request)
    if (sealed.storage_namespace != binding.scope.storage_namespace
            or sealed.receipt_sha256 != binding.receipt_sha256 or sealed.key_id != binding.custody_key_id
            or sealed_envelope_sha256(sealed) != binding.envelope_sha256):
        raise PrimaryReconciliationAccessError("primary_pair_access_binding")


class SavedPrimaryReconciliationService:
    """Saved source WRITE/related READ before scoped keys and OWNED SQL.

    Both methods require exact protected server inputs, never browser payloads.
    Inspect does not commit; persist is explicit LOCAL storage, not a resend.
    Current owner/settings drift needs review, not a historical ACL fallback.
    """

    def __init__(self, scope, lookup_provider, key_provider, connection_factory):
        if not callable(key_provider):
            raise PrimaryReconciliationAccessError("primary_pair_access_dependencies")
        self._policy = _SavedReconciliationSource(scope, lookup_provider, connection_factory)
        self._keys = key_provider

    def __repr__(self):
        return "SavedPrimaryReconciliationService(<permissioned local pair metadata>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReconciliationAccessError("primary_pair_access_not_pickleable")

    def inspect(self, invoice_name, request, sealed, *, doctype="Sales Invoice"):
        """Inspect exact pair; owned rollback/close and final ACL before metadata."""
        return self._run(invoice_name, request, sealed, doctype=doctype, persist=False)

    def persist(self, invoice_name, request, sealed, *, doctype="Sales Invoice"):
        """Explicit local pair storage only; caller keeps originals independently.

        Late denial refuses diagnostics but cannot undo already committed rows.
        No result/caught failure authorizes transport, resealing or hold release.
        """
        return self._run(invoice_name, request, sealed, doctype=doctype, persist=True)

    def _run(self, invoice_name, supplied, sealed, *, doctype, persist):
        try:
            policy = self._policy
            actor = policy._actor()
            request = _references(supplied, sealed)  # Rebuilt/detached before saved lookup.
            source = request.started.candidate.context.scope
            if (sealed.storage_namespace != policy._scope.storage_namespace
                    or source.doctype != doctype or source.invoice_name != invoice_name):
                raise PrimaryReconciliationAccessError("primary_pair_access_target")
            binding, rows, recheck = policy._saved_binding(invoice_name, doctype, actor)
            binding.__post_init__()
            _bind(binding, request, sealed)
            recheck()
            resources = self._keys(policy._scope)
            if type(resources) is not PrimaryReceiptCustodyKeys:
                raise PrimaryReconciliationAccessError("primary_pair_access_keys")
            resources.__post_init__()
            if resources.scope != policy._scope or resources.key_id != binding.custody_key_id:
                raise PrimaryReconciliationAccessError("primary_pair_access_keys")
            recheck()

            def guard(connection, pinned):
                if pinned != request:
                    raise PrimaryReconciliationAccessError("primary_pair_access_request")
                _bind(binding, pinned, sealed)
                recheck()
                _verify_rows(connection, rows)
                recheck()
                return True

            service = PrimaryReceiptReconciliation(policy._scope.storage_namespace, resources.cipher,
                connection_factory=lambda: _owned_saved_receipt_connection(policy, recheck), source_guard=guard)
            # Core authenticates the complete retained payload BEFORE acquisition.
            result = service.persist(request, sealed) if persist else service.inspect(request, sealed)
            if (type(result) is not PrimaryReconciliationResult or result.request != request or result.sealed is not sealed):
                raise PrimaryReconciliationAccessError("primary_pair_access_result")
            result.__post_init__()
            _bind(binding, request, sealed)
            recheck()  # Deny even metadata after source/actor/ACL drift or cleanup.
            return result.diagnostic_projection()
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
            frappe.PermissionError if denied else frappe.ValidationError)
