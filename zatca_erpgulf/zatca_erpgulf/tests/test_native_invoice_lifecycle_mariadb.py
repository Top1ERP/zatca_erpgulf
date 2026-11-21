"""Source retention decisions on fixture-owned InnoDB; all transport mocked."""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.local import LocalProxy

from zatca_erpgulf.zatca_erpgulf import native_invoice_lifecycle as guard
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')
ACTIONS=('before_cancel','on_trash','before_rename')


@pytest.fixture
def lifecycle(handoff,monkeypatch):
    c=handoff;original=c.runtime.get_meta
    with c.connection.cursor() as cursor:
        for table in ('tabZATCA Issuance','tabZATCA Submission Intent'):
            cursor.execute('CREATE INDEX IF NOT EXISTS lifecycle_source_name ON `'+table+'` (source_name)')
    c.connection.commit()
    def get_meta(dt):
        meta=original(dt)
        if dt==c.source.doctype:
            meta=SimpleNamespace(**vars(meta))
            meta.has_field=lambda field:field=='custom_zatca_issuing_unit'
        return meta
    monkeypatch.setattr(c.runtime,'get_meta',get_meta)
    return c


def inspect(c,action='before_cancel',**kwargs):
    doc=c.runtime.get_doc(c.source.doctype,c.source.name)
    return guard.inspect_source_lifecycle(doc,runtime=c.runtime,method=action,**kwargs)


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Background',True)],indirect=True)
@pytest.mark.parametrize('action',ACTIONS)
@pytest.mark.parametrize('phase',['Phase-1','Phase-2'])
def test_unissued_uuid_alone_never_proves_issuance_or_acceptance(lifecycle,action,phase):
    c=lifecycle;c.company.custom_phase_1_or_2=phase
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_uuid=%s WHERE name=%s',(str(uuid4()),c.source.name))
    writes=c.database.transaction_writes;commits=c.database.commits
    inspect(c,action)
    assert c.database.transaction_writes==writes and c.database.commits==commits
    assert c.head()=='0' and not c.sent and not c.built


@pytest.mark.parametrize('case',[(0,'company','Batches',True),(1,'device','Background',True)],indirect=True)
@pytest.mark.parametrize('state',['PREPARED','DISPATCHING','OUTCOME_UNKNOWN','REJECTED','REPORTED','CLEARED','REVIEW_REQUIRED'])
def test_generated_custody_is_retained_even_if_marker_and_status_are_erased(lifecycle,state):
    c=lifecycle;assert c.run()['status']=='PREPARED'
    # Deliberately contradictory state is only negative retention evidence. The
    # guard neither authenticates acceptance nor claims this row is a receipt.
    c.database.sql('UPDATE `tabZATCA Issuance` SET state=%s WHERE source_name=%s',(state,c.source.name))
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_uuid=NULL,custom_zatca_issuing_unit=NULL,custom_zatca_status=NULL WHERE name=%s',(c.source.name,))
    c.runtime.conf['zatca_native_dispatch']=0;c.company.custom_phase_1_or_2='Phase-1'
    before=(c.database.commits,c.database.transaction_writes,len(c.sent),len(c.built),c.head())
    for action in ACTIONS:
        with pytest.raises(guard.NativeInvoiceLifecycleError,match='does not mean ZATCA accepted') as caught:inspect(c,action)
        assert caught.value.code=='native_lifecycle_retained_history'
    assert (c.database.commits,c.database.transaction_writes,len(c.sent),len(c.built),c.head())==before


@pytest.mark.parametrize('case',[(0,'linked','Live',True),(1,'company','Live',True)],indirect=True)
@pytest.mark.parametrize('action',ACTIONS)
def test_pending_request_retains_source_identity_before_any_generation(lifecycle,action):
    c=lifecycle;c.register()
    before=c.database.commits
    with pytest.raises(guard.NativeInvoiceLifecycleError) as caught:inspect(c,action)
    assert caught.value.code=='native_lifecycle_retained_history'
    assert c.rows()[0]['state']=='STAGED' and c.database.commits==before
    assert c.head()=='0' and not c.built and not c.sent
    c.database.rollback();inspect(c,action)


def test_committed_request_is_visible_behind_an_older_repeatable_read_snapshot(lifecycle):
    c=lifecycle;c.database.sql('SELECT COUNT(*) AS total FROM `tabZATCA Submission Intent`',as_dict=True)
    c.change('INSERT INTO `tabZATCA Submission Intent` (name,source_doctype,source_name,state) VALUES (%s,%s,%s,%s)',
        (str(uuid4()),c.source.doctype,c.source.name,'REVIEW'))
    with pytest.raises(guard.NativeInvoiceLifecycleError) as caught:inspect(c)
    assert caught.value.code=='native_lifecycle_retained_history' and not c.sent


def test_saved_marker_without_history_holds_but_unsaved_browser_marker_does_not(lifecycle):
    c=lifecycle;doc=c.runtime.get_doc(c.source.doctype,c.source.name)
    doc.custom_zatca_issuing_unit='egs:CLIENT-INVENTED'
    guard.inspect_source_lifecycle(doc,runtime=c.runtime)
    c.database.sql('UPDATE `tab'+c.source.doctype+'` SET custom_zatca_issuing_unit=%s WHERE name=%s',('egs:INVALID-LOST-CUSTODY',c.source.name))
    with pytest.raises(guard.NativeInvoiceLifecycleError) as caught:inspect(c)
    assert caught.value.code=='native_lifecycle_saved_marker'


def test_merge_cannot_modify_a_native_target_even_if_source_has_no_history(lifecycle):
    c=lifecycle;target='TARGET-'+str(uuid4())
    c.database.sql('INSERT INTO `tab'+c.source.doctype+'` (name,custom_zatca_issuing_unit) VALUES (%s,%s)',(target,'egs:RETAINED'))
    with pytest.raises(guard.NativeInvoiceLifecycleError) as caught:
        inspect(c,'before_rename',old=c.source.name,new=target,merge=True)
    assert caught.value.code=='native_lifecycle_saved_marker'


def test_source_lock_prevents_concurrent_preparation_without_changing_parent_callbacks(lifecycle):
    c=lifecycle;marker=lambda:None;c.database.after_commit.add(marker)
    callbacks=tuple(c.database.after_commit._functions);inspect(c)
    other=c.connections()
    with other.cursor() as cursor:
        with pytest.raises(Exception):
            cursor.execute('SELECT name FROM `tab'+c.source.doctype+'` WHERE name=%s FOR UPDATE NOWAIT',(c.source.name,))
    other.rollback()
    assert tuple(c.database.after_commit._functions)==callbacks and not c.sent


def test_current_proxy_target_is_pinned_and_replacement_cannot_grant_permission(lifecycle,monkeypatch):
    c=lifecycle
    class ProxyRuntime:
        def __init__(self,original):
            self.original=original;self.db=LocalProxy(lambda:original.local.db)
        def __getattr__(self,name):return getattr(self.original,name)
    c.runtime=ProxyRuntime(c.runtime)
    inspect(c)
    original=c.database.sql
    def changed(statement,*args,**kwargs):
        result=original(statement,*args,**kwargs)
        if 'LIMIT 0' in statement:c.runtime.local.db=object()
        return result
    monkeypatch.setattr(c.database,'sql',changed)
    with pytest.raises(guard.NativeInvoiceLifecycleError,match='requires a reviewed'):
        inspect(c)


def test_other_source_type_with_same_name_does_not_own_this_invoice(lifecycle):
    c=lifecycle;other='POS Invoice' if c.source.doctype=='Sales Invoice' else 'Sales Invoice'
    c.database.sql('INSERT INTO `tabZATCA Submission Intent` (name,source_doctype,source_name,state) VALUES (%s,%s,%s,%s)',
        (str(uuid4()),other,c.source.name,'REVIEW'))
    inspect(c)
    assert not c.sent and c.head()=='0'


def test_missing_physical_history_index_is_review_not_a_broad_locking_scan(lifecycle):
    c=lifecycle
    with c.connection.cursor() as cursor:
        cursor.execute('DROP INDEX lifecycle_source_name ON `tabZATCA Submission Intent`')
    try:
        with pytest.raises(guard.NativeInvoiceLifecycleError) as caught:inspect(c)
        assert caught.value.code=='native_lifecycle_history_index'
    finally:
        with c.connection.cursor() as cursor:
            cursor.execute('CREATE INDEX lifecycle_source_name ON `tabZATCA Submission Intent` (source_name)')


def test_concurrent_source_change_stops_hook_without_foreign_rollback_or_commit(lifecycle,monkeypatch):
    c=lifecycle;other=c.connections();before=c.database.commits
    with other.cursor() as cursor:
        cursor.execute('SELECT name FROM `tab'+c.source.doctype+'` WHERE name=%s FOR UPDATE',(c.source.name,))
    monkeypatch.setattr(guard,'frappe',c.runtime);monkeypatch.setattr(guard,'_',lambda message:'AR:'+message)
    try:
        with pytest.raises(guard.NativeInvoiceLifecycleError) as caught:
            guard.protect_native_invoice_lifecycle(c.source,'before_cancel')
        assert caught.value.code=='native_lifecycle_unconfirmed' and caught.value.__context__ is None
        assert str(caught.value)=='AR:'+guard.REVIEW and c.database.commits==before and not c.sent
        c.runtime.log_error.assert_called_once()
    finally:other.rollback()
