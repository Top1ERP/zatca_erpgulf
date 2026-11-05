"""One owned paid/entry-guard proof on NEW TCP-disabled temporary SQL only."""
import copy
import json
import os
import pickle
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import calculation_guarded_payments as guarded
from zatca_erpgulf.zatca_erpgulf import calculation_outstanding_guard as guard
from zatca_erpgulf.zatca_erpgulf import calculation_payments as payment
from zatca_erpgulf.zatca_erpgulf.source_metadata import OUTSTANDING_GUARDS_PROFILE
from zatca_erpgulf.zatca_erpgulf.metadata_source import SelectedMetadataRows
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _canonical
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta,Definition,project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_payments_mariadb import native_case as previous
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access_mariadb import native_case as base_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller
from zatca_erpgulf.zatca_erpgulf.tests.test_outstanding_guard import primary_methods,entry_probe
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

pytestmark=pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB")!="1",reason="NEW guard-owned temporary SQL only; no tenant or authority access")

SCENARIOS=(
    ("return-linked",1,0,"ORIGINAL",0,0,None),
    ("return-self",1,0,"ORIGINAL",1,0,None),
    ("return-pos",1,1,"ORIGINAL",0,0,None),
    ("internal",0,1,None,0,1,"same"),
    ("cross-company",0,1,None,0,1,"other"),
    ("ordinary",0,0,None,0,0,None),
)


def native_case(operator,connections,*,scenario=SCENARIOS[0],doctype="Sales Invoice"):
    label,is_return,is_pos,reference,update,internal,represented=scenario
    has_payment=doctype=="Sales Invoice"
    case=previous(operator,connections,flags=(is_pos,is_return,1)) if has_payment else base_case(operator,connections,doctype=doctype)
    root=case.data.raw_metas[case.invoice.doctype]
    present=guard.FIELDS if has_payment else guard.LockedOutstandingGuardsRead.OVERLAP
    raw=AppliedMeta(root.name,present);links=dict(guard.LINKS)
    for name,df in raw.definitions.items():
        df.values.update(fieldtype="Link" if name in links else "Check",options=(links[name] or root.name) if name in links else None)
        df.fieldtype=df.get("fieldtype");df.fieldname=name
        if name in guard.LockedOutstandingGuardsRead.OVERLAP:root.definitions[name]=df
    values=dict(company=case.company.name,is_return=is_return,is_pos=is_pos,return_against=reference,
        update_outstanding_for_self=update,is_internal_customer=internal,
        represents_company=case.company.name if represented=="same" else "OTHER-COMPANY" if represented=="other" else None)
    for name in guard.LockedOutstandingGuardsRead.OVERLAP:case.data.records["header"][0][name]=values[name]
    case.applied[root.name]=case.data.metas[root.name]=project(root)
    case.observations[root.name]=observed_metadata(root)
    initial=observed_metadata(raw,profile=OUTSTANDING_GUARDS_PROFILE);body=json.loads(initial._payload)
    originals={dict(r["header"])["fieldname"][1]:r for r in json.loads(case.observations[root.name]._payload)["docfields"]}
    for i,row in enumerate(body["docfields"]):
        name=dict(row["header"])["fieldname"][1]
        if name in guard.LockedOutstandingGuardsRead.OVERLAP:body["docfields"][i]=originals[name]
        else:row["name"]+="-GUARD"
    body["docfields"].sort(key=lambda row:row["name"])
    case.guard_observation=SelectedMetadataRows(initial.applied,_canonical(body))
    case.guard_metadata=Mock(side_effect=lambda *args:{root.name:case.guard_observation.applied})
    service,overrides=case.service,dict(case.field_overrides)
    bind_numeric(case,operator);case.field_overrides.update(overrides)
    case.invoice.meta.istable=case.invoice.meta.issingle=0
    for name,df in raw.definitions.items():
        case.field_overrides[root.name,name]=df;setattr(case.invoice,name,values[name])
    for name in guard.FIELDS:
        if name not in present:setattr(case.invoice,name,None)
    if has_payment:
        # Saved money getters retain native Decimal identity.
        case.invoice.loyalty_amount=Decimal("1.234500000")
    case.service=access.SavedCalculationDefaultsService(case.scope,case.factory,case.cache,
        applied_metadata_reader=case.metadata_provider,
        rounding_metadata_reader=service._rounding_metadata,rounding_cache_reader=service._rounding_cache,
        format_metadata_reader=service._format_metadata,format_cache_reader=service._format_cache,
        owner_currency_metadata_reader=service._owner_currency_metadata,company_currency_cache_reader=service._company_currency_cache,
        payment_controls_metadata_reader=getattr(case,"controls_metadata",None),outstanding_guard_metadata_reader=case.guard_metadata)
    setup=connections()
    with setup.cursor() as cursor:
        for name in guard.FIELDS:
            if name not in present:
                cursor.execute("ALTER TABLE `tab"+doctype+"` DROP COLUMN IF EXISTS `"+name+"`")
            else:cursor.execute("ALTER TABLE `tab"+doctype+"` ADD COLUMN IF NOT EXISTS `"+name+"` "+("LONGTEXT" if name in links else "INT"))
        cursor.execute("UPDATE `tab"+doctype+"` SET "+','.join('`'+name+'`=%s' for name in present),tuple(values[name] for name in present))
        cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s",(doctype,))
    seed_metadata(setup,case.observations[root.name],groups=("docfields",))
    if has_payment:
        with setup.cursor() as cursor:cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s AND fieldname IN ('is_pos','is_return')",(doctype,))
        seed_metadata(setup,case.controls_observation,groups=("docfields",))
    with setup.cursor() as cursor:cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s AND fieldname IN ('company','is_pos','is_return','return_against')",(doctype,))
    seed_metadata(setup,case.guard_observation,groups=("docfields",))
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    case.guard_values=values
    return case


def capture(case,major=16,*,combined=True):
    method=case.service.capture_guarded_payment_context if combined else case.service.capture_outstanding_guard_context
    return method(case.invoice.name,erp_major=major)


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("scenario",SCENARIOS,ids=[s[0] for s in SCENARIOS])
def test_actual_paid_is_required_before_reset_or_continuation(defaults_operator,connections,upstream16,monkeypatch,primary_methods,major,scenario):
    case=native_case(defaults_operator,connections,scenario=scenario)
    source=capture(case,major)
    paid=payment.PaidAmountCalculation(source.payment,"CALCULATED",(("conversion_rate",1.23456789),("loyalty_amount",1.255)),
        tuple((name,value) for (name,_),value in zip(source.payment.payment_types,(10.255,0.0,None))))
    calculation=guarded.GuardedOutstandingEntry(source,paid)
    probe=framework(major,upstream16,monkeypatch,setting=source.payment.stage.method.rounding.value)
    trace=[];observed={};precisions={name:p.precision.precision for name,p in zip(payment.PAID_FIELDS,source.payment.stage.fields)}
    inputs=calculation.decision.inputs
    def run_paid(doc):
        for name,value in paid.headers:setattr(doc,name,value)
        doc.redeem_loyalty_points=1
        types={name:None if tag==("null",) else tag[1] for name,tag in source.payment.payment_types}
        doc.payments=[SimpleNamespace(name=name,amount=value,base_amount=999.0,type=types[name]) for name,value in paid.rows]
        cleared=[]
        doc.set=lambda name,value:(cleared.append(name),setattr(doc,name,value))[-1]
        doc.precision=lambda name:(trace.append((name,precisions[name])),precisions[name])[-1]
        controller("calculate_paid_amount",major,{"flt":probe.flt})(SimpleNamespace(doc=doc))
        observed.update(payments=tuple((r.name,r.amount,r.base_amount) for r in doc.payments) if doc.is_pos else (),
            totals=tuple((name,getattr(doc,name)) for name in payment.PAID_FIELDS),clear_payments=bool(cleared))
    actual=entry_probe(inputs,primary_methods[major],run_paid)
    raw=source.payment.stage.method.rounding.value
    calculation.require_match(**observed,paid_setting_trace=tuple((c.args[0],raw) for c in probe.runtime.get_system_settings.call_args_list),
        paid_precision_trace=tuple(trace),calls=actual.calls,reset=actual.reset,continues=actual.continues)
    assert len(case.opened)==1 and case.factory.call_count==1
    assert (actual.reset is not None)==(scenario[0] in ("return-linked","internal"))
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator,case)


def test_guard_only_does_not_read_money_getters_or_rounding_providers(defaults_operator,connections):
    case=native_case(defaults_operator,connections)
    original=case.invoice.get
    def get(name,*args):
        if name in ("grand_total","base_grand_total","paid_amount","loyalty_amount"):raise AssertionError('unused money getter')
        return original(name,*args)
    case.invoice.get=get
    source=capture(case,16,combined=False)
    assert guard.OutstandingGuardDecision.from_saved(source).skip_balance
    for callback in (case.round_metadata,case.round_cache):callback.assert_not_called()
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
def test_pos_self_reference_and_absent_standard_flags(defaults_operator,connections,major):
    case=native_case(defaults_operator,connections,doctype="POS Invoice",scenario=("pos",1,1,"ORIGINAL",None,None,None))
    source=case.service.capture_outstanding_guard_context(case.invoice.name,erp_major=major,doctype="POS Invoice")
    assert source.controls.metadata.applied.get_field("return_against").options=="POS Invoice"
    assert dict(source.controls.normalized_checks)["is_internal_customer"] is None
    decision=guard.OutstandingGuardDecision.from_saved(source)
    assert not decision.skip_balance and decision.calls==("is_internal_invoice","round_floats_in")
    for callback in (case.round_metadata,case.round_cache):callback.assert_not_called()
    untouched(defaults_operator,case)


@pytest.mark.parametrize("field",["update_outstanding_for_self","is_internal_customer","represents_company"])
def test_side_read_levels_precede_providers_and_sql(defaults_operator,connections,field):
    case=native_case(defaults_operator,connections)
    case.field_overrides[case.invoice.doctype,field].values["permlevel"]=1
    with pytest.raises(PermissionDenied):capture(case)
    for callback in (case.factory,case.guard_metadata,case.controls_metadata,case.metadata_provider):callback.assert_not_called()
    one_failure(defaults_operator,access.FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("changed",["flag","reference","representation","options"])
def test_native_guard_drift_without_revision_is_rolled_back(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    old=case.guard_metadata.side_effect;edits=[]
    def read(*args):
        value=old(*args)
        if case.guard_metadata.call_count==2:
            with case.opened[0].cursor() as cursor:
                if changed=="flag":cursor.execute("UPDATE `tabSales Invoice` SET update_outstanding_for_self=1")
                elif changed=="reference":cursor.execute("UPDATE `tabSales Invoice` SET return_against='CHANGED'")
                elif changed=="representation":cursor.execute("UPDATE `tabSales Invoice` SET represents_company='OTHER'")
                else:cursor.execute("UPDATE `tabDocField` SET options='Customer' WHERE parent='Sales Invoice' AND fieldname='represents_company'")
            edits.append(changed)
        return value
    case.guard_metadata.side_effect=read
    with pytest.raises(InspectionFailed):capture(case)
    assert edits==[changed]
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)
    observer=connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT update_outstanding_for_self,return_against,represents_company FROM `tabSales Invoice`")
        assert cursor.fetchone()==(0,"ORIGINAL",None)
        cursor.execute("SELECT options FROM `tabDocField` WHERE parent='Sales Invoice' AND fieldname='represents_company'")
        assert cursor.fetchone()==("Company",)
    observer.close()


@pytest.mark.parametrize("changed",["original","fresh_parent","metadata"])
def test_close_cannot_hide_original_guard_or_definition_changes(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    def wrap(connection):
        old=connection.close.side_effect
        def close():
            value=old()
            if changed=="fresh_parent":defaults_operator.documents[case.invoice.doctype,case.invoice.name]=copy.copy(case.invoice)
            if changed in ("original","fresh_parent"):case.invoice.return_against="CHANGED"
            else:case.field_overrides[case.invoice.doctype,"represents_company"].values["options"]="Customer"
            return value
        connection.close.side_effect=close
    case.before_handoff=wrap
    with pytest.raises(InspectionFailed):capture(case)
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)


def test_coowned_context_and_guard_snapshots_cannot_be_rebound(defaults_operator,connections):
    case=native_case(defaults_operator,connections)
    source=capture(case)
    wrong=replace(source.guard,owner_document=source.guard.owner_document+1)
    with pytest.raises(guard.OutstandingGuardError):replace(source,guard=wrong)
    with pytest.raises(guard.OutstandingGuardError):replace(source.guard,values=tuple(reversed(source.guard.values)))
    paid=payment.PaidAmountCalculation(source.payment,"NUMERIC_FIXED",(("conversion_rate",1.0),("loyalty_amount",1.2345)),
        tuple((name,1.0) for name,_ in source.payment.payment_types))
    entry=guarded.GuardedOutstandingEntry(source,paid)
    class ForeignDecision:
        def __eq__(self,other):return True
        def require_match(self,**kwargs):pass
    object.__setattr__(entry,"decision",ForeignDecision())
    with pytest.raises(guard.OutstandingGuardError):
        entry.require_match(payments=paid.payments,totals=paid.totals,clear_payments=paid.clear_payments,
            paid_setting_trace=(("rounding_method","Commercial Rounding"),)*2,
            paid_precision_trace=(("paid_amount",2),("base_paid_amount",3)),
            calls=("calculate_paid_amount","round_floats_in"),reset=None,continues=True)
    for value in (source,source.guard):
        assert "ORIGINAL" not in repr(value)
        with pytest.raises(TypeError):pickle.dumps(value)
    untouched(defaults_operator,case)
