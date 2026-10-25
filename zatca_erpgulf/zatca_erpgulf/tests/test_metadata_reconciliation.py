"""Declared raw Custom Field/Setter matching with real non-temporal Frappe casts."""

import json
import pickle
from dataclasses import FrozenInstanceError,replace
from types import SimpleNamespace

import frappe
import pytest
from frappe.model.meta import Meta
from frappe.utils.data import cast

from zatca_erpgulf.zatca_erpgulf import metadata_reconciliation as match
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import (
    Definition,project,raw_meta,erp_major,case,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import Document


CUSTOM="custom_zatca_use_line_net_amounts"


def scenario(case):
    raw=raw_meta(case)
    raw.definitions.pop(CUSTOM)
    base=project(raw)
    custom=Document(doctype="Custom Field",name="SYNTHETIC-CUSTOM",modified=case.doc.modified,
        dt=raw.name,fieldname=CUSTOM)
    for prop in match.EDITABLE: setattr(custom,prop,None)
    custom.fieldtype="Check"
    properties={prop:getattr(custom,prop) for prop in match.EDITABLE}
    raw.definitions[CUSTOM]=Definition(CUSTOM,**properties,is_custom_field=1)
    setter=Document(doctype="Property Setter",name="SYNTHETIC-SETTER",modified=case.doc.modified,
        doctype_or_field="DocField",doc_type=raw.name,field_name="net_total",property="precision",
        property_type="Int",value="2")
    raw.definitions["net_total"].values["precision"]=2
    case.base,case.applied,case.raw=base,project(raw),raw
    case.custom,case.setter=custom,setter
    case.custom_fields,case.setters=[custom],[setter]
    return case


def reconcile(case):
    return match.reconcile_field_customizations(case.base,case.applied,
        custom_fields=case.custom_fields,property_setters=case.setters)


def assert_static(call,code="metadata_customization_reconciliation"):
    with pytest.raises(match.MetadataReconciliationError) as caught: call()
    assert str(caught.value)==caught.value.code==code and caught.value.__context__ is None


def test_exact_declarations_are_consistent_protected_and_do_not_write(case):
    case=scenario(case)
    result=reconcile(case)
    assert reconcile(case)==result and result.base==case.base and result.applied==case.applied
    assert result.base is not case.base and result.applied is not case.applied
    assert "NOT verified" in repr(result) and "SYNTHETIC" not in repr(result)
    assert not hasattr(result,"provider_origin_verified") and not hasattr(result,"dispatch_authorized")
    assert json.loads(result._payload)["framework_version"]==frappe.__version__
    with pytest.raises(FrozenInstanceError): result.sha256="f"*64
    with pytest.raises(TypeError,match="not_serializable"): pickle.dumps(result)
    for doc in (case.custom,case.setter):
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()


@pytest.mark.parametrize("property_type",sorted(match.CAST_TYPES))
@pytest.mark.parametrize("value",[None,"","0","2","true","eval:DO_NOT_EXECUTE"])
def test_cast_subset_matches_the_framework_and_preserves_raw_type(case,property_type,value):
    case=scenario(case)
    case.setter.property_type,case.setter.value=property_type,value
    expected=cast(property_type,value)
    case.raw.definitions["net_total"].values["precision"]=expected
    case.applied=project(case.raw)
    result=reconcile(case)
    raw=dict(json.loads(result._payload)["property_setters"][0]["header"])
    assert raw["value"]==match._scalar(value)
    assert result.applied.get_field("net_total").get("precision")==expected


@pytest.mark.parametrize("property_type",["Date","Datetime","Time","Password","PRIVATE"])
def test_temporal_unknown_and_password_cast_paths_are_not_called(case,monkeypatch,property_type):
    case=scenario(case)
    case.setter.property_type=property_type
    def forbidden(*args,**kwargs): raise AssertionError("Unsupported cast must not execute")
    monkeypatch.setattr(match,"_framework_cast",forbidden)
    assert_static(lambda:reconcile(case))


def test_int_and_data_setters_do_not_compare_as_interchangeable_values(case):
    case=scenario(case)
    case.setter.property_type="Data"
    assert_static(lambda:reconcile(case))
    case.raw.definitions["net_total"].values["precision"]="2"
    case.applied=project(case.raw)
    assert reconcile(case)


def test_changed_raw_row_revision_is_retained_even_when_effect_is_equal(case):
    case=scenario(case)
    before=reconcile(case)
    case.setter.modified="2026-10-25 13:00:00"
    assert reconcile(case).sha256!=before.sha256


@pytest.mark.parametrize("fault",["missing_custom","missing_setter","wrong_company_type","wrong_field","custom_shadow",
    "duplicate_custom","duplicate_property","duplicate_name","setter_doc_type","setter_field","setter_property",
    "setter_scope","custom_password","modified","stale_applied","dirty_baseline","custom_marker","parent_hash"])
def test_wrong_missing_extra_ambiguous_or_stale_declarations_are_refused(case,fault):
    case=scenario(case)
    if fault=="missing_custom": case.custom_fields=[]
    elif fault=="missing_setter": case.setters=[]
    elif fault=="wrong_company_type": case.custom.dt="Company"
    elif fault=="wrong_field": case.custom.fieldname="private_key"
    elif fault=="custom_shadow": case.custom.fieldname="net_total"
    elif fault=="duplicate_custom": case.custom_fields.append(case.custom)
    elif fault=="duplicate_property":
        duplicate=Document(**{key:value for key,value in case.setter.__dict__.items() if key not in ("save","db_set","reads")})
        duplicate.name="SECOND"
        case.setters.append(duplicate)
    elif fault=="duplicate_name": case.setters.append(case.setter)
    elif fault=="setter_doc_type": case.setter.doc_type="Company"
    elif fault=="setter_field": case.setter.field_name="private_key"
    elif fault=="setter_property": case.setter.property="is_custom_field"
    elif fault=="setter_scope": case.setter.doctype_or_field="DocType"
    elif fault=="custom_password": case.custom.fieldtype="Password"
    elif fault=="modified": case.setter.modified=None
    elif fault=="stale_applied":
        case.raw.definitions["net_total"].values["precision"]=3
        case.applied=project(case.raw)
    elif fault=="dirty_baseline": case.base=case.applied
    elif fault=="custom_marker":
        case.raw.definitions[CUSTOM].values["is_custom_field"]=None
        case.applied=project(case.raw)
    else: object.__setattr__(case.applied,"sha256","PRIVATE")
    assert_static(lambda:reconcile(case))


def test_base_only_metadata_needs_no_fabricated_customization(case):
    base=project(raw_meta(case))
    result=match.reconcile_field_customizations(base,base,custom_fields=[],property_setters=[])
    assert result.base==result.applied


def test_real_meta_setter_method_produces_the_expected_declared_effect(case,monkeypatch):
    case=scenario(case)
    before=raw_meta(case)
    before.definitions.pop(CUSTOM)
    case.base=project(before)
    case.custom_fields=[]
    fields=[SimpleNamespace(fieldname=name,set=lambda key,value,definition=definition:
        definition.values.__setitem__(key,value)) for name,definition in before.definitions.items()]
    record=frappe._dict({key:case.setter.get(key) for key in match.SETTER_FIELDS})
    database=SimpleNamespace(table_exists=lambda name:name=="Property Setter",
        get_values=lambda *args,**kwargs:[record])
    monkeypatch.setattr(frappe,"db",database)
    Meta.apply_property_setters(SimpleNamespace(name=before.name,fields=fields))
    case.applied=project(before)
    assert reconcile(case)


@pytest.mark.parametrize("change",["profile","framework","base_hash","applied_hash","extra","missing","order",
    "duplicate","row_secret","header","row_modified","scope","cast","value","noncanonical","trailing"])
def test_direct_match_construction_rechecks_raw_rows_and_metadata(case,change):
    case=scenario(case)
    result=reconcile(case)
    body=json.loads(result._payload)
    setter=body["property_setters"][0]
    if change=="profile": body["profile"]="PRIVATE"
    elif change=="framework": body["framework_version"]="OTHER"
    elif change=="base_hash": body["base_sha256"]="f"*64
    elif change=="applied_hash": body["applied_sha256"]="f"*64
    elif change=="extra": body["secret"]="PRIVATE"
    elif change=="missing": body["property_setters"]=[]
    elif change=="order": setter["header"].reverse()
    elif change=="duplicate": body["custom_fields"].append(body["custom_fields"][0])
    elif change=="row_secret": setter["raw_auth"]="PRIVATE"
    elif change=="header": setter["header"].pop()
    elif change=="row_modified": setter["modified"]=["null"]
    elif change=="scope": setter["header"][0][1]=["str","DocType"]
    elif change=="cast": setter["header"][-2][1]=["str","Datetime"]
    elif change=="value": setter["header"][-1][1]=["str","3"]
    payload=match._canonical(body)
    if change=="noncanonical": payload=json.dumps(body).encode()
    if change=="trailing": payload+=b"PRIVATE"
    assert_static(lambda:replace(result,_payload=payload),"metadata_customization_match")


@pytest.mark.parametrize("limit",["custom_fields","setters","payload"])
def test_capture_bounds_are_closed(case,monkeypatch,limit):
    case=scenario(case)
    if limit=="custom_fields": monkeypatch.setattr(match,"MAX_CUSTOM_FIELDS",0)
    elif limit=="setters": monkeypatch.setattr(match,"MAX_SETTERS",0)
    else:
        from zatca_erpgulf.zatca_erpgulf import financial_source_observation
        monkeypatch.setattr(financial_source_observation,"MAX_PAYLOAD_BYTES",100)
    assert_static(lambda:reconcile(case))


def test_success_does_not_retain_mutable_raw_rows_or_metadata(case):
    case=scenario(case)
    result=reconcile(case)
    before=result.sha256
    case.setter.value="CHANGED"
    case.custom.default="eval:DO_NOT_EXECUTE"
    object.__setattr__(case.applied,"sha256","PRIVATE")
    result.__post_init__()
    assert result.sha256==before
