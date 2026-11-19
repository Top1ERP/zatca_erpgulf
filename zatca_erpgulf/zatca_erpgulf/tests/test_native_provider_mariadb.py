"""Native facade/adapters with preseeded custody, private SQL and mocked HTTP.

Active registration is fixture input, not activation proof. The six actual entry
functions run through their fixed callbacks; a metadata stub supplies the existing
synthetic UBL/signing builder. This does not certify ERP financial builders/SDK.
"""

import base64
from datetime import datetime
import inspect
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from requests.structures import CaseInsensitiveDict
import pytest

from zatca_erpgulf.zatca_erpgulf import (
    native_provider as provider,native_delivery as delivery,native_dispatch,native_transport,
    api_settings,credential_settings,sign_invoice_first,submission_context,primary_qr_attachment,
)
from zatca_erpgulf.ksa_compliance import field_compat
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import boundary,materials,setup
from zatca_erpgulf.zatca_erpgulf.tests.test_item_template_mode import ROUTES
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import signed_build
from zatca_erpgulf.zatca_erpgulf.tests.test_native_preparation import registration
from zatca_erpgulf.zatca_erpgulf.tests.test_native_owned_pipeline_mariadb import OwnedDatabase,Runtime
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch_store_mariadb import isolated_server,connections,tables
from zatca_erpgulf.zatca_erpgulf.tests.test_worker_transaction import control_rows


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


@pytest.fixture
def case(boundary,materials,monkeypatch,connections,tables,request):
    route_index,kind,method,simplified=getattr(request,'param',(0,'company','Live',True))
    b=boundary;index={'company':0,'device':2,'linked':1}[kind];selected=setup(b,monkeypatch,kind)
    suffix='-'+str(uuid4())[:8]
    for record in (b.company,b.linked,b.device,b.sales,b.pos):record.name+=suffix
    b.device.custom_linked_doctype=b.linked.name if kind=='linked' else b.company.name
    b.company.custom_zatca_invoice_enabled=1;b.company.custom_phase_1_or_2='Phase-2'
    b.company.custom_send_invoice_to_zatca=method;b.company.custom_start_time='09:00:00';b.company.custom_end_time='11:00:00'
    b.company.company_name='Synthetic issuer'
    module,fn,doctype,_=ROUTES[route_index]
    source=b.sales if doctype=='Sales Invoice' else b.pos
    source.company=b.company.name;source.docstatus=1;source.customer='BUYER'+suffix
    source.custom_zatca_pos_name=None if kind=='company' else b.device.name
    customer=Document(doctype='Customer',name=source.customer,custom_b2c=int(simplified))
    connection=connections();database=OwnedDatabase(connection);runtime=Runtime(b.frappe,database)
    runtime.conf['zatca_native_dispatch']=1
    runtime.has_permission=lambda dt,operation,*,doc,user,raise_exception=True:True
    runtime.get_meta=lambda dt:SimpleNamespace(get_table_fields=lambda:[],has_field=lambda name:name=='custom_zatca_native_chain',
        get_field=lambda name:name if name in ('custom_phase_1_or_2','custom_zatca_invoice_enabled') else None)
    chain=registration(b,selected,materials[index]);identifier=str(uuid4())
    selected.custom_zatca_native_chain=identifier
    owner_key=native_dispatch.owner_key(selected.doctype,selected.name,'Production')
    with connection.cursor() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabSingles` (`doctype` VARCHAR(140),`field` VARCHAR(140),`value` LONGTEXT,PRIMARY KEY(doctype,field)) ENGINE=InnoDB')
        cursor.executemany('INSERT IGNORE INTO `tabSingles` VALUES (%s,%s,%s)',control_rows('30000000-0000-4000-8000-000000000001'))
        for dt in ('Company','ZATCA Multiple Setting'):
            cursor.execute('CREATE TABLE IF NOT EXISTS `tab'+dt+'` (name VARCHAR(140) PRIMARY KEY,custom_pih VARCHAR(140),abbr VARCHAR(140),custom_send_invoice_to_zatca VARCHAR(140)) ENGINE=InnoDB')
        for doc in (b.company,b.linked,b.device):
            cursor.execute('INSERT INTO `tab'+doc.doctype+'` VALUES (%s,%s,%s,%s)',(doc.name,INITIAL_PREVIOUS_HASH,doc.get('abbr'),doc.get('custom_send_invoice_to_zatca')))
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabCustomer` (name VARCHAR(140) PRIMARY KEY,custom_b2c INT) ENGINE=InnoDB')
        cursor.execute('INSERT INTO `tabCustomer` VALUES (%s,%s)',(customer.name,int(simplified)))
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabFile` (name VARCHAR(140) PRIMARY KEY,attached_to_doctype VARCHAR(140),attached_to_name VARCHAR(140),file_name VARCHAR(255)) ENGINE=InnoDB')
        cursor.execute('CREATE TABLE IF NOT EXISTS `tab'+doctype+'` (name VARCHAR(140) PRIMARY KEY,docstatus INT,company VARCHAR(140),'
            'custom_uuid VARCHAR(140),custom_zatca_icv VARCHAR(140),custom_zatca_issuing_unit VARCHAR(140),'
            'custom_zatca_status VARCHAR(140),custom_zatca_full_response LONGTEXT) ENGINE=InnoDB')
        cursor.execute('INSERT INTO `tab'+doctype+'` (name,docstatus,company) VALUES (%s,1,%s)',(source.name,source.company))
        cursor.execute('INSERT INTO `tabZATCA Issuing Chain` (name,record_id,owner_key,active_owner_key,owner_doctype,owner_name,environment,'
            'seller_tax_id,registration_kind,registration_evidence_sha256,certificate_sha256,public_key_sha256,last_icv,previous_hash,state_version,active) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,1)',
            (identifier,identifier,owner_key,owner_key,selected.doctype,selected.name,'Production','TEST-VAT','NEW_EGS','e'*64,
             chain['certificate_sha256'],chain['public_key_sha256'],'0',INITIAL_PREVIOUS_HASH))
    connection.commit()
    docs={(doc.doctype,doc.name):doc for doc in (b.company,b.linked,b.device,source,customer)}
    def get_doc(dt,name,**kwargs):
        if dt=='Company' and type(name) is dict:
            assert name=={'abbr':'TC'};name=b.company.name
        suffix=' FOR UPDATE NOWAIT' if kwargs.get('for_update') else ''
        rows=runtime.db.sql('SELECT * FROM `tab'+dt+'` WHERE name=%s'+suffix,(name,),as_dict=True)
        return Document(**(vars(docs[dt,name])|dict(rows[0])))
    runtime.get_doc=get_doc
    for component in {*(route[0] for route in ROUTES[:6]),api_settings,credential_settings,sign_invoice_first,submission_context,primary_qr_attachment}:
        monkeypatch.setattr(component,'frappe',runtime)
        if hasattr(component,'_'):monkeypatch.setattr(component,'_',lambda text:text)
    monkeypatch.setattr(field_compat,'frappe',runtime)
    monkeypatch.setattr(delivery,'get_alias_value',lambda group,doc,default:doc.get('custom_b2c',default))
    monkeypatch.setattr(delivery,'now_datetime',lambda:datetime(2026,11,19,10))
    from zatca_erpgulf.zatca_erpgulf import sign_invoice
    monkeypatch.setattr(sign_invoice,'_onboarding_address',lambda *args:Document(address_line1='Test Street',
        address_line2='District',city='Riyadh',custom_building_number='1234',pincode='12345',state=''))
    # Only the public framework typing decorator is removed for site-free calls.
    for route_module,route_fn,*_ in ROUTES[:6]:
        monkeypatch.setattr(route_module,route_fn,inspect.unwrap(getattr(route_module,route_fn)))
    api=(module.clearance_api if not simplified else
        getattr(module,'reporting_api',None) or getattr(module,'reporting_api_sales_withoutxml',None) or module.reporting_api_pos_without_xml)
    built=[]
    def metadata(root,invoice_number,**kwargs):
        assert invoice_number==source.name;built.append(invoice_number)
        signed_build(b,runtime.get_doc(doctype,source.name),validation_type='Simplified Invoice' if simplified else 'Standard Invoice',
            endpoint='invoices/reporting/single' if simplified else 'invoices/clearance/single',api=api)
        pytest.fail('Native handoff was not raised')
    monkeypatch.setattr(module,'prepare_invoice_generation',metadata)
    database.exists=lambda dt,name:bool(database.sql('SELECT name FROM `tab'+dt+'` WHERE name=%s',(name,),as_dict=True))
    sent=[]
    def send(prepared,**kwargs):
        observer=connections()
        with observer.cursor() as cursor:
            cursor.execute('SELECT last_icv FROM `tabZATCA Issuing Chain` WHERE name=%s FOR UPDATE NOWAIT',(identifier,))
            assert cursor.fetchone()==('1',)
        observer.rollback()
        sent.append(prepared.body)
        clearing=prepared.url.endswith('invoices/clearance/single')
        body=b'Clearance disabled' if clearing else b'{"validationResults":{"status":"PASS","errorMessages":[],"warningMessages":[],"infoMessages":[]},"reportingStatus":"REPORTED"}'
        return SimpleNamespace(request=prepared,url=prepared.url,history=[],status_code=303 if clearing else 200,
            headers=CaseInsensitiveDict({'x-request-id':'SYNTHETIC'}),close=Mock(),raw=SimpleNamespace(read1=Mock(side_effect=[body,b''])))
    adapter=SimpleNamespace(send=Mock(side_effect=send),close=Mock())
    monkeypatch.setattr(native_transport,'HTTPAdapter',lambda **kwargs:adapter)
    def run():return getattr(module,fn)(source.name)
    def head():return database.sql('SELECT last_icv FROM `tabZATCA Issuing Chain` WHERE name=%s',(identifier,),as_dict=True)[0]['last_icv']
    return SimpleNamespace(b=b,runtime=runtime,database=database,connection=connection,source=source,company=b.company,
        selected=selected,customer=customer,module=module,fn=fn,run=run,head=head,built=built,sent=sent,adapter=adapter,identifier=identifier,connections=connections)


@pytest.mark.parametrize('case',[(n,kind,'Live',True) for n in range(6) for kind in ('company','device','linked')
    if not (n in (2,4) and kind=='company')],indirect=True)
def test_all_six_entries_use_owned_custody_and_cached_acceptance_with_current_key_loss(case):
    c=case;first=c.run()
    assert first['accepted'] and len(c.sent)==1 and len(c.built)==1 and c.head()=='1'
    c.selected.custom_private_key='INVALID'
    again=c.run()
    assert again['accepted'] and again['reused'] and len(c.sent)==1 and len(c.built)==1 and c.head()=='1'
    c.b.request.assert_not_called()


@pytest.mark.parametrize('case',[(0,'company','Batches',True),(1,'device','Background',True)],indirect=True)
def test_hold_then_explicit_manual_send_reuses_exact_generated_bytes(case):
    c=case;prepared=c.run()
    assert prepared['status']=='PREPARED' and not prepared['accepted'] and not c.sent and c.head()=='1'
    saved=c.runtime.get_doc(c.source.doctype,c.source.name)
    assert saved.custom_zatca_status=='Not Submitted' and saved.custom_zatca_full_response==''
    repeat=c.run();assert repeat['reused'] and len(c.built)==1
    result=provider.maybe_process_native_invoice(c.source.doctype,c.source.name,runtime=c.runtime,translate=lambda text:text,
        build=lambda locked:getattr(c.module,c.fn)(locked.name),intent='manual')
    assert result['accepted'] and len(c.sent)==1 and len(c.built)==1 and c.head()=='1'


@pytest.mark.parametrize('case',[(0,'company','Batches',False),(1,'device','Background',False)],indirect=True)
def test_standard_remains_immediate_and_keeps_the_bound303_fallback(case):
    c=case;result=c.run()
    assert result['accepted'] and len(c.sent)==2 and c.sent[0]==c.sent[1] and c.head()=='1'


def test_an_existing_unowned_xml_is_reviewed_before_generation(case):
    c=case
    with c.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabFile` VALUES (%s,%s,%s,%s)',('FILE-'+c.identifier,c.source.doctype,c.source.name,'Original.xml'))
    c.connection.commit()
    with pytest.raises(provider.NativeProviderError):c.run()
    assert not c.built and not c.sent and c.head()=='0'


@pytest.mark.parametrize('filename,allowed',[('DEBUG_invoice.xml',True),('DEBUGXinvoice.xml',False)])
def test_only_the_literal_debug_prefix_is_excluded_from_fiscal_artifact_ambiguity(case,filename,allowed):
    c=case
    with c.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabFile` VALUES (%s,%s,%s,%s)',('FILE-'+c.identifier,c.source.doctype,c.source.name,filename))
    c.connection.commit()
    if allowed:
        assert c.run()['accepted']
    else:
        with pytest.raises(provider.NativeProviderError):c.run()
        assert not c.sent and c.head()=='0'


@pytest.mark.parametrize('case',[(2,'company','Live',True),(4,'company','Live',True)],indirect=True)
def test_unit_specific_entries_keep_their_saved_device_requirement(case):
    c=case
    with pytest.raises(provider.NativeProviderError):c.run()
    assert not c.sent and c.head()=='0'


@pytest.mark.parametrize('stage',['before_prepare','before_reservation'])
def test_current_company_method_change_cannot_send_against_an_earlier_policy(case,monkeypatch,stage):
    c=case
    target=provider if stage=='before_prepare' else native_dispatch
    name='dispatch_saved_invoice' if stage=='before_prepare' else 'reserve_saved_issuance'
    operation=getattr(target,name)
    def changed(*args,**kwargs):
        other=c.connections()
        with other.cursor() as cursor:
            cursor.execute('UPDATE `tabCompany` SET custom_send_invoice_to_zatca=%s WHERE name=%s',('Batches',c.company.name))
        other.commit()
        return operation(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(target,name,changed)
        with pytest.raises(provider.NativeProviderError) as failed:c.run()
    assert failed.value.code in ('native_delivery_policy_changed','issuing_settings_changed')
    assert not c.sent and c.head()==('0' if stage=='before_prepare' else '1')
    assert c.run()['status']=='PREPARED' and c.head()=='1'
