"""Synthetic Company/device settings observations; no site, secrets or requests."""

import json
import hashlib
import pickle
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from zatca_erpgulf.zatca_erpgulf import issuing_settings_observation as settings
from zatca_erpgulf.zatca_erpgulf import credential_settings
from zatca_erpgulf.ksa_compliance import field_compat, field_alias_registry
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import (
    Document, Metadata, erp_major, case, capture as capture_financial,
)

SECRETS = ("custom_private_key", "custom_certificate", "custom_certficate", "custom_basic_auth_from_csid",
    "custom_basic_auth_from_production", "custom_final_auth_csid", "custom_otp", "custom_csr",
    "custom_pih", "custom_uuid", "custom_zatca_icv")


def scenario(case, owner="company", flag=None):
    def company(name):
        record = Document(doctype="Company", name=name, modified=case.doc.modified,
            meta=Metadata("Company", settings.COMPANY_FIELDS))
        for name in settings.COMPANY_FIELDS: setattr(record,name,None)
        record.abbr, record.tax_id = "SYN", "300000000000003"
        record.custom_phase_1_or_2, record.phase_1_or_2 = "Phase-2", "Phase-1"
        record.custom_select = "Production"
        for environment, field in settings.ENVIRONMENT_FIELDS.items():
            setattr(record, field, "https://gateway.invalid/"+environment)
        for name in SECRETS: setattr(record,name,"PRIVATE DO NOT READ")
        return record
    root = company(case.doc.company)
    case.records = {("Company",root.name):root}
    case.company = root
    case.device, case.linked = None, None
    case.doc.custom_zatca_pos_name = None
    if owner != "company":
        case.doc.custom_zatca_pos_name = "SYNTHETIC-DEVICE"
        linked = root if owner == "device" else company("SYNTHETIC-LINKED")
        device = Document(doctype="ZATCA Multiple Setting", name="SYNTHETIC-DEVICE",
            modified=case.doc.modified, meta=Metadata("ZATCA Multiple Setting",settings.DEVICE_FIELDS),
            custom_linked_doctype=linked.name, custom__use_company_certificate__keys=
                (1 if owner == "linked" else 0) if flag is None else flag)
        for name in SECRETS: setattr(device,name,"PRIVATE DO NOT READ")
        case.records[device.doctype,device.name] = device
        case.records[linked.doctype,linked.name] = linked
        case.device, case.linked = device, linked
    case.financial = capture_financial(case)
    return case


def capture(case):
    return settings.capture_issuing_settings_observation(case.financial, records=case.records)


def assert_static(call, code="issuing_settings_capture"):
    with pytest.raises(settings.IssuingSettingsError) as caught: call()
    assert str(caught.value) == caught.value.code == code
    assert caught.value.__context__ is None


@pytest.mark.parametrize("owner", ["company","device","linked","foreign_own"])
def test_explicit_owner_matches_existing_record_policy_without_secret_reads(case, owner):
    case = scenario(case,owner)
    result = capture(case)
    lookup = {**case.records,(case.doc.doctype,case.doc.name):case.doc}
    selected, kind = credential_settings._resolve_owner_record_from_saved_company(
        case.company,case.doc,load_doc=lambda dt,name:lookup[dt,name])
    assert json.loads(result._payload)["declared_owner"] == [selected.doctype,selected.name]
    assert kind == {"company":"company","device":"multiple_setting","linked":"linked_company",
        "foreign_own":"multiple_setting"}[owner]
    assert capture(case) == result
    assert result.financial is not case.financial and result.financial == case.financial
    assert "SYNTHETIC" not in repr(result) and "PRIVATE" not in repr(result)
    with pytest.raises(FrozenInstanceError): result.sha256 = "f"*64
    with pytest.raises(TypeError,match="not_serializable"): pickle.dumps(result)
    for record in case.records.values():
        assert not set(SECRETS) & set(record.reads)
        record.save.assert_not_called()
        record.db_set.assert_not_called()


@pytest.mark.parametrize("field", settings.COMPANY_FIELDS)
def test_every_company_setting_changes_digest_without_invoice_revision(case,field):
    case = scenario(case)
    before, modified = capture(case), case.doc.modified
    value = "https://other.invalid/changed" if field in settings.ENVIRONMENT_FIELDS.values() else "CHANGED"
    setattr(case.company,field,value)
    after = capture(case)
    assert after.sha256 != before.sha256 and case.doc.modified == modified
    assert after.financial.sha256 == before.financial.sha256


@pytest.mark.parametrize("field", ["custom_phase_1_or_2","phase_1_or_2",
    *field_alias_registry.FIELD_ALIAS_GROUPS["company_arabic_name"]["aliases"]])
def test_blank_zero_absent_aliases_are_preserved_without_value_fallback(case,field):
    case = scenario(case)
    hashes = []
    for value in (None, "", 0, "0", False, "VALUE"):
        setattr(case.company,field,value)
        hashes.append(capture(case).sha256)
    case.company.meta.fields.remove(field)
    hashes.append(capture(case).sha256)
    assert len(hashes) == len(set(hashes))


@pytest.mark.parametrize("flag", [0,False,"0"," 0 ","",True,1,"1"," 1 "])
def test_device_checkbox_uses_shared_existing_flag_policy(case,flag):
    case = scenario(case,"linked",flag=flag)
    result = capture(case)
    expected = ["Company",case.linked.name] if settings.use_linked_company(flag) else ["ZATCA Multiple Setting",case.device.name]
    assert json.loads(result._payload)["declared_owner"] == expected


@pytest.mark.parametrize("flag", ["true","false","yes",2,[],{}, "PRIVATE"])
def test_bad_device_flag_never_falls_back_to_company(case,flag):
    case = scenario(case,"linked",flag=flag)
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("owner", ["linked","foreign_own"])
@pytest.mark.parametrize("vat", [None,"","DIFFERENT","  ","300000000000004"])
def test_foreign_taxpayer_refused_even_when_device_uses_own_keys(case,owner,vat):
    case = scenario(case,owner)
    case.linked.tax_id = vat
    assert_static(lambda:capture(case))


def test_taxpayer_whitespace_policy_is_shared_but_exact_values_remain_visible_as_drift(case):
    case = scenario(case,"linked")
    before = capture(case)
    case.linked.tax_id = "  "+case.company.tax_id+" "
    assert capture(case).sha256 != before.sha256


@pytest.mark.parametrize("fault", ["missing_company","missing_device","missing_linked","extra","wrong_name",
    "wrong_type","wrong_meta","missing_flag_schema","missing_link_schema","missing_company_schema","blank_link",
    "wrong_link","bad_source_reference","corrupt_financial","modified","record_key"])
def test_missing_extra_or_unbound_dependencies_fail_closed(case,fault):
    case = scenario(case,"linked")
    if fault == "missing_company": del case.records["Company",case.company.name]
    elif fault == "missing_device": del case.records["ZATCA Multiple Setting",case.device.name]
    elif fault == "missing_linked": del case.records["Company",case.linked.name]
    elif fault == "extra": case.records["Company","UNREFERENCED"] = case.company
    elif fault == "wrong_name": case.device.name = "PRIVATE"
    elif fault == "wrong_type": case.device.doctype = "Company"
    elif fault == "wrong_meta": case.device.meta.name = "Company"
    elif fault == "missing_flag_schema": case.device.meta.fields.remove("custom__use_company_certificate__keys")
    elif fault == "missing_link_schema": case.device.meta.fields.remove("custom_linked_doctype")
    elif fault == "missing_company_schema": case.company.meta.fields.remove("tax_id")
    elif fault == "blank_link": case.device.custom_linked_doctype = ""
    elif fault == "wrong_link": case.device.custom_linked_doctype = "OTHER"
    elif fault == "bad_source_reference":
        case.doc.custom_zatca_pos_name = False
        case.financial = capture_financial(case)
    elif fault == "corrupt_financial": object.__setattr__(case.financial,"sha256","PRIVATE")
    elif fault == "modified": case.company.modified = None
    else: case.records = {"PRIVATE":case.company}
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("field", settings.ENVIRONMENT_FIELDS.values())
@pytest.mark.parametrize("url", ["http://gateway.invalid/x","https://user:PRIVATE@gateway.invalid/x",
    "https://gateway.invalid/x?token=PRIVATE","https://gateway.invalid/x#PRIVATE",
    "PRIVATE",False," ", "https://gw-fatoora.zatca.gov.sa/WRONG-ENV"])
def test_all_configured_environment_urls_fail_closed_before_retention(case,field,url):
    case = scenario(case)
    setattr(case.company,field,url)
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("field", settings.ENVIRONMENT_FIELDS.values())
@pytest.mark.parametrize("value", [None,""])
def test_unconfigured_phase1_urls_are_observed_without_guessing_environment(case,field,value):
    case = scenario(case)
    setattr(case.company,field,value)
    assert capture(case)


@pytest.mark.parametrize("change", ["profile","source_hash","extra","missing","order","duplicate","owner",
    "record_secret","header_extra","header_missing","company","flag","modified","noncanonical","trailing"])
def test_direct_constructor_rechecks_whole_binding_and_canonical_structure(case,change):
    case = scenario(case,"linked")
    result = capture(case)
    body = json.loads(result._payload)
    if change == "profile": body["profile"] = "PRIVATE"
    elif change == "source_hash": body["financial_sha256"] = "f"*64
    elif change == "extra": body["secret"] = "PRIVATE"
    elif change == "missing": body["records"].pop()
    elif change == "order": body["records"].reverse()
    elif change == "duplicate": body["records"][1] = body["records"][0]
    elif change == "owner": body["declared_owner"] = ["Company","OTHER"]
    elif change == "record_secret": body["records"][0]["raw_auth"] = "PRIVATE"
    elif change == "header_extra": body["records"][0]["header"].append(["private_key",["str","PRIVATE"]])
    elif change == "header_missing": body["records"][0]["header"].pop()
    elif change == "company": body["records"][0]["name"] = "OTHER"
    elif change == "flag": body["records"][-1]["header"][-1][1] = ["str","true"]
    elif change == "modified": body["records"][0]["modified"] = ["null"]
    payload = settings._canonical(body)
    if change == "noncanonical": payload = json.dumps(body).encode()
    if change == "trailing": payload += b"PRIVATE"
    assert_static(lambda:replace(result,_payload=payload),"issuing_settings_observation")


def test_record_input_order_and_same_company_deduplication_are_stable(case):
    case = scenario(case,"device")
    before = capture(case)
    assert len(json.loads(before._payload)["records"]) == 2
    case.records = dict(reversed(tuple(case.records.items())))
    assert capture(case) == before


def test_secret_changes_cannot_change_the_nonsecret_observation(case):
    case = scenario(case,"linked")
    before = capture(case)
    for record in case.records.values():
        for field in SECRETS: setattr(record,field,"OTHER PRIVATE")
    assert capture(case) == before
    for record in case.records.values():
        assert not set(SECRETS) & set(record.reads)


def test_shared_alias_registry_remains_the_same_public_object():
    assert field_compat.FIELD_ALIAS_GROUPS is field_alias_registry.FIELD_ALIAS_GROUPS
    encoded = json.dumps(field_alias_registry.FIELD_ALIAS_GROUPS,sort_keys=True,
        separators=(",",":"),ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == "baaa4f4eba067abd74fecde42154c83fcd0bd178c9b66ef6e4905d360155477a"
    assert tuple(field_alias_registry.FIELD_ALIAS_GROUPS["company_arabic_name"]["aliases"]) == (
        "custom_company_name_in_arabic","company_name_in_arabic","custom__company_name_in_arabic__")


def test_captured_financial_and_records_are_independently_pinned(case):
    case = scenario(case,"linked")
    result = capture(case)
    before = result.sha256
    case.company.custom_select = "Sandbox"
    case.device.custom_linked_doctype = "OTHER"
    object.__setattr__(case.financial,"sha256","PRIVATE")
    result.__post_init__()
    assert result.sha256 == before


@pytest.mark.parametrize("flag", [None,0.0,1.0,Decimal("0"),Decimal("1")])
def test_canonical_flag_decoding_retains_existing_nullable_numeric_policy(case,flag):
    case = scenario(case,"linked")
    case.device.custom__use_company_certificate__keys = flag
    result = capture(case)
    lookup = {**case.records,(case.doc.doctype,case.doc.name):case.doc}
    selected,_kind = credential_settings._resolve_owner_record_from_saved_company(
        case.company,case.doc,load_doc=lambda dt,name:lookup[dt,name])
    assert json.loads(result._payload)["declared_owner"] == [selected.doctype,selected.name]


@pytest.mark.parametrize("failure", ["too_many", "payload", "wrong_type"])
def test_capture_size_and_type_bounds_are_static(case,monkeypatch,failure):
    case = scenario(case,"linked")
    if failure == "too_many": case.records["Company","EXTRA"] = case.company
    elif failure == "wrong_type": case.records = []
    else:
        from zatca_erpgulf.zatca_erpgulf import financial_source_observation
        monkeypatch.setattr(financial_source_observation,"MAX_PAYLOAD_BYTES",100)
    assert_static(lambda:capture(case))


def test_phase1_missing_environment_and_urls_are_not_inferred_as_live(case):
    case = scenario(case)
    case.company.custom_select = None
    case.company.custom_phase_1_or_2 = "Phase-1"
    for field in settings.ENVIRONMENT_FIELDS.values(): setattr(case.company,field,None)
    result = capture(case)
    assert not hasattr(result,"dispatch_authorized")
    header = dict(json.loads(result._payload)["records"][0]["header"])
    assert header["custom_select"] == ["null"]
