"""Synthetic party/address graphs; no authority, ERP site or document writes."""

import json
import pickle
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import party_address_observation as party
from zatca_erpgulf.zatca_erpgulf import issuing_settings_observation as issuing
from zatca_erpgulf.zatca_erpgulf import customer_address
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import (
    Document, Metadata, erp_major, case, capture as capture_financial,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_settings_observation import scenario as settings_scenario, SECRETS


def scenario(case, *, addresses=True, cost_center=True, owner="company"):
    settings_scenario(case,owner)
    case.settings_records = case.records
    company = case.company
    company.meta.fields.update(party.COMPANY_FIELDS)
    for field in party.COMPANY_FIELDS:
        if not hasattr(company,field): setattr(company,field,None)
    company.company_name, company.custom_costcenter = "Synthetic Company",int(cost_center)
    customer = Document(doctype="Customer",name=case.doc.customer,
        modified=case.doc.modified,meta=Metadata("Customer",party.CUSTOMER_FIELDS))
    for field in party.CUSTOMER_FIELDS: setattr(customer,field,None)
    customer.customer_name,customer.tax_id = "Synthetic Customer","300000000000003"
    customer.customer_primary_address = "PRIMARY-ADDR" if addresses else None
    center = None
    case.doc.company_address = "COMPANY-ADDR" if addresses else None
    case.doc.customer_address = "CUSTOMER-ADDR" if addresses else None
    case.doc.cost_center = "SYNTHETIC-CC" if cost_center else None
    records = {("Company",company.name):company,("Customer",customer.name):customer}
    if cost_center:
        center = Document(doctype="Cost Center",name=case.doc.cost_center,company=company.name,
            modified=case.doc.modified,meta=Metadata("Cost Center",party.COST_CENTER_FIELDS),
            custom_zatca_branch_address="BRANCH-ADDR" if addresses else None,
            custom_zatca__registration_type="CRN",custom_zatca__registration_number="SYNTHETIC-CRN")
        records[center.doctype,center.name] = center
    roles = {}
    if addresses:
        roles = {"COMPANY-ADDR":("Company",company.name),
            "CUSTOMER-ADDR":("Customer",customer.name),"PRIMARY-ADDR":("Customer",customer.name)}
        if center: roles["BRANCH-ADDR"] = ("Company",company.name)
    for name,(dt,linked_name) in roles.items():
        address = Document(doctype="Address",name=name,modified=case.doc.modified,
            meta=Metadata("Address",(*party.ADDRESS_FIELDS,"links"),{"links":"Dynamic Link"}))
        for field in party.ADDRESS_FIELDS: setattr(address,field,None)
        address.address_line1,address.city,address.pincode,address.country = "Synthetic Street","Riyadh","12345","Saudi Arabia"
        address.disabled,address.is_primary_address = 0,int(name=="PRIMARY-ADDR")
        address.is_your_company_address = int(dt=="Company")
        address.links = [Document(doctype="Dynamic Link",name=name+"-LINK",idx=1,
            parent=name,parenttype="Address",parentfield="links",link_doctype=dt,link_name=linked_name,
            link_title="Synthetic Link")]
        records["Address",name] = address
    case.financial = capture_financial(case)
    case.settings = issuing.capture_issuing_settings_observation(case.financial,records=case.settings_records)
    case.records,case.customer,case.center = records,customer,center
    case.discovery = {"company":["COMPANY-ADDR"] if addresses else [],
        "customer":["CUSTOMER-ADDR","PRIMARY-ADDR"] if addresses else []}
    case.link_meta = Metadata("Dynamic Link",party.LINK_FIELDS) if addresses else None
    return case


def capture(case):
    return party.capture_party_address_observation(case.settings,records=case.records,
        discovery=case.discovery,link_meta=case.link_meta)


def assert_static(call,code="party_address_capture"):
    with pytest.raises(party.PartyAddressError) as caught: call()
    assert str(caught.value) == caught.value.code == code and caught.value.__context__ is None


@pytest.mark.parametrize("addresses",[False,True])
@pytest.mark.parametrize("cost_center",[False,True])
@pytest.mark.parametrize("owner",["company","device","linked","foreign_own"])
def test_exact_graph_is_protected_deterministic_and_side_effect_free(case,addresses,cost_center,owner):
    case = scenario(case,addresses=addresses,cost_center=cost_center,owner=owner)
    result = capture(case)
    assert capture(case) == result
    assert result.settings == case.settings and result.settings is not case.settings
    assert "PARTIAL" in repr(result) and "SYNTHETIC" not in repr(result)
    assert not hasattr(result,"selected_address") and not hasattr(result,"dispatch_authorized")
    with pytest.raises(FrozenInstanceError): result.sha256 = "f"*64
    with pytest.raises(TypeError,match="not_serializable"): pickle.dumps(result)
    for record in case.records.values():
        assert not set(SECRETS)&set(record.reads)
        record.save.assert_not_called()
        record.db_set.assert_not_called()


@pytest.mark.parametrize("doctype,field",[(dt,field) for dt,fields in party.FIELDS.items() for field in fields])
def test_every_selected_party_address_field_is_a_dependency(case,doctype,field):
    case = scenario(case)
    before,modified = capture(case),case.doc.modified
    record = next(record for (dt,_name),record in case.records.items() if dt==doctype)
    if (doctype,field)==("Customer","customer_primary_address"):
        record.customer_primary_address = None
        del case.records["Address","PRIMARY-ADDR"]
        case.discovery["customer"].remove("PRIMARY-ADDR")
    elif (doctype,field)==("Cost Center","custom_zatca_branch_address"):
        record.custom_zatca_branch_address = None
        del case.records["Address","BRANCH-ADDR"]
    elif (doctype,field)==("Cost Center","company"):
        record.company = "OTHER"
        assert_static(lambda:capture(case))
        return
    else:
        setattr(record,field,"CHANGED")
    if doctype=="Company":
        case.settings = issuing.capture_issuing_settings_observation(case.financial,records=case.settings_records)
    after = capture(case)
    assert after.sha256!=before.sha256 and case.doc.modified==modified


@pytest.mark.parametrize("field",party.LINK_FIELDS)
def test_dynamic_link_field_drift_is_visible_without_parent_revision(case,field):
    case = scenario(case)
    # Branch is a direct reference, not discovery; its changed target remains an
    # observation rather than being misrepresented as ownership authorization.
    before = capture(case)
    address = case.records["Address","BRANCH-ADDR"]
    setattr(address.links[0],field,"CHANGED")
    assert capture(case).sha256!=before.sha256 and address.modified==case.doc.modified


@pytest.mark.parametrize("change",["insert","delete","reorder","identity","schema"])
def test_link_membership_order_identity_and_schema_are_observed(case,change):
    case = scenario(case)
    address = case.records["Address","BRANCH-ADDR"]
    row = Document(doctype="Dynamic Link",name="EXTRA-LINK",idx=2,parent=address.name,
        parenttype="Address",parentfield="links",link_doctype="Customer",link_name=case.customer.name,
        link_title="Extra")
    address.links.append(row)
    before = capture(case)
    if change=="insert":
        address.links.append(Document(doctype="Dynamic Link",name="THIRD-LINK",idx=3,parent=address.name,
            parenttype="Address",parentfield="links",link_doctype="Company",link_name=case.company.name,link_title="Third"))
    elif change=="delete": address.links.pop()
    elif change=="reorder":
        address.links.reverse()
        for idx,row in enumerate(address.links,1): row.idx=idx
    elif change=="identity": address.links[0].name="NEW-LINK"
    else: case.link_meta.fields.remove("link_title")
    assert capture(case).sha256!=before.sha256


def test_discovery_order_is_retained_not_replaced_by_an_implicit_sort(case):
    case = scenario(case)
    before = capture(case)
    case.discovery["customer"].reverse()
    assert capture(case).sha256!=before.sha256
    ordered = capture(case)
    case.records = dict(reversed(tuple(case.records.items())))
    assert capture(case)==ordered


def test_shared_address_is_captured_once_for_multiple_roles_and_direct_refs(case):
    case = scenario(case)
    address = case.records["Address","COMPANY-ADDR"]
    address.links.append(Document(doctype="Dynamic Link",name="SHARED-LINK",idx=2,parent=address.name,
        parenttype="Address",parentfield="links",link_doctype="Customer",link_name=case.customer.name,link_title="Shared"))
    case.discovery["customer"].append(address.name)
    result = capture(case)
    assert len([record for record in json.loads(result._payload)["records"]
        if record["name"]==address.name])==1


def test_submitted_invoice_address_can_remain_disabled_and_currently_unlinked(case,monkeypatch):
    case = scenario(case)
    address = case.records["Address","CUSTOMER-ADDR"]
    case.discovery["customer"].remove(address.name)
    address.disabled,address.links = 1,[]
    result = capture(case)
    stored = next(record for record in json.loads(result._payload)["records"] if record["name"]==address.name)
    assert dict(stored["header"])["disabled"]==["int","1"] and stored["links"]["rows"]==[]
    # Characterize the actual existing resolver, without loading a Frappe site.
    saved = SimpleNamespace(name=address.name,disabled=1)
    loader = Mock(return_value=saved)
    forbidden = Mock(side_effect=AssertionError("No fallback/discovery for saved submitted address"))
    monkeypatch.setattr(customer_address.frappe,"get_doc",loader)
    monkeypatch.setattr(customer_address.frappe,"get_all",forbidden)
    monkeypatch.setattr(customer_address.frappe,"db",SimpleNamespace(exists=forbidden))
    resolved,source = customer_address.resolve_customer_address(
        SimpleNamespace(customer_address=address.name,docstatus=1),
        SimpleNamespace(name=case.customer.name,customer_primary_address="OTHER"))
    assert resolved is saved and source=="Sales Invoice.customer_address"
    forbidden.assert_not_called()


@pytest.mark.parametrize("field",["custom_b2c","b2c","custom_customer_name_in_arabic","address_in_arabic"])
def test_alternative_fields_distinguish_absent_null_zero_false_blank(case,field):
    case = scenario(case)
    record = case.records["Address","BRANCH-ADDR"] if field=="address_in_arabic" else case.customer
    hashes=[]
    for value in (None,0,False,"","0","VALUE"):
        setattr(record,field,value)
        hashes.append(capture(case).sha256)
    record.meta.fields.remove(field)
    hashes.append(capture(case).sha256)
    assert len(set(hashes))==len(hashes)


@pytest.mark.parametrize("field",["tax_id","company_name","country","custom_costcenter"])
def test_party_and_settings_cannot_mix_different_company_snapshots(case,field):
    case = scenario(case)
    setattr(case.company,field,"CHANGED")
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("fault",["missing_company","missing_customer","missing_address","extra","cost_company",
    "wrong_name","wrong_meta","modified","child_parent","child_parenttype","child_parentfield","child_idx",
    "duplicate_link","link_meta","missing_link_schema","link_table_schema","discovery_owner","duplicate_discovery",
    "unknown_role","bad_reference","parent_hash"])
def test_unbound_records_schema_refs_and_candidate_declarations_fail_closed(case,fault):
    case = scenario(case)
    address=case.records["Address","CUSTOMER-ADDR"]
    if fault=="missing_company": del case.records["Company",case.company.name]
    elif fault=="missing_customer": del case.records["Customer",case.customer.name]
    elif fault=="missing_address": del case.records["Address",address.name]
    elif fault=="extra": case.records["Customer","UNREFERENCED"]=case.customer
    elif fault=="cost_company": case.center.company="OTHER"
    elif fault=="wrong_name": address.name="OTHER"
    elif fault=="wrong_meta": address.meta.name="Customer"
    elif fault=="modified": address.modified=None
    elif fault.startswith("child_"):
        setattr(address.links[0],fault[6:],"PRIVATE" if fault!="child_idx" else True)
    elif fault=="duplicate_link":
        address.links.append(Document(doctype="Dynamic Link",name=address.links[0].name,idx=2,
            parent=address.name,parenttype="Address",parentfield="links",link_doctype="Customer",link_name=case.customer.name))
    elif fault=="link_meta": case.link_meta=None
    elif fault=="missing_link_schema": case.link_meta.fields.remove("link_name")
    elif fault=="link_table_schema": address.meta.fields.remove("links")
    elif fault=="discovery_owner": address.links[0].link_name="OTHER-CUSTOMER"
    elif fault=="duplicate_discovery": case.discovery["customer"].append(address.name)
    elif fault=="unknown_role": case.discovery["other"]=[]
    elif fault=="bad_reference":
        case.customer.customer_primary_address=False
    else: object.__setattr__(case.settings,"sha256","PRIVATE")
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("change",["profile","parent_hash","extra","missing","order","duplicate","record_secret",
    "header","modified","link_type","link_idx","link_presence","candidate_duplicate","candidate_extra","noncanonical","trailing"])
def test_direct_payload_cannot_bypass_graph_or_typed_structure(case,change):
    case=scenario(case)
    result=capture(case)
    body=json.loads(result._payload)
    address=next(record for record in body["records"] if record["doctype"]=="Address")
    if change=="profile": body["profile"]="PRIVATE"
    elif change=="parent_hash": body["settings_sha256"]="f"*64
    elif change=="extra": body["secret"]="PRIVATE"
    elif change=="missing": body["records"].pop()
    elif change=="order": body["records"].reverse()
    elif change=="duplicate": body["records"][1]=body["records"][0]
    elif change=="record_secret": address["auth"]="PRIVATE"
    elif change=="header": address["header"].pop()
    elif change=="modified": address["modified"]=["null"]
    elif change=="link_type": address["links"]["doctype"]="PRIVATE"
    elif change=="link_idx": address["links"]["rows"][0][1]=True
    elif change=="link_presence": address["links"]["presence"][0]=1
    elif change=="candidate_duplicate": body["discovery"]["customer"].append(body["discovery"]["customer"][0])
    elif change=="candidate_extra": body["discovery"]["other"]=[]
    payload=party._canonical(body)
    if change=="noncanonical": payload=json.dumps(body).encode()
    if change=="trailing": payload+=b"PRIVATE"
    assert_static(lambda:replace(result,_payload=payload),"party_address_observation")


@pytest.mark.parametrize("limit",["addresses","links","payload"])
def test_graph_bounds_are_enforced(case,monkeypatch,limit):
    case=scenario(case)
    if limit=="addresses": monkeypatch.setattr(party,"MAX_ADDRESSES",1)
    elif limit=="links": monkeypatch.setattr(party,"MAX_LINK_ROWS",1)
    else:
        from zatca_erpgulf.zatca_erpgulf import financial_source_observation
        monkeypatch.setattr(financial_source_observation,"MAX_PAYLOAD_BYTES",100)
    assert_static(lambda:capture(case))


def test_no_mutable_parent_or_record_reference_is_retained(case):
    case=scenario(case)
    result=capture(case)
    before=result.sha256
    case.customer.customer_name="CHANGED"
    case.discovery["customer"].reverse()
    object.__setattr__(case.settings,"sha256","PRIVATE")
    result.__post_init__()
    assert result.sha256==before
