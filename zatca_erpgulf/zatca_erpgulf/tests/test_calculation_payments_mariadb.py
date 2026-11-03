"""Paid/change parity on NEW guard-owned TCP-disabled SQL, never tenant data."""
import ast
import json
from dataclasses import replace
from decimal import Decimal
import os
import pickle
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_payments as calc
from zatca_erpgulf.zatca_erpgulf.source_metadata import PAYMENT_CONTROLS_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access_mariadb import native_case as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta,Definition,project
from zatca_erpgulf.zatca_erpgulf.metadata_source import SelectedMetadataRows
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _canonical
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller,controller_text
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
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import insert_data
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator,operator,one_failure,InspectionFailed,PermissionDenied,
)

pytestmark=pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB")!="1",reason="NEW guard-owned SQL only; no tenant or authority access")


def native_case(operator,connections,*,flags=(1,0,1),types=("Card","Cash",None),raw="Commercial Rounding",**options):
    case=previous(operator,connections,**options)
    root=case.data.raw_metas[case.invoice.doctype]
    for name in (*calc.STAGE_FIELDS,"base_grand_total","rounded_total","base_rounded_total"):
        root.definitions[name]=Definition(name,fieldtype="Currency",precision="3" if name.startswith("base_") else "2",options="currency")
        case.data.records["header"][0][name]=Decimal("0.000000000")
    controls=AppliedMeta(root.name,calc.LockedPaymentControlsRead.FIELDS)
    for name,flag in zip(calc.LockedPaymentControlsRead.CHECKS,flags):
        controls.definitions[name]=Definition(name,fieldtype="Check")
        if name in calc.LockedPaymentControlsRead.OVERLAP:
            root.definitions[name]=controls.definitions[name]
            case.data.records["header"][0][name]=flag
    controls.definitions["loyalty_amount"]=Definition("loyalty_amount",fieldtype="Currency",options="Company:company:default_currency")
    payment=case.data.raw_metas["Sales Invoice Payment"]
    payment.definitions["type"]=Definition("type",fieldtype="Read Only")
    # A complete saved table, including a zero Cash row, determines change.
    first=case.data.records["payments"][0]
    case.data.records["payments"]=[dict(first,name="payments-"+str(i+1),idx=i+1,type=kind,amount=Decimal("1.000000000")) for i,kind in enumerate(types)]
    for meta in (root,payment):
        case.applied[meta.name]=case.data.metas[meta.name]=project(meta)
        case.observations[meta.name]=observed_metadata(meta)
    initial=observed_metadata(controls,profile=PAYMENT_CONTROLS_PROFILE)
    body=json.loads(initial._payload)
    overlaps={dict(row["header"])["fieldname"][1]:row for row in json.loads(case.observations[root.name]._payload)["docfields"]}
    for i,row in enumerate(body["docfields"]):
        name=dict(row["header"])["fieldname"][1]
        if name in calc.LockedPaymentControlsRead.OVERLAP:body["docfields"][i]=overlaps[name]
        else:row["name"]+="-PAYMENT-CONTROLS"
    body["docfields"].sort(key=lambda row:row["name"])
    case.controls_observation=SelectedMetadataRows(initial.applied,_canonical(body))
    case.controls_metadata=Mock(side_effect=lambda *args:{root.name:case.controls_observation.applied})
    service=case.service
    bind_numeric(case,operator)
    case.service=access.SavedCalculationDefaultsService(case.scope,case.factory,case.cache,
        applied_metadata_reader=case.metadata_provider,
        rounding_metadata_reader=service._rounding_metadata,rounding_cache_reader=service._rounding_cache,
        format_metadata_reader=service._format_metadata,format_cache_reader=service._format_cache,
        owner_currency_metadata_reader=service._owner_currency_metadata,
        company_currency_cache_reader=service._company_currency_cache,
        payment_controls_metadata_reader=case.controls_metadata)
    case.invoice.meta.istable=case.invoice.meta.issingle=0
    for name,definition in controls.definitions.items():
        definition.fieldname=name
        definition.fieldtype=definition.get("fieldtype")
        case.field_overrides[root.name,name]=definition
    case.invoice.redeem_loyalty_points=flags[2]
    case.invoice.loyalty_amount=Decimal("1.234500000")
    case.round_doc.rounding_method=raw
    setup=connections()
    with setup.cursor() as cursor:
        for name in (*calc.STAGE_FIELDS,"base_grand_total","rounded_total","base_rounded_total","loyalty_amount"):
            cursor.execute("ALTER TABLE `tab"+root.name+"` ADD COLUMN IF NOT EXISTS `"+name+"` DECIMAL(21,9)")
        for name in calc.LockedPaymentControlsRead.CHECKS:
            cursor.execute("ALTER TABLE `tab"+root.name+"` ADD COLUMN IF NOT EXISTS `"+name+"` INT")
        cursor.execute("UPDATE `tab"+root.name+"` SET paid_amount=0,base_paid_amount=0,change_amount=0,base_change_amount=0,base_grand_total=0,rounded_total=0,base_rounded_total=0,loyalty_amount=%s,is_pos=%s,is_return=%s,redeem_loyalty_points=%s",(case.invoice.loyalty_amount,*flags))
        cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'",(raw,))
        cursor.execute("DELETE FROM `tabSales Invoice Payment`")
        cursor.execute("ALTER TABLE `tabSales Invoice Payment` ADD COLUMN IF NOT EXISTS type LONGTEXT")
        for meta in (root,payment):cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s",(meta.name,))
    for meta in (root,payment):seed_metadata(setup,case.observations[meta.name],groups=("docfields",))
    with setup.cursor() as cursor:cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s AND fieldname IN ('is_pos','is_return')",(root.name,))
    seed_metadata(setup,case.controls_observation,groups=("docfields",))
    insert_data(setup,root.name,"payments",case.data.records["payments"])
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    return case


def capture(case,major=16):
    return case.service.capture_payment_calculation_context(case.invoice.name,erp_major=major,doctype=case.invoice.doctype)


def paid(source,amounts=None,rate=1.0,loyalty=1.2345,representation="CALCULATED"):
    if amounts is None:amounts=(1.0,)*len(source.payment_types)
    return calc.PaidAmountCalculation(source,representation,(("conversion_rate",rate),("loyalty_amount",loyalty)),tuple((name,value) for (name,_),value in zip(source.payment_types,amounts)))


def primary_probe(calculation,major,upstream16,monkeypatch,grand=(8.7,0.0,12.34,0.0)):
    raw=calculation.source.stage.method.rounding.value
    probe=framework(major,upstream16,monkeypatch,setting=raw)
    precisions={name:proof.precision.precision for name,proof in zip(calc.STAGE_FIELDS,calculation.source.stage.fields)}
    trace=[];cleared=[]
    doc=SimpleNamespace(doctype="Sales Invoice",**dict(calculation.headers),**dict(calculation.source.controls.normalized_checks))
    types={name:None if tag==("null",) else tag[1] for name,tag in calculation.source.payment_types}
    original=[SimpleNamespace(name=name,amount=value,base_amount=999.0,type=types[name]) for name,value in calculation.rows]
    doc.payments=list(original)
    doc.get=lambda name:getattr(doc,name,None)
    doc.set=lambda name,value:(cleared.append(name),setattr(doc,name,value))[-1]
    doc.precision=lambda name:(trace.append((name,precisions[name])),precisions[name])[-1]
    owner=SimpleNamespace(doc=doc)
    controller("calculate_paid_amount",major,{"flt":probe.flt})(owner)
    touched=tuple((row.name,row.amount,row.base_amount) for row in doc.payments) if doc.is_pos else ()
    settings=lambda:tuple((call.args[0],raw) for call in probe.runtime.get_system_settings.call_args_list)
    calculation.require_match(payments=touched,totals=tuple((name,getattr(doc,name)) for name in calc.PAID_FIELDS),clear_payments=bool(cleared),setting_trace=settings(),precision_trace=tuple(trace))
    if not doc.is_pos and doc.is_return:assert doc.payments==original and all(row.base_amount==999.0 for row in original)
    headers=tuple(zip(("grand_total","rounded_total","base_grand_total","base_rounded_total"),grand))
    change=calc.ChangeAmountCalculation(calculation,"CALCULATED",headers)
    for name,value in headers:setattr(doc,name,value)
    trace.clear();probe.runtime.get_system_settings.reset_mock()
    controller("calculate_change_amount",major,{"flt":probe.flt})(owner)
    change.require_match(totals=tuple((name,getattr(doc,name)) for name in calc.CHANGE_FIELDS),setting_trace=settings(),precision_trace=tuple(trace))
    return change


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("flags",[(1,0,1),(1,1,1),(0,0,1),(0,1,1),(1,0,0),(None,None,None)])
def test_base_paid_and_change_match_actual_versioned_controller(defaults_operator,connections,monkeypatch,upstream16,major,flags):
    case=native_case(defaults_operator,connections,flags=flags)
    source=capture(case,major)
    for amounts,rate,loyalty in (((1.0,1.0,1.0),1.0,1.2345),((0.1,0.2,0.3),3.1415926,0.0),((10.255,0.0,None),1.23456789,1.005),((-1.255,2.675,-0.0),-2.0,-0.1),((1e16,1.0,-1e16),1.0,None)):
        result=paid(source,amounts,rate,loyalty)
        primary_probe(result,major,upstream16,monkeypatch)
    assert len(case.opened)==1
    assert all(row.amount==Decimal("1.000000000") for row in case.refs["payments"])
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("types",[("Card","Cash",None),("Card","cash",None),()])
def test_cash_zero_row_exact_type_fallback_and_absent_method(defaults_operator,connections,monkeypatch,upstream16,major,types):
    case=native_case(defaults_operator,connections,types=types,raw=None,flags=(1,0,0))
    source=capture(case,major)
    result=paid(source,amounts=(10.255,0.0,0.0) if types else ())
    for grand in ((8.7,0.0,12.34,0.0),(8.7,1.0,12.34,1.5),(10.26,0.0,12.34,0.0),(-8.7,None,-12.34,None)):
        change=primary_probe(result,major,upstream16,monkeypatch,grand)
        assert change.applies is bool(types and "Cash" in types and dict(result.totals)["paid_amount"]>(grand[1] or grand[0]))
    untouched(defaults_operator,case)


def test_saved_projection_strict_observations_and_zero_loyalty_rate(defaults_operator,connections):
    case=native_case(defaults_operator,connections)
    source=capture(case)
    fixed=paid(source,representation="NUMERIC_FIXED")
    assert fixed.totals==paid(source).totals
    for values in (dict(rate=0.0),dict(rate=None),dict(loyalty=True),dict(loyalty=Decimal("1.0")),dict(rate=float("nan")),dict(amounts=(1.0,))):
        with pytest.raises(calc.PaymentCalculationError):paid(source,**values)
    for values in (dict(loyalty=0.0,rate=0.0),dict(loyalty=None,rate=None)):paid(source,**values)
    with pytest.raises(calc.PaymentCalculationError):paid(source,rate=2.0,representation="NUMERIC_FIXED")
    for value in (source,fixed,calc.ChangeAmountCalculation(fixed,"CALCULATED",(("grand_total",8.7),("rounded_total",0.0),("base_grand_total",8.7),("base_rounded_total",0.0)))):
        assert "1.2345" not in repr(value)
        with pytest.raises(TypeError):pickle.dumps(value)
    with pytest.raises(calc.PaymentCalculationError):replace(source,payment_types=tuple(reversed(source.payment_types)))
    valid=dict(payments=fixed.payments,totals=fixed.totals,clear_payments=False,setting_trace=(("rounding_method","Commercial Rounding"),)*2,precision_trace=(("paid_amount",2),("base_paid_amount",3)))
    fixed.require_match(**valid)
    for changes in (dict(clear_payments=0),dict(totals=tuple(reversed(fixed.totals))),dict(setting_trace=()),dict(precision_trace=tuple(reversed(valid["precision_trace"])))):
        with pytest.raises(calc.PaymentCalculationError):fixed.require_match(**(valid|changes))
    untouched(defaults_operator,case)


@pytest.mark.parametrize("source_name",calc.LockedPaymentControlsRead.FIELDS)
def test_controls_field_read_precedes_providers(defaults_operator,connections,source_name):
    case=native_case(defaults_operator,connections)
    case.field_overrides[case.invoice.doctype,source_name].values["permlevel"]=1
    with pytest.raises(PermissionDenied):capture(case)
    for callback in (case.factory,case.metadata_provider,case.controls_metadata):callback.assert_not_called()
    one_failure(defaults_operator,access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("changed",["loyalty","flag","type","precision"])
def test_native_drift_without_revision_is_rejected_and_rolled_back(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    original=case.controls_metadata.side_effect;edits=[]
    def read(*args):
        value=original(*args)
        if case.controls_metadata.call_count==2:
            with case.opened[0].cursor() as cursor:
                if changed=="loyalty":cursor.execute("UPDATE `tabSales Invoice` SET loyalty_amount=2")
                elif changed=="flag":cursor.execute("UPDATE `tabSales Invoice` SET redeem_loyalty_points=0")
                elif changed=="type":cursor.execute("UPDATE `tabSales Invoice Payment` SET type='Card'")
                else:cursor.execute("UPDATE `tabDocField` SET `precision`='7' WHERE parent='Sales Invoice' AND fieldname='paid_amount'")
            edits.append(changed)
        return value
    case.controls_metadata.side_effect=read
    with pytest.raises(InspectionFailed):capture(case)
    assert edits==[changed]
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)
    observer=connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT loyalty_amount,redeem_loyalty_points FROM `tabSales Invoice`")
        assert cursor.fetchone()==(Decimal("1.234500000"),1)
        cursor.execute("SELECT type FROM `tabSales Invoice Payment` ORDER BY idx")
        assert cursor.fetchall()==(("Card",),("Cash",),(None,))
    observer.close()


@pytest.mark.parametrize("changed",["loyalty","flag","saved_type","ref_type","cache"])
def test_cleanup_rechecks_original_controls_categories_and_caches(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    def wrap(connection):
        old=connection.close.side_effect
        def close():
            value=old()
            if changed=="loyalty":case.invoice.loyalty_amount=Decimal("2.000000000")
            elif changed=="flag":case.invoice.redeem_loyalty_points=0
            elif changed=="saved_type":case.saved["payments","payments-2"].type="Card"
            elif changed=="ref_type":case.refs["payments"][1].type="Card"
            else:case.invoice._precision={"main":{"paid_amount":2}}
            return value
        connection.close.side_effect=close
    case.before_handoff=wrap
    with pytest.raises(InspectionFailed):capture(case)
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)


def test_standalone_pos_is_not_silently_given_sales_invoice_change_rules(defaults_operator,connections):
    case=previous(defaults_operator,connections,doctype="POS Invoice")
    case.service._payment_controls_metadata=Mock()
    with pytest.raises(InspectionFailed):capture(case)
    case.factory.assert_not_called();case.service._payment_controls_metadata.assert_not_called()
    for name in ("calculate_paid_amount","calculate_change_amount"):
        assert ast.dump(ast.parse(controller_text(name,15)))==ast.dump(ast.parse(controller_text(name,16)))
