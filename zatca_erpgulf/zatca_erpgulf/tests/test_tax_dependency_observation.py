"""Pure linked-template observations; synthetic records, no framework or HTTP."""

import json
import pickle
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from zatca_erpgulf.zatca_erpgulf import tax_dependency_observation as tax
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_observation import (
    Document, Metadata, erp_major, case, capture as capture_financial,
)


def scenario(case, *, invoice=True, items=True, mixed=False):
    case.doc.taxes_and_charges = "SYNTHETIC-SALES-TAX" if invoice else None
    for index, row in enumerate(case.doc.items):
        row.item_tax_template = ("SYNTHETIC-ITEM-TAX" + str(index)
            if items and not (mixed and index) else None)
    observation = capture_financial(case)
    references = tax._dependencies(observation)[1]
    templates, metas = {}, {}
    for doctype, name in references:
        child_type, fields, _required = tax.TABLE_PROFILES[doctype]
        meta = Metadata(doctype, (*tax.TEMPLATE_FIELDS, "taxes"), {"taxes":child_type})
        child_meta = Metadata(child_type, fields)
        document = Document(doctype=doctype, name=name, meta=meta, company=case.doc.company,
            modified=case.doc.modified, custom_zatca_tax_category="Standard",
            custom_exemption_reason_code="", disabled=0)
        rows = []
        for index in range(1,3):
            row = Document(doctype=child_type, name=name+"-ROW-"+str(index), idx=index,
                parent=name, parenttype=doctype, parentfield="taxes")
            for field in fields: setattr(row, field, None)
            if doctype == "Item Tax Template": row.tax_rate = Decimal("15.00")
            else: row.rate = Decimal("15.00")
            rows.append(row)
        document.taxes = rows
        templates[doctype,name], metas[doctype] = document, child_meta
    case.financial, case.templates, case.tax_metas = observation, templates, metas
    return case


def capture(case):
    return tax.capture_tax_dependency_observation(case.financial,
        templates=case.templates, child_metas=case.tax_metas)


def assert_static(call, code="tax_dependency_capture"):
    with pytest.raises(tax.TaxDependencyError) as caught: call()
    assert caught.value.code == str(caught.value) == code
    assert caught.value.__context__ is None


@pytest.mark.parametrize("invoice,items,mixed", [(False,False,False), (True,False,False),
    (False,True,False), (True,True,False), (True,True,True)])
def test_exact_dependency_set_independent_of_tax_precedence_and_mixed_usage(case, invoice, items, mixed):
    case = scenario(case, invoice=invoice, items=items, mixed=mixed)
    result = capture(case)
    assert capture(case) == result
    assert result.financial == case.financial and result.financial is not case.financial
    assert len(json.loads(result._payload)["records"]) == len(case.templates)
    assert len(result.sha256) == 64
    assert "SYNTHETIC" not in repr(result) and "15.00" not in repr(result)
    assert "PARTIAL" in repr(result)
    with pytest.raises(FrozenInstanceError): result.sha256 = "f"*64
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    assert not hasattr(result, "source_snapshot_verified") and not hasattr(result, "dispatch_authorized")
    for doc in (case.doc, *case.templates.values()):
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()


def test_dictionary_input_order_and_shared_item_reference_do_not_duplicate_records(case):
    case.doc.items[1].item_tax_template = "ignored"
    case = scenario(case)
    case.doc.items[1].item_tax_template = case.doc.items[0].item_tax_template
    case.financial = capture_financial(case)
    unused = ("Item Tax Template", "SYNTHETIC-ITEM-TAX1")
    del case.templates[unused]
    result = capture(case)
    case.templates = dict(reversed(tuple(case.templates.items())))
    case.tax_metas = dict(reversed(tuple(case.tax_metas.items())))
    assert capture(case) == result
    assert len(json.loads(result._payload)["records"]) == 2


@pytest.mark.parametrize("doctype", tax.TABLE_PROFILES)
@pytest.mark.parametrize("field", tax.TEMPLATE_FIELDS)
def test_each_template_header_dependency_changes_digest_without_invoice_revision(case, doctype, field):
    case = scenario(case)
    before, modified = capture(case), case.doc.modified
    document = next(doc for (dt,_name), doc in case.templates.items() if dt == doctype)
    setattr(document, field, "CHANGED" if field != "company" else case.doc.company)
    if field == "company":
        document.company = "OTHER-COMPANY"
        assert_static(lambda:capture(case))
    else:
        assert capture(case).sha256 != before.sha256 and case.doc.modified == modified


@pytest.mark.parametrize("doctype,field", [
    (dt, field) for dt, (_child, fields, _required) in tax.TABLE_PROFILES.items() for field in fields
])
def test_each_linked_tax_row_value_changes_digest_without_parent_timestamps(case, doctype, field):
    case = scenario(case)
    before, modified = capture(case), case.doc.modified
    document = next(doc for (dt,_name),doc in case.templates.items() if dt == doctype)
    setattr(document.taxes[0], field, "CHANGED")
    assert capture(case).sha256 != before.sha256
    assert case.doc.modified == document.modified == modified


@pytest.mark.parametrize("doctype", tax.TABLE_PROFILES)
@pytest.mark.parametrize("change", ["zero", "null", "empty", "false", "absent"])
def test_valid_zero_and_schema_presence_never_trigger_an_alias_fallback(case, doctype, change):
    case = scenario(case)
    before = capture(case)
    document = next(doc for (dt,_name),doc in case.templates.items() if dt == doctype)
    value = {"zero":0,"null":None,"empty":"","false":False,"absent":None}[change]
    document.custom_zatca_tax_category = value
    if change == "absent": document.meta.fields.remove("custom_zatca_tax_category")
    assert capture(case).sha256 != before.sha256
    # Observations do not pick invoice/template precedence or convert category.
    case.doc.custom_zatca_tax_category = "INVOICE-VALUE"
    assert case.financial.sha256 == before.financial.sha256


@pytest.mark.parametrize("doctype", tax.TABLE_PROFILES)
@pytest.mark.parametrize("change", ["delete", "insert", "reorder", "row_name", "empty", "schema"])
def test_linked_membership_order_and_schema_changes_are_visible(case, doctype, change):
    case = scenario(case)
    before = capture(case)
    document = next(doc for (dt,_name),doc in case.templates.items() if dt == doctype)
    if change == "delete": document.taxes.pop()
    elif change == "insert":
        row = Document(**{k:v for k,v in document.taxes[0].__dict__.items()
            if k not in ("reads","save","db_set")})
        row.name, row.idx = "SYNTHETIC-EXTRA-ROW", 3
        document.taxes.append(row)
    elif change == "reorder":
        document.taxes.reverse()
        for index,row in enumerate(document.taxes,1): row.idx = index
    elif change == "row_name": document.taxes[0].name = "SYNTHETIC-NEW-NAME"
    elif change == "empty": document.taxes = []
    else:
        # Item rows require both columns; parent optional schema still observes drift.
        document.meta.fields.remove("disabled")
    assert capture(case).sha256 != before.sha256


@pytest.mark.parametrize("fault", ["missing_template","extra_template","wrong_name","wrong_doctype",
    "wrong_meta","missing_meta","extra_meta","parent","parenttype","parentfield","idx","duplicate",
    "wrong_table","missing_table","company_schema","company","modified","missing_child_column"])
def test_unbound_missing_or_extra_dependencies_fail_closed(case, fault):
    case = scenario(case)
    key = next(key for key in case.templates if key[0] == "Item Tax Template")
    document = case.templates[key]
    if fault == "missing_template": del case.templates[key]
    elif fault == "extra_template": case.templates["Item Tax Template","UNREFERENCED"] = document
    elif fault == "wrong_name": document.name = "PRIVATE"
    elif fault == "wrong_doctype": document.doctype = "PRIVATE"
    elif fault == "wrong_meta": document.meta.name = "PRIVATE"
    elif fault == "missing_meta": del case.tax_metas["Item Tax Template"]
    elif fault == "extra_meta": case.tax_metas["Company"] = document.meta
    elif fault in ("parent","parenttype","parentfield"): setattr(document.taxes[0], fault, "PRIVATE")
    elif fault == "idx": document.taxes[0].idx = True
    elif fault == "duplicate": document.taxes[1].name = document.taxes[0].name
    elif fault == "wrong_table": document.meta.tables["taxes"] = "PRIVATE"
    elif fault == "missing_table": document.meta.fields.remove("taxes")
    elif fault == "company_schema": document.meta.fields.remove("company")
    elif fault == "company": document.company = "PRIVATE"
    elif fault == "modified": document.modified = None
    else: case.tax_metas["Item Tax Template"].fields.remove("tax_rate")
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("field", ["taxes_and_charges","item_tax_template"])
@pytest.mark.parametrize("value", [0,False,1,Decimal("0"),["PRIVATE"]])
def test_nonstring_references_are_not_silently_ignored(case, field, value):
    scenario(case)
    if field == "taxes_and_charges": case.doc.taxes_and_charges = value
    else: case.doc.items[0].item_tax_template = value
    # Lists are rejected by financial observation itself, before dependency selection.
    if isinstance(value, list):
        with pytest.raises(financial.FinancialSourceError): capture_financial(case)
    else:
        case.financial = capture_financial(case)
        assert_static(lambda:capture(case))


@pytest.mark.parametrize("field", ["sha256","doctype","name","_payload"])
def test_corrupt_financial_contract_is_not_accepted_as_a_reference_proof(case, field):
    case = scenario(case)
    object.__setattr__(case.financial, field, b"PRIVATE" if field == "_payload" else "PRIVATE")
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("change", ["profile","source_hash","extra","missing","order","company","header",
    "modified","table_type","idx","duplicate","presence","extra_record_field","noncanonical","trailing"])
def test_direct_construction_revalidates_exact_source_dependency_set_and_structure(case, change):
    case = scenario(case)
    result = capture(case)
    body = json.loads(result._payload)
    record = body["records"][0]
    if change == "profile": body["profile"] = "PRIVATE"
    elif change == "source_hash": body["financial_sha256"] = "f"*64
    elif change == "extra": body["secret"] = "PRIVATE"
    elif change == "missing": body["records"].pop()
    elif change == "order": body["records"].reverse()
    elif change == "company": record["header"][0][1] = ["str","OTHER"]
    elif change == "header": record["header"].pop()
    elif change == "modified": record["modified"] = ["null"]
    elif change == "table_type": record["taxes"]["doctype"] = "PRIVATE"
    elif change == "idx": record["taxes"]["rows"][0][1] = True
    elif change == "duplicate": record["taxes"]["rows"][1][0] = record["taxes"]["rows"][0][0]
    elif change == "presence": record["taxes"]["presence"][0] = 1
    elif change == "extra_record_field": record["raw_auth"] = "PRIVATE"
    payload = financial._canonical(body)
    if change == "noncanonical": payload = json.dumps(body).encode()
    if change == "trailing": payload += b"PRIVATE"
    assert_static(lambda:replace(result,_payload=payload), "tax_dependency_observation")


@pytest.mark.parametrize("limit", ["templates","rows","payload"])
def test_capture_bounds_are_enforced(case, monkeypatch, limit):
    case = scenario(case)
    if limit == "templates": monkeypatch.setattr(tax, "MAX_TEMPLATES", 1)
    elif limit == "rows": monkeypatch.setattr(tax, "MAX_TAX_ROWS", 1)
    else: monkeypatch.setattr(financial, "MAX_PAYLOAD_BYTES", 100)
    assert_static(lambda:capture(case))


def test_independent_pins_do_not_retain_mutable_template_or_financial_references(case):
    case = scenario(case)
    result = capture(case)
    before = result.sha256
    first = next(iter(case.templates.values()))
    first.disabled, first.taxes[0].tax_rate = 1, Decimal("0")
    object.__setattr__(case.financial, "sha256", "f"*64)
    assert result.sha256 == before
    result.__post_init__()
    assert result.sha256 == before



@pytest.mark.parametrize("doctype", tax.TABLE_PROFILES)
@pytest.mark.parametrize("value", [0, Decimal("0.00"), None, "", False])
def test_zero_rates_and_conflicting_source_values_are_observed_not_resolved(case, doctype, value):
    case.doc.custom_zatca_tax_category = "INVOICE-OBSERVATION"
    case = scenario(case)
    document = next(doc for (dt,_name),doc in case.templates.items() if dt == doctype)
    document.custom_zatca_tax_category = "TEMPLATE-OBSERVATION"
    rate_field = "tax_rate" if doctype == "Item Tax Template" else "rate"
    setattr(document.taxes[0], rate_field, value)
    result = capture(case)
    record = next(record for record in json.loads(result._payload)["records"]
        if (record["doctype"],record["name"]) == (doctype,document.name))
    assert dict(record["taxes"]["rows"][0][2])[rate_field] == financial._scalar(value)
    assert dict(record["header"])["custom_zatca_tax_category"] == ["str","TEMPLATE-OBSERVATION"]
    assert dict(json.loads(result.financial._payload)["header"])["custom_zatca_tax_category"] == ["str","INVOICE-OBSERVATION"]


def test_same_sql_child_identity_cannot_belong_to_two_templates(case):
    case = scenario(case)
    items = [doc for (dt,_name),doc in case.templates.items() if dt == "Item Tax Template"]
    items[1].taxes[0].name = items[0].taxes[0].name
    assert_static(lambda:capture(case))


def test_missing_template_fails_instead_of_choosing_invoice_fallback(case):
    case.doc.custom_zatca_tax_category = "Standard"
    case = scenario(case, items=False)
    case.templates.clear()
    assert_static(lambda:capture(case))



def test_shared_template_helpers_preserve_committed_v105_wire_fingerprints(case):
    case=scenario(case)
    expected={
        (15,"Sales Invoice"):"878615ba8a8a6b378fd25e145f7a349ded0b97ebd9a7d5a00331bdc916b6a1a9",
        (15,"POS Invoice"):"23a00b991404265cca8208a0c51faaeda4a17dff3ccefa15c7529dbb04078901",
        (16,"Sales Invoice"):"967afadf93b48ceea73a47461f199afd351eea31d9e622f924d0f1d79efd21aa",
        (16,"POS Invoice"):"3ccc87d5536f25d46d0c67104db06850f21360be9e313388c85b47cb3443f44b",
    }
    # Independently compared with committed source before freezing these values.
    assert capture(case).sha256==expected[case.erp_major,case.doc.doctype]
