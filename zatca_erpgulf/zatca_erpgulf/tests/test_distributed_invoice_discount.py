"""Native discount allocation observations and post-allocation Sales XML.

Execute four pinned controller methods only. Item initialization/tax extraction
and the post-allocation tax recalculation boundary are explicit simulations, not
an installed-site or whole ERPNext calculation lifecycle.
"""

import ast
import copy
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    advance_deduction, createxml, create_xml_final_part as sales, pos_final, posxml,
    sign_invoice, xml_tax_data as totals,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import fixture_data, input_snapshot, render
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, ValidationError, fail

SOURCE_HASHES = Path(__file__).parent / "fixtures" / "discount_controller_sources.json"
GUARDS = Path(__file__).parent / "fixtures" / "discount_guards_c2de512.py"
GUARDS_SHA256 = "6de55b3ba22c40a798fbbff0544eeade14550c9548980f7cfc46647eb786e4f4"
SOURCES = {
    15: Path(__file__).resolve().parents[5] / "apps/erpnext/erpnext/controllers/taxes_and_totals.py",
    16: Path("/tmp/zatca-erpnext16-rounding-ade850bbd6a7/erpnext/controllers/taxes_and_totals.py"),
}
CASES = [
    ("net20", "Net Total", 20, (15, 15), ("90.00", "90.00"), "27.00", "207.00"),
    ("grand23", "Grand Total", 23, (15, 15), ("90.00", "90.00"), "27.00", "207.00"),
    ("grand20", "Grand Total", 20, (15, 15), ("91.30", "91.31"), "27.39", "210.00"),
    ("mixed-net", "Net Total", 20, (0, 15), ("90.00", "90.00"), "13.50", "193.50"),
    ("mixed-grand", "Grand Total", 21.5, (0, 15), ("90.00", "90.00"), "13.50", "193.50"),
]
XML_CASES = [(case, has_template) for case in CASES
             for has_template in ([False, True] if len(set(case[3])) == 1 else [True])]


class NativeDoc(Document):
    def precision(self, field):
        return 2
    def set(self, field, value):
        setattr(self, field, value)


def native_controller(major, flt):
    path = SOURCES[major]
    if not path.is_file():
        pytest.skip("Pinned ERPNext controller source must be staged locally for this offline probe")
    source = path.read_bytes()
    record = json.loads(SOURCE_HASHES.read_text())[str(major)]
    assert hashlib.sha256(source).hexdigest() == record["file_sha256"]
    cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef)
               and node.name == "calculate_taxes_and_totals")
    namespace = dict(flt=flt, frappe=SimpleNamespace(throw=fail), _=lambda message: message)
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in record["methods"]:
            text = textwrap.dedent(ast.get_source_segment(source.decode(), node))
            assert hashlib.sha256(text.encode()).hexdigest() == record["methods"][node.name]
            exec(compile(text, "pinned-discount-controller/" + node.name, "exec"), namespace)
    return type("NativeDiscountController", (), {name: namespace[name] for name in record["methods"]})


def guarded_functions(current):
    if not current:
        content = GUARDS.read_bytes()
        assert hashlib.sha256(content).hexdigest() == GUARDS_SHA256
        tree = ast.parse(content)
    else:
        source = Path(sign_invoice.__file__).read_text()
        functions = []
        for node in ast.parse(source).body:
            if isinstance(node, ast.FunctionDef):
                guards = [child for child in ast.walk(node) if isinstance(child, ast.If)
                    and ("len(tax_categories) > 1" in ast.unparse(child.test)
                         or "sales_invoice_doc.apply_discount_on !=" in ast.unparse(child.test))]
                if guards:
                    functions.append(ast.FunctionDef(name=node.name + "_discount_guards",
                        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=name) for name in
                            ("sales_invoice_doc", "tax_categories", "base_discount_amount")],
                            kwonlyargs=[], kw_defaults=[], defaults=[]), body=guards, decorator_list=[]))
        tree = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    namespace = dict(vars(createxml), frappe=SimpleNamespace(throw=fail), _=lambda message: message)
    exec(compile(tree, "discount-guards", "exec"), namespace)
    return [namespace[node.name] for node in tree.body if isinstance(node, ast.FunctionDef)]


def allocate(major, flt, case, *, inclusive=False, quantity=1, currency="SAR", cash=False):
    label, mode, discount, rates, _nets, _tax, _gross = case
    doc, records, _ = fixture_data("invoice-template-15", major, currency, False)
    values = {key: value for key, value in vars(doc).items()}
    doc = NativeDoc(**values)
    factor = 1 if currency == "SAR" else 3.75
    doc.apply_discount_on = mode
    doc.discount_amount = discount
    doc.base_discount_amount = 0
    doc.is_cash_or_non_trade_discount = cash
    doc.taxes[0].row_id = ""
    doc.taxes[0].category = "Total"
    doc.net_total = 200
    doc.grand_total = 200 + sum(rates)
    doc.items = []
    for index, rate in enumerate(rates, 1):
        amount = flt(100 * (1 + rate / 100), 2) if inclusive else 100
        item = NativeDoc(name="ROW-" + str(index), idx=index, item_code="ITEM-" + str(index),
            item_name="Allocated source item", description="Allocated source item", qty=quantity, uom="PCE",
            amount=amount, base_amount=amount * factor, rate=amount / quantity, price_list_rate=amount / quantity,
            net_amount=100.0, base_net_amount=100.0 * factor,
            net_rate=100.0 / quantity, base_net_rate=100.0 / quantity * factor,
            item_tax_template="ITEM-TEMPLATE-" + str(index), item_tax_rate=json.dumps({"TAX-ACCOUNT-0": rate}),
            distributed_discount_amount=0, discount_amount=0, discount_percentage=0)
        doc.items.append(item)
        records["Item Tax Template", item.item_tax_template] = Document(name=item.item_tax_template,
            custom_zatca_tax_category="Zero Rated" if rate == 0 else "Standard",
            custom_exemption_reason_code="VATEX-SA-32" if rate == 0 else None,
            taxes=[Document(tax_type="TAX-ACCOUNT-0", tax_rate=rate)])
    doc.round_floats_in = lambda owner, names: [owner.set(name, flt(owner.get(name), owner.precision(name))) for name in names]
    controller_type = native_controller(major, flt)
    controller = controller_type.__new__(controller_type)
    controller.doc, controller._items = doc, doc.items
    controller.discount_amount_applied = False
    controller._calculate = Mock(side_effect=controller.calculate_net_total)
    controller.apply_discount_amount()
    assert controller.discount_amount_applied is True
    if cash:
        controller._calculate.assert_not_called()
    else:
        controller._calculate.assert_called_once_with()
    # The real allocation/base-conversion/net-total methods have finished.
    # Tax recalculation is outside this probe; fill explicit VAT observations
    # from the independently declared final category/net groups for rendering.
    tax = sum((Decimal(str(item.net_amount)) * Decimal(rate) / 100
               for item, rate in zip(doc.items, rates)), Decimal("0"))
    tax = tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    doc.total_taxes_and_charges = float(tax)
    doc.base_total_taxes_and_charges = flt(float(tax) * factor, 2)
    doc.grand_total = flt(doc.net_total + float(tax), 2)
    doc.rounded_total = doc.grand_total
    doc.base_grand_total = flt(doc.grand_total * factor, 2)
    doc.taxes[0].tax_amount = doc.taxes[0].tax_amount_after_discount_amount = float(tax)
    doc.taxes[0].base_tax_amount = doc.taxes[0].base_tax_amount_after_discount_amount = doc.base_total_taxes_and_charges
    doc.taxes[0].included_in_print_rate = int(inclusive)
    doc.taxes[0].item_wise_tax_detail = json.dumps({item.item_code: [rate, 0] for item, rate in zip(doc.items, rates)})
    if major == 16:
        doc.item_wise_tax_details = [Document(item_row=item.name, tax_row=doc.taxes[0].name, rate=rate, amount=0)
                                     for item, rate in zip(doc.items, rates)]
    records["Sales Taxes and Charges Template", doc.taxes_and_charges].taxes[0].included_in_print_rate = int(inclusive)
    return doc, records


@pytest.fixture(scope="session")
def discount_evidence():
    rows = []
    yield rows
    Path("/tmp/zatca-distributed-discount-216.json").write_text(json.dumps(rows, indent=2) + "\n")


@pytest.mark.parametrize("case,has_template", XML_CASES, ids=[row[0][0] + ("-item" if row[1] else "-invoice") for row in XML_CASES])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("mode", ["Commercial Rounding", "Banker's Rounding"])
@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("quantity", [1, 3])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_native_discount_allocation_drives_sales_xml_without_double_subtraction(
    monkeypatch, upstream16, discount_evidence, case, has_template, major, mode, inclusive, quantity, currency,
):
    probe = framework(major, upstream16, monkeypatch, setting=mode)
    doc, records = allocate(major, probe.flt, case, inclusive=inclusive, quantity=quantity, currency=currency)
    assert tuple(f"{item.net_amount:.2f}" for item in doc.items) == case[4]
    assert f"{doc.total_taxes_and_charges:.2f}" == case[5]
    assert f"{doc.grand_total:.2f}" == case[6]
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]), throw=fail,
        db=SimpleNamespace(commit=Mock(), set_value=Mock()), msgprint=Mock(), log_error=Mock())
    for module in (createxml, sales, totals):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    monkeypatch.setattr(advance_deduction, "supports_advance_deduction_schema", lambda doc: False)
    assert createxml._use_line_net_amounts_discount_model(doc) is True
    assert createxml._has_erp_distributed_discount(doc) is True
    categories = {records["Item Tax Template", item.item_tax_template].custom_zatca_tax_category for item in doc.items}
    if not has_template:
        for item in doc.items:
            item.item_tax_template = ""
    before = input_snapshot((doc, records))
    for guard in guarded_functions(True):
        guard(doc, categories, doc.base_discount_amount)
    if len(categories) > 1:
        for guard in guarded_functions(False):
            with pytest.raises(ValidationError):
                guard(doc, categories, doc.base_discount_amount)
    root = render(doc, has_template, "sales", dict(discount=vars(createxml), tax=vars(totals), items=vars(sales)))
    assert not root.findall("cac:AllowanceCharge")
    lines = root.findall("cac:InvoiceLine")
    for node, item in zip(lines, doc.items):
        actual = Decimal(node.find("cbc:LineExtensionAmount").text)
        source = item.base_net_amount if currency == "SAR" else item.net_amount
        assert actual == Decimal(str(source))
        price = Decimal(node.find("cac:Price").find("cbc:PriceAmount").text)
        assert (price * Decimal(quantity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == actual
    legal = root.find("cac:LegalMonetaryTotal")
    assert Decimal(legal.find("cbc:AllowanceTotalAmount").text) == 0
    assert Decimal(legal.find("cbc:TaxExclusiveAmount").text) == Decimal(str(doc.net_total))
    assert Decimal(legal.find("cbc:PayableAmount").text) == Decimal(str(doc.grand_total))
    assert input_snapshot((doc, records)) == before
    discount_evidence.append(dict(kind="native-allocation-sales-xml", case=case[0], major=major,
        apply_discount_on=doc.apply_discount_on, discount=doc.discount_amount, currency=currency,
        inclusive=inclusive, quantity=quantity, rounding=mode, item_template=has_template,
        final_line_nets=[item.net_amount for item in doc.items],
        net=doc.net_total, vat=doc.total_taxes_and_charges, payable=doc.grand_total))
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.msgprint.assert_not_called()
    runtime.log_error.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
def test_cash_non_trade_grand_discount_is_not_claimed_to_be_distributed(monkeypatch, upstream16, major):
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, _ = allocate(major, probe.flt, CASES[2], cash=True)
    assert [item.net_amount for item in doc.items] == [100.0, 100.0]
    assert all(item.distributed_discount_amount == 0 for item in doc.items)
    assert not createxml._use_line_net_amounts_discount_model(doc)
    assert not createxml._has_erp_distributed_discount(doc)
    for guard in guarded_functions(True):
        with pytest.raises(ValidationError):
            guard(doc, {"Standard"}, doc.base_discount_amount)


@pytest.mark.parametrize("major,marker", [(15, 8.71), (16, 8.69)])
def test_distribution_marker_is_not_subtracted_to_reconstruct_final_net(monkeypatch, upstream16, major, marker):
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, _ = allocate(major, probe.flt, CASES[2], quantity=3)
    row = doc.items[1]
    assert row.net_amount == 91.31 and row.distributed_discount_amount == marker
    assert row.net_rate * row.qty != row.net_amount
    assert createxml._has_erp_distributed_discount(doc)
    assert (sales._line_net_rate(row, doc) * Decimal(3)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("91.31")


@pytest.mark.parametrize("case", ["flag-only", "inclusive-only", "missing-net", "cash", "nominal"])
def test_new_mixed_category_exception_requires_native_allocation_and_keeps_special_rules(monkeypatch, upstream16, case):
    probe = framework(15, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, _ = allocate(15, probe.flt, CASES[3])
    if case in {"flag-only", "inclusive-only"}:
        for item in doc.items:
            item.distributed_discount_amount = 0
        doc.custom_zatca_use_line_net_amounts = int(case == "flag-only")
    elif case == "missing-net":
        doc.items[0].base_net_amount = None
    elif case == "cash":
        doc.apply_discount_on = "Grand Total"
        doc.is_cash_or_non_trade_discount = True
    elif case == "nominal":
        doc.custom_zatca_nominal_invoice = 1
    for guard in guarded_functions(True):
        with pytest.raises(ValidationError):
            guard(doc, {"Standard", "Zero Rated"}, doc.base_discount_amount)


@pytest.mark.parametrize("case", CASES[:2], ids=[row[0] for row in CASES[:2]])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("has_template", [False, True])
def test_existing_pos_discount_model_requires_whole_path_migration(
    monkeypatch, upstream16, discount_evidence, case, major, inclusive, has_template,
):
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, records = allocate(major, probe.flt, case, inclusive=inclusive)
    doc.doctype = "POS Invoice"
    if not has_template:
        for item in doc.items:
            item.item_tax_template = ""
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]), throw=fail,
        db=SimpleNamespace(commit=Mock(), set_value=Mock()))
    for module in (posxml, pos_final):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    before = input_snapshot((doc, records))
    root = render(doc, has_template, "pos", dict(discount=vars(posxml),
        tax=vars(pos_final if has_template else posxml), items=vars(pos_final)))
    observed_lines = [Decimal(node.find("cbc:LineExtensionAmount").text) for node in root.findall("cac:InvoiceLine")]
    source_lines = [Decimal(str(item.net_amount)) for item in doc.items]
    assert observed_lines != source_lines
    allowance = root.find("cac:AllowanceCharge")
    assert Decimal(allowance.find("cbc:Amount").text) == Decimal(str(doc.discount_amount))
    legal = root.find("cac:LegalMonetaryTotal")
    payable = Decimal(legal.find("cbc:PayableAmount").text)
    if has_template and not inclusive and case[0] == "net20":
        assert payable == Decimal("207.00")  # Legacy gross-line/document-allowance alternative.
    if case[0] == "grand23":
        assert payable != Decimal("207.00")
    discount_evidence.append(dict(kind="pos-current-observation", case=case[0], major=major,
        inclusive=inclusive, item_template=has_template, source_net=[str(value) for value in source_lines],
        xml_lines=[str(value) for value in observed_lines],
        source_payable=doc.grand_total, xml_payable=str(payable)))
    # Changing just LineExtensionAmount to the final net would leave a second
    # document allowance. A complete monetary/price/tax migration is required.
    assert allowance is not None and doc.discount_amount > 0
    assert input_snapshot((doc, records)) == before
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
def test_legacy_manual_override_is_not_native_allocation_evidence(monkeypatch, upstream16, major):
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, _ = allocate(major, probe.flt, CASES[2], cash=True)
    doc.custom_zatca_use_line_net_amounts = 1
    assert createxml._use_line_net_amounts_discount_model(doc)
    assert not createxml._has_erp_distributed_discount(doc)
    # Preserve the existing single-category manual override. It is not proof
    # that the native engine distributed a cash/non-trade discount.
    for guard in guarded_functions(True):
        guard(doc, {"Standard"}, doc.base_discount_amount)
