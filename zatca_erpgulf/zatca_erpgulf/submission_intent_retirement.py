"""Explicit local retirement of an authenticated, provably unissued request.

This operator action revokes the durable worker claim under the same source lock
as generation/reservation. It cannot retire an issued document, reclaim an ICV,
erase request history, requeue work, repair a source or contact an authority API.
"""

import hashlib

import frappe
from frappe import _

from .dispatch_record_codec import _identifier,encode_record_header
from .native_invoice_lifecycle import SOURCE_TABLES,require_lifecycle_storage
from .native_provider import _permitted
from .submission_intent import (
    ParentIntent,TABLE,SubmissionIntentError,RETIREMENT_BODY,open_intent,request_header_bytes,
)
from .worker_transaction import owned_worker_transaction


REVIEW = 'This request could not be retired safely. Review its current worker claim and saved issuance history. No invoice was deleted, regenerated or sent.'
SUCCESS = 'The unissued request was retired and its history was retained. Normal invoice permissions and cancellation or deletion checks still apply. This is not ZATCA acceptance.'
STATES = ('STAGED','READY','WAITING','RUNNING','REVIEW')


class IntentRetirementError(RuntimeError):
    http_status_code = 417

    def __init__(self,code,message=REVIEW):
        self.code=code
        super().__init__(message)


class _RetiredRead(ParentIntent):
    def __init__(self,runtime,doctype,name):
        self.bind_parent(runtime,doctype,name,intent='manual')


def require_retired_requests(runtime,doctype,name,requests):
    """Borrow, authenticate all bounded terminal proofs, never commit/rollback."""
    reader=_RetiredRead(runtime,doctype,name)
    for request in requests:
        row,header=open_intent(reader,request['name'])
        if row['state']!='RETIRED' or (header['source_doctype'],header['source_name'])!=(doctype,name):
            raise SubmissionIntentError('submission_intent_retirement_source')
    reader.require_owner()


def retire_unissued_intent(record_id,expected_state,expected_fence,*,runtime):
    """Explicit owned action; expected claim prevents stale Desk decisions.

    System Manager and saved source READ+WRITE/Company READ are required, even
    when the original request actor differs. No actor/Company/source is supplied
    by the caller. Source locks, not a queue lease timeout, prove exclusion.
    """
    _identifier(record_id)
    if expected_state not in STATES:raise IntentRetirementError('intent_retirement_expected_state')
    if expected_fence is not None:_identifier(expected_fence)
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise IntentRetirementError('intent_retirement_access')
        row,header=open_intent(owner,record_id,allow_staged=True)
        retired=row['state']=='RETIRED'
        if not retired and (row['state']!=expected_state or row['fence_token']!=expected_fence):
            raise IntentRetirementError('intent_retirement_claim_changed')
        if expected_state=='STAGED' and expected_fence is not None:
            raise IntentRetirementError('intent_retirement_staged_fence')
        if not retired and header.get('expected_issuance_id') is not None:
            # A retained header that previously observed an original cannot
            # turn lost custody into evidence that no document ever existed.
            raise IntentRetirementError('intent_retirement_original_expected')
        dt,name=header['source_doctype'],header['source_name']
        def query(statement,values=()):
            owner.require_owner()
            rows=owner.database.sql(statement,values,as_dict=True)
            owner.require_owner()
            return rows
        require_lifecycle_storage(query,SOURCE_TABLES[dt]);owner.require_owner()
        source=runtime.get_doc(dt,name,for_update=True)
        company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        # A draft stage binds source/actor, not final Company/fiscal data. Read
        # the current saved Company and enforce its ordinary ACL independently.
        if ((source.doctype,source.name)!=(dt,name)
                or 'company' in header and source.company!=header['company']):
            raise IntentRetirementError('intent_retirement_source_review')
        if retired:
            # Idempotent status still requires normal saved-source ACLs. A
            # deleted/renamed source needs history access, not an ACL bypass.
            return {'status':'RETIRED','request_id':record_id,'accepted':False,'reused':True}
        marker=source.get('custom_zatca_issuing_unit')
        if type(marker) is str and marker.startswith('egs:'):
            raise IntentRetirementError('intent_retirement_source_review')
        issued=query('SELECT name FROM `tabZATCA Issuance` WHERE source_name=%s AND source_doctype=%s '
            'LIMIT 1 LOCK IN SHARE MODE NOWAIT',(name,dt))
        if issued:raise IntentRetirementError('intent_retirement_issued')
        locked,current=open_intent(owner,record_id,lock=True,allow_staged=True)
        if current!=header or locked['state']!=expected_state or locked['fence_token']!=expected_fence:
            raise IntentRetirementError('intent_retirement_claim_changed')
        if expected_state=='RUNNING' and expected_fence is None:
            raise IntentRetirementError('intent_retirement_missing_fence')
        stamp=owner.utc_now()
        proof=dict(record_id=record_id,intent_sha256=hashlib.sha256(request_header_bytes(header)).hexdigest(),
            retired_by=owner.actor,retired_at_utc=stamp.strftime('%Y-%m-%dT%H:%M:%S.%f'),
            prior_state=expected_state,prior_fence=expected_fence,reason='unissued_request_retired')
        encoded=encode_record_header(proof)
        cipher=owner.cipher.seal(record_id,'intent-retirement',encoded,RETIREMENT_BODY)
        owner.database.sql('UPDATE '+TABLE+' SET state=%s,active_key=NULL,result_code=%s,'
            'resolution_header=%s,resolution_ciphertext=%s,modified=%s,finished_at_utc=%s,modified_by=%s,'
            'state_version=state_version+1 WHERE name=%s AND state=%s AND fence_token <=> %s',
            ('RETIRED','unissued_request_retired',encoded.decode(),cipher,stamp,stamp,owner.actor,
             record_id,expected_state,expected_fence))
        if query('SELECT ROW_COUNT() AS affected')[0]['affected']!=1:
            raise IntentRetirementError('intent_retirement_update_changed')
        confirmed,current=open_intent(owner,record_id,lock=True)
        if confirmed['state']!='RETIRED' or current!=header:
            raise IntentRetirementError('intent_retirement_readback')
        owner.commit()
    return {'status':'RETIRED','request_id':record_id,'accepted':False,'reused':False}


@frappe.whitelist(methods=['POST'])
def retire_request(record_id,expected_state,expected_fence=None):
    code=None
    try:
        result=retire_unissued_intent(record_id,expected_state,expected_fence,runtime=frappe)
    except Exception as error:
        code=error.code if isinstance(error,IntentRetirementError) else 'intent_retirement_unconfirmed'
    if code is not None:
        try:frappe.log_error(title='ZATCA unissued request retirement review',message=code)
        except Exception:pass
        raise IntentRetirementError(code,_(REVIEW))
    return dict(result,message=_(SUCCESS))
