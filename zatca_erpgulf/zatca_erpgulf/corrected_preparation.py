"""Explicit durable corrected-XML requests using the shared intent lifecycle.

Approval binds current saved fiscal data and the rejected version/attempt/fence.
The fixed worker prepares a linked original only; it never authorizes transport.
No customer, ERP invoice, posting clock or financial value is created or edited.
"""

import frappe
from frappe import _

from .collection_intent import CollectionIntent,arm_collection_request,CollectionSubmissionError
from .dispatch_record_codec import _identifier
from .dispatch_store import DispatchStore
from .native_dispatch import (
    SOURCE_TABLES,_rejected_original,_require_current_correction_policy,_require_correction_policy,
    prepare_corrected_rejection,read_retained_in_transaction,
)
from .native_provider import _permitted
from .native_response import assess_native_receipt
from .operation_messages import mute_operation_messages
from .rejection_history import require_rejection_history
from .submission_intent import require_bound_source
from .worker_transaction import owned_worker_transaction


REVIEW='The corrected XML request could not be registered safely. Review the current saved invoice, rejected version and attempt history. Nothing was generated or sent by this action.'
REGISTERED='A request to prepare corrected XML locally was registered for the background worker after commit. It will use current approved saved data with a new UUID and the next invoice counter. The old original stays retained. This is not ZATCA acceptance and does not authorize sending. No customer or Sales Invoice is created.'
FLAG='_zatca_corrected_preparation_requests'


class CorrectedPreparationError(RuntimeError):
    http_status_code=417
    def __init__(self,code,message=REVIEW):self.code=code;self.fatal=True;super().__init__(message)


def _repository(owner):
    return DispatchStore(owner.database,storage_namespace=owner.storage_namespace,cipher=owner.cipher,owner_check=owner.owner_current)


def _inspect(issuance_id,attempt_id,fence_token,*,runtime):
    for value in (issuance_id,attempt_id,fence_token):_identifier(value)
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):raise CorrectedPreparationError('corrected_preparation_access')
        rows=owner.database.sql('SELECT record_id,source_doctype,source_name,company,chain FROM `tabZATCA Issuance` '
            'WHERE name=%s LOCK IN SHARE MODE NOWAIT',(issuance_id,),as_dict=True)
        owner.require_owner()
        if len(rows)!=1 or rows[0]['record_id']!=issuance_id or rows[0]['source_doctype'] not in SOURCE_TABLES:
            raise CorrectedPreparationError('corrected_preparation_identity')
        row=rows[0];source=runtime.get_doc(row['source_doctype'],row['source_name'])
        company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        if source.company!=row['company']:raise CorrectedPreparationError('corrected_preparation_company')
        repository=_repository(owner);chain=repository.lock_chain_reference(row['chain'])
        source=runtime.get_doc(source.doctype,source.name,for_update=True)
        _require_current_correction_policy(runtime,owner,source)
        latest=repository.latest_issuance(chain['record_id'],source.doctype,source.name)
        if latest is None or latest['record_id']!=issuance_id:
            raise CorrectedPreparationError('corrected_preparation_current_version')
        issuance=repository.lock_issuance(chain,issuance_id)
        _rejected_original(repository,chain,issuance,source,(issuance_id,attempt_id),expected_fence=fence_token)
        return source.doctype,source.name


class CorrectionIntent(CollectionIntent):
    OPERATIONS=('correction',)
    REPLACE_REVIEW_OPERATIONS=('correction',)

    def __init__(self,runtime,doctype,name,*,issuance_id,attempt_id,fence_token):
        for value in (issuance_id,attempt_id,fence_token):_identifier(value)
        self.approved_attempt=attempt_id;self.approved_fence=fence_token
        super().__init__(runtime,doctype,name,intent='correction',expected_issuance_id=issuance_id)

    def snapshot(self):
        observed=super().snapshot()
        source,company,chain_id,_digest,latest=observed
        if latest is None or latest['record_id']!=self.expected_input:
            raise CorrectedPreparationError('corrected_preparation_current_version')
        _require_correction_policy(self.runtime,source,company,self.actor)
        self.require_owner()
        repository=_repository(self);chain=repository.lock_chain_reference(chain_id)
        issuance=repository.lock_issuance(chain,latest['record_id'])
        _rejected_original(repository,chain,issuance,source,(self.expected_input,self.approved_attempt),expected_fence=self.approved_fence)
        return observed

    def safe_latest(self):return self.latest is not None  # snapshot proved rejection/history and current policy.

    def header_fields(self):
        return dict(super().header_fields(),request_kind='correction-v1',
            rejected_attempt_id=self.approved_attempt,rejected_fence_token=self.approved_fence)

def require_corrected_result(repository,chain,view,header):
    """Verify the completed linked version after canonical current-source reads.

    The caller separately enforces the request's current fiscal projection/ACL.
    No source-output proxy is constructed to impersonate the rejected version.
    """
    if header.get('request_kind')!='correction-v1' or view.issuance_id==header['expected_issuance_id']:
        raise CorrectedPreparationError('corrected_preparation_link_required')
    current,_body=repository.open_issuance(view.issuance_id)
    old=repository.lock_issuance(chain,header['expected_issuance_id'])
    previous,original=repository.open_issuance(old['record_id'])
    if (current['replaces_issuance']!=old['record_id'] or current['source_version']!=previous['source_version']+1
            or old['state']!='REJECTED' or old['active_attempt']!=header['rejected_attempt_id']
            or any(old.get(key) is not None for key in ('late_acceptance_header','late_acceptance_ciphertext'))
            or any(record[key]!=header[key] for record in (current,previous) for key in ('company','chain','source_doctype','source_name'))):
        raise CorrectedPreparationError('corrected_preparation_link_binding')
    receipt,body=repository.open_receipt(header['rejected_attempt_id'])
    fallback=repository.open_clearance_fallback(old) if previous['endpoint']!=receipt['endpoint'] else None
    assessment=assess_native_receipt(previous,original,receipt,body,fallback_receipt=fallback)
    if (receipt['fence_token']!=header['rejected_fence_token'] or receipt['http_status']!=400
            or assessment.outcome!='VALIDATION_REJECTED'):
        raise CorrectedPreparationError('corrected_preparation_rejection_binding')
    require_rejection_history(repository,chain,old,previous,original,header['rejected_attempt_id'])


def run_corrected_command(header,*,runtime,translate,build):
    """Fixed worker path: recheck, prepare only, or reuse verified linked custody."""
    if header.get('request_kind')!='correction-v1':raise CorrectedPreparationError('corrected_preparation_command_kind')
    dt,name=header['source_doctype'],header['source_name']
    with owned_worker_transaction(runtime) as owner:
        repository=_repository(owner);chain=repository.lock_chain_reference(header['chain'])
        source=runtime.get_doc(dt,name,for_update=True)
        _require_current_correction_policy(runtime,owner,source)
        require_bound_source(runtime,source,chain['record_id'],owner=owner)
        view=read_retained_in_transaction(dt,name,runtime=runtime,owner=owner)
        if view is None:raise CorrectedPreparationError('corrected_preparation_original_required')
        if view.issuance_id!=header['expected_issuance_id']:
            view=read_retained_in_transaction(dt,name,runtime=runtime,owner=owner,require_current_source=True)
            require_corrected_result(repository,chain,view,header)
            if not view.accepted and not (view.state=='PREPARED' and view.attempt_id is None):
                raise CorrectedPreparationError('corrected_preparation_linked_outcome_review')
            return dict(status='SUCCESS' if view.accepted else 'PREPARED',accepted=view.accepted,issuance_id=view.issuance_id,reused=True)
    value=prepare_corrected_rejection(dt,name,runtime=runtime,translate=translate,build=build,
        rejected_issuance_id=header['expected_issuance_id'],rejected_attempt_id=header['rejected_attempt_id'],
        rejected_fence_token=header['rejected_fence_token'],use_current_issue_time=True)
    return dict(status='PREPARED',accepted=False,issuance_id=value.record_id,reused=value.reused)


def register_corrected_preparation(issuance_id,attempt_id,fence_token,*,runtime,translate):
    dt,name=_inspect(issuance_id,attempt_id,fence_token,runtime=runtime)
    cache=runtime.flags.setdefault(FLAG,{})
    key=(runtime.local.site,runtime.session.user,issuance_id,attempt_id,fence_token)
    if key in cache:
        cache[key].require_owner();return dict(cache[key].result(),issuance_id=issuance_id)
    for event in ('before_commit','after_commit','after_rollback'):
        if not callable(getattr(getattr(runtime.db,event,None),'add',None)):
            raise CorrectedPreparationError('corrected_preparation_callbacks_missing')
    request=CorrectionIntent(runtime,dt,name,issuance_id=issuance_id,attempt_id=attempt_id,fence_token=fence_token)
    result=arm_collection_request(request,runtime=runtime,translate=translate,cache=cache,key=key)
    return dict(result,issuance_id=issuance_id)


@frappe.whitelist(methods=['POST'])
def queue_corrected_preparation(issuance_id,attempt_id,fence_token):
    code=None;logged=False
    try:
        with mute_operation_messages(frappe):
            result=register_corrected_preparation(issuance_id,attempt_id,fence_token,runtime=frappe,translate=_)
    except Exception as error:
        code=error.code if isinstance(error,CorrectedPreparationError) else 'corrected_preparation_unconfirmed'
        logged=isinstance(error,CollectionSubmissionError) and error.diagnostic_logged
    if code is not None:
        if not logged:
            try:frappe.log_error(title='ZATCA corrected XML request review',message=code)
            except Exception:pass
        raise CorrectedPreparationError(code,_(REVIEW))
    return dict(result,message=_(REGISTERED))
