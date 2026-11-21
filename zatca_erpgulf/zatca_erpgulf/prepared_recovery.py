"""Explicit first-send requests for exact untouched native PREPARED originals.

Read canonical custody with source ACLs, then register the existing manual command
on the parent transaction. This is not a retry endpoint: any previous attempt,
rejection or unknown outcome requires its separate reviewed lifecycle. No signing,
invoice generation or authority transport occurs. Owned preflight may end only
its clean read transaction; registration never commits or rolls back ERP writes.
"""

import frappe
from frappe import _

from .collection_intent import register_native_collection,CollectionSubmissionError
from .dispatch_record_codec import _identifier
from .native_dispatch import SOURCE_TABLES,read_retained_in_transaction
from .native_onboarding import native_mode_enabled
from .native_provider import _permitted
from .operation_messages import mute_operation_messages
from .saved_form_source import saved_form_name
from .worker_transaction import owned_worker_transaction


REVIEW = 'The saved original could not be queued safely. Review its current invoice, permissions, issuing settings and delivery history. Nothing was regenerated or sent by this action.'
REGISTERED = 'A request for the exact saved original was registered and will be queued after commit. This is not ZATCA acceptance. No XML, UUID or invoice counter was regenerated.'


class PreparedRecoveryError(RuntimeError):
    http_status_code=417

    def __init__(self,code,message=REVIEW):
        self.code=code
        self.fatal=True
        super().__init__(message)


def _inspect_original(record_id,*,runtime):
    """Own only a clean read scope; release all locks before parent staging.

    Index metadata locates the saved source but cannot grant send authority.
    Source READ+WRITE and Company READ precede decryption. The canonical reader
    authenticates the actual latest version/current fiscal projection; there is
    no invoice-age cutoff or current-Customer reclassification.
    """
    _identifier(record_id)
    if not native_mode_enabled(runtime):raise PreparedRecoveryError('prepared_recovery_rollout_disabled')
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise PreparedRecoveryError('prepared_recovery_access')
        rows=owner.database.sql('SELECT record_id,source_doctype,source_name,company FROM `tabZATCA Issuance` '
            'WHERE name=%s LOCK IN SHARE MODE NOWAIT',(record_id,),as_dict=True)
        owner.require_owner()
        if len(rows)!=1 or rows[0]['record_id']!=record_id or rows[0]['source_doctype'] not in SOURCE_TABLES:
            raise PreparedRecoveryError('prepared_recovery_identity')
        row=rows[0]
        saved_form_name(row['source_name']);saved_form_name(row['company'])
        source=runtime.get_doc(row['source_doctype'],row['source_name'])
        company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        if ((source.doctype,source.name)!=(row['source_doctype'],row['source_name']) or source.company!=row['company']):
            raise PreparedRecoveryError('prepared_recovery_source')
        view=read_retained_in_transaction(source.doctype,source.name,runtime=runtime,owner=owner,require_current_source=True)
        if (view is None or view.issuance_id!=record_id or view.state!='PREPARED'
                or view.attempt_id is not None or view.accepted):
            raise PreparedRecoveryError('prepared_recovery_not_untouched')
        return source.doctype,source.name


def register_prepared_original(record_id,*,runtime,translate):
    """Fixed explicit manual authorization, shared store/worker/after-commit path.

    Owned preflight rejects foreign parent writes/callbacks. It ends before the
    ordinary borrowed registrar stages a version-pinned command. A later changed
    version, fiscal data, policy or uncertain send cannot trigger regeneration.
    Another worker may complete the same original in the meantime; the command
    then resolves its matching receipt without a second authority call.
    """
    doctype,name=_inspect_original(record_id,runtime=runtime)
    source=runtime.get_doc(doctype,name)
    result=register_native_collection(source,runtime=runtime,translate=translate,
        intent='manual',expected_issuance_id=record_id)
    if (type(result) is not dict or result.get('status')!='DEFERRED' or result.get('accepted') is not False
            or result.get('source_doctype')!=doctype or result.get('source_name')!=name):
        raise PreparedRecoveryError('prepared_recovery_registration_unconfirmed')
    _identifier(result.get('request_id'))
    return dict(result,issuance_id=record_id)


@frappe.whitelist(methods=['POST'])
def queue_saved_original(issuance_id):
    code=None;logged=False
    try:
        with mute_operation_messages(frappe):
            result=register_prepared_original(issuance_id,runtime=frappe,translate=_)
    except Exception as error:
        code=error.code if isinstance(error,PreparedRecoveryError) else 'prepared_recovery_unconfirmed'
        logged=isinstance(error,CollectionSubmissionError) and error.diagnostic_logged
    if code is not None:
        if not logged:
            try:frappe.log_error(title='ZATCA prepared original recovery review',message=code)
            except Exception:pass
        raise PreparedRecoveryError(code,_(REVIEW))
    return dict(result,message=_(REGISTERED))
