"""Credit-note signs, native rounding and legacy currency source simulations.

No tenant, tax-authority API, actual signer, FX recalculation or full ERP/GL
lifecycle is used. Native15 and pinned16 controller decisions are distinguished
from frozen221 output and from original pre-development financial evidence.
"""
from decimal import Decimal
import hashlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    xml_tax_data as totals, pos_financial_xml as pos, create_xml_final_part as sales,
    template_vat_source as source,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import fixture_data, input_snapshot
from zatca_erpgulf.zatca_erpgulf.tests.test_declared_vat_xml import setup
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_currency_binding import financial_model, generate
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_financial_xml import money
from zatca_erpgulf.zatca_erpgulf.tests.test_rounded_total_control import erp16

FIXTURES = Path(__file__).with_name("fixtures")
PARENT_SHA = "f6763978a4f7fbaec2f3822d7170c629c6c388705ad4b4d4fb5733497b2846f0"
CONTEXT_SHA = "8ec0deba6b2729b9493cef61a9f077e9ac20a9f1a9d6937632cb2e24aa8beba2"


def previous():
    path = FIXTURES / "monetary_controls_e47f266.py"
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == PARENT_SHA
    namespace = {**vars(pos), **vars(totals)}
    exec(compile(content, str(path), "exec"), namespace)
    return namespace


def previous_context(monkeypatch):
    path = FIXTURES / "currency_context_e47f266.py"
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == CONTEXT_SHA
    module = ModuleType("frozen_currency_context_e47f266")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(content, str(path), "exec"), vars(module))
    return module.DeclaredVatContext


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("has_flag", [False, True])
@pytest.mark.parametrize("local", [0, 1])
@pytest.mark.parametrize("global_flag", [0, 1])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("adjustment", [Decimal("-.25"), Decimal(".25")])
@pytest.mark.parametrize("consolidated", [0, 1])
def test_native_rounding_source_and_saved_credit_direction_reconcile_xml(
    monkeypatch, erp16, major, template, currency, has_flag, local, global_flag,
    returned, adjustment, consolidated,
):
    doc, records, _ = fixture_data("item-template-mixed-rates" if template else "invoice-template-15",
                                  major, currency, False)
    sign = -1 if returned else 1
    if returned:
        doc.is_return = 1
        for item in doc.items:
            for field in ("qty", "net_amount", "base_net_amount"):
                setattr(item, field, -getattr(item, field))
        for field in ("net_total", "base_net_total", "total_taxes_and_charges",
                      "base_total_taxes_and_charges", "grand_total"):
            setattr(doc, field, -getattr(doc, field))
    doc.is_consolidated, doc.rounding_adjustment = consolidated, adjustment
    native_app = SimpleNamespace(db=SimpleNamespace(get_single_value=Mock(return_value=global_flag)))
    if major == 15:
        import erpnext.controllers.accounts_controller as accounts
        monkeypatch.setattr(accounts, "frappe", native_app)
        method = accounts.AccountsController.is_rounded_total_disabled
    else:
        monkeypatch.setitem(erp16[1], "frappe", native_app)
        method = erp16[1]["is_rounded_total_disabled"]
    doc.meta = SimpleNamespace(get_field=lambda name: object() if has_flag else None)
    if has_flag: doc.disable_rounded_total = local
    else: del doc.disable_rounded_total
    doc.is_rounded_total_disabled = Mock(side_effect=lambda: method(doc))
    disabled = False if consolidated else bool(local if has_flag else global_flag)
    expected_rounding = Decimal(0) if disabled else adjustment * sign
    doc.rounded_total = 0 if disabled else Decimal(str(doc.grand_total)) + adjustment
    runtime, notices = setup(monkeypatch, records)
    before = input_snapshot((doc, records))
    root = ET.Element("Invoice")
    (totals.tax_data_with_template if template else totals.tax_data)(root, doc)
    legal = root.find("cac:LegalMonetaryTotal")
    node = legal.find("cbc:PayableRoundingAmount")
    assert (Decimal(node.text) if node is not None else Decimal(0)) == expected_rounding
    expected = abs(Decimal(str(doc.grand_total))) + expected_rounding
    assert money(root, "PayableAmount") == expected
    if not disabled: assert money(root, "PayableAmount") == abs(doc.rounded_total)
    detailed, accounting = root.findall("cac:TaxTotal")
    assert Decimal(accounting.find("cbc:TaxAmount").text) == abs(Decimal(str(doc.base_total_taxes_and_charges)))
    assert Decimal(detailed.find("cbc:TaxAmount").text) == abs(Decimal(str(doc.total_taxes_and_charges)))
    assert doc.is_rounded_total_disabled.call_count == (0 if consolidated else 1)
    assert native_app.db.get_single_value.call_count == (1 if not consolidated and not has_flag else 0)
    for call in native_app.db.get_single_value.call_args_list:
        assert call.args == ("Global Defaults", "disable_rounded_total")
    assert input_snapshot((doc, records)) == before and not notices
    runtime.log_error.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("raw", [Decimal("-.25"), Decimal(".25")])
def test_frozen_credit_note_rounding_delta_is_not_absolute_value(raw):
    doc = Document(disable_rounded_total=0, is_return=1, rounding_adjustment=raw)
    old = previous()["_get_payable_rounding_amount"](doc)
    current = totals._get_payable_rounding_amount(doc)
    assert old == raw and current == -raw
    assert Decimal(230) + current == abs(Decimal(-230) + raw)
    assert current != abs(raw) if raw > 0 else current == abs(raw)


def test_frozen_consolidated_adjustment_is_preserved_before_later_disable_setting():
    doc = Document(disable_rounded_total=1, is_consolidated=1, is_return=0,
                   rounding_adjustment=Decimal(".25"), is_rounded_total_disabled=Mock(side_effect=AssertionError("Unused")))
    assert previous()["_get_payable_rounding_amount"](doc) == 0
    assert totals._get_payable_rounding_amount(doc) == Decimal(".25")
    doc.is_rounded_total_disabled.assert_not_called()


@pytest.mark.parametrize("returned", [False, True])
def test_frozen_foreign_credit_accounting_vat_sign_keeps_recorded_conversion(monkeypatch, returned):
    doc, records, _ = fixture_data("invoice-template-15", 15, "USD", False)
    doc.is_return = int(returned)
    doc.base_total_taxes_and_charges = Decimal("-112.50" if returned else "112.50")
    setup(monkeypatch, records)
    rows = totals._get_tax_breakdown_without_template(doc)
    outputs = []
    for function in (previous()["_append_tax_totals"], totals._append_tax_totals):
        root = ET.Element("Invoice")
        function(root, doc.currency, rows, doc)
        outputs.append(root)
    assert outputs[0].findall("cac:TaxTotal")[0].find("cbc:TaxAmount").text == outputs[1].findall("cac:TaxTotal")[0].find("cbc:TaxAmount").text
    old_amount, new_amount = [Decimal(root.findall("cac:TaxTotal")[1].find("cbc:TaxAmount").text) for root in outputs]
    assert old_amount == doc.base_total_taxes_and_charges
    assert new_amount == Decimal("112.50")
    if not returned: assert ET.tostring(outputs[0]) == ET.tostring(outputs[1])


@pytest.mark.parametrize("mode", ["missing", "flag0", "flag1", "native0", "native1", "consolidated", "bad-number"])
def test_extracted_pos_control_keeps_parent_outcome_without_duplicate_flag_read(mode):
    outcomes = []
    for function in (previous()["_previous_pos_rounding_disabled"], pos._rounding_disabled):
        reads = []
        class Observed(Document):
            def get(self, key, default=None):
                reads.append(key)
                return super().get(key, default)
        doc = Observed(disable_rounded_total=0, rounding_adjustment=0, is_consolidated=0)
        if mode == "missing": del doc.disable_rounded_total
        elif mode == "flag1": doc.disable_rounded_total = 1
        elif mode == "bad-number": doc.disable_rounded_total = "INVALID"
        elif mode.startswith("native"): doc.is_rounded_total_disabled = lambda: int(mode[-1])
        elif mode == "consolidated":
            doc.is_consolidated, doc.rounding_adjustment = 1, ".25"
            doc.is_rounded_total_disabled = Mock(side_effect=AssertionError("Unused"))
        try: outcome = function(doc)
        except pos.PosFinancialError as error: outcome = error.code
        outcomes.append((outcome, reads))
    assert outcomes[0][0] == outcomes[1][0]
    if mode in ("flag0", "flag1", "bad-number"):
        assert outcomes[0][1] == outcomes[1][1] + ["disable_rounded_total"]
    else:
        assert outcomes[0][1] == outcomes[1][1]


@pytest.mark.parametrize("bad", ["INVALID", "NaN", "Infinity", float("-inf")])
@pytest.mark.parametrize("template", [False, True])
def test_rounding_source_error_is_one_translated_outcome_with_english_log(monkeypatch, bad, template):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    doc.rounding_adjustment, doc.disable_rounded_total = bad, 0
    runtime, notices = setup(monkeypatch, records, "ar")
    before = input_snapshot(doc)
    with pytest.raises(source.DeclaredVatError) as caught:
        (totals.tax_data_with_template if template else totals.tax_data)(ET.Element("Invoice"), doc)
    assert caught.value.code == "invoice_rounding_source"
    assert len(notices) == 1 and notices[0].startswith("AR:")
    runtime.log_error.assert_called_once()
    assert "AR:" not in str(caught.value)
    assert input_snapshot(doc) == before


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("family", ["sales", "nominal", "advance"])
@pytest.mark.parametrize("mode", ["invoice", "legacy-item"])
@pytest.mark.parametrize("currency,override", [("USD", "USD"), ("USD", "EUR"), ("SAR", "USD")])
def test_unselected_explicit_currency_conflicts_now_stop_generation_without_repair(
    monkeypatch, major, family, mode, currency, override,
):
    doc, records = financial_model(major, mode)
    doc.currency, doc.company_currency = currency, override
    runtime, notices = setup(monkeypatch, records)
    old_context = previous_context(monkeypatch)(doc, runtime, str)
    assert old_context.document_for_amounts() is doc
    before = input_snapshot((doc, records))
    with pytest.raises(source.DeclaredVatError) as caught:
        generate(doc, family, mode)
    assert caught.value.code == "invoice_currency_override_conflict"
    assert len(notices) == 1
    assert input_snapshot((doc, records)) == before


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("mode", ["invoice", "legacy-item", "selected", "companion-first"])
@pytest.mark.parametrize("family", ["sales", "nominal", "advance"])
def test_valid_explicit_foreign_currency_keeps_frozen_context_xml(monkeypatch, major, mode, family):
    doc, records = financial_model(major, mode)
    runtime, _ = setup(monkeypatch, records)
    with monkeypatch.context() as patch:
        old_context = previous_context(patch)
        patch.setattr(sales, "DeclaredVatContext", old_context)
        patch.setattr(totals, "DeclaredVatContext", old_context)
        old = generate(doc, family, mode)
    new = generate(doc, family, mode)
    assert ET.tostring(old) == ET.tostring(new)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("template", [False, True])
@pytest.mark.parametrize("adjustment", [Decimal("-.25"), Decimal(".25")])
def test_credit_prepayment_is_subtracted_once_before_signed_rounding(monkeypatch, major, template, adjustment):
    doc, records, _ = fixture_data("invoice-template-15", major, "SAR", False)
    if template:
        for index, item in enumerate(doc.items, 1):
            item.item_tax_template = "ITEM-TEMPLATE-" + str(index)
    doc.is_return, doc.disable_rounded_total, doc.rounding_adjustment = 1, 0, adjustment
    for item in doc.items:
        for field in ("qty", "amount", "base_amount", "net_amount", "base_net_amount"):
            setattr(item, field, -getattr(item, field))
    for field in ("net_total", "base_net_total", "total_taxes_and_charges",
                  "base_total_taxes_and_charges", "grand_total", "base_grand_total", "rounded_total"):
        setattr(doc, field, -getattr(doc, field))
    for row in doc.taxes:
        for field in ("tax_amount", "base_tax_amount", "tax_amount_after_discount_amount",
                      "base_tax_amount_after_discount_amount"):
            setattr(row, field, -getattr(row, field))
    from zatca_erpgulf.zatca_erpgulf import advance_deduction
    setup(monkeypatch, records)
    monkeypatch.setattr(advance_deduction, "get_direct_advance_prepaid_amount", Mock(return_value=Decimal(-10)))
    before = input_snapshot(doc)
    root = ET.Element("Invoice")
    (totals.tax_data_with_template if template else totals.tax_data)(root, doc)
    assert money(root, "PrepaidAmount") == 10
    assert money(root, "PayableAmount") == Decimal(230) - 10 - adjustment
    advance_deduction.get_direct_advance_prepaid_amount.assert_called_once_with(doc, strict=True)
    assert input_snapshot(doc) == before
