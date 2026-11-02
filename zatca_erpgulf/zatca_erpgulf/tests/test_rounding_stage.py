"""One-owned explicit stage and actual15/pinned16 synthetic document probes."""

from dataclasses import replace
from copy import copy
from decimal import Decimal
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_rounding_stage as stage
from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import scenario
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding_formats import scenario as format_case
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator,operator,untouched,one_failure,PermissionDenied,InspectionFailed,
)


def capture(case,major=16,*,names=("grand_total","net_total"),child=False,skips=None):
    return case.service.capture_rounding_stage_context(case.invoice.name,names,erp_major=major,
        doctype=case.invoice.doctype,parentfield="items" if child else None,
        row_name="items-1" if child else None,do_not_round_fields=skips)


def probe(case,result,major,upstream16,monkeypatch,input_stage="SAVED"):
    raw=case.round_doc.rounding_method
    oracle=framework(major,upstream16,monkeypatch,setting=raw)
    child=result.targets[0][0]!="header"
    doc=case.refs["items"][0] if child else case.invoice
    names=tuple(target[2] for target in result.targets)
    if input_stage=="NUMERIC_FIXED":
        for name in names:
            if doc.get(name) is not None:setattr(doc,name,oracle.flt(doc.get(name)))
    before=tuple((name,doc.get(name)) for name in names)
    precisions=[]
    values={value.target[2]:value.precision.precision for value in result.fields}
    def precision(name,parentfield):
        precisions.append((name,parentfield,values[name]));return values[name]
    case.invoice.precision=precision
    doc.set=lambda name,value:setattr(doc,name,value)
    if major==15:oracle.method(case.invoice,doc,list(names))
    else:oracle.method(case.invoice,doc,list(names),do_not_round_fields=result.do_not_round_fields)
    after=tuple((name,doc.get(name)) for name in names)
    settings=tuple((call.args[0],raw) for call in oracle.runtime.get_system_settings.call_args_list)
    return before,after,settings,tuple(precisions)


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("child",[False,True])
@pytest.mark.parametrize("raw",[None,"","Commercial Rounding"])
@pytest.mark.parametrize("input_stage",["SAVED","NUMERIC_FIXED"])
def test_actual_explicit_stage_matches_one_owned_source(defaults_operator,monkeypatch,upstream16,major,doctype,child,raw,input_stage):
    case=scenario(defaults_operator,monkeypatch,doctype=doctype,value=raw)
    names=("amount","net_amount") if child else ("grand_total","net_total")
    result=capture(case,major,names=names,child=child)
    assert type(result) is stage.SavedRoundingStageRead and len(result.fields)==2
    assert case.factory.call_count==1
    assert case.round_metadata.call_count==2
    before,after,settings,precision=probe(case,result,major,upstream16,monkeypatch,input_stage)
    result.require_stage_match(before,after,setting_trace=settings,precision_trace=precision,input_stage=input_stage)
    assert len(settings)==(3 if not raw else 1)
    assert precision==tuple((name,"items" if child else None,2) for name in names)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("skips",[("net_total",),("net_total","grand_total")])
def test_v16_skipped_values_keep_native_types_without_precision_calls(defaults_operator,monkeypatch,upstream16,skips):
    case=scenario(defaults_operator,monkeypatch)
    if len(skips)==2:case.invoice._precision=object()
    result=capture(case,skips=skips)
    before,after,settings,precision=probe(case,result,16,upstream16,monkeypatch)
    result.require_stage_match(before,after,setting_trace=settings,precision_trace=precision)
    assert type(dict(after)["net_total"]) is Decimal
    assert len(precision)==2-len(skips)


def test_null_does_not_trigger_an_extra_default_method_lookup(defaults_operator,monkeypatch,upstream16):
    case=scenario(defaults_operator,monkeypatch,value=None)
    case.invoice.grand_total=case.data.records["header"][0]["grand_total"]=None
    result=capture(case)
    before,after,settings,precision=probe(case,result,16,upstream16,monkeypatch)
    result.require_stage_match(before,after,setting_trace=settings,precision_trace=precision)
    assert len(settings)==2 and dict(after)["grand_total"]==0.0


@pytest.mark.parametrize("bad",[None,(),[],("grand_total","grand_total"),("company",),("unknown",),tuple("field"+str(i) for i in range(65))])
def test_invalid_explicit_field_selection_does_not_guess_default_order(defaults_operator,monkeypatch,bad):
    case=scenario(defaults_operator,monkeypatch)
    with pytest.raises(InspectionFailed):capture(case,names=bad)
    case.factory.assert_not_called()
    case.metadata_provider.assert_not_called()


def test_v15_skip_keyword_is_rejected_before_sources(defaults_operator,monkeypatch):
    case=scenario(defaults_operator,monkeypatch)
    with pytest.raises(InspectionFailed):capture(case,15,skips=())
    case.factory.assert_not_called()


@pytest.mark.parametrize("bad",["order","missing","amount","method","precision","precision_type","source","target"])
def test_stage_evidence_is_complete_ordered_and_source_bound(defaults_operator,monkeypatch,upstream16,bad):
    case=scenario(defaults_operator,monkeypatch)
    result=capture(case)
    before,after,settings,precision=probe(case,result,16,upstream16,monkeypatch)
    if bad=="order":after=tuple(reversed(after))
    elif bad=="missing":before=before[:1]
    elif bad=="amount":after=((after[0][0],0.0),after[1])
    elif bad=="method":settings=(("rounding_method","Commercial Rounding"),)
    elif bad=="precision":precision=(("grand_total",None,3),precision[1])
    elif bad=="precision_type":precision=(("grand_total",None,2.0),precision[1])
    elif bad=="source":
        with pytest.raises(stage.RoundingStageError):replace(result,method=replace(result.method,erp_major=15))
        return
    else:
        with pytest.raises(stage.RoundingStageError):replace(result,targets=(result.targets[1],result.targets[0]))
        return
    with pytest.raises(stage.RoundingStageError,match="rounding_stage_observation"):
        result.require_stage_match(before,after,setting_trace=settings,precision_trace=precision)


def test_equal_scope_formats_are_read_once(defaults_operator,monkeypatch):
    case=format_case(defaults_operator,monkeypatch)
    child=case.data.raw_metas[case.invoice.doctype]
    # Same-scope standard root field added only to this synthetic declaration.
    from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project
    from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
    child.definitions["net_total"].values["options"]="currency"
    case.applied[case.invoice.doctype]=case.data.metas[case.invoice.doctype]=project(child)
    case.observations[case.invoice.doctype]=observed_metadata(child)
    case.field_overrides[case.invoice.doctype,"net_total"]=case.applied[case.invoice.doctype].get_field("net_total")
    result=capture(case)
    assert all(value.formats.formats.currency=="USD" for value in result.fields)
    assert case.format_metadata.call_count==2
    # Only one initial format source read, with a shared source across fields.
    assert result.fields[0].formats.formats.sha256==result.fields[1].formats.formats.sha256


@pytest.mark.parametrize("boundary",["metadata","cache","close"])
def test_other_selected_field_cannot_change_during_callbacks(defaults_operator,monkeypatch,boundary):
    case=scenario(defaults_operator,monkeypatch)
    def mutate():case.invoice._precision={"main":{"net_total":2}}
    if boundary=="close":case.database.close.side_effect=mutate
    else:
        callback=case.metadata_provider if boundary=="metadata" else case.cache
        old=callback.side_effect
        def invoke(*args):
            value=old(*args) if old else callback.return_value
            if callback.call_count==(4 if boundary=="metadata" else 2):mutate()
            return value
        callback.side_effect=invoke
    with pytest.raises(InspectionFailed):capture(case)
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)


def mixed_currencies(case,operator):
    from zatca_erpgulf.zatca_erpgulf.calculation_precision import CurrencyFormatContext
    usd=copy(case.related["Currency"])
    usd.name,usd.number_format="USD","#,###.###"
    operator.documents["Currency","USD"]=usd
    case.format_data.records["Currency"].append((usd.name,usd.modified,usd.number_format))
    case.format_cache.side_effect=lambda scope,lang,currency:CurrencyFormatContext(lang,
        case.related["Language"].number_format,True,currency,
        operator.documents["Currency",currency].number_format)


def test_distinct_parent_currency_scopes_do_not_share_the_wrong_format(defaults_operator,monkeypatch):
    case=format_case(defaults_operator,monkeypatch,scope="company")
    mixed_currencies(case,defaults_operator)
    cursor=case.database.cursor
    class Cursor:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,params=()):
            rows=case.format_data.records["Currency"]
            try:
                if "FROM `tabCurrency`" in sql:
                    case.format_data.records["Currency"]=[row for row in rows if row[0]==params[0]]
                self.current=cursor();self.current.execute(sql,params)
            finally:case.format_data.records["Currency"]=rows
        def fetchone(self):return self.current.fetchone()
        def fetchall(self):return self.current.fetchall()
        @property
        def description(self):return self.current.description
    case.database.cursor=Mock(side_effect=Cursor)
    result=capture(case,names=("grand_total","base_grand_total"))
    assert [value.formats.formats.currency for value in result.fields]==["USD","SAR"]
    assert [value.precision.precision for value in result.fields]==[3,8]
    assert case.format_metadata.call_count==4


def test_earlier_format_provider_cannot_warm_a_later_fields_currency_slot(defaults_operator,monkeypatch):
    case=format_case(defaults_operator,monkeypatch)
    selected=case.data.raw_metas[case.invoice.doctype]
    from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project
    from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
    selected.definitions["net_total"].values["options"]="currency"
    case.applied[case.invoice.doctype]=case.data.metas[case.invoice.doctype]=project(selected)
    case.observations[case.invoice.doctype]=observed_metadata(selected)
    case.field_overrides[case.invoice.doctype,"net_total"]=case.applied[case.invoice.doctype].get_field("net_total")
    local={(case.invoice.doctype,case.invoice.name):{"grand_total":"USD"}}
    defaults_operator.runtime.local.field_currency=local
    old=case.format_metadata.side_effect
    def metadata(*args):
        result=old(*args)
        local[case.invoice.doctype,case.invoice.name]["net_total"]="USD"
        return result
    case.format_metadata.side_effect=metadata
    with pytest.raises(InspectionFailed):capture(case)
