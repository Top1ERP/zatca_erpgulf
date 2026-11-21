"""Stopped handoff reconciliation against canonical custody; HTTP is mocked."""

import hashlib
import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest
from requests.exceptions import ReadTimeout

from zatca_erpgulf.zatca_erpgulf import collection_intent,native_dispatch
from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf import submission_intent_reconciliation as reconciliation
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError,owned_worker_transaction
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def start(c,*,collection=False,process=True):
    if collection:
        result=collection_intent.register_native_collection(c.source,runtime=c.runtime,translate=str,intent='manual')
        identifier=result['request_id']
    else:
        c.register();identifier=c.rows()[0]['record_id']
    c.database.commit()
    header,fence,state=worker._claim(c.runtime,identifier)
    assert state=='RUNNING'
    result=worker._process(c.runtime,str,header,lambda source:c.run(),fence) if process else None
    return identifier,header,fence,result


def row(c,identifier):
    return c.database.sql('SELECT * FROM '+intent.TABLE+' WHERE name=%s',(identifier,),as_dict=True)[0]


def reconcile(c,identifier,fence,state='RUNNING'):
    return reconciliation.reconcile_saved_result(identifier,state,fence,runtime=c.runtime)


@pytest.mark.parametrize('case',[(0,'company','Batches',True),(1,'device','Background',True),
    (0,'linked','Live',True),(1,'linked','Live',False)],indirect=True)
@pytest.mark.parametrize('collection',[False,True])
@pytest.mark.parametrize('review',[False,True])
def test_stopped_worker_completes_only_from_current_saved_original_and_verified_receipt(handoff,collection,review):
    c=handoff;identifier,header,fence,operation=start(c,collection=collection)
    if review:worker._finish(c.runtime,header,fence,'REVIEW','native_operation_review')
    state='REVIEW' if review else 'RUNNING'
    before=row(c,identifier)
    old=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert old is not None
    c.runtime.conf['zatca_native_dispatch']=0  # This is local evidence review, not a rollout/send operation.
    c.selected.custom_private_key='UNAVAILABLE-OLD-SIGNING-KEY'
    snapshot=(c.head(),len(c.sent),len(c.built),c.adapter.send.call_count)
    result=reconcile(c,identifier,fence,state);saved=row(c,identifier)
    assert result['status']=='COMPLETE' and result['accepted']==old.accepted
    assert saved['state']=='COMPLETE' and saved['active_key'] is None
    assert saved['intent_header']==before['intent_header'] and saved['intent_ciphertext']==before['intent_ciphertext']
    proof=json.loads(saved['resolution_header'])
    assert proof['issuance_id']==old.issuance_id and proof['original_xml_sha256']==hashlib.sha256(old.original_xml).hexdigest()
    assert proof['reason']==('reconciled_accepted' if old.accepted else 'reconciled_prepared')
    assert reconcile(c,identifier,fence,state)['reused']
    again=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert again.original_xml==old.original_xml and again.invoice_uuid==old.invoice_uuid and again.attempt_id==old.attempt_id
    assert (c.head(),len(c.sent),len(c.built),c.adapter.send.call_count)==snapshot
    with pytest.raises(intent.SubmissionIntentError,match='completion_fence'):
        worker._finish(c.runtime,header,fence,'COMPLETE','prepared')
    c.b.request.assert_not_called()


@pytest.mark.parametrize('status',[200,208])
@pytest.mark.parametrize('case',[(0,'company','Live',False)],indirect=True)
def test_cleared_and_duplicate_cleared_receipts_use_the_canonical_xml_matcher(handoff,status):
    c=handoff;original=c.adapter.send.side_effect
    # URL is only a captured policy label; the fixture HTTPAdapter and mandatory
    # offline guard prevent any real authority connection.
    c.company.custom_production_url='https://gw-fatoora.zatca.gov.sa/e-invoicing/core/'
    def cleared(prepared,**kwargs):
        response=original(prepared,**kwargs)
        payload=json.loads(prepared.body)
        body=json.dumps(dict(validationResults=dict(status='PASS',errorMessages=[],warningMessages=[],infoMessages=[]),
            clearanceStatus='CLEARED',clearedInvoice=payload['invoice'])).encode()
        response.status_code=status;response.raw.read1=Mock(side_effect=[body,b''])
        return response
    c.adapter.send.side_effect=cleared
    identifier,header,fence,result=start(c)
    assert result['accepted'] and len(c.sent)==1
    reconciled=reconcile(c,identifier,fence)
    assert reconciled['accepted'] and reconciled['issuance_state']=='CLEARED'
    assert json.loads(row(c,identifier)['resolution_header'])['outcome']==(
        'CLEARANCE_MATCHED' if status==200 else 'CLEARANCE_DUPLICATE_MATCHED')
    assert len(c.sent)==1


def test_crash_after_receipt_capture_reuses_canonical_assessment_without_another_send(handoff,monkeypatch):
    c=handoff;identifier,header,fence,_=start(c,process=False)
    monkeypatch.setattr(native_dispatch,'assess_retained_dispatch',Mock(side_effect=RuntimeError('PRIVATE PROCESS CRASH')))
    with pytest.raises(Exception):worker._process(c.runtime,str,header,lambda doc:c.run(),fence)
    before=len(c.sent)
    saved=c.database.sql('SELECT state FROM `tabZATCA Issuance` WHERE source_name=%s',(c.source.name,),as_dict=True)[0]
    assert saved['state']=='REVIEW_REQUIRED' and before==1
    result=reconcile(c,identifier,fence)
    assert result['accepted'] and result['issuance_state']=='REPORTED'
    assert row(c,identifier)['state']=='COMPLETE' and len(c.sent)==before and c.head()=='1'


def test_no_artifact_or_missing_source_marker_never_completes_a_request(handoff):
    c=handoff;identifier,header,fence,_=start(c,process=False)
    with pytest.raises(reconciliation.IntentReconciliationError):reconcile(c,identifier,fence)
    assert row(c,identifier)['state']=='RUNNING' and not c.sent and c.head()=='0'


def test_unknown_transport_cannot_be_turned_into_acceptance_or_an_automatic_retry(handoff):
    c=handoff;c.adapter.send.side_effect=ReadTimeout('PRIVATE TIMEOUT')
    identifier,header,fence,_=start(c,process=False)
    with pytest.raises(Exception):worker._process(c.runtime,str,header,lambda doc:c.run(),fence)
    before=c.adapter.send.call_count
    with pytest.raises(reconciliation.IntentReconciliationError) as caught:reconcile(c,identifier,fence)
    assert caught.value.code=='intent_reconciliation_outcome_unconfirmed'
    assert row(c,identifier)['state']=='RUNNING' and c.adapter.send.call_count==before==1 and c.head()=='1'


@pytest.mark.parametrize('corruption',['receipt','original','source_money','source_marker','request_fence','role','write_permission'])
def test_wrong_or_unavailable_evidence_keeps_the_old_request_and_never_sends(handoff,monkeypatch,corruption):
    c=handoff;identifier,header,fence,_=start(c)
    if corruption=='receipt':
        c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET receipt_ciphertext=%s WHERE source_name=%s',('BROKEN',c.source.name))
    elif corruption=='original':
        c.database.sql('UPDATE `tabZATCA Issuance` SET artifact_ciphertext=%s WHERE source_name=%s',('BROKEN',c.source.name))
    elif corruption=='source_money':
        c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    elif corruption=='source_marker':
        c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_zatca_issuing_unit=NULL WHERE name=%s',(c.source.name,))
    elif corruption=='request_fence':
        c.database.sql('UPDATE '+intent.TABLE+' SET fence_token=%s WHERE name=%s',(str(uuid4()),identifier))
    elif corruption=='role':monkeypatch.setattr(c.runtime,'get_roles',lambda user:[])
    else:
        previous=c.runtime.has_permission
        monkeypatch.setattr(c.runtime,'has_permission',lambda dt,op,**kwargs:False if op=='write' else previous(dt,op,**kwargs))
    c.database.commit();snapshot=(c.head(),len(c.sent),len(c.built))
    with pytest.raises(Exception):reconcile(c,identifier,fence)
    assert row(c,identifier)['state']=='RUNNING' and row(c,identifier)['resolution_ciphertext'] is None
    assert (c.head(),len(c.sent),len(c.built))==snapshot


@pytest.mark.parametrize('change',['cipher','header','state','fence'])
def test_audit_capsule_tampering_does_not_authorize_execution_or_idempotent_acceptance(handoff,change):
    c=handoff;identifier,header,fence,_=start(c);reconcile(c,identifier,fence)
    if change=='cipher':clause='resolution_ciphertext=%s';value='BROKEN'
    elif change=='header':
        proof=json.loads(row(c,identifier)['resolution_header']);proof['resolved_by']='FORGED'
        clause='resolution_header=%s';value=json.dumps(proof)
    elif change=='state':clause='state=%s';value='RUNNING'
    else:clause='fence_token=%s';value=str(uuid4())
    c.database.sql('UPDATE '+intent.TABLE+' SET '+clause+' WHERE name=%s',(value,identifier));c.database.commit()
    with owned_worker_transaction(c.runtime) as owner:
        with pytest.raises(Exception):intent.open_intent(owner,identifier)
    with pytest.raises(Exception):reconcile(c,identifier,fence)
    assert len(c.sent)==1


def test_unknown_commit_ack_retains_reconciliation_without_compensating_originals(handoff,monkeypatch):
    c=handoff;identifier,header,fence,_=start(c);original=c.database.commit
    def lost_ack():original();raise RuntimeError('PRIVATE COMMIT')
    monkeypatch.setattr(c.database,'commit',lost_ack)
    with pytest.raises(WorkerTransactionError) as caught:reconcile(c,identifier,fence)
    assert caught.value.commit_uncertain
    monkeypatch.setattr(c.database,'commit',original)
    assert row(c,identifier)['state']=='COMPLETE' and reconcile(c,identifier,fence)['reused']
    assert len(c.sent)==1 and c.head()=='1'


def test_parent_transaction_is_not_committed_to_force_reconciliation(handoff):
    c=handoff;identifier,header,fence,_=start(c)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    commits=c.database.commits
    with pytest.raises(WorkerTransactionError,match='parent_state'):reconcile(c,identifier,fence)
    assert c.database.commits==commits and row(c,identifier)['state']=='RUNNING'


def test_reviewing_manager_does_not_impersonate_the_original_disabled_actor(handoff):
    c=handoff;identifier,header,fence,_=start(c)
    c.database.sql('UPDATE `tabUser` SET enabled=0 WHERE name=%s',(header['actor'],));c.database.commit()
    c.runtime.set_user('Administrator');queued=c.runtime.enqueue.call_count
    assert reconcile(c,identifier,fence)['accepted']
    saved=row(c,identifier)
    assert json.loads(saved['intent_header'])['actor']==header['actor']
    assert json.loads(saved['resolution_header'])['resolved_by']=='Administrator'
    assert c.runtime.enqueue.call_count==queued and len(c.sent)==1


def test_unreadable_resolution_rolls_back_new_assessment_with_request_state(handoff,monkeypatch):
    c=handoff;identifier,header,fence,_=start(c,process=False)
    monkeypatch.setattr(native_dispatch,'assess_retained_dispatch',Mock(side_effect=RuntimeError('PROCESS CRASH')))
    with pytest.raises(Exception):worker._process(c.runtime,str,header,lambda doc:c.run(),fence)
    original=c.database.sql
    def truncated(statement,values=(),**kwargs):
        if statement.startswith('UPDATE '+intent.TABLE) and 'resolution_header=%s' in statement:
            values=(*values[:3],values[3][:10],*values[4:])
        return original(statement,values,**kwargs)
    monkeypatch.setattr(c.database,'sql',truncated)
    with pytest.raises(Exception):reconcile(c,identifier,fence)
    assert row(c,identifier)['state']=='RUNNING' and row(c,identifier)['resolution_ciphertext'] is None
    issued=c.database.sql('SELECT state FROM `tabZATCA Issuance` WHERE source_name=%s',(c.source.name,),as_dict=True)[0]
    attempt=c.database.sql('SELECT outcome FROM `tabZATCA Dispatch Attempt` WHERE source_name=%s',(c.source.name,),as_dict=True)[0]
    assert issued['state']=='REVIEW_REQUIRED' and attempt['outcome'] is None
    assert len(c.sent)==1 and c.head()=='1'
