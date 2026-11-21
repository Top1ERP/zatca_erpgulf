"""Explicit local acceptance review of a superseded exact-original response.

Retain the current technical attempt and both receipts. A separate authenticated
decision selects the verified older receipt; no source, counter, XML, signing,
queue or authority operation occurs. The newer attempt must satisfy the shared
expired-unknown/received-failure gate and own no conflicting chain reservation.
"""

import frappe
from frappe import _

from .dispatch_record_codec import _identifier
from .dispatch_store import DispatchStore
from .late_acceptance_evidence import open_resolution,OUTCOMES
from .native_dispatch import SOURCE_TABLES,read_retained_in_transaction,assess_retained_in_transaction
from .native_provider import _permitted
from .retry_evidence import require_retry_evidence
from .worker_transaction import owned_worker_transaction


REVIEW='The late response could not resolve this invoice safely. Review the current version, newer attempt and saved response. Nothing was generated or sent.'
SUCCESS='The matching saved response confirms acceptance of this original. The late response review was recorded and both attempts were retained. Nothing was generated or sent.'


class LateAcceptanceError(RuntimeError):
    http_status_code=417
    def __init__(self,code,message=REVIEW):self.code=code;super().__init__(message)


def _version(value):
    # Frappe POST scalars can arrive as text. Do not coerce floats/bools or
    # noncanonical numeric input into a different reviewed revision.
    if type(value) is str and value.isascii() and value.isdecimal() and len(value)<=10 and str(int(value))==value:
        value=int(value)
    if type(value) is not int or not 0<=value<2147483647:
        raise LateAcceptanceError('late_acceptance_expected_revision')
    return value


def reconcile_late_acceptance(issuance_id,expected_attempt_id,expected_state_version,accepted_attempt_id,*,runtime):
    for identifier in (issuance_id,expected_attempt_id,accepted_attempt_id):_identifier(identifier)
    revision=_version(expected_state_version)
    if expected_attempt_id==accepted_attempt_id:
        raise LateAcceptanceError('late_acceptance_older_attempt_required')
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise LateAcceptanceError('late_acceptance_access')
        rows=owner.database.sql('SELECT source_doctype,source_name,company,chain FROM `tabZATCA Issuance` '
            'WHERE name=%s LOCK IN SHARE MODE NOWAIT',(issuance_id,),as_dict=True)
        owner.require_owner()
        if len(rows)!=1:raise LateAcceptanceError('late_acceptance_original_required')
        metadata=rows[0];dt,name=metadata['source_doctype'],metadata['source_name']
        if dt not in SOURCE_TABLES:raise LateAcceptanceError('late_acceptance_source_binding')
        source=runtime.get_doc(dt,name);company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        if (source.doctype,source.name,source.company)!=(dt,name,metadata['company']):
            raise LateAcceptanceError('late_acceptance_source_binding')
        repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        chain=repository.lock_chain_reference(metadata['chain'])
        source=runtime.get_doc(dt,name,for_update=True)
        company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        view=read_retained_in_transaction(dt,name,runtime=runtime,owner=owner,require_current_source=True)
        if view is None or view.issuance_id!=issuance_id or view.chain_id!=chain['record_id']:
            raise LateAcceptanceError('late_acceptance_current_version_required')
        issuance=repository.lock_issuance(chain,issuance_id)
        previous=open_resolution(repository,issuance)
        if previous is not None:
            if (previous['accepted_attempt']!=accepted_attempt_id or previous['prior_attempt']!=expected_attempt_id
                    or previous['prior_state_version']!=revision or not view.accepted):
                raise LateAcceptanceError('late_acceptance_review_changed')
            return dict(status='RESOLVED',accepted=True,issuance_id=issuance_id,attempt_id=accepted_attempt_id,reused=True)
        if issuance['active_attempt']!=expected_attempt_id or issuance['state_version']!=revision:
            raise LateAcceptanceError('late_acceptance_review_changed')
        prior=repository._attempt(expected_attempt_id)
        require_retry_evidence(repository,chain,issuance,attempt_id=expected_attempt_id,
            expected_fence=prior['fence_token'],now_utc=owner.utc_now())
        receipt,_body=repository.open_receipt(accepted_attempt_id)
        if receipt['attempt_number']>=prior['attempt_number'] or receipt['endpoint']!=prior['endpoint']:
            raise LateAcceptanceError('late_acceptance_older_matching_operation_required')
        assessment,current=assess_retained_in_transaction(repository,chain,issuance,
            attempt_id=accepted_attempt_id,request_sha256=issuance['artifact_sha256'],fence_token=receipt['fence_token'])
        if current or assessment.outcome not in OUTCOMES:
            raise LateAcceptanceError('late_acceptance_matching_receipt_required')
        proof=dict(record_id=issuance_id,chain=chain['record_id'],artifact_sha256=issuance['artifact_sha256'],
            accepted_attempt=accepted_attempt_id,accepted_fence=receipt['fence_token'],response_sha256=receipt['response_sha256'],
            prior_attempt=expected_attempt_id,prior_fence=prior['fence_token'],prior_state=issuance['state'],
            prior_state_version=issuance['state_version'],resolved_by=owner.actor,
            resolved_at_utc=owner.utc_now().strftime('%Y-%m-%dT%H:%M:%S.%f'),outcome=assessment.outcome)
        repository.stage_late_acceptance(chain,issuance,proof)
        confirmed=read_retained_in_transaction(dt,name,runtime=runtime,owner=owner,require_current_source=True)
        if not confirmed.accepted or confirmed.attempt_id!=accepted_attempt_id:
            raise LateAcceptanceError('late_acceptance_readback_unconfirmed')
        owner.commit()
    return dict(status='RESOLVED',accepted=True,issuance_id=issuance_id,attempt_id=accepted_attempt_id,reused=False)


@frappe.whitelist(methods=['POST'])
def reconcile_response(issuance_id,expected_attempt_id,expected_state_version,accepted_attempt_id):
    code=None
    try:
        result=reconcile_late_acceptance(issuance_id,expected_attempt_id,expected_state_version,accepted_attempt_id,runtime=frappe)
    except Exception as error:
        code=error.code if isinstance(error,LateAcceptanceError) else 'late_acceptance_unconfirmed'
    if code is not None:
        try:frappe.log_error(title='ZATCA late acceptance review',message=code)
        except Exception:pass
        raise LateAcceptanceError(code,_(REVIEW))
    return dict(result,message=_(SUCCESS))
