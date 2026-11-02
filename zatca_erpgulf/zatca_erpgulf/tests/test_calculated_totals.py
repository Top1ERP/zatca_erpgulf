"""Current aggregate inputs versus actual15/pinned16 controller method bodies."""

import ast
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf import calculated_totals as calc
from zatca_erpgulf.zatca_erpgulf.calculation_rounding_stage import RoundingStageError
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import scenario as source_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import Definition,project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator,operator,untouched,InspectionFailed


def configure(case,operator,*,rows=3,advance_rows=None,advance_root_precision=None):
    doctype=case.invoice.doctype
    root=case.data.raw_metas[doctype]
    for name in (*calc.TOTAL_FIELDS,"total_qty","total_advance"):
        if name not in root.definitions:
            root.definitions[name]=Definition(name,fieldtype="Float" if name=="total_qty" else "Currency",options="currency")
            case.data.records["header"][0][name]=Decimal("0.000000000")
            if hasattr(case.data.connection,"signatures"):
                case.data.connection.signatures["header",name]=list(case.data.connection.signatures["header","total"])
    itemtype="Sales Invoice Item" if doctype=="Sales Invoice" else "POS Invoice Item"
    item=case.data.raw_metas[itemtype]
    for name in ("base_amount","base_net_amount"):
        item.definitions[name]=Definition(name,fieldtype="Currency",options="Company:company:default_currency")
        case.data.records["items"][0][name]=Decimal("1.000000000")
        if hasattr(case.data.connection,"signatures"):
            case.data.connection.signatures["items",name]=list(case.data.connection.signatures["items","amount"])
    first=case.data.records["items"][0]
    case.data.records["items"]=[dict(first,name="items-"+str(i+1),idx=i+1) for i in range(rows)]
    case.data.records["advances"]=[dict(name="advances-"+str(i+1),idx=i+1,parent=case.invoice.name,
        parenttype=doctype,parentfield="advances",modified=case.invoice.modified,
        reference_type="Payment Entry",reference_name="SYNTHETIC-PAYMENT",allocated_amount=Decimal("1.000000000"))
        for i in range(rows if advance_rows is None else advance_rows)]
    if advance_root_precision is not None:
        root.definitions["total_advance"].values["precision"]=str(advance_root_precision)
    for raw in (root,item):
        case.applied[raw.name]=case.data.metas[raw.name]=project(raw)
        case.observations[raw.name]=observed_metadata(raw)
    service=case.service
    bind_numeric(case,operator)
    case.service=service
    return case


def scenario(operator,monkeypatch,*,doctype="Sales Invoice",value="Commercial Rounding",rows=3):
    return configure(source_case(operator,monkeypatch,doctype=doctype,value=value),operator,rows=rows)


def capture(case,major,fields):
    return case.service.capture_rounding_stage_context(case.invoice.name,fields,erp_major=major,doctype=case.invoice.doctype)


def controller(name,major,namespace):
    text=controller_text(name,major)
    exec(compile(text,"primary-controller/"+name,"exec"),namespace)
    return namespace[name]


def item_values(source,*,stage="NUMERIC_FIXED",values=None):
    rows=dict(json.loads(source.numeric.view.financial.financial._payload)["tables"])["items"]["rows"]
    if values is None:values=(1.0,)*len(rows)
    return calc.CalculationRows(source.numeric.view.financial,"items",stage,
        tuple((row[0],1.0,value,value,value,value) for row,value in zip(rows,values)))


def net_probe(calculation,major,upstream16,monkeypatch,raw):
    probe=framework(major,upstream16,monkeypatch,setting=raw)
    precisions=[];before=[]
    doc=SimpleNamespace()
    items=[SimpleNamespace(**dict(zip(calc.ITEM_FIELDS,row[1:]))) for row in calculation.rows.values]
    def precision(name,parentfield):
        value=next(value.precision.precision for value in calculation.source.fields if value.target[2]==name)
        precisions.append((name,parentfield,value));return value
    owner=SimpleNamespace(precision=precision)
    def round_totals(target,names):
        before.extend((name,getattr(target,name)) for name in names)
        probe.method(owner,target,names)
    doc.round_floats_in=round_totals
    doc.get=lambda name:getattr(doc,name,None)
    doc.set=lambda name,value:setattr(doc,name,value)
    controller("calculate_net_total",major,{})(SimpleNamespace(doc=doc,_items=items))
    after=tuple((name,getattr(doc,name)) for name in calc.TOTAL_FIELDS)
    settings=tuple((call.args[0],raw) for call in probe.runtime.get_system_settings.call_args_list)
    return tuple(before),after,doc.total_qty,settings,tuple(precisions)


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("raw",[None,"","Commercial Rounding"])
def test_net_totals_use_current_rows_and_match_real_controller(defaults_operator,monkeypatch,upstream16,major,doctype,raw):
    case=scenario(defaults_operator,monkeypatch,doctype=doctype,value=raw)
    source=capture(case,major,calc.TOTAL_FIELDS)
    for values in ((1.0,1.0,1.0),(0.1,0.2,0.3),(-1.25,2.675,-0.0),(1e16,1.0,-1e16)):
        representation="NUMERIC_FIXED" if values==(1.0,1.0,1.0) else "CALCULATED"
        calculation=calc.NetTotalsCalculation(source,item_values(source,stage=representation,values=values))
        before,after,qty,settings,precision=net_probe(calculation,major,upstream16,monkeypatch,raw)
        calculation.require_match(before,after,total_qty=qty,setting_trace=settings,precision_trace=precision)
        # The unchanged saved-value stage must not certify calculated totals.
        with pytest.raises(RoundingStageError):source.require_stage_match(before,after,setting_trace=settings,precision_trace=precision)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
def test_advance_aggregation_prefix_matches_direct_row_precision(defaults_operator,monkeypatch,upstream16,major):
    case=configure(source_case(defaults_operator,monkeypatch,value=None),defaults_operator,
        advance_root_precision=3)
    source=capture(case,major,("total_advance",))
    assert source.fields[0].precision.precision==3
    for amounts in ((1.0,1.0,1.0),(None,1.255,-0.5),(1.25,-1.25,None)):
        rows=calc.CalculationRows(source.numeric.view.financial,"advances","CALCULATED",
            tuple(("advances-"+str(i+1),value) for i,value in enumerate(amounts)))
        calculation=calc.AdvanceAggregateCalculation(source,rows)
        probe=framework(major,upstream16,monkeypatch,setting=None)
        traces=[];seen=[]
        class Checkpoint(Exception):pass
        class Root:
            def __setattr__(self,name,value):
                if name=="total_advance":seen.append(value);raise Checkpoint
                object.__setattr__(self,name,value)
            def get(self,name):return getattr(self,name,None)
            def precision(self,name):traces.append((source.numeric.view.financial.financial.name,name,3));return 3
        doc=Root();doc.docstatus=SimpleNamespace(is_cancelled=lambda:False)
        doc.advances=[]
        for rowname,value in rows.values:
            def precision(name,rowname=rowname):traces.append((rowname,name,2));return 2
            doc.advances.append(SimpleNamespace(allocated_amount=value,precision=precision))
        with pytest.raises(Checkpoint):controller("calculate_total_advance",major,{"flt":probe.flt})(SimpleNamespace(doc=doc))
        settings=tuple((call.args[0],None) for call in probe.runtime.get_system_settings.call_args_list)
        calculation.require_match(total_advance=seen[0],setting_trace=settings,precision_trace=tuple(traces))
        assert len(settings)==1+sum(value is not None for value in amounts)


@pytest.mark.parametrize("major",[15,16])
def test_distinct_quantity_and_base_net_amounts_keep_the_controller_mapping(defaults_operator,monkeypatch,upstream16,major):
    source=capture(scenario(defaults_operator,monkeypatch),major,calc.TOTAL_FIELDS)
    rows=calc.CalculationRows(source.numeric.view.financial,"items","CALCULATED",(
        ("items-1",2.0,8.7,32.625,7.565,28.36875),
        ("items-2",-1.0,-2.3,-8.625,-2.0,-7.5),
        ("items-3",0.5,1.725,6.46875,1.5,5.625),
    ))
    result=calc.NetTotalsCalculation(source,rows)
    before,after,qty,settings,precision=net_probe(result,major,upstream16,monkeypatch,"Commercial Rounding")
    result.require_match(before,after,total_qty=qty,setting_trace=settings,precision_trace=precision)
    assert qty==1.5 and len(set(value for name,value in before))==4


def test_calculated_input_mode_does_not_silently_claim_saved_projection(defaults_operator,monkeypatch):
    source=capture(scenario(defaults_operator,monkeypatch),16,calc.TOTAL_FIELDS)
    current=item_values(source,stage="CALCULATED",values=(2.0,3.0,4.0))
    assert calc.NetTotalsCalculation(source,current).before[0]==("total",9.0)
    with pytest.raises(calc.CalculatedTotalsError):replace(current,representation="NUMERIC_FIXED")
    for changes in (dict(values=tuple(reversed(current.values))),dict(values=current.values[:1]),dict(table="advances")):
        with pytest.raises(calc.CalculatedTotalsError):replace(current,**changes)
    wrong=((current.values[0][0],True,*current.values[0][2:]),*current.values[1:])
    with pytest.raises(calc.CalculatedTotalsError):replace(current,values=wrong)


def test_single_row_totals_keep_framework_initial_types(defaults_operator,monkeypatch,upstream16):
    case=scenario(defaults_operator,monkeypatch,rows=1)
    source=capture(case,16,calc.TOTAL_FIELDS)
    calculation=calc.NetTotalsCalculation(source,item_values(source))
    before,after,qty,settings,precision=net_probe(calculation,16,upstream16,monkeypatch,"Commercial Rounding")
    calculation.require_match(before,after,total_qty=qty,setting_trace=settings,precision_trace=precision)
    assert type(qty) is float


def test_empty_invoice_keeps_existing_financial_source_refusal(defaults_operator,monkeypatch):
    case=scenario(defaults_operator,monkeypatch,rows=0)
    with pytest.raises(InspectionFailed):capture(case,16,calc.TOTAL_FIELDS)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
def test_empty_controller_totals_do_not_authorize_an_empty_invoice(upstream16,monkeypatch,major):
    probe=framework(major,upstream16,monkeypatch,setting="Commercial Rounding")
    owner=SimpleNamespace(precision=lambda *args:2)
    doc=SimpleNamespace()
    doc.round_floats_in=lambda target,names:probe.method(owner,target,names)
    doc.get=lambda name:getattr(doc,name,None)
    doc.set=lambda name,value:setattr(doc,name,value)
    controller("calculate_net_total",major,{})(SimpleNamespace(doc=doc,_items=[]))
    assert all(type(getattr(doc,name)) is float and getattr(doc,name)==0.0
        for name in (*calc.TOTAL_FIELDS,"total_qty"))


@pytest.mark.parametrize("major",[15,16])
def test_empty_advance_table_keeps_builtin_integer_sum(defaults_operator,monkeypatch,major):
    case=scenario(defaults_operator,monkeypatch)
    case.data.records["advances"]=[]
    service=case.service;bind_numeric(case,defaults_operator);case.service=service
    source=capture(case,major,("total_advance",))
    rows=calc.CalculationRows(source.numeric.view.financial,"advances","NUMERIC_FIXED",())
    result=calc.AdvanceAggregateCalculation(source,rows)
    assert type(result.total_allocated) is int and result.total_allocated==0
    result.require_match(total_advance=0.0,setting_trace=(("rounding_method","Commercial Rounding"),),
        precision_trace=((case.invoice.name,"total_advance",2),))


def test_primary_controller_inventory_keeps_versioned_call_order_and_item_skips():
    def body(name,major):
        return ast.parse(controller_text(name,major)).body[0]
    def direct_calls(node):
        return tuple(stmt.value.func.attr for stmt in node.body if isinstance(stmt,ast.Expr)
            and isinstance(stmt.value,ast.Call) and isinstance(stmt.value.func,ast.Attribute))
    fifteen=direct_calls(body("_calculate",15));sixteen=direct_calls(body("_calculate",16))
    assert "apply_mapped_additional_discount" not in fifteen
    assert sixteen.index("apply_mapped_additional_discount") < sixteen.index("calculate_net_total")
    assert "_cleanup" in fifteen and "_cleanup" not in sixteen
    sixteen_items=body("calculate_item_values",16)
    skip=next(stmt.value for stmt in sixteen_items.body if isinstance(stmt,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=="do_not_round_fields" for target in stmt.targets))
    assert ast.literal_eval(skip)==["valuation_rate","incoming_rate","sales_incoming_rate","conversion_factor"]
    assert ast.dump(body("calculate_net_total",15))==ast.dump(body("calculate_net_total",16))


def controller_text(name,major):
    if major==15:
        path=Path(__file__).resolve().parents[5]/"apps/erpnext/erpnext/controllers/taxes_and_totals.py"
        cls=next(node for node in ast.parse(path.read_text()).body if isinstance(node,ast.ClassDef) and node.name=="calculate_taxes_and_totals")
        return ast.unparse(next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name==name))
    record=json.loads(Path(__file__).with_name("erpnext16_rounded_total_oracle.json").read_text())
    return record["files"]["erpnext/controllers/taxes_and_totals.py"]["calculation_stages"]["excerpts"][name]


@pytest.mark.parametrize("fault",["nan","decimal","signed_zero","row_order","missing_row"])
def test_current_observations_refuse_type_repair_and_tampered_derived_values(defaults_operator,monkeypatch,fault):
    source=capture(scenario(defaults_operator,monkeypatch),16,calc.TOTAL_FIELDS)
    inputs=item_values(source)
    if fault in ("nan","decimal"):
        value=float("nan") if fault=="nan" else Decimal("1")
        changed=((inputs.values[0][0],value,*inputs.values[0][2:]),*inputs.values[1:])
        with pytest.raises(calc.CalculatedTotalsError):replace(inputs,values=changed)
    elif fault in ("row_order","missing_row"):
        with pytest.raises(calc.CalculatedTotalsError):replace(inputs,values=inputs.values[::-1] if fault=="row_order" else inputs.values[:1])
    else:
        calculation=calc.NetTotalsCalculation(source,item_values(source,stage="CALCULATED",values=(0.0,0.0,0.0)))
        object.__setattr__(calculation,"before",(("total",-0.0),*calculation.before[1:]))
        with pytest.raises(calc.CalculatedTotalsError):
            calculation.require_match(calculation.before,calculation.after,total_qty=3.0,
                setting_trace=(("rounding_method","Commercial Rounding"),),
                precision_trace=tuple((name,None,2) for name in calc.TOTAL_FIELDS))


@pytest.mark.parametrize("major",[15,16])
def test_zero_precision_legacy_advance_sum_keeps_integer_accumulation(defaults_operator,monkeypatch,major):
    case=scenario(defaults_operator,monkeypatch,value="Banker's Rounding (legacy)")
    for dt,field in ((case.invoice.doctype,"total_advance"),("Sales Invoice Advance","allocated_amount")):
        raw=case.data.raw_metas[dt]
        raw.definitions[field].values["precision"]="0"
        case.applied[dt]=case.data.metas[dt]=project(raw)
        case.observations[dt]=observed_metadata(raw)
    service=case.service;bind_numeric(case,defaults_operator);case.service=service
    source=capture(case,major,("total_advance",))
    rows=calc.CalculationRows(source.numeric.view.financial,"advances","CALCULATED",
        (("advances-1",9007199254740991.0),("advances-2",1.0),("advances-3",-9007199254740991.0)))
    calculation=calc.AdvanceAggregateCalculation(source,rows)
    assert type(calculation.total_allocated) is int and calculation.total_allocated==1
    assert type(calculation.total_advance) is int and calculation.total_advance==1


@pytest.mark.parametrize("major",[15,16])
def test_cancelled_controller_skips_advance_aggregation(upstream16,monkeypatch,major):
    def forbidden(*args,**kwargs):raise AssertionError("cancelled aggregate must not run")
    doc=SimpleNamespace(docstatus=SimpleNamespace(is_cancelled=lambda:True),total_advance=777,precision=forbidden,get=forbidden)
    controller("calculate_total_advance",major,{"flt":forbidden})(SimpleNamespace(doc=doc))
    assert doc.total_advance==777


@pytest.mark.parametrize("empty",[False,True])
def test_unproven_direct_advance_currency_is_not_replaced_by_parent_precision(defaults_operator,monkeypatch,empty):
    case=scenario(defaults_operator,monkeypatch)
    case.database.defaults=[(*row[:-1],"") for row in case.database.defaults]
    case.cache.return_value={"currency_precision":""}
    raw=case.data.raw_metas[case.invoice.doctype]
    raw.definitions["total_advance"].values["precision"]="2"
    case.applied[raw.name]=case.data.metas[raw.name]=project(raw)
    case.observations[raw.name]=observed_metadata(raw)
    if empty:case.data.records["advances"]=[]
    service=case.service;bind_numeric(case,defaults_operator);case.service=service
    source=capture(case,16,("total_advance",))
    inputs=calc.CalculationRows(source.numeric.view.financial,"advances","CALCULATED",
        tuple(("advances-"+str(i+1),1.0) for i in range(0 if empty else 3)))
    if empty:
        result=calc.AdvanceAggregateCalculation(source,inputs)
        assert result.row_precision is None and result.total_advance==0.0
    else:
        with pytest.raises(calc.CalculatedTotalsError,match="calculation_advance_aggregate"):
            calc.AdvanceAggregateCalculation(source,inputs)


def test_derived_net_totals_require_complete_exact_results_and_traces(defaults_operator,monkeypatch):
    source=capture(scenario(defaults_operator,monkeypatch),16,calc.TOTAL_FIELDS)
    result=calc.NetTotalsCalculation(source,item_values(source))
    valid=dict(before=result.before,after=result.after,total_qty=result.total_qty,
        setting_trace=(("rounding_method","Commercial Rounding"),),
        precision_trace=tuple((name,None,2) for name in calc.TOTAL_FIELDS))
    result.require_match(**valid)
    faults=(dict(before=result.before[::-1]),dict(after=result.after[:-1]),dict(total_qty=True),
        dict(after=(("total",3),*result.after[1:])),dict(setting_trace=()),
        dict(precision_trace=(("total",None,True),*valid["precision_trace"][1:])))
    for fault in faults:
        with pytest.raises(calc.CalculatedTotalsError):result.require_match(**(valid|fault))


def test_derived_advance_prefix_requires_direct_row_traces_and_float_bits(defaults_operator,monkeypatch):
    source=capture(scenario(defaults_operator,monkeypatch),16,("total_advance",))
    rows=calc.CalculationRows(source.numeric.view.financial,"advances","NUMERIC_FIXED",
        tuple(("advances-"+str(i+1),1.0) for i in range(3)))
    result=calc.AdvanceAggregateCalculation(source,rows)
    traces=tuple((row[0],"allocated_amount",2) for row in rows.values)+((source.numeric.view.financial.financial.name,"total_advance",2),)
    valid=dict(total_advance=3.0,setting_trace=(("rounding_method","Commercial Rounding"),)*4,
        precision_trace=traces)
    result.require_match(**valid)
    for fault in (dict(total_advance=3),dict(setting_trace=valid["setting_trace"][:1]),
            dict(precision_trace=traces[::-1]),dict(precision_trace=traces[:-1])):
        with pytest.raises(calc.CalculatedTotalsError):result.require_match(**(valid|fault))
    object.__setattr__(result,"row_values",list(result.row_values))
    with pytest.raises(calc.CalculatedTotalsError):result.require_match(**valid)


def test_current_observations_are_protected_and_rechecked(defaults_operator,monkeypatch):
    import pickle
    source=capture(scenario(defaults_operator,monkeypatch),16,calc.TOTAL_FIELDS)
    rows=item_values(source)
    result=calc.NetTotalsCalculation(source,rows)
    for value in (rows,result):
        assert source.numeric.view.financial.financial.name not in repr(value)
        with pytest.raises(TypeError):pickle.dumps(value)
    object.__setattr__(rows,"sha256","0"*64)
    with pytest.raises(calc.CalculatedTotalsError):calc.NetTotalsCalculation(source,rows)
