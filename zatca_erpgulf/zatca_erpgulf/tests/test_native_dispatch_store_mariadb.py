"""Owned temporary InnoDB, fixed source DDL; no configured/live site database.

This verifies repository transaction/concurrency behavior, not installed Frappe
schema, trusted enrollment, XML signatures or a runtime dispatcher. The existing
private fixture owns its Unix socket/datadir and TCP-disabled subprocess.
"""

from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf.dispatch_store import DispatchStore,DispatchStoreError,CHAIN_FIELDS
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher,DispatchRecordError
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server,connections

pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')
NAMESPACE='30000000-0000-4000-8000-000000000001'
OWNER_KEY='a'*64
NOW=datetime(2026,11,16,9,0,0)
BODY=b'{"invoice":"PRIVATE-SYNTHETIC-ORIGINAL"}'
ROOT=Path(__file__).resolve().parents[1]/'doctype'


class Database:
    def __init__(self,connection):self.connection=connection
    def sql(self,statement,values=(),*,as_dict=True):
        with self.connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(statement,values)
            return cursor.fetchall()


@pytest.fixture(scope='module')
def tables(isolated_server):
    connection=pymysql.connect(unix_socket=isolated_server[0],user='root',database='zatca_journal_rehearsal',autocommit=True)
    try:
        with connection.cursor() as cursor:
            for doctype in ('zatca_issuing_chain','zatca_issuance','zatca_dispatch_attempt'):
                body=json.loads((ROOT/doctype/(doctype+'.json')).read_text())
                columns=['`name` VARCHAR(140) PRIMARY KEY','`owner` VARCHAR(140)','`creation` DATETIME(6)',
                         '`modified` DATETIME(6)','`modified_by` VARCHAR(140)','`docstatus` INT DEFAULT 0']
                for field in body['fields']:
                    kind={'Int':'INT','Check':'TINYINT','Long Text':'LONGTEXT','Datetime':'DATETIME(6)'}.get(field['fieldtype'],'VARCHAR(140)')
                    columns.append('`'+field['fieldname']+'` '+kind+(' UNIQUE' if field.get('unique') else ''))
                cursor.execute('CREATE TABLE `tab'+body['name']+'` ('+','.join(columns)+') ENGINE=InnoDB')
        yield
    finally:connection.close()


def store(connection):
    return DispatchStore(Database(connection),storage_namespace=NAMESPACE,
        cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=NAMESPACE),
        owner_check=lambda:connection.open and not connection.get_autocommit())


@pytest.fixture
def chain(connections,tables):
    connection=connections();chain_id=str(uuid4());owner_key=hashlib.sha256(chain_id.encode()).hexdigest()
    row=dict(zip(CHAIN_FIELDS,[chain_id,owner_key,owner_key,'Company','SYNTHETIC','Production','TEST-VAT',
        'NEW_EGS','e'*64,'c'*64,'b'*64,'0',INITIAL_PREVIOUS_HASH,None,None,0,1]))
    with connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabZATCA Issuing Chain` (`name`,'+','.join('`'+key+'`' for key in row)+
                       ') VALUES ('+','.join('%s' for _ in range(len(row)+1))+')',(chain_id,*row.values()))
    connection.commit()
    return row


def header(chain):
    identifier=str(uuid4())
    return dict(record_id=identifier,issuance_key=hashlib.sha256(identifier.encode()).hexdigest(),
        icv_key=hashlib.sha256((chain['record_id']+'\0'+'1').encode()).hexdigest(),chain=chain['record_id'],company='SYNTHETIC',
        source_doctype='Sales Invoice',source_name='SYNTHETIC-'+identifier,environment='Production',source_version=1,
        source_sha256='d'*64,invoice_uuid=str(uuid4()),icv='1',invoice_hash='SYNTHETIC-HASH',previous_hash=INITIAL_PREVIOUS_HASH,
        certificate_sha256='c'*64,public_key_sha256='b'*64,endpoint='invoices/reporting/single',base_url_sha256='f'*64,
        artifact_sha256=hashlib.sha256(BODY).hexdigest(),replaces_issuance=None)


def test_commit_stores_exact_original_and_advances_local_head_once(connections,chain):
    connection=connections();repo=store(connection);before=repo.lock_active_chain(chain['owner_key']);values=header(chain)
    repo.stage_issuance(before,values,BODY,actor='TEST-OPERATOR',occurred_at=NOW)
    connection.commit()
    fresh=connections();loaded,raw=store(fresh).open_issuance(values['record_id'])
    assert dict(loaded)==values and raw==BODY
    head=store(fresh).lock_active_chain(chain['owner_key'])
    assert head['last_icv']=='1' and head['previous_hash']==values['invoice_hash'] and head['tail_issuance']==values['record_id']
    with fresh.cursor() as cursor:
        cursor.execute('SELECT artifact_ciphertext FROM `tabZATCA Issuance` WHERE name=%s',(values['record_id'],))
        assert 'PRIVATE' not in cursor.fetchone()[0]


def test_whole_rollback_removes_artifact_and_counter_advance(connections,chain):
    connection=connections();repo=store(connection);before=repo.lock_active_chain(chain['owner_key']);values=header(chain)
    repo.stage_issuance(before,values,BODY,actor='TEST-OPERATOR',occurred_at=NOW);connection.rollback()
    fresh=connections();head=store(fresh).lock_active_chain(chain['owner_key'])
    assert head['last_icv']=='0' and head['tail_issuance'] is None
    with fresh.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM `tabZATCA Issuance` WHERE name=%s',(values['record_id'],))
        assert cursor.fetchone()==(0,)


def test_current_source_lookup_cannot_select_an_older_version_by_resetting_uuid(connections,chain):
    connection=connections();repo=store(connection);locked=repo.lock_active_chain(chain['owner_key']);first=header(chain)
    repo.stage_issuance(locked,first,BODY,actor='TEST',occurred_at=NOW);connection.commit()
    repo=store(connection);locked=repo.lock_active_chain(chain['owner_key']);second=header(chain)
    # Synthetic storage setup only: source-level replacement admission belongs
    # to the coordinator, not this fixed-table repository method.
    second.update(source_name=first['source_name'],source_version=2,icv='2',previous_hash=first['invoice_hash'],
        replaces_issuance=first['record_id'],icv_key=hashlib.sha256((chain['record_id']+'\0'+'2').encode()).hexdigest())
    repo.stage_issuance(locked,second,BODY,actor='TEST',occurred_at=NOW);connection.commit()
    with pytest.raises(DispatchStoreError,match='dispatch_source_custody_review'):
        store(connection).find_source_issuance(doctype='Sales Invoice',invoice_name=first['source_name'],
            company=first['company'],chain_id=first['chain'],invoice_uuid=first['invoice_uuid'],icv=first['icv'])
    connection.rollback()
    current=store(connection).find_source_issuance(doctype='Sales Invoice',invoice_name=second['source_name'],
        company=second['company'],chain_id=second['chain'],invoice_uuid=second['invoice_uuid'],icv=second['icv'])
    assert current['record_id']==second['record_id']
    # Historical originals remain available through explicit record custody.
    old,raw=store(connection).open_issuance(first['record_id'])
    assert old['invoice_uuid']==first['invoice_uuid'] and raw==BODY


def test_competing_worker_cannot_acquire_same_chain_and_failed_handle_cannot_continue(connections,chain):
    first,second=connections(),connections();store(first).lock_active_chain(chain['owner_key']);contender=store(second)
    with pytest.raises(DispatchStoreError) as caught:contender.lock_active_chain(chain['owner_key'])
    assert caught.value.code=='dispatch_store_busy'
    first.rollback()
    with pytest.raises(DispatchStoreError) as poisoned:contender.lock_active_chain(chain['owner_key'])
    assert poisoned.value.code=='dispatch_store_unusable'
    second.rollback()
    assert store(second).lock_active_chain(chain['owner_key'])['last_icv']=='0'


def test_failed_head_compare_requires_rollback_of_already_staged_original(connections,chain):
    connection=connections();repo=store(connection);before=repo.lock_active_chain(chain['owner_key']);values=header(chain)
    with connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET state_version=99 WHERE name=%s',(chain['record_id'],))
    with pytest.raises(DispatchStoreError) as caught:repo.stage_issuance(before,values,BODY,actor='TEST',occurred_at=NOW)
    assert caught.value.code=='dispatch_store_compare_failed'
    connection.rollback()
    with connections().cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM `tabZATCA Issuance` WHERE name=%s',(values['record_id'],))
        assert cursor.fetchone()==(0,)


def test_uncertain_commit_is_recovered_by_reading_same_original_not_regenerating(connections,chain):
    connection=connections();repo=store(connection);before=repo.lock_active_chain(chain['owner_key']);values=header(chain)
    repo.stage_issuance(before,values,BODY,actor='TEST',occurred_at=NOW)
    # Model lost commit acknowledgment after InnoDB committed the original.
    connection.commit()
    fresh=connections();read=store(fresh);saved,original=read.open_issuance(values['record_id'])
    assert original==BODY and saved['invoice_uuid']==values['invoice_uuid']
    current=read.lock_active_chain(chain['owner_key'])
    with pytest.raises(DispatchStoreError) as caught:read.stage_issuance(current,values,BODY,actor='TEST',occurred_at=NOW)
    assert caught.value.code=='dispatch_predecessor_changed'
    fresh.rollback()


def test_tampered_plain_metadata_cannot_decrypt_a_stored_original(connections,chain):
    connection=connections();repo=store(connection);before=repo.lock_active_chain(chain['owner_key']);values=header(chain)
    repo.stage_issuance(before,values,BODY,actor='TEST',occurred_at=NOW);connection.commit()
    with connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuance` SET source_name=%s WHERE name=%s',('DIFFERENT',values['record_id']))
    connection.commit()
    with pytest.raises(DispatchRecordError) as caught:store(connections()).open_issuance(values['record_id'])
    assert caught.value.code=='dispatch_record_integrity' and caught.value.__context__ is None


def test_fabricated_or_copied_head_is_not_a_repository_lock_ticket(connections,chain):
    connection=connections();repo=store(connection);before=repo.lock_active_chain(chain['owner_key']);values=header(chain)
    with pytest.raises(DispatchStoreError) as caught:repo.stage_issuance(dict(before),values,BODY,actor='TEST',occurred_at=NOW)
    assert caught.value.code=='dispatch_chain_lock_required'
    connection.rollback()


def test_repository_owner_loss_is_static_and_poisoned_before_any_stage(connections,chain):
    connection=connections();allowed=[True]
    repo=DispatchStore(Database(connection),storage_namespace=NAMESPACE,
        cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=NAMESPACE),
        owner_check=lambda:allowed[0])
    before=repo.lock_active_chain(chain['owner_key']);allowed[0]=False
    with pytest.raises(DispatchStoreError) as caught:repo.stage_issuance(before,header(chain),BODY,actor='TEST',occurred_at=NOW)
    assert caught.value.code=='dispatch_store_owner_changed'
    allowed[0]=True
    with pytest.raises(DispatchStoreError) as unusable:repo.lock_active_chain(chain['owner_key'])
    assert unusable.value.code=='dispatch_store_unusable'
    connection.rollback()


def test_shared_preparation_locks_allow_readers_and_reject_a_writer(connections,chain):
    from zatca_erpgulf.zatca_erpgulf.preparation_database import ReadOnlyPreparationDatabase
    first,second,writer=connections(),connections(),connections()
    statement='SELECT record_id FROM `tabZATCA Issuing Chain` WHERE name=%s FOR UPDATE'
    tables=frozenset(('tabZATCA Issuing Chain',))
    a=ReadOnlyPreparationDatabase(Database(first),owner_check=lambda:True,business_tables=tables)
    b=ReadOnlyPreparationDatabase(Database(second),owner_check=lambda:True,business_tables=tables)
    assert a.sql(statement,(chain['record_id'],))[0]['record_id']==chain['record_id']
    assert b.sql(statement,(chain['record_id'],))[0]['record_id']==chain['record_id']
    with writer.cursor() as cursor:
        with pytest.raises(pymysql.OperationalError) as caught:
            cursor.execute(statement+' NOWAIT',(chain['record_id'],))
    assert caught.value.args[0] in (1205,3572)
    first.rollback();second.rollback();writer.rollback()


def staged(connections,chain):
    connection=connections();repo=store(connection);values=header(chain)
    repo.stage_issuance(repo.lock_active_chain(chain['owner_key']),values,BODY,actor='TEST',occurred_at=NOW)
    connection.commit()
    return values


def locked(connection,chain,record_id):
    repo=store(connection);head=repo.lock_active_chain(chain['owner_key'])
    issuance=repo.lock_issuance(head,record_id)
    return repo,head,issuance


def started(connections,chain,values):
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    attempt_id,fence=str(uuid4()),str(uuid4())
    repo.start_attempt(head,issuance,record_id=attempt_id,fence_token=fence,actor='TEST',now_utc=NOW)
    connection.commit()
    return attempt_id,fence


def test_attempt_and_fence_are_atomic_with_no_counter_or_original_changes(connections,chain):
    values=staged(connections,chain);attempt_id,_=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    assert head['last_icv']=='1' and head['active_attempt']==attempt_id
    assert issuance['state']=='DISPATCHING' and issuance['active_attempt']==attempt_id
    assert repo.open_issuance(values['record_id'])[1]==BODY


def test_rollback_before_http_does_not_leave_a_started_attempt(connections,chain):
    values=staged(connections,chain);connection=connections()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    attempt_id=str(uuid4())
    repo.start_attempt(head,issuance,record_id=attempt_id,fence_token=str(uuid4()),actor='TEST',now_utc=NOW)
    connection.rollback()
    repo,head,issuance=locked(connections(),chain,values['record_id'])
    assert issuance['state']=='PREPARED' and not issuance['active_attempt'] and not head['active_attempt']
    with repo._database.connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(attempt_id,))
        assert cursor.fetchone()==(0,)


@pytest.mark.parametrize('elapsed,explicit',[(0,True),(119,True),(121,False)])
def test_lease_or_omitted_explicit_retry_prevents_duplicate_invocation(connections,chain,elapsed,explicit):
    values=staged(connections,chain);attempt_id,_=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    with pytest.raises(DispatchStoreError) as caught:
        repo.start_attempt(head,issuance,record_id=str(uuid4()),fence_token=str(uuid4()),actor='TEST',
            now_utc=NOW+timedelta(seconds=elapsed),supersedes_attempt=attempt_id if explicit else None)
    assert caught.value.code in ('dispatch_attempt_busy','dispatch_retry_review_required')
    connection.rollback()


@pytest.mark.parametrize('body',[b'',b'{"reportingStatus":"REPORTED"}',b'PRIVATE-ORIGINAL-ERROR'])
def test_receipt_keeps_exact_body_without_claiming_acceptance(connections,chain,body):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    assert repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=200,
        request_id='synthetic-request',body=body) is True
    connection.commit()
    fresh=connections();repo,head,issuance=locked(fresh,chain,values['record_id'])
    metadata,original=repo.open_receipt(attempt_id)
    assert original==body and metadata['http_status']==200
    assert issuance['state']=='REVIEW_REQUIRED' and not head['active_attempt']
    assert repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=200,
        request_id='synthetic-request',body=body) is False
    with fresh.cursor() as cursor:
        cursor.execute('SELECT receipt_ciphertext FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(attempt_id,))
        assert 'PRIVATE' not in cursor.fetchone()[0]


def test_late_old_response_is_retained_without_replacing_newer_attempt(connections,chain):
    values=staged(connections,chain);old_id,old_fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    assert repo.mark_attempt_unknown(head,issuance,attempt_id=old_id,fence_token=old_fence)
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id']);new_id,new_fence=str(uuid4()),str(uuid4())
    repo.start_attempt(head,issuance,record_id=new_id,fence_token=new_fence,actor='TEST',
        now_utc=NOW+timedelta(seconds=121),supersedes_attempt=old_id)
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert repo.retain_receipt(head,issuance,attempt_id=old_id,fence_token=old_fence,http_status=200,
        request_id='late',body=b'OLD') is False
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert issuance['active_attempt']==head['active_attempt']==new_id and issuance['state']=='DISPATCHING'
    assert repo.open_receipt(old_id)[1]==b'OLD'
    assert repo.retain_receipt(head,issuance,attempt_id=new_id,fence_token=new_fence,http_status=400,
        request_id='current',body=b'NEW') is True
    connection.commit()
    assert store(connections()).open_receipt(old_id)[1]==b'OLD'
    assert store(connections()).open_receipt(new_id)[1]==b'NEW'


def test_response_cannot_overwrite_a_previously_retained_response(connections,chain):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=200,request_id='',body=b'FIRST')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    with pytest.raises(DispatchStoreError) as caught:
        repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=409,request_id='',body=b'OTHER')
    assert caught.value.code=='dispatch_receipt_already_retained'
    connection.rollback()
    assert store(connections()).open_receipt(attempt_id)[1]==b'FIRST'


def test_receipt_fence_mismatch_fails_before_persisting_or_accepting(connections,chain):
    values=staged(connections,chain);attempt_id,_=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    with pytest.raises(DispatchStoreError) as caught:
        repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=str(uuid4()),http_status=200,request_id='',body=b'WRONG')
    assert caught.value.code=='dispatch_receipt_binding'
    connection.rollback()


def test_tampered_response_metadata_cannot_open_sealed_receipt(connections,chain):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=200,request_id='',body=b'ORIGINAL')
    connection.commit()
    with connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Dispatch Attempt` SET http_status=400 WHERE name=%s',(attempt_id,))
    connection.commit()
    with pytest.raises(DispatchRecordError) as caught:store(connections()).open_receipt(attempt_id)
    assert caught.value.code=='dispatch_record_integrity'


def test_receipt_is_retained_on_retired_chain_without_reopening_it_for_issuance(connections,chain):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections()
    with connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET active=0,active_owner_key=NULL WHERE name=%s',
            (chain['record_id'],))
    connection.commit()
    repo=store(connection);head=repo.lock_recorded_chain(chain['record_id'],chain['owner_key'])
    issuance=repo.lock_issuance(head,values['record_id'])
    assert repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=400,
        request_id='late-retired',body=b'ORIGINAL-RETIRED-RESPONSE')
    connection.commit()
    assert store(connections()).open_receipt(attempt_id)[1]==b'ORIGINAL-RETIRED-RESPONSE'
    repo=store(connection);head=repo.lock_recorded_chain(chain['record_id'],chain['owner_key'])
    issuance=repo.lock_issuance(head,values['record_id'])
    with pytest.raises(DispatchStoreError) as caught:
        repo.start_attempt(head,issuance,record_id=str(uuid4()),fence_token=str(uuid4()),actor='TEST',now_utc=NOW)
    assert caught.value.code=='dispatch_chain_inactive'
    connection.rollback()


@pytest.mark.parametrize('outcome,expected', [('REPORTING_MATCHED','REPORTED'),
    ('REPORTING_DUPLICATE_MATCHED','REPORTED'), ('VALIDATION_REJECTED','REJECTED'),
    ('AUTHORIZATION_FAILED','OUTCOME_UNKNOWN'), ('CLEARANCE_DISABLED','REPORTING_FALLBACK_READY'),
    ('UNCONFIRMED','REVIEW_REQUIRED')])
def test_current_server_assessment_updates_state_only_after_receipt_retention(connections,chain,outcome,expected):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=200,request_id='',body=b'BODY')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert repo.record_assessment(head,issuance,attempt_id=attempt_id,fence_token=fence,outcome=outcome)
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert issuance['state']==expected and head['last_icv']=='1'
    assert repo.open_receipt(attempt_id)[1]==b'BODY'
    assert repo.record_assessment(head,issuance,attempt_id=attempt_id,fence_token=fence,outcome=outcome) is True


def test_unreceived_attempt_cannot_be_assessed_or_silently_accepted(connections,chain):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    with pytest.raises(DispatchStoreError) as caught:
        repo.record_assessment(head,issuance,attempt_id=attempt_id,fence_token=fence,outcome='REPORTING_MATCHED')
    assert caught.value.code=='dispatch_assessment_receipt_required'
    connection.rollback()


def test_assessment_cannot_overwrite_an_existing_recorded_decision(connections,chain):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=400,request_id='',body=b'BODY')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.record_assessment(head,issuance,attempt_id=attempt_id,fence_token=fence,outcome='VALIDATION_REJECTED')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    with pytest.raises(DispatchStoreError) as caught:
        repo.record_assessment(head,issuance,attempt_id=attempt_id,fence_token=fence,outcome='REPORTING_MATCHED')
    assert caught.value.code=='dispatch_assessment_already_recorded'
    connection.rollback()


@pytest.mark.parametrize('outcome', ['AUTHORIZATION_FAILED','TECHNICAL_FAILURE'])
def test_explicit_retry_of_received_technical_failure_keeps_original_without_waiting_for_old_lease(connections,chain,outcome):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=401,request_id='',body=b'BODY')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.record_assessment(head,issuance,attempt_id=attempt_id,fence_token=fence,outcome=outcome)
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    new_id=str(uuid4())
    repo.start_attempt(head,issuance,record_id=new_id,fence_token=str(uuid4()),actor='TEST',
        now_utc=NOW+timedelta(seconds=1),supersedes_attempt=attempt_id)
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert issuance['state']=='DISPATCHING' and issuance['active_attempt']==new_id
    assert head['last_icv']=='1' and repo.open_issuance(values['record_id'])[1]==BODY


def test_late_old_assessment_is_audited_without_overwriting_a_newer_attempt(connections,chain):
    values=staged(connections,chain);old_id,old_fence=started(connections,chain,values)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    new_id=str(uuid4())
    repo.start_attempt(head,issuance,record_id=new_id,fence_token=str(uuid4()),actor='TEST',
        now_utc=NOW+timedelta(seconds=121),supersedes_attempt=old_id)
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert repo.retain_receipt(head,issuance,attempt_id=old_id,fence_token=old_fence,http_status=200,
        request_id='late',body=b'ORIGINAL') is False
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert repo.record_assessment(head,issuance,attempt_id=old_id,fence_token=old_fence,outcome='REPORTING_MATCHED') is False
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    assert issuance['state']=='DISPATCHING' and issuance['active_attempt']==head['active_attempt']==new_id
    with connection.cursor() as cursor:
        cursor.execute('SELECT outcome FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(old_id,))
        assert cursor.fetchone()==('REPORTING_MATCHED',)


def clearance_disabled(connections,chain):
    connection=connections();repo=store(connection);values=header(chain)
    values['endpoint']='invoices/clearance/single'
    repo.stage_issuance(repo.lock_active_chain(chain['owner_key']),values,BODY,actor='TEST',occurred_at=NOW)
    connection.commit()
    attempt_id,fence=started(connections,chain,values)
    repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=303,
        request_id='clearance-disabled',body=b'ORIGINAL303')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.record_assessment(head,issuance,attempt_id=attempt_id,fence_token=fence,outcome='CLEARANCE_DISABLED')
    connection.commit()
    return values,attempt_id


def test_303_reporting_reservation_changes_only_operation_and_attempt_not_original_or_counter(connections,chain):
    values,prior_id=clearance_disabled(connections,chain)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    identifier=str(uuid4())
    reserved=repo.start_attempt(head,issuance,record_id=identifier,fence_token=str(uuid4()),actor='TEST',
        now_utc=NOW+timedelta(seconds=1),supersedes_attempt=prior_id)
    assert reserved['endpoint']=='invoices/reporting/single' and reserved['attempt_number']==2
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    saved,original=repo.open_issuance(values['record_id'])
    assert saved['endpoint']=='invoices/clearance/single' and original==BODY
    assert saved['invoice_uuid']==values['invoice_uuid'] and head['last_icv']=='1'
    assert repo.open_clearance_fallback(issuance)[1]==b'ORIGINAL303'


def test_303_a_retried_fallback_stays_on_reporting_after_a_technical_response(connections,chain):
    values,prior_id=clearance_disabled(connections,chain)
    connection=connections();repo,head,issuance=locked(connection,chain,values['record_id'])
    identifier,fence=str(uuid4()),str(uuid4())
    repo.start_attempt(head,issuance,record_id=identifier,fence_token=fence,actor='TEST',
        now_utc=NOW+timedelta(seconds=1),supersedes_attempt=prior_id)
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=identifier,fence_token=fence,http_status=503,request_id='',body=b'TECHNICAL')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    repo.record_assessment(head,issuance,attempt_id=identifier,fence_token=fence,outcome='TECHNICAL_FAILURE')
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    retry=repo.start_attempt(head,issuance,record_id=str(uuid4()),fence_token=str(uuid4()),actor='TEST',
        now_utc=NOW+timedelta(seconds=2),supersedes_attempt=identifier)
    assert retry['endpoint']=='invoices/reporting/single' and retry['attempt_number']==3
    connection.commit()


def test_303_state_without_untampered_receipt_cannot_authorize_fallback(connections,chain):
    values,prior_id=clearance_disabled(connections,chain)
    connection=connections()
    with connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Dispatch Attempt` SET request_id=%s WHERE name=%s',('TAMPERED',prior_id))
    connection.commit()
    repo,head,issuance=locked(connection,chain,values['record_id'])
    with pytest.raises(DispatchRecordError) as caught:
        repo.start_attempt(head,issuance,record_id=str(uuid4()),fence_token=str(uuid4()),actor='TEST',
            now_utc=NOW+timedelta(seconds=1),supersedes_attempt=prior_id)
    assert caught.value.code=='dispatch_record_integrity'
    connection.rollback()


def test_native_capacity_preflight_reads_real_column_types_without_changing_them(connections,tables):
    from zatca_erpgulf.zatca_erpgulf.native_dispatch import _require_source_output_capacity,NativeDispatchError
    connection=connections();database=Database(connection)
    with connection.cursor() as cursor:
        cursor.execute('CREATE TABLE `tabSales Invoice` (custom_uuid VARCHAR(36),custom_zatca_icv INT,'
            'custom_zatca_issuing_unit VARCHAR(40)) ENGINE=InnoDB')
    _require_source_output_capacity(database,'Sales Invoice',str(2**31-1))
    with pytest.raises(NativeDispatchError) as small:
        _require_source_output_capacity(database,'Sales Invoice',str(2**31))
    assert small.value.code=='native_source_counter_capacity'
    with connection.cursor() as cursor:
        cursor.execute('ALTER TABLE `tabSales Invoice` MODIFY custom_zatca_icv BIGINT')
    _require_source_output_capacity(database,'Sales Invoice',str(2**63-1))
    with pytest.raises(NativeDispatchError):
        _require_source_output_capacity(database,'Sales Invoice',str(2**63))
    with connection.cursor() as cursor:
        cursor.execute('ALTER TABLE `tabSales Invoice` MODIFY custom_zatca_icv FLOAT')
    with pytest.raises(NativeDispatchError):
        _require_source_output_capacity(database,'Sales Invoice','1')
    with connection.cursor() as cursor:
        cursor.execute('SELECT data_type FROM information_schema.columns WHERE table_schema=DATABASE() '
            'AND table_name=%s AND column_name=%s',('tabSales Invoice','custom_zatca_icv'))
        assert cursor.fetchone()==('float',)  # The preflight did not repair/alter it.


def test_original_open_uses_current_custody_even_when_reader_snapshot_predates_issuance(connections,chain):
    reader=connections()
    with reader.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM `tabZATCA Issuance` WHERE chain=%s',(chain['record_id'],))
        assert cursor.fetchone()==(0,)
    values=staged(connections,chain)
    with reader.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM `tabZATCA Issuance` WHERE chain=%s',(chain['record_id'],))
        assert cursor.fetchone()==(0,)  # The ordinary repeatable-read view is still old.
    assert store(reader).open_issuance(values['record_id'])[1]==BODY


def test_receipt_open_uses_current_sealed_body_after_earlier_started_snapshot(connections,chain):
    values=staged(connections,chain);attempt_id,fence=started(connections,chain,values)
    reader=connections()
    with reader.cursor() as cursor:
        cursor.execute('SELECT state FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(attempt_id,))
        assert cursor.fetchone()==('STARTED',)
    writer=connections();repo,head,issuance=locked(writer,chain,values['record_id'])
    repo.retain_receipt(head,issuance,attempt_id=attempt_id,fence_token=fence,http_status=200,request_id='',body=b'NEW-RECEIPT')
    writer.commit()
    assert store(reader).open_receipt(attempt_id)[1]==b'NEW-RECEIPT'
