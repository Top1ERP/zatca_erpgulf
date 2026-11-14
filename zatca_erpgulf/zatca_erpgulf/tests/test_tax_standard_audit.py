"""Bounded arithmetic audit against published rules, not a ZATCA SDK validator.

The oracle uses independently declared category/rate/net inputs and Decimal
group arithmetic. Characterizing a finding is not a passing compliance verdict.
Original findings stay frozen; current financial builders must satisfy this bounded oracle.
"""

import copy
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    advance_deduction, create_xml_final_part as sales, createxml,
    pos_final, posxml, xml_tax_data,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import (
    fixture_data, input_snapshot, original_namespaces, render,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, fail


CASES = {
    "invoice-control": (False, [("S", "15", "100"), ("S", "15", "100")]),
    "mixed-invoice": (False, [("S", "5", "100"), ("S", "15", "100")]),
    "mixed-item-templates": (True, [("S", "5", "100"), ("S", "15", "100")]),
    "small-invoice": (False, [("S", "15", "0.03")] * 3),
    "small-item-templates": (True, [("S", "15", "0.03")] * 3),
    "half-up-invoice": (False, [("S", "15", "0.10")]),
    "half-up-item-template": (True, [("S", "15", "0.10")]),
    "zero-and-exempt": (True, [("Z", "0", "100"), ("E", "0", "100")]),
    "zero-and-standard": (True, [("Z", "0", "100"), ("S", "15", "100")]),
}
CATEGORY_NAMES = {"S": "Standard", "Z": "Zero Rated", "E": "Exempted"}


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def children(node, tag):
    return [child for child in node if child.tag == tag]


def child(node, tag):
    return next(iter(children(node, tag)), None)


def text(node, tag):
    element = child(node, tag)
    assert element is not None and element.text is not None, tag
    return element.text


def rule_audit(root, declared):
    """Check SAR, no-document-adjustment examples; do not generalize to FX/nominal."""
    assert all(Decimal(text(row, "cbc:Amount")) == 0 for row in children(root, "cac:AllowanceCharge"))
    groups = {}
    for category, rate, net in declared:
        key = category, Decimal(rate)
        groups[key] = groups.get(key, Decimal("0")) + Decimal(net)
    expected_tax = {key: q2(net * key[1] / 100) for key, net in groups.items()}
    expected_total = sum(expected_tax.values(), Decimal("0.00"))
    totals = children(root, "cac:TaxTotal")
    detailed = [total for total in totals if children(total, "cac:TaxSubtotal")]
    assert len(detailed) == 1
    detailed = detailed[0]
    emitted = children(detailed, "cac:TaxSubtotal")
    findings, seen, actual_groups = set(), set(), []
    lines = children(root, "cac:InvoiceLine")
    assert len(lines) == len(declared)
    line_tax_sum = Decimal("0.00")
    for line, (category, rate, net) in zip(lines, declared):
        line_category = child(child(line, "cac:Item"), "cac:ClassifiedTaxCategory")
        if (text(line_category, "cbc:ID") != category
                or Decimal(text(line_category, "cbc:Percent")) != Decimal(rate)
                or Decimal(text(line, "cbc:LineExtensionAmount")) != Decimal(net)):
            findings.add("LINE_SOURCE_MISMATCH")
        line_tax_sum += Decimal(text(child(line, "cac:TaxTotal"), "cbc:TaxAmount"))
    subtotal_sum = Decimal("0.00")
    for subtotal in emitted:
        category = child(subtotal, "cac:TaxCategory")
        key = text(category, "cbc:ID"), Decimal(text(category, "cbc:Percent"))
        taxable = Decimal(text(subtotal, "cbc:TaxableAmount"))
        tax = Decimal(text(subtotal, "cbc:TaxAmount"))
        subtotal_sum += tax
        actual_groups.append(dict(category=key[0], rate=str(key[1]), net=str(taxable), tax=str(tax)))
        if key in seen:
            findings.add("DUPLICATE_CATEGORY_RATE")
        seen.add(key)
        if key not in groups:
            findings.add("EXTRA_CATEGORY_RATE")
        else:
            if taxable != q2(groups[key]):
                findings.add("CATEGORY_BASE_MISMATCH")
            if tax != expected_tax[key]:
                findings.add("CATEGORY_TAX_MISMATCH")
        if tax != q2(taxable * key[1] / 100):
            findings.add("SUBTOTAL_FORMULA_MISMATCH")
    if groups.keys() - seen:
        findings.add("MISSING_CATEGORY_RATE")
    actual_total = Decimal(text(detailed, "cbc:TaxAmount"))
    if actual_total != subtotal_sum:
        findings.add("TOTAL_SUBTOTAL_MISMATCH")
    if actual_total != expected_total:
        findings.add("DOCUMENT_TAX_MISMATCH")
    # Both totals carry SAR in this bounded matrix; no FX assumption is made.
    for total in totals:
        tax_amount = child(total, "cbc:TaxAmount")
        assert tax_amount.get("currencyID") == "SAR"
        if Decimal(tax_amount.text) != actual_total:
            findings.add("SAME_CURRENCY_TOTALS_DIFFER")
    return dict(expected_total=str(expected_total), actual_total=str(actual_total),
        sum_of_emitted_line_taxes=str(line_tax_sum),
        expected_groups=[dict(category=key[0], rate=str(key[1]), net=str(net), tax=str(expected_tax[key]))
                         for key, net in groups.items()],
        actual_groups=actual_groups, findings=sorted(findings))


def model(case, major):
    has_template, declared = CASES[case]
    doc, records, _ = fixture_data("invoice-template-15", major, "SAR", False)
    pattern = doc.items[0]
    doc.items = []
    for index, (category, rate, net) in enumerate(declared, 1):
        item = copy.deepcopy(pattern)
        item.name, item.item_code, item.idx = "ROW-" + str(index), "ITEM-" + str(index), index
        for field in ("amount", "base_amount", "net_amount", "base_net_amount", "rate", "base_rate",
                      "net_rate", "base_net_rate", "price_list_rate", "base_price_list_rate"):
            setattr(item, field, float(net))
        item.item_tax_template = "AUDIT-TEMPLATE-" + str(index) if has_template else ""
        item.item_tax_rate = json.dumps({"TAX-ACCOUNT-0": float(rate)})
        doc.items.append(item)
        if has_template:
            reason = "VATEX-SA-32" if category == "Z" else "VATEX-SA-29" if category == "E" else None
            records["Item Tax Template", item.item_tax_template] = Document(name=item.item_tax_template,
                custom_zatca_tax_category=CATEGORY_NAMES[category], custom_exemption_reason_code=reason,
                taxes=[Document(tax_type="TAX-ACCOUNT-0", tax_rate=float(rate))])
    doc.total = doc.net_total = doc.base_total = doc.base_net_total = float(sum(Decimal(row[2]) for row in declared))
    expected_groups = {}
    for category, rate, net in declared:
        key = category, rate
        expected_groups[key] = expected_groups.get(key, Decimal("0")) + Decimal(net)
    tax = sum((q2(net * Decimal(key[1]) / 100) for key, net in expected_groups.items()), Decimal("0.00"))
    doc.total_taxes_and_charges = doc.base_total_taxes_and_charges = float(tax)
    doc.grand_total = doc.base_grand_total = doc.rounded_total = float(Decimal(str(doc.net_total)) + tax)
    doc.taxes[0].tax_amount = doc.taxes[0].tax_amount_after_discount_amount = float(tax)
    doc.taxes[0].base_tax_amount = doc.taxes[0].base_tax_amount_after_discount_amount = float(tax)
    doc.taxes[0].item_wise_tax_detail = json.dumps({item.item_code: [float(rate), float(Decimal(net) * Decimal(rate) / 100)]
        for item, (_, rate, net) in zip(doc.items, declared)})
    if major == 16:
        doc.item_wise_tax_details = [Document(item_row=item.name, tax_row=doc.taxes[0].name,
            rate=float(rate), amount=float(Decimal(net) * Decimal(rate) / 100))
            for item, (_, rate, net) in zip(doc.items, declared)]
    return doc, records, has_template, declared


@pytest.fixture(scope="session")
def audit_report():
    rows = []
    yield rows
    path = Path("/tmp/zatca-tax-standard-audit-214.json")
    path.write_text(json.dumps(dict(scope="bounded SAR arithmetic audit, not SDK validation", cases=rows), indent=2) + "\n")


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("family", ["sales", "pos"])
@pytest.mark.parametrize("major", [15, 16])
def test_published_tax_rules_expose_original_and_current_gaps(monkeypatch, audit_report, case, family, major):
    doc, records, has_template, declared = model(case, major)
    doc.doctype = "POS Invoice" if family == "pos" else "Sales Invoice"
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]), throw=fail,
        db=SimpleNamespace(commit=Mock(), set_value=Mock()), log_error=Mock(), msgprint=Mock())
    for module in (sales, createxml, pos_final, posxml, xml_tax_data):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    for module in (sales, advance_deduction):
        monkeypatch.setattr(module, "supports_advance_deduction_schema", lambda doc: False)
    old = original_namespaces(runtime)
    original = dict(discount=old["posxml.py" if family == "pos" else "createxml.py"],
        tax=old["pos_final.py" if family == "pos" and has_template else "posxml.py" if family == "pos" else "xml_tax_data.py"],
        items=old["pos_final.py" if family == "pos" else "create_xml_final_part.py"])
    current = dict(discount=vars(posxml if family == "pos" else createxml),
        tax=vars(pos_final if family == "pos" and has_template else posxml if family == "pos" else xml_tax_data),
        items=vars(pos_final if family == "pos" else sales))
    before = input_snapshot((doc, records))
    observations = {}
    for version, namespace in (("original", original), ("development", current)):
        root = render(doc, has_template, family, namespace)
        observations[version] = rule_audit(root, declared)
        assert input_snapshot((doc, records)) == before
    for version, result in observations.items():
        should_fail = (
            (case == "mixed-invoice" and version == "original")
            or (case == "mixed-item-templates" and family == "pos" and version == "original")
            or (case.startswith("small-") and family == "sales" and version == "original")
            or (case.startswith("half-up-") and family == "pos" and version == "original")
        )
        assert bool(result["findings"]) == should_fail, (case, family, version, result)
        if case.startswith("small-"):
            assert result["expected_total"] == "0.01"
            assert Decimal(result["actual_total"]) == (Decimal("0.00") if family == "sales" and version == "original" else Decimal("0.01"))
        if case.startswith("half-up-"):
            assert result["expected_total"] == "0.02"
            assert Decimal(result["actual_total"]) == (Decimal("0.01") if family == "pos" and version == "original" else Decimal("0.02"))
    audit_report.append(dict(case=case, family=family, erp_format=major, **observations))
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.msgprint.assert_not_called()
    runtime.log_error.assert_not_called()
