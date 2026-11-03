"""Advance ceilings on NEW guard-owned TCP-disabled temporary SQL only."""
from dataclasses import replace
from decimal import Decimal
import inspect
import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_advance_limit as limit
from zatca_erpgulf.zatca_erpgulf import calculated_totals as totals
from zatca_erpgulf.zatca_erpgulf.source_metadata import WRITE_OFF_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_party_access_mariadb import native_case as previous,observation
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta,Definition,project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
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


def native_case(operator,connections,*,foreign=True,auto=1,format_precision=False,**options):
    case=previous(operator,connections,**options)
    root=case.data.raw_metas[case.invoice.doctype]
    for name,precision,opts in (("grand_total","2","currency"),("base_grand_total",None if format_precision else "4","Company:company:default_currency"),("rounded_total",None,"currency")):
        root.definitions[name]=Definition(name,fieldtype="Currency",precision=precision,options=opts)
        if name not in case.data.records["header"][0]:case.data.records["header"][0][name]=Decimal("0.000000000")
    case.applied[root.name]=case.data.metas[root.name]=project(root)
    case.observations[root.name]=observed_metadata(root)
    write=AppliedMeta(root.name,limit.LockedWriteOffRead.FIELDS)
    for name in write.definitions:
        write.definitions[name].values.update(fieldtype="Check" if name==limit.AUTO else "Currency",
            options=None if name==limit.AUTO else "Company:company:default_currency" if name==limit.BASE else "currency",
            precision="3" if name==limit.BASE and not format_precision else None)
    case.write_observation=observation(write,WRITE_OFF_PROFILE,"-WRITE-OFF")
    case.write_metadata=Mock(side_effect=lambda *args:{root.name:case.write_observation.applied})
    bind_numeric(case,operator)
    case.normal_metas["Sales Invoice Advance"].istable=1
    case.normal_metas["Sales Invoice Advance"].issingle=0
    case.field_overrides[root.name,"party_account_currency"]=case.owner_observation.applied.get_field("party_account_currency")
    for name in write.definitions:case.field_overrides[root.name,name]=write.definitions[name]
    case.invoice.currency=case.data.records["header"][0]["currency"]="USD" if foreign else "SAR"
    case.invoice.write_off_amount=Decimal("1.234500000")
    case.invoice.base_write_off_amount=Decimal("1.500000000")
    case.invoice.write_off_outstanding_amount_automatically=auto
    case.service=access.SavedCalculationDefaultsService(case.scope,case.factory,case.cache,
        applied_metadata_reader=case.metadata_provider,rounding_metadata_reader=case.round_metadata,
        rounding_cache_reader=case.round_cache,format_metadata_reader=case.format_metadata,format_cache_reader=case.format_cache,
        owner_currency_metadata_reader=case.owner_metadata,advance_party_metadata_reader=case.party_metadata,
        child_metadata_reader=case.child_metadata,write_off_metadata_reader=case.write_metadata)
    case.service._company_currency_cache=Mock(return_value="SAR")
    setup=connections()
    with setup.cursor() as cursor:
        for name in ("rounded_total","write_off_amount","base_write_off_amount"):
            cursor.execute("ALTER TABLE `tab"+root.name+"` ADD COLUMN IF NOT EXISTS `"+name+"` DECIMAL(21,9)")
        cursor.execute("ALTER TABLE `tab"+root.name+"` ADD COLUMN IF NOT EXISTS write_off_outstanding_amount_automatically INT")
        cursor.execute("UPDATE `tab"+root.name+"` SET currency=%s,rounded_total=0,base_grand_total=0,write_off_amount=%s,base_write_off_amount=%s,write_off_outstanding_amount_automatically=%s",
            (case.invoice.currency,case.invoice.write_off_amount,case.invoice.base_write_off_amount,auto))
        cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s AND fieldname IN ('grand_total','base_grand_total','rounded_total')",(root.name,))
    # Reseed the complete original profile after replacing selected precision.
    with setup.cursor() as cursor:
        cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s AND fieldname<>'party_account_currency'",(root.name,))
    seed_metadata(setup,case.observations[root.name],groups=("docfields",))
    seed_metadata(setup,case.write_observation,groups=("docfields",))
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    return case


def capture(case,major):
    return case.service.capture_advance_limit_context(case.invoice.name,erp_major=major,doctype=case.invoice.doctype)


def calculate(source,values):
    rows=totals.CalculationRows(source.stage.numeric.view.financial,"advances","CALCULATED",(("advances-1",1.0),("advances-2",1.0),("advances-3",1.0)))
    aggregate=totals.AdvanceAggregateCalculation(source.advance.stage,rows,source.advance)
    return limit.AdvanceLimitCalculation(source,aggregate,"CALCULATED",tuple(zip(limit.CURRENT_FIELDS,values)))


def primary_probe(case,calculation,major,upstream16,monkeypatch):
    raw=calculation.source.stage.method.rounding.value
    probe=framework(major,upstream16,monkeypatch,setting=raw)
    observed={"blocked":False,"reset":False,"calls":[]};traces=[]
    precisions={proof.target[2]:proof.precision.precision for proof in calculation.source.stage.fields}
    if calculation.source.base_precision:precisions[limit.BASE]=calculation.source.base_precision.precision
    class Rejected(Exception):pass
    class Root:
        def __setattr__(self,name,value):
            if name=="total_advance":probe.runtime.get_system_settings.reset_mock();traces.clear()
            if name=="write_off_amount" and getattr(self,"ready",False):observed["reset"]=True
            object.__setattr__(self,name,value)
        def get(self,name):return getattr(self,name,None)
        def precision(self,name):traces.append((name,precisions[name]));return precisions[name]
    doc=Root();doc.ready=False
    for name,value in calculation.values:setattr(doc,name,value)
    doc.party_account_currency=calculation.source.party.currency;doc.currency=case.invoice.currency
    doc.write_off_outstanding_amount_automatically=case.invoice.write_off_outstanding_amount_automatically
    doc.docstatus=SimpleNamespace(is_cancelled=lambda:False)
    p=dict(calculation.source.advance.row_precisions)
    doc.advances=[SimpleNamespace(allocated_amount=amount,precision=lambda field,name=name:p[name]) for name,amount in calculation.aggregate.rows.values]
    doc.ready=True
    def reject(message):
        observed.update(blocked=True,invoice_total=inspect.currentframe().f_back.f_locals["invoice_total"])
        raise Rejected
    def outstanding():
        observed["invoice_total"]=inspect.currentframe().f_back.f_locals["invoice_total"]
        observed["calls"].append("outstanding")
    owner=SimpleNamespace(doc=doc,calculate_outstanding_amount=outstanding,calculate_write_off_amount=lambda:observed["calls"].append("write_off"))
    try:controller("calculate_total_advance",major,{"flt":probe.flt,"frappe":SimpleNamespace(throw=reject),"_":lambda value:value})(owner)
    except Rejected:pass
    calculation.require_match(invoice_total=observed["invoice_total"],blocked=observed["blocked"],reset_write_off=observed["reset"],
        setting_trace=tuple((call.args[0],raw) for call in probe.runtime.get_system_settings.call_args_list),precision_trace=tuple(traces))
    assert observed["calls"]==([] if calculation.blocked else ["outstanding","write_off"])


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("foreign",[False,True])
def test_exact_controller_ceiling_order_rounding_and_no_writes(defaults_operator,connections,monkeypatch,upstream16,major,foreign):
    case=native_case(defaults_operator,connections,foreign=foreign)
    source=capture(case,major)
    for values in ((8.7,0.0,1.23456789,1.2345),(8.7,1.0,1.23456789,0.1),(-8.7,None,1.23456789,None)):
        result=calculate(source,values)
        primary_probe(case,result,major,upstream16,monkeypatch)
    assert len(case.opened)==1
    assert case.invoice.write_off_amount==Decimal("1.234500000")
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
def test_base_write_off_reuses_captured_company_format(defaults_operator,connections,monkeypatch,upstream16,major):
    case=native_case(defaults_operator,connections,format_precision=True)
    source=capture(case,major)
    assert source.base_precision.precision==(2 if major==15 else 8)
    primary_probe(case,calculate(source,(8.7,0.0,1.23456789,1.2345)),major,upstream16,monkeypatch)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("foreign",[False,True])
def test_missing_method_and_zero_limit_preserve_actual_lookup_and_reset_order(defaults_operator,connections,monkeypatch,upstream16,foreign):
    case=native_case(defaults_operator,connections,foreign=foreign)
    case.round_doc.rounding_method=None
    setup=connections()
    with setup.cursor() as cursor:cursor.execute("UPDATE `tabSingles` SET value=NULL WHERE field='rounding_method'")
    setup.commit();setup.close()
    source=capture(case,16)
    result=calculate(source,(0.0,-0.0,0.0,None))
    assert not result.blocked and result.reset_write_off
    primary_probe(case,result,16,upstream16,monkeypatch)
    untouched(defaults_operator,case)


def test_saved_projection_and_rejection_of_tampered_observations(defaults_operator,connections):
    case=native_case(defaults_operator,connections)
    source=capture(case,16)
    calculated=calculate(source,(8.7,0.0,1.0,1.2345))
    fixed=replace(calculated,representation="NUMERIC_FIXED")
    assert fixed.invoice_total==calculated.invoice_total
    for values in (tuple(reversed(calculated.values)),((*calculated.values[0][:1],True),*calculated.values[1:]),
            (("grand_total",Decimal("8.7")),*calculated.values[1:])):
        with pytest.raises(limit.AdvanceLimitError):replace(calculated,values=values)
    valid=dict(invoice_total=calculated.invoice_total,blocked=calculated.blocked,reset_write_off=calculated.reset_write_off,
        setting_trace=(("rounding_method","Commercial Rounding"),)*2,precision_trace=calculated.precision_trace)
    calculated.require_match(**valid)
    for changes in (dict(blocked=1),dict(reset_write_off=1),dict(precision_trace=tuple(reversed(calculated.precision_trace))),dict(setting_trace=())):
        with pytest.raises(limit.AdvanceLimitError):calculated.require_match(**(valid|changes))
    changed=replace(calculated.aggregate)
    object.__setattr__(changed,"total_advance",3)
    with pytest.raises(limit.AdvanceLimitError):replace(calculated,aggregate=changed)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("source_name",["write_off_amount","base_write_off_amount","write_off_outstanding_amount_automatically"])
def test_selected_write_off_read_levels_precede_providers(defaults_operator,connections,source_name):
    case=native_case(defaults_operator,connections)
    case.field_overrides[case.invoice.doctype,source_name].values["permlevel"]=1
    with pytest.raises(PermissionDenied):capture(case,16)
    for callback in (case.factory,case.metadata_provider,case.write_metadata,case.owner_metadata):callback.assert_not_called()
    one_failure(defaults_operator,access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("changed",["amount","auto","party","precision"])
def test_late_native_write_off_drift_cannot_be_hidden_by_original_revision(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    old=case.write_metadata.side_effect;edits=[]
    def read(*args):
        result=old(*args)
        if case.write_metadata.call_count==2:
            with case.opened[0].cursor() as cursor:
                if changed=="amount":cursor.execute("UPDATE `tabSales Invoice` SET write_off_amount=2")
                elif changed=="auto":cursor.execute("UPDATE `tabSales Invoice` SET write_off_outstanding_amount_automatically=0")
                elif changed=="party":cursor.execute("UPDATE `tabSales Invoice` SET party_account_currency='USD'")
                else:cursor.execute("UPDATE `tabDocField` SET `precision`='7' WHERE parent='Sales Invoice' AND fieldname='base_write_off_amount'")
            edits.append(changed)
        return result
    case.write_metadata.side_effect=read
    with pytest.raises(InspectionFailed):capture(case,16)
    assert edits==[changed]
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)
    observer=connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT write_off_amount,write_off_outstanding_amount_automatically,party_account_currency FROM `tabSales Invoice`")
        assert cursor.fetchone()==(Decimal("1.234500000"),1,"SAR")
    observer.close()


@pytest.mark.parametrize("changed",["amount","auto","precision"])
def test_close_rechecks_original_write_off_getters_and_cache(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    factory=case.factory.side_effect
    def acquire(*args):
        connection=factory(*args);close=connection.close.side_effect
        def finish():
            result=close()
            if changed=="amount":case.invoice.write_off_amount=Decimal("2.000000000")
            elif changed=="auto":case.invoice.write_off_outstanding_amount_automatically=0
            else:case.invoice._precision={"main":{"base_write_off_amount":3}}
            return result
        connection.close.side_effect=finish
        return connection
    case.factory.side_effect=acquire
    with pytest.raises(InspectionFailed):capture(case,16)
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)


def test_exact_equal_ceiling_is_allowed_before_strict_greater_rejection(defaults_operator,connections,monkeypatch,upstream16):
    case=native_case(defaults_operator,connections,auto=0)
    source=capture(case,16)
    equal=calculate(source,(3.0,0.0,1.0,0.0))
    over=calculate(source,(2.99994,0.0,1.0,0.0))
    assert not equal.blocked and over.blocked
    assert not equal.reset_write_off and not over.reset_write_off
    for result in (equal,over):primary_probe(case,result,16,upstream16,monkeypatch)
    untouched(defaults_operator,case)
