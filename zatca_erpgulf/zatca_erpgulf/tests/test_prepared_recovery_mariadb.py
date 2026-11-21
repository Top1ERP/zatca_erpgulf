"""Explicit saved-original recovery on fixture-owned SQL and mocked HTTP only."""

import hashlib
import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import native_dispatch,native_delivery
from zatca_erpgulf.zatca_erpgulf import prepared_recovery as recovery
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def prepare(c):
    result=native_dispatch.prepare_saved_invoice(c.source.doctype,c.source.name,runtime=c.runtime,
        translate=str,build=lambda doc:c.run())
    return result.record_id


def register(c,identifier):
    return recovery.register_prepared_original(identifier,runtime=c.runtime,translate=str)


def command(c,identifier):
    return c.database.sql('SELECT * FROM `tabZATCA Submission Intent` WHERE name=%s',(identifier,),as_dict=True)[0]


def execute(c,identifier):
    build=Mock(side_effect=AssertionError('A saved original must never call a builder'))
    result=worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build)
    build.assert_not_called()
    return result


@pytest.mark.parametrize('case',[(route,kind,method,simplified)
    for route in (0,1) for kind in ('company','device','linked')
    for method in ('Live','Background','Batches') for simplified in (False,True)],indirect=True)
def test_manual_first_send_uses_exact_prepared_bytes_and_existing_after_commit_worker(handoff):
    c=handoff;identifier=prepare(c)
    saved=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_current_source=True)
    artifact=c.database.sql('SELECT artifact_sha256,artifact_ciphertext FROM `tabZATCA Issuance` WHERE name=%s',(identifier,),as_dict=True)[0]
    commits=c.database.commits;assert c.head()=='1' and len(c.built)==1 and not c.sent
    result=register(c,identifier);request_id=result['request_id']
    assert result['status']=='DEFERRED' and result['accepted'] is False and result['issuance_id']==identifier
    assert c.database.commits==commits and command(c,request_id)['state']=='STAGED'
    c.runtime.enqueue.assert_not_called();assert not c.sent and len(c.built)==1
    c.database.commit()
    assert command(c,request_id)['state']=='READY'
    header=json.loads(command(c,request_id)['intent_header'])
    assert header['expected_issuance_id']==identifier and header['intent']=='manual'
    assert c.runtime.enqueue.call_args.kwargs['record_id']==request_id
    assert execute(c,request_id)['status']=='COMPLETE'
    assert len(c.sent)==(1 if c.customer.custom_b2c else 2)
    assert all(hashlib.sha256(body).hexdigest()==artifact['artifact_sha256'] for body in c.sent)
    again=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    assert again.original_xml==saved.original_xml and again.invoice_uuid==saved.invoice_uuid and again.icv==saved.icv
    assert c.head()=='1' and len(c.built)==1 and again.accepted
    c.b.request.assert_not_called()


def test_parent_rollback_removes_only_staged_command_and_never_sends(handoff):
    c=handoff;identifier=prepare(c);result=register(c,identifier)
    callback=c.database.after_commit._functions[0]
    c.database.rollback();callback()
    assert not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE name=%s',(result['request_id'],),as_dict=True)
    assert c.head()=='1' and len(c.built)==1 and not c.sent
    c.runtime.enqueue.assert_not_called()


def test_repeated_explicit_requests_coalesce_without_rewriting_the_command(handoff):
    c=handoff;identifier=prepare(c)
    first=register(c,identifier);c.database.commit();old=command(c,first['request_id'])
    second=register(c,identifier)
    assert second['request_id']==first['request_id'] and second['reused']
    assert command(c,first['request_id'])['intent_ciphertext']==old['intent_ciphertext']
    c.database.commit();assert execute(c,first['request_id'])['status']=='COMPLETE'
    assert len(c.sent)==1 and c.head()=='1' and len(c.built)==1


def test_missing_custody_never_creates_a_new_original_or_command(handoff):
    c=handoff
    with pytest.raises(recovery.PreparedRecoveryError):register(c,str(uuid4()))
    assert c.head()=='0' and not c.sent and not c.built


@pytest.mark.parametrize('case',[(0,'company','Background',True)],indirect=True)
def test_explicit_manual_choice_does_not_wait_for_the_background_window(handoff,monkeypatch):
    from datetime import datetime
    c=handoff;identifier=prepare(c)
    monkeypatch.setattr(native_delivery,'now_datetime',lambda:datetime(2026,11,19,23))
    result=register(c,identifier);c.database.commit()
    assert execute(c,result['request_id'])['status']=='COMPLETE' and len(c.sent)==1 and c.head()=='1'


@pytest.mark.parametrize('state',['DISPATCHING','OUTCOME_UNKNOWN','REJECTED','REVIEW_REQUIRED','REPORTING_FALLBACK_READY'])
def test_issued_attempt_or_unknown_and_rejected_states_never_enter_this_first_send_action(handoff,state):
    c=handoff;identifier=prepare(c)
    c.database.sql('UPDATE `tabZATCA Issuance` SET state=%s WHERE name=%s',(state,identifier));c.database.commit()
    with pytest.raises(recovery.PreparedRecoveryError):register(c,identifier)
    assert not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE source_name=%s',(c.source.name,),as_dict=True)
    assert c.head()=='1' and not c.sent and len(c.built)==1


def test_an_accepted_original_requires_no_new_recovery_request(handoff):
    c=handoff;identifier=prepare(c);assert c.run()['accepted'];before=len(c.sent)
    with pytest.raises(recovery.PreparedRecoveryError):register(c,identifier)
    assert len(c.sent)==before==1 and c.head()=='1'


def test_a_reserved_original_with_an_attempt_is_not_an_untouched_prepared_original(handoff):
    c=handoff;identifier=prepare(c)
    invocation=native_dispatch.reserve_saved_issuance(c.source.doctype,c.source.name,runtime=c.runtime,translate=str)
    native_dispatch.retain_dispatch_observation(invocation,None,runtime=c.runtime)
    with pytest.raises(recovery.PreparedRecoveryError):register(c,identifier)
    assert not c.sent and c.head()=='1'


@pytest.mark.parametrize('fault',['rollout','role','read','write','company','fiscal','marker','original'])
def test_policy_acl_and_integrity_failures_do_not_generate_or_register(handoff,monkeypatch,fault):
    c=handoff;identifier=prepare(c)
    if fault=='rollout':c.runtime.conf['zatca_native_dispatch']=0
    elif fault=='role':monkeypatch.setattr(c.runtime,'get_roles',lambda actor:[])
    elif fault in ('read','write','company'):
        previous=c.runtime.has_permission
        def permitted(dt,operation,**kwargs):
            if (fault=='company' and dt=='Company') or (fault in ('read','write') and dt==c.source.doctype and operation==fault):return False
            return previous(dt,operation,**kwargs)
        monkeypatch.setattr(c.runtime,'has_permission',permitted)
    elif fault=='original':
        c.database.sql('UPDATE `tabZATCA Issuance` SET artifact_ciphertext=%s WHERE name=%s',('BROKEN',identifier));c.database.commit()
    else:
        field,value=('grand_total',114) if fault=='fiscal' else ('custom_zatca_issuing_unit',None)
        c.database.sql('UPDATE `tab'+c.source.doctype+'` SET '+field+'=%s WHERE name=%s',(value,c.source.name));c.database.commit()
    with pytest.raises(Exception):register(c,identifier)
    assert not c.database.sql('SELECT name FROM `tabZATCA Submission Intent` WHERE source_name=%s',(c.source.name,),as_dict=True)
    assert c.head()=='1' and not c.sent and len(c.built)==1


def test_disabled_company_phase_is_not_overridden_by_operator_recovery(handoff):
    c=handoff;identifier=prepare(c);c.company.custom_phase_1_or_2='Phase-1'
    with pytest.raises(recovery.PreparedRecoveryError):register(c,identifier)
    assert not c.sent and c.head()=='1'


def test_foreign_parent_writes_are_not_committed_or_rolled_back(handoff):
    c=handoff;identifier=prepare(c)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    commits=c.database.commits
    with pytest.raises(WorkerTransactionError,match='parent_state'):register(c,identifier)
    assert c.database.commits==commits
    assert c.database.sql('SELECT grand_total FROM `tab'+c.source.doctype+'` WHERE name=%s',(c.source.name,),as_dict=True)[0]['grand_total']==114
    assert not c.sent


def test_another_workers_acceptance_between_preflight_and_registration_does_not_cause_a_second_send(handoff,monkeypatch):
    c=handoff;identifier=prepare(c);original=recovery._inspect_original
    def accepted_in_between(record_id,*,runtime):
        identity=original(record_id,runtime=runtime)
        assert c.run()['accepted']
        return identity
    monkeypatch.setattr(recovery,'_inspect_original',accepted_in_between)
    result=register(c,identifier);c.database.commit()
    assert execute(c,result['request_id'])['status']=='COMPLETE'
    assert len(c.sent)==1 and len(c.built)==1 and c.head()=='1'
