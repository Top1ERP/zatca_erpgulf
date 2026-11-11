"""Real mocked XML builders and sequence ownership; no site/authority I/O.

The frozen reference is the five-step sequence before extraction in da4beaa.
Parity is per adapter: existing Sales/POS differences are not normalized away.
"""

from dataclasses import FrozenInstanceError, fields, replace
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import createxml, icv, posxml
from zatca_erpgulf.zatca_erpgulf.invoice_party_xml import PartyXmlTools, populate_invoice_parties
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import MISSING_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_xml_core import (
    ADAPTERS, assert_no_writes, hash_boundary, select,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, ValidationError


MODES = [("invoice", None), ("debug", None)] + [("compliance", str(code)) for code in range(1, 7)]


def previous_sequence(invoice, doc, number, abbr, tools, code=None):
    """Freeze former direct calls, including the late ordinary is_return read."""
    if tools.purpose == "compliance":
        invoice = tools.reference(invoice, doc, number, code)
    elif tools.purpose == "debug":
        invoice = tools.reference(invoice, doc, number, debug=True)
    else:
        invoice = tools.reference(invoice, doc, number)
    invoice = tools.additional_reference(invoice, abbr, doc)
    invoice = tools.company_data(invoice, doc)
    invoice = tools.customer_data(invoice, doc)
    if tools.purpose == "compliance":
        invoice = tools.payment(invoice, doc, code)
    else:
        invoice = tools.payment(invoice, doc, doc.is_return)
    return invoice


@pytest.fixture
def party_source(hash_boundary, monkeypatch):
    b = hash_boundary
    b.company.custom_costcenter = 0
    b.company.custom_registration_type, b.company.custom_company_registration = "CRN", "1010000000"
    b.company.company_name, b.company.company_name_in_arabic = "Synthetic Seller", "شركة الاختبار"
    buyer = Document(doctype="Customer", name="BUYER", customer_name="Synthetic Buyer",
                     customer_name_in_arabic="عميل الاختبار", tax_id="300000000000003")
    b.docs[buyer.doctype, buyer.name] = buyer
    buyer.save, buyer.db_set = Mock(), Mock()
    address = Document(address_line1="King Road", address_line2="Central District", city="Riyadh",
                       custom_building_number="1234", pincode="12345", state="Riyadh", country="Saudi Arabia")
    b.runtime.get_meta = Mock(return_value=SimpleNamespace(get_field=lambda name: name))
    b.runtime.DoesNotExistError = ValueError
    counter = Mock(return_value="7")
    monkeypatch.setattr(icv, "get_icv", counter)
    aliases = {"customer_b2c": "b2c", "customer_buyer_id_type": "buyer_type", "customer_buyer_id": "buyer_id"}
    for module in (createxml, posxml):
        monkeypatch.setattr(module, "get_address", lambda *args: address)
        monkeypatch.setattr(module, "get_alias_value", lambda key, doc, default=None: doc.get(aliases[key], default))
    monkeypatch.setattr(createxml, "_get_customer_address", lambda *args: address)
    monkeypatch.setattr(posxml, "resolve_customer_address", lambda *args: (address, "synthetic"))
    buyer.b2c, buyer.buyer_type, buyer.buyer_id = 0, "CRN", "2020000000"
    for doc in (b.sales, b.pos):
        doc.customer, doc.currency, doc.due_date = buyer.name, "SAR", "2026-11-11"
        doc.is_return, doc.is_debit_note, doc.return_against = 0, 0, "BASE-INVOICE"
        doc.cost_center = None
    return b, counter


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("purpose,code", MODES)
@pytest.mark.parametrize("owner,flag", [("company", 0), ("device", 0), ("linked", 1)])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_real_party_builders_match_previous_bytes_owner_reads_and_counter_purpose(
    party_source, module, doctype, purpose, code, owner, flag, currency,
):
    b, counter = party_source
    doc = select(b, module, owner, flag)
    doc.currency = currency
    tools = PartyXmlTools.from_namespace(vars(module), doctype=doctype, purpose=purpose)
    expected = previous_sequence(ET.Element("Invoice"), doc, doc.name, "TC", tools, code)
    reads, counter_calls = b.runtime.get_doc.call_args_list[:], counter.call_args_list[:]
    b.runtime.get_doc.reset_mock()
    counter.reset_mock()
    actual = populate_invoice_parties(ET.Element("Invoice"), doc, doc.name, "TC", tools=tools, compliance_type=code)
    assert ET.tostring(actual) == ET.tostring(expected)
    assert b.runtime.get_doc.call_args_list == reads
    assert counter.call_args_list == counter_calls
    assert counter.call_args.args == (doc, "Compliance" if purpose == "compliance" else "Debug" if purpose == "debug" else "Production")
    assert counter.call_args.kwargs == ({} if purpose == "compliance" else {"debug": purpose == "debug"})
    refs = actual.findall("cac:AdditionalDocumentReference")
    assert [ref.find("cbc:ID").text for ref in refs] == ["ICV", "PIH", "QR"]
    assert refs[1].find("cac:Attachment").find("cbc:EmbeddedDocumentBinaryObject").text == getattr(b, owner).custom_pih
    assert actual.find("cac:AccountingSupplierParty") is not None
    assert actual.find("cac:AccountingCustomerParty") is not None
    assert actual.find("cac:PaymentMeans").find("cbc:PaymentMeansCode").text == "30"
    assert_no_writes(b)


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("purpose", ["invoice", "debug"])
@pytest.mark.parametrize("kind", ["return", "debit", "advance"])
def test_existing_note_reference_payment_and_advance_header_behavior_is_preserved(party_source, module, doctype, purpose, kind):
    b, _counter = party_source
    doc = select(b, module, "company")
    doc.is_return, doc.is_debit_note, doc.is_advance_payment = int(kind == "return"), int(kind == "debit"), int(kind == "advance")
    tools = PartyXmlTools.from_namespace(vars(module), doctype=doctype, purpose=purpose)
    expected = previous_sequence(ET.Element("Invoice"), doc, doc.name, "TC", tools)
    actual = populate_invoice_parties(ET.Element("Invoice"), doc, doc.name, "TC", tools=tools)
    assert ET.tostring(actual) == ET.tostring(expected)
    assert (actual.find("cac:BillingReference") is not None) == (kind == "return" or (module is createxml and kind == "debit"))
    assert doc.is_advance_payment == int(kind == "advance")
    assert_no_writes(b)


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("purpose", ["invoice", "debug", "compliance"])
@pytest.mark.parametrize("owner,flag", [("company", 0), ("device", 0), ("linked", 1)])
def test_missing_selected_pih_stops_before_parties_without_inventing_genesis(
    party_source, module, doctype, purpose, owner, flag,
):
    b, counter = party_source
    doc = select(b, module, owner, flag)
    holder = getattr(b, owner)
    holder.custom_pih = ""
    tools = PartyXmlTools.from_namespace(vars(module), doctype=doctype, purpose=purpose)
    later = {name: Mock(side_effect=AssertionError("Missing PIH reached later party builder"))
             for name in ("company_data", "customer_data", "payment")}
    tools = replace(tools, **later)
    root = ET.Element("Invoice")
    with pytest.raises(ValidationError) as raised:
        populate_invoice_parties(root, doc, doc.name, "TC", tools=tools, compliance_type="4")
    assert str(raised.value) == MISSING_PREVIOUS_HASH and raised.value.__context__ is None
    assert [ref.find("cbc:ID").text for ref in root.findall("cac:AdditionalDocumentReference")] == ["ICV"]
    assert holder.custom_pih == ""
    counter.assert_called_once()  # The earlier legacy reference step is not undone.
    for operation in later.values():
        operation.assert_not_called()
    assert_no_writes(b)


def trace_tools(purpose, *, clone=False, failed=None):
    calls, roots = [], []
    def step(name):
        def invoke(root, *args, **kwargs):
            calls.append((name, root, args, kwargs))
            if name == failed:
                raise sentinel
            result = object() if clone else root
            roots.append(result)
            if name == "customer_data" and purpose != "compliance":
                args[0].is_return = 1
            return result
        return invoke
    sentinel = RuntimeError("synthetic-builder-failure")
    names = ("reference", "additional_reference", "company_data", "customer_data", "payment")
    tools = PartyXmlTools(purpose, *(step(name) for name in names))
    return tools, calls, roots, sentinel


@pytest.mark.parametrize("purpose", ["invoice", "debug", "compliance"])
@pytest.mark.parametrize("clone", [False, True])
def test_returned_roots_order_exact_arguments_and_late_return_value(purpose, clone):
    tools, calls, roots, _ = trace_tools(purpose, clone=clone)
    root = object()
    doc = Document(is_return=0)
    result = populate_invoice_parties(root, doc, "CALLER-NUMBER", "ISSUER-ABBR", tools=tools, compliance_type="5")
    assert [call[0] for call in calls] == ["reference", "additional_reference", "company_data", "customer_data", "payment"]
    assert [call[1] for call in calls] == [root, *roots[:-1]]
    assert result is roots[-1]
    assert calls[0][2] == ((doc, "CALLER-NUMBER", "5") if purpose == "compliance" else (doc, "CALLER-NUMBER"))
    assert calls[0][3] == ({"debug": True} if purpose == "debug" else {})
    assert calls[1][2] == ("ISSUER-ABBR", doc)
    assert calls[2][2] == calls[3][2] == (doc,)
    assert calls[-1][2] == (doc, "5" if purpose == "compliance" else 1)


@pytest.mark.parametrize("purpose", ["invoice", "debug", "compliance"])
@pytest.mark.parametrize("failed", ["reference", "additional_reference", "company_data", "customer_data", "payment"])
def test_original_failure_stops_later_builders(purpose, failed):
    tools, calls, _, sentinel = trace_tools(purpose, failed=failed)
    with pytest.raises(RuntimeError) as raised:
        populate_invoice_parties(object(), Document(is_return=0), "NUMBER", "ABBR", tools=tools, compliance_type="3")
    assert raised.value is sentinel
    assert [call[0] for call in calls][-1] == failed
    assert len(calls) == ("reference", "additional_reference", "company_data", "customer_data", "payment").index(failed) + 1


def test_compliance_does_not_require_or_read_is_return():
    tools, _, _, _ = trace_tools("compliance")
    populate_invoice_parties(object(), object(), "NUMBER", "ABBR", tools=tools, compliance_type="4")


@pytest.mark.parametrize("doctype", [None, "Company", "sales invoice", False, ["Sales Invoice"]])
def test_unknown_declared_adapter_fails_before_namespace_access(doctype):
    with pytest.raises(ValueError, match="^party_xml_doctype$"):
        PartyXmlTools.from_namespace({}, doctype=doctype)


@pytest.mark.parametrize("purpose", [None, "", "production", True, ["invoice"]])
def test_invalid_purpose_fails_before_namespace_access(purpose):
    with pytest.raises(ValueError, match="^party_xml_purpose$"):
        PartyXmlTools.from_namespace({}, doctype="Sales Invoice", purpose=purpose)


@pytest.mark.parametrize("field", [item.name for item in fields(PartyXmlTools) if item.name != "purpose"])
def test_noncallable_operations_are_refused_before_execution(field):
    inputs = dict(purpose="invoice", **{item.name: Mock() for item in fields(PartyXmlTools) if item.name != "purpose"})
    inputs[field] = None
    with pytest.raises(TypeError, match="^party_xml_tools$"):
        PartyXmlTools(**inputs)
    for value in inputs.values():
        if isinstance(value, Mock):
            value.assert_not_called()


def test_binding_is_frozen_and_retains_no_unrelated_namespace_values():
    functions = {name: Mock() for name in ("doc_reference", "additional_reference", "company_data", "customer_data", "delivery_and_payment_means")}
    secret = object()
    namespace = dict(functions, private_key=secret, invoice=secret)
    tools = PartyXmlTools.from_namespace(namespace, doctype="Sales Invoice")
    namespace["doc_reference"] = Mock()
    again = PartyXmlTools.from_namespace(namespace, doctype="Sales Invoice")
    assert tools.reference is functions["doc_reference"]
    assert again.reference is namespace["doc_reference"]
    assert all(value is not secret for value in vars(tools).values())
    with pytest.raises(FrozenInstanceError):
        tools.purpose = "compliance"
