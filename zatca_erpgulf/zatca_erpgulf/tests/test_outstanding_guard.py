"""Guard truth/short-circuit comparisons with compiled actual15/pinned16 bodies."""
import ast
import itertools
import json
import pickle
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_outstanding_guard import OutstandingGuardInputs,OutstandingGuardDecision,OutstandingGuardError
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller_text


@pytest.fixture(scope="module")
def primary_methods():
    result={}
    for major in (15,16):
        texts={name:controller_text(name,major) for name in ("calculate_outstanding_amount","is_internal_invoice")}
        if major==15:
            path=Path(__file__).resolve().parents[5]/"apps/erpnext/erpnext/controllers/accounts_controller.py"
            cls=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.ClassDef) and n.name=="AccountsController")
            texts["is_internal_transfer"]=ast.unparse(next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="is_internal_transfer"))
        else:
            record=json.loads(Path(__file__).with_name("erpnext16_rounded_total_oracle.json").read_text())
            texts["is_internal_transfer"]=record["files"]["erpnext/controllers/accounts_controller.py"]["excerpts"]["is_internal_transfer"]
        compiled={}
        for name,text in texts.items():
            namespace={};exec(compile(text,'primary/'+name,'exec'),namespace);compiled[name]=namespace[name]
        result[major]=compiled
    return result


def entry_probe(inputs,methods,paid_callback=None):
    """Stop at the first ordinary-rounding call; no later POS/SQL work runs."""
    calls=[];resets=[];continuation=[]
    class Boundary(Exception):pass
    class Root:
        def __setattr__(self,name,value):
            object.__setattr__(self,name,value)
            if name=="outstanding_amount" and getattr(self,"ready",False):
                calls.append("reset_outstanding");resets.append((name,value))
        def get(self,name):return getattr(self,name,None)
        def round_floats_in(self,doc,fields):
            assert doc is self and fields==["grand_total","total_advance","write_off_amount"]
            calls.append("round_floats_in");continuation.append(True);raise Boundary
    doc=Root();doc.ready=False
    for name in ("doctype","company","is_return","is_pos","return_against","update_outstanding_for_self","is_internal_customer","represents_company"):
        setattr(doc,name,getattr(inputs,name))
    doc.outstanding_amount=17.0;doc.ready=True
    def internal_transfer():
        calls.append("is_internal_transfer");return methods["is_internal_transfer"](doc)
    doc.is_internal_transfer=internal_transfer
    owner=SimpleNamespace(doc=doc)
    def internal_invoice():
        calls.append("is_internal_invoice");return methods["is_internal_invoice"](owner)
    def paid():
        calls.append("calculate_paid_amount")
        if paid_callback:paid_callback(doc)
    owner.is_internal_invoice=internal_invoice;owner.calculate_paid_amount=paid
    try:methods["calculate_outstanding_amount"](owner)
    except Boundary:pass
    assert len(resets)<=1
    return SimpleNamespace(doc=doc,calls=tuple(calls),reset=resets[0] if resets else None,continues=bool(continuation))


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("flags",tuple(itertools.product((None,0,1),(None,"","ORIGINAL"," "),(None,0,1),(None,0,1))))
def test_exact_return_internal_precedence_and_paid_before_zero(primary_methods,major,doctype,flags):
    is_return,reference,update,is_pos=flags
    for internal,represented in itertools.product((None,0,1),(None,"","OTHER","COMPANY")):
        inputs=OutstandingGuardInputs(doctype,"COMPANY",is_return,is_pos,reference,update,internal,represented)
        decision=OutstandingGuardDecision(inputs)
        observation=entry_probe(inputs,primary_methods[major])
        decision.require_match(calls=observation.calls,reset=observation.reset,continues=observation.continues)
        if observation.continues:assert observation.doc.outstanding_amount==17.0
        else:assert type(observation.doc.outstanding_amount) is int and observation.doc.outstanding_amount==0


@pytest.mark.parametrize("value",[True,False,1.0,"1",2,-1])
def test_noncanonical_flag_inputs_are_refused(value):
    with pytest.raises(OutstandingGuardError):OutstandingGuardInputs("Sales Invoice","COMPANY",value,0,None,0,0,None)


def test_output_types_call_order_and_serialization_are_strict():
    inputs=OutstandingGuardInputs("Sales Invoice","COMPANY",1,0,"ORIGINAL",0,1,"COMPANY")
    decision=OutstandingGuardDecision(inputs)
    valid=dict(calls=("calculate_paid_amount","reset_outstanding"),reset=("outstanding_amount",0),continues=False)
    decision.require_match(**valid)
    for changes in (dict(reset=("outstanding_amount",0.0)),dict(continues=0),dict(calls=tuple(reversed(valid["calls"]))),dict(calls=[*valid["calls"]])):
        with pytest.raises(OutstandingGuardError):decision.require_match(**(valid|changes))
    changed=replace(decision);object.__setattr__(changed,"skip_balance",1)
    with pytest.raises(OutstandingGuardError):changed.require_match(**valid)
    for value in (inputs,decision):
        assert "ORIGINAL" not in repr(value)
        with pytest.raises(TypeError):pickle.dumps(value)
