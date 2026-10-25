"""Synthetic applied-Meta/default-field compatibility; no site or schema writes."""

import json
import pickle
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from frappe.model.meta import get_default_df

from zatca_erpgulf.zatca_erpgulf import source_metadata as schema
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf import party_address_observation as party
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import (
    erp_major,case,capture as capture_financial,
)


class Definition:
    def __init__(self,name,**values):
        self.values={"fieldname":name,"fieldtype":"Data",**values}
        self.reads=[]

    def get(self,name):
        self.reads.append(name)
        if self.values.get("fieldtype")=="Password" and name=="default":
            raise AssertionError("Password defaults must not be read")
        return self.values.get(name)


class AppliedMeta:
    def __init__(self,doctype,present,tables=None):
        self.name=doctype
        self.issingle=int(doctype in schema.SINGLETONS)
        self.istable=int(doctype in schema.CHILD_TYPES)
        self.definitions={name:Definition(name) for name in present if name not in schema.BASE_TYPES}
        for name,child in (tables or {}).items():
            self.definitions[name]=Definition(name,fieldtype="Table",options=child)

    def has_field(self,name):
        return name in self.definitions

    def get_field(self,name):
        return self.definitions.get(name)


def bases(doctype):
    # Real installed Frappe helper, no Meta construction, DB or site init.
    return {name:get_default_df(name) for name in schema.BASE_TYPES if name in schema.SOURCE_FIELDS[doctype]}


def raw_meta(case):
    tables={name:financial._child_type(case.doc.doctype,name) for name in financial.TABLE_FIELDS}
    return AppliedMeta(case.doc.doctype,case.doc.meta.fields,tables)


def project(meta):
    return schema.project_source_metadata(meta,base_fields=bases(meta.name))


def assert_static(call,code="source_metadata_capture"):
    with pytest.raises(schema.SourceMetadataError) as caught: call()
    assert str(caught.value)==caught.value.code==code and caught.value.__context__ is None


def test_real_default_field_definitions_are_explicit_not_hidden_docfields():
    for name,kind in schema.BASE_TYPES.items():
        definition=get_default_df(name)
        assert definition.fieldname==name and definition.fieldtype==kind
    assert get_default_df("not_a_default_field") is None


def test_raw_meta_without_docstatus_fails_then_adapter_preserves_old_financial_bytes(case):
    original=capture_financial(case)
    raw=raw_meta(case)
    assert not raw.has_field("docstatus") and raw.get_field("docstatus") is None
    source=SimpleNamespace(doctype=case.doc.doctype,name=case.doc.name,meta=raw,get=case.doc.get)
    child_metas={name:AppliedMeta(meta.name,meta.fields) for name,meta in case.metas.items()}
    with pytest.raises(financial.FinancialSourceError):
        financial.capture_invoice_financial_observation(source,erp_major=case.erp_major,child_metas=child_metas)
    projected=project(raw)
    view=schema.SourceDocumentView(source,projected)
    captured=financial.capture_invoice_financial_observation(view,erp_major=case.erp_major,
        child_metas={name:project(meta) for name,meta in child_metas.items()})
    assert captured._payload==original._payload and captured.sha256==original.sha256
    assert source.meta is raw and case.doc.docstatus==1
    assert not hasattr(view,"save") and not hasattr(view,"db_set")


@pytest.mark.parametrize("doctype",schema.SOURCE_FIELDS)
def test_all_profile_metadata_types_have_deterministic_protected_storage(doctype):
    raw=AppliedMeta(doctype,schema.SOURCE_FIELDS[doctype])
    result=project(raw)
    assert project(raw)==result
    assert result.name==doctype and result.issingle==(doctype in schema.SINGLETONS)
    assert result.istable==(doctype in schema.CHILD_TYPES)
    assert all(result.has_field(name) for name in schema.SOURCE_FIELDS[doctype])
    assert not result.has_field("custom_private_key")
    with pytest.raises(FrozenInstanceError): result.sha256="f"*64
    with pytest.raises(TypeError,match="not_serializable"): pickle.dumps(result)
    definition=result.get_field(schema.SOURCE_FIELDS[doctype][0])
    with pytest.raises(TypeError,match="not_serializable"): pickle.dumps(definition)
    assert "PRIVATE" not in repr(result) and "PRIVATE" not in repr(definition)


@pytest.mark.parametrize("prop",schema.PROPERTIES)
@pytest.mark.parametrize("value",[None,"",0,"0",False,1,"VALUE"])
def test_every_effective_property_is_typed_and_observed(case,prop,value):
    raw=raw_meta(case)
    before=project(raw)
    raw.definitions["net_total"].values[prop]=value
    if prop=="fieldtype" and (type(value) is not str or not value):
        assert_static(lambda:project(raw))
    else:
        after=project(raw)
        if before.get_field("net_total").get(prop)!=value or type(before.get_field("net_total").get(prop)) is not type(value):
            assert after.sha256!=before.sha256
        assert after.get_field("net_total").get(prop)==value


def test_precision_changes_do_not_recalculate_values_or_modify_raw_meta(case):
    raw=raw_meta(case)
    raw.definitions["net_total"].values["fieldtype"]="Currency"
    before=project(raw)
    raw.definitions["net_total"].values["precision"]="0"
    after=project(raw)
    assert after.sha256!=before.sha256
    assert before.get_field("net_total").get("precision") is None
    assert after.get_field("net_total").get("precision")=="0"
    original=capture_financial(case)
    child={name:project(AppliedMeta(meta.name,meta.fields)) for name,meta in case.metas.items()}
    one=financial.capture_invoice_financial_observation(schema.SourceDocumentView(case.doc,before),erp_major=case.erp_major,child_metas=child)
    two=financial.capture_invoice_financial_observation(schema.SourceDocumentView(case.doc,after),erp_major=case.erp_major,child_metas=child)
    assert one==two==original  # Complete source binding must ALSO include metadata.


def test_address_creation_uses_explicit_base_field_not_an_assumed_meta_column():
    raw=AppliedMeta("Address",party.ADDRESS_FIELDS)
    assert not raw.has_field("creation")
    result=project(raw)
    assert result.get_field("creation").fieldtype=="Datetime"
    assert not raw.has_field("creation")


@pytest.mark.parametrize("fault",["missing_base","extra_base","shadow_base","base_type","wrong_type",
    "wrong_name","wrong_field","missing_definition","password","single_flag","child_flag","flag_string"])
def test_ambiguous_or_wrong_schema_declarations_fail_closed(case,fault):
    raw=raw_meta(case)
    supplied=bases(raw.name)
    if fault=="missing_base": supplied={}
    elif fault=="extra_base": supplied["modified"]=get_default_df("modified")
    elif fault=="shadow_base": raw.definitions["docstatus"]=Definition("docstatus",fieldtype="Int")
    elif fault=="base_type": supplied["docstatus"]=Definition("docstatus",fieldtype="Data")
    elif fault=="wrong_type": raw.name="PRIVATE"
    elif fault=="wrong_name": raw.name=None
    elif fault=="wrong_field": raw.definitions["net_total"].values["fieldname"]="OTHER"
    elif fault=="missing_definition": raw.get_field=lambda name:None
    elif fault=="password": raw.definitions["net_total"].values["fieldtype"]="Password"
    elif fault=="single_flag": raw.issingle=1
    elif fault=="child_flag": raw.istable=1
    else: raw.issingle="0"
    assert_static(lambda:schema.project_source_metadata(raw,base_fields=supplied))


@pytest.mark.parametrize("change",["profile","doctype","extra","missing","order","field_name","fieldtype",
    "property","property_order","base_absent","base_type","kind","noncanonical","trailing"])
def test_direct_metadata_construction_revalidates_the_whole_profile(case,change):
    result=project(raw_meta(case))
    body=json.loads(result._payload)
    entry=next(row for row in body["fields"] if row[0]=="net_total")
    base=next(row for row in body["fields"] if row[0]=="docstatus")
    if change=="profile": body["profile"]="PRIVATE"
    elif change=="doctype": body["doctype"]="PRIVATE"
    elif change=="extra": body["secret"]="PRIVATE"
    elif change=="missing": body["fields"].pop()
    elif change=="order": body["fields"].reverse()
    elif change=="field_name": entry[0]="OTHER"
    elif change=="fieldtype": entry[1][0][1]=["str","Password"]
    elif change=="property": entry[1].append(["private_key",["str","PRIVATE"]])
    elif change=="property_order": entry[1].reverse()
    elif change=="base_absent": base[1]=["absent"]
    elif change=="base_type": base[1][0][1]=["str","Currency"]
    elif change=="kind": body["istable"]=True
    payload=financial._canonical(body)
    if change=="noncanonical": payload=json.dumps(body).encode()
    if change=="trailing": payload+=b"PRIVATE"
    assert_static(lambda:replace(result,_payload=payload),"source_metadata_projection")


def test_optional_absence_and_present_null_properties_are_different(case):
    raw=raw_meta(case)
    before=project(raw)
    del raw.definitions["base_discount_amount"]
    after=project(raw)
    assert after.sha256!=before.sha256
    assert not after.has_field("base_discount_amount")
    assert before.get_field("base_discount_amount").get("precision") is None


def test_metadata_and_document_views_are_not_credential_or_mutation_capabilities(case):
    raw=raw_meta(case)
    projected=project(raw)
    view=schema.SourceDocumentView(case.doc,projected)
    for name in ("custom_private_key","custom_certificate","custom_basic_auth_from_csid","password"):
        assert_static(lambda:view.get(name),"source_metadata_field_access")
    with pytest.raises(TypeError,match="not_serializable"): pickle.dumps(view)
    assert "SYNTHETIC" not in repr(view)
    assert view.get("grand_total")==case.doc.grand_total
    case.doc.grand_total=17
    assert view.get("grand_total")==17  # Read interface, not committed/frozen values.
    case.doc.name="OTHER"
    assert_static(lambda:view.get("grand_total"),"source_metadata_view_drift")


@pytest.mark.parametrize("fault",["doctype","name","metadata"])
def test_view_requires_bound_valid_source_and_independent_metadata(case,fault):
    projected=project(raw_meta(case))
    if fault=="doctype": case.doc.doctype="Company"
    elif fault=="name": case.doc.name=""
    else: object.__setattr__(projected,"_payload",b"PRIVATE")
    assert_static(lambda:schema.SourceDocumentView(case.doc,projected),"source_metadata_view")


def test_payload_bounds_are_checked_while_encoding(case,monkeypatch):
    raw=raw_meta(case)
    monkeypatch.setattr(financial,"MAX_PAYLOAD_BYTES",100)
    assert_static(lambda:project(raw))



@pytest.mark.parametrize("field",["sha256","issingle","istable"])
def test_view_does_not_trust_corrupted_derived_metadata_fields(case,field):
    projected=project(raw_meta(case))
    object.__setattr__(projected,field,"PRIVATE" if field=="sha256" else True)
    assert_static(lambda:schema.SourceDocumentView(case.doc,projected),"source_metadata_view")


def test_applied_metadata_changes_do_not_mutate_retained_definitions(case):
    raw=raw_meta(case)
    raw.definitions["net_total"].values.update(fieldtype="Currency",precision="2",is_custom_field=1)
    projected=project(raw)
    before=projected.sha256
    raw.definitions["net_total"].values.update(precision="3",default="eval:DO_NOT_EXECUTE")
    assert projected.sha256==before and projected.get_field("net_total").get("precision")=="2"
    assert project(raw).sha256!=before
    assert project(raw).get_field("net_total").get("default")=="eval:DO_NOT_EXECUTE"
