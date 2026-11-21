"""Explicit retry of exact saved bytes on private SQL; HTTP remains mocked."""

import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from requests.exceptions import ReadTimeout

from zatca_erpgulf.zatca_erpgulf import exact_retry,native_dispatch
from zatca_erpgulf.zatca_erpgulf.native_transport import NativeResponse
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def unknown(c,*,failure=None):
    c.normal_send=c.adapter.send.side_effect
    if failure is None:c.adapter.send.side_effect=ReadTimeout('PRIVATE SYNTHETIC TIMEOUT')
    else:
        def failed(prepared,**kwargs):
            response=c.normal_send(prepared,**kwargs)
            response.status_code=failure;response.raw.read1=Mock(side_effect=[b'SYNTHETIC FAILURE',b''])
            return response
        c.adapter.send.side_effect=failed
    try:c.run()
    except Exception:pass
    view=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_current_source=True)
    assert view.state=='OUTCOME_UNKNOWN' and view.attempt_id and c.head()=='1'
    prior=c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(view.attempt_id,),as_dict=True)[0]
    return view,prior


def expire(c,prior):
    # Only the fixture's unreceived attempt is aged. Received-failure AAD contains
    # its original lease and is never rewritten to manufacture expiry.
    c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET lease_expires_at_utc=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE name=%s',
        (prior['name'],));c.database.commit()


def register(c,view,prior):
    return exact_retry.register_exact_retry(view.issuance_id,view.attempt_id,prior['fence_token'],runtime=c.runtime,translate=str)


def command(c,identifier):
    return c.database.sql('SELECT * FROM `tabZATCA Submission Intent` WHERE name=%s',(identifier,),as_dict=True)[0]


def execute(c,identifier):
    build=Mock(side_effect=AssertionError('An exact retry cannot regenerate an invoice'))
    result=worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build)
    build.assert_not_called();return result


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),(0,'linked','Live',False)],indirect=True)
def test_explicit_retry_uses_same_xml_uuid_hash_icv_and_new_fenced_attempt(handoff):
    c=handoff;view,prior=unknown(c);original=c.adapter.send.call_args.args[0].body
    expire(c,prior);c.adapter.send.side_effect=c.normal_send
    before=c.adapter.send.call_count;commits=c.database.commits
    result=register(c,view,prior);identifier=result['request_id']
    assert result['status']=='DEFERRED' and result['accepted'] is False
    assert command(c,identifier)['state']=='STAGED' and c.database.commits==commits
    assert c.adapter.send.call_count==before
    c.database.commit();saved=command(c,identifier);header=json.loads(saved['intent_header'])
    assert saved['state']=='READY' and header['request_kind']=='retry-v1' and header['intent']=='retry'
    assert header['retry_attempt_id']==view.attempt_id and header['retry_fence_token']==prior['fence_token']
    assert header['expected_issuance_id']==view.issuance_id
    assert execute(c,identifier)['status']=='COMPLETE'
    again=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert again.accepted and again.attempt_id!=view.attempt_id
    assert again.original_xml==view.original_xml and again.invoice_uuid==view.invoice_uuid and again.icv==view.icv
    assert all(body==original for body in c.sent) and len(c.built)==1 and c.head()=='1'
    assert c.adapter.send.call_count-before==(1 if c.customer.custom_b2c else 2)
    assert execute(c,identifier)['status']=='COMPLETE' and len(c.built)==1


def test_unexpired_unknown_reservation_is_not_retry_authority(handoff):
    c=handoff;view,prior=unknown(c);before=c.adapter.send.call_count
    with pytest.raises(Exception):register(c,view,prior)
    assert c.adapter.send.call_count==before and not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE source_name=%s',
        (c.source.name,),as_dict=True)


@pytest.mark.parametrize('failure',[401,500,503])
def test_received_failure_requires_matching_custody_and_can_retry_without_rewriting_lease(handoff,failure):
    c=handoff;view,prior=unknown(c,failure=failure);before=c.adapter.send.call_count
    c.adapter.send.side_effect=c.normal_send
    result=register(c,view,prior);c.database.commit()
    assert execute(c,result['request_id'])['status']=='COMPLETE'
    after=c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(view.attempt_id,),as_dict=True)[0]
    assert after['receipt_ciphertext']==prior['receipt_ciphertext'] and after['lease_expires_at_utc']==prior['lease_expires_at_utc']
    assert c.adapter.send.call_count==before+1 and len(c.built)==1 and c.head()=='1'


def test_corrupt_received_failure_cannot_shortcut_a_lease(handoff):
    c=handoff;view,prior=unknown(c,failure=401)
    c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET receipt_ciphertext=%s WHERE name=%s',('BROKEN',view.attempt_id));c.database.commit()
    with pytest.raises(Exception):register(c,view,prior)
    assert c.adapter.send.call_count==1 and c.head()=='1'


def test_parent_rollback_cancels_retry_handoff_but_retains_original_uncertainty(handoff):
    c=handoff;view,prior=unknown(c);expire(c,prior)
    result=register(c,view,prior);callback=c.database.after_commit._functions[0]
    c.database.rollback();callback()
    assert not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE name=%s',(result['request_id'],),as_dict=True)
    again=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert again.state=='OUTCOME_UNKNOWN' and again.attempt_id==view.attempt_id and c.head()=='1'


def test_repeated_approval_coalesces_the_same_prior_attempt_without_header_rewrite(handoff):
    c=handoff;view,prior=unknown(c);expire(c,prior)
    first=register(c,view,prior);c.database.commit();old=command(c,first['request_id'])
    second=register(c,view,prior)
    assert first['request_id']==second['request_id'] and second['reused']
    assert command(c,first['request_id'])['intent_ciphertext']==old['intent_ciphertext']


@pytest.mark.parametrize('fault',['fence','actor','fiscal','body','phase','rollout'])
def test_stale_or_unavailable_retry_authority_never_regenerates_or_sends(handoff,monkeypatch,fault):
    c=handoff;view,prior=unknown(c);expire(c,prior)
    if fault=='fence':prior['fence_token']=str(uuid4())
    elif fault=='actor':monkeypatch.setattr(c.runtime,'get_roles',lambda user:[])
    elif fault=='fiscal':
        c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,));c.database.commit()
    elif fault=='body':
        c.database.sql('UPDATE `tabZATCA Issuance` SET artifact_ciphertext=%s WHERE name=%s',('BROKEN',view.issuance_id));c.database.commit()
    elif fault=='phase':c.company.custom_phase_1_or_2='Phase-1'
    else:c.runtime.conf['zatca_native_dispatch']=0
    with pytest.raises(Exception):register(c,view,prior)
    assert c.adapter.send.call_count==1 and c.head()=='1' and len(c.built)==1


def test_before_commit_rechecks_attempt_fence_instead_of_reusing_preflight(handoff):
    c=handoff;view,prior=unknown(c);expire(c,prior);result=register(c,view,prior)
    c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET fence_token=%s WHERE name=%s',(str(uuid4()),view.attempt_id))
    with pytest.raises(Exception):c.database.commit()
    assert command(c,result['request_id'])['state']=='STAGED' and c.adapter.send.call_count==1


def test_worker_rechecks_prior_attempt_after_committed_approval(handoff):
    c=handoff;view,prior=unknown(c);expire(c,prior);result=register(c,view,prior);c.database.commit()
    c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET fence_token=%s WHERE name=%s',(str(uuid4()),view.attempt_id));c.database.commit()
    assert execute(c,result['request_id'])['status']=='REVIEW' and c.adapter.send.call_count==1 and c.head()=='1'


def test_foreign_parent_writes_are_not_committed_or_rolled_back(handoff):
    c=handoff;view,prior=unknown(c);expire(c,prior)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,));commits=c.database.commits
    with pytest.raises(WorkerTransactionError,match='parent_state'):register(c,view,prior)
    assert c.database.commits==commits and c.adapter.send.call_count==1


def test_late_current_acceptance_after_approval_completes_without_another_send(handoff,monkeypatch):
    c=handoff;invoke=native_dispatch.invoke_saved_request;captured=[]
    def observed(invocation,**kwargs):
        captured.append(invocation);return invoke(invocation,**kwargs)
    monkeypatch.setattr(native_dispatch,'invoke_saved_request',observed)
    view,prior=unknown(c);expire(c,prior)
    result=register(c,view,prior);c.database.commit()
    body=json.dumps(dict(validationResults=dict(status='PASS',errorMessages=[],warningMessages=[],infoMessages=[]),
        reportingStatus='REPORTED')).encode()
    native_dispatch.retain_dispatch_observation(captured[0],NativeResponse(200,'SYNTHETIC-LATE',body),runtime=c.runtime)
    assessment,current=native_dispatch.assess_retained_dispatch(captured[0],runtime=c.runtime)
    assert current and assessment.outcome=='REPORTING_MATCHED'
    before=c.adapter.send.call_count
    assert execute(c,result['request_id'])['status']=='COMPLETE'
    assert c.adapter.send.call_count==before==1 and len(c.built)==1 and c.head()=='1'


@pytest.mark.parametrize('case',[(0,'company','Live',False)],indirect=True)
def test_retry_after_303_reporting_timeout_keeps_reporting_endpoint_and_original_bytes(handoff):
    c=handoff;normal=c.adapter.send.side_effect
    def timed_out_reporting(prepared,**kwargs):
        if prepared.url.endswith('invoices/reporting/single'):raise ReadTimeout('SYNTHETIC REPORTING TIMEOUT')
        return normal(prepared,**kwargs)
    c.adapter.send.side_effect=timed_out_reporting
    try:c.run()
    except Exception:pass
    view=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    prior=c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(view.attempt_id,),as_dict=True)[0]
    assert prior['endpoint']=='invoices/reporting/single' and view.state=='OUTCOME_UNKNOWN'
    original=c.adapter.send.call_args.args[0].body;expire(c,prior)
    result=register(c,view,prior);c.database.commit();c.adapter.send.side_effect=normal
    assert execute(c,result['request_id'])['status']=='COMPLETE'
    assert c.adapter.send.call_args.args[0].url.endswith('invoices/reporting/single')
    assert c.adapter.send.call_args.args[0].body==original and c.head()=='1' and len(c.built)==1


def test_retry_index_tampering_is_rejected_before_claim_or_transport(handoff):
    c=handoff;view,prior=unknown(c);expire(c,prior);result=register(c,view,prior);c.database.commit()
    c.database.sql('UPDATE `tabZATCA Submission Intent` SET retry_attempt_id=%s WHERE name=%s',
        (str(uuid4()),result['request_id']));c.database.commit()
    with pytest.raises(Exception):execute(c,result['request_id'])
    assert c.adapter.send.call_count==1 and c.head()=='1'
