"""Trusted draft collection origins with actual fixed callers; no SQL/HTTP."""

from contextvars import copy_context
import inspect
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import draft_submission as draft
from zatca_erpgulf.zatca_erpgulf import deferred_submission as deferred
from zatca_erpgulf.zatca_erpgulf import background_worker, sign_invoice, pos_sign
from zatca_erpgulf.zatca_erpgulf.tests.test_deferred_submission import boundary
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider import entry
from zatca_erpgulf.zatca_erpgulf.tests.test_background_scheduling import worker_boundary, parent_boundary, WORKERS


def resolve(b,doctype=None,name=None):
    return draft.resolve_submission_operation(b.app,doctype or b.invoice.doctype,name or b.invoice.name)


@pytest.mark.parametrize('operation',['manual','scheduled'])
@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice'])
def test_origin_is_ephemeral_and_bound_to_saved_draft_without_committing_or_queuing(boundary,operation,doctype):
    b=boundary;b.invoice.docstatus=0;b.invoice.doctype=doctype
    assert resolve(b)=='submit'
    seen=[]
    def submit():
        seen.append(resolve(b));b.invoice.docstatus=1
        assert resolve(b)==operation
        return 'ERP-RETURN'
    b.invoice.submit=Mock(side_effect=submit)
    assert draft.submit_draft(b.invoice,runtime=b.app,translate=str,operation=operation)=='ERP-RETURN'
    assert seen==[operation] and draft.CURRENT.get() is None and resolve(b)=='submit'
    b.app.enqueue.assert_not_called();b.app.db.commit.assert_not_called();b.app.db.rollback.assert_not_called()


@pytest.mark.parametrize('change',['site','actor','doctype','name','retained'])
def test_origin_cannot_cross_site_actor_source_or_closed_context(boundary,change):
    b=boundary;b.invoice.docstatus=0
    with draft.draft_submission_origin(b.invoice,runtime=b.app,translate=str,operation='manual'):
        if change=='site':b.app.local.site='other.invalid'
        elif change=='actor':b.app.session.user='Administrator'
        if change=='retained':saved=copy_context()
        else:
            with pytest.raises(deferred.DeferredSubmissionError):
                resolve(b,doctype='POS Invoice' if change=='doctype' else None,name='OTHER' if change=='name' else None)
    if change=='retained':
        with pytest.raises(deferred.DeferredSubmissionError):saved.run(resolve,b)
    assert draft.CURRENT.get() is None


@pytest.mark.parametrize('operation',['manual','scheduled'])
def test_nested_identical_origin_preserves_outer_lifetime_and_exception_cleanup(boundary,operation):
    b=boundary;b.invoice.docstatus=0
    with draft.draft_submission_origin(b.invoice,runtime=b.app,translate=str,operation=operation):
        outer=draft.CURRENT.get()
        with draft.draft_submission_origin(b.invoice,runtime=b.app,translate=str,operation=operation):
            assert draft.CURRENT.get() is outer
        assert resolve(b)==operation and not outer.closed
        with pytest.raises(TypeError):pickle.dumps(outer)
    assert outer.closed and draft.CURRENT.get() is None
    b.invoice.submit=Mock(side_effect=RuntimeError('ERP validation failed'))
    with pytest.raises(RuntimeError):draft.submit_draft(b.invoice,runtime=b.app,translate=str,operation=operation)
    assert draft.CURRENT.get() is None


def test_conflicting_nested_origin_is_one_translated_english_logged_review(boundary):
    b=boundary;b.invoice.docstatus=0
    with draft.draft_submission_origin(b.invoice,runtime=b.app,translate=str,operation='manual'):
        with pytest.raises(deferred.DeferredSubmissionError):
            with draft.draft_submission_origin(b.invoice,runtime=b.app,translate=lambda s:'AR:'+s,operation='scheduled'):
                pytest.fail('Conflicting origin entered')
        assert resolve(b)=='manual'
    assert b.app.throw.call_args.args[0].startswith('AR:')
    b.app.log_error.assert_called_once()
    assert 'AR:' not in str(b.app.log_error.call_args)


@pytest.mark.parametrize('change',['cancelled','submitted','guest','operation','name'])
def test_invalid_origin_cannot_call_erp_submit(boundary,change):
    b=boundary;b.invoice.docstatus=0;b.invoice.submit=Mock();operation='manual'
    if change=='cancelled':b.invoice.docstatus=2
    elif change=='submitted':b.invoice.docstatus=1
    elif change=='guest':b.app.session.user='Guest'
    elif change=='operation':operation='rpc-bypass'
    else:b.invoice.name=' bad '
    with pytest.raises(deferred.DeferredSubmissionError):draft.submit_draft(b.invoice,runtime=b.app,translate=str,operation=operation)
    b.invoice.submit.assert_not_called();assert draft.CURRENT.get() is None


@pytest.mark.parametrize('module,doctype,name',[(sign_invoice,'Sales Invoice','resubmit_invoices'),
    (pos_sign,'POS Invoice','resubmit_invoices_pos')])
def test_actual_manual_draft_collection_retains_manual_origin(entry,monkeypatch,module,doctype,name):
    e=entry;e.docs.pop((e.source.doctype,e.source.name));e.source.doctype=doctype;e.source.docstatus=0
    e.docs[doctype,e.source.name]=e.source;e.company.custom_submit_or_not=1
    monkeypatch.setattr(module,'frappe',e.runtime)
    monkeypatch.setattr(module,'_',str)
    monkeypatch.setattr(module,'get_alias_value',lambda group,doc,default:doc.get('b2c',default))
    seen=[]
    def submit():
        seen.append(draft.resolve_submission_operation(e.runtime,doctype,e.source.name))
        e.source.docstatus=1
    e.source.submit=Mock(side_effect=submit)
    assert inspect.unwrap(getattr(module,name))([e.source.name])=={}
    assert seen==['manual'] and draft.CURRENT.get() is None
    e.prepare.assert_not_called();e.dispatch.assert_not_called()


@pytest.mark.parametrize('worker',WORKERS)
def test_actual_scheduled_draft_collection_retains_scheduled_origin(worker_boundary,worker,monkeypatch):
    b=worker_boundary;b.company('OPEN',custom_submit_or_not=1)
    invoice=b.invoice(worker[2],'DRAFT','OPEN',docstatus=0);seen=[]
    def submit():
        seen.append(draft.resolve_submission_operation(b.frappe,invoice.doctype,invoice.name))
        invoice.docstatus=1
    invoice.submit=Mock(side_effect=submit)
    monkeypatch.setattr(background_worker,'process_native_saved_source',lambda *args,**kwargs:None)
    background_worker.run_pending_background_invoices(worker[2],b.callback,commit_per_invoice=worker[3])
    assert seen==['scheduled'] and draft.CURRENT.get() is None


@pytest.mark.parametrize('operation',['manual','scheduled'])
@pytest.mark.parametrize('native',[True,False])
def test_actual_sales_external_id_background_hook_defers_only_native_owner_after_parent_validation(
        parent_boundary,monkeypatch,operation,native):
    from types import SimpleNamespace
    from zatca_erpgulf.zatca_erpgulf.tests.test_background_scheduling import parent_invoice
    from zatca_erpgulf.zatca_erpgulf.tests.test_deferred_submission import Callbacks
    from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
    from zatca_erpgulf.zatca_erpgulf import submission_intent
    from zatca_erpgulf.ksa_compliance import field_compat
    b=parent_boundary;doc=parent_invoice(b,'Sales Invoice');doc.docstatus=0;doc.custom_unique_id='EXTERNAL-ID'
    doc.custom_zatca_pos_name='DEVICE'
    company=b.docs['Company','OPEN'];company.doctype='Company'
    device=Document(doctype='ZATCA Multiple Setting',name='DEVICE',custom_linked_doctype='OPEN',
        custom_zatca_native_chain='30000000-0000-4000-8000-000000000001' if native else None)
    b.docs['ZATCA Multiple Setting','DEVICE']=device
    b.frappe.get_meta=lambda dt:SimpleNamespace(has_field=lambda field:field in ('custom_zatca_native_chain','custom_unique_id'))
    monkeypatch.setattr(field_compat,'field_exists',lambda dt,name:name in (
        'custom_phase_1_or_2','custom_zatca_invoice_enabled','custom_send_invoice_to_zatca','custom_b2c'))
    b.frappe.has_permission=lambda dt,operation,*,doc,user,raise_exception=True:True
    b.frappe.flags={}
    b.frappe.db.before_commit=Callbacks();b.frappe.db.after_commit=Callbacks();b.frappe.db.after_rollback=Callbacks()
    parent=Mock();monkeypatch.setattr(submission_intent,'ParentIntent',parent)
    def submit():
        doc.docstatus=1
        inspect.unwrap(sign_invoice.zatca_background_on_submit)(doc)
    doc.submit=Mock(side_effect=submit)
    draft.submit_draft(doc,runtime=b.frappe,translate=str,operation=operation)
    assert deferred.is_invoice_submission_deferred(b.frappe,doc.doctype,doc.name) is native
    if native:
        parent.assert_called_once_with(b.frappe,'Sales Invoice',doc.name,intent=operation)
        assert len(b.frappe.db.before_commit.calls)==len(b.frappe.db.after_commit.calls)==1
    else:
        parent.assert_not_called()
        assert not b.frappe.db.after_commit.calls
    for (module_name,_),route in b.routes.items():
        if module_name==sign_invoice.__name__:route.assert_not_called()
    b.frappe.db.commit.assert_not_called();b.frappe.log_error.assert_not_called()


def test_early_native_branch_is_inert_outside_hook_and_rejects_retained_hook_before_selection(boundary,monkeypatch):
    from zatca_erpgulf.zatca_erpgulf import native_provider
    b=boundary;selection=Mock();monkeypatch.setattr(native_provider,'_selection',selection)
    assert deferred.maybe_defer_native_invoice_submission(b.invoice.doctype,b.invoice.name,runtime=b.app,translate=str) is False
    with deferred.invoice_submit_hook(b.invoice.doctype,b.invoice,runtime=b.app,translate=str):saved=copy_context()
    with pytest.raises(deferred.DeferredSubmissionError):
        saved.run(deferred.maybe_defer_native_invoice_submission,b.invoice.doctype,b.invoice.name,runtime=b.app,translate=str)
    selection.assert_not_called();b.app.enqueue.assert_not_called()
