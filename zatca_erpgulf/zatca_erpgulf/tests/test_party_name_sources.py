"""Frozen-parent name/XML/QR comparisons; no tenant, signer or authority I/O.

Native source shapes are synthetic. Whole-company loading is not an atomic
settings snapshot, taxpayer validation or certificate/issuer binding proof.
"""
import ast
import csv
import hashlib
from pathlib import Path
import re
from types import SimpleNamespace
import unicodedata
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance import field_alias_registry, party_names
from zatca_erpgulf.ksa_compliance.field_compat import get_compat_value
from zatca_erpgulf.zatca_erpgulf import advance_deduction, create_qr, createxml, posxml
from zatca_erpgulf.zatca_erpgulf.create_qr import get_company_arabic_name as real_company_name_reader
from zatca_erpgulf.zatca_erpgulf.invoice_party_xml import PartyXmlTools, populate_invoice_parties
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr, tlv_values
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_party_xml import MODES, party_source
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_xml_core import ADAPTERS, hash_boundary, assert_no_writes
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, ValidationError

REFERENCE = Path(__file__).with_name("fixtures") / "party_name_adapters_a53b85b.py"
REFERENCE_SHA = "9f0c757d55d96bd6bf5b86251e6e9e2e21e2100291835a7e72f3a52df92f7e37"
COMPANY = ("company_name_in_arabic", "custom_company_name_in_arabic", "custom__company_name_in_arabic__")
CUSTOMER = ("customer_name_in_arabic", "custom_customer_name_in_arabic", "zatca_customer_name_in_arabic")
ALIASES = (COMPANY, CUSTOMER)


def previous(module):
    raw = REFERENCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REFERENCE_SHA
    tree = ast.parse(raw)
    sources = ast.literal_eval(tree.body[1].value)
    path = "zatca_erpgulf/zatca_erpgulf/" + module.__name__.rsplit(".", 1)[-1] + ".py"
    namespace = dict(vars(module))
    namespace.update(re=re, unicodedata=unicodedata)
    exec(compile(sources[path], str(REFERENCE), "exec"), namespace)
    return namespace


def company_from(runtime, invoice):
    return runtime.get_doc("Company", invoice.company)


def set_names(doc, fields, selected, *, english):
    for index, field in enumerate(fields):
        setattr(doc, field, "شركة اختبار" if index == selected else "")
    doc.company_name = doc.customer_name = english


def route_qr(doc, route, operation=None):
    module, name = (advance_deduction, "ensure_final_sales_invoice_qr_for_print") if route == "advance" else (create_qr, "create_qr_code")
    doc.doctype = "POS Invoice" if route == "pos" else "Sales Invoice"
    return (operation or getattr(module, name))(doc)


def test_display_order_is_distinct_from_unchanged_schema_first_priority(monkeypatch):
    from zatca_erpgulf.ksa_compliance import field_compat
    for group, fields in zip(("company_arabic_name", "customer_arabic_name"), ALIASES):
        assert party_names.display_aliases(group) == fields
        canonical = field_alias_registry.FIELD_ALIAS_GROUPS[group]["aliases"]
        assert canonical == [fields[1], fields[0], fields[2]]
        assert set(fields) == set(canonical)
        doc = Document(doctype="Company", **{fields[0]: "legacy display", fields[1]: ""})
        monkeypatch.setattr(field_compat, "field_exists", lambda *args: True)
        assert get_compat_value(doc, canonical, "fallback") == ""
        value = party_names.first_available_name(fields, has_field=lambda name: True, read=doc.get)
        assert value == "legacy display"
        immutable = party_names.display_aliases(group)
        assert isinstance(immutable, tuple) and field_alias_registry.FIELD_ALIAS_GROUPS[group]["display_aliases"] == list(immutable)


@pytest.mark.parametrize("module", [createxml, posxml])
@pytest.mark.parametrize("fields", ALIASES)
@pytest.mark.parametrize("values", [
    ("شركة أولى", "شركة ثانية", "شركة ثالثة"), (None, " شركة ثانية ", "شركة ثالثة"),
    ("", "", "شركة ثالثة"), ("   ", "شركة ثانية", "شركة ثالثة"),
    (0, "شركة ثانية", "شركة ثالثة"), (False, "شركة ثانية", "شركة ثالثة"),
    (None, None, None), ("éxample", "عربي", ""), ("  العربية  ", "", ""),
])
@pytest.mark.parametrize("hidden", [None, 0])
def test_xml_alias_selection_matches_parent_value_and_exact_lazy_reads(monkeypatch, module, fields, values, hidden):
    doc = Document(doctype="Company", **dict(zip(fields, values)))
    meta = SimpleNamespace(get_field=Mock(side_effect=lambda key: key != fields[hidden] if hidden is not None else True))
    runtime = SimpleNamespace(get_meta=Mock(return_value=meta))
    monkeypatch.setattr(module, "frappe", runtime)
    old = previous(module)["_first_available_value"]
    expected = old(doc, fields)
    calls = meta.get_field.call_args_list[:]
    meta.get_field.reset_mock()
    assert module._first_available_value(doc, fields) == expected
    assert meta.get_field.call_args_list == calls
    runtime.get_meta.assert_called_with("Company")


@pytest.mark.parametrize("module", [createxml, posxml])
@pytest.mark.parametrize("value", [None, "", 0, False, "Acme Trading LLC", "ACME LTD", "شركة الاختبار",
    "شـركة الاختبار", "شركة A", "École Société", "K Example", "company", "  factory  ",
    "مؤسسة الاختبار", "الاختبار، شركة", "1234", "Co. Ltd.", "🚀 Seller", "مؤسسه", "abc\txyz"])
def test_comparison_normalization_keeps_each_existing_vocabulary_and_unicode_rules(module, value):
    name = "_normalize_name_for_similarity" if module is createxml else "_normalize_name"
    assert getattr(module, name)(value) == previous(module)[name](value)


@pytest.mark.parametrize("module", [createxml, posxml])
@pytest.mark.parametrize("names", [
    ["شركة الاختبار", "Synthetic Seller"], ["ACME LLC", "Acme Limited"],
    ["ACME LTD", "Acme Co."], ["company", "LLC"], ["شـركة الاختبار", "شركة الاختبار"],
    [" A ", "A", " B "], [None, "", "  ", 0, "seller"],
    ["123", "123"], ["École", "Ecole"], ["شركة", "Company"],
])
def test_name_lists_match_parent_without_changing_threshold_or_rendered_text(module, names):
    name = "_deduplicate_names" if module is createxml else "_unique"
    before = list(names)
    assert getattr(module, name)(names) == previous(module)[name](names)
    assert names == before


@pytest.mark.parametrize("module", [createxml, posxml])
def test_existing_comparison_override_remains_bound_at_call_time(monkeypatch, module):
    helper = "_names_are_highly_similar" if module is createxml else "_similar"
    list_helper = "_deduplicate_names" if module is createxml else "_unique"
    compare = Mock(return_value=False)
    monkeypatch.setattr(module, helper, compare)
    assert getattr(module, list_helper)(["same", "same"]) == ["same", "same"]
    compare.assert_called_once_with("same", "same")


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("purpose,code", MODES)
@pytest.mark.parametrize("selected", [0, 1, 2])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_real_reference_party_and_payment_xml_is_byte_identical_with_parent_names(
    party_source, monkeypatch, module, doctype, purpose, code, selected, currency,
):
    b, counter = party_source
    doc = b.sales if module is createxml else b.pos
    doc.currency = currency
    buyer = b.docs["Customer", doc.customer]
    set_names(b.company, COMPANY, selected, english="Synthetic Seller")
    set_names(buyer, CUSTOMER, selected, english="Synthetic Buyer")
    names = ("_get_company_display_names", "_get_customer_display_names") if module is createxml else ("_company_names", "_customer_names")
    old = previous(module)
    tools = PartyXmlTools.from_namespace(vars(module), doctype=doctype, purpose=purpose)
    with monkeypatch.context() as patch:
        for name in names: patch.setattr(module, name, old[name])
        expected = populate_invoice_parties(ET.Element("Invoice"), doc, doc.name, "TC", tools=tools, compliance_type=code)
    reads = b.runtime.get_doc.call_args_list[:]
    b.runtime.get_doc.reset_mock()
    actual = populate_invoice_parties(ET.Element("Invoice"), doc, doc.name, "TC", tools=tools, compliance_type=code)
    assert ET.tostring(actual) == ET.tostring(expected)
    assert b.runtime.get_doc.call_args_list == reads
    supplier = actual.find("cac:AccountingSupplierParty").find("cac:Party")
    assert supplier.find("cac:PartyLegalEntity").find("cbc:RegistrationName").text == "شركة اختبار"
    assert_no_writes(b)


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("selected", [0, 1, 2])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("returned", [False, True])
def test_real_qr_parent_comparison_exposes_only_advance_third_alias_name_delta(local_qr, route, selected, currency, returned):
    doc, runtime, payloads, saver = local_qr
    company = company_from(runtime, doc)
    set_names(company, COMPANY, selected, english="Synthetic Seller")
    doc.currency, doc.is_return = currency, int(returned)
    if returned:
        doc.grand_total, doc.total_taxes_and_charges = -11.5, -1.5
    runtime.db.get_value.side_effect = lambda dt, name, field: company.get(field)
    module = advance_deduction if route == "advance" else create_qr
    name = "ensure_final_sales_invoice_qr_for_print" if route == "advance" else "create_qr_code"
    route_qr(doc, route, previous(module)[name])
    old = tlv_values(payloads[-1])
    doc.ksa_einv_qr = None
    runtime.db.get_value.reset_mock()
    runtime.db.get_value.side_effect = AssertionError("No split name/VAT SQL")
    runtime.get_doc.reset_mock()
    route_qr(doc, route)
    current = tlv_values(payloads[-1])
    assert current[1] == "شركة اختبار" and current[2] == company.tax_id
    assert {key: old[key] for key in (2, 3, 4, 5)} == {key: current[key] for key in (2, 3, 4, 5)}
    if route == "advance" and selected == 2:
        assert old[1] == "Synthetic Seller" and current[1] != old[1]
    else:
        assert current == old
    company_reads = [call for call in runtime.get_doc.call_args_list if call.args and call.args[0] == "Company"]
    assert len(company_reads) == 1
    runtime.db.get_value.assert_not_called()
    runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("language", ["en", "ar"])
@pytest.mark.parametrize("missing", ["name", "vat", "both"])
def test_missing_seller_fields_have_one_translated_display_and_one_english_diagnostic(local_qr, monkeypatch, route, language, missing):
    doc, runtime, payloads, saver = local_qr
    company = company_from(runtime, doc)
    if missing in ("name", "both"):
        set_names(company, COMPANY, -1, english="")
    if missing in ("vat", "both"): company.tax_id = None
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open(newline="") as stream:
        catalog = dict(csv.reader(stream))
    translate = lambda message: catalog.get(message, message) if language == "ar" else message
    for module in (create_qr, advance_deduction): monkeypatch.setattr(module, "_", translate)
    runtime.throw = Mock(side_effect=runtime.throw)
    with pytest.raises(ValidationError) as error: route_qr(doc, route)
    assert str(error.value) == translate(create_qr.SELLER_REVIEW)
    assert (str(error.value) != create_qr.SELLER_REVIEW) == (language == "ar")
    runtime.throw.assert_called_once()
    runtime.log_error.assert_called_once()
    diagnostic = runtime.log_error.call_args.kwargs["message"]
    assert create_qr.SELLER_REVIEW in diagnostic and "qr_seller_details_missing" in diagnostic
    assert ("Missing: seller name" in diagnostic) == (missing in ("name", "both"))
    assert not payloads and doc.ksa_einv_qr is None
    saver.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()
    doc.notify_update.assert_not_called()


@pytest.mark.parametrize("raw", ["  شركة الاختبار  ", "   "])
@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
def test_existing_qr_name_bytes_and_whitespace_policy_are_not_silently_normalized(local_qr, route, raw):
    doc, runtime, payloads, _ = local_qr
    company = company_from(runtime, doc)
    company.company_name_in_arabic = raw
    company.tax_id = " 300000000000003 "
    route_qr(doc, route)
    assert (tlv_values(payloads[-1])[1], tlv_values(payloads[-1])[2]) == (raw, company.tax_id)


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
def test_existing_owned_qr_is_preserved_before_loading_new_seller_details(local_qr, route):
    doc, runtime, payloads, saver = local_qr
    doc.ksa_einv_qr = "/files/PRESERVED.png"
    runtime.get_all.return_value = [dict(name="OLD", file_name="QR-Phase1-old.png", file_url=doc.ksa_einv_qr,
        attached_to_doctype="POS Invoice" if route == "pos" else "Sales Invoice", attached_to_name=doc.name,
        attached_to_field="ksa_einv_qr", is_private=0)]
    runtime.get_doc.side_effect = AssertionError("No fresh seller lookup for an owned QR")
    route_qr(doc, route)
    assert not payloads and doc.ksa_einv_qr == "/files/PRESERVED.png"
    runtime.get_doc.assert_not_called()
    saver.assert_not_called()
    runtime.db.set_value.assert_not_called()


def test_advance_english_fallback_and_ordinary_arabic_requirement_remain_distinct(local_qr):
    doc, runtime, payloads, _ = local_qr
    company = company_from(runtime, doc)
    set_names(company, COMPANY, -1, english="Synthetic Seller")
    route_qr(doc, "advance")
    assert tlv_values(payloads[-1])[1] == "Synthetic Seller"
    doc.ksa_einv_qr = None
    with pytest.raises(ValidationError, match="Company seller details"): route_qr(doc, "sales")


@pytest.mark.parametrize("enabled", [False, True])
def test_phase2_print_gate_refuses_substitution_even_when_integration_is_disabled(local_qr, monkeypatch, enabled):
    doc, runtime, payloads, _ = local_qr
    monkeypatch.setattr(advance_deduction, "resolve_zatca_phase", lambda doc: "Phase-2")
    monkeypatch.setattr(advance_deduction, "is_zatca_invoice_enabled", lambda doc: enabled)
    runtime.get_doc.side_effect = AssertionError("Phase2 gate must precede fresh names")
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc)
    assert not payloads


def test_name_core_has_no_framework_image_signer_network_or_database_dependency():
    tree = ast.parse(Path(party_names.__file__).read_text())
    imports = [n.names[0].name for n in tree.body if isinstance(n, ast.Import)]
    assert imports == ["re", "unicodedata"]
    assert [n.module for n in tree.body if isinstance(n, ast.ImportFrom)] == ["field_alias_registry"]


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("enabled", [0, 1])
@pytest.mark.parametrize("primary,legacy,blocked", [
    ("Phase-2", "Phase-1", True), (None, "Phase-2", True),
    (" Phase-2 ", None, True), ("Phase-1", "Phase-2", False),
    (None, "Phase-1", False), ("", "Phase-2", False),
    ("unknown", "Phase-2", False), (None, None, False),
])
def test_canonical_phase_aliases_protect_qr_without_changing_blank_or_unknown_policy(
    local_qr, monkeypatch, route, enabled, primary, legacy, blocked,
):
    from zatca_erpgulf.ksa_compliance import field_compat
    from zatca_erpgulf.zatca_erpgulf import zatca_runtime
    doc, runtime, payloads, saver = local_qr
    company = company_from(runtime, doc)
    company.doctype = "Company"
    company.custom_zatca_invoice_enabled = enabled
    fields = set(COMPANY)
    for field, value in (("custom_phase_1_or_2", primary), ("phase_1_or_2", legacy)):
        if value is not None:
            setattr(company, field, value)
            fields.add(field)
    meta = SimpleNamespace(get_field=lambda key: key in fields,
        get_image_fields=lambda: [SimpleNamespace(fieldname="ksa_einv_qr")])
    runtime.get_meta.return_value = meta
    monkeypatch.setattr(field_compat, "frappe", runtime)
    for module in (create_qr, advance_deduction):
        monkeypatch.setattr(module, "resolve_zatca_phase", zatca_runtime.resolve_zatca_phase)
    if blocked:
        # Missing seller/money must not force a fallback QR on an explicit Phase2.
        company.tax_id = None
        doc.grand_total = None
    route_qr(doc, route)
    assert bool(payloads) == (not blocked)
    if blocked:
        assert doc.ksa_einv_qr is None
        saver.assert_not_called()
        runtime.db.set_value.assert_not_called()
        runtime.log_error.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("enabled", [0, 1])
@pytest.mark.parametrize("cached_phase,fresh_phase", [("Phase-1", "Phase-2"), ("Phase-2", "Phase-1")])
def test_advance_phase_disagreement_cannot_authorize_a_phase1_substitute(local_qr, monkeypatch, enabled, cached_phase, fresh_phase):
    doc, runtime, payloads, saver = local_qr
    fresh = company_from(runtime, doc)
    fresh.custom_phase_1_or_2 = fresh_phase
    cached = Document(custom_phase_1_or_2=cached_phase, custom_zatca_invoice_enabled=enabled)
    runtime.get_cached_doc.return_value = cached
    runtime.get_doc.reset_mock()
    monkeypatch.setattr(advance_deduction, "resolve_zatca_phase", lambda company: company.custom_phase_1_or_2)
    monkeypatch.setattr(advance_deduction, "is_zatca_invoice_enabled", lambda company: bool(enabled))
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc)
    assert not payloads and doc.ksa_einv_qr is None
    saver.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.log_error.assert_not_called()
    assert runtime.get_doc.call_count == (0 if cached_phase == "Phase-2" else 1)


@pytest.mark.parametrize("values", [
    ("شركة أولى", "شركة ثانية", "شركة ثالثة"), (None, "شركة ثانية", ""),
    ("", "", "شركة ثالثة"), ("   ", "شركة ثانية", ""), (0, "", "شركة ثالثة"),
    (None, None, None), (" العربية ", "", ""),
])
@pytest.mark.parametrize("hidden", [None, 0])
def test_legacy_company_arabic_reader_keeps_result_with_one_loaded_company(local_qr, values, hidden):
    doc, runtime, _, _ = local_qr
    company = company_from(runtime, doc)
    for key, value in zip(COMPANY, values): setattr(company, key, value)
    runtime.get_meta.return_value = SimpleNamespace(get_field=lambda key: key != COMPANY[hidden] if hidden is not None else True)
    runtime.db.get_value.side_effect = lambda dt, name, key: company.get(key)
    expected = previous(create_qr)["get_company_arabic_name"](doc.company)
    runtime.get_doc.reset_mock()
    runtime.db.get_value.reset_mock()
    assert real_company_name_reader(doc.company) == expected
    runtime.get_doc.assert_called_once_with("Company", doc.company)
    runtime.db.get_value.assert_not_called()
