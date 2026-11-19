"""Collection-only projection over typed native source observations; no ERP/SQL."""

from copy import deepcopy
from decimal import Decimal
from datetime import date,datetime,time,timedelta,timezone

import pytest

from zatca_erpgulf.zatca_erpgulf.issuing_observation import freeze_native_value
from zatca_erpgulf.zatca_erpgulf.publication_source import publication_source_sha256,render_source_sha256
from zatca_erpgulf.zatca_erpgulf.native_preparation import source_observation_sha256


def invoice(doctype='Sales Invoice'):
    name='SYNTHETIC'
    def child(kind,field,**values):
        return dict(doctype=kind,name=kind+'-ROW',parenttype=doctype,parent=name,parentfield=field,idx=1,**values)
    return dict(doctype=doctype,name=name,company='FICTIONAL',customer='BUYER',docstatus=1,
        status='Unpaid',outstanding_amount=Decimal('115.00'),grand_total=Decimal('115.00'),
        net_total=Decimal('100.00'),paid_amount=Decimal('0.00'),base_paid_amount=Decimal('0.00'),
        total_taxes_and_charges=Decimal('15.00'),conversion_rate=Decimal('3.75'),
        currency='USD',apply_discount_on='Net Total',discount_amount=Decimal('0.00'),
        items=[child('Sales Invoice Item','items',amount=Decimal('100.00'),net_amount=Decimal('100.00'),
            paid_amount=Decimal('7.00'),item_tax_rate='{"VAT":15}')],
        taxes=[child('Sales Taxes and Charges','taxes',tax_amount=Decimal('15.00'),rate=Decimal('15'))],
        payments=[child('Sales Invoice Payment','payments',amount=Decimal('0.00'),mode_of_payment='Cash')],
        advances=[child('Sales Invoice Advance','advances',allocated_amount=Decimal('0.00'))],
        payment_schedule=[child('Payment Schedule','payment_schedule',payment_term='NET30',
            due_date='2026-12-01',payment_amount=Decimal('115.00'),base_payment_amount=Decimal('431.25'),
            paid_amount=Decimal('0.00'),base_paid_amount=Decimal('0.00'),outstanding=Decimal('115.00'),
            base_outstanding=Decimal('431.25'),discounted_amount=Decimal('0.00'),discount=Decimal('2.00'))],
        custom_zatca_advance_prepaid_amount=Decimal('0.00'),custom_unknown_fiscal_field='KEEP')


def digest(doc):
    return publication_source_sha256((doc['doctype'],doc['name']),freeze_native_value(doc))


@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice'])
@pytest.mark.parametrize('field,value',[('outstanding_amount',Decimal('0.00')),('status','Paid'),
    ('status','Overdue'),('status','Credit Note Issued')])
def test_named_header_collection_changes_do_not_change_fiscal_projection(doctype,field,value):
    original=invoice(doctype);current=deepcopy(original);current[field]=value
    assert digest(original)==digest(current)
    assert source_observation_sha256((doctype,original['name']),freeze_native_value(original))!=source_observation_sha256(
        (doctype,current['name']),freeze_native_value(current))


@pytest.mark.parametrize('field',['paid_amount','base_paid_amount','discounted_amount','outstanding','base_outstanding'])
def test_only_identified_payment_schedule_collection_metrics_can_change(field):
    original=invoice();current=deepcopy(original);current['payment_schedule'][0][field]=Decimal('44.12')
    assert digest(original)==digest(current)


@pytest.mark.parametrize('field,value',[
    ('grand_total',Decimal('114.99')),('net_total',Decimal('99.99')),('paid_amount',Decimal('115')),
    ('base_paid_amount',Decimal('431.25')),('currency','SAR'),('conversion_rate',Decimal('3.76')),
    ('discount_amount',Decimal('1')),('apply_discount_on','Grand Total'),('customer','OTHER'),
    ('company','OTHER'),('docstatus',2),('custom_zatca_advance_prepaid_amount',Decimal('1')),
    ('custom_unknown_fiscal_field','CHANGED')])
def test_fiscal_and_unknown_fields_remain_exactly_observed(field,value):
    original=invoice();current=deepcopy(original);current[field]=value
    assert digest(original)!=digest(current)


@pytest.mark.parametrize('table,field,value',[
    ('items','amount',Decimal('99.99')),('items','paid_amount',Decimal('1')),
    ('items','item_tax_rate','{"VAT":5}'),('taxes','tax_amount',Decimal('14.99')),
    ('payments','amount',Decimal('1')),('advances','allocated_amount',Decimal('1')),
    ('payment_schedule','payment_amount',Decimal('114')),('payment_schedule','base_payment_amount',Decimal('430')),
    ('payment_schedule','discount',Decimal('1')),('payment_schedule','due_date','2026-12-02'),
    ('payment_schedule','payment_term','OTHER'),('payment_schedule','name','OTHER')])
def test_child_amount_terms_identity_and_unrelated_paid_fields_cannot_hide_drift(table,field,value):
    original=invoice();current=deepcopy(original);current[table][0][field]=value
    assert digest(original)!=digest(current)


@pytest.mark.parametrize('identity_field',['doctype','parent','parenttype','parentfield'])
def test_schedule_exemption_needs_the_native_child_identity(identity_field):
    original=invoice();original['payment_schedule'][0][identity_field]='OTHER'
    current=deepcopy(original);current['payment_schedule'][0]['paid_amount']=Decimal('1')
    assert digest(original)!=digest(current)


def test_pos_schedule_and_custom_nested_fields_do_not_gain_the_sales_schedule_exception():
    original=invoice('POS Invoice');current=deepcopy(original)
    current['payment_schedule'][0]['paid_amount']=Decimal('1')
    assert digest(original)!=digest(current)
    original=invoice();original['custom_nested']={'status':'ORIGINAL','outstanding_amount':Decimal('1')}
    current=deepcopy(original);current['custom_nested']['outstanding_amount']=Decimal('0')
    assert digest(original)!=digest(current)


@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice'])
def test_consolidated_invoice_is_only_a_pos_bookkeeping_reference(doctype):
    original=invoice(doctype);original['consolidated_invoice']=None
    current=deepcopy(original);current['consolidated_invoice']='CONSOLIDATED-SALES'
    assert (digest(original)==digest(current)) is (doctype=='POS Invoice')


@pytest.mark.parametrize('change',['removed','added','reordered','scale','type'])
def test_shape_order_and_fiscal_numeric_types_remain_significant(change):
    original=invoice();current=deepcopy(original)
    if change=='removed':current['payment_schedule']=[]
    elif change=='added':current['payment_schedule'].append(deepcopy(current['payment_schedule'][0]))
    elif change=='reordered':
        second=deepcopy(original['payment_schedule'][0]);second['name']='SECOND';second['idx']=2
        original['payment_schedule'].append(second)
        current=deepcopy(original);current['payment_schedule'].reverse()
    elif change=='scale':current['grand_total']=Decimal('115.0')
    else:current['grand_total']=115.0
    assert digest(original)!=digest(current)


def test_partial_adapter_cannot_assert_native_publication_provenance():
    assert publication_source_sha256(('Sales Invoice','SYNTHETIC'),(('grand_total',('str','115')),)) is None


def test_different_source_identity_cannot_select_a_projection():
    with pytest.raises(ValueError,match='publication_source_identity'):
        publication_source_sha256(('Sales Invoice','OTHER'),freeze_native_value(invoice()))


@pytest.mark.parametrize('value',[date(2026,9,27),datetime(2026,9,27,9,5,42),
    datetime(2026,9,27,9,5,42,tzinfo=timezone.utc),time(9,5,42),
    timedelta(hours=9,minutes=5,seconds=42),timedelta(hours=49,seconds=1,microseconds=123)])
def test_render_dates_follow_actual_framework_json_but_do_not_change_fiscal_observation(value):
    from frappe.utils.response import json_handler
    original=invoice();original['posting_clock']=value
    transported=deepcopy(original);transported['posting_clock']=json_handler(value)
    original_observation=freeze_native_value(original);transported_observation=freeze_native_value(transported)
    identity=(original['doctype'],original['name'])
    assert render_source_sha256(identity,original_observation)==render_source_sha256(identity,transported_observation)
    assert publication_source_sha256(identity,original_observation)!=publication_source_sha256(identity,transported_observation)


@pytest.mark.parametrize('value',[115.0,'115.00',115,Decimal('115.0')])
def test_print_transport_projection_never_coerces_money(value):
    original=invoice();transported=deepcopy(original);transported['grand_total']=value
    identity=(original['doctype'],original['name'])
    assert render_source_sha256(identity,freeze_native_value(original))!=render_source_sha256(identity,freeze_native_value(transported))
