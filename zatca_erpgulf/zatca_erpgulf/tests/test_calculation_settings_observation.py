"""Synthetic POS/currency/Singleton settings; no site defaults or authority."""

import json
import pickle
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_settings_observation as calc
from zatca_erpgulf.zatca_erpgulf import issuing_settings_observation as issuing
from zatca_erpgulf.zatca_erpgulf import tax_dependency_observation as tax
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import (
    Document, Metadata, erp_major, case, capture as capture_financial,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_settings_observation import scenario as settings_scenario, SECRETS


class Singleton(Document):
    def get(self,name):
        assert name not in ("modified","creation","password","encryption_key")
        return super().get(name)


def scenario(case, *, pos=True, template=True, distinct=False):
    settings_scenario(case)
    case.company.default_currency="USD" if distinct else "SAR"
    case.doc.pos_profile="SYNTHETIC-POS" if pos else None
    case.financial=capture_financial(case)
    case.settings=issuing.capture_issuing_settings_observation(case.financial,records=case.records)
    records,metas={},{}
    for doctype in calc.SINGLETONS:
        meta=Metadata(doctype,calc.FIELDS[doctype])
        meta.issingle=1
        record=Singleton(doctype=doctype,name=doctype,meta=meta)
        for field in calc.FIELDS[doctype]: setattr(record,field,None)
        if doctype=="System Settings":
            record.time_zone,record.float_precision,record.currency_precision="Asia/Riyadh","3","2"
            record.rounding_method="Banker's Rounding (legacy)"
        else:
            record.default_currency="EUR" if distinct else "SAR"
            record.default_company=case.company.name
        records[doctype,doctype]=record
    currencies={"SAR",case.company.default_currency,"EUR" if distinct else "SAR"}
    if pos:
        meta=Metadata("POS Profile",(*calc.POS_FIELDS,"payments"),{"payments":"POS Payment Method"})
        record=Document(doctype="POS Profile",name=case.doc.pos_profile,meta=meta,modified=case.doc.modified)
        for field in calc.POS_FIELDS: setattr(record,field,None)
        record.company=case.company.name
        record.currency="GBP" if distinct else "SAR"
        currencies.add(record.currency)
        record.taxes_and_charges="POS-TAX" if template else None
        record.apply_discount_on="Net Total"
        record.payments=[Document(doctype="POS Payment Method",name="SYNTHETIC-MOP-1",idx=1,
            parent=record.name,parenttype=record.doctype,parentfield="payments",
            mode_of_payment="Cash",default=1,allow_in_returns=0)]
        records[record.doctype,record.name]=record
        metas["POS Profile"]=Metadata("POS Payment Method",calc.PAYMENT_FIELDS)
        if template:
            meta=Metadata(calc.TAX_TEMPLATE,(*tax.TEMPLATE_FIELDS,"taxes"),{"taxes":"Sales Taxes and Charges"})
            taxes=Document(doctype=calc.TAX_TEMPLATE,name="POS-TAX",meta=meta,modified=case.doc.modified,
                company=case.company.name)
            for field in tax.TEMPLATE_FIELDS:
                if not hasattr(taxes,field): setattr(taxes,field,None)
            rows=[]
            for idx in (1,2):
                row=Document(doctype="Sales Taxes and Charges",name="POS-TAX-ROW-"+str(idx),idx=idx,
                    parent=taxes.name,parenttype=taxes.doctype,parentfield="taxes")
                for field in tax.TABLE_PROFILES[calc.TAX_TEMPLATE][1]: setattr(row,field,None)
                row.rate=Decimal("15.00")
                rows.append(row)
            taxes.taxes=rows
            records[taxes.doctype,taxes.name]=taxes
            metas[calc.TAX_TEMPLATE]=Metadata("Sales Taxes and Charges",tax.TABLE_PROFILES[calc.TAX_TEMPLATE][1])
    for name in currencies:
        record=Document(doctype="Currency",name=name,modified=case.doc.modified,
            meta=Metadata("Currency",calc.CURRENCY_FIELDS))
        for field in calc.CURRENCY_FIELDS: setattr(record,field,None)
        record.currency_name,record.enabled,record.fraction_units=name,1,100
        record.smallest_currency_fraction_value=Decimal("0.01")
        records[record.doctype,record.name]=record
    case.records,case.child_metas=records,metas
    return case


def capture(case):
    return calc.capture_calculation_settings_observation(case.settings,records=case.records,child_metas=case.child_metas)


def assert_static(call,code="calculation_settings_capture"):
    with pytest.raises(calc.CalculationSettingsError) as caught: call()
    assert caught.value.code==str(caught.value)==code and caught.value.__context__ is None


@pytest.mark.parametrize("pos,template,distinct",[(False,False,False),(True,False,False),(True,True,False),(True,True,True)])
def test_exact_settings_pos_currency_graph_is_protected_and_side_effect_free(case,pos,template,distinct):
    case=scenario(case,pos=pos,template=template,distinct=distinct)
    result=capture(case)
    assert capture(case)==result and result.settings==case.settings and result.settings is not case.settings
    assert "PARTIAL" in repr(result) and "SYNTHETIC" not in repr(result)
    with pytest.raises(FrozenInstanceError): result.sha256="f"*64
    with pytest.raises(TypeError,match="not_serializable"): pickle.dumps(result)
    for record in case.records.values():
        record.save.assert_not_called()
        record.db_set.assert_not_called()
        assert not set(SECRETS)&set(record.reads)
        if record.doctype in calc.SINGLETONS: assert "modified" not in record.reads


@pytest.mark.parametrize("doctype,field",[(dt,field) for dt,fields in calc.FIELDS.items() for field in fields])
def test_each_calculation_setting_is_a_dependency_without_invoice_revision(case,doctype,field):
    case=scenario(case)
    before,modified=capture(case),case.doc.modified
    record=next(record for (dt,_name),record in case.records.items() if dt==doctype)
    if doctype=="Global Defaults" and field=="default_currency":
        record.default_currency=None
    elif doctype=="POS Profile" and field=="company":
        record.company="OTHER"
        assert_static(lambda:capture(case))
        return
    elif doctype=="POS Profile" and field=="currency":
        record.currency=None
    elif doctype=="POS Profile" and field=="taxes_and_charges":
        record.taxes_and_charges=None
        del case.records[calc.TAX_TEMPLATE,"POS-TAX"]
        del case.child_metas[calc.TAX_TEMPLATE]
    else: setattr(record,field,"CHANGED")
    after=capture(case)
    assert after.sha256!=before.sha256 and case.doc.modified==modified
    assert after.settings.sha256==before.settings.sha256


@pytest.mark.parametrize("field",["time_zone","float_precision","currency_precision","rounding_method"])
def test_singleton_zero_blank_absent_states_are_not_replaced_with_defaults(case,field):
    case=scenario(case)
    record=case.records["System Settings","System Settings"]
    hashes=[]
    for value in (None,"",0,"0",False,"VALUE"):
        setattr(record,field,value)
        hashes.append(capture(case).sha256)
    if field not in calc.REQUIRED["System Settings"]:
        record.meta.fields.remove(field)
        hashes.append(capture(case).sha256)
    assert len(hashes)==len(set(hashes))


def test_singletons_have_explicit_storage_kind_and_no_fabricated_modified(case):
    case=scenario(case)
    result=capture(case)
    for record in json.loads(result._payload)["records"]:
        if record["doctype"] in calc.SINGLETONS:
            assert record["name"]==record["doctype"] and record["singleton"] is True
            assert "modified" not in record


@pytest.mark.parametrize("field",calc.PAYMENT_FIELDS)
def test_each_pos_payment_field_changes_digest(case,field):
    case=scenario(case)
    before=capture(case)
    setattr(case.records["POS Profile","SYNTHETIC-POS"].payments[0],field,"CHANGED")
    assert capture(case).sha256!=before.sha256


@pytest.mark.parametrize("field",tax.TABLE_PROFILES[calc.TAX_TEMPLATE][1])
def test_pos_template_tax_row_changes_are_not_hidden_by_parent_timestamps(case,field):
    case=scenario(case)
    before=capture(case)
    setattr(case.records[calc.TAX_TEMPLATE,"POS-TAX"].taxes[0],field,"CHANGED")
    assert capture(case).sha256!=before.sha256


def test_pos_template_is_not_replaced_by_invoice_tax_template(case):
    case=scenario(case)
    # Invoice and profile references remain separate explicit dependencies.
    case.doc.taxes_and_charges="INVOICE-TAX"
    case.financial=capture_financial(case)
    case.settings=issuing.capture_issuing_settings_observation(case.financial,
        records={("Company",case.company.name):case.company})
    result=capture(case)
    assert any(record["name"]=="POS-TAX" for record in json.loads(result._payload)["records"])
    del case.records[calc.TAX_TEMPLATE,"POS-TAX"]
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("fault",["missing_singleton","singleton_name","singleton_meta","singleton_flag",
    "singleton_field","extra","currency_missing","currency_name","pos_company","pos_missing","pos_payments_meta",
    "pos_payments_parent","pos_payments_idx","template_missing","template_company","template_meta",
    "template_parent","template_idx","parent_hash","modified","extra_meta"])
def test_wrong_missing_or_extra_graph_records_and_storage_kinds_fail_closed(case,fault):
    case=scenario(case)
    system=case.records["System Settings","System Settings"]
    pos=case.records["POS Profile","SYNTHETIC-POS"]
    template=case.records[calc.TAX_TEMPLATE,"POS-TAX"]
    if fault=="missing_singleton": del case.records["System Settings","System Settings"]
    elif fault=="singleton_name": system.name="PRIVATE"
    elif fault=="singleton_meta": system.meta.name="Company"
    elif fault=="singleton_flag": system.meta.issingle=0
    elif fault=="singleton_field": system.meta.fields.remove("float_precision")
    elif fault=="extra": case.records["Company","EXTRA"]=case.company
    elif fault=="currency_missing": del case.records["Currency","SAR"]
    elif fault=="currency_name": case.records["Currency","SAR"].name="OTHER"
    elif fault=="pos_company": pos.company="OTHER"
    elif fault=="pos_missing": del case.records["POS Profile","SYNTHETIC-POS"]
    elif fault=="pos_payments_meta": del case.child_metas["POS Profile"]
    elif fault=="pos_payments_parent": pos.payments[0].parent="OTHER"
    elif fault=="pos_payments_idx": pos.payments[0].idx=True
    elif fault=="template_missing": del case.records[calc.TAX_TEMPLATE,"POS-TAX"]
    elif fault=="template_company": template.company="OTHER"
    elif fault=="template_meta": case.child_metas[calc.TAX_TEMPLATE].name="OTHER"
    elif fault=="template_parent": template.taxes[0].parent="OTHER"
    elif fault=="template_idx": template.taxes[0].idx=True
    elif fault=="parent_hash": object.__setattr__(case.settings,"sha256","PRIVATE")
    elif fault=="modified": pos.modified=None
    else: case.child_metas["OTHER"]=system.meta
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("change",["profile","parent","extra","missing","order","duplicate","singleton_revision",
    "singleton_kind","header","tax_header","tax_company","payment_idx","payment_kind","extra_field","noncanonical","trailing"])
def test_direct_payload_reconstruction_revalidates_every_record(case,change):
    case=scenario(case)
    result=capture(case)
    body=json.loads(result._payload)
    singleton=next(record for record in body["records"] if record["doctype"]=="System Settings")
    template=next(record for record in body["records"] if record["doctype"]==calc.TAX_TEMPLATE)
    pos=next(record for record in body["records"] if record["doctype"]=="POS Profile")
    if change=="profile": body["profile"]="PRIVATE"
    elif change=="parent": body["settings_sha256"]="f"*64
    elif change=="extra": body["secret"]="PRIVATE"
    elif change=="missing": body["records"].pop()
    elif change=="order": body["records"].reverse()
    elif change=="duplicate": body["records"][1]=body["records"][0]
    elif change=="singleton_revision": singleton["modified"]=["str","FABRICATED"]
    elif change=="singleton_kind": singleton["singleton"]=1
    elif change=="header": singleton["header"].pop()
    elif change=="tax_header": template["header"].pop()
    elif change=="tax_company": template["header"][0][1]=["str","OTHER"]
    elif change=="payment_idx": pos["payments"]["rows"][0][1]=True
    elif change=="payment_kind": pos["payments"]["doctype"]="OTHER"
    elif change=="extra_field": singleton["raw_auth"]="PRIVATE"
    payload=calc._canonical(body)
    if change=="noncanonical": payload=json.dumps(body).encode()
    if change=="trailing": payload+=b"PRIVATE"
    assert_static(lambda:replace(result,_payload=payload),"calculation_settings_observation")


@pytest.mark.parametrize("limit",["records","payments","taxes","payload"])
def test_capture_bounds_are_enforced(case,monkeypatch,limit):
    case=scenario(case)
    if limit=="records": monkeypatch.setattr(calc,"MAX_RECORDS",3)
    elif limit=="payments": monkeypatch.setattr(calc,"MAX_PAYMENT_ROWS",0)
    elif limit=="taxes": monkeypatch.setattr(calc,"MAX_TAX_ROWS",1)
    else:
        from zatca_erpgulf.zatca_erpgulf import financial_source_observation
        monkeypatch.setattr(financial_source_observation,"MAX_PAYLOAD_BYTES",100)
    assert_static(lambda:capture(case))


def test_input_order_and_shared_currency_refs_do_not_duplicate_records(case):
    case=scenario(case)
    before=capture(case)
    case.records=dict(reversed(tuple(case.records.items())))
    case.child_metas=dict(reversed(tuple(case.child_metas.items())))
    assert capture(case)==before
    assert sum(record["doctype"]=="Currency" for record in json.loads(before._payload)["records"])==1


def test_timezone_is_observed_without_rewriting_issue_time_amounts_or_precision(case):
    case=scenario(case)
    original_time,original_total=case.doc.posting_time,case.doc.grand_total
    with localcontext() as context:
        context.prec=6
        before=capture(case)
    with localcontext() as context:
        context.prec=28
        assert capture(case)==before
    case.records["System Settings","System Settings"].time_zone="America/New_York"
    assert capture(case).sha256!=before.sha256
    assert case.doc.posting_time==original_time and case.doc.grand_total==original_total
    assert not hasattr(before,"utc_instant") and not hasattr(before,"effective_precision")


def test_no_mutable_records_or_parent_reference_is_retained(case):
    case=scenario(case)
    result=capture(case)
    before=result.sha256
    case.records["System Settings","System Settings"].time_zone="CHANGED"
    object.__setattr__(case.settings,"sha256","PRIVATE")
    result.__post_init__()
    assert result.sha256==before



@pytest.mark.parametrize("change",["delete","reorder","zero","schema"])
def test_payment_membership_order_and_default_zero_do_not_disappear(case,change):
    case=scenario(case)
    pos=case.records["POS Profile","SYNTHETIC-POS"]
    pos.payments.append(Document(doctype="POS Payment Method",name="SECOND-MOP",idx=2,parent=pos.name,
        parenttype=pos.doctype,parentfield="payments",mode_of_payment="Card",default=0,allow_in_returns=1))
    before=capture(case)
    if change=="delete": pos.payments.pop()
    elif change=="reorder":
        pos.payments.reverse()
        for idx,row in enumerate(pos.payments,1): row.idx=idx
    elif change=="zero": pos.payments[0].default=0
    else: case.child_metas["POS Profile"].fields.remove("allow_in_returns")
    assert capture(case).sha256!=before.sha256


def test_all_four_explicit_currency_references_are_required_and_deduplicated(case):
    case=scenario(case,distinct=True)
    result=capture(case)
    names={record["name"] for record in json.loads(result._payload)["records"] if record["doctype"]=="Currency"}
    assert names=={"SAR","USD","EUR","GBP"}
    del case.records["Currency","GBP"]
    assert_static(lambda:capture(case))
