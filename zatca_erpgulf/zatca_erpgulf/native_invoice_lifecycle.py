"""Protect saved native source identities in the caller's ERP transaction.

This is a retention guard, not an authority acceptance checker. Even an unsent
generated original owns a local chain position. A queued request also retains
its source identity until a reviewed transition can safely retire that request.
No counter rewind, receipt inference, history deletion or parent commit occurs.
"""

import frappe
from frappe import _

from .native_provider import _schema_available
from .saved_form_source import saved_form_name
from .worker_transaction import current_database


SOURCE_TABLES = {
    'Sales Invoice': 'tabSales Invoice',
    'POS Invoice': 'tabPOS Invoice',
}
REVIEW = 'This invoice has a native ZATCA issuance or queued request, or its history could not be verified. Cancellation, deletion or renaming requires a reviewed history transition. This does not mean ZATCA accepted the invoice.'


class NativeInvoiceLifecycleError(RuntimeError):
    http_status_code = 417

    def __init__(self, code, message=REVIEW):
        self.code = code
        super().__init__(message)


def inspect_source_lifecycle(doc, *, runtime, method=None, old=None, new=None, merge=False):
    """Current locked negative evidence only; never assert remote acceptance.

    Source locking serializes with native preparation. Shared current reads see
    committed custody/requests even behind an older RR snapshot. No current
    Company phase, rollout switch, UUID, display status or signing key can erase
    that history. Unissued sources without requests retain normal ERP behavior.
    """
    table = SOURCE_TABLES.get(doc.doctype)
    if table is None:
        return
    hint = doc.get('custom_zatca_issuing_unit')
    if not _schema_available(runtime) and not (type(hint) is str and hint.startswith('egs:')):
        return  # Older installations without native owner fields keep their hooks.
    saved_form_name(doc.name)
    if method == 'before_rename' and old is not None and old != doc.name:
        raise NativeInvoiceLifecycleError('native_lifecycle_rename_identity')
    database = current_database(runtime)
    site, actor = runtime.local.site, runtime.session.user
    db_name = runtime.conf.get('db_name')
    # Resolve a lazy current-site connection before pinning its physical handle.
    rows = database.sql('SELECT DATABASE() AS db_name', as_dict=True)
    connection = database._conn
    socket = getattr(connection, '_sock', None)

    def require_owner():
        if (current_database(runtime) is not database or runtime.local.site != site
                or runtime.session.user != actor or runtime.conf.get('db_name') != db_name
                or database.db_type != 'mariadb' or database.cur_db_name != db_name
                or database._conn is not connection or socket is None or connection._sock is not socket
                or not connection.open or connection.get_autocommit() is not False
                or getattr(database, 'auto_commit_on_many_writes', None) not in (0, False)):
            raise NativeInvoiceLifecycleError('native_lifecycle_parent_binding')

    def query(statement, values=()):
        require_owner()
        result = database.sql(statement, values, as_dict=True)
        require_owner()
        return result

    require_owner()
    if len(rows) != 1 or rows[0]['db_name'] != db_name:
        raise NativeInvoiceLifecycleError('native_lifecycle_database')
    # Open metadata locks first. Physical schema is inspected, never installed
    # or repaired by a destructive source hook. Missing custody is not zero history.
    for name in (table, 'tabZATCA Issuance', 'tabZATCA Submission Intent'):
        query('SELECT name FROM `' + name + '` LIMIT 0')
    engines = query('SELECT table_name,engine FROM information_schema.tables '
        'WHERE table_schema=DATABASE() AND table_name IN (%s,%s,%s)',
        (table, 'tabZATCA Issuance', 'tabZATCA Submission Intent'))
    if len(engines) != 3 or any(row['engine'] != 'InnoDB' for row in engines):
        raise NativeInvoiceLifecycleError('native_lifecycle_storage')
    indexes = query('SELECT DISTINCT table_name FROM information_schema.statistics '
        'WHERE table_schema=DATABASE() AND table_name IN (%s,%s) '
        'AND seq_in_index=1 AND column_name=%s AND sub_part IS NULL',
        ('tabZATCA Issuance', 'tabZATCA Submission Intent', 'source_name'))
    if {row['table_name'] for row in indexes} != {'tabZATCA Issuance', 'tabZATCA Submission Intent'}:
        raise NativeInvoiceLifecycleError('native_lifecycle_history_index')
    field = ('custom_zatca_issuing_unit' if runtime.get_meta(doc.doctype).has_field('custom_zatca_issuing_unit') else 'name')
    names = [(doc.name, True)]
    if method == 'before_rename' and merge:
        saved_form_name(new)
        if new != doc.name:
            names.append((new, False))
    for name, required in names:
        source = query('SELECT name,`' + field + '` AS marker FROM `' + table + '` WHERE name=%s FOR UPDATE NOWAIT', (name,))
        if not source:
            if required:
                raise NativeInvoiceLifecycleError('native_lifecycle_missing_source')
            continue  # The framework retains its normal missing merge-target check.
        if len(source) != 1 or source[0]['name'] != name:
            raise NativeInvoiceLifecycleError('native_lifecycle_source_identity')
        # A saved marker with lost custody is a review, not permission to discard
        # it. A browser-supplied marker/status is deliberately not this evidence.
        marker = source[0]['marker'] if field != 'name' else None
        if type(marker) is str and marker.startswith('egs:'):
            raise NativeInvoiceLifecycleError('native_lifecycle_saved_marker')
        for history in ('tabZATCA Issuance', 'tabZATCA Submission Intent'):
            found = query('SELECT name FROM `' + history + '` WHERE source_name=%s '
                'AND source_doctype=%s LIMIT 1 LOCK IN SHARE MODE NOWAIT', (name, doc.doctype))
            if found:
                raise NativeInvoiceLifecycleError('native_lifecycle_retained_history')


def protect_native_invoice_lifecycle(doc, method=None, old=None, new=None, merge=False):
    """Fixed Sales/POS hook; one translated message and static English diagnosis.

    Ordinary framework permissions/links/accounting checks still apply. Catch
    private SQL errors here without exporting driver text or taking over rollback.
    """
    code = None
    try:
        inspect_source_lifecycle(doc, runtime=frappe, method=method, old=old, new=new, merge=merge)
    except Exception as error:
        code = error.code if isinstance(error, NativeInvoiceLifecycleError) else 'native_lifecycle_unconfirmed'
    if code is not None:
        try:
            frappe.log_error(title='Native ZATCA invoice lifecycle review', message=code)
        except Exception:
            pass  # Diagnostic failure must not permit the destructive operation.
        raise NativeInvoiceLifecycleError(code, _(REVIEW))
