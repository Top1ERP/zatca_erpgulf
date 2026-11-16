"""Early template gate with real metadata and frozen pre-gate source ordering.

Spies model UUID writes/commit arguments and callbacks, not SQL/ORM durability.
No tenant, service, genuine signer/GL, installed16 or SDK acceptance is exercised.
"""
import ast
import copy
import csv
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import createxml, posxml, nonproduction
from zatca_erpgulf.zatca_erpgulf.invoice_generation_data import prepare_invoice_generation
from zatca_erpgulf.zatca_erpgulf.template_vat_source import DeclaredVatError, resolve_invoice_template_mode
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, isolated, ValidationError
from zatca_erpgulf.zatca_erpgulf.tests.test_item_template_mode import (
    ROUTES, route_boundary, typed_throw, no_writes,
)

REFERENCE=Path(__file__).with_name("fixtures")/"metadata_gate_d9c87a4.py"
REFERENCE_SHA="4fddb950aa2d7c889d94cc45ee1fb7b0c401f764c84002f96307ccedeb78839d"
ADAPTERS=((createxml,"Sales Invoice"),(posxml,"POS Invoice"))
GENERATION=[row for row in ROUTES if row[3]!="compliance"]
FIXED_UUID="b05809d9-7851-4767-b7e9-47af44c80cb9"


def previous(module,name):
    raw=REFERENCE.read_bytes();assert hashlib.sha256(raw).hexdigest()==REFERENCE_SHA
    sources=ast.literal_eval(ast.parse(raw).body[1].value)
    path="zatca_erpgulf/zatca_erpgulf/"+module.__name__.rsplit(".",1)[-1]+".py"
    namespace=dict(vars(module));exec(compile(sources[path],str(REFERENCE),"exec"),namespace)
    return namespace[name]


def rows(mode,mixed=False):
    return [Document(item_tax_template="VAT" if mode else ""),
            Document(item_tax_template="" if mode and mixed else "VAT" if mode or mixed else "")]


def setup_metadata(isolated,monkeypatch,adapter,doctype):
    doc,company,customer,runtime,files=isolated
    doc.doctype=doctype
    translate=lambda message:message
    runtime.throw=Mock(side_effect=typed_throw)
    monkeypatch.setattr(adapter,"frappe",runtime)
    monkeypatch.setattr(adapter,"_",translate)
    monkeypatch.setattr(adapter.uuid,"uuid1",Mock(return_value=FIXED_UUID))
    monkeypatch.setattr(nonproduction, "uuid4", lambda: FIXED_UUID)
    namespace=dict(salesinvoice_data=adapter._CANONICAL_INVOICE_METADATA,frappe=runtime,_=translate,
                   resolve_invoice_template_mode=adapter.resolve_invoice_template_mode)
    return doc,runtime,namespace


@pytest.mark.parametrize("adapter,doctype",ADAPTERS)
@pytest.mark.parametrize("purpose",["production","debug"])
@pytest.mark.parametrize("existing",[None,FIXED_UUID])
@pytest.mark.parametrize("first",[False,True])
@pytest.mark.parametrize("language",["en","ar"])
def test_initial_mixed_rows_fail_before_uuid_provider_or_metadata_append(
    isolated,monkeypatch,adapter,doctype,purpose,existing,first,language,
):
    doc,runtime,namespace=setup_metadata(isolated,monkeypatch,adapter,doctype)
    doc.custom_uuid=existing;doc.items=rows(first,mixed=True)
    # The old adapter could produce metadata and persist Sales UUID first.
    original=previous(adapter,"salesinvoice_data")
    root=ET.Element("Invoice")
    old=original(root,doc.name,purpose=purpose)
    assert len(old)==3 and old[2] is doc and root.find("cbc:UUID") is not None
    assert doc.db_set.call_count==int(adapter is createxml and purpose=="production" and existing is None)
    doc.custom_uuid=existing;doc.db_set.reset_mock();runtime.log_error.reset_mock()
    adapter.uuid.uuid1.reset_mock()
    with (Path(__file__).resolve().parents[2]/"translations/ar.csv").open(newline="") as stream:catalog=dict(csv.reader(stream))
    translate=lambda message:catalog.get(message,message) if language=="ar" else message
    monkeypatch.setattr(adapter,"_",translate);namespace["_"]=translate
    root=ET.Element("Invoice");ET.SubElement(root,"Unrelated").text="KEEP"
    before=ET.tostring(root)
    with pytest.raises(DeclaredVatError) as caught:
        prepare_invoice_generation(root,doc.name,namespace=namespace,doctype=doctype,purpose=purpose)
    assert caught.value.code=="item_template_mixed"
    assert ET.tostring(root)==before and doc.custom_uuid==existing
    doc.db_set.assert_not_called();runtime.db.commit.assert_not_called()
    adapter.uuid.uuid1.assert_not_called()
    runtime.log_error.assert_called_once()
    assert runtime.throw.call_args.args[0]==translate(caught.value.template)


@pytest.mark.parametrize("adapter,doctype",ADAPTERS)
@pytest.mark.parametrize("purpose",["production","debug","compliance"])
@pytest.mark.parametrize("existing",[None,FIXED_UUID])
@pytest.mark.parametrize("mode",[False,True])
@pytest.mark.parametrize("major",[15,16])
def test_public_metadata_keeps_three_values_bytes_and_uuid_write_contract(
    isolated,monkeypatch,adapter,doctype,purpose,existing,mode,major,
):
    doc,runtime,namespace=setup_metadata(isolated,monkeypatch,adapter,doctype)
    doc.custom_uuid=existing;doc.items=rows(mode)
    if major==16:doc.item_wise_tax_details=[Document(item_row="ROW",tax_row="TAX",rate=15)]
    old_root=ET.Element("Invoice");expected=previous(adapter,"salesinvoice_data")(old_root,doc.name,purpose=purpose)
    writes=doc.db_set.call_args_list[:]
    doc.custom_uuid=existing;doc.db_set.reset_mock();runtime.get_doc.reset_mock()
    root=ET.Element("Invoice");current=adapter.salesinvoice_data(root,doc.name,purpose=purpose)
    assert len(current)==len(expected)==3 and current[2] is doc
    assert ET.tostring(root)==ET.tostring(old_root) and current[1]==expected[1]
    assert doc.db_set.call_args_list==writes
    runtime.get_doc.assert_called_once_with(doctype,doc.name)
    runtime.log_error.assert_not_called()


@pytest.mark.parametrize("adapter,doctype",ADAPTERS)
@pytest.mark.parametrize("purpose",["production","debug"])
@pytest.mark.parametrize("mode",[False,True])
def test_canonical_bridge_returns_checked_mode_without_an_extra_caller_scan(isolated,monkeypatch,adapter,doctype,purpose,mode):
    doc,runtime,namespace=setup_metadata(isolated,monkeypatch,adapter,doctype)
    doc.custom_uuid=FIXED_UUID;doc.items=rows(mode)
    reader=Mock(wraps=resolve_invoice_template_mode)
    monkeypatch.setattr(adapter,"resolve_invoice_template_mode",reader);namespace["resolve_invoice_template_mode"]=reader
    root=ET.Element("Invoice")
    result=prepare_invoice_generation(root,doc.name,namespace=namespace,doctype=doctype,purpose=purpose)
    assert result[0] is root and result[2] is doc and result[3] is mode
    assert reader.call_count==2  # Before and after identity callbacks, not three.
    runtime.get_doc.assert_called_once_with(doctype,doc.name)


@pytest.mark.parametrize("adapter,doctype",ADAPTERS)
@pytest.mark.parametrize("purpose",["production","debug"])
@pytest.mark.parametrize("variant",["runtime","translator","reader"])
def test_distinct_bindings_keep_legacy_metadata_contract_and_caller_reader(
    isolated,monkeypatch,adapter,doctype,purpose,variant,
):
    doc,runtime,namespace=setup_metadata(isolated,monkeypatch,adapter,doctype)
    doc.custom_uuid=FIXED_UUID;doc.items=rows(True)
    reader=Mock(wraps=resolve_invoice_template_mode)
    monkeypatch.setattr(adapter,"resolve_invoice_template_mode",reader);namespace["resolve_invoice_template_mode"]=reader
    if variant=="runtime":namespace["frappe"]=SimpleNamespace()
    elif variant=="translator":namespace["_"]=lambda message:"AR:"+message
    else:namespace["resolve_invoice_template_mode"]=Mock(wraps=resolve_invoice_template_mode)
    result=prepare_invoice_generation(ET.Element("Invoice"),doc.name,namespace=namespace,doctype=doctype,purpose=purpose)
    assert len(result)==4 and result[2] is doc and result[3] is True
    assert reader.call_count==(2 if variant=="reader" else 3)
    if variant=="reader":namespace["resolve_invoice_template_mode"].assert_called_once()
    runtime.get_doc.assert_called_once_with(doctype,doc.name)


@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("purpose",["production","debug"])
@pytest.mark.parametrize("mode",[False,True])
def test_imported_metadata_override_gets_original_arguments_and_preserves_returned_objects(doctype,purpose,mode):
    old_root,replacement=ET.Element("Original"),ET.Element("Replacement")
    doc=Document(items=rows(mode));runtime=SimpleNamespace()
    metadata=Mock(return_value=(replacement,"OPAQUE-UUID",doc))
    mode_reader=Mock(wraps=resolve_invoice_template_mode)
    namespace=dict(salesinvoice_data=metadata,frappe=runtime,_=str,resolve_invoice_template_mode=mode_reader)
    result=prepare_invoice_generation(old_root,"NAME",namespace=namespace,doctype=doctype,purpose=purpose)
    assert result==(replacement,"OPAQUE-UUID",doc,mode)
    expected_kwargs={} if purpose=="production" else dict(purpose="debug")
    metadata.assert_called_once_with(old_root,"NAME",**expected_kwargs)
    assert "_include_template_mode" not in metadata.call_args.kwargs
    mode_reader.assert_called_once_with(doc,runtime=runtime,translate=str)


def test_override_side_effects_cannot_be_undone_by_post_return_mode_review():
    effects=[];doc=Document(items=rows(False,mixed=True))
    runtime=SimpleNamespace(log_error=Mock(),throw=typed_throw)
    def override(*args,**kwargs):effects.append("already performed");return ET.Element("Replacement"),"ID",doc
    namespace=dict(salesinvoice_data=override,frappe=runtime,_=str,resolve_invoice_template_mode=resolve_invoice_template_mode)
    with pytest.raises(DeclaredVatError):prepare_invoice_generation(ET.Element("Invoice"),"NAME",namespace=namespace,doctype="Sales Invoice")
    assert effects==["already performed"]


@pytest.mark.parametrize("change",["mode","mixed"])
@pytest.mark.parametrize("initial",[False,True])
@pytest.mark.parametrize("language",["en","ar"])
def test_sales_db_set_callback_drift_is_reviewed_without_rewinding_written_uuid(isolated,monkeypatch,change,initial,language):
    doc,runtime,namespace=setup_metadata(isolated,monkeypatch,createxml,"Sales Invoice")
    doc.custom_uuid=None;doc.items=rows(initial)
    doc.db_set.side_effect=lambda *args,**kwargs:setattr(doc,"items",rows(not initial,mixed=change=="mixed"))
    with (Path(__file__).resolve().parents[2]/"translations/ar.csv").open(newline="") as stream:catalog=dict(csv.reader(stream))
    translate=lambda text:catalog.get(text,text) if language=="ar" else text
    monkeypatch.setattr(createxml,"_",translate);namespace["_"]=translate
    root=ET.Element("Invoice")
    with pytest.raises(DeclaredVatError) as caught:
        prepare_invoice_generation(root,doc.name,namespace=namespace,doctype="Sales Invoice")
    assert caught.value.code==("item_template_mixed" if change=="mixed" else "metadata_item_template_changed")
    assert doc.custom_uuid==FIXED_UUID and len(root)==0
    doc.db_set.assert_called_once_with("custom_uuid",FIXED_UUID,commit=True,update_modified=False)
    runtime.log_error.assert_called_once();runtime.db.commit.assert_not_called()
    assert runtime.throw.call_args.args[0]==translate(caught.value.template)


@pytest.mark.parametrize("adapter,doctype",ADAPTERS)
@pytest.mark.parametrize("shape",["absent","none","empty"])
def test_legacy_partial_metadata_records_without_document_get_still_work(isolated,monkeypatch,adapter,doctype,shape):
    doc,runtime,namespace=setup_metadata(isolated,monkeypatch,adapter,doctype)
    partial=SimpleNamespace(name=doc.name,posting_date=doc.posting_date,posting_time=doc.posting_time,custom_uuid=FIXED_UUID,db_set=Mock())
    if shape!="absent":partial.items=None if shape=="none" else []
    runtime.get_doc.return_value=partial;runtime.get_doc.side_effect=None
    result=adapter.salesinvoice_data(ET.Element("Invoice"),doc.name)
    assert len(result)==3 and result[2] is partial
    partial.db_set.assert_not_called()


@pytest.mark.parametrize("adapter,doctype",ADAPTERS)
def test_compliance_keeps_existing_metadata_and_later_company_boundary(isolated,monkeypatch,adapter,doctype):
    doc,runtime,namespace=setup_metadata(isolated,monkeypatch,adapter,doctype)
    doc.items=rows(False,mixed=True)
    reader=Mock(side_effect=AssertionError("Compliance Company binding must run first"))
    monkeypatch.setattr(adapter,"resolve_invoice_template_mode",reader)
    result=adapter.salesinvoice_data(ET.Element("Invoice"),doc.name,purpose="compliance")
    assert len(result)==3 and result[2] is doc
    reader.assert_not_called();doc.db_set.assert_not_called()


@pytest.mark.parametrize("route",GENERATION)
@pytest.mark.parametrize("mode",[False,True])
@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("returned",[False,True])
@pytest.mark.parametrize("currency",["SAR","USD"])
def test_all_eight_generators_keep_parent_xml_and_source_with_imported_metadata(
    route_boundary,route,mode,major,returned,currency,
):
    b=route_boundary;module,name,doctype,purpose=route
    b.doc.doctype=doctype;b.doc.items=rows(mode);b.doc.currency=currency;b.doc.is_return=int(returned)
    if major==16:b.doc.item_wise_tax_details=[Document(item_row="ROW",rate=15)]
    kwargs=dict(any_item_has_tax_template=not mode)
    old=previous(module,name)(b.doc.name,**kwargs)
    expected=ET.tostring(b.roots[-1])
    current=inspect.unwrap(getattr(module,name))(b.doc.name,**kwargs)
    assert ET.tostring(b.roots[-1])==expected
    if purpose=="debug":assert current["status"]==old["status"]=="success"
    no_writes(b)


@pytest.mark.parametrize("route",GENERATION)
@pytest.mark.parametrize("first",[False,True])
def test_eight_native_routes_stop_initial_mixed_rows_before_uuid_call_or_write(route_boundary,monkeypatch,route,first):
    b=route_boundary;module,name,doctype,purpose=route
    adapter=createxml if doctype=="Sales Invoice" else posxml
    doc,runtime,namespace=setup_metadata((b.doc,b.company,b.customer,b.app,b.files),monkeypatch,adapter,doctype)
    translate=module._;monkeypatch.setattr(adapter,"_",translate)
    monkeypatch.setattr(module,"salesinvoice_data",adapter._CANONICAL_INVOICE_METADATA)
    monkeypatch.setattr(module,"resolve_invoice_template_mode",adapter.resolve_invoice_template_mode)
    doc.items=rows(first,mixed=True);doc.custom_uuid=None
    adapter.uuid.uuid1.reset_mock()
    if purpose=="debug":assert inspect.unwrap(getattr(module,name))(doc.name)["status"]=="error"
    else:
        with pytest.raises(DeclaredVatError):inspect.unwrap(getattr(module,name))(doc.name)
    doc.db_set.assert_not_called();adapter.uuid.uuid1.assert_not_called()
    module.sign_invoice_xml.assert_not_called()
    module.doc_reference.assert_not_called()
    assert not b.roots and not b.calls and not b.files
    no_writes(b)
