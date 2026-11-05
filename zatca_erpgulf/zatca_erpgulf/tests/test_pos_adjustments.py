"""Post-balance POS and default-payment comparisons with primary method ASTs."""
import ast
import itertools
import pickle
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_pos_adjustments as calc
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller_text
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


@pytest.fixture(scope='module')
def primary_pos_methods():
    methods={}
    for major in (15,16):
        tree=ast.parse(controller_text('calculate_outstanding_amount',major)).body[0]
        outer=tree.body[-1]
        assert isinstance(outer,ast.If) and isinstance(outer.body[-1],ast.If) and isinstance(outer.body[-2],ast.If)
        tail=ast.parse('def pos_tail(self,total_amount_to_pay):\n pass').body[0]
        tail.body=outer.body[-2:]
        default=ast.parse(controller_text('set_total_amount_to_default_mop',major)).body[0]
        # A test-only epilogue exposes the actual arithmetic locals. Original
        # statements, conditions, lookups and writes remain intact and run once.
        default.body.append(ast.parse('return total_paid_amount,pending_amount').body[0])
        namespace={}
        module=ast.fix_missing_locations(ast.Module(body=[tail,default],type_ignores=[]))
        exec(compile(module,'primary-pos-suffix','exec'),namespace)
        methods[major]=namespace
    return methods


def tail_probe(inputs,raw_limit,namespace,flt):
    calls=[];assignments=[];lookups=[]
    class Root:
        def __setattr__(self,name,value):
            object.__setattr__(self,name,value)
            if name=='write_off_outstanding_amount_automatically' and getattr(self,'ready',False):
                calls.append('assign_automatic_write_off');assignments.append(value)
        def get(self,name):return getattr(self,name,None)
    doc=Root();doc.ready=False
    doc.doctype=inputs.doctype;doc.is_pos=inputs.is_pos;doc.is_return=inputs.is_return
    doc.is_consolidated=inputs.is_consolidated;doc.pos_profile=inputs.pos_profile
    doc.outstanding_amount=inputs.outstanding;doc.write_off_outstanding_amount_automatically=inputs.automatic_before;doc.ready=True
    def get_value(dt,name,field):
        assert (dt,name,field)==('POS Profile',inputs.pos_profile,'write_off_limit')
        lookups.append(True);calls.append('get_write_off_limit');return raw_limit
    namespace['flt']=flt;namespace['frappe']=SimpleNamespace(db=SimpleNamespace(get_value=get_value))
    owner=SimpleNamespace(doc=doc,set_total_amount_to_default_mop=lambda value:calls.append('redistribute_default_payment'),
        calculate_paid_amount=lambda:calls.append('calculate_paid_amount'))
    namespace['pos_tail'](owner,0.0)
    return SimpleNamespace(calls=tuple(calls),queried=bool(lookups),assigns=bool(assignments),
        automatic=doc.write_off_outstanding_amount_automatically,redistributes='redistribute_default_payment' in calls)


@pytest.mark.parametrize('major',[15,16])
@pytest.mark.parametrize('doctype',['Sales Invoice','POS Invoice'])
@pytest.mark.parametrize('flags',tuple(itertools.product((None,0,1),repeat=3)))
@pytest.mark.parametrize('profile',[None,'','POS-TEST'])
def test_primary_tail_lazy_limit_exact_boundary_and_unchanged_flags(monkeypatch,upstream16,primary_pos_methods,major,doctype,flags,profile):
    probe=framework(major,upstream16,monkeypatch,setting=None)
    pos,returned,consolidated=flags
    for before in (None,0,1):
        for raw,outstanding in ((None,None),(Decimal('0'),None),(Decimal('2.00'),-2.0),
                (Decimal('2.00'),2.0),(Decimal('2.00'),2.0000000001),(Decimal('-2'),0.0)):
            inputs=calc.PosTailInputs(doctype,pos,returned,consolidated,profile,before,outstanding)
            actual=tail_probe(inputs,raw,primary_pos_methods[major],probe.flt)
            result=calc.PosTailCalculation(inputs,calc.PosLimitObservation(actual.queried,raw if actual.queried else None))
            result.require_match(automatic_after=actual.automatic,assigns_automatic=actual.assigns,
                redistributes=actual.redistributes,calls=actual.calls,setting_trace=())
    probe.runtime.get_system_settings.assert_not_called()


def redistribution_probe(currency,party,profile,amount,rows,found,mop,namespace,flt):
    calls=[];appended=[];lookups=[]
    class Root:
        def __setattr__(self,name,value):
            object.__setattr__(self,name,value)
            if name=='payments' and getattr(self,'ready',False):calls.append('replace_payments')
        def get(self,name):return getattr(self,name,None)
        def append(self,field,values):
            assert field=='payments';calls.append('append_payment');appended.append(tuple(values.items()))
            self.payments.append(SimpleNamespace(name='NEW-PAYMENT',base_amount=0.0,type=None,**values))
    doc=Root();doc.ready=False;doc.currency=currency;doc.party_account_currency=party;doc.pos_profile=profile
    doc.payments=[SimpleNamespace(name=name,amount=a,base_amount=b) for name,a,b in rows];original=doc.payments;doc.ready=True
    def get_value(dt,filters,fields,*,as_dict):
        assert dt=='POS Payment Method' and filters=={'parent':profile,'default':1} and type(filters['default']) is int
        assert fields==['mode_of_payment'] and type(as_dict) is int and as_dict==1
        lookups.append(True);calls.append('get_default_mop')
        return SimpleNamespace(mode_of_payment=mop) if found else None
    namespace['flt']=flt;namespace['frappe']=SimpleNamespace(db=SimpleNamespace(get_value=get_value))
    total,pending=namespace['set_total_amount_to_default_mop'](SimpleNamespace(doc=doc),amount)
    return SimpleNamespace(doc=doc,total=total,pending=pending,queried=bool(lookups),calls=tuple(calls),
        replaced=doc.payments is not original,append_values=appended[0] if appended else None)


ROWS=((),(('a',1.0,1.5),), (('a',0.1,0.3),('b',0.2,0.6)),
    (('a',-120.0,-180.0),), (('a',1e16,2e16),('b',1.0,2.0),('c',-1e16,-2e16)))


@pytest.mark.parametrize('major',[15,16])
@pytest.mark.parametrize('foreign',[False,True])
@pytest.mark.parametrize('rows',ROWS)
@pytest.mark.parametrize('amount',[-115.0,-0.0,0.3,10.0])
def test_default_mop_primary_sum_units_pending_and_row_replacement(monkeypatch,upstream16,primary_pos_methods,major,foreign,rows,amount):
    probe=framework(major,upstream16,monkeypatch,setting=None)
    party='USD' if foreign else 'SAR'
    for found,mop in ((False,None),(True,'Cash'),(True,None),(True,'')):
        actual=redistribution_probe('SAR',party,None,amount,rows,found,mop,primary_pos_methods[major],probe.flt)
        lookup=calc.DefaultMopObservation(actual.queried,found if actual.queried else False,mop if actual.queried and found else None)
        result=calc.DefaultMopRedistributionCalculation('SAR',party,None,amount,rows,lookup)
        result.require_match(total_paid=actual.total,pending=actual.pending,replaced=actual.replaced,
            append_values=actual.append_values,calls=actual.calls,setting_trace=())
    probe.runtime.get_system_settings.assert_not_called()


@pytest.mark.parametrize('foreign',[False,True])
def test_selected_null_amount_is_not_silently_coerced(monkeypatch,upstream16,primary_pos_methods,foreign):
    probe=framework(16,upstream16,monkeypatch,setting=None)
    party='USD' if foreign else 'SAR';rows=(('a',None if not foreign else 1.0,None if foreign else 1.0),)
    with pytest.raises(TypeError):redistribution_probe('SAR',party,'PROFILE',10.0,rows,False,None,primary_pos_methods[16],probe.flt)
    with pytest.raises(calc.PosAdjustmentError):calc.DefaultMopRedistributionCalculation('SAR',party,'PROFILE',10.0,rows,calc.DefaultMopObservation(False,False,None))


def test_strict_types_no_optimistic_lookup_and_observation_reconstruction():
    inputs=calc.PosTailInputs('Sales Invoice',1,0,1,'PROFILE',1,2.0)
    result=calc.PosTailCalculation(inputs,calc.PosLimitObservation(True,Decimal('2.00')))
    valid=dict(automatic_after=1,assigns_automatic=True,redistributes=False,calls=result.calls,setting_trace=())
    result.require_match(**valid)
    for changes in (dict(assigns_automatic=1),dict(automatic_after=True),dict(calls=tuple(reversed(result.calls))),dict(setting_trace=(('rounding_method',None),))):
        with pytest.raises(calc.PosAdjustmentError):result.require_match(**(valid|changes))
    with pytest.raises(calc.PosAdjustmentError):calc.PosTailCalculation(inputs,calc.PosLimitObservation(False,None))
    for value in (True,1.0,'1',2):
        with pytest.raises(calc.PosAdjustmentError):replace(inputs,is_pos=value)
    redistribution=calc.DefaultMopRedistributionCalculation('SAR','SAR','PROFILE',10.0,(),calc.DefaultMopObservation(True,True,'Cash'))
    for changes in (dict(rows=(('a',True,1.0),)),dict(lookup=calc.DefaultMopObservation(False,False,None)),dict(amount_to_pay=Decimal('10'))):
        with pytest.raises(calc.PosAdjustmentError):replace(redistribution,**changes)
    changed=replace(redistribution)
    object.__setattr__(changed,'append_values',(*changed.append_values[:2],('default',1.0)))
    with pytest.raises(calc.PosAdjustmentError):
        changed.require_match(total_paid=redistribution.total_paid,pending=redistribution.pending,replaced=True,
            append_values=redistribution.append_values,calls=redistribution.calls,setting_trace=())
    for value in (inputs,result,redistribution):
        assert 'PROFILE' not in repr(value)
        with pytest.raises(TypeError):pickle.dumps(value)
