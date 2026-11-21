"""Origin-backed first-send recovery on private SQL, with mocked transport."""

import json
import os
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_provider,native_dispatch,prepared_collection
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


@pytest.fixture
def origins(handoff,monkeypatch):
    c=handoff;original=c.runtime.get_doc;known={c.company.name,c.b.linked.name}
    def get_doc(dt,name,**kwargs):
        if dt=='Company' and type(name) is str and name not in known:
            row=c.database.sql('SELECT * FROM `tabCompany` WHERE name=%s',(name,),as_dict=True)[0]
            return Document(doctype=dt,custom_zatca_invoice_enabled=0,custom_phase_1_or_2='Phase-1',**row)
        return original(dt,name,**kwargs)
    monkeypatch.setattr(c.runtime,'get_doc',get_doc)
    c.actor=c.runtime.session.user
    def prepare_dispatch(dt,name,**kwargs):
        native_dispatch.prepare_saved_invoice(dt,name,**kwargs)
        raise RuntimeError('SIMULATED PROCESS STOP AFTER GENERATION')
    def generate(*,request=True,operation='submit'):
        if request:
            if operation=='submit':
                c.register();identifier=c.rows()[0]['record_id']
            else:
                from zatca_erpgulf.zatca_erpgulf.collection_intent import register_native_collection
                identifier=register_native_collection(c.source,runtime=c.runtime,translate=str,intent=operation)['request_id']
            c.database.commit()
            header,fence,_=worker._claim(c.runtime,identifier)
        with monkeypatch.context() as patch:
            patch.setattr(native_provider,'dispatch_saved_invoice',prepare_dispatch)
            try:
                if request:worker._process(c.runtime,str,header,lambda doc:c.run(),fence)
                else:c.run()
            except Exception:pass
        assert c.head()=='1' and len(c.built)==1 and not c.sent
        return native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_origin=True)
    c.generate=generate
    def administrator():
        c.database.sql('INSERT INTO `tabUser` (name,enabled) VALUES (%s,1) ON DUPLICATE KEY UPDATE enabled=1',('Administrator',))
        c.database.commit();c.runtime.set_user('Administrator')
    c.administrator=administrator
    def recover():return prepared_collection.discover_prepared_collections(runtime=c.runtime)
    c.recover=recover
    return c


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),
    (0,'linked','Batches',False),(1,'linked','Background',False)],indirect=True)
@pytest.mark.parametrize('with_request',[False,True])
def test_immediate_original_recovers_under_its_original_actor_without_generation(origins,with_request):
    c=origins;view=c.generate(request=with_request);origin=view.generation_origin
    assert origin['action']=='DISPATCH' and origin['actor']==c.actor
    c.administrator();old_user=c.runtime.session.user;before=len(c.built)
    c.runtime.enqueue.reset_mock()
    queued=[]
    c.runtime.enqueue.side_effect=lambda *args,**kwargs:queued.append((c.runtime.session.user,kwargs['record_id']))
    assert c.recover()==1 and c.runtime.session.user==old_user
    actor,identifier=queued[0];assert actor==c.actor and actor!='Administrator'
    row=c.database.sql('SELECT * FROM `tabZATCA Submission Intent` WHERE name=%s',(identifier,),as_dict=True)[0]
    header=json.loads(row['intent_header'])
    assert header['intent']=='recovery' and header['expected_issuance_id']==view.issuance_id and header['actor']==c.actor
    assert c.recover()==0 and not c.sent
    c.runtime.set_user(c.actor)
    build=Mock(side_effect=AssertionError('Recovery must reuse the saved original'))
    assert worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build)['status']=='COMPLETE'
    build.assert_not_called();assert len(c.built)==before and c.head()=='1'
    assert len(c.sent)==(1 if c.customer.custom_b2c else 2)
    again=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert again.original_xml==view.original_xml and again.invoice_uuid==view.invoice_uuid


@pytest.mark.parametrize('case',[(0,'company','Batches',True),(1,'device','Background',True)],indirect=True)
def test_deferred_batches_stays_manual_and_background_uses_its_existing_schedule(origins):
    c=origins;view=c.generate();assert view.generation_origin['action']=='PREPARE'
    c.administrator();c.runtime.enqueue.reset_mock()
    count=c.recover()
    if c.company.custom_send_invoice_to_zatca=='Batches':
        assert count==0;c.runtime.enqueue.assert_not_called()
    else:
        assert count==1
        identifier=c.runtime.enqueue.call_args.kwargs['record_id']
        row=c.database.sql('SELECT actor,operation FROM `tabZATCA Submission Intent` WHERE name=%s',(identifier,),as_dict=True)[0]
        assert row=={'actor':'Administrator','operation':'scheduled'}
    assert not c.sent and c.head()=='1'


@pytest.mark.parametrize('fault',['disabled_actor','lost_write','changed_policy','missing_origin'])
def test_absent_authority_never_upgrades_the_actor_or_makes_a_new_dispatch(origins,monkeypatch,fault):
    c=origins;view=c.generate()
    if fault=='disabled_actor':
        c.database.sql('UPDATE `tabUser` SET enabled=0 WHERE name=%s',(c.actor,));c.database.commit()
    elif fault=='lost_write':
        original=c.runtime.has_permission
        def permitted(dt,op,*,doc,user,raise_exception=True):
            return False if user==c.actor and op=='write' else original(dt,op,doc=doc,user=user,raise_exception=raise_exception)
        monkeypatch.setattr(c.runtime,'has_permission',permitted)
    elif fault=='changed_policy':
        c.company.custom_send_invoice_to_zatca='Batches'
        c.database.sql('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Batches',c.company.name));c.database.commit()
    else:
        c.database.sql('UPDATE `tabZATCA Issuance` SET origin_actor=NULL,origin_action=NULL,origin_method=NULL,origin_ciphertext=NULL WHERE name=%s',(view.issuance_id,));c.database.commit()
    c.administrator();c.runtime.enqueue.reset_mock()
    assert c.recover()==0;c.runtime.enqueue.assert_not_called()
    assert not c.sent and c.head()=='1'


@pytest.mark.parametrize('column',['origin_actor','origin_action','origin_method','origin_ciphertext'])
def test_origin_tampering_cannot_authorize_recovery(origins,column):
    c=origins;view=c.generate()
    value='BROKEN'
    c.database.sql('UPDATE `tabZATCA Issuance` SET '+column+'=%s WHERE name=%s',(value,view.issuance_id));c.database.commit()
    with pytest.raises(Exception):
        native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_origin=True)
    assert not c.sent and c.head()=='1'


def test_trusted_internal_preparation_without_delivery_context_gets_no_origin(origins):
    c=origins
    value=native_dispatch.prepare_saved_invoice(c.source.doctype,c.source.name,runtime=c.runtime,translate=str,build=lambda doc:c.run())
    view=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_origin=True)
    assert value.record_id==view.issuance_id and view.generation_origin is None
    c.administrator();assert c.recover()==0 and not c.sent


@pytest.mark.parametrize('case',[(0,'company','Batches',True)],indirect=True)
def test_original_manual_authorization_resumes_batches_without_becoming_scheduler_authorization(origins):
    c=origins;view=c.generate(operation='manual');assert view.generation_origin['intent']=='manual'
    c.administrator();c.runtime.enqueue.reset_mock();assert c.recover()==1
    identifier=c.runtime.enqueue.call_args.kwargs['record_id'];c.runtime.set_user(c.actor)
    result=worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=Mock(side_effect=AssertionError('No builder')))
    assert result['status']=='COMPLETE' and len(c.sent)==1 and c.head()=='1'


@pytest.mark.parametrize('case',[(0,'company','Background',True)],indirect=True)
def test_scheduled_origin_recovery_waits_for_its_current_window_without_rearming_review(origins,monkeypatch):
    from datetime import datetime
    from zatca_erpgulf.zatca_erpgulf import native_delivery
    c=origins;c.generate(operation='scheduled');c.administrator();c.runtime.enqueue.reset_mock()
    assert c.recover()==1
    identifier=c.runtime.enqueue.call_args.kwargs['record_id'];c.runtime.set_user(c.actor)
    build=Mock(side_effect=AssertionError('No builder'))
    monkeypatch.setattr(native_delivery,'now_datetime',lambda:datetime(2026,11,21,23))
    assert worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build)['status']=='WAITING'
    assert not c.sent and c.head()=='1'
    monkeypatch.setattr(native_delivery,'now_datetime',lambda:datetime(2026,11,22,10))
    assert worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build)['status']=='COMPLETE'
    assert len(c.sent)==1 and c.head()=='1';build.assert_not_called()


def test_revoked_original_request_fence_cannot_be_used_as_automatic_authorization(origins):
    from uuid import uuid4
    c=origins;view=c.generate();request_id=view.generation_origin['request_id']
    c.database.sql('UPDATE `tabZATCA Submission Intent` SET fence_token=%s WHERE name=%s',(str(uuid4()),request_id));c.database.commit()
    c.administrator();c.runtime.enqueue.reset_mock()
    with pytest.raises(Exception):c.recover()
    c.runtime.enqueue.assert_not_called();assert not c.sent and c.head()=='1'


def test_recovery_queue_loss_keeps_ready_command_and_restores_scheduler_actor(origins):
    c=origins;c.generate();c.administrator();c.runtime.enqueue.reset_mock()
    c.runtime.enqueue.side_effect=RuntimeError('PRIVATE REDIS FAILURE')
    with pytest.raises(Exception):c.recover()
    assert c.runtime.session.user=='Administrator'
    rows=c.database.sql('SELECT record_id,state,actor FROM `tabZATCA Submission Intent` WHERE operation=%s AND source_name=%s',
        ('recovery',c.source.name),as_dict=True)
    assert len(rows)==1 and rows[0]['state']=='READY' and rows[0]['actor']==c.actor
    c.runtime.enqueue.side_effect=None
    assert worker.rediscover_ready_intents(runtime=c.runtime)>=1
    assert c.runtime.session.user=='Administrator' and not c.sent
