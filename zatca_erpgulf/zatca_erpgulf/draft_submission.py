"""Retain a trusted collection operation across an ordinary ERP draft submit.

This scope neither grants permission nor chooses an issuing unit. ERP validators
and native parent/worker checks remain authoritative. Only fixed server callers
select manual/scheduled; no document flag or RPC argument carries this scope.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .saved_form_source import saved_form_name


CURRENT = ContextVar('zatca_draft_submission_origin', default=None)


@dataclass(repr=False)
class _Origin:
    site: str
    actor: str
    source: tuple
    operation: str
    closed: bool = False

    def __reduce_ex__(self, protocol):
        raise TypeError('draft_submission_origin_not_serializable')


def _review(runtime, translate):
    from .deferred_submission import _review as deferred_review
    deferred_review(runtime, translate, 'deferred_draft_origin_changed')


def _matches(current, runtime, doctype, name):
    return (
        not current.closed
        and current.site == runtime.local.site
        and current.actor == runtime.session.user
        and current.source == (doctype, name)
    )


@contextmanager
def draft_submission_origin(document, *, runtime, translate, operation):
    """Bind only a saved draft identity; never retain the mutable Document."""
    identity = document.get('doctype'), document.get('name')
    invalid = False
    try:
        saved_form_name(identity[1])
        saved_form_name(runtime.session.user)
    except ValueError:
        invalid = True
    if (invalid or identity[0] not in ('Sales Invoice', 'POS Invoice')
            or document.get('docstatus') != 0 or runtime.session.user == 'Guest'
            or type(runtime.local.site) is not str or not runtime.local.site
            or type(operation) is not str or operation not in ('manual', 'scheduled')):
        _review(runtime, translate)
    previous = CURRENT.get()
    if previous is not None:
        if not _matches(previous, runtime, *identity) or previous.operation != operation:
            _review(runtime, translate)
        yield
        return
    current = _Origin(runtime.local.site, runtime.session.user, identity, operation)
    token = CURRENT.set(current)
    try:
        yield
    finally:
        current.closed = True
        CURRENT.reset(token)


def resolve_submission_operation(runtime, doctype, name):
    """An ordinary submit remains submit; a stale/cross-source scope holds."""
    current = CURRENT.get()
    if current is None:
        return 'submit'
    if not _matches(current, runtime, doctype, name):
        # The native parent registration owns the single translated diagnostic.
        from .deferred_submission import DeferredSubmissionError
        raise DeferredSubmissionError('deferred_draft_origin_changed')
    return current.operation


def submit_draft(document, *, runtime, translate, operation):
    """Call the unchanged ERP submit lifecycle inside the fixed operation scope."""
    from .native_draft_transaction import protect_native_draft, NativeDraftTransactionError
    failed = None
    try:
        with draft_submission_origin(document, runtime=runtime, translate=translate, operation=operation):
            with protect_native_draft(document,runtime=runtime):
                return document.submit()
    except NativeDraftTransactionError as error:
        failed = error.code, error.fatal
    # A contextmanager may attach the original ERP exception while unwinding.
    # Publish a fresh static boundary error, never that private child context.
    review = NativeDraftTransactionError(failed[0],fatal=failed[1])
    runtime.log_error(title='ZATCA native draft transaction review',message=review.code)
    review.diagnostic_logged = True
    runtime.throw(translate(review.template),exc=review)
    raise review
