"""Explicit bounded operator actions for an existing inactive legacy review.

Derive source, attachment, reason and cursor from authenticated saved custody.
No client-supplied invoice, approval, plaintext XML or counter seed is accepted.
Each action performs one capture page or audit segment, without authority calls.
"""

from dataclasses import asdict

import frappe
from frappe import _

from .chain_registration import ChainRegistrationError, decode_registration_header
from .dispatch_record_codec import _identifier
from .dispatch_store import DispatchStore
from .legacy_history_capture import HistoryCaptureStore
from .native_registration import _saved, review_legacy_registration
from .operation_messages import mute_operation_messages
from .worker_transaction import owned_worker_transaction


REVIEW = 'The saved history operation could not be confirmed. Review the current inactive proposal, permissions and retained evidence before continuing. No invoice was created or sent.'
CAPTURED = 'Saved history pages: {0}. Captured sources: {1}. Unresolved sources: {2}. Continue explicitly to save the next page. No invoice was created or sent.'
EXHAUSTED = 'The saved capture reaches the reviewed tail. This does not prove complete or valid history. Run the captured history audit to inspect the retained evidence.'
AUDITED = 'Checked pages: {0}. Remaining pages: {1}. Missing counter positions: {2}. Unresolved sources: {3}. Broken PIH links: {4}. Rotated-key sources: {5}.'
COMPLETE = 'The captured-ledger traversal is complete. This is a local evidence report, not approval to activate an issuer or ZATCA acceptance.'
CONTINUE = 'The audit checkpoint was saved. Continue explicitly to check the remaining pages.'
SAVED = 'This is the saved report from {0} UTC. Restart the audit explicitly for a fresh check.'
GENESIS = 'Initial PIH match: {0}.'


class HistoryReviewActionError(RuntimeError):
    http_status_code = 417

    def __init__(self, code, message=REVIEW, *, commit_uncertain=False):
        self.code = code
        self.fatal = True
        self.commit_uncertain = commit_uncertain
        super().__init__(message)


def _saved_arguments(review_id, *, runtime):
    """Own a clean read scope; release it before entering the existing service.

    Header metadata is only a locator until authenticated. Saved row permissions
    precede root XML decryption. The second owned service rechecks every current
    binding; this read scope grants no lease across the transaction boundary.
    """
    _identifier(review_id)
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise HistoryReviewActionError('history_action_manager_required')
        _saved(runtime, 'ZATCA Issuing Chain', review_id, owner.actor)
        repository = DispatchStore(owner.database, storage_namespace=owner.storage_namespace,
            cipher=owner.cipher, owner_check=owner.owner_current)
        chain = repository.lock_chain_reference(review_id)
        if (chain['registration_kind'] != 'LEGACY_REVIEWED' or chain['active'] != 0
                or chain['active_owner_key'] is not None or chain['state_version'] != 0
                or chain['tail_issuance'] is not None or chain['active_attempt'] is not None):
            raise HistoryReviewActionError('history_action_inactive_review_required')
        rows = owner.database.sql('SELECT SUBSTRING(registration_header,1,32769) AS header '
            'FROM `tabZATCA Issuing Chain` WHERE name=%s LOCK IN SHARE MODE NOWAIT', (review_id,), as_dict=True)
        owner.require_owner()
        if len(rows) != 1:
            raise HistoryReviewActionError('history_action_review_missing')
        locator, _encoded = decode_registration_header(rows[0]['header'])
        for doctype, name in ((locator['source_doctype'], locator['source_name']),
                ('Company', locator['company']), ('ZATCA ICV Counter', locator['legacy_counter']),
                ('File', locator['file_id'])):
            _saved(runtime, doctype, name, owner.actor)
        _saved(runtime, locator['owner_doctype'], locator['owner_name'], owner.actor, write=True)
        header, _xml, reason = repository.open_reviewed_registration(chain)
        if dict(header) != dict(locator):
            raise HistoryReviewActionError('history_action_locator_changed')
        capture = HistoryCaptureStore(runtime, owner, header, chain)
        head = capture.head
        exhausted = bool(head and head['through_icv'] == header['icv']
            and head['captured_sources'] == head['known_positions'])
        arguments = dict(doctype=header['source_doctype'], invoice_name=header['source_name'],
            counter_name=header['legacy_counter'], file_id=header['file_id'], reason=reason,
            expected_xml_sha256=header['xml_sha256'], history_review_id=review_id,
            history_page_after='0' if head is None else head['through_icv'])
        return arguments, exhausted


def run_saved_history_action(review_id, operation, *, runtime, translate):
    """Fixed capture/audit operations; all progress remains inactive and local."""
    if type(operation) is not str or operation not in ('capture', 'audit', 'restart-audit'):
        raise HistoryReviewActionError('history_action_operation')
    arguments, exhausted = _saved_arguments(review_id, runtime=runtime)
    if operation == 'capture' and exhausted:
        return dict(status='CAPTURE_EXHAUSTED', review_id=review_id, message=translate(EXHAUSTED))
    if operation == 'capture':
        arguments['history_capture'] = True
    else:
        arguments.update(history_page_after='0', history_audit=True,
            history_audit_restart=operation == 'restart-audit')
    result = review_legacy_registration(**arguments, runtime=runtime, translate=translate)
    if result.record_id != review_id or result.active is not False:
        raise HistoryReviewActionError('history_action_result_binding')
    if operation == 'capture':
        if result.capture is None:
            raise HistoryReviewActionError('history_action_capture_missing')
        capture = result.capture
        message = translate(CAPTURED).format(capture.head_page_number,
            capture.captured_sources, capture.unresolved_sources)
        return dict(status='CAPTURED', review_id=review_id, capture=asdict(capture), message=message)
    audit = result.audit
    if audit is None:
        raise HistoryReviewActionError('history_action_audit_missing')
    parts = [translate(AUDITED).format(audit.checked_pages, audit.remaining_pages, audit.missing_positions,
        audit.unresolved_sources, audit.broken_links, audit.rotated_sources)]
    value = 'Unknown' if audit.genesis_match is None else 'Yes' if audit.genesis_match else 'No'
    parts.append(translate(GENESIS).format(translate(value)))
    parts.append(translate(COMPLETE if audit.traversal_complete else CONTINUE))
    if audit.reused:
        parts.append(translate(SAVED).format(audit.checked_at_utc))
    return dict(status='AUDITED', review_id=review_id, audit=asdict(audit), message='<br>'.join(parts))


@frappe.whitelist(methods=['POST'])
def review_saved_history(review_id, operation):
    """One translated display result and static English-only diagnostics."""
    code = None
    uncertain = False
    try:
        with mute_operation_messages(frappe):
            result = run_saved_history_action(review_id, operation, runtime=frappe, translate=_)
    except Exception as error:
        code = error.code if isinstance(error, (HistoryReviewActionError, ChainRegistrationError)) else 'history_action_unconfirmed'
        uncertain = getattr(error, 'commit_uncertain', False) is True
    if code is not None:
        try:
            frappe.log_error(title='ZATCA saved history review', message=code)
        except Exception:
            pass
        raise HistoryReviewActionError(code, _(REVIEW), commit_uncertain=uncertain)
    return result
