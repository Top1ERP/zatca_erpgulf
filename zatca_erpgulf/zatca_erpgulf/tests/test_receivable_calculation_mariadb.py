"""Receivable/write-off suffixes on NEW guard-owned TCP-disabled SQL only."""
from dataclasses import replace
from decimal import Decimal
import os
import pickle
from types import SimpleNamespace
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_receivable as calc
from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.source_metadata import WRITE_OFF_PROFILE, PROPERTIES
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_limit_mariadb import native_case as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_party_access_mariadb import observation
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta,Definition,project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
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
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator,operator,one_failure,InspectionFailed,PermissionDenied,
)

pytestmark=pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB")!="1",reason="NEW guard-owned SQL only; no tenant or authority access")


def native_case(operator,connections,*,is_return=0,raw="Commercial Rounding",**options):
    case=previous(operator,connections,**options)
    root=case.data.raw_metas[case.invoice.doctype]
    for name in ("outstanding_amount","base_rounded_total"):
        root.definitions[name]=Definition(name,fieldtype="Currency",precision="3" if name=="outstanding_amount" else "2",options="currency")
        case.data.records["header"][0][name]=Decimal("2.675000000") if name=="outstanding_amount" else Decimal("0.000000000")
    case.data.records["header"][0]["is_return"]=is_return
    case.applied[root.name]=case.data.metas[root.name]=project(root)
    case.observations[root.name]=observed_metadata(root)
    write=AppliedMeta(root.name,calc.WRITE_FIELDS+(calc.AUTO,))
    for name,df in write.definitions.items():
        df.values.update({key:case.write_observation.applied.get_field(name).get(key) for key in PROPERTIES})
    write.definitions["write_off_amount"].values["precision"]="2"
    case.write_observation=observation(write,WRITE_OFF_PROFILE,"-WRITE-OFF")
    service,overrides=case.service,dict(case.field_overrides)
    bind_numeric(case,operator)
    case.service=service
    case.field_overrides.update(overrides)
    for name,df in write.definitions.items():case.field_overrides[root.name,name]=df
    case.invoice.meta.istable=case.invoice.meta.issingle=0
    case.invoice.write_off_amount=Decimal("1.234500000")
    case.invoice.base_write_off_amount=Decimal("1.500000000")
    case.invoice.write_off_outstanding_amount_automatically=options.get("auto",1)
    case.round_doc.rounding_method=raw
    setup=connections()
    with setup.cursor() as cursor:
        for name in ("outstanding_amount","base_rounded_total"):
            cursor.execute("ALTER TABLE `tab"+root.name+"` ADD COLUMN IF NOT EXISTS `"+name+"` DECIMAL(21,9)")
        cursor.execute("UPDATE `tab"+root.name+"` SET outstanding_amount=2.675,base_rounded_total=0,is_return=%s",(is_return,))
        cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'",(raw,))
        cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s AND fieldname<>'party_account_currency'",(root.name,))
    seed_metadata(setup,case.observations[root.name],groups=("docfields",))
    seed_metadata(setup,case.write_observation,groups=("docfields",))
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    return case


def capture(case,major):
    return case.service.capture_receivable_context(case.invoice.name,erp_major=major,doctype=case.invoice.doctype)


def payable(source,values=(8.7,0.0,12.34567,0.0,1.2345,0.1,0.15),representation="CALCULATED"):
    return calc.PayableAmountCalculation(source,representation,tuple(zip(calc.PAYABLE_FIELDS,values)))


def primary_balance(calculation,major,upstream16,monkeypatch):
    source=calculation.payable.source;raw=source.stage.method.rounding.value
    probe=framework(major,upstream16,monkeypatch,setting=raw)
    traces=[];checkpoints=[];selected={row.target[2]:row.precision.precision for row in source.stage.fields}
    class StopSuffix(Exception):pass
    class Root:
        def __setattr__(self,name,value):
            object.__setattr__(self,name,value)
            if name=="outstanding_amount" and getattr(self,"ready",False):raise StopSuffix
        def get(self,name):return getattr(self,name,None)
        def precision(self,name):traces.append((name,selected[name]));return selected[name]
        def round_floats_in(self,doc,names):checkpoints.append(("round",tuple(names)))
    doc=Root();doc.ready=False;doc.doctype="Sales Invoice"
    for name,value in (*calculation.payable.values,*calculation.values):setattr(doc,name,value)
    doc.is_return=source.is_return;doc.return_against=None
    doc.update_outstanding_for_self=0;doc.is_pos=0
    doc.currency="USD" if source.foreign else source.party.currency
    doc.party_account_currency=source.party.currency
    doc.ready=True
    def change():checkpoints.append(("change",))
    def base_conversion(target,names):checkpoints.append(("company",tuple(names)))
    owner=SimpleNamespace(doc=doc,calculate_paid_amount=lambda:checkpoints.append(("paid",)),
        is_internal_invoice=lambda:False,calculate_change_amount=change,_set_in_company_currency=base_conversion)
    with pytest.raises(StopSuffix) as caught:controller("calculate_outstanding_amount",major,{"flt":probe.flt})(owner)
    count=calculation.payable.setting_count
    precision_count=len(calculation.payable.precision_trace)
    settings=tuple((call.args[0],raw) for call in probe.runtime.get_system_settings.call_args_list)
    # Read the actual local from the stopped primary frame, without tolerances
    # or a second execution of the controller under test.
    tb=caught.value.__traceback__
    while tb and "total_amount_to_pay" not in tb.tb_frame.f_locals:tb=tb.tb_next
    assert tb is not None
    actual_total=tb.tb_frame.f_locals["total_amount_to_pay"]
    calculation.payable.require_match(amount=actual_total,setting_trace=settings[:count],precision_trace=tuple(traces[:precision_count]))
    calculation.require_match(amount=doc.outstanding_amount,setting_trace=settings[count:],precision_trace=tuple(traces[precision_count:]))
    expected=[("paid",),("round",("grand_total","total_advance","write_off_amount")),("company",("write_off_amount",)),("round",("paid_amount",))]
    if not source.is_return:expected.append(("change",))
    assert checkpoints[:len(expected)]==expected


def primary_write_off(calculation,major,upstream16,monkeypatch):
    source=calculation.source;raw=source.stage.method.rounding.value
    probe=framework(major,upstream16,monkeypatch,setting=raw)
    traces=[];calls=[];writes=[];precisions={name:p.precision for name,p in source.precisions}
    class Root:
        def __setattr__(self,name,value):
            object.__setattr__(self,name,value)
            if name in calc.WRITE_FIELDS and getattr(self,"ready",False):writes.append((name,value))
        def get(self,name):return getattr(self,name,None)
        def precision(self,name):traces.append((name,precisions[name]));return precisions[name]
    doc=Root();doc.ready=False
    for name,value in calculation.values:setattr(doc,name,value)
    doc.write_off_amount=1.2345;doc.base_write_off_amount=1.5;doc.ready=True
    owner=SimpleNamespace(doc=doc,calculate_outstanding_amount=lambda:calls.append(tuple(writes)))
    controller("calculate_write_off_amount",major,{"flt":probe.flt})(owner)
    calculation.require_match(amounts=tuple(writes),recalculate=bool(calls),
        setting_trace=tuple((call.args[0],raw) for call in probe.runtime.get_system_settings.call_args_list),precision_trace=tuple(traces))
    assert calls==([tuple(writes)] if calculation.recalculate else [])
    if not calculation.recalculate:assert (doc.write_off_amount,doc.base_write_off_amount)==(1.2345,1.5)


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("foreign",[False,True])
@pytest.mark.parametrize("is_return",[0,1],ids=["ordinary","return"])
def test_primary_payable_balance_and_write_off_order(defaults_operator,connections,upstream16,monkeypatch,major,foreign,is_return):
    case=native_case(defaults_operator,connections,foreign=foreign,is_return=is_return)
    source=capture(case,major)
    for inputs,paid in (((8.7,0.0,12.34567,0.0,1.2345,0.1,0.15),(0.0,0.0,0.0,0.0)),
            ((-8.7,-8.655,-12.34567,-12.33335,0.0,None,None),(-10.0,-15.0,-1.25,-1.5))):
        calculation=calc.OutstandingAmountCalculation(payable(source,inputs),"CALCULATED",tuple(zip(calc.BALANCE_FIELDS,paid)))
        primary_balance(calculation,major,upstream16,monkeypatch)
    for flag,amount,rate in ((1,2.675,1.23456789),(0,None,None)):
        calculation=calc.WriteOffCalculation(source,"CALCULATED",((calc.AUTO,flag),("outstanding_amount",amount),("conversion_rate",rate)))
        primary_write_off(calculation,major,upstream16,monkeypatch)
    if not is_return:
        if foreign:
            calculation=calc.OutstandingAmountCalculation(payable(source,(8.7,0.0,None,None,0.0,None,None)),"CALCULATED",tuple(zip(calc.BALANCE_FIELDS,(None,None,None,None))))
            primary_balance(calculation,major,upstream16,monkeypatch)
        else:
            calculation=calc.WriteOffCalculation(source,"CALCULATED",((calc.AUTO,1),("outstanding_amount",None),("conversion_rate",1.0)))
            primary_write_off(calculation,major,upstream16,monkeypatch)
    assert len(case.opened)==1
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
def test_base_precision_reuses_same_company_format(defaults_operator,connections,upstream16,monkeypatch,major):
    case=native_case(defaults_operator,connections,format_precision=True)
    source=capture(case,major)
    assert dict(source.precisions)["base_write_off_amount"].precision==(2 if major==15 else 8)
    calculation=calc.WriteOffCalculation(source,"CALCULATED",((calc.AUTO,1),("outstanding_amount",1.255),("conversion_rate",1.23456789)))
    primary_write_off(calculation,major,upstream16,monkeypatch)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("raw",[None,"Commercial Rounding"])
def test_negative_write_off_preserves_bound_legacy_or_commercial_method(defaults_operator,connections,upstream16,monkeypatch,major,raw):
    case=native_case(defaults_operator,connections,raw=raw,is_return=1)
    source=capture(case,major)
    calculation=calc.WriteOffCalculation(source,"CALCULATED",((calc.AUTO,1),("outstanding_amount",-2.675),("conversion_rate",3.1415926)))
    primary_write_off(calculation,major,upstream16,monkeypatch)
    assert dict(calculation.amounts)["write_off_amount"]==(-2.67 if raw is None else -2.68)
    untouched(defaults_operator,case)


def test_fixed_null_flag_uses_existing_saved_check_matching(defaults_operator,connections):
    case=native_case(defaults_operator,connections,auto=None)
    source=capture(case,16)
    for flag in (None,0):
        result=calc.WriteOffCalculation(source,"NUMERIC_FIXED",((calc.AUTO,flag),("outstanding_amount",2.675),("conversion_rate",1.0)))
        assert result.amounts==() and not result.recalculate
    with pytest.raises(calc.ReceivableCalculationError):
        calc.WriteOffCalculation(source,"NUMERIC_FIXED",((calc.AUTO,1),("outstanding_amount",2.675),("conversion_rate",1.0)))
    untouched(defaults_operator,case)


@pytest.mark.parametrize("changed",["write","return","party","precision"])
def test_native_drift_without_revision_change_is_rolled_back(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    old=case.write_metadata.side_effect;edits=[]
    def read(*args):
        result=old(*args)
        if case.write_metadata.call_count==2:
            with case.opened[0].cursor() as cursor:
                if changed=="write":cursor.execute("UPDATE `tabSales Invoice` SET write_off_amount=2")
                elif changed=="return":cursor.execute("UPDATE `tabSales Invoice` SET is_return=1")
                elif changed=="party":cursor.execute("UPDATE `tabSales Invoice` SET party_account_currency='USD'")
                else:cursor.execute("UPDATE `tabDocField` SET `precision`='7' WHERE parent='Sales Invoice' AND fieldname='write_off_amount'")
            edits.append(changed)
        return result
    case.write_metadata.side_effect=read
    with pytest.raises(InspectionFailed):capture(case,16)
    assert edits==[changed]
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)
    observer=connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT write_off_amount,is_return,party_account_currency FROM `tabSales Invoice`")
        assert cursor.fetchone()==(Decimal("1.234500000"),0,"SAR")
        cursor.execute("SELECT `precision` FROM `tabDocField` WHERE parent='Sales Invoice' AND fieldname='write_off_amount'")
        assert cursor.fetchone()==("2",)
    observer.close()


@pytest.mark.parametrize("changed",["write","return","party","precision","currency_cache"])
def test_close_rechecks_original_side_fields_and_caches(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections,format_precision=changed=="currency_cache")
    def wrap(connection):
        old=connection.close.side_effect
        def close():
            value=old()
            if changed=="write":case.invoice.write_off_amount=Decimal("2.000000000")
            elif changed=="return":case.invoice.is_return=1
            elif changed=="party":case.invoice.party_account_currency="USD"
            elif changed=="precision":case.invoice._precision={"main":{"write_off_amount":2}}
            else:defaults_operator.runtime.local.field_currency={(case.invoice.doctype,case.invoice.name):{"base_write_off_amount":"SAR"}}
            return value
        connection.close.side_effect=close
    case.before_handoff=wrap
    with pytest.raises(InspectionFailed):capture(case,16)
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("name",["write_off_amount","base_write_off_amount",calc.AUTO])
def test_side_field_read_precedes_sql_and_providers(defaults_operator,connections,name):
    case=native_case(defaults_operator,connections)
    case.field_overrides[case.invoice.doctype,name].values["permlevel"]=1
    with pytest.raises(PermissionDenied):capture(case,16)
    for callback in (case.factory,case.metadata_provider,case.write_metadata):callback.assert_not_called()


def test_saved_projection_and_strict_source_result_reconstruction(defaults_operator,connections):
    case=native_case(defaults_operator,connections)
    source=capture(case,16)
    fixed=calc.WriteOffCalculation(source,"NUMERIC_FIXED",((calc.AUTO,1),("outstanding_amount",2.675),("conversion_rate",1.0)))
    assert fixed.recalculate
    for flag in (True,"1",1.0,2):
        with pytest.raises(calc.ReceivableCalculationError):replace(fixed,values=((calc.AUTO,flag),*fixed.values[1:]))
    for changes in (dict(return_tag=("int","1")),dict(caches=tuple(reversed(source.caches)))):
        with pytest.raises(calc.ReceivableCalculationError):replace(source,**changes)
    for values in (tuple(reversed(fixed.values)),((calc.AUTO,1),("outstanding_amount",Decimal("2.675")),("conversion_rate",1.0))):
        with pytest.raises(calc.ReceivableCalculationError):replace(fixed,values=values)
    valid=dict(amounts=fixed.amounts,recalculate=True,setting_trace=(("rounding_method","Commercial Rounding"),)*2,precision_trace=(("write_off_amount",2),("base_write_off_amount",3)))
    fixed.require_match(**valid)
    for changes in (dict(recalculate=1),dict(amounts=tuple(reversed(fixed.amounts))),dict(setting_trace=())):
        with pytest.raises(calc.ReceivableCalculationError):fixed.require_match(**(valid|changes))
    p=payable(source)
    trace=tuple(("rounding_method","Commercial Rounding") for _ in range(p.setting_count))
    p.require_match(amount=p.amount,setting_trace=trace,precision_trace=p.precision_trace)
    with pytest.raises(calc.ReceivableCalculationError):p.require_match(amount=p.amount,setting_trace=(),precision_trace=p.precision_trace)
    tampered=replace(p)
    object.__setattr__(tampered,"precision_trace",tuple((name,float(value)) for name,value in p.precision_trace))
    with pytest.raises(calc.ReceivableCalculationError):tampered.pin()
    tampered_source=replace(source)
    precision=tampered_source.precisions[0][1]
    object.__setattr__(precision,"precision",float(precision.precision))
    with pytest.raises(calc.ReceivableCalculationError):tampered_source.pin()
    balance=calc.OutstandingAmountCalculation(p,"CALCULATED",tuple(zip(calc.BALANCE_FIELDS,(0.0,0.0,0.0,0.0))))
    balance.require_match(amount=balance.amount,setting_trace=(("rounding_method","Commercial Rounding"),),precision_trace=(("outstanding_amount",3),))
    with pytest.raises(calc.ReceivableCalculationError):balance.require_match(amount=Decimal(str(balance.amount)),setting_trace=(("rounding_method","Commercial Rounding"),),precision_trace=(("outstanding_amount",3),))
    for value in (source,fixed,p,balance):
        assert "1.2345" not in repr(value)
        with pytest.raises(TypeError):pickle.dumps(value)
    untouched(defaults_operator,case)
