"""Actual eight XML entries over private custody and attached local test files.

Active registration/framework loaders are fixtures; synthetic UBL signing and
mocked transport do not prove installed ERP generation, SDK or authority success.
"""

import os
import json
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_dispatch,native_projection
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_legacy_submission_context import ADAPTERS
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider_mariadb import (
    case,boundary,materials,isolated_server,connections,tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import signed_build


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',
    reason='Owned private SQL opt-in only')


def attach_original(c,tmp_path,monkeypatch,*,prepared=True,generate=True):
    if generate:
        assert c.run()['status']==('PREPARED' if prepared else 'SUCCESS')
    source=c.runtime.get_doc(c.source.doctype,c.source.name)
    view=native_dispatch.read_retained_invoice(source.doctype,source.name,runtime=c.runtime)
    folder=tmp_path/'private'/'files';folder.mkdir(parents=True)
    path=folder/'original.xml';path.write_bytes(view.original_xml)
    file_name='FILE-'+c.identifier
    with c.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE `tabFile` ADD COLUMN IF NOT EXISTS file_url VARCHAR(255)')
        cursor.execute('ALTER TABLE `tabFile` ADD COLUMN IF NOT EXISTS is_private INT')
        cursor.execute('INSERT INTO `tabFile` (name,attached_to_doctype,attached_to_name,file_name,file_url,is_private) '
            'VALUES (%s,%s,%s,%s,%s,1)',(file_name,source.doctype,source.name,'original.xml','/private/files/original.xml'))
    c.connection.commit()
    original=c.runtime.get_doc
    def get_doc(dt,name,**kwargs):
        if dt=='File':
            rows=c.runtime.db.sql('SELECT * FROM `tabFile` WHERE name=%s',(name,),as_dict=True)
            return Document(doctype='File',**rows[0])
        return original(dt,name,**kwargs)
    monkeypatch.setattr(c.runtime,'get_doc',get_doc)
    def get_all(dt,*,filters,fields,order_by,limit_page_length):
        assert dt=='File' and fields==['name'] and order_by=='name asc' and limit_page_length==2
        urls=filters['file_url'][1]
        return c.runtime.db.sql('SELECT name FROM `tabFile` WHERE attached_to_doctype=%s AND attached_to_name=%s '
            'AND file_url IN ('+','.join('%s' for _ in urls)+') ORDER BY name LIMIT 2',
            (filters['attached_to_doctype'],filters['attached_to_name'],*urls),as_dict=True)
    monkeypatch.setattr(c.runtime,'get_all',get_all,raising=False)
    monkeypatch.setattr(c.runtime,'get_site_path',lambda *parts:str(folder),raising=False)
    for module,*_ in ADAPTERS:
        monkeypatch.setattr(module,'frappe',c.runtime)
        monkeypatch.setattr(module,'_',lambda text:text)
    return source,view,path,file_name


@pytest.mark.parametrize('case,adapter_index',[
    ((route,kind,mode,True),n)
    for n,(_,_,_,source_kind,requires,_) in enumerate(ADAPTERS)
    for route in ([0] if source_kind=='sales' else [1])
    for kind in ('company','device','linked') if not (requires and kind=='company')
    for mode in ('Live','Batches')],indirect=['case'])
@pytest.mark.parametrize('wrapper',[False,True])
def test_all_existing_xml_entries_use_exact_owned_custody_and_cached_result(case,tmp_path,monkeypatch,adapter_index,wrapper):
    c=case
    # Capture the original through the normal generated entry, holding it first.
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Batches',c.company.name))
    c.connection.commit()
    source,view,path,_=attach_original(c,tmp_path,monkeypatch)
    desired=c.company.custom_send_invoice_to_zatca
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',(desired,c.company.name))
    c.connection.commit()
    module,api,wrapper_name,*_=ADAPTERS[adapter_index]
    before_files=c.database.sql('SELECT COUNT(*) AS total FROM `tabFile`',as_dict=True)[0]['total']
    def run():
        current=c.runtime.get_doc(source.doctype,source.name)
        if wrapper:return getattr(module,wrapper_name)(current,'/private/files/original.xml',source.name)
        return getattr(module,api)(view.invoice_uuid,view.invoice_hash,str(path),source.name,current)
    result=run()
    assert result['accepted'] is (desired=='Live') and result['issuance_id']==view.issuance_id
    assert len(c.built)==1 and len(c.sent)==int(desired=='Live') and c.head()=='1'
    assert native_dispatch.read_retained_invoice(source.doctype,source.name,runtime=c.runtime).original_xml==view.original_xml
    if desired=='Live':
        c.runtime.conf['zatca_native_dispatch']=0;c.selected.custom_private_key='INVALID'
        again=run();assert again['accepted'] and again['reused'] and len(c.sent)==1 and c.head()=='1'
    assert path.read_bytes()==view.original_xml
    assert c.database.sql('SELECT COUNT(*) AS total FROM `tabFile`',as_dict=True)[0]['total']==before_files
    assert c.database.sql('SELECT COUNT(*) AS total FROM `tabFile` WHERE attached_to_doctype=%s AND attached_to_name=%s',
        (source.doctype,source.name),as_dict=True)[0]['total']==1
    c.b.request.assert_not_called()


@pytest.mark.parametrize('case,adapter_index',[
    ((0,'device','Live',True),0),((0,'device','Live',True),2),
    ((1,'device','Live',True),1),((1,'device','Live',True),3)],indirect=['case'])
def test_owned_generation_handoff_precedes_old_xml_progress_and_response_writers(case,monkeypatch,adapter_index):
    c=case;module,api,*_=ADAPTERS[adapter_index]
    monkeypatch.setattr(module,'frappe',c.runtime)
    monkeypatch.setattr(module,'_',lambda text:text)
    def metadata(root,invoice_number,**kwargs):
        c.built.append(invoice_number)
        signed_build(c.b,c.runtime.get_doc(c.source.doctype,c.source.name),api=getattr(module,api))
        pytest.fail('Owned handoff was not raised')
    monkeypatch.setattr(c.module,'prepare_invoice_generation',metadata)
    realtime=Mock(side_effect=AssertionError('No legacy progress before owned handoff'))
    monkeypatch.setattr(c.runtime,'publish_realtime',realtime,raising=False)
    assert c.run()['accepted'] and len(c.sent)==1 and len(c.built)==1 and c.head()=='1'
    realtime.assert_not_called()
    c.b.request.assert_not_called()


def test_stale_expected_issuance_is_checked_under_reservation_locks_before_any_attempt(case,tmp_path,monkeypatch):
    c=case
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Batches',c.company.name))
    c.connection.commit()
    source,view,path,_=attach_original(c,tmp_path,monkeypatch)
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Live',c.company.name))
    c.connection.commit()
    with pytest.raises(native_dispatch.NativeDispatchError,match='native_expected_issuance_changed'):
        native_dispatch.reserve_saved_issuance(source.doctype,source.name,runtime=c.runtime,translate=lambda s:s,
            expected_issuance_id='10000000-0000-4000-8000-000000000099')
    assert c.database.sql('SELECT COUNT(*) AS total FROM `tabZATCA Dispatch Attempt` WHERE source_doctype=%s AND source_name=%s',
        (source.doctype,source.name),as_dict=True)[0]['total']==0
    assert not c.sent and len(c.built)==1 and c.head()=='1' and path.read_bytes()==view.original_xml


def test_expected_version_prevents_repairing_a_different_current_source(case,tmp_path,monkeypatch):
    c=case;source,view,path,_=attach_original(c,tmp_path,monkeypatch,prepared=False)
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tab'+source.doctype+'` SET custom_zatca_status=%s,custom_zatca_full_response=%s WHERE name=%s',
            ('Not Submitted','',source.name))
    c.connection.commit()
    with pytest.raises(native_dispatch.NativeDispatchError,match='native_expected_issuance_changed'):
        native_projection.project_accepted_status(source.doctype,source.name,runtime=c.runtime,
            expected_issuance_id='10000000-0000-4000-8000-000000000099')
    assert c.runtime.get_doc(source.doctype,source.name).custom_zatca_status=='Not Submitted'
    assert len(c.sent)==1 and len(c.built)==1 and c.head()=='1'


@pytest.mark.parametrize('status,state,result_status',[(401,'OUTCOME_UNKNOWN','REVIEW'),(400,'REJECTED','ERROR')])
def test_matching_upload_cannot_blindly_resend_unknown_or_rejected_requests(case,tmp_path,monkeypatch,status,state,result_status):
    c=case
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Batches',c.company.name))
    c.connection.commit()
    source,view,path,_=attach_original(c,tmp_path,monkeypatch)
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Live',c.company.name))
    c.connection.commit()
    original_send=c.adapter.send.side_effect
    def response(prepared,**kwargs):
        result=original_send(prepared,**kwargs);result.status_code=status
        body=json.dumps({'validationResults':{'status':'ERROR','infoMessages':[],'warningMessages':[],
            'errorMessages':[{'type':'ERROR','status':'ERROR','code':'QRCODE_INVALID','message':'Synthetic rejection'}]},
            'reportingStatus':'NOT_REPORTED'}).encode() if status==400 else b'UNAUTHORIZED-SYNTHETIC'
        result.raw.read1=Mock(side_effect=[body,b''])
        return result
    c.adapter.send.side_effect=response
    module,_,wrapper,*_=ADAPTERS[0]
    def run():return getattr(module,wrapper)(c.runtime.get_doc(source.doctype,source.name),'/private/files/original.xml',source.name)
    assert run()['status']==result_status
    assert native_dispatch.read_retained_invoice(source.doctype,source.name,runtime=c.runtime).state==state
    assert run()['status']==result_status
    assert len(c.sent)==len(c.built)==1 and c.head()=='1'


@pytest.mark.parametrize('case',[(0,'device','Batches',True),(0,'device','Batches',False)],indirect=True)
def test_existing_xml_uses_issued_kind_after_customer_classification_changes(case,tmp_path,monkeypatch):
    c=case
    # Both kinds are first prepared without transport, using the existing fixed
    # generator inside the owned preparation primitive. No policy flag is forged.
    native_dispatch.prepare_saved_invoice(c.source.doctype,c.source.name,runtime=c.runtime,translate=lambda s:s,
        build=lambda locked:getattr(c.module,c.fn)(locked.name))
    source=c.runtime.get_doc(c.source.doctype,c.source.name)
    view=native_dispatch.read_retained_invoice(source.doctype,source.name,runtime=c.runtime)
    # Install the same attachment adapter without generating a second original.
    source,_,path,_=attach_original(c,tmp_path,monkeypatch,generate=False)
    was_simplified=bool(c.customer.custom_b2c)
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabCustomer` SET custom_b2c=%s WHERE name=%s',(int(not was_simplified),source.customer))
    c.connection.commit()
    module,_,wrapper,*_=ADAPTERS[0]
    result=getattr(module,wrapper)(c.runtime.get_doc(source.doctype,source.name),'/private/files/original.xml',source.name)
    assert result['accepted'] is (not was_simplified)
    assert len(c.sent)==(0 if was_simplified else 2) and len(c.built)==1 and c.head()=='1'
    assert native_dispatch.read_retained_invoice(source.doctype,source.name,runtime=c.runtime).original_xml==view.original_xml
