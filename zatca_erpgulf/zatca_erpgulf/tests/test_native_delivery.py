"""Native delivery intent/settings and fresh-lock policy, no DB or authority."""

from contextlib import contextmanager
from contextvars import copy_context
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_delivery as delivery
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.ksa_compliance import field_compat


@pytest.fixture
def policy(monkeypatch):
    company=Document(doctype='Company',name='SYNTHETIC',custom_zatca_invoice_enabled=1,
        custom_phase_1_or_2='Phase-2',custom_send_invoice_to_zatca='Live',custom_start_time='09:00:00',custom_end_time='11:00:00')
    customer=Document(doctype='Customer',name='BUYER',b2c=1)
    monkeypatch.setattr(delivery,'get_alias_value',lambda group,doc,default:doc.get('b2c',default))
    monkeypatch.setattr(field_compat,'field_exists',lambda dt,name:hasattr(company,name))
    monkeypatch.setattr(delivery,'now_datetime',lambda:datetime(2026,11,19,10))
    return company,customer


@pytest.mark.parametrize('simplified,method,intent,action',[
    (True,'Live','entry','DISPATCH'),(True,'','submit','DISPATCH'),
    (True,'Batches','entry','PREPARE'),(True,'Batches','submit','PREPARE'),
    (True,'Background','entry','PREPARE'),(True,'Background','submit','PREPARE'),
    (True,'Batches','manual','DISPATCH'),(True,'Background','manual','DISPATCH'),
    (True,'Background','scheduled','DISPATCH'),(True,'Batches','scheduled','SKIP'),
    (False,'Batches','entry','DISPATCH'),(False,'Background','submit','DISPATCH'),
    (False,'Batches','manual','DISPATCH'),(False,'Background','scheduled','DISPATCH'),
])
def test_company_policy_is_preserved_across_entry_and_authorized_delivery_intents(policy,simplified,method,intent,action):
    company,customer=policy;customer.b2c=int(simplified);company.custom_send_invoice_to_zatca=method
    decision=delivery.delivery_decision(company,customer,intent)
    assert decision.action==action and decision.simplified is simplified


def test_scheduled_policy_rechecks_the_current_window_and_has_no_manual_window_restriction(policy,monkeypatch):
    company,customer=policy;company.custom_send_invoice_to_zatca='Background'
    monkeypatch.setattr(delivery,'now_datetime',lambda:datetime(2026,11,19,12))
    assert delivery.delivery_decision(company,customer,'scheduled').action=='SKIP'
    assert delivery.delivery_decision(company,customer,'manual').action=='DISPATCH'
    company.custom_start_time='INVALID'
    with pytest.raises(ValueError):delivery.delivery_decision(company,customer,'scheduled')


def test_unknown_simplified_submission_method_never_grants_transport(policy):
    company,customer=policy;company.custom_send_invoice_to_zatca='UNKNOWN'
    with pytest.raises(delivery.NativeDeliveryError):delivery.delivery_decision(company,customer,'entry')


@pytest.mark.parametrize('indicator,buyer,action',[('0200000',0,'PREPARE'),('0100000',1,'DISPATCH')])
def test_retained_document_classification_controls_delivery_after_a_buyer_flag_change(policy,indicator,buyer,action):
    company,customer=policy;company.custom_send_invoice_to_zatca='Batches';customer.b2c=buyer
    from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider import CLASSIFIED_XML
    original=CLASSIFIED_XML.replace(b'0200000',indicator.encode())
    decision=delivery.delivery_decision(company,customer,'entry',original_xml=original)
    assert decision.action==action and decision.simplified is indicator.startswith('02')


def test_a_retained_or_cross_site_context_cannot_authorize_another_operation(policy):
    company,customer=policy;source=Document(doctype='Sales Invoice',name='SYNTHETIC',company=company.name,customer=customer.name)
    runtime=SimpleNamespace(local=SimpleNamespace(site='fictional.invalid'),session=SimpleNamespace(user='operator'))
    expected=delivery.delivery_decision(company,customer,'entry')
    with delivery.native_delivery(runtime,source,'entry',expected):
        ctx=delivery.CURRENT.get();child=copy_context()
        ctx.require(runtime,source)
        runtime.local.site='other.invalid'
        with pytest.raises(delivery.NativeDeliveryError):ctx.require(runtime,source)
        runtime.local.site='fictional.invalid'
    with pytest.raises(delivery.NativeDeliveryError):child.run(ctx.require,runtime,source)
    assert delivery.CURRENT.get() is None


@pytest.mark.parametrize('change',['method','buyer','window','permission'])
def test_changed_policy_is_rejected_under_current_shared_master_reads(policy,change):
    company,customer=policy
    if change=='window':company.custom_send_invoice_to_zatca='Background'
    source=Document(doctype='Sales Invoice',name='SYNTHETIC',company=company.name,customer=customer.name)
    intent='scheduled' if change=='window' else 'entry'
    expected=delivery.delivery_decision(company,customer,intent)
    def permission(doctype,operation,*,doc,user,raise_exception=True):return change!='permission'
    runtime=SimpleNamespace(local=SimpleNamespace(site='fictional.invalid'),session=SimpleNamespace(user='operator'),
        get_doc=Mock(side_effect=lambda dt,name,**kwargs:company if dt=='Company' else customer),
        has_permission=permission)
    @contextmanager
    def preparing(tables):
        assert tables==frozenset(('tabCompany','tabCustomer'))
        yield
    owner=SimpleNamespace(preparing=preparing,actor='operator')
    scope=SimpleNamespace(runtime=runtime,prepared_source=source,confirm_current=Mock())
    if change=='method':company.custom_send_invoice_to_zatca='Batches'
    elif change=='buyer':customer.b2c=0
    elif change=='window':company.custom_end_time='09:30:00'
    with delivery.native_delivery(runtime,source,intent,expected):
        with pytest.raises(delivery.NativeDeliveryError):delivery.confirm_delivery_policy(scope,owner,dispatch=True)
    assert all(call.kwargs['for_update'] is True for call in runtime.get_doc.call_args_list)
    scope.confirm_current.assert_not_called()
