"""Borrowed ERP savepoint and callback ownership for selected native drafts.

Never commit or roll back the enclosing transaction. Confirm a local rollback
before permitting a collector to continue. Lost transaction/connection/callback
provenance stops the batch; privileged SQL or external side effects are not a
sandbox boundary. Installed accounting/filesystem acceptance remains separate.
"""

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from .submission_intent import fiscal_sha
from .permission_compat import saved_row_has_permission
from .worker_transaction import CALLBACKS,current_database
from .zatca_runtime import is_zatca_invoice_enabled, resolve_zatca_phase, PHASE_2_VALUE


CURRENT = ContextVar('zatca_native_draft_transaction', default=None)
REVIEW = 'The native draft transaction needs review. Processing stopped because its transaction or isolated rollback could not be confirmed.'
SOURCE_REVIEW = 'The draft invoice could not be submitted safely. Review its saved data, issuing-unit settings and local transaction before retrying.'


class NativeDraftTransactionError(RuntimeError):
    def __init__(self, code, *, fatal=True):
        self.code = code
        self.fatal = fatal
        self.diagnostic_logged = False
        self.template = REVIEW if fatal else SOURCE_REVIEW
        super().__init__(self.template)


def _same_functions(left, right):
    return len(left) == len(right) and all(a is b for a, b in zip(left, right))


class DraftSavepoint:
    """One physical parent connection and the callbacks appended by one submit."""

    def __init__(self, runtime, document):
        self.runtime = runtime
        self.database = current_database(runtime)
        self.site = runtime.local.site
        self.actor = runtime.session.user
        self.db_name = runtime.conf.get('db_name')
        self.key = runtime.conf.get('encryption_key')
        self.connection = self.database._conn
        self.socket = getattr(self.connection, '_sock', None)
        self.source = document.doctype, document.name
        self.savepoint = 'zatca_draft_' + uuid4().hex
        self.state = 'NEW'
        self.cancellations = []
        self.active_registrations = []
        self.tripped = False
        self.queues = {}
        self.original = {}
        self.fence = self._forbid_commit
        self.require_owner()
        if CURRENT.get() is not None:
            raise NativeDraftTransactionError('native_draft_nested')
        writes = getattr(self.database, 'transaction_writes', None)
        if type(writes) is not int or writes < 0 or not isinstance(getattr(self.database, 'value_cache', None), dict):
            raise NativeDraftTransactionError('native_draft_framework_shape', fatal=False)
        self.writes = writes
        for name in CALLBACKS:
            manager = getattr(self.database, name, None)
            queue = getattr(manager, '_functions', None)
            if not isinstance(queue, deque) or not callable(getattr(manager, 'add', None)):
                raise NativeDraftTransactionError('native_draft_callback_shape', fatal=False)
            self.queues[name] = queue
            self.original[name] = tuple(queue)
        rows = self.sql('SELECT DATABASE() AS db_name', ())
        if len(rows) != 1 or rows[0]['db_name'] != self.db_name:
            raise NativeDraftTransactionError('native_draft_database')
        # Source get_doc(for_update=True) also locks its native child rows. The
        # framework's schema defaults to InnoDB. Reject known unsupported base
        # engines rather than claiming that a savepoint can undo their writes.
        current = runtime.get_doc(*self.source, for_update=True)
        if not all(saved_row_has_permission(runtime.has_permission,self.source[0],operation,
                doc=current,user=self.actor) for operation in ('read','write')):
            raise NativeDraftTransactionError('native_draft_source_access', fatal=False)
        self.require_owner()
        if (current.docstatus != 0 or current.company != document.company
                or fiscal_sha(current) != fiscal_sha(document)):
            raise NativeDraftTransactionError('native_draft_saved_source_changed', fatal=False)
        engines = self.sql('SELECT engine FROM information_schema.tables WHERE table_schema=DATABASE() '
            'AND table_type=%s LIMIT 8193', ('BASE TABLE',))
        if not engines or len(engines) > 8192 or any(row['engine'] != 'InnoDB' for row in engines):
            raise NativeDraftTransactionError('native_draft_transactional_schema', fatal=False)
        self.epoch = self.transaction_epoch()
        self.sql('SAVEPOINT ' + self.savepoint, ())
        self.state = 'ACTIVE'
        self.queues['before_commit'].appendleft(self.fence)

    def __repr__(self):
        return '<NativeDraftSavepoint protected>'

    def __reduce_ex__(self, protocol):
        raise TypeError('native_draft_savepoint_not_serializable')

    def require_owner(self):
        r = self.runtime
        c = self.connection
        if (current_database(r) is not self.database or r.local.site != self.site
                or r.session.user != self.actor or r.conf.get('db_name') != self.db_name
                or r.conf.get('encryption_key') != self.key or self.database.db_type != 'mariadb'
                or self.database.cur_db_name != self.db_name
                or self.database._conn is not c or self.socket is None or c._sock is not self.socket
                or not c.open or c.get_autocommit() is not False
                or getattr(self.database, 'auto_commit_on_many_writes', None) not in (0, False)):
            raise NativeDraftTransactionError('native_draft_owner_changed')

    def sql(self, statement, values):
        self.require_owner()
        rows = self.database.sql(statement, values, as_dict=True)
        self.require_owner()
        return rows

    def transaction_epoch(self):
        rows = self.sql('SELECT DATABASE() AS db_name,VARIABLE_NAME AS name,VARIABLE_VALUE AS value FROM information_schema.SESSION_STATUS '
            'WHERE VARIABLE_NAME IN (%s,%s)', ('COM_COMMIT', 'COM_ROLLBACK'))
        found = {row['name']: row['value'] for row in rows}
        if (len(rows) != 2 or set(found) != {'COM_COMMIT', 'COM_ROLLBACK'}
                or any(row['db_name'] != self.db_name for row in rows)
                or any(type(value) is not str or not value.isascii() or not value.isdecimal()
                       or len(value) > 20 for value in found.values())):
            raise NativeDraftTransactionError('native_draft_transaction_epoch')
        return found

    def require_epoch(self):
        if self.tripped or self.transaction_epoch() != self.epoch:
            raise NativeDraftTransactionError('native_draft_parent_transaction_changed')

    def _forbid_commit(self):
        self.tripped = True
        raise NativeDraftTransactionError('native_draft_premature_commit')

    def callback_suffixes(self):
        result = {}
        for name in CALLBACKS:
            manager = getattr(self.database, name, None)
            queue = getattr(manager, '_functions', None)
            expected = ((self.fence,) + self.original[name]) if name == 'before_commit' else self.original[name]
            if (queue is not self.queues[name] or len(queue) < len(expected)
                    or not _same_functions(tuple(queue)[:len(expected)], expected)):
                raise NativeDraftTransactionError('native_draft_parent_callbacks_changed')
            result[name] = tuple(queue)[len(expected):]
        return result

    def register(self, runtime, doctype, name, cancel, *, native, active):
        self.require_owner()
        if (self.state != 'ACTIVE' or runtime is not self.runtime or (doctype, name) != self.source
                or not native or not callable(cancel) or not callable(active)):
            raise NativeDraftTransactionError('native_draft_handoff_changed')
        self.cancellations.append(cancel)
        self.active_registrations.append(active)
        return self.require_publishable

    def require_publishable(self):
        if self.state != 'SUCCEEDED' or self.tripped:
            raise NativeDraftTransactionError('native_draft_handoff_not_publishable')

    def finish(self):
        self.require_owner()
        self.require_epoch()
        self.callback_suffixes()
        if not self.active_registrations or not all(active() is True for active in self.active_registrations):
            raise NativeDraftTransactionError('native_draft_handoff_missing', fatal=False)
        # Missing SAVEPOINT also detects an implicit DDL commit or engine abort
        # that did not increment the explicit session COMMIT/ROLLBACK counters.
        self.sql('RELEASE SAVEPOINT ' + self.savepoint, ())
        self.callback_suffixes()
        self.queues['before_commit'].popleft()
        self.state = 'SUCCEEDED'

    def rollback(self):
        # Invalidate retained commit closures even if SQL ownership was lost.
        for cancel in self.cancellations:
            cancel()
        self.require_owner()
        self.require_epoch()
        suffixes = self.callback_suffixes()
        for callback in suffixes['before_rollback']:
            callback()
            self.require_owner()
            self.require_epoch()
        self.sql('ROLLBACK TO SAVEPOINT ' + self.savepoint, ())
        self.database.value_cache.clear()
        for callback in suffixes['after_rollback']:
            callback()
            self.require_owner()
            self.require_epoch()
        # A rollback callback may write its own cleanup rows. Those also belong
        # to this failed operation, not to a later successful invoice commit.
        self.sql('ROLLBACK TO SAVEPOINT ' + self.savepoint, ())
        final_suffixes = self.callback_suffixes()
        if any(not _same_functions(final_suffixes[name], suffixes[name]) for name in CALLBACKS):
            raise NativeDraftTransactionError('native_draft_rollback_callbacks_changed')
        for name in CALLBACKS:
            self.queues[name].clear()
            self.queues[name].extend(self.original[name])
        self.sql('RELEASE SAVEPOINT ' + self.savepoint, ())
        self.database.value_cache.clear()
        self.database.transaction_writes = self.writes
        self.state = 'ROLLED_BACK'


def bind_deferred_registration(runtime, doctype, name, cancel, *, native, active):
    """Internal producer hook, no client-supplied approval or callback token."""
    scope = CURRENT.get()
    return None if scope is None else scope.register(runtime, doctype, name, cancel, native=native,active=active)


@contextmanager
def protect_native_draft(document, *, runtime):
    """Protect selected Phase2 only; retain ordinary legacy/Phase1 submit policy."""
    from .native_provider import _selection
    selection = _selection(runtime, document.doctype, document.name, document)
    if selection is None or not is_zatca_invoice_enabled(selection[1]) or resolve_zatca_phase(selection[1]) != PHASE_2_VALUE:
        yield
        return
    admission_failed = False
    try:
        scope = DraftSavepoint(runtime, document)
    except NativeDraftTransactionError:
        raise
    except Exception:
        # A locking read can fail after an engine-level parent rollback. No
        # local savepoint/epoch has been established; the collector must stop.
        admission_failed = True
    if admission_failed:
        raise NativeDraftTransactionError('native_draft_admission_unconfirmed')
    token = CURRENT.set(scope)
    caught = None
    try:
        try:
            yield
        except BaseException as error:
            caught = error
        if caught is None:
            try:
                scope.finish()
            except Exception as error:
                caught = error
        if caught is not None:
            failed = None
            try:
                scope.rollback()
            except Exception as error:
                failed = error.code if isinstance(error, NativeDraftTransactionError) else 'native_draft_rollback_unconfirmed'
            if failed is not None:
                scope.state = 'UNUSABLE'
                raise NativeDraftTransactionError(failed)
            raise caught
    finally:
        CURRENT.reset(token)
