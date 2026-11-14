"""Original deployed financial XML versus development on identical simulations.

Frozen dependencies are bound to the original native tax reader, never to its
current replacement. These are unsigned financial fragments, not SDK acceptance
or a claim about a tenant's actual saved invoices.
"""

from collections import defaultdict
import copy
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import hashlib
from html import unescape
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from frappe.utils import cint
from frappe.utils.data import get_time
import pytest

from zatca_erpgulf.zatca_erpgulf import (
    advance_deduction, create_xml_final_part as sales, createxml as discounts,
    pos_final, posxml, xml_tax_data as totals,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, fail

REFERENCE = Path(__file__).parent / "fixtures" / "financial_baseline_2e97708"
BASELINE = "2e97708e115e31c675182647d10829d6175e7449"
MANIFEST_SHA256 = "bd710681f766f8cf6b5ca06e9abe6962c5a51b2e7010d147a0de59e0899e257f"
CASES = {
    "invoice-template-15": (False, (15,), ((15,), (15,))),
    "invoice-template-two-taxes": (False, (15, 5), ((15, 5), (15, 5))),
    "item-template-two-taxes": (True, (15, 5), ((15, 5), (15, 5))),
    "item-template-mixed-rates": (True, (15,), ((5,), (15,))),
    "invoice-template-mixed-rates": (False, (15,), ((5,), (15,))),
    "zero-then-fifteen": (False, (15,), ((0,), (15,))),
    "fifteen-then-zero": (False, (15,), ((15,), (0,))),
    "item-override-zero": (False, (15,), ((0,), (0,))),
    "item-template-zero": (True, (0,), ((0,), (0,))),
    "invoice-template-zero": (False, (0,), ((0,), (0,))),
}
# Observed development differences, not user-approved financial behavior.
CHARACTERIZED_XML_DELTAS = {"invoice-template-mixed-rates", "zero-then-fifteen",
                          "fifteen-then-zero", "item-override-zero"}
MODULES = (sales, discounts, pos_final, posxml, totals)


def original_namespaces(runtime):
    manifest_bytes = (REFERENCE / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256
    manifest = json.loads(manifest_bytes)
    assert manifest["baseline"] == BASELINE
    spaces = {}
    common = dict(Decimal=Decimal, ROUND_HALF_UP=ROUND_HALF_UP, ROUND_DOWN=ROUND_DOWN,
        defaultdict=defaultdict, json=json, re=re, unescape=unescape, ET=ET,
        cint=cint, get_time=get_time, frappe=runtime, _=lambda message, *args: message,
        supports_advance_deduction_schema=lambda doc: False,
        is_advance_payment_invoice=lambda doc: False)
    # Explicit original import graph: no current financial function is injected.
    for filename in ("tax_details.py", "xml_tax_data.py", "create_xml_final_part.py",
                     "posxml.py", "pos_final.py", "createxml.py"):
        namespace = dict(common, __name__="frozen_financial_baseline." + filename[:-3])
        if spaces:
            namespace["get_item_tax_detail"] = spaces["tax_details.py"]["get_item_tax_detail"]
        if "xml_tax_data.py" in spaces:
            for name in ("get_exemption_reason_map", "resolve_exemption_reason_text"):
                namespace[name] = spaces["xml_tax_data.py"][name]
        if "posxml.py" in spaces:
            namespace["add_line_item_discount"] = spaces["posxml.py"]["add_line_item_discount"]
            namespace["get_exemption_reason_map"] = spaces["posxml.py"]["get_exemption_reason_map"]
        content = (REFERENCE / filename).read_bytes()
        assert hashlib.sha256(content).hexdigest() == manifest["modules"][filename]["fixture_sha256"]
        exec(compile(content, str(REFERENCE / filename), "exec"), namespace)
        spaces[filename] = namespace
    assert spaces["xml_tax_data.py"]["get_item_tax_detail"] is spaces["tax_details.py"]["get_item_tax_detail"]
    assert spaces["create_xml_final_part.py"]["get_item_tax_detail"] is spaces["tax_details.py"]["get_item_tax_detail"]
    return spaces


def fixture_data(case, major, currency, distributed_discount):
    has_template, invoice_rates, line_rates = CASES[case]
    factor = 1 if currency == "SAR" else 3.75
    line_net = 90 if distributed_discount else 100
    zero_category = all(rate == 0 for rates in line_rates for rate in rates)
    category = "Zero Rated" if zero_category else "Standard"
    reason = "VATEX-SA-32" if zero_category else None
    items, templates, details = [], {}, []
    for index, rates in enumerate(line_rates, 1):
        name = "ITEM-TEMPLATE-" + str(index)
        templates["Item Tax Template", name] = Document(name=name,
            custom_zatca_tax_category=category, custom_exemption_reason_code=reason,
            taxes=[Document(tax_type="TAX-ACCOUNT-" + str(j), tax_rate=rate) for j, rate in enumerate(rates)])
        items.append(Document(name="ROW-" + str(index), idx=index, item_code="ITEM-" + str(index),
            item_name="Simulated item", description="Simulated item", qty=1, uom="PCE",
            rate=100, base_rate=100 * factor, amount=100, base_amount=100 * factor,
            net_rate=line_net, base_net_rate=line_net * factor, net_amount=line_net,
            base_net_amount=line_net * factor, price_list_rate=100, base_price_list_rate=100 * factor,
            discount_amount=0, discount_percentage=0, distributed_discount_amount=100 - line_net,
            item_tax_template=name if has_template else "",
            item_tax_rate="" if case in {"invoice-template-15", "invoice-template-two-taxes", "invoice-template-zero"}
            else json.dumps({"TAX-ACCOUNT-" + str(j): rate for j, rate in enumerate(rates)})))
        for tax_index, rate in enumerate(rates):
            details.append(Document(item_row=items[-1].name, tax_row="TAX-" + str(tax_index),
                rate=rate, amount=line_net * rate / 100 * factor))
    taxes = []
    for tax_index, rate in enumerate(invoice_rates):
        amount = sum(line_net * rates[tax_index] / 100 for rates in line_rates)
        taxes.append(Document(name="TAX-" + str(tax_index), idx=tax_index + 1,
            charge_type="On Net Total", account_head="TAX-ACCOUNT-" + str(tax_index), rate=rate,
            included_in_print_rate=0, add_deduct_tax="Add", tax_amount=amount,
            tax_amount_after_discount_amount=amount, base_tax_amount=amount * factor,
            base_tax_amount_after_discount_amount=amount * factor,
            item_wise_tax_detail=json.dumps({item.item_code: [rates[tax_index], line_net * rates[tax_index] / 100]
                for item, rates in zip(items, line_rates)})))
    total_tax = sum(row.tax_amount for row in taxes)
    doc = Document(doctype="Sales Invoice", name="SIMULATED-" + case, company="SIMULATED-COMPANY",
        currency=currency, company_currency="SAR", conversion_rate=factor,
        pos_profile="SIMULATED-POS", taxes_and_charges="INVOICE-TEMPLATE",
        custom_zatca_tax_category=category, custom_exemption_reason_code=reason,
        custom_exemption_reason="Simulated reason", custom_zatca_nominal_invoice=0,
        custom_zatca_discount_reason="Discount", custom_zatca_advance_deduction_details=[],
        total=200, net_total=2 * line_net, base_total=200 * factor, base_net_total=2 * line_net * factor,
        discount_amount=200 - 2 * line_net, base_discount_amount=(200 - 2 * line_net) * factor,
        additional_discount_percentage=0, apply_discount_on="Net Total", is_return=0, is_debit_note=0,
        total_taxes_and_charges=total_tax, base_total_taxes_and_charges=total_tax * factor,
        grand_total=2 * line_net + total_tax, base_grand_total=(2 * line_net + total_tax) * factor,
        rounded_total=2 * line_net + total_tax, rounding_adjustment=0, base_rounding_adjustment=0,
        disable_rounded_total=1, total_advance=0, items=items, taxes=taxes, save=Mock(), db_set=Mock())
    if major == 16:
        # Exercise the real invoice-level fallback with an empty native table.
        doc.item_wise_tax_details = [] if case == "invoice-template-15" else details
    templates["Sales Taxes and Charges Template", doc.taxes_and_charges] = Document(
        name=doc.taxes_and_charges, custom_zatca_tax_category=category,
        custom_exemption_reason_code=reason, taxes=copy.deepcopy(taxes))
    templates["POS Profile", doc.pos_profile] = Document(taxes_and_charges=doc.taxes_and_charges)
    templates["Company", doc.company] = Document(name=doc.company,
        custom_submit_line_item_discount_to_zatca=0)
    return doc, templates, has_template


def numeric_snapshot(doc):
    return (doc.net_total, doc.base_net_total, doc.total_taxes_and_charges, doc.grand_total,
        tuple((i.item_code, i.net_amount, i.base_net_amount, i.item_tax_rate) for i in doc.items),
        tuple((t.account_head, t.rate, t.tax_amount, t.item_wise_tax_detail) for t in doc.taxes))


def input_snapshot(value):
    """Observe every supplied document/master field, excluding mock call state."""
    if isinstance(value, Mock):
        return ("mock-boundary",)
    if isinstance(value, SimpleNamespace):
        return {key: input_snapshot(item) for key, item in vars(value).items()}
    if isinstance(value, dict):
        return {key: input_snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(input_snapshot(item) for item in value)
    return value


def financial_summary(root):
    def children(node, tag):
        return [child for child in node if child.tag == tag]
    def text(node, tag):
        return next((child.text for child in node if child.tag == tag), None)
    totals_rows = []
    for total in children(root, "cac:TaxTotal"):
        buckets = []
        for sub in children(total, "cac:TaxSubtotal"):
            category = next(iter(children(sub, "cac:TaxCategory")), ET.Element("empty"))
            buckets.append(dict(taxable=text(sub, "cbc:TaxableAmount"), tax=text(sub, "cbc:TaxAmount"),
                category=text(category, "cbc:ID"), rate=text(category, "cbc:Percent"),
                reason=text(category, "cbc:TaxExemptionReasonCode")))
        totals_rows.append(dict(tax=text(total, "cbc:TaxAmount"), subtotals=buckets))
    money = next(iter(children(root, "cac:LegalMonetaryTotal")), ET.Element("empty"))
    lines = []
    for line in children(root, "cac:InvoiceLine"):
        tax = next(iter(children(line, "cac:TaxTotal")), ET.Element("empty"))
        item = next(iter(children(line, "cac:Item")), ET.Element("empty"))
        category = next(iter(children(item, "cac:ClassifiedTaxCategory")), ET.Element("empty"))
        lines.append(dict(net=text(line, "cbc:LineExtensionAmount"), tax=text(tax, "cbc:TaxAmount"),
                          category=text(category, "cbc:ID"), rate=text(category, "cbc:Percent")))
    return dict(totals=totals_rows, monetary={child.tag: child.text for child in money}, lines=lines)


def render(doc, has_template, family, namespace):
    root = ET.Element("Invoice", {"xmlns:cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
                                  "xmlns:cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"})
    discount_name = "add_nominal_discount_tax" if family == "nominal" else (
        "add_document_level_discount_with_tax_template" if has_template else "add_document_level_discount_with_tax")
    namespace["discount"][discount_name](root, doc)
    tax_name = "tax_data_with_template" if has_template else "tax_data"
    if family == "nominal":
        tax_name += "_nominal"
    namespace["tax"][tax_name](root, doc)
    namespace["items"]["item_data_with_template" if has_template else "item_data"](root, doc)
    return root


@pytest.fixture(scope="session")
def compatibility_report():
    results = []
    yield results
    directory = Path("/tmp/zatca-baseline-tax-compatibility-213")
    directory.mkdir(exist_ok=True)
    (directory / "results.json").write_text(json.dumps(dict(baseline=BASELINE,
        kind="simulated unsigned financial XML; not tenant or SDK evidence", cases=results), indent=2) + "\n")


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("family", ["sales", "nominal", "pos"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("distributed_discount", [False, True])
def test_original_deployed_and_development_financial_xml(
    monkeypatch, compatibility_report, case, family, major, currency, distributed_discount,
):
    doc, records, has_template = fixture_data(case, major, currency, distributed_discount)
    if case in {"invoice-template-15", "invoice-template-two-taxes", "invoice-template-zero"}:
        assert not has_template
        assert all(not item.item_tax_template and not item.item_tax_rate for item in doc.items)
    if family == "pos":
        doc.doctype = "POS Invoice"
    doc.custom_zatca_nominal_invoice = int(family == "nominal")
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]), throw=fail,
        db=SimpleNamespace(commit=Mock(), set_value=Mock()), log_error=Mock(), msgprint=Mock())
    for module in MODULES:
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    for module in (sales, advance_deduction):
        monkeypatch.setattr(module, "supports_advance_deduction_schema", lambda doc: False)
    original = original_namespaces(runtime)
    before = numeric_snapshot(doc)
    supplied_inputs = input_snapshot((doc, records))
    old = dict(discount=original["posxml.py" if family == "pos" else "createxml.py"],
               tax=original["pos_final.py" if family == "pos" and has_template else "posxml.py" if family == "pos"
                            else "create_xml_final_part.py" if family == "nominal" else "xml_tax_data.py"],
               items=original["pos_final.py" if family == "pos" else "create_xml_final_part.py"])
    current = dict(discount=vars(posxml if family == "pos" else discounts),
                   tax=vars(pos_final if family == "pos" and has_template else posxml if family == "pos"
                            else sales if family == "nominal" else totals),
                   items=vars(pos_final if family == "pos" else sales))
    old_root = render(doc, has_template, family, old)
    assert numeric_snapshot(doc) == before
    assert input_snapshot((doc, records)) == supplied_inputs
    new_root = render(doc, has_template, family, current)
    assert numeric_snapshot(doc) == before
    assert input_snapshot((doc, records)) == supplied_inputs
    old_xml, new_xml = ET.tostring(old_root), ET.tostring(new_root)
    same = old_xml == new_xml
    expected_difference = case in CHARACTERIZED_XML_DELTAS and family != "pos"
    assert same == (not expected_difference)
    old_summary, new_summary = financial_summary(old_root), financial_summary(new_root)
    if family == "sales" and currency == "SAR" and not distributed_discount:
        # Independent literal financial goldens, not a current-helper oracle.
        old_tax, new_tax = {
            "invoice-template-15": ("30.00", "30.00"),
            "invoice-template-two-taxes": ("30.00", "30.00") if major == 15 else ("40.00", "40.00"),
            "item-template-two-taxes": ("30.00", "30.00"),
            "item-template-mixed-rates": ("20.00", "20.00"),
            "invoice-template-mixed-rates": ("20.00", "20.00"),
            "zero-then-fifteen": ("30.00", "15.00"),
            "fifteen-then-zero": ("30.00", "15.00"),
            "item-override-zero": ("30.00", "0.00"),
            "item-template-zero": ("0.00", "0.00"),
            "invoice-template-zero": ("0.00", "0.00"),
        }[case]
        assert old_summary["totals"][0]["tax"] == old_tax
        assert new_summary["totals"][0]["tax"] == new_tax
        assert old_summary["monetary"]["cbc:PayableAmount"] == str(Decimal("200.00") + Decimal(old_tax))
        assert new_summary["monetary"]["cbc:PayableAmount"] == str(Decimal("200.00") + Decimal(new_tax))
    identifier = "-".join((case, family, str(major), currency, "distributed" if distributed_discount else "none"))
    result = dict(id=identifier, case=case, family=family, erp_major=major, currency=currency,
        distributed_discount=distributed_discount, xml_identical=same,
        original=old_summary, development=new_summary,
        review_status="identical" if same else "observed difference; awaiting user review",
        input=dict(net=doc.net_total, tax=doc.total_taxes_and_charges, gross=doc.grand_total))
    compatibility_report.append(result)
    directory = Path("/tmp/zatca-baseline-tax-compatibility-213")
    directory.mkdir(exist_ok=True)
    (directory / (identifier + "-original.xml")).write_bytes(old_xml)
    (directory / (identifier + "-development.xml")).write_bytes(new_xml)
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.log_error.assert_not_called()
    runtime.msgprint.assert_not_called()
