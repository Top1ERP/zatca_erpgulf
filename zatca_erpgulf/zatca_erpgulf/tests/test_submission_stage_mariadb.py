"""Stopped initial handoff retirement on fixture-owned Unix SQL; no real HTTP."""

import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import collection_intent,submission_intent as intent
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf import submission_intent_retirement as retirement
from zatca_erpgulf.zatca_erpgulf import native_invoice_lifecycle as lifecycle_guard
from zatca_erpgulf.zatca_erpgulf import deferred_submission as deferred
from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction,WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_invoice_lifecycle_mariadb import (
    lifecycle,handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def saved(c,identifier):
    return c.database.sql('SELECT * FROM '+intent.TABLE+' WHERE name=%s',(identifier,),as_dict=True)[0]


def interrupted_stage(c,*,collection=False,expected_issuance_id=None):
    if collection:
        result=collection_intent.register_native_collection(c.source,runtime=c.runtime,translate=str,
            intent='manual',expected_issuance_id=expected_issuance_id)
        identifier=result['request_id']
        # Mimic a caller incorrectly catching its failed before-commit callback.
        c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
        with pytest.raises(collection_intent.CollectionSubmissionError):c.database.commit()
    else:
        with deferred.invoice_submit_hook(c.source.doctype,c.source,runtime=c.runtime,translate=str):
            deferred.maybe_defer_invoice_submission(c.source.doctype,c.source.name,runtime=c.runtime,translate=str)
            with pytest.raises(deferred.DeferredSubmissionError):c.database.commit()
        identifier=c.rows()[0]['record_id']
    if collection:
        with pytest.raises(collection_intent.CollectionSubmissionError) as caught:c.database.commit()
        assert caught.value.template==collection_intent.QUEUE_REVIEW
    else:c.database.commit()
    assert saved(c,identifier)['state']=='STAGED'
    c.runtime.enqueue.assert_not_called()
    return identifier


def retire(c,identifier):
    return retirement.retire_unissued_intent(identifier,'STAGED',None,runtime=c.runtime)


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Background',True),
    (0,'linked','Live',False)],indirect=True)
@pytest.mark.parametrize('collection',[False,True])
def test_authenticated_stopped_stage_can_be_retired_without_finalizing_or_generating(lifecycle,collection):
    c=lifecycle;identifier=interrupted_stage(c,collection=collection);before=saved(c,identifier)
    with owned_worker_transaction(c.runtime) as owner:
        with pytest.raises(intent.SubmissionIntentError,match='unfinalized'):intent.open_intent(owner,identifier)
        row,header=intent.open_intent(owner,identifier,allow_staged=True)
        assert row['state']=='STAGED' and header['actor']==c.runtime.session.user
    assert worker.rediscover_ready_intents(runtime=c.runtime)==0
    result=retire(c,identifier);after=saved(c,identifier)
    assert result['status']=='RETIRED' and not result['accepted']
    assert after['intent_header']==before['intent_header'] and after['intent_ciphertext']==before['intent_ciphertext']
    assert after['active_key'] is None and json.loads(after['resolution_header'])['prior_state']=='STAGED'
    assert retire(c,identifier)['reused']
    for method in ('before_cancel','on_trash','before_rename'):
        lifecycle_guard.inspect_source_lifecycle(c.source,runtime=c.runtime,method=method)
    build=Mock()
    assert worker.run_submission_intent(identifier,runtime=c.runtime,translate=str,build=build)['status']=='RETIRED'
    build.assert_not_called();assert c.head()=='0' and not c.sent and not c.built


@pytest.mark.parametrize('fault',['old_unsealed','cipher','source','actor','clock','fence','role','permission'])
@pytest.mark.parametrize('collection',[False,True])
def test_missing_corrupt_or_unauthorized_stage_never_releases_the_source(lifecycle,monkeypatch,fault,collection):
    c=lifecycle;identifier=interrupted_stage(c,collection=collection)
    if fault=='old_unsealed':statement='intent_header=NULL,intent_ciphertext=NULL';values=()
    elif fault=='cipher':statement='intent_ciphertext=%s';values=('BROKEN',)
    elif fault=='source':statement='source_name=%s';values=('OTHER-SOURCE',)
    elif fault=='actor':statement='actor=%s';values=('Administrator',)
    elif fault=='clock':
        header=json.loads(saved(c,identifier)['intent_header']);header['created_at_utc']='2026-11-21T10:00:00.000000'
        statement='intent_header=%s';values=(json.dumps(header),)
    elif fault=='fence':statement='fence_token=%s';values=(str(uuid4()),)
    else:statement=None
    if statement:
        c.database.sql('UPDATE '+intent.TABLE+' SET '+statement+' WHERE name=%s',(*values,identifier));c.database.commit()
    if fault=='role':monkeypatch.setattr(c.runtime,'get_roles',lambda user:[])
    if fault=='permission':
        original=c.runtime.has_permission
        monkeypatch.setattr(c.runtime,'has_permission',lambda dt,op,**kwargs:False if op=='write' else original(dt,op,**kwargs))
    with pytest.raises(Exception):retire(c,identifier)
    row=saved(c,identifier)
    assert row['state']=='STAGED' and row['resolution_ciphertext'] is None
    assert c.head()=='0' and not c.sent and not c.built


@pytest.mark.parametrize('collection',[False,True])
def test_a_saved_original_blocks_stage_retirement_even_after_output_erasure(lifecycle,collection):
    c=lifecycle;identifier=interrupted_stage(c,collection=collection)
    c.company.custom_send_invoice_to_zatca='Batches'
    c.database.sql('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Batches',c.company.name))
    c.database.commit();assert c.run()['status']=='PREPARED'
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_zatca_issuing_unit=NULL,custom_uuid=NULL WHERE name=%s',(c.source.name,))
    c.database.commit()
    with pytest.raises(retirement.IntentRetirementError) as caught:retire(c,identifier)
    assert caught.value.code=='intent_retirement_issued'
    assert saved(c,identifier)['state']=='STAGED' and c.head()=='1' and not c.sent


@pytest.mark.parametrize('collection',[False,True])
def test_finalization_authenticates_initial_ciphertext_instead_of_overwriting_damage(lifecycle,collection):
    c=lifecycle
    if collection:
        result=collection_intent.register_native_collection(c.source,runtime=c.runtime,translate=str,intent='manual')
        identifier=result['request_id']
    else:c.register();identifier=c.rows()[0]['record_id']
    c.database.sql('UPDATE '+intent.TABLE+' SET intent_ciphertext=%s WHERE name=%s',('BROKEN',identifier))
    with pytest.raises(Exception):c.database.commit()
    assert saved(c,identifier)['state']=='STAGED'
    c.runtime.enqueue.assert_not_called();assert c.head()=='0' and not c.sent


@pytest.mark.parametrize('case',[(0,'company','Batches',True)],indirect=True)
def test_staged_collection_that_observed_original_cannot_retire_missing_custody(lifecycle):
    c=lifecycle;assert c.run()['status']=='PREPARED'
    identifier=interrupted_stage(c,collection=True)
    c.database.sql('DELETE FROM `tabZATCA Issuance` WHERE source_name=%s',(c.source.name,))
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_zatca_issuing_unit=NULL,custom_uuid=NULL WHERE name=%s',(c.source.name,))
    c.database.commit()
    with pytest.raises(retirement.IntentRetirementError) as caught:retire(c,identifier)
    assert caught.value.code=='intent_retirement_original_expected' and saved(c,identifier)['state']=='STAGED'


def test_parent_writes_are_neither_committed_nor_rolled_back_by_stage_retirement(lifecycle):
    c=lifecycle;identifier=interrupted_stage(c)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET grand_total=114 WHERE name=%s',(c.source.name,))
    commits=c.database.commits
    with pytest.raises(WorkerTransactionError,match='parent_state'):retire(c,identifier)
    assert c.database.commits==commits and saved(c,identifier)['state']=='STAGED'


def test_unknown_commit_ack_preserves_stage_retirement_proof(lifecycle,monkeypatch):
    c=lifecycle;identifier=interrupted_stage(c);original=c.database.commit
    def lost_ack():original();raise RuntimeError('PRIVATE ACK LOST')
    monkeypatch.setattr(c.database,'commit',lost_ack)
    with pytest.raises(WorkerTransactionError) as caught:retire(c,identifier)
    assert caught.value.commit_uncertain
    monkeypatch.setattr(c.database,'commit',original)
    assert retire(c,identifier)['reused'] and saved(c,identifier)['state']=='RETIRED' and c.head()=='0'


@pytest.mark.parametrize('collection',[False,True])
def test_resumed_old_finalizer_cannot_promote_a_retired_stage(lifecycle,collection):
    c=lifecycle
    request=(collection_intent.CollectionIntent(c.runtime,c.source.doctype,c.source.name,intent='manual')
        if collection else intent.ParentIntent(c.runtime,c.source.doctype,c.source.name))
    c.original_commit();retire(c,request.record_id)
    with pytest.raises(intent.SubmissionIntentError):request.finalize(translate=str)
    assert saved(c,request.record_id)['state']=='RETIRED' and c.head()=='0' and not c.sent and not c.built


def test_legacy_unsealed_stage_is_not_silently_authenticated_during_retirement(lifecycle):
    c=lifecycle;identifier=interrupted_stage(c)
    c.database.sql('UPDATE '+intent.TABLE+' SET intent_header=NULL,intent_ciphertext=NULL WHERE name=%s',(identifier,))
    c.database.commit()
    with pytest.raises(Exception):retire(c,identifier)
    with pytest.raises(lifecycle_guard.NativeInvoiceLifecycleError):
        lifecycle_guard.inspect_source_lifecycle(c.source,runtime=c.runtime)
    assert saved(c,identifier)['intent_header'] is None and saved(c,identifier)['resolution_ciphertext'] is None
