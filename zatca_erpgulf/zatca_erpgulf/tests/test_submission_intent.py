"""Durable handoff value/context boundaries; no SQL/site/queue/authority."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf import submission_intent_worker as worker
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher, DispatchRecordError
from zatca_erpgulf.zatca_erpgulf.tests.test_publication_source import invoice


class Source(SimpleNamespace):
    def get(self,key,default=None):return getattr(self,key,default)
    def as_dict(self):return vars(self).copy()


def header(source=None):
    source=source or Source(**invoice())
    return dict(record_id=str(uuid4()),source_key=intent.source_key(source.doctype,source.name),
        source_doctype=source.doctype,source_name=source.name,company=source.company,actor='operator@example.invalid',
        chain=str(uuid4()),intent='submit',source_sha256=intent.fiscal_sha(source),
        created_at_utc='2026-11-20T09:00:00.000000')


@pytest.mark.parametrize('field,value',[('extra',1),('actor','Guest'),('intent','arbitrary'),('chain','bad'),
    ('source_key','a'*64),('source_sha256','BAD'),('created_at_utc','2026-11-20T9:00:00'),
    ('created_at_utc','2026-02-30T09:00:00.000000'),('source_doctype','Quotation'),('company',' x ')])
def test_header_rejects_incomplete_or_cross_bound_values(field,value):
    h=header();h[field]=value
    with pytest.raises((ValueError,RuntimeError)):intent.validate_header(h)


@pytest.mark.parametrize('kind',['artifact','receipt','storage-probe','publication-source'])
def test_intent_envelope_cannot_be_opened_as_another_payload_kind(kind):
    h=header();raw=intent.validate_header(h)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    value=cipher.seal(h['record_id'],'submission-intent',raw,intent.BODY)
    assert cipher.open(h['record_id'],'submission-intent',raw,value)==intent.BODY
    with pytest.raises(DispatchRecordError):cipher.open(h['record_id'],kind,raw,value)


@pytest.mark.parametrize('change',['money','child','actor','site','company','chain','source','cancelled'])
def test_execution_binding_rejects_fiscal_source_or_context_drift(change):
    doc=Source(**invoice());h=header(doc)
    runtime=SimpleNamespace(local=SimpleNamespace(site='fictional.invalid'),session=SimpleNamespace(user=h['actor']))
    with intent.execution_context(runtime,h):
        intent.require_bound_source(runtime,doc,h['chain'])
        chain=h['chain']
        if change=='money':doc.grand_total=Decimal('114.99')
        elif change=='child':doc.items[0]['net_amount']=Decimal('99.99')
        elif change=='actor':runtime.session.user='Administrator'
        elif change=='site':runtime.local.site='other.invalid'
        elif change=='company':doc.company='OTHER'
        elif change=='chain':chain=str(uuid4())
        elif change=='source':doc.name='OTHER'
        else:doc.docstatus=2
        with pytest.raises(intent.SubmissionIntentError):intent.require_bound_source(runtime,doc,chain)
    assert intent.CURRENT.get() is None


def test_outputs_and_named_collection_state_keep_the_committed_fiscal_binding():
    doc=Source(**invoice());before=intent.fiscal_sha(doc)
    doc.custom_uuid=str(uuid4());doc.custom_zatca_status='REPORTED';doc.custom_zatca_icv='123'
    doc.outstanding_amount=Decimal('0.00');doc.status='Paid';doc.modified=datetime(2026,11,20)
    doc.payment_schedule[0]['paid_amount']=Decimal('115.00')
    assert intent.fiscal_sha(doc)==before
    doc.paid_amount=Decimal('115.00')
    assert intent.fiscal_sha(doc)!=before


def test_partial_document_cannot_claim_complete_fiscal_binding():
    with pytest.raises(intent.SubmissionIntentError):intent.fiscal_sha(SimpleNamespace(doctype='Sales Invoice',name='X'))


@pytest.mark.parametrize('fail',[False,True])
def test_internal_actor_queue_scope_restores_session_and_permission_caches(fail):
    local=SimpleNamespace(site='fictional.invalid',cache={'original':1},form_dict={'a':1})
    runtime=SimpleNamespace(local=local,db=object(),session=SimpleNamespace(user='Administrator',sid='ORIGINAL',data={'x':1}))
    original_session=vars(runtime.session).copy();original_local=vars(local).copy()
    def set_user(user):
        runtime.session.user=user;runtime.session.sid='';runtime.session.data={}
        for key in ('cache','form_dict','jenv','role_permissions','new_doc_templates','user_perms'):setattr(local,key,{})
    runtime.set_user=set_user
    def run():
        with worker._queue_as_actor(runtime,'operator@example.invalid'):
            assert runtime.session.user=='operator@example.invalid'
            if fail:raise RuntimeError('queue unavailable')
    if fail:
        with pytest.raises(RuntimeError):run()
    else:run()
    assert vars(runtime.session)==original_session and vars(local)==original_local
    assert runtime.session.data is original_session['data'] and local.cache is original_local['cache']


@pytest.mark.parametrize('state',['RUNNING','REVIEW','COMPLETE'])
def test_nonready_job_never_processes_or_finishes_again(monkeypatch,state):
    h=header();monkeypatch.setattr(worker,'_claim',lambda *args:(h,None,state))
    process=Mock();finish=Mock();monkeypatch.setattr(worker,'_process',process);monkeypatch.setattr(worker,'_finish',finish)
    assert worker.run_submission_intent(h['record_id'],runtime=object(),translate=str,build=Mock())['status']==state
    process.assert_not_called();finish.assert_not_called()


@pytest.mark.parametrize('result,state,code',[
    ({'status':'PREPARED','accepted':False},'COMPLETE','prepared'),
    ({'status':'SUCCESS','accepted':True},'COMPLETE','accepted'),
    ({'status':'SUCCESS','accepted':False},'REVIEW','native_operation_review'),
    ({'status':'UNKNOWN','accepted':False},'REVIEW','native_operation_review'),
    ({'status':'ERROR','accepted':False},'REVIEW','native_operation_review')])
def test_only_prepared_or_explicit_accepted_result_completes_the_handoff(monkeypatch,result,state,code):
    h=header();runtime=object()
    monkeypatch.setattr(worker,'_claim',lambda *args:(h,'fence','RUNNING'))
    monkeypatch.setattr(worker,'_process',lambda *args:result)
    finish=Mock();monkeypatch.setattr(worker,'_finish',finish)
    assert worker.run_submission_intent(h['record_id'],runtime=runtime,translate=str,build=Mock())['status']==state
    finish.assert_called_once_with(runtime,h,'fence',state,code)


def test_processing_error_is_redacted_and_unknown_claim_commit_is_not_compensated(monkeypatch):
    h=header();monkeypatch.setattr(worker,'_claim',lambda *args:(h,'fence','RUNNING'))
    monkeypatch.setattr(worker,'_process',Mock(side_effect=RuntimeError('PRIVATE-SECRET')))
    finish=Mock();monkeypatch.setattr(worker,'_finish',finish)
    result=worker.run_submission_intent(h['record_id'],runtime=object(),translate=str,build=Mock())
    assert result['status']=='REVIEW' and 'PRIVATE' not in repr(result)+repr(finish.call_args)
    monkeypatch.setattr(worker,'_claim',Mock(side_effect=RuntimeError('unknown commit')))
    finish.reset_mock()
    with pytest.raises(RuntimeError):worker.run_submission_intent(h['record_id'],runtime=object(),translate=str,build=Mock())
    finish.assert_not_called()


@pytest.mark.parametrize('operation,skipped,state,code',[
    ('scheduled',{'status':'SKIPPED','accepted':False,'reason':'outside_company_window'},'WAITING','outside_company_window'),
    ('submit',{'status':'SKIPPED','accepted':False,'reason':'outside_company_window'},'REVIEW','native_operation_review'),
    ('manual',{'status':'SKIPPED','accepted':False,'reason':'outside_company_window'},'REVIEW','native_operation_review'),
    ('scheduled',{'status':'SKIPPED','accepted':False,'reason':'company_policy_changed'},'REVIEW','native_operation_review'),
    ('scheduled',{'status':'SKIPPED','accepted':0,'reason':'outside_company_window'},'REVIEW','native_operation_review'),
    ('scheduled',{'status':'UNKNOWN','accepted':False,'reason':'outside_company_window'},'REVIEW','native_operation_review'),
    ('scheduled',{'status':'SKIPPED','accepted':False,'reason':'outside_company_window','extra':True},'REVIEW','native_operation_review')])
def test_only_exact_pretransport_scheduled_window_skip_can_wait(monkeypatch,operation,skipped,state,code):
    h=header();h['intent']=operation;runtime=object()
    monkeypatch.setattr(worker,'_claim',lambda *args:(h,'fence','RUNNING'))
    monkeypatch.setattr(worker,'_process',lambda *args:skipped)
    finish=Mock();monkeypatch.setattr(worker,'_finish',finish)
    result=worker.run_submission_intent(h['record_id'],runtime=runtime,translate=str,build=Mock())
    assert result['status']==state
    finish.assert_called_once_with(runtime,h,'fence',state,code)
