"""Durable corrected preparation on private SQL; generation never sends HTTP."""

import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import corrected_preparation as correction,submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf import submission_intent_reconciliation as reconciliation,native_dispatch as dispatch
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_correction_clock_mariadb import rejected,metadata_runtime
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import signed_build
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


@pytest.fixture(autouse=True)
def command_records(handoff):
    # Deliberately corrupt READY rows must not become another test's recovery
    # input. Delete only IDs created by this case in its fixture-owned server.
    handoff.corrected_commands=set()
    yield
    handoff.original_rollback()
    with handoff.connection.cursor() as cursor:
        for identifier in handoff.corrected_commands:
            cursor.execute('DELETE FROM `tabZATCA Submission Intent` WHERE name=%s',(identifier,))
    handoff.connection.commit()


def row(c,identifier):
    return c.database.sql('SELECT * FROM `tabZATCA Submission Intent` WHERE name=%s',(identifier,),as_dict=True)[0]


def prior(c,view):
    return c.database.sql('SELECT * FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(view.attempt_id,),as_dict=True)[0]


def register(c,view,fence=None):
    result=correction.register_corrected_preparation(view.issuance_id,view.attempt_id,
        fence or prior(c,view)['fence_token'],runtime=c.runtime,translate=str)
    c.corrected_commands.add(result['request_id']);return result


def builder(c):
    return Mock(side_effect=lambda source:signed_build(c.b,source,
        validation_type='Simplified Invoice' if c.customer.custom_b2c else 'Standard Invoice',
        endpoint='invoices/reporting/single' if c.customer.custom_b2c else 'invoices/clearance/single'))


def execute(c,identifier,build=None):
    return worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build or builder(c))


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),(0,'linked','Live',False)],indirect=True)
@pytest.mark.parametrize('corrected_data',[False,True])
def test_fixed_command_prepares_one_linked_original_after_commit_and_never_sends(handoff,corrected_data):
    c=handoff;view=rejected(c)
    if corrected_data:
        c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=116 WHERE name=%s',(c.source.name,));c.database.commit()
    before=c.runtime.get_doc(c.source.doctype,c.source.name).as_dict();calls=c.adapter.send.call_count;commits=c.database.commits
    result=register(c,view);identifier=result['request_id']
    assert result['status']=='DEFERRED' and not result['accepted'] and row(c,identifier)['state']=='STAGED'
    assert c.database.commits==commits and c.head()=='1' and c.adapter.send.call_count==calls
    c.database.commit();saved=row(c,identifier);header=json.loads(saved['intent_header'])
    assert saved['state']=='READY' and header['request_kind']=='correction-v1' and header['intent']=='correction'
    assert header['rejected_attempt_id']==view.attempt_id and header['rejected_fence_token']==prior(c,view)['fence_token']
    build=builder(c);assert execute(c,identifier,build)['status']=='COMPLETE';build.assert_called_once()
    assert build.call_args.args[0].grand_total==before['grand_total']
    current=dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_current_source=True)
    assert current.state=='PREPARED' and not current.accepted and current.attempt_id is None and current.issuance_id!=view.issuance_id
    new=c.database.sql('SELECT * FROM `tabZATCA Issuance` WHERE name=%s',(current.issuance_id,),as_dict=True)[0]
    assert new['replaces_issuance']==view.issuance_id and new['origin_ciphertext'] is None
    assert c.head()=='2' and c.adapter.send.call_count==calls and row(c,identifier)['active_key'] is None
    again=Mock(side_effect=AssertionError('Completed commands must not regenerate'))
    assert execute(c,identifier,again)['status']=='COMPLETE';again.assert_not_called()
    after=c.runtime.get_doc(c.source.doctype,c.source.name).as_dict()
    outputs={'custom_uuid','custom_zatca_icv','custom_zatca_issuing_unit','custom_zatca_status','custom_zatca_full_response'}
    assert {key:value for key,value in after.items() if key not in outputs}=={key:value for key,value in before.items() if key not in outputs}


def test_parent_rollback_cancels_only_the_correction_command(handoff):
    c=handoff;view=rejected(c);result=register(c,view);callback=c.database.after_commit._functions[0]
    c.database.rollback();callback()
    assert not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE name=%s',(result['request_id'],),as_dict=True)
    assert c.head()=='1' and dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime).state=='REJECTED'


def test_repeated_approval_coalesces_without_rewriting_immutable_header(handoff):
    c=handoff;view=rejected(c);first=register(c,view);c.database.commit();old=row(c,first['request_id'])
    second=register(c,view)
    assert second['reused'] and second['request_id']==first['request_id']
    assert row(c,first['request_id'])['intent_ciphertext']==old['intent_ciphertext']


@pytest.mark.parametrize('fault',['fence','phase','rollout','role','write','receipt'])
def test_registration_cannot_waive_rejection_or_current_authority(handoff,monkeypatch,fault):
    c=handoff;view=rejected(c);fence=prior(c,view)['fence_token']
    if fault=='fence':fence=str(uuid4())
    elif fault=='phase':c.company.custom_phase_1_or_2='Phase-1'
    elif fault=='rollout':c.runtime.conf['zatca_native_dispatch']=0
    elif fault=='role':monkeypatch.setattr(c.runtime,'get_roles',lambda user:[])
    elif fault=='write':
        permission=c.runtime.has_permission
        monkeypatch.setattr(c.runtime,'has_permission',lambda dt,op,**kwargs:False if op=='write' else permission(dt,op,**kwargs))
    else:
        c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET receipt_ciphertext=%s WHERE name=%s',('BROKEN',view.attempt_id));c.database.commit()
    with pytest.raises(Exception):register(c,view,fence)
    assert c.head()=='1' and not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE source_name=%s',(c.source.name,),as_dict=True)


def test_before_commit_does_not_approve_changed_fiscal_data(handoff):
    c=handoff;view=rejected(c);result=register(c,view)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=116 WHERE name=%s',(c.source.name,))
    with pytest.raises(Exception):c.database.commit()
    assert row(c,result['request_id'])['state']=='STAGED' and c.head()=='1'


@pytest.mark.parametrize('fault',['fiscal','role','fence','index'])
def test_worker_rechecks_approval_before_generation(handoff,monkeypatch,fault):
    c=handoff;view=rejected(c);result=register(c,view);c.database.commit();identifier=result['request_id']
    if fault=='fiscal':c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=116 WHERE name=%s',(c.source.name,))
    elif fault=='role':monkeypatch.setattr(c.runtime,'get_roles',lambda user:[])
    elif fault=='fence':c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET fence_token=%s WHERE name=%s',(str(uuid4()),view.attempt_id))
    else:c.database.sql('UPDATE `tabZATCA Submission Intent` SET rejected_fence_token=%s WHERE name=%s',(str(uuid4()),identifier))
    c.database.commit();build=Mock()
    if fault=='index':
        with pytest.raises(Exception):execute(c,identifier,build)
    else:assert execute(c,identifier,build)['status']=='REVIEW'
    build.assert_not_called();assert c.head()=='1'


@pytest.mark.parametrize('reconcile',[False,True])
def test_stopped_worker_reuses_or_reconciles_the_protected_link_without_another_build(handoff,reconcile):
    c=handoff;view=rejected(c);result=register(c,view);c.database.commit();identifier=result['request_id']
    header,fence,state=worker._claim(c.runtime,identifier);assert state=='RUNNING'
    assert worker._process(c.runtime,str,header,builder(c),fence)['status']=='PREPARED'
    assert c.head()=='2';build=Mock(side_effect=AssertionError('No second corrected version'))
    if reconcile:
        completed=reconciliation.reconcile_saved_result(identifier,'RUNNING',fence,runtime=c.runtime)
        assert completed['status']=='COMPLETE' and not completed['accepted']
    else:
        assert worker._process(c.runtime,str,header,build,fence)['reused']
        worker._finish(c.runtime,header,fence,'COMPLETE','prepared')
    build.assert_not_called();assert c.head()=='2' and row(c,identifier)['state']=='COMPLETE'


def test_queue_failure_keeps_ready_command_for_existing_actor_recovery(handoff):
    c=handoff;view=rejected(c);result=register(c,view);identifier=result['request_id']
    c.runtime.enqueue.side_effect=RuntimeError('PRIVATE REDIS')
    with pytest.raises(Exception):c.database.commit()
    assert row(c,identifier)['state']=='READY';c.runtime.enqueue.side_effect=None;c.runtime.enqueue.reset_mock()
    assert worker.rediscover_ready_intents(runtime=c.runtime)>=1
    assert any(call.kwargs.get('record_id')==identifier for call in c.runtime.enqueue.call_args_list)
    assert execute(c,identifier)['status']=='COMPLETE' and c.head()=='2'


def test_foreign_parent_writes_are_neither_committed_nor_rolled_back(handoff):
    c=handoff;view=rejected(c)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=116 WHERE name=%s',(c.source.name,));commits=c.database.commits
    with pytest.raises(WorkerTransactionError,match='parent_state'):register(c,view)
    assert c.database.commits==commits and c.head()=='1'


def test_uncertain_creation_commit_is_reconciled_from_linked_custody_without_compensation(handoff,monkeypatch):
    c=handoff;view=rejected(c);result=register(c,view);c.database.commit();identifier=result['request_id']
    commit=c.database.commit;lost={'done':False}
    def lost_ack():
        created=c.database.sql('SELECT name FROM `tabZATCA Issuance` WHERE source_name=%s AND source_version=2',
            (c.source.name,),as_dict=True)
        commit()
        if created and not lost['done']:
            lost['done']=True;raise RuntimeError('PRIVATE COMMIT ACK LOST')
    monkeypatch.setattr(c.database,'commit',lost_ack)
    assert execute(c,identifier)['status']=='REVIEW' and lost['done'] and c.head()=='2'
    saved=row(c,identifier);assert saved['resolution_ciphertext'] is None
    assert reconciliation.reconcile_saved_result(identifier,'REVIEW',saved['fence_token'],runtime=c.runtime)['accepted'] is False
    assert row(c,identifier)['state']=='COMPLETE' and c.head()=='2'


@pytest.mark.parametrize('fault',['fiscal','fence'])
def test_actual_generation_rechecks_after_worker_preflight(handoff,monkeypatch,fault):
    c=handoff;view=rejected(c);result=register(c,view);c.database.commit();core=correction.prepare_corrected_rejection
    def changed(*args,**kwargs):
        if fault=='fiscal':c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=117 WHERE name=%s',(c.source.name,))
        else:c.database.sql('UPDATE `tabZATCA Dispatch Attempt` SET fence_token=%s WHERE name=%s',(str(uuid4()),view.attempt_id))
        c.database.commit();return core(*args,**kwargs)
    monkeypatch.setattr(correction,'prepare_corrected_rejection',changed)
    build=Mock()
    assert execute(c,result['request_id'],build)['status']=='REVIEW';build.assert_not_called();assert c.head()=='1'


def test_an_explicit_new_request_after_pre_generation_failure_retains_the_old_review(handoff):
    c=handoff;view=rejected(c);first=register(c,view);c.database.commit()
    assert execute(c,first['request_id'],Mock(side_effect=RuntimeError('SYNTHETIC BUILD FAILURE')))['status']=='REVIEW'
    old=row(c,first['request_id']);assert c.head()=='1'
    second=register(c,view);assert second['request_id']!=first['request_id'];c.database.commit()
    assert execute(c,second['request_id'])['status']=='COMPLETE' and c.head()=='2'
    kept=row(c,first['request_id'])
    assert kept['state']=='REVIEW' and kept['active_key'] is None and kept['intent_ciphertext']==old['intent_ciphertext']
