"""Complete a stopped handoff from canonical saved custody, never by resending.

Only the request state/audit capsule may change. The same retained reader verifies
current source/version/projection and exact accepted receipts; this module does
not copy receipt interpretation, sign, repair source fields, queue or transport.
"""

import hashlib

import frappe
from frappe import _

from .dispatch_record_codec import _identifier,encode_record_header
from .native_dispatch import read_retained_in_transaction,assess_retained_in_transaction
from .dispatch_store import DispatchStore
from .native_provider import _permitted
from .submission_intent import (
    TABLE,SubmissionIntentError,RECONCILIATION_BODY,open_intent,open_reconciliation,fiscal_sha,validate_header,
)
from .worker_transaction import owned_worker_transaction


REVIEW = 'The request could not be completed from saved evidence. Review its current worker claim, original document and matching response. Nothing was regenerated or sent.'
PREPARED = 'The saved original was verified and the request was completed locally. ZATCA acceptance is not confirmed. Nothing was sent.'
ACCEPTED = 'The saved original and matching response confirm ZATCA acceptance. The request was completed from saved evidence; nothing was sent.'


class IntentReconciliationError(RuntimeError):
    http_status_code=417

    def __init__(self,code,message=REVIEW):
        self.code=code
        super().__init__(message)


def reconcile_saved_result(record_id,expected_state,expected_fence,*,runtime):
    """Explicit local review; no age cutoff, builder, source or actor override."""
    _identifier(record_id)
    if expected_state not in ('RUNNING','REVIEW'):
        raise IntentReconciliationError('intent_reconciliation_expected_state')
    if expected_fence is not None:_identifier(expected_fence)
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise IntentReconciliationError('intent_reconciliation_access')
        row,header=open_intent(owner,record_id)
        repeated=row['state']=='COMPLETE' and row['resolution_header'] is not None
        previous=open_reconciliation(owner,row,header) if repeated else None
        state=previous['prior_state'] if repeated else row['state']
        fence=previous['prior_fence'] if repeated else row['fence_token']
        if state!=expected_state or fence!=expected_fence:
            raise IntentReconciliationError('intent_reconciliation_claim_changed')
        if expected_state=='RUNNING' and expected_fence is None:
            raise IntentReconciliationError('intent_reconciliation_missing_fence')
        dt,name=header['source_doctype'],header['source_name']
        source=runtime.get_doc(dt,name)
        company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        chain=repository.lock_chain_reference(header['chain'])
        source=runtime.get_doc(dt,name,for_update=True)
        company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        if ((source.doctype,source.name)!=(dt,name) or source.company!=header['company'] or source.docstatus!=1
                or source.get('custom_zatca_issuing_unit')!='egs:'+header['chain']
                or fiscal_sha(source)!=header['source_sha256']):
            raise IntentReconciliationError('intent_reconciliation_source_changed')
        view=read_retained_in_transaction(dt,name,runtime=runtime,owner=owner,require_current_source=True)
        if view is None or view.chain_id!=header['chain']:
            raise IntentReconciliationError('intent_reconciliation_original_changed')
        if header.get('expected_issuance_id') not in (None,view.issuance_id):
            if header.get('request_kind')!='correction-v1':
                raise IntentReconciliationError('intent_reconciliation_original_changed')
            from .corrected_preparation import require_corrected_result
            require_corrected_result(repository,chain,view,header)
        if not repeated and view.state=='REVIEW_REQUIRED' and view.attempt_id is not None:
            # A process may have durably captured its response and stopped
            # before assessment. Stage that same canonical assessment locally;
            # commit it only together with an admissible completed request.
            issuance=repository.lock_issuance(chain,view.issuance_id)
            receipt,_body=repository.open_receipt(view.attempt_id)
            _assessment,current=assess_retained_in_transaction(repository,chain,issuance,
                attempt_id=view.attempt_id,request_sha256=issuance['artifact_sha256'],fence_token=receipt['fence_token'])
            if not current:raise IntentReconciliationError('intent_reconciliation_attempt_changed')
            view=read_retained_in_transaction(dt,name,runtime=runtime,owner=owner,require_current_source=True)
        if view.accepted:
            reason='reconciled_accepted'
        elif view.state=='PREPARED' and view.attempt_id is None:
            reason='reconciled_prepared'
        else:
            raise IntentReconciliationError('intent_reconciliation_outcome_unconfirmed')
        result=dict(status='COMPLETE',intent_id=record_id,issuance_id=view.issuance_id,
            issuance_state=view.state,accepted=view.accepted,reused=repeated)
        if repeated:
            if (previous['issuance_id']!=view.issuance_id or previous['reason']!=reason
                    or previous['attempt_id']!=view.attempt_id or previous['outcome']!=view.outcome
                    or previous['original_xml_sha256']!=hashlib.sha256(view.original_xml).hexdigest()):
                raise IntentReconciliationError('intent_reconciliation_evidence_changed')
            return result
        locked,current=open_intent(owner,record_id,lock=True)
        if current!=header or locked['state']!=expected_state or locked['fence_token']!=expected_fence:
            raise IntentReconciliationError('intent_reconciliation_claim_changed')
        stamp=owner.utc_now()
        proof=dict(record_id=record_id,intent_sha256=hashlib.sha256(validate_header(header)).hexdigest(),
            resolved_by=owner.actor,resolved_at_utc=stamp.strftime('%Y-%m-%dT%H:%M:%S.%f'),
            prior_state=expected_state,prior_fence=expected_fence,reason=reason,issuance_id=view.issuance_id,
            issuance_state=view.state,attempt_id=view.attempt_id,outcome=view.outcome,
            original_xml_sha256=hashlib.sha256(view.original_xml).hexdigest())
        encoded=encode_record_header(proof)
        cipher=owner.cipher.seal(record_id,'intent-reconciliation',encoded,RECONCILIATION_BODY)
        owner.database.sql('UPDATE '+TABLE+' SET state=%s,active_key=NULL,result_code=%s,'
            'resolution_header=%s,resolution_ciphertext=%s,modified=%s,finished_at_utc=%s,modified_by=%s,'
            'state_version=state_version+1 WHERE name=%s AND state=%s AND fence_token <=> %s',
            ('COMPLETE',reason,encoded.decode(),cipher,stamp,stamp,owner.actor,record_id,expected_state,expected_fence))
        if owner.database.sql('SELECT ROW_COUNT() AS affected',as_dict=True)[0]['affected']!=1:
            raise IntentReconciliationError('intent_reconciliation_update_changed')
        confirmed,current=open_intent(owner,record_id,lock=True)
        if confirmed['state']!='COMPLETE' or current!=header:
            raise IntentReconciliationError('intent_reconciliation_readback')
        owner.commit()
    return result


@frappe.whitelist(methods=['POST'])
def reconcile_request(record_id,expected_state,expected_fence=None):
    code=None
    try:
        result=reconcile_saved_result(record_id,expected_state,expected_fence,runtime=frappe)
    except Exception as error:
        code=error.code if isinstance(error,(IntentReconciliationError,SubmissionIntentError)) else 'intent_reconciliation_unconfirmed'
    if code is not None:
        try:frappe.log_error(title='ZATCA saved request reconciliation review',message=code)
        except Exception:pass
        raise IntentReconciliationError(code,_(REVIEW))
    return dict(result,message=_(ACCEPTED if result['accepted'] else PREPARED))
