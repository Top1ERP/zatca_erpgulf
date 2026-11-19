"""Initial storage setup on fixture-owned InnoDB, including v15 Singles shape."""

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import native_storage as storage
from zatca_erpgulf.zatca_erpgulf.dispatch_storage_context import CONTROL,CONTROL_FIELDS
from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction,WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_owned_pipeline_mariadb import OwnedDatabase,Runtime
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch_store_mariadb import isolated_server,connections,tables


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


def runtime_for(connection):
    original=SimpleNamespace(session=SimpleNamespace(user='test-manager'),get_roles=lambda actor:['System Manager'])
    runtime=Runtime(original,OwnedDatabase(connection))
    kinds=dict(zip(CONTROL_FIELDS,('Data','Int','Long Text')))
    runtime.get_meta=lambda doctype:SimpleNamespace(issingle=1,get_field=lambda name:SimpleNamespace(
        fieldtype=kinds[name],read_only=1))
    return runtime


@pytest.fixture
def clean(connections,tables):
    connection=connections()
    with connection.cursor() as cursor:
        # Match Frappe15: the (doctype,field) index is deliberately NOT unique.
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabSingles` (`doctype` VARCHAR(255),`field` VARCHAR(255),'
            '`value` LONGTEXT,KEY singles_doctype_field_index(doctype,field)) ENGINE=InnoDB')
        for table in storage.TABLES:cursor.execute('DELETE FROM `'+table+'`')
        cursor.execute('DELETE FROM `tabSingles`')
    connection.commit()
    runtime=runtime_for(connection)
    def rows():
        return runtime.db.sql('SELECT field,value FROM `tabSingles` WHERE doctype=%s ORDER BY field',(CONTROL,),as_dict=True)
    return SimpleNamespace(runtime=runtime,connection=connection,connections=connections,rows=rows)


def test_initial_namespace_probe_commit_and_reuse_do_not_modify_the_site_key(clean):
    t=clean;before=dict(t.runtime.conf)
    result=storage.initialize_native_storage(runtime=t.runtime)
    assert not result.reused and len(result.namespace)==36 and t.runtime.db.commits==1
    saved=t.rows();assert len(saved)==3 and {row['field'] for row in saved}==set(CONTROL_FIELDS)
    assert all(before['encryption_key']!=row['value'] for row in saved)
    with owned_worker_transaction(t.runtime) as owner:assert owner.storage_namespace==result.namespace
    again=storage.initialize_native_storage(runtime=t.runtime)
    assert again.reused and again.namespace==result.namespace and t.runtime.db.commits==1
    assert t.rows()==saved and t.runtime.conf==before


@pytest.mark.parametrize('key',[None,'','INVALID',base64.urlsafe_b64encode(b'X'*16).decode()])
def test_missing_or_invalid_site_key_never_creates_a_key_or_namespace(clean,key):
    t=clean;t.runtime.conf['encryption_key']=key
    with pytest.raises(storage.NativeStorageError):storage.initialize_native_storage(runtime=t.runtime)
    assert not t.rows() and t.runtime.conf['encryption_key']==key and t.runtime.db.commits==0


@pytest.mark.parametrize('table',storage.TABLES)
def test_orphan_custody_without_control_is_never_reinterpreted_as_empty_storage(clean,table):
    t=clean
    with t.connection.cursor() as cursor:cursor.execute('INSERT INTO `'+table+'` (name) VALUES (%s)',(str(uuid4()),))
    t.connection.commit()
    with pytest.raises(storage.NativeStorageError,match='orphan_records_review'):storage.initialize_native_storage(runtime=t.runtime)
    assert not t.rows() and t.runtime.db.commits==0


@pytest.mark.parametrize('fault',['partial','duplicate','unknown','version','probe','key','site'])
def test_partial_duplicate_corrupt_or_foreign_control_is_held_without_reset(clean,fault):
    t=clean;storage.initialize_native_storage(runtime=t.runtime)
    with t.connection.cursor() as cursor:
        if fault=='partial':cursor.execute('DELETE FROM `tabSingles` WHERE doctype=%s AND field=%s',(CONTROL,'storage_key_check'))
        elif fault=='duplicate':cursor.execute('INSERT INTO `tabSingles` SELECT * FROM `tabSingles` WHERE doctype=%s AND field=%s',(CONTROL,'storage_namespace'))
        elif fault=='unknown':cursor.execute('INSERT INTO `tabSingles` VALUES (%s,%s,%s)',(CONTROL,'unknown','PRESENT'))
        elif fault in ('version','probe'):
            cursor.execute('UPDATE `tabSingles` SET value=%s WHERE doctype=%s AND field=%s',
                ('INVALID',CONTROL,'storage_version' if fault=='version' else 'storage_key_check'))
    t.connection.commit()
    if fault=='key':t.runtime.conf['encryption_key']=base64.urlsafe_b64encode(b'X'*32).decode()
    elif fault=='site':t.runtime.local.site='other.invalid'
    before=t.rows()
    with pytest.raises(storage.NativeStorageError) as failed:storage.initialize_native_storage(runtime=t.runtime)
    assert failed.value.__context__ is None and t.rows()==before and t.runtime.db.commits==1
    if fault!='unknown':
        with pytest.raises(WorkerTransactionError):
            with owned_worker_transaction(t.runtime):pytest.fail('Unbound worker admitted')


@pytest.mark.parametrize('after_insert',[1,2,3])
def test_partial_control_inserts_roll_back_together(clean,monkeypatch,after_insert):
    t=clean;sql=t.runtime.db.sql;count=0
    def broken(statement,values=(),**kwargs):
        nonlocal count
        rows=sql(statement,values,**kwargs)
        if statement.startswith('INSERT INTO `tabSingles`'):
            count+=1
            if count==after_insert:raise RuntimeError('PRIVATE-INSERT-FAILURE')
        return rows
    with monkeypatch.context() as patch:
        patch.setattr(t.runtime.db,'sql',broken)
        with pytest.raises(storage.NativeStorageError):storage.initialize_native_storage(runtime=t.runtime)
    assert not t.rows() and t.runtime.db.commits==0
    assert not storage.initialize_native_storage(runtime=t.runtime).reused


def test_lost_commit_acknowledgment_recovers_the_same_committed_namespace(clean,monkeypatch):
    t=clean;commit=t.runtime.db.commit
    def unknown():
        commit()
        raise RuntimeError('PRIVATE-LOST-ACK')
    with monkeypatch.context() as patch:
        patch.setattr(t.runtime.db,'commit',unknown)
        with pytest.raises(storage.NativeStorageError) as failed:storage.initialize_native_storage(runtime=t.runtime)
    assert failed.value.commit_uncertain and failed.value.__context__ is None
    namespace=next(row['value'] for row in t.rows() if row['field']=='storage_namespace')
    again=storage.initialize_native_storage(runtime=t.runtime)
    assert again.reused and again.namespace==namespace and t.runtime.db.commits==1


def test_zero_wait_mutex_excludes_another_initializer_with_nonunique_singles(clean,monkeypatch):
    t=clean;other=runtime_for(t.connections());sql=t.runtime.db.sql;observed=[]
    def competing(statement,values=(),**kwargs):
        if 'information_schema.columns' in statement:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(storage.initialize_native_storage,runtime=other)
                with pytest.raises(storage.NativeStorageError,match='setup_busy'):future.result(timeout=5)
            observed.append(True)
        return sql(statement,values,**kwargs)
    monkeypatch.setattr(t.runtime.db,'sql',competing)
    first=storage.initialize_native_storage(runtime=t.runtime)
    assert observed and len(t.rows())==3
    assert storage.initialize_native_storage(runtime=other).namespace==first.namespace


def test_an_existing_parent_session_mutex_is_neither_recursively_acquired_nor_released(clean):
    t=clean;name='zatca-storage-'+hashlib.sha256(t.runtime.conf['db_name'].encode()).hexdigest()[:48]
    with t.connection.cursor() as cursor:cursor.execute('SELECT GET_LOCK(%s,0)',(name,));assert cursor.fetchone()==(1,)
    try:
        with pytest.raises(storage.NativeStorageError,match='setup_busy'):storage.initialize_native_storage(runtime=t.runtime)
        with t.connection.cursor() as cursor:
            cursor.execute('SELECT IS_USED_LOCK(%s)=CONNECTION_ID()',(name,));assert cursor.fetchone()==(1,)
        assert not t.rows()
    finally:
        with t.connection.cursor() as cursor:cursor.execute('SELECT RELEASE_LOCK(%s)',(name,))


def test_lost_mutex_acquisition_acknowledgment_does_not_leave_a_recursive_lock(clean,monkeypatch):
    t=clean;sql=t.runtime.db.sql
    def unknown(statement,values=(),**kwargs):
        rows=sql(statement,values,**kwargs)
        if 'SELECT GET_LOCK' in statement:raise RuntimeError('PRIVATE-MUTEX-ACK')
        return rows
    with monkeypatch.context() as patch:
        patch.setattr(t.runtime.db,'sql',unknown)
        with pytest.raises(storage.NativeStorageError):storage.initialize_native_storage(runtime=t.runtime)
    assert not t.rows()
    assert not storage.initialize_native_storage(runtime=t.runtime).reused


def test_manager_and_clean_parent_transaction_are_required(clean):
    t=clean;t.runtime.original.get_roles=lambda actor:[]
    with pytest.raises(storage.NativeStorageError,match='manager_required'):storage.initialize_native_storage(runtime=t.runtime)
    t.runtime.original.get_roles=lambda actor:['System Manager'];t.runtime.db.transaction_writes=1
    with pytest.raises(storage.NativeStorageError):storage.initialize_native_storage(runtime=t.runtime)
    assert not t.rows() and t.runtime.db.commits==0


@pytest.mark.parametrize('fault',['metadata','column_missing','capacity'])
def test_schema_and_physical_capacity_are_reviewed_before_any_insert(clean,monkeypatch,fault):
    t=clean;sql=t.runtime.db.sql
    if fault=='metadata':
        t.runtime.get_meta=lambda doctype:SimpleNamespace(issingle=0)
    else:
        def changed(statement,values=(),**kwargs):
            rows=sql(statement,values,**kwargs)
            if 'information_schema.columns' in statement:
                rows=[dict(row) for row in rows]
                if fault=='column_missing':rows.pop()
                else:rows[0]['max_bytes']=1
            return rows
        monkeypatch.setattr(t.runtime.db,'sql',changed)
    with pytest.raises(storage.NativeStorageError):storage.initialize_native_storage(runtime=t.runtime)
    assert not t.rows() and t.runtime.db.commits==0
