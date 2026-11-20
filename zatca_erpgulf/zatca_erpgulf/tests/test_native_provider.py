"""Fixed-callsite native facade with explicit orchestration doubles only."""

from types import SimpleNamespace
from unittest.mock import Mock
import inspect

import pytest

from zatca_erpgulf.zatca_erpgulf import native_provider as provider, native_delivery as delivery, deferred_submission
from zatca_erpgulf.zatca_erpgulf.native_dispatch import NativeDispatchOutcome,RetainedNativeIssuance,RetainedNativeView
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_item_template_mode import ROUTES,isolated,route_boundary
from zatca_erpgulf.ksa_compliance import field_compat


UNIT='30000000-0000-4000-8000-000000000001'
CLASSIFIED_XML=(b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    b'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
    b'<cbc:InvoiceTypeCode name="0200000">388</cbc:InvoiceTypeCode></Invoice>')


@pytest.fixture
def entry(monkeypatch):
    source=Document(doctype='Sales Invoice',name='SYNTHETIC',company='COMPANY',customer='BUYER',docstatus=1)
    company=Document(doctype='Company',name='COMPANY',custom_zatca_native_chain=UNIT,
        custom_zatca_invoice_enabled=1,custom_phase_1_or_2='Phase-2',custom_send_invoice_to_zatca='Live')
    customer=Document(doctype='Customer',name='BUYER',b2c=1)
    docs={(doc.doctype,doc.name):doc for doc in (source,company,customer)}
    def throw(message,*,exc):raise exc
    def permission(doctype,operation,*,doc,user,raise_exception=True):return True
    runtime=SimpleNamespace(local=SimpleNamespace(site='fictional.invalid'),session=SimpleNamespace(user='operator'),
        flags={},conf={'zatca_native_dispatch':1},get_meta=lambda dt:SimpleNamespace(has_field=lambda field:True),
        get_doc=Mock(side_effect=lambda dt,name:docs[dt,name]),has_permission=permission,
        log_error=Mock(),throw=Mock(side_effect=throw))
    monkeypatch.setattr(delivery,'get_alias_value',lambda group,doc,default:doc.get('b2c',default))
    monkeypatch.setattr(field_compat,'field_exists',lambda dt,name:hasattr(company,name))
    read=Mock(return_value=None)
    prepare=Mock(return_value=RetainedNativeIssuance('ISSUANCE','PREPARED',False,source.doctype,source.name))
    dispatch=Mock(return_value=NativeDispatchOutcome('ISSUANCE','ATTEMPT','REPORTING_MATCHED',True,0,False))
    monkeypatch.setattr(provider,'read_retained_invoice',read)
    monkeypatch.setattr(provider,'prepare_saved_invoice',prepare)
    monkeypatch.setattr(provider,'dispatch_saved_invoice',dispatch)
    build=Mock()
    def run(intent='entry'):
        return provider.maybe_process_native_invoice(source.doctype,source.name,runtime=runtime,translate=lambda text:'AR:'+text,
            build=build,intent=intent)
    return SimpleNamespace(source=source,company=company,customer=customer,runtime=runtime,read=read,
        prepare=prepare,dispatch=dispatch,run=run,build=build,docs=docs)


@pytest.mark.parametrize('method,intent,status',[('Live','entry','SUCCESS'),('Batches','submit','PREPARED'),
    ('Background','entry','PREPARED'),('Batches','manual','SUCCESS')])
def test_native_operation_uses_the_owned_service_without_synthetic_authority_success(entry,method,intent,status):
    e=entry;e.company.custom_send_invoice_to_zatca=method
    result=e.run(intent)
    assert result['status']==status and result['accepted'] is (status=='SUCCESS')
    operation=e.dispatch if status=='SUCCESS' else e.prepare
    operation.assert_called_once()
    assert operation.call_args.kwargs['build'] is e.build and 'PRIVATE' not in str(result)
    assert delivery.CURRENT.get() is None


def test_unmarked_legacy_owner_does_not_enter_native_custody(entry):
    e=entry;e.company.custom_zatca_native_chain=None
    assert e.run() is None
    e.read.assert_not_called();e.prepare.assert_not_called();e.dispatch.assert_not_called()


def test_cached_verified_acceptance_needs_no_current_customer_key_or_enabled_rollout(entry):
    e=entry;e.source.custom_zatca_issuing_unit='egs:'+UNIT;e.runtime.conf['zatca_native_dispatch']=0
    e.company.custom_private_key='INVALID';del e.docs['Customer','BUYER']
    e.read.return_value=RetainedNativeView('ISSUANCE','ATTEMPT','REPORTED','REPORTING_MATCHED',True,0,False,b'PRIVATE-XML',None)
    result=e.run();assert result['accepted'] is True
    assert all(call.args[0]!='Customer' for call in e.runtime.get_doc.call_args_list)
    e.prepare.assert_not_called()


@pytest.mark.parametrize('state,status',[('PREPARED','PREPARED'),('REJECTED','ERROR'),('OUTCOME_UNKNOWN','REVIEW')])
def test_hold_policy_keeps_exact_custody_without_regeneration_or_retry(entry,state,status):
    e=entry;e.company.custom_send_invoice_to_zatca='Batches'
    e.read.return_value=RetainedNativeView('ISSUANCE',None,state,'RETAINED_ORIGINAL',False,0,False,CLASSIFIED_XML,None)
    result=e.run();assert result['status']==status and not result['accepted']
    e.prepare.assert_not_called();e.dispatch.assert_not_called()


@pytest.mark.parametrize('state',['REJECTED','DISPATCHING','OUTCOME_UNKNOWN','REVIEW_REQUIRED'])
def test_ordinary_manual_or_live_processing_does_not_blindly_retry_an_unconfirmed_attempt(entry,state):
    e=entry;e.read.return_value=RetainedNativeView('ISSUANCE','ATTEMPT',state,'RETAINED_ORIGINAL',False,0,False,b'PRIVATE',None)
    result=e.run('manual')
    assert not result['accepted'] and result['status'] in ('ERROR','REVIEW')
    e.prepare.assert_not_called();e.dispatch.assert_not_called()


@pytest.mark.parametrize('outcome,current',[('AUTHORIZATION_FAILED',True),('VALIDATION_REJECTED',True),('REPORTING_MATCHED',False)])
def test_unauthorized_rejected_or_stale_outcome_is_never_success(entry,outcome,current):
    entry.dispatch.return_value=NativeDispatchOutcome('ISSUANCE','ATTEMPT',outcome,current,0,False)
    result=entry.run();assert result['status']!='SUCCESS' and not result['accepted']


def test_native_review_has_one_translated_boundary_and_redacted_english_diagnostic(entry):
    e=entry
    def failed_child(*args,**kwargs):
        assert e.runtime.flags['mute_messages'] is True
        raise RuntimeError('PRIVATE-TOKEN-ERROR')
    e.dispatch.side_effect=failed_child
    with pytest.raises(provider.NativeProviderError) as failed:e.run()
    assert failed.value.__context__ is None and 'PRIVATE' not in str(failed.value)
    assert e.runtime.throw.call_args.args[0].startswith('AR:')
    e.runtime.throw.assert_called_once();e.runtime.log_error.assert_called_once()
    assert 'AR:' not in str(e.runtime.log_error.call_args) and 'PRIVATE' not in str(e.runtime.log_error.call_args)
    assert e.runtime.flags=={}


@pytest.mark.parametrize('route',ROUTES[:6])
def test_each_generator_hands_its_fixed_builder_to_the_facade_before_identity_preparation(route_boundary,monkeypatch,route):
    b=route_boundary;module,name,doctype,_=route;b.doc.doctype=doctype
    facade=Mock(return_value={'status':'PREPARED','accepted':False})
    monkeypatch.setattr(provider,'maybe_process_native_invoice',facade)
    result=inspect.unwrap(getattr(module,name))(b.doc.name)
    assert result['status']=='PREPARED'
    facade.assert_called_once()
    assert facade.call_args.args==(doctype,b.doc.name) and callable(facade.call_args.kwargs['build'])
    module.salesinvoice_data.assert_not_called()


def test_deferred_worker_consults_native_custody_before_a_legacy_success_status(entry,monkeypatch):
    e=entry;e.source.custom_zatca_status='REPORTED'
    facade=Mock(return_value={'status':'REVIEW','accepted':False})
    monkeypatch.setattr(provider,'maybe_process_native_invoice',facade)
    legacy=Mock()
    result=deferred_submission._execute_saved_invoice(e.source.doctype,e.source.name,runtime=e.runtime,
        translate=lambda text:text,process=legacy)
    assert result['status']=='REVIEW'
    facade.assert_called_once();legacy.assert_not_called()


@pytest.mark.parametrize('route',ROUTES[:2])
def test_manual_collection_returns_the_owned_outcome_without_calling_legacy_resubmission(entry,monkeypatch,route):
    e=entry;module,_fn,doctype,_purpose=route
    e.docs.pop((e.source.doctype,e.source.name));e.source.doctype=doctype;e.docs[doctype,e.source.name]=e.source
    monkeypatch.setattr(module,'frappe',e.runtime)
    monkeypatch.setattr(module,'_',lambda text:text)
    owned=Mock(return_value={'status':'SUCCESS','accepted':True})
    monkeypatch.setattr(provider,'process_native_saved_source',owned)
    legacy=Mock();monkeypatch.setattr(module,'zatca_background_on_submit',legacy)
    function=module.resubmit_invoices if doctype=='Sales Invoice' else module.resubmit_invoices_pos
    result=inspect.unwrap(function)([e.source.name])
    assert result[e.source.name]['accepted'] is True
    assert owned.call_args.kwargs['intent']=='manual'
    legacy.assert_not_called()


def test_pos_manual_draft_uses_its_own_document_when_authorized_for_submission(entry,monkeypatch):
    from contextlib import nullcontext
    from zatca_erpgulf.zatca_erpgulf import native_draft_transaction
    # Collection identity only; actual savepoint ownership has private SQL tests.
    monkeypatch.setattr(native_draft_transaction,'protect_native_draft',lambda *args,**kwargs:nullcontext())
    from zatca_erpgulf.zatca_erpgulf import pos_sign
    e=entry;e.docs.pop((e.source.doctype,e.source.name));e.source.doctype='POS Invoice';e.source.docstatus=0
    e.docs['POS Invoice',e.source.name]=e.source;e.source.submit=Mock();e.company.custom_submit_or_not=1
    monkeypatch.setattr(pos_sign,'frappe',e.runtime)
    monkeypatch.setattr(pos_sign,'get_alias_value',lambda group,doc,default:doc.get('b2c',default))
    inspect.unwrap(pos_sign.resubmit_invoices_pos)([e.source.name])
    e.source.submit.assert_called_once()


@pytest.mark.parametrize('method,enabled,phase,reason',[('Background',1,'Phase-2','outside_company_window'),
    ('Batches',1,'Phase-2','company_policy_changed'),('Background',0,'Phase-2','company_policy_changed'),
    ('Background',1,'Phase-1','company_policy_changed')])
def test_only_current_enabled_background_window_skip_is_identified_as_safe_wait(entry,monkeypatch,method,enabled,phase,reason):
    from datetime import datetime
    e=entry;e.company.custom_send_invoice_to_zatca=method;e.company.custom_zatca_invoice_enabled=enabled
    e.company.custom_phase_1_or_2=phase;e.company.custom_start_time='09:00:00';e.company.custom_end_time='11:00:00'
    monkeypatch.setattr(delivery,'now_datetime',lambda:datetime(2026,11,20,13))
    assert e.run('scheduled')=={'status':'SKIPPED','accepted':False,'reason':reason}
    e.prepare.assert_not_called();e.dispatch.assert_not_called()


@pytest.mark.parametrize('state',['REJECTED','DISPATCHING','OUTCOME_UNKNOWN','REVIEW_REQUIRED'])
def test_uncertain_or_rejected_retained_original_is_not_hidden_by_a_closed_schedule(entry,monkeypatch,state):
    from datetime import datetime
    e=entry;e.company.custom_send_invoice_to_zatca='Background'
    e.company.custom_start_time='09:00:00';e.company.custom_end_time='11:00:00'
    e.read.return_value=RetainedNativeView('ISSUANCE','ATTEMPT',state,'RETAINED_ORIGINAL',False,0,False,b'PRIVATE',None)
    monkeypatch.setattr(delivery,'now_datetime',lambda:datetime(2026,11,20,13))
    result=e.run('scheduled')
    assert result['status']==('ERROR' if state=='REJECTED' else 'REVIEW') and result['state']==state
    assert 'reason' not in result
    e.prepare.assert_not_called();e.dispatch.assert_not_called()
