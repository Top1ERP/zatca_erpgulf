"""Uninstalled saved-WRITE local recovery of an EXISTING exact original only.

No builder, signing, expiry/release, new hold, HTTP, source write or raw export.
Inputs/dependencies are protected server objects, never browser JSON. Normal ACL
and a mandatory source/custody evidence guard precede owned storage. Guard True
is not independent provenance, crypto validation or an installed encrypted vault.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import _verify_rows
from .compliance_capture import _owned_transaction
from .credential_bundle_access import CredentialStorageScope
from .issuance_candidate import PreparedIssuanceCandidate
from .issuing_chain import IssuingChainState
from .journal_storage import decode_candidate_context, encode_candidate_context
from .preparation_hold import (
    MariaDBPreparationHoldRepository, PreparationHold, decode_preparation_ticket, encode_preparation_ticket,
)
from .preparation_review_access import (
    FALSE_FLAGS, PreparationReviewAccessError, _SavedReviewSource, _bind_current_source,
)
from .primary_receipt_access import _owned_saved_receipt_connection


DENIED_MESSAGE = "You do not have permission to persist local ZATCA preparation originals. Keep the exact original and ticket; do not regenerate or resend automatically."
FAILED_MESSAGE = "Local ZATCA preparation recovery could not be confirmed. Keep the exact original and ticket. Review local storage; do not regenerate or resend automatically."
TITLE = "ZATCA preparation recovery"
MESSAGES = MappingProxyType({
    "PREPARATION_ORIGINAL_STORED_LOCAL_NO_REPLAY": "The exact original was recorded or matched in local storage. This does not prove ZATCA acceptance. No new XML was generated and no request was sent.",
    "PREPARATION_RECOVERY_UNCONFIRMED_NO_REBUILD": "Local storage could not be confirmed and may already contain the original. Keep the exact original and ticket for review. Do not regenerate XML, release the hold or resend automatically.",
})


class PreparationRecoveryAccessError(PreparationReviewAccessError):
    """Static internal code; never include protected input or driver errors."""


def _validated_parts(retained):
    """Rebuild all declared/derived fields; equality is NOT origin attestation."""
    try:
        if (type(retained) is not RetainedPreparationOriginal or type(retained.scope) is not CredentialStorageScope
            or type(retained.hold) is not PreparationHold or type(retained.candidate) is not PreparedIssuanceCandidate):
            raise ValueError
        scope = CredentialStorageScope(retained.scope.site, retained.scope.storage_namespace)
        hold = PreparationHold(retained.hold.hold_id,
            decode_preparation_ticket(encode_preparation_ticket(retained.hold.ticket)),
            retained.hold.original_manifest_sha256)
        candidate = decode_candidate_context(encode_candidate_context(retained.candidate), retained.candidate.xml_bytes)
        if hold != retained.hold or candidate != retained.candidate:
            raise ValueError
        hold.ticket.validate_candidate(candidate)
        if hold.original_manifest_sha256 is not None and hold.original_manifest_sha256 != candidate.manifest_sha256:
            raise ValueError
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PreparationRecoveryAccessError("preparation_recovery_input")
    return scope, hold, candidate


@dataclass(frozen=True, repr=False)
class RetainedPreparationOriginal:
    """Caller-kept exact server original/ticket, NOT crash-proof custody.

    Keep independent protected custody after denial, interruption or uncertain
    commit. No return value authorizes rebuilding/releasing/resending. Do not
    marshal this object through an RPC, queue, log or operator response.
    """

    scope: CredentialStorageScope = field(repr=False)
    hold: PreparationHold = field(repr=False)
    candidate: PreparedIssuanceCandidate = field(repr=False)

    def __post_init__(self):
        _validated_parts(self)

    def __repr__(self):
        return "<RetainedPreparationOriginal protected exact original and ticket>"

    def __reduce__(self):
        raise TypeError("preparation_recovery_not_serializable")


class _SavedRecoverySource(_SavedReviewSource):
    SOURCE_PERMISSION = "write"
    ERROR = PreparationRecoveryAccessError
    ERROR_PREFIX = "preparation_recovery"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        return frappe, _, has_permission, None


def _submitted_selection(policy, invoice_name, doctype, actor):
    selected = policy._saved_selection(invoice_name, doctype, actor)
    if selected[0].get("docstatus") != 1:
        # Conservative local policy, not a claimed ZATCA regulation.
        raise policy.ERROR(policy.ERROR_PREFIX + "_source_status")
    return selected


def _guard_original_source(policy, retained, pinned, selected, evidence, connection=None):
    """Shared exact source/ACL/evidence boundary for recovery and custody."""
    invoice, company, owner, rows, _records, recheck = selected
    recheck()
    if connection is not None:
        _verify_rows(connection, rows)
    _bind_current_source(retained.hold, invoice, company, owner)
    if retained != pinned:
        raise policy.ERROR(policy.ERROR_PREFIX + "_input_drift")
    if evidence(policy._scope, rows, retained, connection=connection) is not True:
        raise policy.ERROR(policy.ERROR_PREFIX + "_evidence")
    if retained != pinned:
        raise policy.ERROR(policy.ERROR_PREFIX + "_input_drift")
    if connection is not None:
        _verify_rows(connection, rows)
    recheck()


def _projection(completed):
    return {"state": "PREPARATION_ORIGINAL_STORED_LOCAL_NO_REPLAY" if completed else
        "PREPARATION_RECOVERY_UNCONFIRMED_NO_REBUILD", "local_transaction_completed": completed,
        **{name: False for name in FALSE_FLAGS}}


def present_preparation_recovery(report, translate):
    """One localized display message, separate from unchanged English metadata."""
    if type(report) is not dict or not callable(translate):
        raise PreparationRecoveryAccessError("preparation_recovery_report")
    completed = report.get("local_transaction_completed")
    if type(completed) is not bool:
        raise PreparationRecoveryAccessError("preparation_recovery_report")
    expected = _projection(completed)
    if (set(report) != set(expected) or report.get("state") != expected["state"]
        or any(report[name] is not value for name, value in expected.items() if name != "state")):
        raise PreparationRecoveryAccessError("preparation_recovery_report")
    return {"title": translate(TITLE), "message": translate(MESSAGES[expected["state"]]),
        "indicator": "blue" if completed else "orange"}


class SavedPreparationRecoveryService:
    """Submitted saved source WRITE/related READ plus mandatory exact evidence.

    source_evidence_guard(scope, rows, retained, connection=...) must compare
    committed source/accounting/settings snapshot, credential epoch and original
    custody against the pinned original. No default verifier/vault is supplied.
    A success means owned commit AND close returned, not trusted storage origin
    or authority acceptance. Late denial cannot undo an already completed commit.
    """

    def __init__(self, scope, source_evidence_guard, connection_factory):
        if not callable(source_evidence_guard):
            raise PreparationRecoveryAccessError("preparation_recovery_dependencies")
        self._policy = _SavedRecoverySource(scope, connection_factory)
        self._evidence = source_evidence_guard

    def __repr__(self):
        return "<SavedPreparationRecoveryService permissioned exact local persistence>"

    def __reduce__(self):
        raise TypeError("preparation_recovery_not_serializable")

    def persist(self, invoice_name, retained, *, doctype="Sales Invoice"):
        """Explicit local redelivery ONLY; caller keeps the input independently."""
        try:
            policy = self._policy
            actor = policy._actor()
            # Independent validated objects pin every derived field as well as
            # immutable XML bytes. Later callback checks need no repeated XML
            # parsing. This is not a sandbox against arbitrary trusted Python.
            pinned = RetainedPreparationOriginal(*_validated_parts(retained))
            source = retained.candidate.context.scope
            if retained.scope != policy._scope or (source.doctype, source.invoice_name) != (doctype, invoice_name):
                raise PreparationRecoveryAccessError("preparation_recovery_target")
            selected = _submitted_selection(policy, invoice_name, doctype, actor)
            recheck = selected[-1]

            def guard(connection=None):
                _guard_original_source(policy, retained, pinned, selected, self._evidence, connection)

            guard()  # Normal saved ACL and explicit evidence BEFORE owned SQL.

            def work(connection):
                guard(connection)
                stored, after = MariaDBPreparationHoldRepository(connection, policy._scope.storage_namespace).complete(
                    retained.hold, retained.candidate)
                if (type(stored) is not PreparationHold or stored.hold_id != retained.hold.hold_id
                    or stored.ticket != retained.hold.ticket or stored.original_manifest_sha256 != retained.candidate.manifest_sha256
                    or type(after) is not IssuingChainState or after.registration != retained.hold.ticket.predecessor.registration
                    or after.last_icv < retained.candidate.artifact.icv):
                    raise PreparationRecoveryAccessError("preparation_recovery_result")
                guard(connection)

            try:
                _owned_transaction(lambda: _owned_saved_receipt_connection(policy, recheck), work)
            except frappe.PermissionError:
                raise
            except Exception:
                completed = False  # Commit may already have succeeded; NEVER retry here.
            else:
                completed = True
            guard()  # Deny disclosure after cleanup/commit; never undo or clear rows.
            return _projection(completed)
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
            frappe.PermissionError if denied else frappe.ValidationError)
