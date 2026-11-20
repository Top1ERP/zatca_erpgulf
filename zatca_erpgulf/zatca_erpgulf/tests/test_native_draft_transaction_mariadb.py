"""Borrowed native draft isolation on owned private InnoDB, never a tenant DB.

ERP submit and ledger rows are explicit doubles. The real savepoints, callbacks,
parent encrypted intents and queue bridge run together; no installed GL/File or
canonical signer/authority acceptance is claimed.
"""

import os
from uuid import uuid4
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import draft_submission as draft
from zatca_erpgulf.zatca_erpgulf import deferred_submission as deferred
from zatca_erpgulf.zatca_erpgulf import native_draft_transaction as transaction
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_publication_mariadb import NativeSource
from zatca_erpgulf.zatca_erpgulf.worker_transaction import CALLBACKS


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


@pytest.fixture
def batch(handoff,monkeypatch):
    c=handoff;dt=c.source.doctype;table='`tab'+dt+'`'
    names=[c.source.name]+['DRAFT-'+str(uuid4()) for _ in range(2)]
    with c.connection.cursor() as cursor:
        cursor.execute('CREATE TABLE IF NOT EXISTS `fixture_draft_ledger` (name VARCHAR(140) PRIMARY KEY,value INT) ENGINE=InnoDB')
        cursor.execute('UPDATE '+table+' SET docstatus=0,custom_zatca_status=%s WHERE name=%s',('Not Submitted',names[0]))
        for name in names[1:]:
            cursor.execute('INSERT INTO '+table+' (name,company,docstatus,outstanding_amount,status,grand_total,paid_amount,custom_zatca_status) '
                'VALUES (%s,%s,0,115,%s,115,0,%s)',(name,c.company.name,'Unpaid','Not Submitted'))
    c.original_commit()
    prototype=c.runtime.get_doc(dt,names[0]);original=c.runtime.get_doc
    def get_doc(kind,name,**kwargs):
        if kind!=dt:return original(kind,name,**kwargs)
        suffix=' FOR UPDATE NOWAIT' if kwargs.get('for_update') else ''
        rows=c.database.sql('SELECT * FROM '+table+' WHERE name=%s'+suffix,(name,),as_dict=True)
        assert len(rows)==1
        doc=NativeSource(**(vars(prototype)|dict(rows[0])))
        if dt=='Sales Invoice':
            children=c.database.sql('SELECT * FROM `tabPayment Schedule` WHERE parent=%s ORDER BY idx'+suffix,(name,),as_dict=True)
            doc.payment_schedule=[NativeSource(doctype='Payment Schedule',**row) for row in children]
        return doc
    monkeypatch.setattr(c.runtime,'get_doc',get_doc)
    def ledger(name,value=1):c.database.sql('INSERT INTO `fixture_draft_ledger` VALUES (%s,%s)',(name,value))
    def make(name,*,after=None,register=True):
        doc=get_doc(dt,name)
        def submit():
            c.database.sql('UPDATE '+table+' SET docstatus=1 WHERE name=%s',(name,))
            ledger(name)
            doc.docstatus=1
            if register:
                with deferred.invoice_submit_hook(dt,doc,runtime=c.runtime,translate=str):
                    assert deferred.maybe_defer_invoice_submission(dt,name,runtime=c.runtime,translate=str)
            if after:after(doc)
            return doc
        doc.submit=submit
        return doc
    c.names=names;c.make=make;c.ledger=ledger;c.table=table
    c.submit=lambda doc:draft.submit_draft(doc,runtime=c.runtime,translate=str,operation='manual')
    c.intents=lambda:c.database.sql('SELECT * FROM `tabZATCA Submission Intent` WHERE source_name IN (%s,%s,%s)',tuple(names),as_dict=True)
    c.ledger_rows=lambda:c.database.sql('SELECT * FROM `fixture_draft_ledger` WHERE name IN (%s,%s,%s)',tuple(names),as_dict=True)
    try:yield c
    finally:
        c.original_rollback()
        with c.connection.cursor() as cursor:
            for name in names:
                cursor.execute('DELETE FROM `tabZATCA Submission Intent` WHERE source_name=%s',(name,))
                cursor.execute('DELETE FROM `fixture_draft_ledger` WHERE name=%s',(name,))
        c.connection.commit()


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),
    (0,'linked','Background',True),(1,'linked','Background',True)],indirect=True)
def test_failed_middle_draft_preserves_other_sources_ledgers_callbacks_and_encrypted_intents(batch):
    c=batch;first,middle,last=c.names;baseline_commit=c.database.commits
    c.submit(c.make(first));before={name:tuple(getattr(c.database,name)._functions) for name in CALLBACKS}
    retained=[]
    def fail(doc):
        retained.extend(tuple(c.database.after_commit._functions)[len(before['after_commit']):])
        raise ValueError('SYNTHETIC ERP VALIDATION')
    with pytest.raises(ValueError,match='SYNTHETIC ERP'):c.submit(c.make(middle,after=fail))
    assert c.runtime.get_doc(c.source.doctype,middle).docstatus==0
    assert [(row['name'],row['value']) for row in c.ledger_rows()]==[(first,1)]
    assert {row['source_name'] for row in c.intents()}=={first}
    assert all(tuple(getattr(c.database,name)._functions)==before[name] for name in CALLBACKS)
    assert not deferred.is_invoice_submission_deferred(c.runtime,c.source.doctype,middle)
    assert deferred.is_invoice_submission_deferred(c.runtime,c.source.doctype,first)
    for callback in retained:callback()
    c.runtime.enqueue.assert_not_called()
    c.submit(c.make(last));assert c.database.commits==baseline_commit and c.head()=='0'
    c.database.commit()
    assert {row['source_name'] for row in c.intents()}=={first,last}
    assert all(row['state']=='READY' for row in c.intents())
    assert {row['name'] for row in c.ledger_rows()}=={first,last}
    assert c.runtime.enqueue.call_count==2 and not c.sent
    assert c.execute()['status']=='COMPLETE' and c.head()=='1' and len(c.sent)==1


def test_local_rollback_preserves_parent_sql_write_counter_and_clears_only_operation_callbacks(batch):
    c=batch;foreign='FOREIGN-'+str(uuid4());c.ledger(foreign,9)
    prior=Mock();c.database.after_commit.add(prior)
    before=c.database.transaction_writes;events=[]
    def fail(doc):
        c.database.before_rollback.add(lambda:events.append('before'))
        def cleanup():
            events.append('after');c.ledger('CLEANUP-'+c.names[0])
        c.database.after_rollback.add(cleanup)
        raise ValueError('SYNTHETIC')
    with pytest.raises(ValueError):c.submit(c.make(c.names[0],after=fail))
    assert events==['before','after'] and c.database.transaction_writes==before
    assert tuple(c.database.after_commit._functions)==(prior,) and not c.intents()
    assert c.runtime.get_doc(c.source.doctype,c.names[0]).docstatus==0
    assert c.database.sql('SELECT * FROM `fixture_draft_ledger` WHERE name=%s',(foreign,),as_dict=True)[0]['value']==9
    assert not c.database.sql('SELECT * FROM `fixture_draft_ledger` WHERE name=%s',('CLEANUP-'+c.names[0],),as_dict=True)
    c.database.commit();prior.assert_called_once();c.runtime.enqueue.assert_not_called()


@pytest.mark.parametrize('failure',['callback_prefix','callback_manager','callback_cleanup','commit','raw_commit','raw_rollback','actor','site','key'])
def test_lost_parent_transaction_or_callback_ownership_stops_without_claiming_local_rollback(batch,failure):
    c=batch;before_cancels=Mock();c.database.after_commit.add(before_cancels)
    def fail(doc):
        if failure=='callback_prefix':c.database.after_commit._functions.popleft()
        elif failure=='callback_manager':c.database.after_commit._functions=c.database.after_commit._functions.copy()
        elif failure=='callback_cleanup':c.database.after_rollback.add(lambda:(_ for _ in ()).throw(RuntimeError('PRIVATE CLEANUP')))
        elif failure=='commit':c.database.commit()
        elif failure=='raw_commit':c.connection.commit()
        elif failure=='raw_rollback':c.connection.rollback()
        elif failure=='actor':c.runtime.session.user='CHANGED'
        elif failure=='site':c.runtime.local.site='other.invalid'
        else:c.runtime.conf['encryption_key']='CHANGED'
        raise ValueError('PRIVATE CHILD ERROR')
    with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(c.make(c.names[0],after=fail))
    assert caught.value.fatal and caught.value.__context__ is None
    assert 'PRIVATE' not in str(caught.value)+repr(c.runtime.log_error.call_args)
    assert not deferred.is_invoice_submission_deferred(c.runtime,c.source.doctype,c.names[0])
    before_cancels.assert_not_called();c.runtime.enqueue.assert_not_called();assert not c.sent


def test_early_framework_commit_guard_precedes_previous_parent_finalizers(batch):
    c=batch;c.submit(c.make(c.names[0]));before=c.intents()[0]
    def early(doc):c.database.commit()
    with pytest.raises(transaction.NativeDraftTransactionError):c.submit(c.make(c.names[1],after=early))
    current=c.database.sql('SELECT state FROM `tabZATCA Submission Intent` WHERE name=%s',(before['name'],),as_dict=True)
    assert current[0]['state']=='STAGED'  # Earlier finalizer was never run.
    c.runtime.enqueue.assert_not_called();assert c.head()=='0' and not c.sent


def test_missing_native_hook_rolls_back_erp_writes_without_creating_an_intent(batch):
    c=batch
    with pytest.raises(transaction.NativeDraftTransactionError) as failed:c.submit(c.make(c.names[0],register=False))
    assert not failed.value.fatal and failed.value.code=='native_draft_handoff_missing'
    assert c.runtime.get_doc(c.source.doctype,c.names[0]).docstatus==0 and not c.ledger_rows() and not c.intents()
    c.runtime.enqueue.assert_not_called()


def test_preexisting_nontransactional_table_blocks_before_erp_submit(batch):
    c=batch
    with c.connection.cursor() as cursor:cursor.execute('CREATE TABLE `fixture_nontransactional_draft` (name INT) ENGINE=MyISAM')
    try:
        doc=c.make(c.names[0]);original=doc.submit;doc.submit=Mock(side_effect=original)
        with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(doc)
        assert not caught.value.fatal and caught.value.code=='native_draft_transactional_schema'
        doc.submit.assert_not_called();assert not c.intents() and not c.ledger_rows()
    finally:
        c.original_rollback()
        with c.connection.cursor() as cursor:cursor.execute('DROP TABLE `fixture_nontransactional_draft`')


def test_current_locked_source_rejects_a_stale_caller_before_erp_write(batch):
    c=batch;doc=c.make(c.names[0]);doc.grand_total=114
    with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(doc)
    assert caught.value.code=='native_draft_saved_source_changed' and not caught.value.fatal
    assert not c.intents() and not c.ledger_rows() and c.runtime.get_doc(doc.doctype,doc.name).docstatus==0


def test_rollback_callback_cannot_register_an_unprocessed_cleanup_then_continue(batch):
    c=batch
    def fail(doc):
        c.database.after_rollback.add(lambda:c.database.after_rollback.add(Mock()))
        raise ValueError('SYNTHETIC')
    with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(c.make(c.names[0],after=fail))
    assert caught.value.fatal and caught.value.code=='native_draft_rollback_callbacks_changed'
    c.runtime.enqueue.assert_not_called()


@pytest.mark.parametrize('case',[(0,'linked','Background',True),(1,'device','Background',True)],indirect=True)
def test_actual_background_batch_continues_after_rollback_and_preserves_prior_callbacks_and_error_log(batch,monkeypatch):
    from datetime import datetime
    from zatca_erpgulf.zatca_erpgulf import background_worker
    c=batch;c.company.custom_submit_or_not=1
    original=c.runtime.get_doc;submitted=[]
    def fail(doc):raise ValueError('SYNTHETIC ERP VALIDATION')
    def get_doc(dt,name,**kwargs):
        doc=original(dt,name,**kwargs)
        if dt==c.source.doctype:
            owned=c.make(name,after=fail if name==c.names[1] else None)
            def submit():submitted.append(name);return owned.submit()
            def reload():
                fresh=original(dt,name)
                for key,value in vars(fresh).items():setattr(doc,key,value)
                return doc
            doc.submit=submit;doc.reload=reload
        return doc
    monkeypatch.setattr(c.runtime,'get_doc',get_doc)
    monkeypatch.setattr(background_worker,'frappe',c.runtime)
    monkeypatch.setattr(background_worker,'now_datetime',lambda:datetime(2026,11,20,10))
    monkeypatch.setattr(background_worker,'get_alias_value',lambda group,doc,default:doc.get('custom_b2c',default))
    c.runtime.get_all=Mock(return_value=[{'name':name} for name in c.names])
    c.runtime.get_traceback=Mock(return_value='SYNTHETIC ERP VALIDATION')
    diagnostics=[]
    def log_error(**kwargs):
        diagnostics.append(kwargs);c.ledger('DIAGNOSTIC-'+c.names[1],7)
    c.runtime.log_error=log_error;callback=Mock();sales=c.source.doctype=='Sales Invoice'
    background_worker.run_pending_background_invoices(c.source.doctype,callback,commit_per_invoice=sales)
    assert submitted==c.names and len(diagnostics)==1
    assert c.runtime.get_doc(c.source.doctype,c.names[1]).docstatus==0
    assert {row['source_name'] for row in c.intents()}=={c.names[0],c.names[2]}
    assert {row['name'] for row in c.ledger_rows()}=={c.names[0],c.names[2]}
    assert c.runtime.enqueue.call_count==(2 if sales else 0)
    if not sales:c.database.commit()
    assert c.runtime.enqueue.call_count==2 and all(row['state']=='READY' for row in c.intents())
    assert c.database.sql('SELECT value FROM `fixture_draft_ledger` WHERE name=%s',('DIAGNOSTIC-'+c.names[1],),as_dict=True)[0]['value']==7
    callback.assert_not_called();assert not c.sent and c.head()=='0'


def test_concurrent_committed_source_change_cannot_be_hidden_by_parent_read_snapshot(batch):
    c=batch;doc=c.make(c.names[0])
    c.change('UPDATE '+c.table+' SET grand_total=114 WHERE name=%s',(c.names[0],))
    with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(doc)
    assert caught.value.code=='native_draft_saved_source_changed' and not caught.value.fatal
    assert not c.intents() and not c.ledger_rows() and c.head()=='0'
    c.runtime.enqueue.assert_not_called()


@pytest.mark.parametrize('transport',['legacy','native','owned_worker'])
def test_post_hook_extension_cannot_send_or_acquire_an_owned_worker_inside_erp_draft(batch,transport):
    from zatca_erpgulf.zatca_erpgulf import native_transport
    from zatca_erpgulf.zatca_erpgulf.issuing_attempt import confirm_issuing_transport
    from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction,WorkerTransactionError
    c=batch
    def after(doc):
        assert deferred.HOOK.get() is None and transaction.CURRENT.get() is not None
        if transport=='legacy':confirm_issuing_transport('TC',doc,runtime=c.runtime)
        elif transport=='native':native_transport.invoke_saved_request(object(),runtime=c.runtime)
        else:
            with owned_worker_transaction(c.runtime):pytest.fail('Worker entered a borrowed ERP transaction')
    error=WorkerTransactionError if transport=='owned_worker' else deferred.DeferredSubmissionError
    with pytest.raises(error) as caught:c.submit(c.make(c.names[0],after=after))
    assert caught.value.code==('worker_transaction_draft_context' if transport=='owned_worker' else 'deferred_inline_transport')
    assert c.runtime.get_doc(c.source.doctype,c.names[0]).docstatus==0 and not c.intents() and not c.ledger_rows()
    assert c.head()=='0' and not c.sent;c.runtime.enqueue.assert_not_called()


def test_cancelled_handoff_cannot_look_successful_when_the_erp_submit_returns_normally(batch):
    c=batch;retained=[]
    def cancel(doc):
        retained.extend(c.database.after_commit._functions)
        # Model an extension cancelling a registration but swallowing its error.
        c.database.after_rollback._functions[-1]()
    with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(c.make(c.names[0],after=cancel))
    assert caught.value.code=='native_draft_handoff_missing' and not caught.value.fatal
    assert c.runtime.get_doc(c.source.doctype,c.names[0]).docstatus==0 and not c.intents() and not c.ledger_rows()
    for callback in retained:callback()
    c.runtime.enqueue.assert_not_called();assert c.head()=='0'


def test_current_locked_permission_recheck_cannot_use_an_older_owner_snapshot(batch):
    c=batch
    with c.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE '+c.table+' ADD COLUMN IF NOT EXISTS owner VARCHAR(140)')
        cursor.execute('UPDATE '+c.table+' SET owner=%s WHERE name=%s',('ALLOWED',c.names[0]))
    c.original_commit();doc=c.make(c.names[0]);original_submit=doc.submit;doc.submit=Mock(side_effect=original_submit)
    c.change('UPDATE '+c.table+' SET owner=%s WHERE name=%s',('REVOKED',c.names[0]))
    c.runtime.has_permission=lambda dt,operation,*,doc,user,raise_exception=True:not (
        dt==c.source.doctype and doc.get('owner')=='REVOKED')
    with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(doc)
    assert caught.value.code=='native_draft_source_access' and not caught.value.fatal
    doc.submit.assert_not_called();assert not c.intents() and not c.ledger_rows() and c.head()=='0'


def test_lock_failure_before_savepoint_is_a_fatal_admission_not_an_ordinary_batch_error(batch):
    c=batch;doc=c.make(c.names[0]);original_submit=doc.submit;doc.submit=Mock(side_effect=original_submit)
    other=c.connections()
    with other.cursor() as cursor:cursor.execute('SELECT name FROM '+c.table+' WHERE name=%s FOR UPDATE NOWAIT',(c.names[0],))
    try:
        with pytest.raises(transaction.NativeDraftTransactionError) as caught:c.submit(doc)
        assert caught.value.fatal and caught.value.code=='native_draft_admission_unconfirmed'
        assert caught.value.__context__ is None
        doc.submit.assert_not_called();c.runtime.enqueue.assert_not_called()
    finally:other.rollback()
    assert not c.intents() and not c.ledger_rows() and c.head()=='0'
