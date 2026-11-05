"""Derived POS-return paid stage on NEW guard-owned TCP-disabled SQL only."""
import json
import os
import pickle
from dataclasses import replace
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_pos_adjustments as adjustments
from zatca_erpgulf.zatca_erpgulf.calculation_pos_return_paid import PosReturnPaidCalculation
from zatca_erpgulf.zatca_erpgulf.calculation_payments import PaidAmountCalculation,PAID_FIELDS
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_payments_mariadb import native_case
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_adjustments import primary_pos_methods,redistribution_probe
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema,defaults_schema,financial_schema,metadata_schema,isolated_server,connections,untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access_mariadb import field_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import empty_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_rounding_stage_mariadb import selected_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator,operator

pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='NEW guarded temporary SQL only; no tenant or authority access')


def setup_source(operator,connections,major):
    case=native_case(operator,connections,flags=(1,1,1))
    source=case.service.capture_payment_calculation_context(case.invoice.name,erp_major=major)
    paid=PaidAmountCalculation(source,'CALCULATED',(('conversion_rate',1.23456789),('loyalty_amount',1.255)),
        tuple((name,amount) for (name,_),amount in zip(source.payment_types,(-120.0,0.0,0.0))))
    return case,paid


def context(paid,foreign,amount,found):
    header=dict(json.loads(paid.source.stage.numeric.view.financial.financial._payload)['header'])
    currency=header['currency'][1];profile=header.get('pos_profile',['absent'])
    profile=None if profile in (['absent'],['null']) else profile[1]
    party='USD' if foreign else currency
    selected=sum(row[2] if foreign else row[1] for row in paid.payments)
    queried=amount-selected>0
    lookup=adjustments.DefaultMopObservation(queried,found if queried else False,'Cash' if queried and found else None)
    redistribution=adjustments.DefaultMopRedistributionCalculation(currency,party,profile,amount,paid.payments,lookup)
    tail=adjustments.PosTailCalculation(adjustments.PosTailInputs('Sales Invoice',1,1,0,profile,0,17.0),adjustments.PosLimitObservation(False,None))
    return tail,redistribution


@pytest.mark.parametrize('major',[15,16])
@pytest.mark.parametrize('foreign',[False,True])
def test_actual_redistribution_then_shared_paid_kernel_without_outstanding_recalculation(defaults_operator,connections,upstream16,monkeypatch,primary_pos_methods,major,foreign):
    case,paid=setup_source(defaults_operator,connections,major)
    for amount,found in ((-115.0,True),(-115.0,False),(-1000.0,True)):
        tail,redistribution=context(paid,foreign,amount,found)
        calculation=PosReturnPaidCalculation(paid,tail,redistribution,'NEW-PAYMENT' if redistribution.replaces else None)
        raw=paid.source.stage.method.rounding.value
        probe=framework(major,upstream16,monkeypatch,setting=raw)
        actual=redistribution_probe(redistribution.currency,redistribution.party_currency,redistribution.pos_profile,amount,paid.payments,found,'Cash',primary_pos_methods[major],probe.flt)
        redistribution.require_match(total_paid=actual.total,pending=actual.pending,replaced=actual.replaced,
            append_values=actual.append_values,calls=actual.calls,setting_trace=())
        probe.runtime.get_system_settings.assert_not_called()
        doc=actual.doc;doc.is_pos=1;doc.is_return=1;doc.redeem_loyalty_points=1
        doc.conversion_rate=1.23456789;doc.loyalty_amount=1.255;doc.outstanding_amount=17.0
        trace=[];precisions={name:proof.precision.precision for name,proof in zip(PAID_FIELDS,paid.source.stage.fields)}
        doc.precision=lambda name:(trace.append((name,precisions[name])),precisions[name])[-1]
        controller('calculate_paid_amount',major,{'flt':probe.flt})(type('Owner',(),{'doc':doc})())
        calculation.require_match(payments=tuple((row.name,row.amount,row.base_amount) for row in doc.payments),
            totals=tuple((name,getattr(doc,name)) for name in PAID_FIELDS),
            setting_trace=tuple((c.args[0],raw) for c in probe.runtime.get_system_settings.call_args_list),precision_trace=tuple(trace))
        assert doc.outstanding_amount==17.0
        if redistribution.replaces:assert len(doc.payments)==1 and doc.payments[0].name=='NEW-PAYMENT'
        else:assert len(doc.payments)==len(paid.payments)
    assert len(case.opened)==1
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator,case)


def test_derived_rows_require_exact_original_rows_profile_and_new_identity(defaults_operator,connections):
    case,paid=setup_source(defaults_operator,connections,16)
    tail,redistribution=context(paid,False,-115.0,True)
    result=PosReturnPaidCalculation(paid,tail,redistribution,'NEW-PAYMENT')
    for changes in (dict(appended_row_name=None),dict(appended_row_name=paid.payments[0][0]),
            dict(redistribution=replace(redistribution,pos_profile='OTHER')),
            dict(redistribution=replace(redistribution,rows=tuple(reversed(redistribution.rows))))):
        with pytest.raises(adjustments.PosAdjustmentError):replace(result,**changes)
    with pytest.raises(adjustments.PosAdjustmentError):
        replace(result,tail=adjustments.PosTailCalculation(adjustments.PosTailInputs('Sales Invoice',1,0,0,None,0,17.0),adjustments.PosLimitObservation(False,None)))
    for value in (result,):
        assert 'NEW-PAYMENT' not in repr(value)
        with pytest.raises(TypeError):pickle.dumps(value)
    untouched(defaults_operator,case)
