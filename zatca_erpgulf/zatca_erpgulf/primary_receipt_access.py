"""Internal saved-source access to LOCAL primary receipt persistence only.

No whitelist, provider installation, hook, queue, transport, clock, file access
or invoice/accounting mutation. Historical source/provider/receipt authenticity
is not established by current permissions, a lookup declaration or local commit.
"""

import hashlib
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import (
    ArchiveInspectionEngine, ArchiveSourceAccessError, ArchiveSourceBinding,
    SavedSourceRow, _discard, _verify_rows,
)
from .issuance_candidate import _canonical_uuid, _sha256
from .journal_repository import MariaDBJournalRepository
from .journal_storage import encode_dispatch_event
from .primary_receipt_persistence import PrimaryReceiptPersistence, _validate_retained


DENIED_MESSAGE = "You do not have permission to persist staged ZATCA invoice receipts."
FAILED_MESSAGE = "Staged ZATCA invoice receipt persistence failed. Keep the original receipt and do not resend automatically. No new request was sent."


class PrimaryReceiptAccessError(ArchiveSourceAccessError):
    """Static internal code, never a raw identity/receipt/provider exception."""


@dataclass(frozen=True, repr=False)
class PrimaryReceiptBinding(ArchiveSourceBinding):
    """Exact server-declared predecessor/attempt/event, NOT origin attestation."""

    attempt_id: str
    response_event_sha256: str
    ERROR = PrimaryReceiptAccessError
    ERROR_PREFIX = "primary_receipt_access"

    def __post_init__(self):
        super().__post_init__()
        _canonical_uuid(self.attempt_id, "primary_receipt_access_attempt")
        _sha256(self.response_event_sha256, "primary_receipt_access_response")


class _SavedPrimaryReceiptSource(ArchiveInspectionEngine):
    """Reuse saved owner/route/revision policy, with invoice WRITE not read."""

    BINDING_TYPE = PrimaryReceiptBinding
    ROW_TYPE = SavedSourceRow
    SOURCE_PERMISSION = "write"
    ERROR = PrimaryReceiptAccessError
    ERROR_PREFIX = "primary_receipt_access"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        return frappe, _, has_permission, MariaDBJournalRepository

    def _check_saved_status(self, binding, invoice):
        # Receipt capture may precede any accepted/rejected invoice label. Keep
        # status in the exact row/revision projection, never use it as acceptance.
        pass


class SavedPrimaryReceiptService:
    """Protected server input/output, not an operator JSON or dispatch endpoint.

    System Manager/Administrator + direct source WRITE and related saved-row
    READ ACL are required. Lookups/factories are server dependencies, never
    request arguments. Current routing/owner/source must still match; historical
    drift needs a separate reviewed policy, not a fallback. Keep the original
    retained receipt even when access is revoked after a successful commit.
    """

    def __init__(self, scope, lookup_provider, connection_factory):
        self._policy = _SavedPrimaryReceiptSource(scope, lookup_provider, connection_factory)

    def __repr__(self):
        return "SavedPrimaryReceiptService(<permissioned protected local persistence>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptAccessError("primary_receipt_access_not_pickleable")

    def persist(self, invoice_name, receipt, *, doctype="Sales Invoice"):
        """Authorize before lookup/acquisition; guard source in the SAME write tx.

        No ambient Frappe commit/rollback. SQL locks serialize declared source
        projections, not permission tables/authority epochs. Final ACL/source
        check refuses disclosure after closure, but cannot undo an owned commit.
        """
        try:
            policy = self._policy
            actor = policy._actor()
            _validate_retained(receipt)
            if receipt.storage_namespace != policy._scope.storage_namespace:
                raise PrimaryReceiptAccessError("primary_receipt_access_scope")
            candidate = receipt.before.candidate
            if (candidate.context.scope.doctype != doctype or candidate.context.scope.invoice_name != invoice_name):
                raise PrimaryReceiptAccessError("primary_receipt_access_target")
            binding, rows, recheck = policy._saved_binding(invoice_name, doctype, actor)
            if (binding.context != candidate.context or binding.uuid != candidate.artifact.uuid
                    or binding.icv != candidate.artifact.icv or binding.journal_sha256 != receipt.before.journal_sha256
                    or binding.attempt_id != receipt.response_event.attempt_id
                    or binding.response_event_sha256 != hashlib.sha256(encode_dispatch_event(receipt.response_event)).hexdigest()):
                raise PrimaryReceiptAccessError("primary_receipt_access_binding")
            recheck()

            def factory():
                owned, failure, cleanup_failure = None, None, None
                try:
                    recheck()
                    ambient = frappe.db
                    ambient_raw = getattr(ambient, "_conn", None)
                    acquired = policy._connect(policy._scope)
                    # Recognizable borrowed handles must NEVER be cleaned up.
                    if acquired is ambient or acquired is ambient_raw:
                        raise PrimaryReceiptAccessError("primary_receipt_access_borrowed")
                    owned = acquired
                    if any(not callable(getattr(owned, method, None)) for method in ("cursor", "commit", "rollback", "close")):
                        raise PrimaryReceiptAccessError("primary_receipt_access_connection")
                    owned.rollback()  # Fresh OWNED handle only; no pending observations.
                    recheck()
                    return owned
                except BaseException as error:
                    failure = error
                if owned is not None:
                    cleanup_failure = _discard(owned)
                for error in (failure, cleanup_failure):
                    if error is not None and not isinstance(error, Exception):
                        raise error
                raise PrimaryReceiptAccessError("primary_receipt_access_acquisition")

            def guard(connection, retained):
                if retained is not receipt:
                    raise PrimaryReceiptAccessError("primary_receipt_access_retained")
                recheck()
                _verify_rows(connection, rows)
                recheck()
                return True

            result = PrimaryReceiptPersistence(policy._scope.storage_namespace,
                connection_factory=factory, source_guard=guard).persist(receipt)
            recheck()  # Denial here cannot undo storage; caller retains input.
            return result
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        if denied:
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        frappe.throw(_(FAILED_MESSAGE))
