"""Explicit request retirement and resumed-worker exclusion on private SQL."""

import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf import submission_intent_retirement as retirement
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf import native_invoice_lifecycle as lifecycle_guard
from zatca_erpgulf.zatca_erpgulf import collection_intent
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError,owned_worker_transaction
from zatca_erpgulf.zatca_erpgulf.tests.test_native_invoice_lifecycle_mariadb import (
    lifecycle,handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def prepare(c,collection=False):
    if collection:
        result=collection_intent.register_native_collection(c.source,runtime=c.runtime,translate=str,intent='manual')
        identifier=result['request_id']
    else:
        c.register();identifier=c.rows()[0]['record_id']
    c.database.commit()
    return identifier


def row(c,identifier):
    return c.database.sql('SELECT * FROM '+intent.TABLE+' WHERE name=%s',(identifier,),as_dict=True)[0]


def retire(c,identifier,expected_state='READY',expected_fence=None):
    return retirement.retire_unissued_intent(identifier,expected_state,expected_fence,runtime=c.runtime)


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Background',True),(0,'linked','Live',True)],indirect=True)
@pytest.mark.parametrize('collection',[False,True])
def test_explicit_retirement_preserves_header_and_proves_normal_lifecycle_admission(lifecycle,collection):
    c=lifecycle;identifier=prepare(c,collection);before=row(c,identifier)
    result=retire(c,identifier);after=row(c,identifier)
    assert result['status']=='RETIRED' and result['accepted'] is False
    assert after['intent_header']==before['intent_header'] and after['intent_ciphertext']==before['intent_ciphertext']
    assert after['active_key'] is None and after['resolution_ciphertext']
    proof=json.loads(after['resolution_header']);assert proof['retired_by']==c.runtime.session.user
    assert retire(c,identifier)['reused'] and c.head()=='0' and not c.sent and not c.built
    for method in ('before_cancel','on_trash','before_rename'):
        lifecycle_guard.inspect_source_lifecycle(c.source,runtime=c.runtime,method=method)
    build=Mock()
    assert worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build)['status']=='RETIRED'
    build.assert_not_called()


@pytest.mark.parametrize('collection',[False,True])
def test_resumed_running_worker_cannot_generate_or_finish_after_authenticated_retirement(lifecycle,collection):
    c=lifecycle;identifier=prepare(c,collection);header,fence,state=worker._claim(c.runtime,identifier)
    assert state=='RUNNING';retire(c,identifier,state,fence)
    with pytest.raises(intent.SubmissionIntentError,match='execution_fence'):
        worker._process(c.runtime,str,header,lambda doc:c.run(),fence)
    with pytest.raises(intent.SubmissionIntentError,match='completion_fence'):
        worker._finish(c.runtime,header,fence,'COMPLETE','prepared')
    assert row(c,identifier)['state']=='RETIRED' and c.head()=='0' and not c.sent and not c.built


@pytest.mark.parametrize('state',['READY','WAITING','REVIEW'])
def test_current_nonstarted_review_or_waiting_request_can_be_explicitly_retired(lifecycle,state):
    c=lifecycle;identifier=prepare(c)
    c.database.sql('UPDATE '+intent.TABLE+' SET state=%s WHERE name=%s',(state,identifier));c.database.commit()
    assert retire(c,identifier,state)['status']=='RETIRED'


def test_stale_operator_claim_and_unauthorized_actor_cannot_retire(lifecycle,monkeypatch):
    c=lifecycle;identifier=prepare(c);header,fence,_=worker._claim(c.runtime,identifier)
    with pytest.raises(retirement.IntentRetirementError,match='could not be retired') as caught:retire(c,identifier)
    assert caught.value.code=='intent_retirement_claim_changed'
    monkeypatch.setattr(c.runtime,'get_roles',lambda actor:[])
    with pytest.raises(retirement.IntentRetirementError) as caught:retire(c,identifier,'RUNNING',fence)
    assert caught.value.code=='intent_retirement_access' and row(c,identifier)['state']=='RUNNING'


@pytest.mark.parametrize('already_retired',[False,True])
def test_normal_source_write_permission_is_required(lifecycle,monkeypatch,already_retired):
    c=lifecycle;identifier=prepare(c);original=c.runtime.has_permission
    if already_retired:retire(c,identifier)
    monkeypatch.setattr(c.runtime,'has_permission',lambda dt,operation,**kwargs:False if operation=='write' else original(dt,operation,**kwargs))
    with pytest.raises(Exception):retire(c,identifier)
    assert row(c,identifier)['state']==('RETIRED' if already_retired else 'READY') and not c.sent


@pytest.mark.parametrize('case',[(0,'company','Batches',True),(1,'device','Background',True)],indirect=True)
@pytest.mark.parametrize('state',['PREPARED','OUTCOME_UNKNOWN','REJECTED','REPORTED'])
def test_any_issuance_blocks_retirement_even_after_marker_erasure(lifecycle,state):
    c=lifecycle;identifier=prepare(c);assert c.run()['status']=='PREPARED'
    c.database.sql('UPDATE `tabZATCA Issuance` SET state=%s WHERE source_name=%s',(state,c.source.name))
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_zatca_issuing_unit=NULL,custom_uuid=NULL WHERE name=%s',(c.source.name,))
    c.database.commit();before=(c.head(),len(c.built),len(c.sent))
    with pytest.raises(retirement.IntentRetirementError) as caught:retire(c,identifier)
    assert caught.value.code=='intent_retirement_issued' and row(c,identifier)['state']=='READY'
    assert (c.head(),len(c.built),len(c.sent))==before


@pytest.mark.parametrize('tamper',['missing','copied','state','actor','header','cipher','fence'])
def test_retirement_tampering_never_grants_destructive_permission(lifecycle,tamper):
    c=lifecycle;identifier=prepare(c);retire(c,identifier);saved=row(c,identifier)
    if tamper=='missing':statement='resolution_ciphertext=NULL';values=()
    elif tamper=='copied':
        proof=json.loads(saved['resolution_header']);proof['record_id']=str(uuid4())
        statement='resolution_header=%s';values=(json.dumps(proof),)
    elif tamper=='state':statement='state=%s';values=('READY',)
    elif tamper in ('actor','header'):
        proof=json.loads(saved['resolution_header']);proof['retired_by' if tamper=='actor' else 'reason']='FORGED'
        statement='resolution_header=%s';values=(json.dumps(proof),)
    elif tamper=='fence':statement='fence_token=%s';values=(str(uuid4()),)
    else:statement='resolution_ciphertext=%s';values=('BROKEN',)
    c.database.sql('UPDATE '+intent.TABLE+' SET '+statement+' WHERE name=%s',(*values,identifier));c.database.commit()
    with pytest.raises(Exception):lifecycle_guard.inspect_source_lifecycle(c.source,runtime=c.runtime)
    with owned_worker_transaction(c.runtime) as owner:
        with pytest.raises(Exception):intent.open_intent(owner,identifier)
    assert c.head()=='0' and not c.sent


def test_unknown_commit_ack_preserves_terminal_proof_without_compensation(lifecycle,monkeypatch):
    c=lifecycle;identifier=prepare(c);original=c.database.commit
    def lost_ack():original();raise RuntimeError('PRIVATE COMMIT ACK')
    monkeypatch.setattr(c.database,'commit',lost_ack)
    with pytest.raises(WorkerTransactionError) as caught:retire(c,identifier)
    assert caught.value.commit_uncertain
    monkeypatch.setattr(c.database,'commit',original)
    assert row(c,identifier)['state']=='RETIRED' and retire(c,identifier)['reused']
    assert c.head()=='0' and not c.sent


def test_parent_writes_are_not_taken_over_by_an_operator_request(lifecycle):
    c=lifecycle;identifier=prepare(c);c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    commits=c.database.commits
    with pytest.raises(WorkerTransactionError,match='parent_state'):retire(c,identifier)
    assert c.database.commits==commits and row(c,identifier)['state']=='READY'


@pytest.mark.parametrize('case',[(0,'company','Batches',True)],indirect=True)
def test_authenticated_expected_original_cannot_be_retired_when_custody_disappears(lifecycle):
    c=lifecycle;assert c.run()['status']=='PREPARED'
    identifier=prepare(c,collection=True)
    assert json.loads(row(c,identifier)['intent_header'])['expected_issuance_id']
    # Corrupt only the fixture's history to simulate missing custody. The
    # operator action must not convert that loss into negative evidence.
    c.database.sql('DELETE FROM `tabZATCA Issuance` WHERE source_name=%s',(c.source.name,))
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_zatca_issuing_unit=NULL,custom_uuid=NULL WHERE name=%s',(c.source.name,))
    c.database.commit()
    with pytest.raises(retirement.IntentRetirementError) as caught:retire(c,identifier)
    assert caught.value.code=='intent_retirement_original_expected' and c.head()=='1'


def test_one_retired_request_does_not_release_a_second_active_source_request(lifecycle):
    c=lifecycle;first=prepare(c);second=prepare(c,collection=True)
    retire(c,first)
    with pytest.raises(lifecycle_guard.NativeInvoiceLifecycleError):
        lifecycle_guard.inspect_source_lifecycle(c.source,runtime=c.runtime)
    retire(c,second)
    lifecycle_guard.inspect_source_lifecycle(c.source,runtime=c.runtime)
    assert c.head()=='0' and not c.sent


def test_unreadable_proof_is_detected_before_retirement_commit(lifecycle,monkeypatch):
    c=lifecycle;identifier=prepare(c);original=c.database.sql;commits=c.database.commits
    def truncated(statement,values=(),**kwargs):
        if statement.startswith('UPDATE '+intent.TABLE) and 'resolution_header=%s' in statement:
            values=(*values[:3],values[3][:10],*values[4:])
        return original(statement,values,**kwargs)
    monkeypatch.setattr(c.database,'sql',truncated)
    with pytest.raises(Exception):retire(c,identifier)
    assert row(c,identifier)['state']=='READY' and row(c,identifier)['resolution_ciphertext'] is None
    assert c.database.commits==commits and c.head()=='0' and not c.sent
