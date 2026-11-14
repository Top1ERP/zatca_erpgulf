"""Final group rounding, exact prior deltas and explicit accounting boundaries."""

import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance.vat_math import vat_from_group
from zatca_erpgulf.zatca_erpgulf import advance_deduction, create_xml_final_part as sales, xml_tax_data as totals
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import fixture_data, input_snapshot
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, fail

REFERENCE = Path(__file__).parent / "fixtures" / "group_rounding_d3286d5.py"
REFERENCE_SHA256 = "8a9994d918974098dc2f9aebe9b592169acfdafd762c0ce461d194897fea386d"
CASES = [
    # Nets, USD base-net observations, rate, old/new DOC VAT, old/new SAR VAT.
    (["100", "100"], ["375", "375"], 15, "30.00", "30.00", "112.50", "112.50"),
    (["0.03"] * 3, ["0.11", "0.12", "0.11"], 15, "0.00", "0.01", "0.06", "0.05"),
    (["1.01", "2.03"], ["3.79", "7.61"], 15, "0.45", "0.46", "1.71", "1.71"),
    (["0.10"], ["0.38"], 15, "0.02", "0.02", "0.06", "0.06"),
    (["1.01", "2.03"], ["3.79", "7.61"], 0, "0.00", "0.00", "0.00", "0.00"),
]


def parent_functions():
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    namespace = dict(vars(sales))
    namespace.update(vars(totals))
    exec(compile(content, str(REFERENCE), "exec"), namespace)
    return namespace


def model(case, major, currency, negative, has_template):
    nets, bases, rate, old, new, old_sar, new_sar = case
    doc, records, _ = fixture_data("invoice-template-15", major, currency, False)
    item = doc.items[0]
    sign = -1 if negative else 1
    doc.items = []
    for index, (net, base) in enumerate(zip(nets, bases), 1):
        row = copy.deepcopy(item)
        row.name, row.item_code, row.idx = "ROW-" + str(index), "ITEM-" + str(index), index
        row.qty = sign
        net = Decimal(net) * sign
        base = Decimal(base) * sign if currency == "USD" else net
        # Base observations are explicit fixture inputs, not a claim about a
        # particular installed ERPNext conversion/rounding configuration.
        for field in ("net_amount", "amount", "net_rate", "rate", "price_list_rate"):
            setattr(row, field, net)
        for field in ("base_net_amount", "base_amount", "base_net_rate", "base_rate", "base_price_list_rate"):
            setattr(row, field, base)
        row.item_tax_template = "GROUP-TEMPLATE" if has_template else ""
        row.item_tax_rate = json.dumps({"TAX-ACCOUNT-0": rate})
        doc.items.append(row)
    category, reason = ("Zero Rated", "VATEX-SA-32") if rate == 0 else ("Standard", None)
    doc.custom_zatca_tax_category, doc.custom_exemption_reason_code = category, reason
    doc.taxes[0].rate = rate
    doc.taxes[0].item_wise_tax_detail = json.dumps({row.item_code: [rate, 0] for row in doc.items})
    doc.net_total = doc.total = sum((row.net_amount for row in doc.items), Decimal("0.00"))
    doc.base_net_total = doc.base_total = sum((row.base_net_amount for row in doc.items), Decimal("0.00"))
    doc.total_taxes_and_charges = Decimal(new) * sign
    doc.base_total_taxes_and_charges = Decimal(new_sar if currency == "USD" else new) * sign
    doc.grand_total = doc.rounded_total = doc.net_total + doc.total_taxes_and_charges
    doc.base_grand_total = doc.base_net_total + doc.base_total_taxes_and_charges
    doc.is_return = int(negative)
    doc.taxes[0].tax_amount = doc.taxes[0].tax_amount_after_discount_amount = doc.total_taxes_and_charges
    doc.taxes[0].base_tax_amount = doc.taxes[0].base_tax_amount_after_discount_amount = doc.base_total_taxes_and_charges
    records["Item Tax Template", "GROUP-TEMPLATE"] = Document(name="GROUP-TEMPLATE",
        custom_zatca_tax_category=category, custom_exemption_reason_code=reason,
        taxes=[Document(tax_type="TAX-ACCOUNT-0", tax_rate=rate)])
    records["Sales Taxes and Charges Template", doc.taxes_and_charges].custom_zatca_tax_category = category
    records["Sales Taxes and Charges Template", doc.taxes_and_charges].custom_exemption_reason_code = reason
    if major == 16:
        doc.item_wise_tax_details = [Document(item_row=row.name, tax_row=doc.taxes[0].name, rate=rate, amount=0)
                                     for row in doc.items]
    return doc, records


@pytest.fixture
def environment(monkeypatch):
    records = {}
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]), throw=fail,
        db=SimpleNamespace(commit=Mock(), set_value=Mock()), msgprint=Mock(), log_error=Mock())
    for module in (sales, totals):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", lambda message, *args: message)
    monkeypatch.setattr(advance_deduction, "supports_advance_deduction_schema", lambda doc: False)
    return runtime, records


def no_writes(runtime, doc):
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.msgprint.assert_not_called()
    runtime.log_error.assert_not_called()


@pytest.mark.parametrize("representation", [str, float, Decimal])
@pytest.mark.parametrize("base,rate,expected", [("0.09", "15", "0.01"), ("0.10", "15", "0.02"),
    ("3.04", "15", "0.46"), ("200", "15", "30.00"), ("200", "0", "0.00")])
def test_shared_math_uses_decimal_half_up_without_intermediate_rounding(representation, base, rate, expected):
    result = vat_from_group(representation(base), representation(rate))
    assert result == Decimal(expected) and result.as_tuple().exponent == -2


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("nominal", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("negative", [False, True])
def test_complete_groups_match_literal_amounts_preserve_sources_and_reconcile_supplied_invoice(
    environment, case, has_template, nominal, currency, major, negative,
):
    runtime, records = environment
    doc, masters = model(case, major, currency, negative, has_template)
    records.update(masters)
    source = input_snapshot((doc, records))
    module = sales if nominal else totals
    name = ("_nominal_breakdown_" if nominal else "_get_tax_breakdown_") + (
        "with_template" if has_template else "without_template")
    runtime.get_doc.reset_mock()
    previous = parent_functions()[name](doc)
    queries = runtime.get_doc.call_args_list[:]
    runtime.get_doc.reset_mock()
    current = getattr(module, name)(doc)
    assert runtime.get_doc.call_args_list == queries
    nets, bases, rate, old, new, old_sar, new_sar = case
    assert len(previous) == len(current) == 1
    assert previous[0]["tax_amount"] == Decimal(old)
    assert current[0]["tax_amount"] == Decimal(new)
    assert current[0]["tax_amount"] == abs(doc.total_taxes_and_charges)
    assert current[0]["taxable_amount"] == abs(doc.net_total)
    for field in ("zatca_tax_category", "tax_rate", "exemption_reason_code"):
        assert previous[0][field] == current[0][field]
    if nominal:
        assert previous[0]["sar_tax_amount"] == Decimal(old_sar if currency == "USD" else old)
        assert current[0]["sar_tax_amount"] == abs(doc.base_total_taxes_and_charges)
    tax_name = "tax_data_with_template" if has_template else "tax_data"
    if nominal:
        tax_name += "_nominal"
    root = ET.Element("Invoice")
    assert getattr(module, tax_name)(root, doc) is root
    detailed = next(total for total in root.findall("cac:TaxTotal") if total.findall("cac:TaxSubtotal"))
    assert Decimal(detailed.find("cbc:TaxAmount").text) == Decimal(new)
    monetary = root.find("cac:LegalMonetaryTotal")
    assert Decimal(monetary.find("cbc:PayableAmount").text) == (Decimal(new) if nominal else abs(doc.grand_total))
    if old == new and (not nominal or currency == "SAR" or old_sar == new_sar):
        assert previous == current
    assert input_snapshot((doc, records)) == source
    no_writes(runtime, doc)


def test_known_row_rounded_accounting_mismatch_is_not_silently_declared_reconciled(environment):
    # Characterize the still-open runtime reconciliation gate. Do not invent
    # a VAT-account selector or silently mutate ERP invoice/accounting amounts.
    runtime, records = environment
    doc, masters = model(CASES[1], 15, "SAR", False, False)
    records.update(masters)
    doc.total_taxes_and_charges = Decimal("0.00")
    doc.base_total_taxes_and_charges = Decimal("0.00")
    doc.grand_total = doc.rounded_total = doc.net_total
    doc.base_grand_total = doc.base_net_total
    for name in ("tax_amount", "tax_amount_after_discount_amount", "base_tax_amount", "base_tax_amount_after_discount_amount"):
        setattr(doc.taxes[0], name, Decimal("0.00"))
    source = input_snapshot((doc, records))
    rows = totals._get_tax_breakdown_without_template(doc)
    assert rows[0]["tax_amount"] == Decimal("0.01")
    assert rows[0]["tax_amount"] != doc.total_taxes_and_charges
    assert input_snapshot((doc, records)) == source
    no_writes(runtime, doc)
