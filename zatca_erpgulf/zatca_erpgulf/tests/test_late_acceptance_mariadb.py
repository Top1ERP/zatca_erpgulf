"""Reviewed superseded receipt resolution on private SQL with mocked HTTP."""

import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from requests.exceptions import ReadTimeout

from zatca_erpgulf.zatca_erpgulf import native_dispatch as dispatch,late_acceptance as operator
from zatca_erpgulf.zatca_erpgulf import submission_intent_reconciliation as reconciliation
from zatca_erpgulf.zatca_erpgulf.native_transport import NativeResponse
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_exact_retry_mariadb import unknown,expire,register,execute,command
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def issuance(c,identifier):
    return c.database.sql('SELECT * FROM `tabZATCA Issuance` WHERE name=%s',(identifier,),as_dict=True)[0]


def pair(c,monkeypatch,*,age=True,newer_failure=False,status=200,body=None):
    captured=[];invoke=dispatch.invoke_saved_request
    def observed(invocation,**kwargs):
        captured.append(invocation);return invoke(invocation,**kwargs)
    monkeypatch.setattr(dispatch,'invoke_saved_request',observed)
    view,first=unknown(c);expire(c,first)
    result=register(c,view,first);c.database.commit()
    if newer_failure:
        def failed(prepared,**kwargs):
            response=c.normal_send(prepared,**kwargs);response.status_code=503
            response.raw.read1=Mock(side_effect=[b'SYNTHETIC TECHNICAL FAILURE',b'']);return response
        c.adapter.send.side_effect=failed
    assert execute(c,result['request_id'])['status']=='REVIEW'
    latest=issuance(c,view.issuance_id)
    prior=c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(latest['active_attempt'],),as_dict=True)[0]
    assert prior['name']!=first['name'] and latest['state']=='OUTCOME_UNKNOWN'
    if age and not newer_failure:expire(c,prior)
    if body is None:
        payload=dict(validationResults=dict(status='PASS',errorMessages=[],warningMessages=[],infoMessages=[]))
        if captured[0].route.endpoint=='invoices/clearance/single':
            payload.update(clearanceStatus='CLEARED',clearedInvoice=json.loads(captured[0].request_bytes)['invoice'])
        else:payload.update(reportingStatus='REPORTED')
        body=json.dumps(payload).encode()
    assert dispatch.retain_dispatch_observation(captured[0],NativeResponse(status,'SYNTHETIC-LATE',body),runtime=c.runtime) is False
    return view,first,prior,result['request_id'],captured,body


def reconcile(c,view,prior,*,revision=None,candidate=None):
    version=issuance(c,view.issuance_id)['state_version'] if revision is None else revision
    return operator.reconcile_late_acceptance(view.issuance_id,prior['name'],version,
        candidate or view.attempt_id,runtime=c.runtime)


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),(0,'linked','Live',False)],indirect=True)
def test_reviewed_old_acceptance_resolves_same_original_preserves_both_attempts_and_avoids_resend(handoff,monkeypatch):
    c=handoff;view,first,prior,request,captured,body=pair(c,monkeypatch)
    before=issuance(c,view.issuance_id);revision=before['state_version'];calls=c.adapter.send.call_count
    result=reconcile(c,view,prior);saved=issuance(c,view.issuance_id)
    assert result['accepted'] and result['status']=='RESOLVED' and saved['active_attempt']==prior['name']
    assert saved['artifact_ciphertext']==before['artifact_ciphertext'] and saved['late_acceptance_ciphertext']
    proof=json.loads(saved['late_acceptance_header'])
    assert proof['accepted_attempt']==first['name'] and proof['prior_attempt']==prior['name'] and proof['prior_state_version']==revision
    again=dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_current_source=True)
    assert again.accepted and again.attempt_id==first['name'] and again.original_xml==view.original_xml
    assert c.head()=='1' and len(c.built)==1 and c.adapter.send.call_count==calls==2
    assert reconcile(c,view,prior,revision=revision)['reused']
    stopped=command(c,request)
    assert reconciliation.reconcile_saved_result(request,'REVIEW',stopped['fence_token'],runtime=c.runtime)['accepted']
    # Existing cached operation projects the selected raw response without
    # signing or transport, even when the current signing key is unavailable.
    c.selected.custom_private_key='UNAVAILABLE-OLD-KEY'
    c.adapter.send.side_effect=AssertionError('No resend after matched acceptance')
    assert c.run()['accepted'] and c.adapter.send.call_count==calls and c.head()=='1'
    source=c.runtime.get_doc(c.source.doctype,c.source.name)
    assert source.custom_zatca_full_response==body.decode()


def test_newer_unexpired_unknown_is_not_revoked_by_an_older_response(handoff,monkeypatch):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch,age=False)
    with pytest.raises(Exception):reconcile(c,view,prior)
    saved=issuance(c,view.issuance_id)
    assert saved['state']=='OUTCOME_UNKNOWN' and saved['late_acceptance_ciphertext'] is None and c.head()=='1'


def test_matching_received_technical_failure_can_be_reviewed_without_rewriting_its_lease(handoff,monkeypatch):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch,newer_failure=True)
    assert reconcile(c,view,prior)['accepted']
    after=c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(prior['name'],),as_dict=True)[0]
    assert after['receipt_ciphertext']==prior['receipt_ciphertext'] and after['lease_expires_at_utc']==prior['lease_expires_at_utc']


@pytest.mark.parametrize('status,body',[(200,b'{}'),(401,b'PRIVATE AUTH'),(503,b'TECHNICAL'),
    (400,json.dumps(dict(validationResults=dict(status='ERROR',warningMessages=[],infoMessages=[],
        errorMessages=[dict(type='ERROR',status='ERROR',code='SYNTHETIC',message='Rejected')]),reportingStatus='NOT_REPORTED')).encode())])
def test_generic_success_auth_technical_and_validation_rejection_never_grant_late_acceptance(handoff,monkeypatch,status,body):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch,status=status,body=body)
    with pytest.raises(Exception):reconcile(c,view,prior)
    assert issuance(c,view.issuance_id)['late_acceptance_ciphertext'] is None and c.adapter.send.call_count==2 and c.head()=='1'


@pytest.mark.parametrize('fault',['revision','attempt','role','write','fiscal','receipt','original','fence'])
def test_stale_unavailable_or_corrupt_evidence_cannot_resolve_or_resend(handoff,monkeypatch,fault):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch);revision=issuance(c,view.issuance_id)['state_version']
    if fault=='revision':revision+=1
    elif fault=='attempt':prior=dict(prior,name=str(uuid4()))
    elif fault=='role':monkeypatch.setattr(c.runtime,'get_roles',lambda user:[])
    elif fault=='write':
        old=c.runtime.has_permission
        monkeypatch.setattr(c.runtime,'has_permission',lambda dt,op,**kwargs:False if op=='write' else old(dt,op,**kwargs))
    elif fault=='fiscal':c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    elif fault=='receipt':c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET receipt_ciphertext=%s WHERE name=%s',('BROKEN',first['name']))
    elif fault=='original':c.database.sql('UPDATE `tabZATCA Issuance` SET artifact_ciphertext=%s WHERE name=%s',('BROKEN',view.issuance_id))
    else:c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET fence_token=%s WHERE name=%s',(str(uuid4()),first['name']))
    c.database.commit()
    with pytest.raises(Exception):reconcile(c,view,prior,revision=revision)
    assert issuance(c,view.issuance_id)['late_acceptance_ciphertext'] is None and c.adapter.send.call_count==2 and c.head()=='1'


def test_later_newer_response_is_retained_without_overwriting_reviewed_acceptance(handoff,monkeypatch):
    c=handoff;view,first,prior,request,captured,body=pair(c,monkeypatch)
    reconcile(c,view,prior);saved=issuance(c,view.issuance_id)
    assert dispatch.retain_dispatch_observation(captured[1],NativeResponse(200,'LATER-SECOND',body),runtime=c.runtime) is False
    assessment,current=dispatch.assess_retained_dispatch(captured[1],runtime=c.runtime)
    assert not current and assessment.outcome=='REPORTING_MATCHED'
    after=issuance(c,view.issuance_id)
    assert after['late_acceptance_ciphertext']==saved['late_acceptance_ciphertext'] and after['state']=='REPORTED'
    assert dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime).attempt_id==first['name']


@pytest.mark.parametrize('fault',['missing','proof','cipher','state','unknown_state'])
def test_invalid_decision_never_falls_back_to_a_different_acceptance_receipt(handoff,monkeypatch,fault):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch);reconcile(c,view,prior)
    if fault=='missing':statement='late_acceptance_ciphertext=NULL';values=()
    elif fault=='cipher':statement='late_acceptance_ciphertext=%s';values=('BROKEN',)
    elif fault=='state':statement='state=%s';values=('CLEARED',)
    elif fault=='unknown_state':statement='state=%s';values=('OUTCOME_UNKNOWN',)
    else:
        proof=json.loads(issuance(c,view.issuance_id)['late_acceptance_header']);proof['resolved_by']='Administrator'
        statement='late_acceptance_header=%s';values=(json.dumps(proof),)
    c.database.sql('UPDATE `tabZATCA Issuance` SET '+statement+' WHERE name=%s',(*values,view.issuance_id));c.database.commit()
    with pytest.raises(Exception):dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert c.head()=='1' and c.adapter.send.call_count==2


def test_foreign_parent_writes_are_not_taken_over(handoff,monkeypatch):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,));commits=c.database.commits
    with pytest.raises(WorkerTransactionError,match='parent_state'):reconcile(c,view,prior)
    assert c.database.commits==commits and issuance(c,view.issuance_id)['late_acceptance_ciphertext'] is None


def test_lost_commit_ack_keeps_resolution_for_idempotent_review_without_compensation(handoff,monkeypatch):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch);revision=issuance(c,view.issuance_id)['state_version'];original=c.database.commit
    def lost_ack():original();raise RuntimeError('PRIVATE ACK LOST')
    monkeypatch.setattr(c.database,'commit',lost_ack)
    with pytest.raises(WorkerTransactionError) as caught:reconcile(c,view,prior,revision=revision)
    assert caught.value.commit_uncertain
    monkeypatch.setattr(c.database,'commit',original)
    assert reconcile(c,view,prior,revision=revision)['reused'] and c.adapter.send.call_count==2 and c.head()=='1'


def test_a_verified_newer_rejection_keeps_contradictory_old_acceptance_for_review(handoff,monkeypatch):
    c=handoff;view,first,prior,request,captured,_body=pair(c,monkeypatch,age=False)
    rejected=json.dumps(dict(validationResults=dict(status='ERROR',warningMessages=[],infoMessages=[],
        errorMessages=[dict(type='ERROR',status='ERROR',code='SYNTHETIC',message='Rejected')]),
        reportingStatus='NOT_REPORTED')).encode()
    assert dispatch.retain_dispatch_observation(captured[1],NativeResponse(400,'NEWER-REJECTED',rejected),runtime=c.runtime)
    assessment,current=dispatch.assess_retained_dispatch(captured[1],runtime=c.runtime)
    assert current and assessment.outcome=='VALIDATION_REJECTED'
    with pytest.raises(Exception):reconcile(c,view,prior)
    saved=issuance(c,view.issuance_id)
    assert saved['state']=='REJECTED' and saved['late_acceptance_ciphertext'] is None and c.adapter.send.call_count==2


def test_decision_is_read_back_before_commit_and_cannot_hide_truncated_storage(handoff,monkeypatch):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch);sql=c.database.sql;commits=c.database.commits
    def truncated(statement,values=(),**kwargs):
        if statement.startswith('UPDATE `tabZATCA Issuance` SET state=%s,late_acceptance_header='):
            values=(values[0],values[1][:10],*values[2:])
        return sql(statement,values,**kwargs)
    monkeypatch.setattr(c.database,'sql',truncated)
    with pytest.raises(Exception):reconcile(c,view,prior)
    saved=issuance(c,view.issuance_id)
    assert saved['state']=='OUTCOME_UNKNOWN' and saved['late_acceptance_ciphertext'] is None
    assert c.database.commits==commits and c.adapter.send.call_count==2 and c.head()=='1'


def test_another_chain_reservation_is_not_released_by_late_acceptance(handoff,monkeypatch):
    c=handoff;view,first,prior,*_=pair(c,monkeypatch);other=str(uuid4())
    c.database.sql('UPDATE `tabZATCA Issuing Chain` SET active_attempt=%s WHERE name=%s',(other,view.chain_id));c.database.commit()
    with pytest.raises(Exception):reconcile(c,view,prior)
    chain=c.database.sql('SELECT active_attempt FROM `tabZATCA Issuing Chain` WHERE name=%s',(view.chain_id,),as_dict=True)[0]
    assert chain['active_attempt']==other and issuance(c,view.issuance_id)['late_acceptance_ciphertext'] is None


@pytest.mark.parametrize('case',[(0,'company','Live',False)],indirect=True)
def test_standard_reporting_after_captured_303_selects_the_earlier_bound_reporting_receipt(handoff,monkeypatch):
    c=handoff;captured=[];invoke=dispatch.invoke_saved_request;normal=c.adapter.send.side_effect
    def observed(invocation,**kwargs):captured.append(invocation);return invoke(invocation,**kwargs)
    monkeypatch.setattr(dispatch,'invoke_saved_request',observed)
    def timeout_reporting(prepared,**kwargs):
        if prepared.url.endswith('invoices/reporting/single'):raise ReadTimeout('SYNTHETIC REPORTING TIMEOUT')
        return normal(prepared,**kwargs)
    c.adapter.send.side_effect=timeout_reporting
    with pytest.raises(Exception):c.run()
    view=dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    first=c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(view.attempt_id,),as_dict=True)[0]
    assert first['attempt_number']==2;expire(c,first)
    result=register(c,view,first);c.database.commit();assert execute(c,result['request_id'])['status']=='REVIEW'
    prior=c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE issuance=%s ORDER BY attempt_number DESC LIMIT 1',
        (view.issuance_id,),as_dict=True)[0];expire(c,prior)
    body=json.dumps(dict(validationResults=dict(status='PASS',errorMessages=[],warningMessages=[],infoMessages=[]),reportingStatus='REPORTED')).encode()
    assert not dispatch.retain_dispatch_observation(captured[1],NativeResponse(200,'LATE-FALLBACK',body),runtime=c.runtime)
    assert reconcile(c,view,prior)['accepted']
    saved=dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert saved.accepted and saved.state=='REPORTED' and saved.attempt_id==first['name']
    assert len(c.built)==1 and c.head()=='1' and c.adapter.send.call_count==3


@pytest.mark.parametrize('case',[(0,'company','Live',True),(0,'company','Live',False)],indirect=True)
def test_endpoint_specific_production_duplicate_acceptance_uses_the_same_review_path(handoff,monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.tests.test_native_response import duplicate_body
    c=handoff;c.company.custom_production_url='https://gw-fatoora.zatca.gov.sa/e-invoicing/core/'
    reporting=c.customer.custom_b2c
    view,first,prior,*_=pair(c,monkeypatch,status=409 if reporting else 208,
        body=json.dumps(duplicate_body()).encode() if reporting else None)
    assert reconcile(c,view,prior)['accepted']
    saved=dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert saved.outcome==('REPORTING_DUPLICATE_MATCHED' if reporting else 'CLEARANCE_DUPLICATE_MATCHED')
    assert c.head()=='1' and c.adapter.send.call_count==2
