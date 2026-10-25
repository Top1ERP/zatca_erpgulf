"""Uninstalled permissioned LOCAL preparation review, metadata/display only.

No whitelist, live provider, builder, sender, release, commit, repair or original
export. Saved READ ACL precedes bounded source lookup; owned SQL checks precede
disclosure and cleanup never touches recognizable ambient parent connections.
Current permissions/declarations are not historical source/crypto provenance.
"""

from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from .api_routing import resolve_api_route
from .archive_source_access import (
    ArchiveInspectionEngine, ArchiveSourceAccessError, FIELDS, SavedSourceRow, _discard, _verify_rows,
)
from .credential_bundle_access import CredentialStorageScope
from .preparation_hold import MariaDBPreparationHoldRepository, PreparationHold
from .primary_receipt_access import _owned_saved_receipt_connection


DENIED_MESSAGE = "You do not have permission to review local ZATCA preparation holds."
FAILED_MESSAGE = "Local ZATCA preparation review could not be confirmed. No invoice or hold was changed and no request was sent."
TITLE = "ZATCA preparation review"
MESSAGES = MappingProxyType({
    "PENDING_ORIGINAL_UNCONFIRMED_REVIEW": "A local preparation hold exists, but no completed original is recorded. The builder may already have run. Review protected custody; do not regenerate XML or release the hold automatically.",
    "ORIGINAL_RECORDED_LOCAL_NO_REPLAY": "The exact original is recorded locally. This does not prove ZATCA acceptance. This review does not authorize rebuilding, resending or releasing the hold.",
    "NO_LOCAL_HOLD_OBSERVED_REVIEW": "No local preparation hold was observed. This does not prove that no invoice was generated or sent. Review the source and storage mapping before taking any action.",
})
FALSE_FLAGS = ("provider_origin_verified", "historical_source_verified", "credential_epoch_verified",
    "signature_verified", "durable_custody_verified", "remote_acceptance_verified",
    "rebuild_authorized", "replay_authorized", "dispatch_authorized", "hold_release_authorized")
REVIEW_FIELDS = MappingProxyType({**FIELDS,
    "Sales Invoice": ("company", "docstatus", "custom_zatca_pos_name"),
    "POS Invoice": ("company", "docstatus", "custom_zatca_pos_name"),
})


class PreparationReviewAccessError(ArchiveSourceAccessError):
    """Static code, never a raw SQL/identity/ticket/provider exception."""


class SavedPreparationReviewRow(SavedSourceRow):
    # Pending review must not require a saved UUID/ICV or accepted invoice label.
    # This minimal current revision/ownership projection is NOT a tax snapshot.
    FIELD_MAP = REVIEW_FIELDS


class _SavedReviewSource(ArchiveInspectionEngine):
    ROW_TYPE = SavedPreparationReviewRow
    ERROR = PreparationReviewAccessError
    ERROR_PREFIX = "preparation_review"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def __init__(self, scope, connection_factory):
        if type(scope) is not CredentialStorageScope or not callable(connection_factory):
            raise self.ERROR("preparation_review_dependencies")
        self._scope, self._connect = scope, connection_factory

    def _dependencies(self):
        return frappe, _, has_permission, None  # Saved selection only, no archive binding.


def _projection(hold):
    if hold is not None and type(hold) is not PreparationHold:
        raise PreparationReviewAccessError("preparation_review_result")
    recorded = None if hold is None else hold.original_manifest_sha256 is not None
    state = ("NO_LOCAL_HOLD_OBSERVED_REVIEW" if hold is None else
        "ORIGINAL_RECORDED_LOCAL_NO_REPLAY" if recorded else "PENDING_ORIGINAL_UNCONFIRMED_REVIEW")
    return {"state": state, "original_recorded_observed": recorded,
        "active_chain_hold_observed": None if hold is None else not recorded,
        **{name: False for name in FALSE_FLAGS}}


def present_preparation_review(report, translate):
    """One translated app-owned display message; NEVER store it as diagnostics."""
    if type(report) is not dict or not callable(translate):
        raise PreparationReviewAccessError("preparation_review_report")
    state = report.get("state")
    if type(state) is not str or state not in MESSAGES:
        raise PreparationReviewAccessError("preparation_review_report")
    recorded = {"NO_LOCAL_HOLD_OBSERVED_REVIEW": None, "PENDING_ORIGINAL_UNCONFIRMED_REVIEW": False,
                "ORIGINAL_RECORDED_LOCAL_NO_REPLAY": True}[state]
    expected = {"state": state, "original_recorded_observed": recorded,
        "active_chain_hold_observed": None if recorded is None else not recorded,
        **{name: False for name in FALSE_FLAGS}}
    if set(report) != set(expected) or any(report[name] is not value for name, value in expected.items() if name != "state"):
        raise PreparationReviewAccessError("preparation_review_report")
    return {"title": translate(TITLE), "message": translate(MESSAGES[state]),
        "indicator": "blue" if recorded is True else "orange"}


def _bind_current_source(hold, invoice, company, owner):
    if hold is None:
        return
    if type(hold) is not PreparationHold:
        raise PreparationReviewAccessError("preparation_review_result")
    context = hold.ticket.context
    source = context.scope
    if ((source.doctype, source.invoice_name, source.company_name) != (invoice.doctype, invoice.name, company.name)
        or source.seller_tax_id != company.get("tax_id") or source.environment != company.get("custom_select")
        or (context.credential_epoch.owner_doctype, context.credential_epoch.owner_name) != (owner.doctype, owner.name)
        or resolve_api_route(company, context.route.endpoint) != context.route):
        raise PreparationReviewAccessError("preparation_review_source_binding")


class SavedPreparationReviewService:
    """Administrator/System Manager AND saved source/related READ, no mutations.

    Source/Company/owner revisions are locked before and after archive access.
    Draft/submitted/cancelled sources may be reviewed regardless of saved UUID,
    ICV/status. Changed seller/environment/owner/route requires separate review,
    not a silent historical-access fallback. Provider origin remains a gate.
    """

    def __init__(self, scope, connection_factory):
        self._policy = _SavedReviewSource(scope, connection_factory)

    def __repr__(self):
        return "<SavedPreparationReviewService permissioned metadata only>"

    def __reduce__(self):
        raise TypeError("preparation_review_not_serializable")

    def inspect(self, invoice_name, *, doctype="Sales Invoice"):
        connection, failure, cleanup_failure, report = None, None, None, None
        try:
            policy = self._policy
            actor = policy._actor()
            invoice, company, owner, rows, _records, recheck = policy._saved_selection(invoice_name, doctype, actor)
            connection = _owned_saved_receipt_connection(policy, recheck)
            _verify_rows(connection, rows)
            recheck()
            hold = MariaDBPreparationHoldRepository(connection, policy._scope.storage_namespace).load_for_source(
                doctype, company.name, invoice.name)
            _bind_current_source(hold, invoice, company, owner)
            _verify_rows(connection, rows)
            recheck()
            report = _projection(hold)
        except BaseException as error:
            failure = error
        finally:
            if connection is not None:
                cleanup_failure = _discard(connection)
        if failure is None and cleanup_failure is None:
            try:
                recheck()  # Late actor/source/ACL changes deny even metadata.
                return report
            except BaseException as error:
                failure = error
        for error in (failure, cleanup_failure):
            if error is not None and not isinstance(error, Exception):
                raise error
        denied = isinstance(failure, frappe.PermissionError)
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
            frappe.PermissionError if denied else frappe.ValidationError)
