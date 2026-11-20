"""Parent ERP-shaped transaction and durable queue handoff on private InnoDB.

Only a fixture-owned TCP-disabled server and synthetic source/build/HTTP doubles
are used. This does not install ERP schema, activate an EGS or contact ZATCA.
"""

from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import os

import pytest

from zatca_erpgulf.zatca_erpgulf import deferred_submission as deferred
from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf import native_provider
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider_mariadb import (
    case,boundary,materials,isolated_server,connections,tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_publication_mariadb import use_native_source
from zatca_erpgulf.zatca_erpgulf.worker_transaction import CALLBACKS,owned_worker_transaction


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


class Callbacks:
    def __init__(self):self._functions=deque()
    def add(self,fn):self._functions.append(fn)
    def run(self):
        while self._functions:self._functions.popleft()()
    def reset(self):self._functions.clear()


@pytest.fixture
def handoff(case,monkeypatch):
    c=case;use_native_source(c,monkeypatch)
    c.runtime.flags={};c.runtime.enqueue=Mock();c.runtime.get_roles=lambda user:['System Manager']
    for name in CALLBACKS:setattr(c.database,name,Callbacks())
    c.original_commit=c.database.commit;c.original_rollback=c.database.rollback
    def commit():
        c.database.before_rollback.reset();c.database.after_rollback.reset()
        c.database.before_commit.run();c.original_commit();c.database.after_commit.run()
    def rollback():
        c.database.before_rollback.run();c.original_rollback();c.database.after_rollback.run()
        c.database.before_commit.reset();c.database.after_commit.reset()
    monkeypatch.setattr(c.database,'commit',commit);monkeypatch.setattr(c.database,'rollback',rollback)
    actor=c.runtime.session.user
    with c.connection.cursor() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabUser` (name VARCHAR(140) PRIMARY KEY,enabled INT) ENGINE=InnoDB')
        cursor.execute('INSERT INTO `tabUser` VALUES (%s,1) ON DUPLICATE KEY UPDATE enabled=1',(actor,))
    c.original_commit()
    def set_user(user):
        c.runtime.session.user=user;c.runtime.session.sid='';c.runtime.session.data={}
        for key in ('cache','form_dict','jenv','role_permissions','new_doc_templates','user_perms'):
            setattr(c.runtime.local,key,{})
    c.runtime.set_user=set_user
    def register():
        with deferred.invoice_submit_hook(c.source.doctype,c.source,runtime=c.runtime,translate=str):
            assert deferred.maybe_defer_invoice_submission(c.source.doctype,c.source.name,runtime=c.runtime,translate=str)
    c.register=register
    def rows():
        return c.database.sql('SELECT * FROM '+intent.TABLE+' WHERE source_key=%s',
            (intent.source_key(c.source.doctype,c.source.name),),as_dict=True)
    c.rows=rows
    c.execute=lambda:worker.run_submission_intent(c.rows()[0]['record_id'],runtime=c.runtime,translate=str,build=lambda source:c.run())
    def change(statement,values=()):
        other=c.connections()
        with other.cursor() as cursor:cursor.execute(statement,values)
        other.commit()
    c.change=change
    try:
        yield c
    finally:
        # Tests intentionally leave corrupt/uncertain records. Only this fixture's
        # temporary row is removed, so later global discovery is independent.
        c.original_rollback()
        with c.connection.cursor() as cursor:
            cursor.execute('DELETE FROM '+intent.TABLE+' WHERE source_key=%s',
                (intent.source_key(c.source.doctype,c.source.name),))
        c.connection.commit()


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),
    (0,'linked','Live',False),(0,'device','Batches',True),(1,'device','Background',True)],indirect=True)
def test_parent_commit_and_worker_use_durable_ids_one_native_original_and_mocked_transport(handoff):
    c=handoff;before=c.database.commits;c.register()
    staged=c.rows()[0]
    assert staged['state']=='STAGED' and staged['intent_header'] is None and c.head()=='0'
    assert c.database.commits==before and not c.sent and not c.built
    c.runtime.enqueue.assert_not_called()
    # ERP writes after the original submit hook are part of the final fiscal bind.
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=116 WHERE name=%s',(c.source.name,))
    c.database.commit()
    ready=c.rows()[0];assert ready['state']=='READY' and ready['intent_ciphertext']
    call=c.runtime.enqueue.call_args
    assert call.args==(intent.METHOD,) and call.kwargs['record_id']==ready['record_id']
    assert not {'doctype','invoice_name','user','actor'} & set(call.kwargs)
    result=c.execute()
    assert result['status']=='COMPLETE' and c.head()=='1' and len(c.built)==1
    expected_calls = (1 if c.customer.custom_b2c else 2) if c.company.custom_send_invoice_to_zatca=='Live' else 0
    assert len(c.sent)==expected_calls  # Standard fixture returns303 then Reporting.
    if expected_calls == 2:
        assert c.sent[0] == c.sent[1]
    assert c.rows()[0]['result_code'] in ('accepted','prepared')
    assert c.execute()['status']=='COMPLETE' and c.head()=='1' and len(c.built)==1
    c.b.request.assert_not_called()


def test_parent_rollback_removes_intent_and_retained_queue_callback_is_inert(handoff):
    c=handoff;c.register();retained=c.database.after_commit._functions[0]
    assert len(c.rows())==1
    c.database.rollback();assert not c.rows();retained()
    c.runtime.enqueue.assert_not_called();assert c.head()=='0'


def test_early_commit_cannot_finalize_or_discover_half_finished_hook(handoff):
    c=handoff
    with deferred.invoice_submit_hook(c.source.doctype,c.source,runtime=c.runtime,translate=str):
        deferred.maybe_defer_invoice_submission(c.source.doctype,c.source.name,runtime=c.runtime,translate=str)
        with pytest.raises(deferred.DeferredSubmissionError):c.database.commit()
    # Even a caller incorrectly catching the error and committing cannot make
    # the unsealed STAGED row eligible for authenticated READY discovery.
    c.database.commit();assert c.rows()[0]['state']=='STAGED'
    with owned_worker_transaction(c.runtime) as owner:
        with pytest.raises(intent.SubmissionIntentError,match='unfinalized'):intent.open_intent(owner,c.rows()[0]['record_id'])
    assert worker.rediscover_ready_intents(runtime=c.runtime)==0
    c.runtime.enqueue.assert_not_called();assert not c.sent


def test_queue_failure_after_commit_preserves_ready_intent_and_recovery_restores_original_actor(handoff):
    c=handoff;c.register();actor=c.runtime.session.user
    c.runtime.enqueue.side_effect=RuntimeError('PRIVATE-REDIS-CREDENTIAL')
    with pytest.raises(deferred.DeferredSubmissionError) as caught:c.database.commit()
    assert str(caught.value)==deferred.QUEUE_UNKNOWN and c.rows()[0]['state']=='READY'
    assert 'PRIVATE-REDIS' not in repr(c.runtime.log_error.call_args)
    c.runtime.set_user('Administrator');old=vars(c.runtime.session).copy()
    queued=[]
    c.runtime.enqueue.side_effect=lambda *args,**kwargs:queued.append((c.runtime.session.user,args,kwargs))
    assert worker.rediscover_ready_intents(runtime=c.runtime)>=1
    mine=[entry for entry in queued if entry[2]['record_id']==c.rows()[0]['record_id']]
    assert len(mine)==1 and mine[0][0]==actor and mine[0][1]==(intent.METHOD,)
    assert vars(c.runtime.session)==old
    c.runtime.set_user(actor)
    assert c.execute()['status']=='COMPLETE' and len(c.sent)==1


@pytest.mark.parametrize('change',['money','cancelled','permission','phase','chain','mode'])
def test_committed_policy_or_fiscal_drift_never_generates_or_sends(handoff,change):
    c=handoff;c.register();c.database.commit()
    if change=='money':c.change('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    elif change=='cancelled':c.change('UPDATE `tab'+c.source.doctype+'` SET docstatus=2 WHERE name=%s',(c.source.name,))
    elif change=='permission':c.runtime.has_permission=lambda *args,**kwargs:False
    elif change=='phase':c.company.custom_phase_1_or_2='Phase-1'
    elif change=='chain':c.selected.custom_zatca_native_chain=str(uuid4())
    else:c.runtime.conf['zatca_native_dispatch']=0
    assert c.execute()['status']=='REVIEW'
    assert not c.built and not c.sent and c.head()=='0'


def test_output_and_collection_changes_do_not_block_same_committed_fiscal_source(handoff):
    c=handoff;c.register();c.database.commit()
    c.change('UPDATE `tab'+c.source.doctype+'` SET outstanding_amount=0,status=%s WHERE name=%s',('Paid',c.source.name))
    assert c.execute()['status']=='COMPLETE' and c.head()=='1' and len(c.sent)==1


def test_actor_retry_upgrade_is_rejected_and_disabled_actor_is_held(handoff):
    c=handoff;c.register();c.database.commit();actor=c.runtime.session.user
    c.runtime.set_user('Administrator' if actor!='Administrator' else 'OTHER')
    with pytest.raises(intent.SubmissionIntentError,match='actor_changed'):c.execute()
    assert c.rows()[0]['state']=='READY' and not c.sent
    c.runtime.set_user(actor);c.change('UPDATE `tabUser` SET enabled=0 WHERE name=%s',(actor,))
    assert c.execute()['status']=='REVIEW' and c.rows()[0]['result_code']=='actor_disabled'
    assert not c.built and not c.sent


@pytest.mark.parametrize('field,value',[('actor','FORGED'),('intent_header','{}'),('intent_ciphertext','v1.invalid')])
def test_corrupt_committed_envelope_fails_closed_without_source_work(handoff,field,value):
    c=handoff;c.register();c.database.commit();identifier=c.rows()[0]['record_id']
    c.change('UPDATE '+intent.TABLE+' SET `'+field+'`=%s WHERE name=%s',(value,identifier))
    with pytest.raises((intent.SubmissionIntentError,DispatchRecordError)):c.execute()
    assert not c.sent and not c.built and c.head()=='0'


def test_running_crash_and_late_wrong_fence_are_not_automatically_replayed(handoff):
    c=handoff;c.register();c.database.commit();identifier=c.rows()[0]['record_id']
    header,fence,state=worker._claim(c.runtime,identifier)
    assert state=='RUNNING' and fence
    assert c.execute()['status']=='RUNNING' and not c.built
    with pytest.raises(intent.SubmissionIntentError,match='completion_fence'):
        worker._finish(c.runtime,header,str(uuid4()),'COMPLETE','prepared')
    assert c.rows()[0]['state']=='RUNNING' and c.head()=='0'


def test_source_changes_after_initial_worker_read_are_rechecked_under_chain_source_lock(handoff,monkeypatch):
    c=handoff;c.register();c.database.commit();original=native_provider._run
    def changed(*args,**kwargs):
        # The first worker observation is already bound; change SQL before the
        # owned coordinator reloads/locks it, without hiding this in a fake hash.
        c.change('UPDATE `tab'+c.source.doctype+'` SET grand_total=112 WHERE name=%s',(c.source.name,))
        return original(*args,**kwargs)
    monkeypatch.setattr(native_provider,'_run',changed)
    assert c.execute()['status']=='REVIEW' and c.head()=='0' and not c.built and not c.sent


def test_parent_schema_requires_transactional_engine_and_unique_source_slot(handoff):
    c=handoff
    # Fixture-owned DDL only, restored even when admission fails.
    with c.connection.cursor() as cursor:
        cursor.execute('SHOW INDEX FROM '+intent.TABLE+" WHERE Column_name='source_key'")
        key=cursor.fetchone()[2]
        cursor.execute('ALTER TABLE '+intent.TABLE+' DROP INDEX `'+key+'`')
    try:
        with pytest.raises(deferred.DeferredSubmissionError):c.register()
        assert not c.rows() and c.head()=='0'
    finally:
        c.database.rollback()
        with c.connection.cursor() as cursor:
            cursor.execute('ALTER TABLE '+intent.TABLE+' ADD UNIQUE KEY `'+key+'` (source_key)')
    assert not c.sent


def test_duplicate_pending_registration_and_completed_source_are_not_rearmed(handoff):
    c=handoff;c.register();c.register()
    assert len(c.rows())==1 and len(c.database.before_commit._functions)==1
    c.database.commit();assert c.execute()['status']=='COMPLETE'
    with pytest.raises(deferred.DeferredSubmissionError):c.register()
    assert c.rows()[0]['state']=='COMPLETE' and len(c.sent)==1 and c.head()=='1'


def test_ready_intent_survives_old_invoice_age_without_queuing_an_unstarted_record_as_admin(handoff):
    c=handoff;c.register();c.database.commit();identifier=c.rows()[0]['record_id']
    c.change('UPDATE '+intent.TABLE+' SET creation=%s WHERE name=%s',('2025-01-01 00:00:00',identifier))
    c.runtime.enqueue.reset_mock();actor=c.runtime.session.user
    c.runtime.set_user('Administrator');queued=[]
    c.runtime.enqueue.side_effect=lambda *args,**kwargs:queued.append((c.runtime.session.user,kwargs['record_id']))
    assert worker.rediscover_ready_intents(runtime=c.runtime)>=1
    assert (actor,identifier) in queued and c.runtime.session.user=='Administrator'
    assert not c.sent and c.head()=='0'


def test_recovery_queue_failure_restores_session_and_keeps_ready_record(handoff):
    c=handoff;c.register();c.database.commit();c.runtime.set_user('Administrator')
    old_session=vars(c.runtime.session).copy();old_local=vars(c.runtime.local).copy()
    c.runtime.enqueue.side_effect=RuntimeError('queue unavailable')
    with pytest.raises(RuntimeError):worker.rediscover_ready_intents(runtime=c.runtime)
    assert vars(c.runtime.session)==old_session and vars(c.runtime.local)==old_local
    assert c.rows()[0]['state']=='READY' and not c.sent


def test_ready_claim_lock_serializes_competing_worker_without_generating_a_second_original(handoff):
    c=handoff;c.register();c.database.commit();identifier=c.rows()[0]['record_id']
    other=c.connections()
    with other.cursor() as cursor:cursor.execute('SELECT name FROM '+intent.TABLE+' WHERE name=%s FOR UPDATE NOWAIT',(identifier,))
    with pytest.raises(Exception):worker._claim(c.runtime,identifier)
    assert not c.built and not c.sent
    other.rollback()
    assert c.execute()['status']=='COMPLETE' and len(c.built)==1 and c.head()=='1'


@pytest.mark.parametrize('change',['actor','site','key','automatic_commit'])
def test_parent_binding_drift_blocks_before_commit_without_queue_or_native_allocation(handoff,change):
    c=handoff;c.register()
    if change=='actor':c.runtime.session.user='CHANGED'
    elif change=='site':c.runtime.local.site='other.invalid'
    elif change=='key':c.runtime.conf['encryption_key']='CHANGED'
    else:c.database.auto_commit_on_many_writes=1
    with pytest.raises(deferred.DeferredSubmissionError):c.database.commit()
    assert c.rows()[0]['state']=='STAGED' and not c.sent and not c.built
    c.runtime.enqueue.assert_not_called()


def test_finalization_failure_cannot_make_ready_record_discoverable(handoff):
    c=handoff;c.register();c.company.custom_phase_1_or_2='Phase-1'
    with pytest.raises(deferred.DeferredSubmissionError):c.database.commit()
    assert c.rows()[0]['state']=='STAGED'
    c.database.rollback();assert not c.rows()
    c.runtime.enqueue.assert_not_called();assert c.head()=='0'


def test_nontransactional_intent_table_is_rejected_before_staging(handoff):
    c=handoff
    with c.connection.cursor() as cursor:cursor.execute('ALTER TABLE '+intent.TABLE+' ENGINE=MyISAM')
    try:
        with pytest.raises(deferred.DeferredSubmissionError):c.register()
        assert not c.rows()
    finally:
        c.database.rollback()
        with c.connection.cursor() as cursor:cursor.execute('ALTER TABLE '+intent.TABLE+' ENGINE=InnoDB')
    c.runtime.enqueue.assert_not_called();assert not c.sent


def test_unrelated_parent_invoices_can_stage_concurrently_in_an_initially_empty_outbox(handoff):
    from zatca_erpgulf.zatca_erpgulf.tests.test_native_owned_pipeline_mariadb import OwnedDatabase,Runtime
    c=handoff;second_connection=c.connections();second_database=OwnedDatabase(second_connection)
    second_runtime=Runtime(c.runtime,second_database)
    first=intent.ParentIntent(c.runtime,'Sales Invoice','SYNTHETIC-FIRST-'+str(uuid4()))
    second=intent.ParentIntent(second_runtime,'POS Invoice','SYNTHETIC-SECOND-'+str(uuid4()))
    assert first.record_id!=second.record_id
    assert c.database.commits==1 and second_database.commits==0
    second_database.rollback();c.database.rollback()
    assert not c.sent and c.head()=='0'


@pytest.mark.parametrize('failure',['permission','rollout'])
def test_worker_review_does_not_leave_framework_error_log_writes_between_owned_transactions(handoff,failure):
    c=handoff;c.register();c.database.commit()
    with c.connection.cursor() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS `fixture_intent_error_log` (name VARCHAR(140) PRIMARY KEY,message LONGTEXT) ENGINE=InnoDB')
    c.original_commit()
    writes=[]
    def log_error(**kwargs):
        writes.append(kwargs)
        c.database.sql('INSERT INTO `fixture_intent_error_log` VALUES (%s,%s)',(str(uuid4()),kwargs['message']))
    c.runtime.log_error=log_error
    if failure=='permission':c.runtime.has_permission=lambda *args,**kwargs:False
    else:c.runtime.conf['zatca_native_dispatch']=0
    assert c.execute()['status']=='REVIEW'
    assert c.rows()[0]['result_code']=='native_operation_review' and c.database.transaction_writes==0
    assert not writes and not c.built and not c.sent and c.head()=='0'
