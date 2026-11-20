"""Defer native Phase2 submit-hook transport until the ERP transaction commits.

Native selections stage an authenticated durable intent in the parent ERP
transaction; only before-commit finalization makes it discoverable. Unmarked
legacy selections keep their existing identifier-only callback. Queue delivery
is never a receipt or remote acceptance guarantee.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib

from .issuing_attempt import IssuingAttemptError
from .permission_compat import saved_row_has_permission, PermissionCompatibilityError
from .zatca_runtime import PHASE_2_VALUE, is_zatca_invoice_enabled, resolve_zatca_phase


REVIEW = 'The ZATCA submission could not be deferred safely until the invoice transaction commits. No request was sent. Review the saved invoice, permissions and background worker configuration.'
QUEUE_UNKNOWN = 'The invoice transaction has committed, but background queue registration could not be confirmed. A worker may already be processing this invoice. Review the saved submission state before retrying.'
METHOD = 'zatca_erpgulf.zatca_erpgulf.deferred_submission.execute_queued_invoice'
FLAG = '_zatca_deferred_invoice_submissions'
HOOK = ContextVar('zatca_invoice_submit_hook', default=None)
DOCTYPES = ('Sales Invoice', 'POS Invoice')


class DeferredSubmissionError(IssuingAttemptError):
    def __init__(self, code):
        super().__init__(code)
        self.template = REVIEW
        self.args = (REVIEW,)


def _site(runtime):
    site = getattr(getattr(runtime, 'local', None), 'site', None)
    return ('site', site) if isinstance(site, str) and site else ('runtime', id(runtime))


def _review(runtime, translate, code, *, queue_started=False):
    error = DeferredSubmissionError(code)
    if queue_started:
        error.template = QUEUE_UNKNOWN
        error.args = (QUEUE_UNKNOWN,)
    runtime.log_error(title='ZATCA deferred submission review', message=f'{code}: {error.template}')
    error.diagnostic_logged = True
    runtime.throw(translate(error.template), exc=error)
    raise error


@dataclass(repr=False)
class _Hook:
    site: object
    doctype: str
    invoice_name: str
    closed: bool = False

    def __reduce_ex__(self, protocol):
        raise TypeError('invoice_hook_not_serializable')


@contextmanager
def invoice_submit_hook(doctype, document, *, runtime, translate):
    """Scope the original validators/route selection; do not replace Frappe APIs."""
    getter = getattr(document, 'get', None)
    name = getter('name') if callable(getter) else getattr(document, 'name', None)
    declared = getter('doctype') if callable(getter) else getattr(document, 'doctype', None)
    if doctype not in DOCTYPES or not isinstance(name, str) or not name or declared not in (None, doctype):
        _review(runtime, translate, 'deferred_source_identity')
    previous = HOOK.get()
    if previous is not None:
        if previous.closed or (previous.site, previous.doctype, previous.invoice_name) != (_site(runtime), doctype, name):
            _review(runtime, translate, 'deferred_hook_context')
        yield
        return
    current = _Hook(_site(runtime), doctype, name)
    token = HOOK.set(current)
    try:
        yield
    finally:
        current.closed = True
        HOOK.reset(token)


def _flags(runtime):
    flags = runtime.flags
    if isinstance(flags, dict):
        return flags.setdefault(FLAG, set())
    present = getattr(flags, FLAG, None)
    if present is None:
        present = set()
        setattr(flags, FLAG, present)
    return present


def is_invoice_submission_deferred(runtime, doctype, invoice_name):
    """Request-local pending callback only, never remote/queue acceptance."""
    flags = getattr(runtime, 'flags', None)
    pending = flags.get(FLAG) if isinstance(flags, dict) else getattr(flags, FLAG, None)
    return isinstance(pending, set) and (_site(runtime), doctype, invoice_name) in pending


def _require_source(runtime, translate, doctype, invoice_name):
    source = runtime.get_doc(doctype, invoice_name)
    company = runtime.get_doc('Company', source.get('company'))
    invalid = False
    try:
        engine, user = runtime.has_permission, runtime.session.user
        permitted = all(saved_row_has_permission(engine, dt, operation, doc=doc, user=user)
                        for dt, operation, doc in ((doctype,'read',source), (doctype,'write',source),
                                                  ('Company','read',company)))
    except (AttributeError, PermissionCompatibilityError):
        invalid = True
    if invalid or not permitted:
        _review(runtime, translate, 'deferred_source_access')
    if (source.get('doctype') != doctype or source.get('name') != invoice_name
            or source.get('docstatus') != 1 or source.get('company') != company.name):
        _review(runtime, translate, 'deferred_saved_source')
    return source, company


def maybe_defer_invoice_submission(doctype, invoice_name, *, runtime, translate):
    """At a native production entry, register once instead of allocating/sending.

    Earlier hook validators have already run. Ordinary calls outside this hook
    retain their contract. A fresh worker reloads all settings/ACLs after commit.
    """
    current = HOOK.get()
    if current is None:
        return False
    if (current.closed or (current.site, current.doctype, current.invoice_name)
            != (_site(runtime), doctype, invoice_name)):
        _review(runtime, translate, 'deferred_hook_context')
    _source, company = _require_source(runtime, translate, doctype, invoice_name)
    if not is_zatca_invoice_enabled(company) or resolve_zatca_phase(company) != PHASE_2_VALUE:
        _review(runtime, translate, 'deferred_phase_changed')
    pending = _flags(runtime)
    if type(pending) is not set:
        _review(runtime, translate, 'deferred_callback_state')
    actor = runtime.session.user
    key = current.site, doctype, invoice_name
    if key in pending:
        return True
    after_commit = getattr(runtime.db, 'after_commit', None)
    after_rollback = getattr(runtime.db, 'after_rollback', None)
    if not callable(getattr(after_commit, 'add', None)) or not callable(getattr(after_rollback, 'add', None)):
        _review(runtime, translate, 'deferred_transaction_callbacks')
    native_intent = None
    try:
        from .native_provider import _selection
        if _selection(runtime,doctype,invoice_name,_source) is not None:
            from .submission_intent import ParentIntent
            from .draft_submission import resolve_submission_operation
            before_commit=getattr(runtime.db,'before_commit',None)
            if not callable(getattr(before_commit,'add',None)):
                raise DeferredSubmissionError('deferred_before_commit_callback')
            native_intent=ParentIntent(runtime,doctype,invoice_name,
                intent=resolve_submission_operation(runtime,doctype,invoice_name))
    except Exception:
        failed=True
    else:
        failed=False
    if failed:
        _review(runtime,translate,'deferred_durable_intent_registration')
    pending.add(key)
    registration = {'armed':False, 'cancelled':False}

    def cancel_registration():
        registration['cancelled'] = True
        pending.discard(key)
        if native_intent is not None:
            native_intent.closed=True

    def finalize_native_intent():
        if registration['cancelled']:
            return
        if not registration['armed'] or not current.closed:
            cancel_registration()
            _review(runtime,translate,'deferred_early_commit')
        try:
            native_intent.finalize(translate=translate)
        except Exception:
            failed=True
        else:
            failed=False
        if failed:
            cancel_registration()
            _review(runtime,translate,'deferred_durable_intent_finalization')

    def enqueue_committed_source():
        if registration['cancelled']:
            return
        if not registration['armed'] or not current.closed:
            cancel_registration()
            _review(runtime, translate, 'deferred_early_commit')
        pending.discard(key)
        if _site(runtime) != current.site or runtime.session.user != actor:
            _review(runtime, translate, 'deferred_site_or_actor_changed',queue_started=native_intent is not None)
        if getattr(getattr(getattr(runtime, 'local', None), 'flags', None), 'in_migrate', False):
            _review(runtime, translate, 'deferred_migration_context',queue_started=native_intent is not None)
        if native_intent is not None:
            try:
                from .submission_intent import METHOD as INTENT_METHOD
                native_intent.require_owner()
                if not native_intent.finalized:
                    raise DeferredSubmissionError('deferred_unfinalized_intent')
                runtime.enqueue(INTENT_METHOD,queue='long',timeout=900,is_async=True,now=False,enqueue_after_commit=False,
                    job_id='zatca-intent-'+native_intent.record_id,deduplicate=True,record_id=native_intent.record_id)
            except Exception:
                failed=True
            else:
                failed=False
            native_intent.closed=True
            if failed:
                _review(runtime,translate,'deferred_queue_outcome_unknown',queue_started=True)
            return
        # Queue IDs reduce duplicate queue entries only. They are not a lease.
        digest = hashlib.sha256((doctype+'\0'+invoice_name).encode()).hexdigest()
        try:
            runtime.enqueue(METHOD, queue='long', timeout=900, is_async=True, now=False,
                            enqueue_after_commit=False, job_id='zatca-submit-'+digest,
                            deduplicate=True, doctype=doctype, invoice_name=invoice_name)
        except Exception:
            failed = True
        else:
            failed = False
        if failed:
            _review(runtime, translate, 'deferred_queue_outcome_unknown', queue_started=True)

    try:
        if native_intent is not None:
            before_commit.add(finalize_native_intent)
        after_commit.add(enqueue_committed_source)
        after_rollback.add(cancel_registration)
        registration['armed'] = True
    except Exception:
        cancel_registration()
        failed = True
    else:
        failed = False
    if failed:
        _review(runtime, translate, 'deferred_callback_registration')
    return True


def maybe_defer_native_invoice_submission(doctype, invoice_name, *, runtime, translate):
    """Cover an early native hook return without changing legacy queue policy.

    The Sales external-ID Background branch otherwise returns before reaching a
    generator's shared deferral. Outside the ERP hook this helper is inert.
    """
    current = HOOK.get()
    if current is None:
        return False
    if (current.closed or (current.site,current.doctype,current.invoice_name)
            != (_site(runtime),doctype,invoice_name)):
        _review(runtime,translate,'deferred_hook_context')
    try:
        from .native_provider import _selection
        selected = _selection(runtime,doctype,invoice_name,None)
    except Exception:
        failed = True
    else:
        failed = False
    if failed:
        _review(runtime,translate,'deferred_native_background_selection')
    if selected is None:
        return False
    return maybe_defer_invoice_submission(doctype,invoice_name,runtime=runtime,translate=translate)


def reject_submit_hook_transport(runtime, translate):
    """An extension bypassing entry deferral still cannot enter native HTTP."""
    if HOOK.get() is not None:
        _review(runtime, translate, 'deferred_inline_transport')


def execute_queued_invoice(doctype, invoice_name):
    """Internal queue target, not RPC; fresh saved permissions/settings each job.

    Native registrations enter the owned provider before status-only skipping;
    unmarked owners retain legacy processing. The fixed native builder bypasses
    the old Background early-return because delivery policy owns that decision.
    """
    import frappe
    from frappe import _
    if doctype not in DOCTYPES or not isinstance(invoice_name, str) or not invoice_name:
        _review(frappe, _, 'deferred_source_identity')
    def process(source, *, native=False):
        if doctype == 'Sales Invoice':
            from .sign_invoice import _process_submitted_invoice
        else:
            from .pos_sign import _process_submitted_invoice
        return _process_submitted_invoice(source,bypass_background_check=True) if native else _process_submitted_invoice(source)
    return _execute_saved_invoice(doctype, invoice_name, runtime=frappe, translate=_, process=process,
        native_process=lambda source:process(source,native=True))


def _execute_saved_invoice(doctype, invoice_name, *, runtime, translate, process, native_process=None):
    """Internal worker policy; the public queue target supplies its fixed process."""
    source, company = _require_source(runtime, translate, doctype, invoice_name)
    if not is_zatca_invoice_enabled(company) or resolve_zatca_phase(company) != PHASE_2_VALUE:
        return {'status':'SKIPPED', 'reason':'company_policy_changed'}
    from .native_provider import maybe_process_native_invoice
    native=maybe_process_native_invoice(doctype,invoice_name,runtime=runtime,translate=translate,
        build=process if native_process is None else native_process,intent='submit',source=source)
    if native is not None:
        return native
    if source.get('custom_zatca_status') in ('REPORTED','CLEARED'):
        return {'status':'SKIPPED', 'reason':'already_completed'}
    return process(source)
