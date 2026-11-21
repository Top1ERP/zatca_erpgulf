"""Submitted native requests on owned private SQL and mocked transport only."""

import inspect
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from werkzeug.local import LocalProxy
from requests.exceptions import ReadTimeout

from zatca_erpgulf.zatca_erpgulf import collection_intent as collection
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf import native_provider,sign_invoice,pos_sign
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_draft_transaction_mariadb import batch


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def register(c,operation='manual',**kwargs):
    doc=c.runtime.get_doc(c.source.doctype,c.source.name)
    return collection.register_native_collection(doc,runtime=c.runtime,translate=str,intent=operation,**kwargs)


def execute(c,identifier,*,build=None,runtime=None):
    return worker.run_submission_intent(identifier,runtime=runtime or c.runtime,translate=str,build=build or (lambda doc:c.run()))


def row(c,identifier):
    return c.database.sql('SELECT * FROM `tabZATCA Submission Intent` WHERE name=%s',(identifier,),as_dict=True)[0]


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Background',True),
    (0,'linked','Batches',True),(0,'linked','Live',False)],indirect=True)
def test_submitted_request_commits_before_one_fixed_native_operation(handoff):
    c=handoff;before=c.database.commits;result=register(c);identifier=result['request_id']
    assert result['status']=='DEFERRED' and result['accepted'] is False
    assert row(c,identifier)['state']=='STAGED' and not c.sent and not c.built and c.head()=='0'
    assert c.database.commits==before;c.runtime.enqueue.assert_not_called()
    assert register(c)['request_id']==identifier
    c.database.commit();assert row(c,identifier)['state']=='READY'
    assert c.runtime.enqueue.call_args.kwargs['record_id']==identifier
    assert execute(c,identifier)['status']=='COMPLETE'
    assert row(c,identifier)['active_key'] is None and c.head()=='1' and len(c.built)==1
    assert len(c.sent)==(1 if c.customer.custom_b2c else 2)
    assert execute(c,identifier)['status']=='COMPLETE' and len(c.built)==1


def test_independent_call_coalesces_committed_ready_command_without_rewriting_its_header(handoff):
    c=handoff;first=register(c);c.database.commit();old=row(c,first['request_id'])
    second=register(c)
    assert second['reused'] and second['request_id']==first['request_id']
    assert row(c,first['request_id'])['intent_ciphertext']==old['intent_ciphertext']
    c.database.commit()
    assert execute(c,first['request_id'])['status']=='COMPLETE' and len(c.sent)==1


@pytest.mark.parametrize('case',[(0,'company','Batches',True),(1,'linked','Background',True)],indirect=True)
def test_prepared_original_expected_version_and_exact_bytes_are_retained(handoff):
    c=handoff;assert c.run()['status']=='PREPARED'
    old=native_provider.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    result=register(c);c.database.commit()
    header=json.loads(row(c,result['request_id'])['intent_header'])
    assert header['expected_issuance_id']==old.issuance_id
    assert execute(c,result['request_id'])['status']=='COMPLETE' and len(c.built)==1 and c.head()=='1'
    again=native_provider.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert again.original_xml==old.original_xml and again.invoice_uuid==old.invoice_uuid


def test_parent_rollback_cancels_retained_callback_and_removes_only_request(handoff):
    c=handoff;result=register(c);callback=c.database.after_commit._functions[0]
    c.database.rollback();callback()
    assert not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE name=%s',(result['request_id'],),as_dict=True)
    c.runtime.enqueue.assert_not_called();assert not c.sent and c.head()=='0'


def test_unknown_delivery_cannot_be_turned_into_another_ordinary_collection_request(handoff):
    c=handoff;result=register(c);c.database.commit();c.adapter.send.side_effect=ReadTimeout('PRIVATE TIMEOUT')
    assert execute(c,result['request_id'])['status']=='REVIEW'
    before=c.adapter.send.call_count
    assert register(c)['status']=='REVIEW'
    assert c.adapter.send.call_count==before==1 and c.head()=='1' and len(c.built)==1


def test_explicit_manual_action_after_pre_generation_failure_keeps_old_review_immutable(handoff):
    c=handoff;first=register(c);c.database.commit()
    def fail(doc):raise RuntimeError('PRIVATE BUILDER')
    assert execute(c,first['request_id'],build=fail)['status']=='REVIEW' and c.head()=='0'
    old=row(c,first['request_id'])
    second=register(c);assert second['request_id']!=first['request_id']
    c.database.commit();assert execute(c,second['request_id'])['status']=='COMPLETE'
    retained=row(c,first['request_id'])
    assert retained['state']=='REVIEW' and retained['intent_ciphertext']==old['intent_ciphertext'] and retained['active_key'] is None
    assert c.head()=='1' and len(c.sent)==1


def test_before_commit_source_change_is_fatal_and_never_queues(handoff):
    c=handoff;result=register(c)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    with pytest.raises(collection.CollectionSubmissionError) as caught:c.database.commit()
    assert caught.value.fatal and caught.value.code=='collection_source_changed_before_commit'
    assert row(c,result['request_id'])['state']=='STAGED';c.runtime.enqueue.assert_not_called()
    assert not c.sent and c.head()=='0'


@pytest.mark.parametrize('case',[(0,'company','Background',True),(1,'device','Background',True)],indirect=True)
def test_actual_manual_mixed_draft_and_submitted_collection_stages_both_without_owned_worker_entry(batch,monkeypatch):
    c=batch;dt=c.source.doctype;first,second,_=c.names
    c.database.sql('UPDATE '+c.table+' SET docstatus=1 WHERE name=%s',(second,));c.original_commit()
    c.company.custom_submit_or_not=1;original=c.runtime.get_doc
    def get_doc(kind,name,**kwargs):
        doc=original(kind,name,**kwargs)
        if kind==dt:doc.submit=c.make(name).submit
        return doc
    monkeypatch.setattr(c.runtime,'get_doc',get_doc)
    module=sign_invoice if dt=='Sales Invoice' else pos_sign
    monkeypatch.setattr(module,'get_alias_value',lambda group,doc,default:doc.get('custom_b2c',default))
    function=module.resubmit_invoices if dt=='Sales Invoice' else module.resubmit_invoices_pos
    results=inspect.unwrap(function)([first,second])
    assert results[second]['status']=='DEFERRED' and not results[second]['accepted']
    assert {item['source_name'] for item in c.intents()}=={first,second}
    assert all(item['state']=='STAGED' for item in c.intents()) and not c.sent and c.head()=='0'
    c.database.commit();assert c.runtime.enqueue.call_count==2 and all(item['state']=='READY' for item in c.intents())


class ProxyRuntime:
    def __init__(self,original):
        self.original=original;self.db=LocalProxy(lambda:original.local.db)
    def __getattr__(self,name):return getattr(self.original,name)


def test_real_localproxy_parent_binding_accepts_submit_and_collection_requests(handoff):
    from zatca_erpgulf.zatca_erpgulf.submission_intent import ParentIntent
    c=handoff;proxy=ProxyRuntime(c.runtime)
    first=ParentIntent(proxy,c.source.doctype,c.source.name)
    assert first.database is c.database and proxy.db is not c.database
    first.finalize(translate=str);c.original_commit()
    doc=proxy.get_doc(c.source.doctype,c.source.name)
    result=collection.register_native_collection(doc,runtime=proxy,translate=str,intent='manual')
    c.database.commit()
    assert execute(c,result['request_id'],runtime=proxy)['status']=='COMPLETE'
    assert c.head()=='1' and len(c.sent)==1


@pytest.mark.parametrize('case',[(0,'company','Background',True),(1,'device','Background',True)],indirect=True)
def test_native_prepared_discovery_ignores_age_and_stages_only_one_active_schedule(handoff,monkeypatch):
    from zatca_erpgulf.zatca_erpgulf import prepared_collection
    from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
    c=handoff;assert c.run()['status']=='PREPARED'
    original=c.runtime.get_doc
    known={c.company.name,c.b.linked.name}
    def get_doc(dt,name,**kwargs):
        if dt=='Company' and type(name) is str and name not in known:
            rows=c.database.sql('SELECT * FROM `tabCompany` WHERE name=%s',(name,),as_dict=True)
            return Document(doctype='Company',custom_zatca_invoice_enabled=0,custom_phase_1_or_2='Phase-1',**rows[0])
        return original(dt,name,**kwargs)
    monkeypatch.setattr(c.runtime,'get_doc',get_doc)
    c.database.sql('UPDATE `tabZATCA Issuance` SET creation=%s WHERE source_name=%s',('2024-01-01',c.source.name))
    c.original_commit();before=c.database.commits
    assert prepared_collection.discover_prepared_collections(runtime=c.runtime)==1
    assert c.database.commits==before+1 and not c.sent and c.head()=='1'
    identifier=c.runtime.enqueue.call_args.kwargs['record_id']
    assert row(c,identifier)['operation']=='scheduled' and row(c,identifier)['state']=='READY'
    assert prepared_collection.discover_prepared_collections(runtime=c.runtime)==0
    assert execute(c,identifier)['status']=='COMPLETE' and len(c.sent)==1 and len(c.built)==1


def test_collection_queue_failure_after_commit_remains_ready_for_existing_recovery(handoff):
    c=handoff;result=register(c);c.runtime.enqueue.side_effect=RuntimeError('PRIVATE REDIS')
    with pytest.raises(collection.CollectionSubmissionError) as caught:c.database.commit()
    assert str(caught.value)==collection.QUEUE_REVIEW and caught.value.__context__ is None
    assert row(c,result['request_id'])['state']=='READY'
    c.runtime.enqueue.side_effect=None
    assert worker.rediscover_ready_intents(runtime=c.runtime)>=1
    assert execute(c,result['request_id'])['status']=='COMPLETE' and len(c.sent)==1


def test_scheduled_request_waits_without_rearming_a_review_and_manual_action_remains_explicit(handoff,monkeypatch):
    from datetime import datetime
    from zatca_erpgulf.zatca_erpgulf import native_delivery
    c=handoff;c.company.custom_send_invoice_to_zatca='Background'
    c.database.sql('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Background',c.company.name));c.original_commit()
    result=register(c,'scheduled');c.database.commit()
    monkeypatch.setattr(native_delivery,'now_datetime',lambda:datetime(2026,11,20,13))
    assert execute(c,result['request_id'])['status']=='WAITING' and c.head()=='0'
    assert register(c,'scheduled')['request_id']==result['request_id'];c.database.commit()
    monkeypatch.setattr(native_delivery,'now_datetime',lambda:datetime(2026,11,21,10))
    assert execute(c,result['request_id'])['status']=='COMPLETE' and len(c.sent)==1


def test_localproxy_native_draft_savepoint_and_queue_actor_restore(handoff):
    from zatca_erpgulf.zatca_erpgulf import draft_submission,deferred_submission
    c=handoff;proxy=ProxyRuntime(c.runtime);dt=c.source.doctype;name=c.source.name
    c.database.sql('UPDATE `tab'+dt+'` SET docstatus=0 WHERE name=%s',(name,));c.original_commit()
    doc=proxy.get_doc(dt,name)
    def submit():
        c.database.sql('UPDATE `tab'+dt+'` SET docstatus=1 WHERE name=%s',(name,));doc.docstatus=1
        with deferred_submission.invoice_submit_hook(dt,doc,runtime=proxy,translate=str):
            assert deferred_submission.maybe_defer_invoice_submission(dt,name,runtime=proxy,translate=str)
    doc.submit=submit
    draft_submission.submit_draft(doc,runtime=proxy,translate=str,operation='manual')
    assert c.rows()[0]['state']=='STAGED'
    c.database.commit();assert c.rows()[0]['state']=='READY'
    actor=proxy.session.user
    with worker._queue_as_actor(proxy,'Administrator'):assert proxy.session.user=='Administrator'
    assert proxy.session.user==actor
    assert execute(c,c.rows()[0]['record_id'],runtime=proxy)['status']=='COMPLETE'


@pytest.mark.parametrize('field,value',[('active_key','0'*64),('operation','submit'),('expected_issuance_id','30000000-0000-4000-8000-000000000009')])
def test_collection_index_tamper_cannot_select_another_operation_or_version(handoff,field,value):
    from zatca_erpgulf.zatca_erpgulf.submission_intent import SubmissionIntentError
    c=handoff;result=register(c);c.database.commit()
    c.change('UPDATE `tabZATCA Submission Intent` SET `'+field+'`=%s WHERE name=%s',(value,result['request_id']))
    with pytest.raises(SubmissionIntentError):execute(c,result['request_id'])
    assert c.head()=='0' and not c.sent and not c.built


def test_old_rr_snapshot_cannot_hide_existing_active_slot(handoff):
    from zatca_erpgulf.zatca_erpgulf.tests.test_native_owned_pipeline_mariadb import OwnedDatabase,Runtime
    from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import Callbacks
    from zatca_erpgulf.zatca_erpgulf.worker_transaction import CALLBACKS
    c=handoff;other_db=OwnedDatabase(c.connections());other=Runtime(c.runtime,other_db)
    other.flags={}
    for name in CALLBACKS:setattr(other_db,name,Callbacks())
    other_db.sql('SELECT COUNT(*) AS n FROM `tabZATCA Submission Intent`',as_dict=True)
    first=register(c);c.database.commit()
    original_loader=c.runtime.get_doc
    def other_loader(dt,name,**kwargs):
        prototype=original_loader(dt,name)
        suffix=' FOR UPDATE NOWAIT' if kwargs.get('for_update') else ''
        values=other_db.sql('SELECT * FROM `tab'+dt+'` WHERE name=%s'+suffix,(name,),as_dict=True)[0]
        return type(prototype)(**(vars(prototype)|dict(values)))
    other.get_doc=other_loader
    original_doc=c.runtime.get_doc(c.source.doctype,c.source.name)
    # Every current lock/read now uses the second physical connection, whose
    # older consistent view intentionally predates the committed active slot.
    second=collection.register_native_collection(original_doc,runtime=other,translate=str,intent='manual')
    assert second['reused'] and second['request_id']==first['request_id']
    other_db.rollback()
    assert row(c,first['request_id'])['state']=='READY' and c.head()=='0'
