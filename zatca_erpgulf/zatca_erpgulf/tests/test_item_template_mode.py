"""Loaded-row template selection: frozen route parity and real money evidence.

No tenant, actual signer, GL, installed16, SDK or authority service is used.
Production metadata persistence is mocked, not certified transactional here.
"""
import ast
import copy
import csv
from decimal import Decimal
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance.item_template_mode import ItemTemplateModeError, REVIEW, item_template_mode
from zatca_erpgulf.zatca_erpgulf import (
    sign_invoice, pos_sign, sales_invoice_withoutxml, zatca_background_sched,
    pos_submit__without_xml, pos_schedule_background, debug_xml, pos_debug_xml,
    createxml, posxml, pos_final, create_xml_final_part as sales, xml_tax_data as totals,
)
from zatca_erpgulf.zatca_erpgulf.template_vat_source import DeclaredVatError, resolve_invoice_template_mode
from zatca_erpgulf.zatca_erpgulf.pos_financial_xml import PosFinancialError
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, isolated, stub_pipeline, ValidationError
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import (
    MODULES, fixture_data, input_snapshot, render,
)

REFERENCE = Path(__file__).with_name("fixtures") / "template_mode_generators_0cc3972.py"
REFERENCE_SHA = "ef79c872aabb8be937af20ce7829b24552f93ef71d9bcc7a905d3a9ea60fe433"
ROUTES = [
    (sign_invoice, "zatca_call", "Sales Invoice", "invoice"),
    (pos_sign, "zatca_call", "POS Invoice", "invoice"),
    (sales_invoice_withoutxml, "zatca_call_withoutxml", "Sales Invoice", "invoice"),
    (zatca_background_sched, "zatca_call_scheduler_background", "Sales Invoice", "invoice"),
    (pos_submit__without_xml, "zatca_call_pos_without_xml", "POS Invoice", "invoice"),
    (pos_schedule_background, "zatca_call_pos_without_xml_background", "POS Invoice", "invoice"),
    (sign_invoice, "zatca_call_compliance", "Sales Invoice", "compliance"),
    (pos_sign, "zatca_call_compliance", "POS Invoice", "compliance"),
    (debug_xml, "_debug_call", "Sales Invoice", "debug"),
    (pos_debug_xml, "_debug_call", "POS Invoice", "debug"),
]


def previous(module, name):
    raw = REFERENCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REFERENCE_SHA
    mapping = ast.literal_eval(ast.parse(raw).body[1].value)
    namespace = dict(vars(module))
    path = "zatca_erpgulf/zatca_erpgulf/" + module.__name__.rsplit(".", 1)[-1] + ".py"
    exec(compile(mapping[path], str(REFERENCE), "exec"), namespace)
    return namespace[name]


def typed_throw(message, *args, **kwargs):
    error = kwargs.get("exc")
    raise error if isinstance(error, BaseException) else ValidationError(message)


@pytest.fixture
def route_boundary(isolated, monkeypatch):
    doc, company, customer, app, files = isolated
    app.throw = Mock(side_effect=typed_throw)
    captures, stage_calls = [], []
    for module, _, _, _ in ROUTES:
        monkeypatch.setattr(module, "frappe", app)
        monkeypatch.setattr(module, "_", lambda message: message)
        stub_pipeline(monkeypatch, module, doc)
        module.salesinvoice_data.side_effect = lambda root, *args, **kwargs: (root, "TEST-UUID", doc)
        monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
        if hasattr(module, "is_advance_payment_invoice"):
            monkeypatch.setattr(module, "is_advance_payment_invoice", lambda doc: False)
        for name in ("is_zatca_invoice_enabled",):
            if hasattr(module, name): monkeypatch.setattr(module, name, lambda doc: True)
        if hasattr(module, "resolve_zatca_phase"): monkeypatch.setattr(module, "resolve_zatca_phase", lambda doc: "Phase-1")
        for name in ("add_document_level_discount_with_tax", "add_document_level_discount_with_tax_template",
                     "tax_data", "tax_data_with_template", "item_data", "item_data_with_template"):
            def stage(root, invoice, _name=name):
                stage_calls.append(_name)
                ET.SubElement(root, "Stage", name=_name)
                return root
            monkeypatch.setattr(module, name, Mock(side_effect=stage), raising=False)
        def capture(root):
            captures.append(copy.deepcopy(root))
            return "<Invoice>unsigned marker XML</Invoice>"
        monkeypatch.setattr(module, "xml_structuring", capture)
        monkeypatch.setattr(module, "sign_invoice_xml", Mock(return_value=SimpleNamespace(
            encoded_hash="TEST-HASH", qr_payload="TEST-QR", xml="<Invoice/>")))
        for name in ("attach_qr_image", "reporting_api", "clearance_api", "reporting_api_sales_withoutxml", "reporting_api_pos_without_xml", "compliance_api_call"):
            if hasattr(module, name): monkeypatch.setattr(module, name, Mock(return_value={"status": "PASS"}))
        monkeypatch.setattr(module, "structuring_signedxml", lambda *args: "unused.xml", raising=False)
    return SimpleNamespace(doc=doc, company=company, customer=customer, app=app, files=files,
                           roots=captures, calls=stage_calls)


def invoke(boundary, route, hint, *, old=False):
    module, name, doctype, purpose = route
    boundary.doc.doctype = doctype
    kwargs = dict(any_item_has_tax_template=hint)
    if purpose == "compliance": kwargs.update(company_abbr=boundary.company.abbr)
    fn = previous(module, name) if old else inspect.unwrap(getattr(module, name))
    return fn(boundary.doc.name, **kwargs)


def no_writes(b):
    b.doc.save.assert_not_called(); b.doc.db_set.assert_not_called()
    b.app.db.set_value.assert_not_called(); b.app.db.commit.assert_not_called()


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("hint", [False, True])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("returned", [False, True])
def test_all_loaded_routes_ignore_stale_hint_and_keep_correct_hint_parent_bytes(
    route_boundary, route, mode, hint, major, currency, returned,
):
    b=route_boundary
    b.doc.doctype = route[2]
    b.doc.currency, b.doc.is_return = currency, int(returned)
    b.doc.items = [Document(name="ROW-1", item_tax_template="VAT-15" if mode else ""),
                   Document(name="ROW-2", item_tax_template="VAT-5" if mode else None)]
    if major == 16: b.doc.item_wise_tax_details = [Document(item_row="ROW-1", tax_row="VAT", rate=15)]
    before = input_snapshot(b.doc)
    invoke(b, route, hint, old=True)
    expected = ET.tostring(b.roots[-1])
    b.calls.clear()
    invoke(b, route, hint)
    current = ET.tostring(b.roots[-1])
    suffix = "_with_template" if mode else ""
    assert b.calls == ["add_document_level_discount_with_tax" + ("_template" if mode else ""), "tax_data"+suffix, "item_data"+suffix]
    already_source_based = route[3] == "compliance" or route[0] is debug_xml
    assert (current == expected) == (mode == hint or already_source_based)
    assert input_snapshot(b.doc) == before
    no_writes(b)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("first", [False, True])
@pytest.mark.parametrize("language", ["en", "ar"])
@pytest.mark.parametrize("hint", [False, True])
def test_mixed_rows_stop_all_ten_routes_before_reference_financial_signer_or_transport(
    route_boundary, monkeypatch, route, first, language, hint,
):
    b=route_boundary; module, _, _, purpose=route
    b.doc.items = [Document(item_tax_template="VAT" if first else ""),
                   Document(item_tax_template="" if first else "VAT")]
    with (Path(__file__).resolve().parents[2]/"translations/ar.csv").open(newline="") as stream:
        catalog=dict(csv.reader(stream))
    translate=lambda message:catalog.get(message,message) if language=="ar" else message
    monkeypatch.setattr(module,"_",translate)
    if purpose=="debug":
        result=invoke(b,route,hint)
        assert result["status"]=="error" and result["notices"]==[REVIEW]
    else:
        with pytest.raises(DeclaredVatError) as caught:invoke(b,route,hint)
        assert caught.value.code=="item_template_mixed" and caught.value.template==REVIEW
    b.app.throw.assert_called_once()
    assert b.app.throw.call_args.args[0]==translate(REVIEW)
    b.app.log_error.assert_called_once()
    assert "item_template_mixed" in b.app.log_error.call_args.kwargs["message"]
    assert REVIEW in b.app.log_error.call_args.kwargs["message"]
    module.salesinvoice_data.assert_called_once()  # Metadata may already exist.
    module.sign_invoice_xml.assert_not_called()
    module.doc_reference.assert_not_called()
    if hasattr(module,"doc_reference_compliance"):module.doc_reference_compliance.assert_not_called()
    for name in ("reporting_api","clearance_api","reporting_api_sales_withoutxml","reporting_api_pos_without_xml","compliance_api_call"):
        if hasattr(module,name):getattr(module,name).assert_not_called()
    assert not b.roots and not b.calls and not b.files
    no_writes(b)


@pytest.mark.parametrize("values,expected", [([],False),([None,""],False),([0,False],False),(["VAT"],True),([" ","VAT"],True)])
@pytest.mark.parametrize("mapping", [False,True])
def test_native_presence_is_not_trimmed_reinterpreted_or_resolved(values,expected,mapping):
    rows=[{"item_tax_template":value} if mapping else Document(item_tax_template=value) for value in values]
    assert item_template_mode(rows)==expected


@pytest.mark.parametrize("bad", [True, "PRIVATE-VALUE", {}, 1.5])
def test_non_table_values_are_not_guessed_as_empty_or_template_mode(bad):
    with pytest.raises(ItemTemplateModeError) as caught:item_template_mode(bad)
    assert caught.value.code=="item_template_rows" and "PRIVATE" not in str(caught.value)


def test_one_pass_and_first_mixed_observation_stop_without_reading_later_rows():
    reads=[]
    class Row:
        def __init__(self,value): self.value=value
        @property
        def item_tax_template(self): reads.append(self.value); return self.value
    assert item_template_mode([Row("VAT"),Row("VAT")]) is True
    assert reads==["VAT","VAT"]
    reads.clear()
    with pytest.raises(ItemTemplateModeError,match="mixed"):
        item_template_mode([Row("VAT"),Row(""),Row("MUST-NOT-READ")])
    assert reads==["VAT",""]


def financial_runtime(monkeypatch,records):
    runtime=SimpleNamespace(get_doc=Mock(side_effect=lambda dt,name:records[dt,name]),throw=typed_throw,
        db=SimpleNamespace(commit=Mock(),set_value=Mock()),log_error=Mock(),msgprint=Mock())
    for module in MODULES:
        monkeypatch.setattr(module,"frappe",runtime)
        monkeypatch.setattr(module,"_",lambda message,*args:message)
    monkeypatch.setattr(sales,"supports_advance_deduction_schema",lambda doc:False)
    return runtime


def financial_xml(doc,mode,family):
    return render(doc,mode,family,dict(discount=vars(posxml if family=="pos" else createxml),
        tax=vars(pos_final if family=="pos" and mode else posxml if family=="pos" else sales if family=="nominal" else totals),
        items=vars(pos_final if family=="pos" else sales)))


@pytest.mark.parametrize("case",["invoice-template-15","invoice-template-zero","item-template-mixed-rates"])
@pytest.mark.parametrize("family",["sales","nominal","pos"])
@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("currency",["SAR","USD"])
@pytest.mark.parametrize("discount",[False,True])
def test_real_financial_xml_is_identical_when_existing_hint_matches_loaded_rows(monkeypatch,case,family,major,currency,discount):
    doc,records,mode=fixture_data(case,major,currency,discount)
    doc.custom_zatca_nominal_invoice=int(family=="nominal")
    if family=="pos":doc.doctype="POS Invoice"
    runtime=financial_runtime(monkeypatch,records)
    before=input_snapshot((doc,records))
    expected=financial_xml(doc,mode,family)
    actual_mode=resolve_invoice_template_mode(doc,runtime=runtime,translate=lambda text:text)
    actual=financial_xml(doc,actual_mode,family)
    assert ET.tostring(actual)==ET.tostring(expected)
    assert input_snapshot((doc,records))==before
    runtime.log_error.assert_not_called();runtime.db.commit.assert_not_called()


def test_literal_stale_mode_results_are_recorded_without_changing_saved_money(monkeypatch):
    results=[]
    for family in ("sales","pos"):
        for case,hint in (("invoice-template-15",True),("item-template-mixed-rates",False)):
            doc,records,mode=fixture_data(case,15,"SAR",False)
            if family=="pos":doc.doctype="POS Invoice"
            runtime=financial_runtime(monkeypatch,records)
            before=input_snapshot((doc,records))
            try:
                previous_root=financial_xml(doc,hint,family)
                legal=previous_root.find("cac:LegalMonetaryTotal")
                old={"payable":legal.find("cbc:PayableAmount").text,"xml":ET.tostring(previous_root).decode()}
            except (ValidationError,KeyError,DeclaredVatError,PosFinancialError) as error:
                old={"refused":type(error).__name__}
            selected=resolve_invoice_template_mode(doc,runtime=runtime,translate=lambda text:text)
            current=financial_xml(doc,selected,family)
            payable=current.find("cac:LegalMonetaryTotal").find("cbc:PayableAmount").text
            assert Decimal(payable)==Decimal("220" if mode else "230")
            assert input_snapshot((doc,records))==before
            results.append(dict(family=family,case=case,old=old,current_payable=payable))
    Path('/tmp/zatca-template-mode-226-money.json').write_text(json.dumps(results,indent=2))
