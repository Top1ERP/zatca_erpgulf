"""Native currency ownership and financial XML simulations; no site or HTTP.

Frozen220 comparisons are separate from the original pre-development oracle.
The 16 metadata is pinned-source evidence, not an installed16 runtime.
"""
import copy
from dataclasses import FrozenInstanceError
from decimal import Decimal
import hashlib
import inspect
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance.invoice_currency import InvoiceCurrencyError, bind_invoice_currency
from zatca_erpgulf.ksa_compliance.item_vat_selection import FIELD
from zatca_erpgulf.zatca_erpgulf import (
    create_xml_final_part as sales, template_vat_source as source,
    xml_tax_data, createxml, sign_invoice, debug_xml,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import isolated, stub_pipeline
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import fixture_data, input_snapshot
from zatca_erpgulf.zatca_erpgulf.tests.test_declared_vat_xml import declare, emit, setup
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_financial_xml import money
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_vat_accounts import model


FIXTURES = Path(__file__).with_name("fixtures")
FROZEN = {
    "currency_context_9223294.py": "140dcc7d32d8127945d5352e30354d9e8379563f2f47ca518006c6e520548db1",
    "currency_builders_9223294.py": "709501e27ad910f8d217535a8b92c75392c8393adcaf1e4910baade5d2850713",
}


def no_helper(doc, state="absent"):
    if state == "absent": vars(doc).pop("company_currency", None)
    else: doc.company_currency = None if state == "null" else ""


def financial_model(major, mode, *, discount=False, returned=False, inclusive=False):
    if mode == "invoice":
        doc, records, _ = fixture_data("invoice-template-15", major, "USD", discount)
        if returned:
            doc.is_return = 1
            for item in doc.items:
                for key in ("qty", "amount", "base_amount", "net_amount", "base_net_amount"):
                    setattr(item, key, -getattr(item, key))
            for key in ("net_total", "base_net_total", "total_taxes_and_charges",
                        "base_total_taxes_and_charges", "grand_total", "rounded_total"):
                setattr(doc, key, -getattr(doc, key))
        doc.taxes[0].included_in_print_rate = int(inclusive)
    else:
        doc, records = model(major, "USD", discount=discount, returned=returned,
                             inclusive=inclusive, quantity=3)
        doc.doctype = "Sales Invoice"
        if mode in ("selected", "companion-first"):
            declare(doc, records)
            if mode == "companion-first":
                template = records["Item Tax Template", doc.items[0].item_tax_template]
                delattr(template, FIELD)
                template.taxes = [template.taxes[-1]]
    records["Company", doc.company].default_currency = "SAR"
    return doc, records


def generate(doc, family, mode):
    if family in ("sales", "nominal") and mode != "invoice":
        return emit(doc, family)
    root = ET.Element("Invoice")
    if family == "advance":
        operation = sales.item_data_advance_invoice if mode == "invoice" else sales.item_data_with_template_advance_invoice
        operation(root, doc)
    elif family == "nominal":
        sales.tax_data_nominal(root, doc)
        sales.item_data(root, doc)
    else:
        from zatca_erpgulf.zatca_erpgulf import xml_tax_data
        xml_tax_data.tax_data(root, doc)
        sales.item_data(root, doc)
    return root


def old_builders():
    namespaces = {}
    for filename, expected in FROZEN.items():
        raw = (FIXTURES / filename).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        if filename.startswith("currency_context"):
            module = ModuleType("frozen_currency_context_9223294")
            exec(compile(raw, filename, "exec"), vars(module))
            namespaces["context"] = module
        else:
            space = dict(vars(sales), DeclaredVatContext=namespaces["context"].DeclaredVatContext)
            exec(compile(raw, filename, "exec"), space)
            namespaces["builders"] = space
    return namespaces


@pytest.mark.parametrize("document", ["SAR", "USD", "EUR"])
@pytest.mark.parametrize("override", [None, "", "SAR"])
def test_pure_binding_has_one_accounting_owner_and_no_fx(document, override):
    result = bind_invoice_currency(document, "SAR", invoice_override=override)
    assert result.document == document and result.accounting == "SAR"
    assert result.uses_base_amounts is (document == "SAR")
    with pytest.raises(FrozenInstanceError): result.accounting = "USD"


@pytest.mark.parametrize("document,company,override,code", [
    (None, "SAR", None, "invoice_currency_missing_or_invalid"),
    ("", "SAR", None, "invoice_currency_missing_or_invalid"),
    (" USD", "SAR", None, "invoice_currency_missing_or_invalid"),
    (True, "SAR", None, "invoice_currency_missing_or_invalid"),
    ("USD", None, "SAR", "invoice_currency_missing_or_invalid"),
    ("USD", "", "SAR", "invoice_currency_missing_or_invalid"),
    ("USD", " SAR ", None, "invoice_currency_missing_or_invalid"),
    ("USD", "SAR", "USD", "invoice_currency_override_conflict"),
    ("USD", "SAR", False, "invoice_currency_override_conflict"),
    ("USD", "SAR", 0, "invoice_currency_override_conflict"),
    ("USD", "SAR", " SAR ", "invoice_currency_override_conflict"),
    ("USD", "USD", None, "invoice_accounting_currency_unsupported"),
    ("SAR", "USD", "USD", "invoice_accounting_currency_unsupported"),
    ("USD", "USD", "SAR", "invoice_currency_override_conflict"),
])
def test_invalid_or_conflicting_declarations_never_infer_a_currency(document, company, override, code):
    with pytest.raises(InvoiceCurrencyError, match="^" + code + "$"):
        bind_invoice_currency(document, company, invoice_override=override)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("mode", ["invoice", "legacy-item", "selected", "companion-first"])
@pytest.mark.parametrize("family", ["sales", "nominal", "advance"])
@pytest.mark.parametrize("state", ["absent", "null", "blank"])
@pytest.mark.parametrize("discount", [False, True])
@pytest.mark.parametrize("returned", [False, True])
def test_native_missing_helper_matches_explicit_bound_xml_without_mutation(
    monkeypatch, major, mode, family, state, discount, returned,
):
    doc, records = financial_model(major, mode, discount=discount, returned=returned, inclusive=True)
    doc.custom_zatca_nominal_invoice = int(family == "nominal")
    runtime, notices = setup(monkeypatch, records)
    expected = ET.tostring(generate(doc, family, mode))
    no_helper(doc, state)
    before = input_snapshot((doc, records))
    result = generate(doc, family, mode)
    assert ET.tostring(result) == expected
    for line, item in zip(result.findall("cac:InvoiceLine"), doc.items):
        assert Decimal(line.find("cbc:LineExtensionAmount").text) == abs(Decimal(str(item.net_amount)))
        unit = Decimal(line.find("cac:Price").find("cbc:PriceAmount").text)
        assert (unit * abs(Decimal(str(item.qty)))).quantize(Decimal(".01")) == abs(Decimal(str(item.net_amount)))
    assert input_snapshot((doc, records)) == before
    assert not notices
    runtime.log_error.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("mode", ["invoice", "legacy-item"])
@pytest.mark.parametrize("family", ["sales", "nominal", "advance"])
def test_frozen_parent_monetary_delta_is_explicit(monkeypatch, major, mode, family):
    doc, records = financial_model(major, mode)
    doc.custom_zatca_nominal_invoice = int(family == "nominal")
    setup(monkeypatch, records)
    no_helper(doc)
    prior = old_builders()
    namespace = prior["builders"]
    old = ET.Element("Invoice")
    if family == "advance":
        namespace["item_data_advance_invoice" if mode == "invoice" else "item_data_with_template_advance_invoice"](old, doc)
    else:
        if family == "nominal":
            breakdown = namespace["_nominal_breakdown_without_template" if mode == "invoice" else "_nominal_breakdown_with_template"](doc)
            taxable, vat = sales._append_nominal_tax_totals(old, doc, breakdown)
            sales._build_nominal_legal_monetary_total(old, doc, taxable, vat)
        namespace["_append_sales_invoice_item_lines"](old, doc, has_template=mode != "invoice")
    new = generate(doc, family, mode)
    old_net = sum(Decimal(node.find("cbc:LineExtensionAmount").text) for node in old.findall("cac:InvoiceLine"))
    new_net = sum(Decimal(node.find("cbc:LineExtensionAmount").text) for node in new.findall("cac:InvoiceLine"))
    assert old_net == Decimal("750.00") and new_net == Decimal("200.00")
    assert doc.net_total == 200 and doc.base_net_total == 750
    if family == "nominal":
        assert money(old, "PayableAmount") == Decimal("112.50" if mode == "invoice" else "75.00")
        assert money(new, "PayableAmount") == Decimal("30.00" if mode == "invoice" else "20.00")


@pytest.mark.parametrize("family", ["sales", "nominal", "advance"])
def test_frozen_selected_parent_refusal_becomes_native_company_bound_generation(monkeypatch, family):
    doc, records = financial_model(16, "selected")
    setup(monkeypatch, records)
    no_helper(doc)
    previous = old_builders()
    space = previous["builders"]
    with pytest.raises(previous["context"].DeclaredVatError) as caught:
        if family == "advance": space["item_data_with_template_advance_invoice"](ET.Element("Invoice"), doc)
        elif family == "nominal": space["_nominal_breakdown_with_template"](doc)
        else: space["_append_sales_invoice_item_lines"](ET.Element("Invoice"), doc, has_template=True)
    assert caught.value.code == "declared_vat_currency_context"
    assert len(generate(doc, family, "selected")) > 0


@pytest.mark.parametrize("family", ["sales", "pos"])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("fault", ["missing", "blank", "foreign", "masked-conflict"])
def test_selected_company_currency_is_authoritative_over_invoice_override(monkeypatch, family, currency, fault):
    doc, records = model(16, currency)
    declare(doc, records)
    company = records["Company", doc.company]
    if fault == "missing": del company.default_currency
    elif fault == "blank": company.default_currency = ""
    else: company.default_currency = "USD"
    if fault != "masked-conflict": no_helper(doc)
    runtime, notices = setup(monkeypatch, records, "ar")
    before = input_snapshot((doc, records))
    from zatca_erpgulf.zatca_erpgulf.pos_financial_xml import PosFinancialError
    with pytest.raises((source.DeclaredVatError, PosFinancialError)) as caught:
        emit(doc, family)
    assert caught.value.code.startswith("invoice_") or caught.value.code == "accounting_currency"
    assert len(notices) == 1 and notices[0].startswith("AR:")
    runtime.log_error.assert_called_once()
    assert "AR:" not in str(caught.value)
    assert input_snapshot((doc, records)) == before


def test_one_builder_binds_company_once_and_keeps_original_reference_owner(monkeypatch):
    doc, records = financial_model(16, "companion-first")
    runtime, _ = setup(monkeypatch, records)
    no_helper(doc)
    references = Mock()
    monkeypatch.setattr(sales, "_append_direct_advance_reference_lines", references)
    root = ET.Element("Invoice")
    sales.item_data_with_template(root, doc)
    company_calls = [call for call in runtime.get_doc.call_args_list if call.args[0] == "Company"]
    assert len(company_calls) == 1
    references.assert_called_once_with(root, doc)
    context = source.DeclaredVatContext(doc, runtime, str)
    view = context.document_for_amounts()
    assert view is context.document_for_amounts()
    assert view.items is doc.items and view.get("company_currency") == "SAR"
    assert view.currency == doc.currency
    with pytest.raises(FrozenInstanceError): view.company_currency = "USD"
    assert not hasattr(doc, "company_currency")


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_pinned_native_schema_owns_base_currency_on_company_not_invoice_helper(major, doctype):
    oracle = json.loads(Path(__file__).with_name("erpnext_currency_fields_oracle.json").read_text())
    declaration = next(row for row in oracle["sources"] if row["erp_major"] == major and row["doctype"] == doctype)
    root = Path(__file__).resolve().parents[3].parents[1] / "apps/erpnext" if major == 15 else Path("/tmp/zatca-erpnext16-rounding-ade850bbd6a7")
    content = (root / declaration["path"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == declaration["sha256"]
    fields = {row["fieldname"]: row for row in json.loads(content)["fields"]}
    assert "company_currency" not in fields
    assert fields["base_net_total"]["options"] == "Company:company:default_currency"
    assert fields["base_total_taxes_and_charges"]["options"] == "Company:company:default_currency"
    assert fields["net_total"]["options"] == "currency"


@pytest.mark.parametrize("module,method", [(sign_invoice, "zatca_call"),
    (sign_invoice, "zatca_call_compliance"), (debug_xml, "debug_call")])
@pytest.mark.parametrize("mode", ["invoice", "legacy-item", "selected"])
@pytest.mark.parametrize("conflict", [False, True])
def test_real_sales_compliance_debug_routes_keep_saved_signing_owner(
    isolated, monkeypatch, module, method, mode, conflict,
):
    invoice, company, _, app, files = isolated
    financial, records = financial_model(16, mode)
    for key, value in vars(financial).items():
        if key not in {"doctype", "name", "company", "save", "db_set"}:
            setattr(invoice, key, value)
    no_helper(invoice)
    company.default_currency = "USD" if conflict else "SAR"
    records["Company", invoice.company] = company
    for item in invoice.items:
        if item.item_tax_template:
            records["Item Tax Template", item.item_tax_template].company = invoice.company
    loader = app.get_doc.side_effect
    app.get_doc.side_effect = lambda dt, name=None: records[dt, name] if isinstance(name, str) and (dt, name) in records else loader(dt, name)

    def throw(message, *args, exc=None, **kwargs):
        if exc is not None:
            exc.args = (message,)
            raise exc
        raise app.ValidationError(message)

    app.throw = throw
    for adapter in (module, sales, createxml, xml_tax_data):
        monkeypatch.setattr(adapter, "frappe", app)
        monkeypatch.setattr(adapter, "_", lambda message: message)
    for adapter in (module, sales):
        if hasattr(adapter, "supports_advance_deduction_schema"):
            monkeypatch.setattr(adapter, "supports_advance_deduction_schema", lambda doc: False)
    stub_pipeline(monkeypatch, module, invoice)
    for name, owner in {
        "tax_data": xml_tax_data, "tax_data_with_template": xml_tax_data,
        "tax_data_nominal": sales, "tax_data_with_template_nominal": sales,
        "item_data": sales, "item_data_with_template": sales,
        "item_data_advance_invoice": sales, "item_data_with_template_advance_invoice": sales,
        "add_nominal_discount_tax": createxml,
        "add_document_level_discount_with_tax": createxml,
        "add_document_level_discount_with_tax_template": createxml,
    }.items():
        if hasattr(module, name): monkeypatch.setattr(module, name, getattr(owner, name))
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    roots = []

    def structure(root):
        roots.append(copy.deepcopy(root))
        return "<Invoice/>"

    monkeypatch.setattr(module, "xml_structuring", structure)
    signer = Mock(return_value=SimpleNamespace(encoded_hash="HASH", qr_payload="QR", xml="<Invoice/>"))
    monkeypatch.setattr(module, "sign_invoice_xml", signer)
    for name in ("attach_qr_image", "reporting_api", "clearance_api", "compliance_api_call"):
        if hasattr(module, name): monkeypatch.setattr(module, name, Mock(return_value={"status": "PASS"}))
    monkeypatch.setattr(module, "structuring_signedxml", Mock(return_value="UNUSED.xml"), raising=False)
    if method == "debug_call":
        monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
        monkeypatch.setattr(module, "resolve_zatca_phase", lambda *args: "Phase-1")
    kwargs = dict(any_item_has_tax_template=mode != "invoice")
    if method == "zatca_call_compliance": kwargs.update(company_abbr=company.abbr, compliance_type="1")
    before = input_snapshot(invoice)
    if conflict and method != "debug_call":
        with pytest.raises(source.DeclaredVatError):
            inspect.unwrap(getattr(module, method))(invoice.name, **kwargs)
    else:
        result = inspect.unwrap(getattr(module, method))(invoice.name, **kwargs)
        if method == "debug_call":
            assert result["status"] == ("error" if conflict else "success")
            if conflict: assert result["notices"] == [source.CURRENCY_REVIEW]
    if conflict:
        signer.assert_not_called()
        assert not roots and not files
        app.log_error.assert_called_once()
    else:
        signer.assert_called_once()
        assert signer.call_args.args[2] is invoice
        assert len(roots) == 1
        assert sum(Decimal(row.find("cbc:LineExtensionAmount").text) for row in roots[0].findall("cac:InvoiceLine")) == 200
        assert money(roots[0], "PayableAmount") == (230 if mode == "invoice" else 220)
        assert len(files) == (1 if method == "debug_call" else 0)
    assert input_snapshot(invoice) == before and not hasattr(invoice, "company_currency")
    invoice.save.assert_not_called()
    invoice.db_set.assert_not_called()
    app.db.commit.assert_not_called()
