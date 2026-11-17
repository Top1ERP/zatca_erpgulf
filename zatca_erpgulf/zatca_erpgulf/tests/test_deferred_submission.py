"""Native hook handoff, fake transaction callbacks/queue; no Redis/site or HTTP."""

from contextvars import copy_context
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import deferred_submission as deferred
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import confirm_issuing_transport
from zatca_erpgulf.zatca_erpgulf.tests.test_item_template_mode import ROUTES, isolated, route_boundary
from zatca_erpgulf.ksa_compliance import field_compat


class Record(SimpleNamespace):
    def get(self, name, default=None):return getattr(self, name, default)


class Callbacks:
    def __init__(self):self.calls=[]
    def add(self, fn):self.calls.append(fn)
    def run(self):
        calls,self.calls=self.calls,[]
        for fn in calls:fn()


@pytest.fixture
def boundary(monkeypatch):
    invoice=Record(doctype='Sales Invoice',name='LOCAL',company='Synthetic',docstatus=1)
    company=Record(doctype='Company',name='Synthetic',custom_zatca_invoice_enabled=1,custom_phase_1_or_2='Phase-2')
    def permission(doctype, operation, *, doc, user, print_logs=True):
        assert print_logs is False
        return True
    def throw(message, *, exc=None):raise exc
    app=SimpleNamespace(local=SimpleNamespace(site='fictional.invalid'),session=SimpleNamespace(user='operator'),flags={},
        db=SimpleNamespace(after_commit=Callbacks(),after_rollback=Callbacks(),commit=Mock(),rollback=Mock()),
        get_doc=Mock(side_effect=lambda dt,name:company if dt=='Company' else invoice),
        has_permission=permission,throw=Mock(side_effect=throw),log_error=Mock(),enqueue=Mock())
    app.get_meta = lambda doctype:SimpleNamespace(get_field=lambda name:name if hasattr(company,name) else None)
    app.db.exists = Mock(return_value=False)
    monkeypatch.setattr(field_compat, 'frappe', app)
    return SimpleNamespace(app=app,invoice=invoice,company=company)


def register(b):
    with deferred.invoice_submit_hook(b.invoice.doctype,b.invoice,runtime=b.app,translate=lambda text:text):
        return deferred.maybe_defer_invoice_submission(b.invoice.doctype,b.invoice.name,runtime=b.app,translate=lambda text:text)


@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice'])
def test_registration_does_not_touch_queue_and_only_committed_callback_enqueues(boundary,doctype):
    b=boundary;b.invoice.doctype=doctype
    assert register(b) is True
    assert deferred.is_invoice_submission_deferred(b.app,doctype,b.invoice.name)
    b.app.enqueue.assert_not_called();b.app.db.commit.assert_not_called()
    b.app.db.after_commit.run()
    call=b.app.enqueue.call_args
    assert call.args==(deferred.METHOD,)
    assert call.kwargs['doctype']==doctype and call.kwargs['invoice_name']==b.invoice.name
    assert call.kwargs['now'] is False and call.kwargs['is_async'] is True
    assert call.kwargs['enqueue_after_commit'] is False and call.kwargs['deduplicate'] is True
    assert not deferred.is_invoice_submission_deferred(b.app,doctype,b.invoice.name)
    assert all(isinstance(v,(str,bool,int)) for v in call.kwargs.values())


def test_rollback_invalidates_even_a_retained_commit_callback(boundary):
    b=boundary;register(b)
    retained=b.app.db.after_commit.calls[0]
    b.app.db.after_rollback.run()
    retained()
    b.app.enqueue.assert_not_called()
    assert not deferred.is_invoice_submission_deferred(b.app,b.invoice.doctype,b.invoice.name)


def test_callback_registration_partial_failure_cannot_send_later(boundary):
    b=boundary
    b.app.db.after_rollback.add=Mock(side_effect=RuntimeError('PRIVATE-DRIVER'))
    with pytest.raises(deferred.DeferredSubmissionError):register(b)
    b.app.db.after_commit.run()
    b.app.enqueue.assert_not_called()
    assert 'PRIVATE-DRIVER' not in b.app.log_error.call_args.kwargs['message']


def test_duplicate_hook_producer_calls_register_only_one_pending_job(boundary):
    b=boundary
    assert register(b) and register(b)
    assert len(b.app.db.after_commit.calls)==1
    b.app.db.after_commit.run()
    b.app.enqueue.assert_called_once()


@pytest.mark.parametrize('change',['site','actor','migration'])
def test_commit_callback_cannot_change_site_actor_or_enter_migration_fallback(boundary,change):
    b=boundary;register(b)
    if change=='site':b.app.local.site='different.invalid'
    if change=='actor':b.app.session.user='Administrator'
    if change=='migration':b.app.local.flags=SimpleNamespace(in_migrate=True)
    with pytest.raises(deferred.DeferredSubmissionError):b.app.db.after_commit.run()
    b.app.enqueue.assert_not_called()


def test_deep_commit_inside_submit_hook_cannot_release_transport(boundary):
    b=boundary
    with deferred.invoice_submit_hook(b.invoice.doctype,b.invoice,runtime=b.app,translate=lambda text:text):
        deferred.maybe_defer_invoice_submission(b.invoice.doctype,b.invoice.name,runtime=b.app,translate=lambda text:text)
        with pytest.raises(deferred.DeferredSubmissionError):b.app.db.after_commit.run()
    b.app.enqueue.assert_not_called()


def test_retained_hook_context_is_invalid_after_exit(boundary):
    b=boundary
    with deferred.invoice_submit_hook(b.invoice.doctype,b.invoice,runtime=b.app,translate=lambda text:text):child=copy_context()
    with pytest.raises(deferred.DeferredSubmissionError):
        child.run(deferred.maybe_defer_invoice_submission,b.invoice.doctype,b.invoice.name,runtime=b.app,translate=lambda text:text)
    b.app.enqueue.assert_not_called()


def test_transport_fence_blocks_an_extension_bypassing_native_entry_deferral(boundary):
    b=boundary
    with deferred.invoice_submit_hook(b.invoice.doctype,b.invoice,runtime=b.app,translate=lambda text:text):
        with pytest.raises(deferred.DeferredSubmissionError):confirm_issuing_transport('unused',b.invoice,runtime=b.app)
    b.app.enqueue.assert_not_called()


@pytest.mark.parametrize('route',ROUTES[:6])
def test_all_native_generators_defer_before_metadata_and_party_counter_builders(route_boundary,monkeypatch,route):
    b=route_boundary;module,fn,doctype,_=route;b.doc.doctype=doctype;b.doc.docstatus=1
    monkeypatch.setattr(field_compat, 'frappe', b.app)
    b.app.db.after_commit=Callbacks();b.app.db.after_rollback=Callbacks();b.app.enqueue=Mock()
    with deferred.invoice_submit_hook(doctype,b.doc,runtime=b.app,translate=lambda text:text):
        inspect.unwrap(getattr(module,fn))(b.doc.name)
    module.salesinvoice_data.assert_not_called()
    module.sign_invoice_xml.assert_not_called()
    b.doc.db_set.assert_not_called();b.app.db.commit.assert_not_called();b.app.enqueue.assert_not_called()
    b.app.db.after_commit.run();b.app.enqueue.assert_called_once()


@pytest.mark.parametrize('denied',[('Sales Invoice','read'),('Sales Invoice','write'),('Company','read')])
def test_saved_permissions_precede_callback_registration(boundary,denied):
    b=boundary
    def permission(doctype,operation,*,doc,user,raise_exception=True):
        return (doctype,operation)!=denied
    b.app.has_permission=permission
    with pytest.raises(deferred.DeferredSubmissionError):register(b)
    assert b.app.db.after_commit.calls==[]
    b.app.enqueue.assert_not_called()


def test_queue_invocation_failure_is_unknown_not_a_no_send_claim(boundary):
    b=boundary;register(b)
    b.app.enqueue.side_effect = RuntimeError('PRIVATE-QUEUE-CREDENTIALS')
    with pytest.raises(deferred.DeferredSubmissionError) as caught:b.app.db.after_commit.run()
    assert str(caught.value) == deferred.QUEUE_UNKNOWN
    assert 'No request was sent' not in str(caught.value)
    assert 'PRIVATE-QUEUE' not in b.app.log_error.call_args.kwargs['message']
    assert caught.value.__context__ is None


@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice'])
def test_intra_company_hook_output_does_not_commit_erp_parent_transaction(boundary,monkeypatch,doctype):
    from zatca_erpgulf.zatca_erpgulf import sign_invoice, pos_sign
    b=boundary;b.invoice.doctype=doctype;b.invoice.customer='BUYER'
    b.invoice.save=Mock();b.company.tax_id='SAME-TAXPAYER';b.company.abbr='TC'
    customer=Record(doctype='Customer',name='BUYER',tax_id=b.company.tax_id)
    def get_doc(kind,name):
        return b.company if kind=='Company' else customer if kind=='Customer' else b.invoice
    b.app.get_doc.side_effect=get_doc
    b.app.db.get_value=Mock(return_value='TC');b.app.db.set_value=Mock()
    module=sign_invoice if doctype=='Sales Invoice' else pos_sign
    monkeypatch.setattr(module,'frappe',b.app);monkeypatch.setattr(module,'_',lambda text:text)
    inspect.unwrap(module.zatca_background_on_submit)(b.invoice)
    b.app.db.set_value.assert_called_once_with(doctype,b.invoice.name,{
        'custom_zatca_status':'Intra-company transfer','custom_zatca_full_response':'Intra-company transfer',
    },update_modified=False)
    b.invoice.save.assert_not_called();b.app.db.commit.assert_not_called();b.app.enqueue.assert_not_called()
    assert b.app.db.after_commit.calls==[] and b.invoice.custom_zatca_status=='Intra-company transfer'


@pytest.mark.parametrize('adapter',[
    ('submit_xml_qr_notmultiple','submit_sales_invoice_simplifeid','Sales Invoice'),
    ('submit_poswithqr_notmultiple','submit_pos_invoice_simplifeid','POS Invoice'),
    ('sales_invoice_with_xmlqr','submit_sales_invoice_withxmlqr','Sales Invoice'),
    ('pos_submit_with_xml_qr','submit_pos_withxmlqr','POS Invoice'),
])
def test_existing_xml_hook_defers_before_file_extraction(boundary,monkeypatch,adapter):
    import importlib
    module_name,fn,doctype=adapter
    module=importlib.import_module('zatca_erpgulf.zatca_erpgulf.'+module_name)
    b=boundary;b.invoice.doctype=doctype
    monkeypatch.setattr(module,'frappe',b.app);monkeypatch.setattr(module,'_',lambda text:text)
    # Any native file extraction here would be a test failure before commit.
    for attr in ('extract_uuid_and_invoicehash','extract_uuid_and_invoicehash_simplifeid','extract_invoice_data_from_field'):
        if hasattr(module,attr):monkeypatch.setattr(module,attr,Mock(side_effect=AssertionError('No file read before commit')))
    with deferred.invoice_submit_hook(doctype,b.invoice,runtime=b.app,translate=lambda text:text):
        getattr(module,fn)(b.invoice,'/PRIVATE-UNREAD.xml',b.invoice.name)
    b.app.enqueue.assert_not_called()
    b.app.db.after_commit.run();b.app.enqueue.assert_called_once()


@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice'])
@pytest.mark.parametrize('change',['none','phase','disabled','cancelled','permission','reported','cleared'])
def test_worker_rechecks_saved_policy_and_permissions_before_legacy_preparation(boundary,doctype,change):
    b=boundary;b.invoice.doctype=doctype;process=Mock(return_value='LOCAL-PROCESS-RESULT')
    if change=='phase':b.company.custom_phase_1_or_2='Phase-1'
    if change=='disabled':b.company.custom_zatca_invoice_enabled=0
    if change=='cancelled':b.invoice.docstatus=2
    if change in ('reported','cleared'):b.invoice.custom_zatca_status=change.upper()
    if change=='permission':
        def denied(doctype,operation,*,doc,user,print_logs=True):return False
        b.app.has_permission=denied
    def run():
        return deferred._execute_saved_invoice(doctype,b.invoice.name,runtime=b.app,translate=lambda text:text,process=process)
    if change in ('cancelled','permission'):
        with pytest.raises(deferred.DeferredSubmissionError):run()
    else:
        result=run()
        if change=='none':assert result=='LOCAL-PROCESS-RESULT'
        else:assert result['status']=='SKIPPED'
    if change=='none':process.assert_called_once_with(b.invoice)
    else:process.assert_not_called()
    b.app.db.commit.assert_not_called();b.app.enqueue.assert_not_called()
