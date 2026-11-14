"""One POS financial preparation, unchanged XML and imported integration hooks.

All source/signing/transport/storage boundaries are simulated. Frozen218
adapter evidence is separate from the original pre-development oracle.
"""

import copy
from dataclasses import FrozenInstanceError
from decimal import Decimal
import hashlib
import inspect
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance.tax_details import get_item_tax_rate
from zatca_erpgulf.zatca_erpgulf import (
    pos_debug_xml, pos_final, pos_financial_composition as composition,
    pos_financial_xml as core, pos_schedule_background, pos_sign, pos_submit__without_xml, posxml,
)
from zatca_erpgulf.zatca_erpgulf.document_tax_xml import DocumentTaxTools, populate_document_tax
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import (
    CASES, fixture_data, input_snapshot,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, isolated, stub_pipeline
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_financial_xml import money, runtime_for
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_vat_accounts import PATTERNS, model


PARENT = Path(__file__).parent / "fixtures" / "pos_financial_c8ae317.py"
PARENT_SHA256 = "43100e52ac8867e814d69835847a09eeb50929b98aa1e5e3b5121eb6cdbc2deb"


def namespace():
    return {**posxml._CANONICAL_POS_BUILDERS, **pos_final._CANONICAL_POS_BUILDERS,
            "DocumentTaxTools": DocumentTaxTools, "populate_document_tax": populate_document_tax}


@pytest.fixture
def parent(monkeypatch):
    raw = PARENT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PARENT_SHA256
    module = ModuleType("frozen_pos_financial_c8ae317")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(raw, str(PARENT), "exec"), vars(module))
    return module


def compare(monkeypatch, parent, doc, records, has_template):
    runtime, _ = runtime_for(monkeypatch, records)
    before = input_snapshot((doc, records))
    results, reads = [], []
    for previous in (True, False):
        runtime.get_doc.reset_mock()
        root = ET.Element("Invoice")
        try:
            if previous:
                for section in ("totals", "lines"):
                    parent.render_pos_financials(root, doc, has_template=has_template,
                        get_doc=runtime.get_doc, read_rate=get_item_tax_rate, section=section)
            else:
                assert composition.populate_pos_financials(root, doc, namespace=namespace(),
                    has_template=has_template) is root
        except (parent.PosFinancialError, core.PosFinancialError) as error:
            results.append((error.code, ET.tostring(root)))
        else:
            results.append((None, ET.tostring(root)))
        reads.append(runtime.get_doc.call_count)
        assert input_snapshot((doc, records)) == before
    assert results[0] == results[1]
    if results[0][0] is None:
        assert reads[0] == reads[1] * 2
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("discount", [False, True])
def test_previous_80_pos_cases_keep_exact_xml_or_rejection(monkeypatch, parent, case, major, currency, discount):
    doc, records, has_template = fixture_data(case, major, currency, discount)
    compare(monkeypatch, parent, doc, records, has_template)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("pattern", PATTERNS)
@pytest.mark.parametrize("discount", [False, True])
@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("show_discount", [0, 1])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("quantity", [1, 3])
def test_previous_640_account_cases_share_one_preparation_with_identical_xml(
    monkeypatch, parent, major, currency, pattern, discount, inclusive, show_discount, returned, quantity,
):
    doc, records = model(major, currency, pattern=pattern, discount=discount,
        inclusive=inclusive, returned=returned, quantity=quantity)
    records["Company", doc.company].custom_submit_line_item_discount_to_zatca = show_discount
    compare(monkeypatch, parent, doc, records, True)


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_prepared_rendering_retains_no_mutable_invoice_or_master_values(monkeypatch, has_template, currency):
    doc, records, _ = fixture_data("item-template-mixed-rates" if has_template else "invoice-template-15",
                                  15, currency, False)
    doc.items[0].qty = 3
    doc.items[0].rate = doc.items[0].price_list_rate = 100 / 3
    runtime, _ = runtime_for(monkeypatch, records)
    packet = core.prepare_pos_financials(doc, has_template=has_template,
        get_doc=runtime.get_doc, read_rate=get_item_tax_rate)
    doc.currency = "USD" if currency == "SAR" else "SAR"
    doc.custom_exemption_reason = "CHANGED"
    doc.base_total_taxes_and_charges = 999
    doc.items[0].qty = 99
    doc.items[0].item_name = doc.items[0].description = "CHANGED"
    for item in doc.items:
        if item.item_tax_template:
            records["Item Tax Template", item.item_tax_template].custom_zatca_tax_category = "Zero Rated"
    runtime.get_doc.reset_mock()
    after_mutation = input_snapshot((doc, records))
    root = ET.Element("Invoice")
    core.append_pos_totals(root, packet)
    core.append_pos_lines(root, packet)
    assert root.findall("cac:TaxTotal")[1].find("cbc:TaxAmount").get("currencyID") == currency
    first = root.find("cac:InvoiceLine")
    assert first.find("cbc:InvoicedQuantity").text == "3"
    assert "CHANGED" not in first.find("cac:Item").find("cbc:Name").text
    assert first.find("cac:Item").find("cac:ClassifiedTaxCategory").find("cbc:ID").text == "S"
    assert money(root, "PayableAmount") == (220 if has_template else 230)
    assert input_snapshot((doc, records)) == after_mutation
    runtime.get_doc.assert_not_called()
    with pytest.raises(FrozenInstanceError): packet.document.currency = "CHANGED"
    with pytest.raises(FrozenInstanceError): packet.lines[0].item.qty = 99
    with pytest.raises(TypeError): packet.breakdown[0]["tax_rate"] = 0
    if has_template:
        with pytest.raises(FrozenInstanceError): packet.lines[0].template.custom_zatca_tax_category = "CHANGED"


@pytest.mark.parametrize("has_template", [False, True])
def test_changed_master_on_a_second_read_cannot_split_totals_and_lines(monkeypatch, has_template):
    doc, records, _ = fixture_data("item-template-mixed-rates" if has_template else "invoice-template-15",
                                  15, "SAR", False)
    runtime, _ = runtime_for(monkeypatch, records)
    reads = {}
    def changing(doctype, name):
        key = doctype, name
        reads[key] = reads.get(key, 0) + 1
        record = copy.deepcopy(records[key])
        if reads[key] > 1 and doctype == "Item Tax Template":
            record.custom_zatca_tax_category = "Zero Rated"
            record.custom_exemption_reason_code = "VATEX-SA-32"
            record.taxes[0].tax_rate = 0
        if reads[key] > 1 and doctype == "Company":
            record.custom_submit_line_item_discount_to_zatca = 1
        return record
    runtime.get_doc.side_effect = changing
    root = ET.Element("Invoice")
    composition.populate_pos_financials(root, doc, namespace=namespace(), has_template=has_template)
    assert max(reads.values()) == 1
    assert money(root, "PayableAmount") == (220 if has_template else 230)
    assert not any(line.find("cac:Price").find("cbc:BaseQuantity") is not None
                   for line in root.findall("cac:InvoiceLine"))


@pytest.mark.parametrize("has_template", [False, True])
def test_a_failed_second_line_leaves_caller_root_intact_with_one_message(monkeypatch, has_template):
    doc, records, _ = fixture_data("item-template-mixed-rates" if has_template else "invoice-template-15",
                                  15, "SAR", False)
    runtime, notices = runtime_for(monkeypatch, records, language="ar")
    original = core.lines._append_sales_invoice_line
    calls = []
    error = core.PosFinancialError("invalid_source", core.MISSING)
    def failing(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2: raise error
        return original(*args, **kwargs)
    monkeypatch.setattr(core.lines, "_append_sales_invoice_line", failing)
    root = ET.Element("Invoice")
    ET.SubElement(root, "Unrelated").text = "KEEP"
    before = ET.tostring(root), input_snapshot((doc, records))
    with pytest.raises(core.PosFinancialError) as caught:
        composition.populate_pos_financials(root, doc, namespace=namespace(), has_template=has_template)
    assert caught.value is error
    assert (ET.tostring(root), input_snapshot((doc, records))) == before
    assert len(notices) == 1
    runtime.log_error.assert_called_once()


@pytest.mark.parametrize("field", ["currency", "item_name", "description", "reason"])
def test_mutable_presentation_inputs_fail_before_any_financial_append(monkeypatch, field):
    doc, records, _ = fixture_data("invoice-template-zero" if field == "reason" else "invoice-template-15",
                                  15, "SAR", False)
    if field == "currency": doc.currency = {"invalid": "currency"}
    elif field == "reason": doc.custom_exemption_reason_code = ["VATEX-SA-32"]
    else: setattr(doc.items[0], field, {"invalid": "presentation"})
    runtime, notices = runtime_for(monkeypatch, records)
    root = ET.Element("Invoice")
    with pytest.raises(core.PosFinancialError) as caught:
        composition.populate_pos_financials(root, doc, namespace=namespace(), has_template=False)
    assert caught.value.code == ("classification" if field == "reason" else "invalid_source")
    assert len(root) == 0 and len(notices) == 1
    runtime.log_error.assert_called_once()


@pytest.mark.parametrize("flag", [False, True, None, 0, 1, "0", "1"])
@pytest.mark.parametrize("clone", [False, True])
@pytest.mark.parametrize("use_item_result", [False, True])
def test_imported_builders_keep_selection_order_and_root_contract(flag, clone, use_item_result):
    ns, calls, roots = {}, [], []
    for name in ("add_document_level_discount_with_tax", "add_document_level_discount_with_tax_template",
                 "tax_data", "tax_data_with_template", "item_data", "item_data_with_template"):
        def builder(root, doc, name=name):
            calls.append((name, root, doc))
            result = ET.Element(name) if clone else root
            roots.append(result)
            return result
        ns[name] = builder
    root, doc = ET.Element("Invoice"), Document()
    result = composition.populate_pos_financials(root, doc, namespace=ns,
        has_template=flag, use_item_result=use_item_result)
    assert [entry[0] for entry in calls] == (["add_document_level_discount_with_tax_template", "tax_data_with_template", "item_data_with_template"]
                                           if flag else ["add_document_level_discount_with_tax", "tax_data", "item_data"])
    assert calls[0][1] is root and calls[1][1] is roots[0] and calls[2][1] is roots[1]
    assert result is roots[2 if use_item_result else 1]


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_imported_failure_preserves_exception_and_stops_later_builders(stage):
    ns, calls = {}, []
    sentinel = ValueError("custom integration failure")
    for index, name in enumerate(("add_document_level_discount_with_tax", "tax_data", "item_data")):
        def builder(root, doc, index=index):
            calls.append(index)
            if index == stage: raise sentinel
            return root
        ns[name] = builder
    with pytest.raises(ValueError) as caught:
        composition.populate_pos_financials(ET.Element("Invoice"), Document(), namespace=ns, has_template=False)
    assert caught.value is sentinel and calls == list(range(stage + 1))


@pytest.mark.parametrize("binding", ["runtime", "translate", "rate"])
def test_distinct_adapter_bindings_keep_each_public_dependency(monkeypatch, binding):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    runtime, _ = runtime_for(monkeypatch, records)
    if binding == "runtime": monkeypatch.setattr(pos_final, "frappe", SimpleNamespace(**vars(runtime)))
    elif binding == "translate": monkeypatch.setattr(pos_final, "_", lambda message: message)
    else: monkeypatch.setattr(pos_final, "get_item_tax_rate", lambda *args, **kwargs: get_item_tax_rate(*args, **kwargs))
    prepare = Mock(wraps=core.prepare_pos_financials)
    monkeypatch.setattr(core, "prepare_pos_financials", prepare)
    root = composition.populate_pos_financials(ET.Element("Invoice"), doc,
        namespace=namespace(), has_template=False)
    assert money(root, "PayableAmount") == 230
    assert prepare.call_count == 2


@pytest.mark.parametrize("custom", ["factory", "composer", "factory-method"])
def test_imported_factory_and_composer_hooks_are_invoked(monkeypatch, custom):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    runtime_for(monkeypatch, records)
    ns, calls = namespace(), []
    original_factory = DocumentTaxTools.from_namespace
    def factory(*args, **kwargs):
        calls.append("factory")
        return original_factory(*args, **kwargs)
    def compose(*args, **kwargs):
        calls.append("composer")
        return populate_document_tax(*args, **kwargs)
    if custom == "factory": ns["DocumentTaxTools"] = SimpleNamespace(from_namespace=factory)
    elif custom == "composer": ns["populate_document_tax"] = compose
    else: monkeypatch.setattr(DocumentTaxTools, "from_namespace", classmethod(lambda cls, *args, **kwargs: factory(*args, **kwargs)))
    root = composition.populate_pos_financials(ET.Element("Invoice"), doc, namespace=ns, has_template=False)
    assert money(root, "PayableAmount") == 230
    assert calls == (["composer"] if custom == "composer" else ["factory"])


ROUTES = [(pos_sign, "zatca_call"), (pos_sign, "zatca_call_compliance"),
    (pos_schedule_background, "zatca_call_pos_without_xml_background"),
    (pos_submit__without_xml, "zatca_call_pos_without_xml"), (pos_debug_xml, "debug_call")]


@pytest.mark.parametrize("module,method", ROUTES)
@pytest.mark.parametrize("has_template", [False, True])
def test_real_generation_routes_prepare_once_before_mocked_signing(isolated, monkeypatch, module, method, has_template):
    invoice, company, _, runtime, files = isolated
    financial_doc, records, _ = fixture_data("item-template-mixed-rates" if has_template else "invoice-template-15",
                                            15, "SAR", False)
    for key, value in vars(financial_doc).items():
        if key not in {"doctype", "name", "company", "save", "db_set"}: setattr(invoice, key, value)
    invoice.doctype = "POS Invoice"
    records["Company", invoice.company] = company
    original_get_doc = runtime.get_doc.side_effect
    runtime.get_doc.side_effect = lambda dt, name=None: records[dt, name] if isinstance(name, str) and (dt, name) in records else original_get_doc(dt, name)
    translate = lambda message: message
    for adapter in (posxml, pos_final, module):
        monkeypatch.setattr(adapter, "frappe", runtime)
        monkeypatch.setattr(adapter, "_", translate)
    stub_pipeline(monkeypatch, module, invoice)
    for name, builder in {**posxml._CANONICAL_POS_BUILDERS, **pos_final._CANONICAL_POS_BUILDERS}.items():
        if hasattr(module, name): monkeypatch.setattr(module, name, builder)
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    roots = []
    def structure(root):
        roots.append(copy.deepcopy(root))
        return "<Invoice/>"
    monkeypatch.setattr(module, "xml_structuring", structure)
    signer = Mock(return_value=SimpleNamespace(encoded_hash="HASH", qr_payload="QR", xml="<Invoice/>"))
    monkeypatch.setattr(module, "sign_invoice_xml", signer)
    for name in ("attach_qr_image", "reporting_api", "reporting_api_pos_without_xml", "clearance_api", "compliance_api_call"):
        if hasattr(module, name): monkeypatch.setattr(module, name, Mock(return_value={"status": "PASS"}))
    monkeypatch.setattr(module, "structuring_signedxml", Mock(return_value="UNUSED.xml"), raising=False)
    if method == "debug_call":
        monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
        monkeypatch.setattr(module, "resolve_zatca_phase", lambda *args: "Phase-1")
    prepare = Mock(wraps=core.prepare_pos_financials)
    monkeypatch.setattr(core, "prepare_pos_financials", prepare)
    kwargs = dict(any_item_has_tax_template=has_template)
    if method == "zatca_call_compliance": kwargs.update(company_abbr=company.abbr, compliance_type="1")
    result = inspect.unwrap(getattr(module, method))(invoice.name, **kwargs)
    assert prepare.call_count == 1
    signer.assert_called_once()
    assert signer.call_args.args[2] is invoice
    assert prepare.call_args.args[0] is invoice
    assert len(roots) == 1 and money(roots[0], "PayableAmount") == (220 if has_template else 230)
    if method == "debug_call": assert result["status"] == "success" and len(files) == 1
    else: assert files == []
    invoice.save.assert_not_called()
    invoice.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
