"""Native attached-original admission and fixed callsites; no HTTP/ERP claims."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_existing_xml as adapter
from zatca_erpgulf.zatca_erpgulf import native_provider as provider
from zatca_erpgulf.zatca_erpgulf.native_dispatch import RetainedNativeView,NativeDispatchOutcome
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider import entry,UNIT,CLASSIFIED_XML
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_legacy_submission_context import ADAPTERS


ISSUANCE='10000000-0000-4000-8000-000000000001'
UUID='20000000-0000-4000-8000-000000000001'


@pytest.fixture
def attached(entry,monkeypatch,tmp_path):
    e=entry;e.source.custom_zatca_issuing_unit='egs:'+UNIT
    e.source.custom_zatca_pos_name='DEVICE'
    path=tmp_path/'issued.xml';path.write_bytes(CLASSIFIED_XML)  # Classification only, not a signed UBL.
    file=Document(doctype='File',name='FISCAL-FILE',file_url='/private/files/issued.xml',file_name='issued.xml',
        is_private=1,attached_to_doctype=e.source.doctype,attached_to_name=e.source.name)
    e.docs['File',file.name]=file
    e.runtime.get_site_path=lambda *parts:str(tmp_path)
    e.runtime.get_all=Mock(return_value=[{'name':file.name}])
    view=RetainedNativeView(ISSUANCE,None,'PREPARED','RETAINED_ORIGINAL',False,0,False,
        path.read_bytes(),None,invoice_uuid=UUID,invoice_hash='HASH',icv='1',chain_id=UNIT)
    read=Mock(return_value=view)
    monkeypatch.setattr(adapter,'read_retained_invoice',read)
    e.read.return_value=view
    e.dispatch.return_value=NativeDispatchOutcome(ISSUANCE,'ATTEMPT','REPORTING_MATCHED',True,0,False)
    reader=Mock(wraps=adapter._read_local_attachment)
    monkeypatch.setattr(adapter,'_read_local_attachment',reader)
    def run(**kwargs):
        return adapter.maybe_process_native_existing_xml(e.source.doctype,e.source.name,file.file_url,
            runtime=e.runtime,translate=lambda text:'AR:'+text,source=e.source,**kwargs)
    e.file=file;e.path=path;e.view=view;e.initial_read=read;e.reader=reader;e.admit=run
    return e


@pytest.mark.parametrize('route',ADAPTERS)
@pytest.mark.parametrize('wrapper',[False,True])
def test_all_eight_real_entrypoints_return_the_native_result_without_legacy_writers(attached,monkeypatch,route,wrapper):
    e=attached;module,api,wrapper_name,kind,requires,*_=route
    if kind=='pos':
        del e.docs[e.source.doctype,e.source.name]
        e.source.doctype='POS Invoice';e.docs[e.source.doctype,e.source.name]=e.source
        e.file.attached_to_doctype=e.source.doctype
    monkeypatch.setattr(module,'frappe',e.runtime)
    monkeypatch.setattr(module,'_',lambda text:'AR:'+text)
    if wrapper:
        result=getattr(module,wrapper_name)(e.source,e.file.file_url,e.source.name)
    else:
        result=getattr(module,api)(UUID,'HASH',str(e.path),e.source.name,e.source)
    assert result['accepted'] and result['issuance_id']==ISSUANCE
    assert e.dispatch.call_args.kwargs['expected_issuance_id']==ISSUANCE
    e.reader.assert_called_once();e.build.assert_not_called();e.prepare.assert_not_called()
    e.runtime.log_error.assert_not_called()
    assert e.runtime.flags=={}


@pytest.mark.parametrize('method,state,status,accepted',[
    ('Live','PREPARED','SUCCESS',True),('Batches','PREPARED','PREPARED',False),
    ('Background','PREPARED','PREPARED',False),('Live','OUTCOME_UNKNOWN','REVIEW',False),
    ('Live','DISPATCHING','REVIEW',False),('Live','REJECTED','ERROR',False),
    ('Live','REVIEW_REQUIRED','REVIEW',False)])
def test_entry_policy_never_turns_an_uploaded_original_into_permission_to_retry(attached,method,state,status,accepted):
    e=attached;e.company.custom_send_invoice_to_zatca=method
    view=replace(e.view,state=state)
    e.initial_read.return_value=e.read.return_value=view
    result=e.admit()
    assert result['status']==status and result['accepted'] is accepted
    assert e.dispatch.call_count==int(accepted)
    e.prepare.assert_not_called();e.build.assert_not_called()


def test_cached_verified_acceptance_does_not_need_rollout_or_current_customer_credentials(attached):
    e=attached
    view=replace(e.view,state='REPORTED',accepted=True,outcome='REPORTING_MATCHED')
    e.initial_read.return_value=e.read.return_value=view
    e.runtime.conf['zatca_native_dispatch']=0;e.source.customer='MISSING'
    assert e.admit()['accepted'] and e.dispatch.call_count==1


@pytest.mark.parametrize('fault',['source_read','source_write','company_read','file_read','duplicate','missing',
    'public','debug','wrong_owner','wrong_url','bytes','symlink','missing_file','missing_original','device'])
def test_ambiguous_or_unauthorized_file_never_reaches_delivery_and_reports_once(attached,fault):
    e=attached
    denied={'source_read':('Sales Invoice','read'),'source_write':('Sales Invoice','write'),
        'company_read':('Company','read'),'file_read':('File','read')}
    if fault in denied:
        e.runtime.has_permission=lambda dt,op,*,doc,user,raise_exception=True:(dt,op)!=denied[fault]
    elif fault=='duplicate':e.runtime.get_all.return_value*=2
    elif fault=='missing':e.runtime.get_all.return_value=[]
    elif fault=='public':e.file.is_private=0
    elif fault=='debug':e.file.file_name='DEBUG_invoice.xml'
    elif fault=='wrong_owner':e.file.attached_to_name='OTHER'
    elif fault=='wrong_url':e.file.file_url='/private/files/other.xml'
    elif fault=='bytes':e.path.write_bytes(b'CHANGED-PRIVATE-XML')
    elif fault=='symlink':
        e.path.unlink();e.path.symlink_to(Path('/outside-private-folder'))
    elif fault=='missing_file':e.path.unlink()
    elif fault=='missing_original':e.initial_read.return_value=None
    elif fault=='device':e.source.custom_zatca_pos_name=None
    with pytest.raises(provider.NativeProviderError) as caught:
        e.admit(require_issuing_unit=fault=='device')
    assert caught.value.__context__ is None
    assert e.runtime.log_error.call_count==e.runtime.throw.call_count==1
    logged=e.runtime.log_error.call_args.kwargs['message']
    assert provider.REVIEW in logged and 'PRIVATE-XML' not in logged and 'AR:' not in logged
    e.dispatch.assert_not_called();e.prepare.assert_not_called();e.build.assert_not_called()
    assert e.runtime.flags=={}


@pytest.mark.parametrize('identity',[(UUID,'WRONG'),('WRONG','HASH'),(None,None)])
def test_raw_api_arguments_must_match_the_captured_original_before_file_reads(attached,identity):
    e=attached
    with pytest.raises(provider.NativeProviderError):e.admit(supplied_identity=identity)
    e.reader.assert_not_called();e.runtime.get_all.assert_not_called();e.dispatch.assert_not_called()


@pytest.mark.parametrize('path',['https://remote.invalid/a.xml','/public/files/issued.xml',
    '/private/files/../issued.xml','/private/files/%2e%2e%2fissued.xml','/private/files/a%00.xml',
    '/different-site/private/files/issued.xml'])
def test_untrusted_paths_are_not_opened_or_fetched(attached,path):
    e=attached
    with pytest.raises(provider.NativeProviderError):
        adapter.maybe_process_native_existing_xml(e.source.doctype,e.source.name,path,
            runtime=e.runtime,translate=lambda text:text,source=e.source)
    e.runtime.get_all.assert_not_called();e.reader.assert_not_called();e.dispatch.assert_not_called()


@pytest.mark.parametrize('path_kind',['url','file'])
def test_local_url_and_legacy_site_concatenation_select_only_owned_metadata(attached,path_kind):
    e=attached;path=e.file.file_url if path_kind=='url' else e.runtime.local.site+e.file.file_url
    result=adapter.maybe_process_native_existing_xml(e.source.doctype,e.source.name,path,
        runtime=e.runtime,translate=lambda text:text,source=e.source,path_kind=path_kind)
    assert result['accepted']
    filters=e.runtime.get_all.call_args.kwargs['filters']
    assert filters['attached_to_name']==e.source.name and filters['attached_to_doctype']==e.source.doctype


@pytest.mark.parametrize('change',['site','actor','latest'])
def test_context_or_version_changes_stop_before_any_attempt(attached,change):
    e=attached
    if change=='latest':e.read.return_value=replace(e.view,issuance_id='30000000-0000-4000-8000-000000000099')
    else:
        def rows(*args,**kwargs):
            if change=='site':e.runtime.local.site='OTHER.invalid'
            else:e.runtime.session.user='OTHER'
            return [{'name':e.file.name}]
        e.runtime.get_all.side_effect=rows
    with pytest.raises(provider.NativeProviderError):e.admit()
    e.dispatch.assert_not_called();e.prepare.assert_not_called()


def test_active_owned_preparation_keeps_the_existing_exact_payload_handoff(attached,monkeypatch):
    e=attached;monkeypatch.setattr(adapter,'active_preparation',lambda runtime:object())
    assert e.admit() is None
    e.runtime.get_all.assert_not_called();e.initial_read.assert_not_called();e.dispatch.assert_not_called()


def test_unmarked_legacy_owners_remain_outside_native_custody(attached):
    e=attached;e.source.custom_zatca_issuing_unit=None;e.company.custom_zatca_native_chain=None
    e.source.custom_zatca_pos_name=None
    assert e.admit() is None
    e.runtime.get_all.assert_not_called();e.initial_read.assert_not_called();e.dispatch.assert_not_called()


def test_caller_company_credentials_and_state_are_not_used_to_select_the_source(attached):
    e=attached
    supplied=Document(doctype=e.source.doctype,name=e.source.name,company='WRONG-COMPANY',
        custom_zatca_issuing_unit='egs:'+UNIT,docstatus=0,custom_private_key='PRIVATE-CALLER-KEY')
    result=adapter.maybe_process_native_existing_xml(e.source.doctype,e.source.name,e.file.file_url,
        runtime=e.runtime,translate=lambda s:s,source=supplied)
    assert result['accepted'] and 'PRIVATE' not in str(result)
    e.dispatch.assert_called_once()


def test_conflicting_caller_source_identity_cannot_submit_another_record(attached):
    e=attached
    supplied=Document(doctype=e.source.doctype,name='OTHER',custom_zatca_issuing_unit='egs:'+UNIT)
    with pytest.raises(provider.NativeProviderError,match=provider.REVIEW):
        adapter.maybe_process_native_existing_xml(e.source.doctype,e.source.name,e.file.file_url,
            runtime=e.runtime,translate=lambda s:s,source=supplied)
    e.runtime.get_all.assert_not_called();e.initial_read.assert_not_called();e.dispatch.assert_not_called()


def test_schema_discovery_failure_is_redacted_before_any_file_or_custody_access(attached):
    e=attached;e.source.custom_zatca_issuing_unit=None
    e.runtime.get_meta=Mock(side_effect=RuntimeError('PRIVATE-SCHEMA-DETAILS'))
    with pytest.raises(provider.NativeProviderError):e.admit()
    assert 'PRIVATE' not in str(e.runtime.log_error.call_args)
    e.runtime.get_all.assert_not_called();e.initial_read.assert_not_called();e.dispatch.assert_not_called()
