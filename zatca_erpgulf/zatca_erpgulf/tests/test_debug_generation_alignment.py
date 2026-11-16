"""Compare real Debug/type/item decisions with frozen ordinary generators.

No tenant, genuine signer, image/SDK acceptance or authority service is used.
Only mocked prepared XML and private test File observations cross boundaries.
"""
import ast
import copy
import csv
import hashlib
import inspect
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    createxml, posxml, debug_xml, pos_debug_xml, sign_invoice, pos_sign,
    create_xml_final_part as items,
)
from zatca_erpgulf.zatca_erpgulf.compliance_types import compliance_document_type
from zatca_erpgulf.zatca_erpgulf.invoice_type_xml import TYPE_REVIEW, populate_invoice_type
from zatca_erpgulf.zatca_erpgulf.sales_item_xml import populate_sales_items
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import (
    Document, isolated, stub_pipeline, prepare_debug_messages,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_sales_item_builder_parity import source as sales_source
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_item_builder_parity import advance_source, prepare

REFERENCE = Path(__file__).with_name("fixtures") / "debug_generation_8905036.py"
REFERENCE_SHA = "8d9443ff4580c5939037ab026e5cd1132c025425483f3f1cfc018ec31a49efe2"


def previous(module, name):
    raw = REFERENCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REFERENCE_SHA
    mapping = ast.literal_eval(ast.parse(raw).body[1].value)
    path = "zatca_erpgulf/zatca_erpgulf/" + module.__name__.rsplit(".", 1)[-1] + ".py"
    namespace = dict(vars(module))
    exec(compile(mapping[path], str(REFERENCE), "exec"), namespace)
    return namespace[name]


def bind_types(monkeypatch, module, customer):
    adapter = posxml if module in (pos_debug_xml, pos_sign) else createxml
    for name in ("invoice_typecode_simplified", "invoice_typecode_standard", "invoice_typecode_compliance", "invoice_typecode_advance_payment"):
        if hasattr(adapter, name): monkeypatch.setattr(module, name, getattr(adapter, name))
    reader = lambda group, doc, default=None: customer.b2c if group == "customer_b2c" else default
    monkeypatch.setattr(module, "get_alias_value", reader)
    monkeypatch.setattr(adapter, "get_alias_value", reader)
    if adapter is createxml: monkeypatch.setattr(adapter, "_is_export_invoice", lambda *args: False)
    if hasattr(module, "is_advance_payment_invoice"):
        monkeypatch.setattr(module, "is_advance_payment_invoice", lambda doc: doc.get("test_advance", False))


def capture_xml(monkeypatch, module):
    # Each old/current invocation owns a new root; a fixed Mock return value
    # would append a second type node to the previous invocation's source.
    _, uuid, doc = module.salesinvoice_data.return_value
    module.salesinvoice_data.side_effect = lambda root, *args, **kwargs: (root, uuid, doc)
    captured = []
    def capture(root):
        captured.append(copy.deepcopy(root))
        return "<Invoice>mock unsigned content</Invoice>"
    monkeypatch.setattr(module, "xml_structuring", capture)
    return captured


def type_pair(root):
    node = root.find("cbc:InvoiceTypeCode")
    return node.get("name"), node.text


def no_source_writes(invoice, app):
    invoice.save.assert_not_called()
    invoice.db_set.assert_not_called()
    app.db.set_value.assert_not_called()
    app.db.commit.assert_not_called()


@pytest.mark.parametrize("method", ["Background", "Live", "Batches"])
@pytest.mark.parametrize("unique", [False, True])
@pytest.mark.parametrize("code", ["0", "1", "2", "3", "4", "5", "6"])
@pytest.mark.parametrize("b2c", [0, 1])
@pytest.mark.parametrize("kind", ["invoice", "credit", "debit", "advance"])
def test_sales_debug_classification_uses_customer_or_explicit_sample_instead_of_schedule(
    isolated, monkeypatch, method, unique, code, b2c, kind,
):
    doc, company, customer, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, debug_xml)
    customer.b2c = b2c
    doc.is_return, doc.is_debit_note, doc.test_advance = int(kind == "credit"), int(kind == "debit"), kind == "advance"
    doc.custom_unique_id = "OFFLINE-ID" if unique else None
    company.custom_send_invoice_to_zatca = method
    bind_types(monkeypatch, debug_xml, customer)
    monkeypatch.setattr(debug_xml, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    # Keep amount work mocked: this matrix proves actual type-builder behavior.
    for name in ("item_data_advance_invoice", "item_data_with_template_advance_invoice"):
        monkeypatch.setattr(debug_xml, name, lambda root, doc: root)
    captured = capture_xml(monkeypatch, debug_xml)
    before = (doc.custom_uuid, doc.custom_zatca_icv, doc.custom_zatca_status, doc.custom_zatca_full_response)
    old_result = previous(debug_xml, "_debug_call")(doc.name, compliance_type=code)
    assert old_result["status"] == "success", old_result
    old_pair = type_pair(captured[-1])
    current_result = inspect.unwrap(debug_xml.debug_call)(doc.name, compliance_type=code)
    assert current_result["status"] == "success", current_result
    actual = type_pair(captured[-1])
    if code == "0":
        expected_code = {"invoice": "388", "credit": "381", "debit": "383", "advance": "386"}[kind]
        assert actual == (("02" if b2c else "01") + "00000", expected_code)
    else:
        sample = compliance_document_type(code)
        assert actual == (sample.type_name, sample.document_code)
    forced = unique or method == "Background"
    if not forced or (code == "0" and kind == "advance"):
        assert actual == old_pair
    else:
        # The frozen Debug ignored explicit samples/B2B in these branches.
        assert old_pair[0].startswith("02")
    assert len(files) == 2 and all(file["is_private"] == 1 for file in files)
    assert before == (doc.custom_uuid, doc.custom_zatca_icv, doc.custom_zatca_status, doc.custom_zatca_full_response)
    debug_xml.compliance_api_call.assert_not_called()
    no_source_writes(doc, app)


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("b2c", [0, 1])
@pytest.mark.parametrize("kind", ["invoice", "credit", "debit", "advance"])
def test_ordinary_generator_type_and_route_match_complete_frozen_parent(isolated, monkeypatch, module, b2c, kind):
    doc, company, customer, app, _ = isolated
    doc.doctype = "POS Invoice" if module is pos_sign else "Sales Invoice"
    stub_pipeline(monkeypatch, module, doc)
    customer.b2c = b2c
    doc.is_return, doc.is_debit_note, doc.test_advance = int(kind == "credit"), int(kind == "debit"), kind == "advance"
    bind_types(monkeypatch, module, customer)
    for name in ("item_data_advance_invoice", "item_data_with_template_advance_invoice"):
        if hasattr(module, name): monkeypatch.setattr(module, name, lambda root, doc: root)
    captured = capture_xml(monkeypatch, module)
    monkeypatch.setattr(module, "structuring_signedxml", lambda *args: "not-a-real-path.xml")
    report, clear = Mock(), Mock()
    monkeypatch.setattr(module, "reporting_api", report)
    monkeypatch.setattr(module, "clearance_api", clear)
    monkeypatch.setattr(module, "attach_qr_image", Mock())
    previous(module, "zatca_call")(doc.name)
    expected = ET.tostring(captured[-1]); old_calls = (report.call_args_list[:], clear.call_args_list[:])
    report.reset_mock(); clear.reset_mock()
    inspect.unwrap(module.zatca_call)(doc.name)
    assert ET.tostring(captured[-1]) == expected
    assert (report.call_args_list, clear.call_args_list) == old_calls
    no_source_writes(doc, app)


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
@pytest.mark.parametrize("value", [None, "", True, False, "7", -1, 0.0, "PRIVATE-SELECTOR", {"private": "value"}])
@pytest.mark.parametrize("language", ["en", "ar"])
def test_bad_debug_selector_stops_before_identity_or_any_xml_and_has_one_canonical_result(isolated, monkeypatch, module, value, language):
    doc, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    app.local.lang = language
    result = inspect.unwrap(module.debug_call)(doc.name, compliance_type=value)
    assert result == {"status": "error", "message": "Debug XML generation failed. See technical details.",
        "technical_details": TYPE_REVIEW, "notices": [TYPE_REVIEW]}
    assert "PRIVATE" not in str(result)
    app.log_error.assert_called_once()
    assert TYPE_REVIEW in app.log_error.call_args.args[0]
    module.salesinvoice_data.assert_not_called()
    module.xml_structuring.assert_not_called()
    module.compliance_api_call.assert_not_called()
    assert not files and app.flags == {"mute_messages": False}
    no_source_writes(doc, app)


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
@pytest.mark.parametrize("selector,expected", [(0, "0"), (" 0 ", "0"), (2, "2"), (" 6 ", "6")])
def test_debug_numeric_and_trimmed_selectors_use_the_same_validated_contract(isolated, monkeypatch, module, selector, expected):
    doc, _, _, _, _ = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    result = inspect.unwrap(module.debug_call)(doc.name, compliance_type=selector)
    assert result["status"] == "success", result
    if expected == "0": module.invoice_typecode_simplified.assert_called_once()
    else: assert module.invoice_typecode_compliance.call_args.args[1] == expected


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("legacy_installed", [False, True])
@pytest.mark.parametrize("copy_present", [False, True])
@pytest.mark.parametrize("schema", [False, True])
@pytest.mark.parametrize("allocation", [None, 0, -11.5, 11.5])
def test_primary_item_selection_matches_frozen_parent_including_direct_legacy_priority(
    isolated, monkeypatch, has_template, legacy_installed, copy_present, schema, allocation,
):
    doc, _, _, app, _ = isolated
    stub_pipeline(monkeypatch, sign_invoice, doc)
    doc.items = [Document(item_tax_template="ITEM-VAT" if has_template else "")]
    monkeypatch.setattr(sign_invoice, "get_alias_value", lambda *args: 1)
    monkeypatch.setattr(sign_invoice, "is_advance_payment_invoice", lambda doc: False)
    monkeypatch.setattr(sign_invoice, "supports_advance_deduction_schema", lambda doc: schema)
    app.get_installed_apps.return_value = ["claudion4saudi"] if legacy_installed else []
    doc.custom_advances_copy = [Document(reference_name="OLD")] if copy_present else []
    doc.custom_zatca_advance_deduction_details = [Document(advance_invoice="DIRECT", allocated_total_amount=allocation)]
    calls = []
    for name in ("item_data", "item_data_with_template", "item_data_advance_invoice", "item_data_with_template_advance_invoice"):
        monkeypatch.setattr(sign_invoice, name, lambda root, doc, _name=name: calls.append(_name) or root)
    for name in ("add_document_level_discount_with_tax_template", "tax_data_with_template"):
        monkeypatch.setattr(sign_invoice, name, lambda root, doc: root)
    class Captured(BaseException): pass
    monkeypatch.setattr(sign_invoice, "xml_structuring", Mock(side_effect=Captured))
    with pytest.raises(Captured): previous(sign_invoice, "zatca_call")(doc.name, any_item_has_tax_template=has_template)
    expected = calls[:]
    calls.clear()
    with pytest.raises(Captured): inspect.unwrap(sign_invoice.zatca_call)(doc.name, any_item_has_tax_template=has_template)
    assert calls == expected and len(calls) == 1
    no_source_writes(doc, app)


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("erp_major", [15, 16])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("route", ["none", "direct", "legacy", "both"])
def test_actual_item_xml_and_direct_or_old_advance_references_keep_bytes_and_money(
    advance_source, has_template, currency, erp_major, returned, route,
):
    s = advance_source
    doc = prepare(s, route=route, currency=currency, erp_major=erp_major,
        quantity=-3 if returned else 3, company_field=True)
    namespace = dict(vars(items), frappe=s.runtime, supports_advance_deduction_schema=lambda doc: True)
    old_advance = route in ("legacy", "both")
    old_name = ("item_data_with_template_advance_invoice" if has_template else "item_data_advance_invoice") if old_advance else ("item_data_with_template" if has_template else "item_data")
    before = [(row.qty, row.net_amount, row.base_net_amount) for row in doc.items]
    old_root = namespace[old_name](ET.Element("Invoice"), doc)
    live_name = ("item_data_with_template_advance_invoice" if has_template else "item_data_advance_invoice") if route != "none" else ("item_data_with_template" if has_template else "item_data")
    ordinary = namespace[live_name](ET.Element("Invoice"), doc)
    current = populate_sales_items(ET.Element("Invoice"), doc, namespace=namespace, has_template=has_template)
    assert ET.tostring(current) == ET.tostring(ordinary) == ET.tostring(old_root)
    if route in ("direct", "both"):
        ref = current.findall("cac:InvoiceLine")[-1].find("cac:DocumentReference")
        assert ref.find("cbc:DocumentTypeCode").text == "386"
        assert ref.find("cbc:ID").text == s.advance.name
    assert before == [(row.qty, row.net_amount, row.base_net_amount) for row in doc.items]
    doc.save.assert_not_called(); doc.db_set.assert_not_called()
    s.runtime.db.commit.assert_not_called(); s.runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("step", ["sample", "advance", "simplified", "standard"])
def test_type_composition_propagates_replacement_roots_and_current_overrides(step):
    original, replacement = ET.Element("Original"), ET.Element("Replacement")
    leaf = Mock(return_value=replacement)
    source = Document(is_return=0)
    namespace = {"get_alias_value": Mock(return_value=1 if step == "simplified" else 0),
        "is_advance_payment_invoice": Mock(return_value=step == "advance"),
        "invoice_typecode_" + step if step != "sample" else "invoice_typecode_compliance": leaf}
    if step == "advance": namespace["invoice_typecode_advance_payment"] = namespace.pop("invoice_typecode_advance")
    result = populate_invoice_type(original, source, Document(), namespace=namespace,
        doctype="Sales Invoice", compliance_type="2" if step == "sample" else "0")
    assert result is replacement
    leaf.assert_called_once_with(original, "2" if step == "sample" else source)
    if step == "sample":
        namespace["is_advance_payment_invoice"].assert_not_called()
        namespace["get_alias_value"].assert_not_called()


def test_debug_does_not_observe_submission_schedule_or_bypass_for_type_selection(isolated, monkeypatch):
    doc, company, customer, app, _ = isolated
    prepare_debug_messages(isolated, monkeypatch, debug_xml)
    class LocalCompany(Document):
        @property
        def custom_send_invoice_to_zatca(self): raise AssertionError("Debug read live schedule")
    saved = LocalCompany(**{key: value for key, value in vars(company).items() if key != "custom_send_invoice_to_zatca"})
    loader = app.get_doc.side_effect
    app.get_doc.side_effect = lambda dt, name=None: saved if dt == "Company" else loader(dt, name)
    monkeypatch.setattr(debug_xml, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    assert inspect.unwrap(debug_xml.debug_call)(doc.name, bypass_background_check=True)["status"] == "success"


def test_type_review_has_arabic_display_without_changing_english_error():
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open(newline="") as stream:
        catalog = dict(csv.reader(stream))
    assert catalog[TYPE_REVIEW] != TYPE_REVIEW and "XML" in catalog[TYPE_REVIEW]


@pytest.mark.parametrize("code", ["0", "1", "2", "3", "4", "5", "6"])
@pytest.mark.parametrize("b2c", [0, 1])
@pytest.mark.parametrize("phase", ["Phase-1", "Phase-2"])
@pytest.mark.parametrize("method", ["Background", "Batches"])
@pytest.mark.parametrize("returned", [False, True])
def test_pos_debug_valid_types_and_b2c_rejection_match_complete_frozen_parent(
    isolated, monkeypatch, code, b2c, phase, method, returned,
):
    doc, company, customer, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    customer.b2c, doc.is_return = b2c, int(returned)
    company.custom_send_invoice_to_zatca = method
    bind_types(monkeypatch, pos_debug_xml, customer)
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: phase)
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    captured = capture_xml(monkeypatch, pos_debug_xml)
    old = previous(pos_debug_xml, "_debug_call")(doc.name, compliance_type=code)
    current = inspect.unwrap(pos_debug_xml.debug_call)(doc.name, compliance_type=code)
    assert old["status"] == current["status"]
    if code == "0" and not b2c:
        assert old == current and current["status"] == "error"
        assert not captured and not files
    else:
        assert current["status"] == "success", current
        assert len(captured) == 2 and ET.tostring(captured[0]) == ET.tostring(captured[1])
        if code == "0": assert type_pair(captured[1]) == ("0200000", "381" if returned else "388")
        else:
            sample = compliance_document_type(code)
            assert type_pair(captured[1]) == (sample.type_name, sample.document_code)
        assert len(files) == 2 and all(file["is_private"] == 1 for file in files)
    no_source_writes(doc, app)
    pos_debug_xml.compliance_api_call.assert_not_called()
