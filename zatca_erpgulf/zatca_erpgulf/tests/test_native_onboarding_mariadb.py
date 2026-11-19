"""Owned CSR/key/intent persistence in fixture-owned SQL; no ERP site or API."""

import base64
import hashlib
import inspect
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from zatca_erpgulf.zatca_erpgulf import native_onboarding as onboarding, sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import boundary,materials,setup
from zatca_erpgulf.zatca_erpgulf.tests.test_native_owned_pipeline_mariadb import OwnedDatabase,Runtime
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch_store_mariadb import isolated_server,connections,tables,NAMESPACE
from zatca_erpgulf.zatca_erpgulf.tests.test_worker_transaction import control_rows


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')
CONFIG='''csr.common.name=SYNTHETIC-UNIT
csr.serial.number=1-TEST|2-TEST|3-SYNTHETIC
csr.organization.identifier=TEST-VAT
csr.organization.unit.name=SYNTHETIC-BRANCH
csr.organization.name=SYNTHETIC
csr.country.name=SA
csr.invoice.type=1100
csr.location.address=RIYADH
csr.industry.business.category=TEST'''


@pytest.fixture
def target(boundary,materials,monkeypatch,connections,tables,request):
    b=boundary;kind=getattr(request,'param','company');setup(b,monkeypatch,'company' if kind=='company' else 'device')
    suffix='-'+str(uuid4())[:8]
    for doc in (b.company,b.device):doc.name+=suffix
    b.device.custom_linked_doctype=b.company.name
    selected=b.company if kind=='company' else b.device
    serial='1-TEST|2-TEST|3-SYNTHETIC'+suffix
    configuration=CONFIG.replace('1-TEST|2-TEST|3-SYNTHETIC',serial)
    for doc in (b.company,b.device):
        for name in onboarding.PROTECTED_FIELDS:setattr(doc,name,None)
        doc.custom_csr_config=configuration;doc.custom_pih=None;doc.custom_zatca_icv_counter=None
        setattr(doc,onboarding.MARKER,None)
    connection=connections();database=OwnedDatabase(connection);runtime=Runtime(b.frappe,database)
    runtime.conf[onboarding.MODE]=1
    runtime.get_roles=lambda actor:['System Manager']
    runtime.has_permission=lambda doctype,operation,*,doc,user,raise_exception=True:True
    columns=tuple(dict.fromkeys((*onboarding.PROTECTED_FIELDS,onboarding.MARKER,'custom_csr_config','custom_pih',
        'custom_zatca_icv_counter','custom_linked_doctype','custom__use_company_certificate__keys','custom_otp','custom_select')))
    runtime.get_meta=lambda dt:SimpleNamespace(get_field=lambda name:SimpleNamespace(fieldtype='Data' if name==onboarding.MARKER else 'Long Text'),
        has_field=lambda name:name in columns)
    with connection.cursor() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabSingles` (`doctype` VARCHAR(140),`field` VARCHAR(140),`value` LONGTEXT,PRIMARY KEY(doctype,field)) ENGINE=InnoDB')
        cursor.executemany('INSERT IGNORE INTO `tabSingles` VALUES (%s,%s,%s)',control_rows(NAMESPACE))
        for doc in (b.company,b.device):
            cursor.execute('CREATE TABLE IF NOT EXISTS `tab'+doc.doctype+'` (`name` VARCHAR(140) PRIMARY KEY,'+
                ','.join('`'+name+'` '+('VARCHAR(140)' if name==onboarding.MARKER else 'LONGTEXT') for name in columns)+') ENGINE=InnoDB')
            cursor.execute('INSERT INTO `tab'+doc.doctype+'` (`name`,'+','.join('`'+name+'`' for name in columns)+') '
                'VALUES ('+','.join('%s' for _ in range(len(columns)+1))+')',(doc.name,*(doc.get(name) for name in columns)))
    connection.commit()
    prototypes={(doc.doctype,doc.name):doc for doc in (b.company,b.device)}
    def get_doc(doctype,name,**kwargs):
        if doctype=='Company' and type(name) is dict:
            assert name=={'abbr':'TC'};name=b.company.name
        suffix=' FOR UPDATE NOWAIT' if kwargs.get('for_update') else ''
        row=runtime.db.sql('SELECT * FROM `tab'+doctype+'` WHERE name=%s'+suffix,(name,),as_dict=True)[0]
        prototype=prototypes.get((doctype,name))
        return Document(**((vars(prototype) if prototype is not None else {'doctype':doctype})|dict(row)))
    runtime.get_doc=get_doc
    monkeypatch.setattr(client,'frappe',runtime);monkeypatch.setattr(client,'has_permission',runtime.has_permission)
    identity={'doctype':selected.doctype,'name':selected.name}
    def prepare():return onboarding.prepare_new_unit('TC',identity,'Production',runtime=runtime)
    return SimpleNamespace(b=b,runtime=runtime,database=database,selected=selected,identity=identity,prepare=prepare,
        connection=connection,connections=connections,serial=serial,configuration=configuration)


@pytest.mark.parametrize('target',['company','device'],indirect=True)
def test_csr_key_owner_marker_and_inactive_intent_commit_together(target):
    t=target;prepared=t.prepare()
    saved=t.runtime.get_doc(t.selected.doctype,t.selected.name)
    assert saved.get(onboarding.MARKER)==prepared.record_id and saved.custom_csr_data==prepared.csr_data
    csr=x509.load_pem_x509_csr(base64.b64decode(prepared.csr_data))
    key=serialization.load_pem_private_key(saved.custom_private_key.encode(),password=None)
    assert csr.is_signature_valid and csr.public_key().public_numbers()==key.public_key().public_numbers()
    row=t.database.sql('SELECT active,active_owner_key,last_icv,onboarding_state,onboarding_header,onboarding_ciphertext FROM '
        '`tabZATCA Issuing Chain` WHERE name=%s',(prepared.record_id,),as_dict=True)[0]
    assert row['active']==0 and row['active_owner_key'] is None and row['last_icv']=='0' and row['onboarding_state']=='CSR_READY'
    assert 'PRIVATE KEY' not in row['onboarding_ciphertext'] and 'PRIVATE KEY' not in row['onboarding_header']
    again=t.prepare()
    assert again.reused and again.record_id==prepared.record_id and again.csr_data==prepared.csr_data
    assert t.runtime.get_doc(t.selected.doctype,t.selected.name).custom_private_key==saved.custom_private_key
    assert t.database.commits==1
    t.b.request.assert_not_called()


def test_existing_csr_button_uses_owned_native_preparation_when_enabled(target):
    t=target
    encoded=inspect.unwrap(client.create_csr)(t.identity,'Production','TC')
    assert x509.load_pem_x509_csr(base64.b64decode(encoded)).is_signature_valid
    assert t.database.commits==1
    t.selected.save.assert_not_called()
    t.b.request.assert_not_called()
    assert inspect.unwrap(client.create_csr)(t.identity,'Production','TC')==encoded
    assert t.database.commits==1


def test_existing_csr_button_preserves_its_safe_error_when_the_commit_acknowledgment_is_lost(target,monkeypatch):
    t=target;commit=t.database.commit
    def unknown():
        commit()
        raise RuntimeError('PRIVATE-LOST-ACK')
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'commit',unknown)
        with pytest.raises(AssertionError,match='Native ZATCA onboarding could not be confirmed') as failed:
            inspect.unwrap(client.create_csr)(t.identity,'Production','TC')
    assert failed.value.__context__ is None
    saved=t.runtime.get_doc(t.selected.doctype,t.selected.name)
    assert inspect.unwrap(client.create_csr)(t.identity,'Production','TC')==saved.custom_csr_data
    assert t.database.commits==1


@pytest.mark.parametrize('field',onboarding.PROTECTED_FIELDS)
def test_unknown_or_existing_material_is_not_adopted_or_replaced(target,field):
    t=target
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tab'+t.selected.doctype+'` SET `'+field+'`=%s WHERE name=%s',('PRESENT',t.selected.name))
    t.connection.commit()
    with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_existing_material_review'):t.prepare()
    assert t.database.commits==0


def test_missing_namespace_does_not_generate_a_storage_key_or_an_intent(target):
    t=target
    with t.connection.cursor() as cursor:cursor.execute('DELETE FROM `tabSingles` WHERE doctype=%s',('ZATCA Dispatch Control',))
    t.connection.commit()
    with pytest.raises(onboarding.NativeOnboardingError):t.prepare()
    assert t.database.commits==0


def test_lost_commit_acknowledgment_recovers_the_same_key_and_csr(target,monkeypatch):
    t=target;commit=t.database.commit
    def unknown():
        commit()
        raise RuntimeError('PRIVATE-LOST-ACK')
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'commit',unknown)
        with pytest.raises(onboarding.NativeOnboardingError) as failed:t.prepare()
    assert failed.value.commit_uncertain and failed.value.__context__ is None
    saved=t.runtime.get_doc(t.selected.doctype,t.selected.name)
    recovered=t.prepare()
    assert recovered.reused and recovered.record_id==saved.get(onboarding.MARKER)
    assert recovered.csr_data==saved.custom_csr_data and t.database.commits==1


@pytest.mark.parametrize('stage',['intent','owner'])
def test_any_partial_write_is_rolled_back_without_leaving_an_orphan_key_or_intent(target,monkeypatch,stage):
    t=target;sql=t.database.sql
    def broken(statement,values=(),**kwargs):
        result=sql(statement,values,**kwargs)
        if stage=='intent' and statement.startswith('INSERT INTO `tabZATCA Issuing Chain`') or (
                stage=='owner' and statement.startswith('UPDATE `tab'+t.selected.doctype+'`')):
            raise RuntimeError('PRIVATE-WRITE-FAILURE')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'sql',broken)
        with pytest.raises(onboarding.NativeOnboardingError):t.prepare()
    saved=t.runtime.get_doc(t.selected.doctype,t.selected.name)
    assert saved.custom_private_key is None and saved.custom_csr_data is None and saved.get(onboarding.MARKER) is None
    assert t.database.commits==0
    assert t.database.sql('SELECT COUNT(*) AS n FROM `tabZATCA Issuing Chain` WHERE owner_name=%s',
        (t.selected.name,),as_dict=True)[0]['n']==0


@pytest.mark.parametrize('fault',['key','csr','config','certificate','history'])
def test_recovery_refuses_changed_material_instead_of_generating_another_key(target,fault):
    t=target;first=t.prepare()
    name,value={'key':('custom_private_key','INVALID-KEY'),'csr':('custom_csr_data','CHANGED-CSR'),
        'config':('custom_csr_config',t.configuration+'\n'),'certificate':('custom_certificate','UNRECORDED-CERT'),
        'history':('custom_pih','UNRECORDED-HASH')}[fault]
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tab'+t.selected.doctype+'` SET `'+name+'`=%s WHERE name=%s',(value,t.selected.name))
    t.connection.commit()
    with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_saved_material_review'):t.prepare()
    assert t.database.commits==1
    assert t.runtime.get_doc(t.selected.doctype,t.selected.name).get(onboarding.MARKER)==first.record_id


def test_crypto_callback_cannot_mix_one_config_with_another_saved_epoch(target,monkeypatch):
    t=target;keygen=onboarding.ec.generate_private_key
    def changed(*args,**kwargs):
        with t.connection.cursor() as cursor:
            cursor.execute('UPDATE `tab'+t.selected.doctype+'` SET custom_csr_config=%s WHERE name=%s',
                (t.configuration+'\n',t.selected.name))
        return keygen(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(onboarding.ec,'generate_private_key',changed)
        with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_source_changed'):t.prepare()
    assert t.database.commits==0
    assert t.runtime.get_doc(t.selected.doctype,t.selected.name).custom_csr_config==t.configuration


def test_disabled_mode_or_wrong_environment_cannot_create_an_intent(target):
    t=target;t.runtime.conf[onboarding.MODE]=0
    with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_disabled'):t.prepare()
    t.runtime.conf[onboarding.MODE]=1
    with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_environment'):
        onboarding.prepare_new_unit('TC',t.identity,'Sandbox',runtime=t.runtime)
    assert t.database.commits==0


@pytest.mark.parametrize('denied',['role','read','write','guest'])
def test_csr_preparation_requires_manager_and_saved_target_permissions_before_keygen(target,monkeypatch,denied):
    t=target
    if denied=='role':t.runtime.get_roles=lambda actor:[]
    elif denied=='guest':t.runtime.session.user='Guest'
    else:
        t.runtime.has_permission=lambda dt,operation,**kwargs:operation!=denied
    monkeypatch.setattr(onboarding.ec,'generate_private_key',lambda *a,**kw:pytest.fail('Unauthorized keygen'))
    with pytest.raises(onboarding.NativeOnboardingError):t.prepare()
    assert t.database.commits==0


@pytest.mark.parametrize('fault',['missing','fieldtype','character_capacity','byte_capacity'])
def test_saved_schema_must_hold_the_exact_key_csr_and_marker_without_truncation(target,monkeypatch,fault):
    t=target;sql=t.database.sql
    if fault=='fieldtype':
        t.runtime.get_meta=lambda dt:SimpleNamespace(get_field=lambda name:SimpleNamespace(fieldtype='Password'))
    else:
        def columns(statement,values=(),**kwargs):
            rows=sql(statement,values,**kwargs)
            if 'information_schema.columns' in statement:
                rows=[dict(row) for row in rows]
                if fault=='missing':rows.pop()
                else:rows[0]['max_chars' if fault=='character_capacity' else 'max_bytes']=1
            return rows
        monkeypatch.setattr(t.database,'sql',columns)
    with pytest.raises(onboarding.NativeOnboardingError):t.prepare()
    assert t.database.commits==0
    assert t.runtime.get_doc(t.selected.doctype,t.selected.name).custom_private_key is None


@pytest.mark.parametrize('target',['device'],indirect=True)
def test_a_device_using_company_keys_cannot_create_a_second_intent_for_the_shared_unit(target,monkeypatch):
    t=target
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Multiple Setting` SET custom__use_company_certificate__keys=%s WHERE name=%s',
            ('1',t.selected.name))
    t.connection.commit()
    monkeypatch.setattr(onboarding.ec,'generate_private_key',lambda *a,**kw:pytest.fail('Wrong-owner keygen'))
    with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_shared_owner'):t.prepare()
    assert t.database.commits==0


def test_another_owner_cannot_reserve_the_same_declared_unit_with_a_fresh_key(target):
    t=target;first=t.prepare()
    other={'doctype':t.b.device.doctype,'name':t.b.device.name}
    with pytest.raises(onboarding.NativeOnboardingError):
        onboarding.prepare_new_unit('TC',other,'Production',runtime=t.runtime)
    assert t.database.commits==1
    saved=t.runtime.get_doc(t.b.device.doctype,t.b.device.name)
    assert saved.get(onboarding.MARKER) is None and saved.custom_private_key is None
    rows=t.database.sql('SELECT name FROM `tabZATCA Issuing Chain` WHERE egs_identity_key=%s',
        (onboarding.egs_identity_key('Production','TEST-VAT',t.serial),),as_dict=True)
    assert len(rows)==1 and rows[0]['name']==first.record_id


def test_changed_or_missing_unit_reservation_is_review_not_a_new_initialization(target):
    t=target;first=t.prepare()
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET egs_identity_key=NULL WHERE name=%s',(first.record_id,))
    t.connection.commit()
    with pytest.raises(onboarding.NativeOnboardingError):t.prepare()
    assert t.database.commits==1
