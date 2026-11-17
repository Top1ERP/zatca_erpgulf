"""DB-view ownership/transaction boundaries; no Frappe site or SQL connection."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.preparation_database import (
    ReadOnlyPreparationDatabase,PreparationDatabaseError,preparation_database,
)


@pytest.fixture
def boundary():
    db=SimpleNamespace(sql=Mock(return_value=[{'value':'ORIGINAL'}]),get_value=Mock(return_value='SAVED'),db_type='mariadb')
    runtime=SimpleNamespace(local=SimpleNamespace(db=db))
    return runtime,db


@pytest.mark.parametrize('operation',['commit','rollback','begin','close','connect','set_value','insert','_conn','_cursor'])
def test_preparation_denies_writes_and_raw_transaction_handles(boundary,operation):
    runtime,original=boundary
    with preparation_database(runtime,owner_check=lambda:True,business_tables=frozenset(('tabCompany',))) as db:
        with pytest.raises(PreparationDatabaseError):getattr(db,operation)
        original.sql.assert_not_called()
    assert runtime.local.db is original


@pytest.mark.parametrize('statement',[
    'COMMIT','ROLLBACK','START TRANSACTION','UPDATE `tabCompany` SET value=1',
    'INSERT INTO `tabCompany` VALUES (1)','DELETE FROM `tabCompany`','CREATE TABLE x (a int)',
    'SELECT 1; COMMIT','SELECT value INTO OUTFILE "/UNOWNED" FROM t',
    'SELECT GET_LOCK("unowned",0)','SELECT LOAD_FILE("/UNOWNED")',
])
def test_non_read_sql_never_reaches_driver(boundary,statement):
    runtime,original=boundary
    with preparation_database(runtime,owner_check=lambda:True,business_tables=frozenset()) as db:
        with pytest.raises(PreparationDatabaseError) as caught:db.sql(statement)
        assert caught.value.code=='preparation_database_write_denied'
        original.sql.assert_not_called()


@pytest.mark.parametrize('suffix',['',' FOR UPDATE',' FOR UPDATE NOWAIT',' LOCK IN SHARE MODE'])
def test_business_reads_share_nowait_and_keep_exact_parameters(boundary,suffix):
    runtime,original=boundary
    with preparation_database(runtime,owner_check=lambda:True,business_tables=frozenset(('tabCompany',))) as db:
        values=('SYNTHETIC',)
        result=db.sql('SELECT name FROM `tabCompany` WHERE name=%s'+suffix,values,as_dict=True)
        original.sql.assert_called_once_with('SELECT name FROM `tabCompany` WHERE name=%s LOCK IN SHARE MODE NOWAIT',values,as_dict=True)
        assert result==[{'value':'ORIGINAL'}]


def test_metadata_reads_and_native_read_results_are_not_normalized(boundary):
    runtime,original=boundary
    with preparation_database(runtime,owner_check=lambda:True,business_tables=frozenset(('tabCompany',))) as db:
        db.sql('SHOW COLUMNS FROM `tabDocType`')
        original.sql.assert_called_once_with('SHOW COLUMNS FROM `tabDocType`')
        assert db.get_value('Company','SYNTHETIC','tax_id',cache=True)=='SAVED'
        original.get_value.assert_called_once_with('Company','SYNTHETIC','tax_id',cache=False)


def test_owner_drift_blocks_read_and_handle_cannot_be_revived(boundary):
    runtime,original=boundary;owner=[True]
    with preparation_database(runtime,owner_check=lambda:owner[0],business_tables=frozenset()) as db:
        owner[0]=False
        with pytest.raises(PreparationDatabaseError):db.sql('SELECT 1')
        owner[0]=True
        with pytest.raises(PreparationDatabaseError) as caught:db.sql('SELECT 1')
        assert caught.value.code=='preparation_database_unusable'
    original.sql.assert_not_called()


def test_internal_handoff_restores_original_without_touching_transactions(boundary):
    runtime,original=boundary
    class Handoff(BaseException):pass
    signal=Handoff()
    with pytest.raises(Handoff) as caught:
        with preparation_database(runtime,owner_check=lambda:True,business_tables=frozenset()):raise signal
    assert caught.value is signal and runtime.local.db is original
    original.sql.assert_not_called()


def test_switched_local_db_is_restored_and_rejected(boundary):
    runtime,original=boundary
    with pytest.raises(PreparationDatabaseError) as caught:
        with preparation_database(runtime,owner_check=lambda:True,business_tables=frozenset()):runtime.local.db=object()
    assert caught.value.code=='preparation_database_binding_changed' and runtime.local.db is original
