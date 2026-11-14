"""Multi-account POS adoption with literal fiscal and frozen-parent evidence.

The source is simulated. Native allocation/numeric selection probes do not run
ERP's full tax, document or ledger lifecycle. No tenant or authority is used.
"""

import copy
import ast
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType
import textwrap
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance.tax_details import get_item_tax_rate
from zatca_erpgulf.zatca_erpgulf import pos_financial_xml as core
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import (
    CASES as BASELINE_CASES, fixture_data, input_snapshot, original_namespaces, render,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_distributed_invoice_discount import (
    CASES, SOURCES, SOURCE_HASHES, NativeDoc, allocate, native_controller,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_financial_xml import current, money, runtime_for


PARENT = Path(__file__).parent / "fixtures" / "pos_financial_266fa5d.py"
PARENT_SHA256 = "fce20e4257e25de380307725c8d9b91984d3794526fecab005e10db5eb2f3812"
PATTERNS = {
    "split-standard": [("Standard", 5), ("Standard", 15)],
    "zero-standard": [("Zero Rated", 0), ("Standard", 15)],
    "zero-exempt": [("Zero Rated", 0), ("Exempted", 0)],
    "merged-standard": [("Standard", 15), ("Standard", 15)],
    "three-accounts": [("Zero Rated", 0), ("Standard", 5), ("Standard", 15)],
}


def q2(value):
    return Decimal(str(value)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def wire_accounts(doc, records, major):
    """Simulate recalculated per-account observations after final nets exist.

    Each invoice row defaults to0; the item's single account map overrides it.
    This follows the inspected native _get_tax_rate fallback. It prevents an
    omitted other-account override from applying a second nonzero VAT rate.
    """
    pattern = copy.deepcopy(doc.taxes[0])
    taxes = []
    for index, item in enumerate(doc.items, 1):
        account = "DECLARED-ACCOUNT-" + str(index)
        template = records["Item Tax Template", item.item_tax_template]
        template.taxes[0].tax_type = account
        rate = template.taxes[0].tax_rate
        item.item_tax_rate = json.dumps({account: rate})
        row = copy.deepcopy(pattern)
        row.name, row.idx, row.account_head = "PHYSICAL-TAX-" + str(index), index, account
        row.rate = 0
        amount = q2(Decimal(str(item.net_amount)) * Decimal(str(rate)) / 100)
        row.tax_amount_after_discount_amount = row.tax_amount = float(amount)
        row.base_tax_amount_after_discount_amount = row.base_tax_amount = float(q2(amount * Decimal(str(doc.conversion_rate))))
        row.item_wise_tax_detail = json.dumps({other.item_code: [rate if other is item else 0, 0]
                                               for other in doc.items})
        taxes.append(row)
    doc.taxes = taxes
    doc.total_taxes_and_charges = float(sum((q2(row.tax_amount_after_discount_amount) for row in taxes), Decimal("0")))
    doc.base_total_taxes_and_charges = float(q2(Decimal(str(doc.total_taxes_and_charges)) * Decimal(str(doc.conversion_rate))))
    doc.grand_total = doc.rounded_total = float(q2(Decimal(str(doc.net_total)) + Decimal(str(doc.total_taxes_and_charges))))
    doc.base_grand_total = float(q2(Decimal(str(doc.grand_total)) * Decimal(str(doc.conversion_rate))))
    if major == 16:
        doc.item_wise_tax_details = [Document(item_row=item.name, tax_row=tax.name,
            rate=records["Item Tax Template", item.item_tax_template].taxes[0].tax_rate
                if item.item_tax_template.endswith("-" + str(tax.idx)) else 0,
            amount="NOT A RATE SOURCE") for item in doc.items for tax in taxes]
    return doc, records


def model(major=15, currency="SAR", *, pattern="split-standard", discount=False,
          inclusive=False, quantity=1, returned=False):
    doc, records, _ = fixture_data("item-template-mixed-rates", major, currency, False)
    doc.doctype = "POS Invoice"
    item_pattern = doc.items[0]
    template_pattern = records["Item Tax Template", item_pattern.item_tax_template]
    doc.items = []
    net = 90 if discount else 100
    for index, (category, rate) in enumerate(PATTERNS[pattern], 1):
        item = copy.deepcopy(item_pattern)
        item.name, item.idx, item.item_code = "PHYSICAL-ITEM-" + str(index), index, "SAME-ITEM-CODE"
        item.qty = quantity
        item.net_amount, item.base_net_amount = net, net * doc.conversion_rate
        item.amount = 100 * (1 + rate / 100) if inclusive else 100
        item.base_amount = item.amount * doc.conversion_rate
        item.rate = item.price_list_rate = item.amount / quantity
        item.item_tax_template = "DECLARED-TEMPLATE-" + str(index)
        item.distributed_discount_amount = 10 if discount else 0
        template = copy.deepcopy(template_pattern)
        template.custom_zatca_tax_category = category
        template.custom_exemption_reason_code = "VATEX-SA-32" if category == "Zero Rated" else "VATEX-SA-29" if category == "Exempted" else None
        template.taxes[0].tax_rate = rate
        records["Item Tax Template", item.item_tax_template] = template
        doc.items.append(item)
    doc.net_total, doc.base_net_total = net * len(doc.items), net * len(doc.items) * doc.conversion_rate
    doc.total, doc.base_total = sum(item.amount for item in doc.items), sum(item.base_amount for item in doc.items)
    doc.discount_amount = 10 * len(doc.items) if discount else 0
    doc.base_discount_amount = doc.discount_amount * doc.conversion_rate
    doc.taxes[0].included_in_print_rate = int(inclusive)
    wire_accounts(doc, records, major)
    if returned:
        doc.is_return = 1
        for item in doc.items:
            for field in ("qty", "net_amount", "base_net_amount", "amount", "base_amount"):
                setattr(item, field, -getattr(item, field))
        for tax in doc.taxes:
            for field in ("tax_amount", "base_tax_amount", "tax_amount_after_discount_amount", "base_tax_amount_after_discount_amount"):
                setattr(tax, field, -getattr(tax, field))
        for field in ("net_total", "base_net_total", "total_taxes_and_charges",
                      "base_total_taxes_and_charges", "grand_total", "base_grand_total", "rounded_total"):
            setattr(doc, field, -getattr(doc, field))
    return doc, records


@pytest.fixture
def parent(monkeypatch):
    content = PARENT.read_bytes()
    assert hashlib.sha256(content).hexdigest() == PARENT_SHA256
    module = ModuleType("frozen_pos_financial_266fa5d")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(content, str(PARENT), "exec"), vars(module))
    return module


@pytest.mark.parametrize("case", BASELINE_CASES)
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("discount", [False, True])
def test_all_previous_pos_baseline_cases_keep_xml_or_rejection_code(monkeypatch, parent, case, major, currency, discount):
    doc, records, has_template = fixture_data(case, major, currency, discount)
    runtime, _ = runtime_for(monkeypatch, records)
    before = input_snapshot((doc, records))
    outputs = []
    for module in (parent, core):
        root = ET.Element("Invoice")
        try:
            for section in ("totals", "lines"):
                module.render_pos_financials(root, doc, has_template=has_template,
                    get_doc=runtime.get_doc, read_rate=get_item_tax_rate, section=section)
        except (parent.PosFinancialError, core.PosFinancialError) as error:
            outputs.append((error.code, ET.tostring(root)))
        else:
            outputs.append((None, ET.tostring(root)))
    assert outputs[0] == outputs[1]
    assert input_snapshot((doc, records)) == before


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("pattern", PATTERNS)
@pytest.mark.parametrize("discount", [False, True])
@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("show_discount", [0, 1])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("quantity", [1, 3])
def test_declared_accounts_reconcile_without_duplicate_taxable_bases(
    monkeypatch, major, currency, pattern, discount, inclusive, show_discount, returned, quantity,
):
    doc, records = model(major, currency, pattern=pattern, discount=discount,
        inclusive=inclusive, returned=returned, quantity=quantity)
    records["Company", doc.company].custom_submit_line_item_discount_to_zatca = show_discount
    runtime, notices = runtime_for(monkeypatch, records)
    before = input_snapshot((doc, records))
    root = current(doc, True)
    assert money(root, "TaxExclusiveAmount") == (90 if discount else 100) * len(doc.items)
    assert money(root, "PayableAmount") == abs(q2(doc.grand_total))
    assert money(root, "AllowanceTotalAmount") == 0
    assert not root.findall("cac:AllowanceCharge")
    detailed = root.findall("cac:TaxTotal")[1]
    groups = detailed.findall("cac:TaxSubtotal")
    assert len(groups) == len(set(PATTERNS[pattern]))
    categories = {"Standard": "S", "Zero Rated": "Z", "Exempted": "E"}
    expected_groups = {}
    for category, rate in PATTERNS[pattern]:
        key = categories[category], Decimal(rate)
        expected_groups[key] = expected_groups.get(key, 0) + (90 if discount else 100)
    for node in groups:
        category = node.find("cac:TaxCategory")
        key = category.find("cbc:ID").text, Decimal(category.find("cbc:Percent").text)
        assert Decimal(node.find("cbc:TaxableAmount").text) == expected_groups[key]
        assert Decimal(node.find("cbc:TaxAmount").text) == q2(Decimal(expected_groups[key]) * key[1] / 100)
    assert sum((Decimal(node.find("cbc:TaxableAmount").text) for node in groups), Decimal("0")) == money(root, "TaxExclusiveAmount")
    assert sum((Decimal(node.find("cbc:TaxAmount").text) for node in groups), Decimal("0")) == abs(q2(doc.total_taxes_and_charges))
    for node, (category, rate) in zip(root.findall("cac:InvoiceLine"), PATTERNS[pattern]):
        actual_category = node.find("cac:Item").find("cac:ClassifiedTaxCategory")
        assert actual_category.find("cbc:ID").text == categories[category]
        assert Decimal(actual_category.find("cbc:Percent").text) == rate
        assert Decimal(node.find("cac:TaxTotal").find("cbc:TaxAmount").text) == q2(Decimal(90 if discount else 100) * rate / 100)
        price = node.find("cac:Price")
        net_price = Decimal(price.find("cbc:PriceAmount").text)
        assert q2(net_price * quantity) == (90 if discount else 100)
        allowance = price.find("cac:AllowanceCharge")
        if allowance is not None:
            assert Decimal(allowance.find("cbc:BaseAmount").text) - Decimal(allowance.find("cbc:Amount").text) == net_price
    assert input_snapshot((doc, records)) == before
    assert notices == []
    runtime.log_error.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


@pytest.mark.parametrize("case", [CASES[0], CASES[1], CASES[3], CASES[4]], ids=lambda case: case[0])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("inclusive", [False, True])
def test_native_allocated_net_or_grand_discount_survives_account_separation(
    monkeypatch, upstream16, case, major, currency, inclusive,
):
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, records = allocate(major, probe.flt, case, inclusive=inclusive, currency=currency)
    previous_payable = doc.grand_total
    wire_accounts(doc, records, major)
    # Tax-row recalculation is explicitly simulated after the pinned allocator.
    assert doc.grand_total == previous_payable == float(case[6])
    runtime_for(monkeypatch, records)
    assert money(current(doc, True), "PayableAmount") == Decimal(case[6])


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("fault,code", [
    ("offsetting-amounts", "account_amount_mismatch"),
    ("base-header", "account_amount_mismatch"),
    ("missing-after-discount", "invalid_source"),
    ("unexpected-zero-account", "tax_roles"),
    ("duplicate-account", "tax_roles"),
    ("compound-charge", "tax_roles"),
    ("unintended-second-rate", "account_rate_mismatch"),
    ("native-source", "account_source"),
])
def test_new_account_scope_blocks_inconsistent_money_even_when_grand_total_matches(monkeypatch, major, fault, code):
    doc, records = model(major)
    if fault == "offsetting-amounts":
        for prefix in ("", "base_"):
            field = prefix + "tax_amount_after_discount_amount"
            setattr(doc.taxes[0], field, getattr(doc.taxes[0], field) + 1)
            setattr(doc.taxes[1], field, getattr(doc.taxes[1], field) - 1)
    elif fault == "base-header": doc.base_total_taxes_and_charges += .01
    elif fault == "missing-after-discount": doc.taxes[0].tax_amount_after_discount_amount = None
    elif fault == "unexpected-zero-account":
        extra = copy.deepcopy(doc.taxes[0]); extra.name, extra.account_head = "EXTRA", "UNCLASSIFIED-FREIGHT"
        extra.tax_amount_after_discount_amount = extra.base_tax_amount_after_discount_amount = 0
        doc.taxes.append(extra)
    elif fault == "duplicate-account": doc.taxes[1].account_head = doc.taxes[0].account_head
    elif fault == "compound-charge": doc.taxes[0].charge_type = "On Previous Row Total"
    elif fault == "unintended-second-rate":
        if major == 15: doc.taxes[1].rate = 15
        else: doc.item_wise_tax_details[1].rate = 15
    elif fault == "native-source":
        if major == 15: doc.items[0].item_tax_rate = "NOT JSON"
        else: doc.item_wise_tax_details.pop()
    runtime, notices = runtime_for(monkeypatch, records, language="ar")
    before = input_snapshot((doc, records))
    root = ET.Element("Invoice")
    with pytest.raises(core.PosFinancialError) as caught:
        core.render_pos_section(root, doc, has_template=True, section="totals",
            runtime=runtime, translate=lambda message: "AR:" + message, read_rate=get_item_tax_rate)
    assert caught.value.code == code
    assert len(notices) == 1
    assert len(root) == 0
    assert input_snapshot((doc, records)) == before
    runtime.log_error.assert_called_once()
    assert "AR:" not in runtime.log_error.call_args.kwargs["message"]


@pytest.mark.parametrize("major", [15, 16])
def test_same_category_rounding_across_accounts_needs_accounting_review(monkeypatch, major):
    doc, records = model(major, pattern="merged-standard")
    for item in doc.items:
        item.net_amount = item.base_net_amount = .03
    doc.net_total = doc.base_net_total = .06
    wire_accounts(doc, records, major)
    assert doc.total_taxes_and_charges == 0
    runtime_for(monkeypatch, records)
    with pytest.raises(core.PosFinancialError) as caught:
        current(doc, True)
    assert caught.value.code == "reconciliation"  # Merged XML group must have0.01 VAT.


@pytest.mark.parametrize("major", [15, 16])
def test_original_and_217_vs_new_multi_account_output_is_explicit(monkeypatch, parent, major):
    doc, records = model(major)
    runtime, _ = runtime_for(monkeypatch, records)
    old = original_namespaces(runtime)
    original = render(doc, True, "pos", dict(discount=old["posxml.py"],
        tax=old["pos_final.py"], items=old["pos_final.py"]))
    assert money(original, "PayableAmount") == 210
    with pytest.raises(parent.PosFinancialError) as caught:
        parent.prepare_pos_financials(doc, has_template=True,
            get_doc=runtime.get_doc, read_rate=get_item_tax_rate)
    assert caught.value.code == "tax_roles"
    assert money(current(doc, True), "PayableAmount") == 220 == doc.grand_total


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("mode", ["Commercial Rounding", "Banker's Rounding"])
@pytest.mark.parametrize("returned", [False, True])
def test_native_foreign_vat_header_is_not_replaced_by_rounded_account_sum(
    monkeypatch, upstream16, major, mode, returned,
):
    probe = framework(major, upstream16, monkeypatch, setting=mode)
    doc, records = allocate(major, probe.flt, CASES[0], currency="USD")
    doc.doctype = "POS Invoice"
    wire_accounts(doc, records, major)
    doc.taxes = [NativeDoc(**vars(row)) for row in doc.taxes]
    controller_type = native_controller(major, probe.flt)
    controller = controller_type.__new__(controller_type)
    controller.doc, controller.grand_total_diff = doc, 0
    controller.set_rounded_total = Mock()  # Rounding lifecycle is a separate probe.
    content = SOURCES[major].read_bytes()
    assert hashlib.sha256(content).hexdigest() == json.loads(SOURCE_HASHES.read_text())[str(major)]["file_sha256"]
    cls = next(node for node in ast.parse(content).body if isinstance(node, ast.ClassDef)
               and node.name == "calculate_taxes_and_totals")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "calculate_totals")
    namespace = dict(flt=probe.flt)
    exec(compile(textwrap.dedent(ast.get_source_segment(content.decode(), method)),
                 "pinned-native-total-conversion", "exec"), namespace)
    running = doc.net_total
    for tax in doc.taxes:
        controller._set_in_company_currency(tax, ["tax_amount_after_discount_amount"])
        running += tax.tax_amount_after_discount_amount
        tax.total = running
    namespace["calculate_totals"](controller)
    assert q2(doc.base_total_taxes_and_charges) == Decimal("101.25")
    row_sum = sum((q2(row.base_tax_amount_after_discount_amount) for row in doc.taxes), Decimal("0"))
    assert row_sum == Decimal("101.26" if mode == "Commercial Rounding" else "101.24")
    controller.set_rounded_total.assert_called_once()
    if returned:
        doc.is_return = 1
        for item in doc.items:
            item.qty, item.net_amount, item.base_net_amount = -item.qty, -item.net_amount, -item.base_net_amount
        for tax in doc.taxes:
            tax.tax_amount_after_discount_amount *= -1
            tax.base_tax_amount_after_discount_amount *= -1
        for field in ("net_total", "base_net_total", "total_taxes_and_charges",
                      "base_total_taxes_and_charges", "grand_total", "rounded_total"):
            setattr(doc, field, -getattr(doc, field))
    runtime_for(monkeypatch, records)
    before = input_snapshot((doc, records))
    root = current(doc, True)
    assert Decimal(root.findall("cac:TaxTotal")[0].find("cbc:TaxAmount").text) == Decimal("101.25")
    assert money(root, "PayableAmount") == Decimal("207.00")
    assert input_snapshot((doc, records)) == before


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_price_inclusion_uses_own_account_and_ignores_tax_row_order(monkeypatch, major, currency):
    doc, records = model(major, currency, discount=True)
    doc.taxes[0].included_in_print_rate = 1
    doc.taxes[1].included_in_print_rate = 0
    doc.items[0].amount = doc.items[0].rate = doc.items[0].price_list_rate = 105
    doc.items[0].base_amount = 105 * doc.conversion_rate
    records["Company", doc.company].custom_submit_line_item_discount_to_zatca = 1
    runtime_for(monkeypatch, records)
    before = input_snapshot((doc, records))
    first = current(doc, True)
    assert input_snapshot((doc, records)) == before
    assert money(first, "PayableAmount") == 198
    for node in first.findall("cac:InvoiceLine"):
        price = node.find("cac:Price")
        allowance = price.find("cac:AllowanceCharge")
        assert Decimal(price.find("cbc:PriceAmount").text) == 90
        assert Decimal(allowance.find("cbc:Amount").text) == 10
        assert Decimal(allowance.find("cbc:BaseAmount").text) == 100
    doc.taxes.reverse()
    if major == 16:
        doc.item_wise_tax_details.reverse()
    second = current(doc, True)
    assert ET.tostring(first) == ET.tostring(second)
