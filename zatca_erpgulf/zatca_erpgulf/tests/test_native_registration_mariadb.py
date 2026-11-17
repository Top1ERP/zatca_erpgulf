"""Real owned review/cipher/SQL/private file reads; no installed ERP or API."""

import base64
import hashlib
import json
import os
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_registration as registration
from zatca_erpgulf.zatca_erpgulf import api_settings, credential_settings, sign_invoice, sign_invoice_first, submission_context
from zatca_erpgulf.zatca_erpgulf.dispatch_store import DispatchStoreError
from zatca_erpgulf.zatca_erpgulf.icv import _counter_key
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import issuing_attempt
from zatca_erpgulf.zatca_erpgulf.native_preparation import native_preparation, PreparedRequestHandoff
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import boundary, materials, setup
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import signed_build
from zatca_erpgulf.zatca_erpgulf.tests.test_native_preparation import registration as chain_values
from zatca_erpgulf.zatca_erpgulf.tests.test_native_owned_pipeline_mariadb import OwnedDatabase, Runtime
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch_store_mariadb import isolated_server, connections, tables, NAMESPACE


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')
REASON='Reviewed last generated original and counter; pending cutover acceptance.'


@pytest.fixture
def legacy(boundary,materials,monkeypatch,connections,tables,tmp_path,request):
    b=boundary
    parameters=getattr(request,'param',('company',0))
    kind,index=parameters[:2]
    value=parameters[2] if len(parameters)>2 else '27'
    source_kind=parameters[3] if len(parameters)>3 else 'sales'
    validation_type=parameters[4] if len(parameters)>4 else 'Simplified Invoice'
    selected=setup(b,monkeypatch,kind)
    suffix='-'+str(uuid4())[:8]
    for doc in (b.company,b.linked,b.device,b.sales,b.pos):doc.name+=suffix
    b.device.custom_linked_doctype=b.linked.name if kind=='linked' else b.company.name
    for source in (b.sales,b.pos):
        source.company=b.company.name;source.docstatus=1
        source.custom_zatca_pos_name=None if kind=='company' else b.device.name
        source.save=Mock();source.db_set=Mock()
    b.company.custom_zatca_invoice_enabled=1;b.company.custom_phase_1_or_2='Phase-2';b.company.company_name='Synthetic issuer'
    prototypes={(doc.doctype,doc.name):doc for doc in (b.company,b.linked,b.device,b.sales,b.pos)}
    def original(doctype,name,**kwargs):
        if doctype=='Company' and type(name) is dict:
            assert name=={'abbr':'TC'};name=b.company.name
        return prototypes[doctype,name]
    b.frappe.get_doc.side_effect=original
    b.frappe.has_permission=lambda doctype,operation,*,doc,user,raise_exception=True:True
    b.frappe.local=SimpleNamespace(site='fictional.invalid')
    monkeypatch.setattr(sign_invoice,'_onboarding_address',lambda *args:Document(
        address_line1='Test Street',address_line2='District',city='Riyadh',custom_building_number='1234',pincode='12345',state=''))
    source=getattr(b,source_kind)
    chain=chain_values(b,selected,materials[index]);chain['last_icv']=str(int(value)-1)
    with pytest.raises(PreparedRequestHandoff) as ready:
        with native_preparation(b.frappe,source_identity=(source.doctype,source.name),company_name=b.company.name,
                chain=chain,invoice_uuid=str(uuid4()),owner_check=lambda:True):
            with issuing_attempt('TC',source,purpose='production',runtime=b.frappe,translate=lambda text:text,invoice_doc=source):
                signed_build(b,source,validation_type=validation_type,
                    endpoint='invoices/clearance/single' if validation_type=='Standard Invoice' else 'invoices/reporting/single')
    packet=ready.value.packet;xml=base64.b64decode(json.loads(packet.request_bytes)['invoice'])
    source.custom_uuid=packet.invoice_uuid;source.custom_zatca_icv=value
    source.custom_zatca_issuing_unit=('company:' if kind=='company' else 'setting:')+hashlib.sha256(suffix.encode()).hexdigest()[:24]
    selected.custom_pih=packet.invoice_hash
    counter_name=_counter_key(source.company,source.custom_zatca_issuing_unit,'Production')
    selected.custom_zatca_icv_counter=counter_name
    file_id='FILE'+suffix
    file_doc=Document(doctype='File',name=file_id,attached_to_doctype=source.doctype,attached_to_name=source.name,
        is_private=1,file_name='Original'+suffix+'.xml',file_url='/private/files/Original'+suffix+'.xml')
    counter=Document(doctype='ZATCA ICV Counter',name=counter_name,company=source.company,
        issuing_unit=source.custom_zatca_issuing_unit,environment='Production',counter_key=counter_name,active=1,
        last_issued_icv=value,last_invoice=source.name,last_invoice_doctype=source.doctype)
    prototypes.update({('File',file_id):file_doc,('ZATCA ICV Counter',counter_name):counter})
    folder=tmp_path/'private'/'files';folder.mkdir(parents=True)
    path=folder/file_doc.file_name;path.write_bytes(xml)
    connection=connections();database=OwnedDatabase(connection);runtime=Runtime(b.frappe,database)
    runtime.get_roles=lambda actor:['System Manager']
    runtime.get_site_path=lambda *parts:str(tmp_path.joinpath(*parts))
    for module in (api_settings,credential_settings,sign_invoice,sign_invoice_first,submission_context):
        monkeypatch.setattr(module,'frappe',runtime)
    with connection.cursor() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabSingles` (`doctype` VARCHAR(140),`field` VARCHAR(140),`value` LONGTEXT,PRIMARY KEY(doctype,field)) ENGINE=InnoDB')
        cursor.executemany('INSERT IGNORE INTO `tabSingles` VALUES (%s,%s,%s)',[
            ('ZATCA Dispatch Control','storage_namespace',NAMESPACE),('ZATCA Dispatch Control','storage_version','1')])
        columns={'Company':{'custom_pih':'VARCHAR(140)'},'ZATCA Multiple Setting':{'custom_pih':'VARCHAR(140)'},
            'Sales Invoice':{'company':'VARCHAR(140)','docstatus':'INT','custom_uuid':'VARCHAR(140)',
                'custom_zatca_icv':'VARCHAR(140)','custom_zatca_issuing_unit':'VARCHAR(140)'},
            'File':{key:('INT' if key=='is_private' else 'VARCHAR(140)') for key in (
                'attached_to_doctype','attached_to_name','is_private','file_name','file_url')},
            'ZATCA ICV Counter':{key:('INT' if key=='active' else 'VARCHAR(140)') for key in (
                'company','issuing_unit','environment','counter_key','active','last_issued_icv','last_invoice','last_invoice_doctype')}}
        columns['POS Invoice']=columns['Sales Invoice']
        for doctype,fields in columns.items():
            cursor.execute('CREATE TABLE IF NOT EXISTS `tab'+doctype+'` (`name` VARCHAR(140) PRIMARY KEY,'+
                ','.join('`'+key+'` '+kind for key,kind in fields.items())+') ENGINE=InnoDB')
        for (doctype,name),document in prototypes.items():
            keys=('name',*columns[doctype])
            cursor.execute('INSERT INTO `tab'+doctype+'` ('+','.join('`'+key+'`' for key in keys)+
                ') VALUES ('+','.join('%s' for key in keys)+')',tuple(document.get(key) for key in keys))
    connection.commit()
    def saved(doctype,name,**kwargs):
        if doctype=='Company' and type(name) is dict:
            assert name=={'abbr':'TC'};name=b.company.name
        suffix=' FOR UPDATE NOWAIT' if kwargs.get('for_update') else ''
        row=runtime.db.sql('SELECT * FROM `tab'+doctype+'` WHERE name=%s'+suffix,(name,),as_dict=True)[0]
        return Document(**(vars(prototypes[doctype,name])|dict(row)))
    runtime.get_doc=saved
    def change(document,key,value):
        setattr(document,key,value)
        if key in columns[document.doctype]:
            with connection.cursor() as cursor:
                cursor.execute('UPDATE `tab'+document.doctype+'` SET `'+key+'`=%s WHERE name=%s',(value,document.name))
            connection.commit()
    def review(**overrides):
        options=dict(runtime=runtime,translate=lambda text:text,reason=REASON,
            expected_xml_sha256=hashlib.sha256(xml).hexdigest())
        options.update(overrides)
        return registration.review_legacy_registration(source.doctype,source.name,counter_name,file_id,
            **options)
    return SimpleNamespace(b=b,runtime=runtime,database=database,source=source,selected=selected,counter=counter,
        file_doc=file_doc,path=path,xml=xml,review=review,connection=connection,connections=connections,change=change,
        prototypes=prototypes)


@pytest.mark.parametrize('legacy',[(kind,index,'27',source_kind,validation_type)
    for kind,index in [('company',0),('device',2),('linked',1)] for source_kind in ['sales','pos']
    for validation_type in ['Simplified Invoice','Standard Invoice']],indirect=True)
def test_review_commits_encrypted_inactive_anchor_without_invoice_or_counter_writes(legacy):
    t=legacy
    reviewed=t.review()
    assert reviewed.last_icv=='27' and not reviewed.active and not reviewed.reused
    row=t.database.sql('SELECT active,active_owner_key,last_icv,previous_hash,registration_kind,registration_header,registration_ciphertext '
        'FROM `tabZATCA Issuing Chain` WHERE name=%s',(reviewed.record_id,),as_dict=True)[0]
    assert row['active']==0 and row['active_owner_key'] is None
    assert row['last_icv']=='27' and row['previous_hash']==t.selected.custom_pih and row['registration_kind']=='LEGACY_REVIEWED'
    assert 'Invoice' not in row['registration_ciphertext'] and REASON not in row['registration_header']
    assert t.database.commits==1 and t.counter.active==1 and t.counter.last_issued_icv=='27'
    for source in (t.source,t.selected):source.save.assert_not_called();source.db_set.assert_not_called()
    # Lost acknowledgment recovery reuses exact custody, not a second chain.
    again=t.review()
    assert again.reused and again.record_id==reviewed.record_id and t.database.commits==1
    t.b.request.assert_not_called()


@pytest.mark.parametrize('fault',['role','owner_write','source_read','counter_read','file_read','missing_icv',
    'float_icv','wrong_tail','wrong_pih','wrong_uuid','changed_file','public_file','foreign_file','draft','pointer'])
def test_missing_or_inconsistent_evidence_never_falls_back_to_genesis(legacy,fault):
    t=legacy
    if fault=='role':t.runtime.get_roles=lambda actor:['Accounts Manager']
    elif fault in ('owner_write','source_read','counter_read','file_read'):
        denied={'owner_write':(t.selected.doctype,'write'),'source_read':(t.source.doctype,'read'),
            'counter_read':('ZATCA ICV Counter','read'),'file_read':('File','read')}[fault]
        t.runtime.has_permission=lambda doctype,operation,*,doc,user,raise_exception=True:(doctype,operation)!=denied
    elif fault=='missing_icv':t.change(t.counter,'last_issued_icv',None)
    elif fault=='float_icv':t.change(t.source,'custom_zatca_icv','27.0')
    elif fault=='wrong_tail':t.change(t.counter,'last_invoice','ANOTHER')
    elif fault=='wrong_pih':t.change(t.selected,'custom_pih',INITIAL_PREVIOUS_HASH)
    elif fault=='wrong_uuid':t.change(t.source,'custom_uuid',str(uuid4()))
    elif fault=='changed_file':t.path.write_bytes(t.xml+b' ')
    elif fault=='public_file':t.change(t.file_doc,'is_private',0)
    elif fault=='foreign_file':t.change(t.file_doc,'attached_to_name','ANOTHER')
    elif fault=='draft':t.change(t.source,'docstatus',0)
    else:t.selected.custom_zatca_icv_counter='ANOTHER'
    with pytest.raises(registration.ChainRegistrationError) as failed:
        t.review()
    codes={'role':'registration_manager_required','owner_write':'registration_source_permission',
        'source_read':'native_source_permission','counter_read':'registration_source_permission',
        'file_read':'registration_source_permission','missing_icv':'registration_counter_precision',
        'float_icv':'dispatch_counter_shape','wrong_tail':'registration_counter_binding',
        'wrong_pih':'registration_generated_head_mismatch','wrong_uuid':'registration_generated_head_mismatch',
        'changed_file':'registration_reviewed_file_changed','public_file':'attachment_not_private',
        'foreign_file':'attachment_owner','draft':'registration_generated_source_review',
        'pointer':'registration_counter_pointer_mismatch'}
    assert failed.value.code==codes[fault]
    assert failed.value.__context__ is None
    assert t.database.commits==0
    assert t.database.sql('SELECT COUNT(*) AS n FROM `tabZATCA Issuing Chain` WHERE owner_name=%s',
        (t.selected.name,),as_dict=True)[0]['n']==0
    t.b.request.assert_not_called()


def test_same_legacy_unit_in_two_companies_is_ambiguous_not_a_maximum_seed(legacy):
    t=legacy
    with t.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabZATCA ICV Counter` (name,company,issuing_unit,environment,active,last_issued_icv) '
            'VALUES (%s,%s,%s,%s,1,%s)',('DUP-'+str(uuid4()),'OTHER',t.source.custom_zatca_issuing_unit,'Production','999'))
    t.connection.commit()
    with pytest.raises(registration.ChainRegistrationError,match='registration_counter_ambiguous'):
        t.review()
    assert t.database.commits==0 and t.counter.last_issued_icv=='27'


def test_lost_review_commit_acknowledgment_recovers_one_inactive_record(legacy,monkeypatch):
    t=legacy
    commit=t.database.commit
    def unknown():
        commit()
        raise RuntimeError('PRIVATE-LOST-COMMIT-ACK')
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'commit',unknown)
        with pytest.raises(registration.ChainRegistrationError) as failed:t.review()
    assert failed.value.code=='registration_commit_unknown' and failed.value.commit_uncertain
    assert failed.value.__context__ is None and 'PRIVATE' not in str(failed.value)
    recovered=t.review()
    assert recovered.reused and not recovered.active and t.database.commits==1
    assert t.database.sql('SELECT COUNT(*) AS n FROM `tabZATCA Issuing Chain` WHERE owner_name=%s',
        (t.selected.name,),as_dict=True)[0]['n']==1


def test_partial_insert_failure_rolls_back_without_source_repair(legacy,monkeypatch):
    t=legacy;sql=t.database.sql
    def broken(statement,values=(),**kwargs):
        result=sql(statement,values,**kwargs)
        if statement.startswith('INSERT INTO `tabZATCA Issuing Chain`'):
            raise RuntimeError('PRIVATE-DRIVER-DIAGNOSTIC')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'sql',broken)
        with pytest.raises(registration.ChainRegistrationError,match='dispatch_store_operation_failed') as failed:t.review()
    assert failed.value.__context__ is None and not failed.value.commit_uncertain and t.database.commits==0
    with t.connections().cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM `tabZATCA Issuing Chain` WHERE owner_name=%s',(t.selected.name,))
        assert cursor.fetchone()==(0,)
    assert t.counter.last_issued_icv=='27'


@pytest.mark.parametrize('fault',['header','ciphertext','evidence_hash'])
def test_tampering_with_retained_review_never_replaces_it_or_activates_it(legacy,fault):
    t=legacy;reviewed=t.review()
    column={'header':'registration_header','ciphertext':'registration_ciphertext','evidence_hash':'registration_evidence_sha256'}[fault]
    with t.connection.cursor() as cursor:
        if fault=='header':
            cursor.execute('SELECT registration_header FROM `tabZATCA Issuing Chain` WHERE name=%s',(reviewed.record_id,))
            header=json.loads(cursor.fetchone()[0]);header['owner_name']='OTHER'
            value=json.dumps(header,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        else:value='0'*64 if fault=='evidence_hash' else 'v1.PRIVATE-INVALID'
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET `'+column+'`=%s WHERE name=%s',(value,reviewed.record_id))
    t.connection.commit()
    with pytest.raises(registration.ChainRegistrationError):t.review()
    assert t.database.commits==1
    row=t.database.sql('SELECT active,last_icv FROM `tabZATCA Issuing Chain` WHERE name=%s',(reviewed.record_id,),as_dict=True)[0]
    assert row==dict(active=0,last_icv='27')


def test_unknown_permission_signature_is_a_static_review_without_fallback(legacy):
    t=legacy;t.runtime.has_permission=lambda *args,**kwargs:True
    with pytest.raises(registration.ChainRegistrationError,match='permission_engine_signature') as failed:t.review()
    assert failed.value.__context__ is None and t.database.commits==0


@pytest.mark.parametrize('legacy',[('company',0,'9007199254740993')],indirect=True)
def test_large_counter_keeps_exact_digits_without_a_float_or_zero_seed(legacy):
    t=legacy;reviewed=t.review()
    assert reviewed.last_icv=='9007199254740993'
    row=t.database.sql('SELECT last_icv,active FROM `tabZATCA Issuing Chain` WHERE name=%s',
        (reviewed.record_id,),as_dict=True)[0]
    assert row==dict(last_icv='9007199254740993',active=0)


def test_inactive_review_cannot_reserve_an_active_dispatch_slot(legacy):
    from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction
    from zatca_erpgulf.zatca_erpgulf.dispatch_store import DispatchStore
    from zatca_erpgulf.zatca_erpgulf.native_dispatch import owner_key
    t=legacy;t.review()
    with owned_worker_transaction(t.runtime) as owner:
        repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        with pytest.raises(DispatchStoreError,match='dispatch_registration_required'):
            repository.lock_active_chain(owner_key(t.selected.doctype,t.selected.name,'Production'))
    assert t.database.commits==1
    t.b.request.assert_not_called()


def test_a_new_reason_or_fingerprint_does_not_overwrite_an_existing_review(legacy):
    t=legacy;reviewed=t.review()
    with pytest.raises(registration.ChainRegistrationError,match='registration_review_changed'):
        registration.review_legacy_registration(t.source.doctype,t.source.name,t.counter.name,t.file_doc.name,
            runtime=t.runtime,translate=lambda text:text,reason='A different review',
            expected_xml_sha256=hashlib.sha256(t.xml).hexdigest())
    assert t.database.commits==1
    assert t.database.sql('SELECT active,last_icv FROM `tabZATCA Issuing Chain` WHERE name=%s',
        (reviewed.record_id,),as_dict=True)[0]==dict(active=0,last_icv='27')


def test_current_credential_rotation_does_not_silently_adopt_an_old_certificate(legacy,materials):
    t=legacy;material=materials[1]
    t.selected.custom_certificate=material.text;t.selected.custom_private_key=material.pem
    token=base64.b64encode(material.text.encode())
    field='custom_final_auth_csid' if t.selected.doctype=='ZATCA Multiple Setting' else 'custom_basic_auth_from_production'
    setattr(t.selected,field,base64.b64encode(token+b':TEST-ONLY-SECRET').decode())
    with pytest.raises(registration.ChainRegistrationError,match='registration_certificate_review'):
        t.review()
    assert t.database.commits==0


def test_a_cancelled_legacy_source_does_not_erase_its_generated_chain_position(legacy):
    t=legacy;t.change(t.source,'docstatus',2)
    review=t.review()
    assert review.last_icv=='27' and not review.active
    assert t.runtime.get_doc(t.source.doctype,t.source.name).docstatus==2


def test_explicit_rereview_preserves_older_evidence_and_has_one_current_slot(legacy):
    from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction
    from zatca_erpgulf.zatca_erpgulf.dispatch_store import DispatchStore
    t=legacy;first=t.review()
    refreshed=t.review(reason='Fresh explicit review',supersedes_review_id=first.record_id)
    assert refreshed.record_id!=first.record_id and not refreshed.reused and not refreshed.active
    rows=t.database.sql('SELECT name,registration_review_key,state_version,active,last_icv FROM `tabZATCA Issuing Chain` '
        'WHERE owner_name=%s ORDER BY state_version',(t.selected.name,),as_dict=True)
    assert len(rows)==2 and all(row['active']==0 and row['last_icv']=='27' for row in rows)
    assert rows[0]['registration_review_key'] and rows[0]['state_version']==0
    assert rows[1]['registration_review_key'] is None and rows[1]['state_version']==1
    # Repeating the exact supersession command is recovery, not another version.
    again=t.review(reason='Fresh explicit review',supersedes_review_id=first.record_id)
    assert again.reused and again.record_id==refreshed.record_id and t.database.commits==2
    with owned_worker_transaction(t.runtime) as owner:
        repo=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        old=repo.lock_chain_reference(first.record_id)
        header,xml,reason=repo.open_reviewed_registration(old)
        assert xml==t.xml and reason==REASON and header['supersedes_review'] is None


def test_failed_supersession_rolls_back_slot_change_and_new_record_together(legacy,monkeypatch):
    t=legacy;first=t.review();sql=t.database.sql
    def broken(statement,values=(),**kwargs):
        result=sql(statement,values,**kwargs)
        if statement.startswith('INSERT INTO `tabZATCA Issuing Chain`'):
            raise RuntimeError('PRIVATE-INSERT-FAILURE')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'sql',broken)
        with pytest.raises(registration.ChainRegistrationError,match='dispatch_store_operation_failed'):
            t.review(reason='Fresh explicit review',supersedes_review_id=first.record_id)
    assert t.database.commits==1
    row=t.database.sql('SELECT state_version,registration_review_key FROM `tabZATCA Issuing Chain` WHERE name=%s',
        (first.record_id,),as_dict=True)[0]
    assert row['state_version']==0 and row['registration_review_key']
    assert t.review().record_id==first.record_id


def test_missing_current_slot_is_history_to_review_not_permission_to_start_again(legacy):
    t=legacy;first=t.review()
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET registration_review_key=NULL,state_version=1 WHERE name=%s',
            (first.record_id,))
    t.connection.commit()
    with pytest.raises(registration.ChainRegistrationError,match='dispatch_registration_history_review'):
        t.review()
    assert t.database.commits==1


def test_a_later_generated_invoice_requires_a_new_explicit_review(legacy,materials):
    t=legacy;first=t.review()
    next_source=Document(**(vars(t.source)|dict(name=t.source.name+'-NEXT',custom_uuid=str(uuid4()),custom_zatca_icv='28')))
    t.prototypes[next_source.doctype,next_source.name]=next_source
    with t.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabSales Invoice` (name,company,docstatus,custom_uuid,custom_zatca_icv,custom_zatca_issuing_unit) '
            'VALUES (%s,%s,1,%s,%s,%s)',(next_source.name,next_source.company,next_source.custom_uuid,'28',next_source.custom_zatca_issuing_unit))
    t.connection.commit()
    chain=chain_values(t.b,t.selected,materials[0])
    chain.update(last_icv='27',previous_hash=t.selected.custom_pih)
    t.b.frappe=t.runtime
    with pytest.raises(PreparedRequestHandoff) as ready:
        with native_preparation(t.runtime,source_identity=(next_source.doctype,next_source.name),company_name=t.b.company.name,
                chain=chain,invoice_uuid=next_source.custom_uuid,owner_check=lambda:True):
            with issuing_attempt('TC',next_source,purpose='production',runtime=t.runtime,
                    translate=lambda text:text,invoice_doc=next_source):
                signed_build(t.b,next_source)
    packet=ready.value.packet
    xml=base64.b64decode(json.loads(packet.request_bytes)['invoice'])
    file_id='NEXT-'+str(uuid4())
    file_doc=Document(doctype='File',name=file_id,attached_to_doctype=next_source.doctype,attached_to_name=next_source.name,
        is_private=1,file_name=file_id+'.xml',file_url='/private/files/'+file_id+'.xml')
    (t.path.parent/file_doc.file_name).write_bytes(xml)
    t.prototypes['File',file_id]=file_doc
    with t.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabFile` (name,attached_to_doctype,attached_to_name,is_private,file_name,file_url) '
            'VALUES (%s,%s,%s,1,%s,%s)',(file_id,next_source.doctype,next_source.name,file_doc.file_name,file_doc.file_url))
        cursor.execute('UPDATE `tabZATCA ICV Counter` SET last_issued_icv=%s,last_invoice=%s WHERE name=%s',
            ('28',next_source.name,t.counter.name))
    t.connection.commit()
    t.change(t.selected,'custom_pih',packet.invoice_hash)
    arguments=dict(runtime=t.runtime,translate=lambda text:text,reason='Reviewed later generated anchor',
        expected_xml_sha256=hashlib.sha256(xml).hexdigest())
    with pytest.raises(registration.ChainRegistrationError,match='registration_review_changed'):
        registration.review_legacy_registration(next_source.doctype,next_source.name,t.counter.name,file_id,**arguments)
    second=registration.review_legacy_registration(next_source.doctype,next_source.name,t.counter.name,file_id,
        supersedes_review_id=first.record_id,**arguments)
    assert second.last_icv=='28' and not second.active and t.database.commits==2
    assert t.runtime.get_doc(t.source.doctype,t.source.name).custom_zatca_icv=='27'
    assert t.database.sql('SELECT last_icv FROM `tabZATCA Issuing Chain` WHERE name=%s',
        (first.record_id,),as_dict=True)[0]['last_icv']=='27'


def test_lost_supersession_acknowledgment_recovers_the_new_current_review(legacy,monkeypatch):
    t=legacy;first=t.review();commit=t.database.commit
    def unknown():
        commit()
        raise RuntimeError('PRIVATE-ACK-LOST')
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'commit',unknown)
        with pytest.raises(registration.ChainRegistrationError) as failed:
            t.review(reason='Fresh explicit review',supersedes_review_id=first.record_id)
    assert failed.value.commit_uncertain and failed.value.code=='registration_commit_unknown'
    recovered=t.review(reason='Fresh explicit review',supersedes_review_id=first.record_id)
    assert recovered.reused and recovered.record_id!=first.record_id and not recovered.active
    assert t.database.commits==2
    assert t.database.sql('SELECT COUNT(*) AS n FROM `tabZATCA Issuing Chain` WHERE owner_name=%s',
        (t.selected.name,),as_dict=True)[0]['n']==2


def test_wrong_prior_review_cannot_create_or_replace_a_candidate(legacy):
    t=legacy;first=t.review()
    with pytest.raises(registration.ChainRegistrationError,match='registration_review_changed'):
        t.review(supersedes_review_id=str(uuid4()))
    assert t.review().record_id==first.record_id and t.database.commits==1


def test_review_does_not_require_source_write_because_it_never_relinks_the_invoice(legacy):
    t=legacy
    t.runtime.has_permission=lambda doctype,operation,*,doc,user,raise_exception=True:(doctype,operation)!=(t.source.doctype,'write')
    assert not t.review().active
    t.source.save.assert_not_called();t.source.db_set.assert_not_called()
