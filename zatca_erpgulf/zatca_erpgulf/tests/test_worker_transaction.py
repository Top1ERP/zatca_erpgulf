"""Current-site transaction ownership with explicit framework-shaped doubles."""

import base64
from datetime import datetime, timezone
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.worker_transaction import (
    CALLBACKS,OWNED_WORKER,WorkerTransactionError,owned_worker_transaction,
)
from zatca_erpgulf.zatca_erpgulf.dispatch_storage_context import derive_storage_cipher,make_storage_probe


def control_rows(namespace, *, site='fictional.invalid'):
    key=base64.urlsafe_b64encode(b'T'*32).decode()
    cipher=derive_storage_cipher(key,site=site,namespace=namespace)
    return [('ZATCA Dispatch Control','storage_namespace',namespace),
        ('ZATCA Dispatch Control','storage_version','1'),
        ('ZATCA Dispatch Control','storage_key_check',make_storage_probe(cipher,namespace))]


@pytest.fixture
def boundary():
    connection=SimpleNamespace(_sock=object(),open=True,get_autocommit=lambda:False)
    db=SimpleNamespace(db_type='mariadb',cur_db_name='synthetic',_conn=connection,
        transaction_writes=0,auto_commit_on_many_writes=0,rollback=Mock(),commit=Mock())
    for name in CALLBACKS:setattr(db,name,SimpleNamespace(_functions=deque()))
    namespace='30000000-0000-4000-8000-000000000001'
    ready=[{'field':name,'value':value} for _doctype,name,value in control_rows(namespace)]
    def sql(statement,values=(),**kwargs):
        if statement.startswith('SELECT DATABASE'):return [{'db_name':'synthetic'}]
        return ready
    db.sql=Mock(side_effect=sql)
    runtime=SimpleNamespace(local=SimpleNamespace(site='fictional.invalid',db=db),
        session=SimpleNamespace(user='operator'),conf={'db_name':'synthetic','encryption_key':base64.urlsafe_b64encode(b'T'*32).decode()})
    return runtime,db,connection


def test_owned_worker_commits_once_without_closing_or_changing_site_configuration(boundary):
    runtime,db,connection=boundary;before=dict(runtime.conf)
    with owned_worker_transaction(runtime) as owner:
        assert owner.owner_current() and owner.storage_namespace.startswith('3000')
        assert owner.cipher is not None
        owner.commit()
        assert not owner.owner_current() and owner.state=='COMMITTED'
    db.rollback.assert_called_once();db.commit.assert_called_once()
    assert runtime.conf==before and runtime.local.db is db and OWNED_WORKER.get() is None


@pytest.mark.parametrize('dirty',['writes',*CALLBACKS])
def test_parent_writes_or_callbacks_are_not_rolled_back_or_committed(boundary,dirty):
    runtime,db,_=boundary
    if dirty=='writes':db.transaction_writes=1
    else:getattr(db,dirty)._functions.append(lambda:None)
    with pytest.raises(WorkerTransactionError) as caught:
        with owned_worker_transaction(runtime):pytest.fail('parent transaction taken')
    assert caught.value.code=='worker_transaction_parent_state'
    db.sql.assert_not_called();db.rollback.assert_not_called();db.commit.assert_not_called()


def test_an_invoice_submit_context_cannot_acquire_an_owned_transaction_even_before_parent_writes(boundary):
    from zatca_erpgulf.zatca_erpgulf.deferred_submission import HOOK
    runtime,db,_=boundary;token=HOOK.set(object())
    try:
        with pytest.raises(WorkerTransactionError,match='worker_transaction_submit_context'):
            with owned_worker_transaction(runtime):pytest.fail('Submit context was taken')
    finally:HOOK.reset(token)
    db.sql.assert_not_called();db.rollback.assert_not_called();db.commit.assert_not_called()


@pytest.mark.parametrize('change',['writes',*CALLBACKS,'site','actor','database','key'])
def test_lazy_connection_cannot_create_parent_state_then_have_it_discarded(boundary,change):
    runtime,db,_=boundary
    original=db.sql.side_effect
    def changed(statement,values=(),**kwargs):
        result=original(statement,values,**kwargs)
        if change=='writes':db.transaction_writes=1
        elif change in CALLBACKS:getattr(db,change)._functions.append(lambda:None)
        elif change=='site':runtime.local.site='changed.invalid'
        elif change=='actor':runtime.session.user='Administrator'
        elif change=='database':runtime.local.db=object()
        elif change=='key':runtime.conf['encryption_key']='changed'
        return result
    db.sql.side_effect=changed
    with pytest.raises(WorkerTransactionError) as caught:
        with owned_worker_transaction(runtime):pytest.fail('parent state taken')
    assert caught.value.code=='worker_transaction_parent_changed'
    db.rollback.assert_not_called();db.commit.assert_not_called()


@pytest.mark.parametrize('change',['site','actor','database','connection','socket','key'])
def test_owner_changes_poison_operation_without_rolling_back_a_foreign_handle(boundary,change):
    runtime,db,connection=boundary
    with pytest.raises(WorkerTransactionError):
        with owned_worker_transaction(runtime) as owner:
            if change=='site':runtime.local.site='other.invalid'
            if change=='actor':runtime.session.user='Administrator'
            if change=='database':runtime.local.db=object()
            if change=='connection':db._conn=object()
            if change=='socket':connection._sock=object()
            if change=='key':runtime.conf['encryption_key']='different'
            owner.commit()
    db.commit.assert_not_called()
    assert db.rollback.call_count==1  # Entry discarded only the verified read snapshot.
    assert OWNED_WORKER.get() is None


def test_uncertain_commit_is_not_followed_by_speculative_rollback(boundary):
    runtime,db,_=boundary;db.commit.side_effect=RuntimeError('PRIVATE-DRIVER')
    with pytest.raises(WorkerTransactionError) as caught:
        with owned_worker_transaction(runtime) as owner:owner.commit()
    assert caught.value.commit_uncertain and caught.value.code=='worker_transaction_commit_unknown'
    db.rollback.assert_called_once();db.commit.assert_called_once()
    assert caught.value.__context__ is None and 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('change',['site','actor','connection','socket','key','callbacks'])
def test_changed_binding_during_a_returning_commit_is_unknown_and_cannot_release_dispatch(boundary,change):
    runtime,db,connection=boundary
    def commit():
        if change=='site':runtime.local.site='changed.invalid'
        elif change=='actor':runtime.session.user='another-user'
        elif change=='connection':db._conn=object()
        elif change=='socket':connection._sock=object()
        elif change=='key':runtime.conf['encryption_key']='changed'
        elif change=='callbacks':db.after_commit._functions.append(lambda:None)
    db.commit.side_effect=commit
    with pytest.raises(WorkerTransactionError) as caught:
        with owned_worker_transaction(runtime) as owner:owner.commit()
    assert caught.value.commit_uncertain and owner.state=='COMMIT_UNKNOWN'
    db.rollback.assert_called_once()
    assert OWNED_WORKER.get() is None


@pytest.mark.parametrize('key',[None,'','invalid',base64.urlsafe_b64encode(b'X'*16).decode()])
def test_missing_or_invalid_site_key_is_not_generated_or_saved(boundary,key):
    runtime,db,_=boundary;runtime.conf['encryption_key']=key;before=dict(runtime.conf)
    with pytest.raises(WorkerTransactionError):
        with owned_worker_transaction(runtime):pytest.fail('unconfigured cipher acquired')
    assert runtime.conf==before and db.rollback.call_count==2
    db.commit.assert_not_called()


def test_readonly_preparation_restores_original_db_before_coordinator_commit(boundary):
    runtime,db,_=boundary
    with owned_worker_transaction(runtime) as owner:
        with owner.preparing(frozenset(('tabCompany',))) as guarded:
            assert runtime.local.db is guarded and owner.owner_current()
        assert runtime.local.db is db and owner.owner_current()
        owner.commit()


def test_uncommitted_owned_scope_rolls_back_and_invalidates_its_owner_check(boundary):
    runtime,db,_=boundary
    with owned_worker_transaction(runtime) as owner:assert owner.owner_current()
    assert not owner.owner_current() and db.rollback.call_count==2
    db.commit.assert_not_called()


@pytest.mark.parametrize('value', [datetime(2026,11,17,9,0), '2026-11-17', None,
    datetime(2026,11,17,9,0,tzinfo=timezone.utc)])
def test_server_clock_must_be_one_native_naive_utc_datetime(boundary,value):
    runtime,db,_=boundary
    original=db.sql.side_effect
    def sql(statement,values=(),**kwargs):
        if statement.startswith('SELECT UTC_TIMESTAMP'):return [{'utc_now':value}]
        return original(statement,values,**kwargs)
    db.sql.side_effect=sql
    with owned_worker_transaction(runtime) as owner:
        if type(value) is datetime and value.tzinfo is None:
            assert owner.utc_now()==value
        else:
            with pytest.raises(WorkerTransactionError) as caught:owner.utc_now()
            assert caught.value.code=='worker_transaction_clock'
