"""Offline POS money/price contract using native allocated nets and old XML.

No tenant, tax authority, signing or invoice recalculation is invoked. Pinned
allocation methods are exercised separately from simulated tax observations.
"""

from decimal import Decimal, ROUND_HALF_UP
import ast
import copy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance.tax_details import get_item_tax_rate
from zatca_erpgulf.zatca_erpgulf import (
    pos_debug_xml, pos_financial_xml as core, pos_final, posxml, pos_sign,
    pos_schedule_background, pos_submit__without_xml,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import (
    fixture_data, input_snapshot, original_namespaces, render,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_distributed_invoice_discount import (
    XML_CASES, allocate,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_rounded_total_control import erp16
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import (
    Document, isolated, stub_pipeline,
)


def rate_consumer_invoice(major, currency, *, negative=False, rate=15, raw_kind="json"):
    """Complete fiscal inputs for the older native-reader comparison suites."""
    doc, records, _ = fixture_data("invoice-template-15", major, currency, False)
    doc.taxes[0].rate = rate
    doc.taxes[0].item_wise_tax_detail = {item.item_code: [rate, 99] for item in doc.items}
    if raw_kind == "json":
        doc.taxes[0].item_wise_tax_detail = json.dumps(doc.taxes[0].item_wise_tax_detail)
    for item in doc.items:
        item.item_tax_rate = json.dumps({"TAX-ACCOUNT-0": rate})
    for row in doc.get("item_wise_tax_details", []):
        row.rate = rate
    if negative:
        doc.is_return = 1
        for item in doc.items:
            for field in ("qty", "net_amount", "base_net_amount"):
                setattr(item, field, -getattr(item, field))
        for field in ("net_total", "base_net_total", "total_taxes_and_charges",
                      "base_total_taxes_and_charges", "grand_total", "rounded_total"):
            setattr(doc, field, -getattr(doc, field))
    return doc, records


def runtime_for(monkeypatch, records, *, language="en"):
    notices = []
    def fail(message, *, exc):
        notices.append(message)
        exc.args = (message,)
        raise exc
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]),
        throw=Mock(side_effect=fail), msgprint=Mock(), log_error=Mock(),
        db=SimpleNamespace(commit=Mock(), set_value=Mock()))
    translate = (lambda message: "AR:" + message) if language == "ar" else (lambda message: message)
    for module in (posxml, pos_final):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", translate)
    return runtime, notices


def current(doc, has_template):
    return render(doc, has_template, "pos", dict(discount=vars(posxml),
        tax=vars(pos_final if has_template else posxml), items=vars(pos_final)))


def money(root, field):
    return Decimal(root.find("cac:LegalMonetaryTotal").find("cbc:" + field).text)


@pytest.mark.parametrize("case,has_template", XML_CASES,
    ids=[row[0][0] + ("-item" if row[1] else "-invoice") for row in XML_CASES])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("quantity", [1, 3])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("show_discount", [0, 1])
def test_final_native_nets_reconcile_every_pos_section(
    monkeypatch, upstream16, case, has_template, major, inclusive, quantity, currency, show_discount,
):
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, records = allocate(major, probe.flt, case, inclusive=inclusive,
        quantity=quantity, currency=currency)
    doc.doctype = "POS Invoice"
    # Exercise absence of company_currency on native POS documents too.
    del doc.company_currency
    if not has_template:
        for item in doc.items:
            item.item_tax_template = ""
    records["Company", doc.company].custom_submit_line_item_discount_to_zatca = show_discount
    runtime, notices = runtime_for(monkeypatch, records)
    before = input_snapshot((doc, records))
    root = current(doc, has_template)
    assert money(root, "TaxExclusiveAmount") == Decimal(str(doc.net_total))
    assert money(root, "TaxInclusiveAmount") == money(root, "PayableAmount") == Decimal(case[6])
    assert money(root, "AllowanceTotalAmount") == 0
    assert not root.findall("cac:AllowanceCharge")
    assert root.find("cac:LegalMonetaryTotal").find("cbc:PrepaidAmount") is None
    xml_lines = root.findall("cac:InvoiceLine")
    for node, source in zip(xml_lines, doc.items):
        net = Decimal(node.find("cbc:LineExtensionAmount").text)
        assert net == Decimal(str(source.net_amount))
        price = node.find("cac:Price")
        unit = Decimal(price.find("cbc:PriceAmount").text)
        assert (unit * quantity).quantize(Decimal(".01"), rounding=ROUND_HALF_UP) == net
        assert (price.find("cbc:BaseQuantity") is not None) == bool(show_discount)
        allowance = price.find("cac:AllowanceCharge")
        if show_discount:
            assert allowance is not None
            gross = Decimal(allowance.find("cbc:BaseAmount").text)
            discount = Decimal(allowance.find("cbc:Amount").text)
            assert gross - discount == unit
            assert gross == core.lines._quantize_price_amount(Decimal("100") / quantity)
        else:
            assert allowance is None
    taxes = root.findall("cac:TaxTotal")
    assert len(taxes) == 2 and not taxes[0].findall("cac:TaxSubtotal")
    assert taxes[0].find("cbc:TaxAmount").get("currencyID") == "SAR"
    assert Decimal(taxes[0].find("cbc:TaxAmount").text) == Decimal(str(doc.base_total_taxes_and_charges))
    assert taxes[1].find("cbc:TaxAmount").get("currencyID") == currency
    assert Decimal(taxes[1].find("cbc:TaxAmount").text) == Decimal(case[5])
    assert input_snapshot((doc, records)) == before
    assert notices == []
    runtime.db.commit.assert_not_called()
    runtime.db.set_value.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()


@pytest.mark.parametrize("has_template", [False, True])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
def test_return_rounding_and_pos_payment_are_not_prepayment(monkeypatch, has_template, currency):
    doc, records, _ = fixture_data("item-template-mixed-rates" if has_template else "invoice-template-15",
                                  15, currency, False)
    doc.is_return = 1
    for item in doc.items:
        for field in ("qty", "net_amount", "base_net_amount"):
            setattr(item, field, -getattr(item, field))
    for field in ("net_total", "base_net_total", "total_taxes_and_charges",
                  "base_total_taxes_and_charges", "grand_total"):
        setattr(doc, field, -getattr(doc, field))
    doc.disable_rounded_total = 0
    doc.rounding_adjustment = -.25
    doc.rounded_total = doc.grand_total - .25
    doc.paid_amount = doc.grand_total
    runtime_for(monkeypatch, records)
    root = current(doc, has_template)
    assert money(root, "PayableRoundingAmount") == Decimal(".25")
    assert money(root, "PayableAmount") == abs(Decimal(str(doc.rounded_total)))
    assert root.find("cac:LegalMonetaryTotal").find("cbc:PrepaidAmount") is None
    assert Decimal(root.findall("cac:TaxTotal")[0].find("cbc:TaxAmount").text) > 0


@pytest.mark.parametrize("case,code", [
    ("missing-net", "invalid_source"), ("zero-qty", "invalid_source"),
    ("nan", "invalid_source"), ("infinite", "invalid_source"),
    ("wrong-sign", "invalid_source"), ("zero-standard", "classification"),
    ("unknown-category", "classification"), ("missing-reason", "classification"),
    ("header-tax", "reconciliation"), ("header-net", "reconciliation"),
    ("header-gross", "reconciliation"), ("zero-rounded", "reconciliation"),
    ("extra-tax", "tax_roles"), ("deduct-tax", "tax_roles"),
    ("quantity-tax", "tax_roles"), ("mixed-templates", "mixed_template_sources"),
    ("cash", "special_transaction"), ("nominal", "special_transaction"),
    ("foreign-company", "accounting_currency"), ("no-tax", "tax_roles"),
    ("unallocated-discount", "undistributed_discount"),
])
@pytest.mark.parametrize("section", ["totals", "lines"])
def test_invalid_money_or_ambiguous_roles_leave_xml_untouched(monkeypatch, case, code, section):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    if case == "missing-net": doc.items[0].base_net_amount = None
    elif case == "zero-qty": doc.items[0].qty = 0
    elif case in ("nan", "infinite"): doc.items[0].base_net_amount = float("nan" if case == "nan" else "inf")
    elif case == "wrong-sign": doc.items[0].qty = -1
    elif case == "zero-standard": doc.taxes[0].rate = 0; doc.taxes[0].item_wise_tax_detail = "{}"
    elif case == "unknown-category": doc.custom_zatca_tax_category = "Unknown"
    elif case == "missing-reason":
        doc.custom_zatca_tax_category = "Exempted"
        doc.taxes[0].rate = 0
        doc.taxes[0].item_wise_tax_detail = "{}"
    elif case == "header-tax": doc.total_taxes_and_charges = 29.99
    elif case == "header-net": doc.net_total = 199.99
    elif case == "header-gross": doc.grand_total = 229.99
    elif case == "zero-rounded": doc.disable_rounded_total = 0; doc.rounded_total = 0
    elif case == "extra-tax": doc.taxes.append(Document(account_head="Freight"))
    elif case == "deduct-tax": doc.taxes[0].add_deduct_tax = "Deduct"
    elif case == "quantity-tax": doc.taxes[0].charge_type = "On Item Quantity"
    elif case == "mixed-templates": doc.items[0].item_tax_template = "ITEM-TEMPLATE-1"
    elif case == "cash":
        doc.apply_discount_on, doc.is_cash_or_non_trade_discount, doc.discount_amount = "Grand Total", 1, 20
    elif case == "nominal": doc.custom_zatca_nominal_invoice = 1
    elif case == "foreign-company": doc.company_currency = "USD"
    elif case == "no-tax": doc.taxes = []
    elif case == "unallocated-discount": doc.discount_amount = 20
    runtime, notices = runtime_for(monkeypatch, records, language="ar")
    root = ET.Element("Invoice")
    ET.SubElement(root, "Unrelated").text = "unchanged"
    before = ET.tostring(root), input_snapshot((doc, records))
    with pytest.raises(core.PosFinancialError) as caught:
        core.render_pos_section(root, doc, has_template=False, section=section,
            runtime=runtime, translate=lambda message: "AR:" + message, read_rate=get_item_tax_rate)
    assert caught.value.code == code
    assert str(caught.value).startswith("POS XML requires review")
    assert "AR:" not in str(caught.value)
    assert len(notices) == 1 and notices[0].startswith("AR:")
    runtime.log_error.assert_called_once()
    assert "AR:" not in runtime.log_error.call_args.kwargs["message"]
    assert code in runtime.log_error.call_args.kwargs["message"]
    assert (ET.tostring(root), input_snapshot((doc, records))) == before


def test_profile_is_metadata_fallback_not_invoice_financial_source(monkeypatch):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    # A stale profile must not override an invoice's real tax inclusion flag.
    records["POS Profile", doc.pos_profile].taxes_and_charges = "STALE"
    records["Company", doc.company].custom_submit_line_item_discount_to_zatca = 1
    records["Sales Taxes and Charges Template", "STALE"] = Document(
        custom_zatca_tax_category="Zero Rated", custom_exemption_reason_code="VATEX-SA-32",
        taxes=[Document(included_in_print_rate=1, rate=0)])
    runtime, _ = runtime_for(monkeypatch, records)
    root = current(doc, False)
    assert money(root, "PayableAmount") == 230
    assert ("POS Profile", doc.pos_profile) not in [call.args for call in runtime.get_doc.call_args_list]
    # Missing invoice metadata may legitimately fall back through its profile.
    doc.taxes_and_charges = ""
    doc.custom_zatca_tax_category = ""
    records["POS Profile", doc.pos_profile].taxes_and_charges = "INVOICE-TEMPLATE"
    assert money(current(doc, False), "PayableAmount") == 230


def test_line_rounding_does_not_silently_override_recorded_erp_vat(monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.tests.test_tax_standard_audit import model
    doc, records, has_template, _ = model("small-invoice", 15)
    doc.total_taxes_and_charges = doc.base_total_taxes_and_charges = 0
    doc.grand_total = doc.rounded_total = .09
    runtime_for(monkeypatch, records)
    with pytest.raises(core.PosFinancialError, match="total_taxes_and_charges: ERP=0, XML=0.01"):
        current(doc, has_template)


def test_legitimate_free_invoice_and_zero_rounded_total(monkeypatch):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    for item in doc.items:
        item.net_amount = item.base_net_amount = 0
    for field in ("net_total", "base_net_total", "total_taxes_and_charges",
                  "base_total_taxes_and_charges", "grand_total", "rounded_total"):
        setattr(doc, field, 0)
    doc.disable_rounded_total = 0
    runtime_for(monkeypatch, records)
    assert money(current(doc, False), "PayableAmount") == 0


@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("gross_field", ["price_list_rate", "rate_with_margin"])
def test_item_discount_display_uses_actual_gross_reference(monkeypatch, inclusive, gross_field):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    records["Company", doc.company].custom_submit_line_item_discount_to_zatca = 1
    doc.taxes[0].included_in_print_rate = int(inclusive)
    for item in doc.items:
        # ERP has already applied the item discount to its final net of100.
        # Store a real gross reference of120 exclusive /138 inclusive.
        setattr(item, gross_field, 138 if inclusive else 120)
        item.discount_amount = 23 if inclusive else 20
        item.discount_percentage = 100 / 6
    runtime_for(monkeypatch, records)
    root = current(doc, False)
    assert money(root, "PayableAmount") == 230
    for node in root.findall("cac:InvoiceLine"):
        price = node.find("cac:Price")
        allowance = price.find("cac:AllowanceCharge")
        assert Decimal(price.find("cbc:PriceAmount").text) == 100
        assert Decimal(allowance.find("cbc:BaseAmount").text) == 120
        assert Decimal(allowance.find("cbc:Amount").text) == 20


def test_conflicting_exemptions_do_not_create_duplicate_category_rate_groups(monkeypatch):
    doc, records, _ = fixture_data("item-template-zero", 15, "SAR", False)
    records["Item Tax Template", doc.items[1].item_tax_template].custom_exemption_reason_code = "VATEX-SA-33"
    runtime_for(monkeypatch, records)
    with pytest.raises(core.PosFinancialError) as caught:
        current(doc, True)
    assert caught.value.code == "conflicting_exemptions"


@pytest.mark.parametrize("has_template", [False, True])
def test_repeated_master_reads_are_bounded_per_financial_section(monkeypatch, has_template):
    doc, records, _ = fixture_data("item-template-mixed-rates" if has_template else "invoice-template-15",
                                  15, "SAR", False)
    doc.items = [copy.deepcopy(doc.items[0]) for _ in range(100)]
    for index, item in enumerate(doc.items, 1):
        item.idx = index
    doc.net_total = doc.base_net_total = doc.total = doc.base_total = 10000
    doc.total_taxes_and_charges = doc.base_total_taxes_and_charges = 500 if has_template else 1500
    doc.grand_total = doc.rounded_total = doc.net_total + doc.total_taxes_and_charges
    runtime, _ = runtime_for(monkeypatch, records)
    old = original_namespaces(runtime)
    original = render(doc, has_template, "pos", dict(discount=old["posxml.py"],
        tax=old["pos_final.py" if has_template else "posxml.py"], items=old["pos_final.py"]))
    old_calls = runtime.get_doc.call_count
    runtime.get_doc.reset_mock()
    root = current(doc, has_template)
    assert money(root, "PayableAmount") == money(original, "PayableAmount")
    assert runtime.get_doc.call_count == 4
    assert old_calls > 100
    path = Path("/tmp/zatca-pos-master-reads-217-" + str(has_template) + ".json")
    path.write_text(json.dumps(dict(items=100, item_templates=has_template,
        original_get_doc_calls=old_calls, development_get_doc_calls=runtime.get_doc.call_count)) + "\n")


@pytest.mark.parametrize("allocated", [False, True])
@pytest.mark.parametrize("nominal", [0, 1])
def test_both_pos_mixed_category_guards_require_native_allocation(allocated, nominal):
    from zatca_erpgulf.zatca_erpgulf.createxml import _has_erp_distributed_discount
    from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import fail, ValidationError
    doc, _, _ = fixture_data("invoice-template-15", 15, "SAR", True)
    doc.custom_zatca_nominal_invoice = nominal
    if not allocated:
        for item in doc.items:
            item.distributed_discount_amount = 0
    source = Path(pos_sign.__file__).read_text()
    guards = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.If)
              and "len(tax_categories) > 1" in ast.unparse(node.test)]
    assert len(guards) == 2
    for node in guards:
        statement = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        namespace = dict(pos_invoice_doc=doc, base_discount_amount=20,
            tax_categories={"Standard", "Zero Rated"}, frappe=SimpleNamespace(throw=fail),
            _=lambda message: message, _has_erp_distributed_discount=_has_erp_distributed_discount)
        if allocated and not nominal:
            exec(compile(statement, "pos-mixed-category-guard", "exec"), namespace)
        else:
            with pytest.raises(ValidationError):
                exec(compile(statement, "pos-mixed-category-guard", "exec"), namespace)


@pytest.mark.parametrize("module,method", [
    (pos_sign, "zatca_call"),
    (pos_sign, "zatca_call_compliance"),
    (pos_submit__without_xml, "zatca_call_pos_without_xml"),
    (pos_schedule_background, "zatca_call_pos_without_xml_background"),
])
def test_financial_error_is_not_swallowed_or_rewrapped_before_signing(isolated, monkeypatch, module, method):
    doc, _, _, runtime, files = isolated
    doc.doctype = "POS Invoice"
    monkeypatch.setattr(module, "frappe", runtime)
    stub_pipeline(monkeypatch, module, doc)
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    error = core.PosFinancialError("reconciliation", core.RECALCULATE, "English canonical detail")
    tax = Mock(side_effect=error)
    monkeypatch.setattr(module, "tax_data", tax)
    signer = Mock(side_effect=AssertionError("Invalid money reached signing"))
    monkeypatch.setattr(module, "sign_invoice_xml", signer)
    operation = inspect.unwrap(getattr(module, method))
    kwargs = dict(company_abbr="TEST", compliance_type="1") if method == "zatca_call_compliance" else {}
    with pytest.raises(core.PosFinancialError) as caught:
        operation(doc.name, **kwargs)
    assert caught.value is error
    tax.assert_called_once()
    signer.assert_not_called()
    runtime.log_error.assert_not_called()
    runtime.msgprint.assert_not_called()
    runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    assert files == []


def test_debug_returns_one_display_key_and_english_diagnostic(isolated, monkeypatch):
    doc, _, _, runtime, files = isolated
    doc.doctype = "POS Invoice"
    module = pos_debug_xml
    stub_pipeline(monkeypatch, module, doc)
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
    monkeypatch.setattr(module, "resolve_zatca_phase", lambda *args: "Phase-2")
    error = core.PosFinancialError("reconciliation", core.RECALCULATE, "English canonical detail")
    monkeypatch.setattr(module, "tax_data", Mock(side_effect=error))
    result = inspect.unwrap(module.debug_call)(doc.name)
    assert result["status"] == "error"
    assert result["notices"] == [core.RECALCULATE]
    assert result["technical_details"] == str(error)
    runtime.log_error.assert_called_once()
    assert "English canonical detail" in runtime.log_error.call_args.args[0]
    assert runtime.flags == {"mute_messages": False}
    runtime.msgprint.assert_not_called()
    assert files == []


@pytest.mark.parametrize("fault", ["multiple-rows", "wrong-account", "missing-rate"])
def test_item_template_must_identify_the_single_invoice_vat_role(monkeypatch, fault):
    doc, records, _ = fixture_data("item-template-mixed-rates", 15, "SAR", False)
    template = records["Item Tax Template", doc.items[0].item_tax_template]
    if fault == "multiple-rows":
        template.taxes.append(copy.deepcopy(template.taxes[0]))
    elif fault == "wrong-account":
        template.taxes[0].tax_type = "Other VAT account"
    else:
        template.taxes[0].tax_rate = None
    runtime_for(monkeypatch, records)
    with pytest.raises(core.PosFinancialError) as caught:
        current(doc, True)
    assert caught.value.code == ("invalid_source" if fault == "missing-rate" else "tax_roles")


def test_price_precision_cannot_silently_break_the_line_equation(monkeypatch):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    doc.items[0].qty = 3 * 10 ** 16
    runtime_for(monkeypatch, records)
    with pytest.raises(core.PosFinancialError) as caught:
        current(doc, False)
    assert caught.value.code == "unit_price_precision"


def test_debug_does_not_duplicate_an_already_recorded_financial_diagnostic(isolated, monkeypatch):
    doc, _, _, runtime, files = isolated
    doc.doctype = "POS Invoice"
    module = pos_debug_xml
    stub_pipeline(monkeypatch, module, doc)
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
    monkeypatch.setattr(module, "resolve_zatca_phase", lambda *args: "Phase-2")
    error = core.PosFinancialError("reconciliation", core.RECALCULATE)
    error.diagnostic_logged = True
    monkeypatch.setattr(module, "tax_data", Mock(side_effect=error))
    result = inspect.unwrap(module.debug_call)(doc.name)
    assert result["notices"] == [core.RECALCULATE]
    runtime.log_error.assert_not_called()
    assert files == []


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("has_flag", [False, True])
@pytest.mark.parametrize("local_flag", [0, 1])
@pytest.mark.parametrize("global_flag", [0, 1])
def test_native_rounding_control_uses_schema_then_global_defaults(
    monkeypatch, erp16, major, has_flag, local_flag, global_flag,
):
    doc, records, _ = fixture_data("invoice-template-15", major, "SAR", False)
    native_runtime = SimpleNamespace(db=SimpleNamespace(get_single_value=Mock(return_value=global_flag)))
    if major == 15:
        import erpnext.controllers.accounts_controller as accounts
        monkeypatch.setattr(accounts, "frappe", native_runtime)
        method = accounts.AccountsController.is_rounded_total_disabled
    else:
        monkeypatch.setitem(erp16[1], "frappe", native_runtime)
        method = erp16[1]["is_rounded_total_disabled"]
    doc.meta = SimpleNamespace(get_field=lambda name: object() if has_flag else None)
    if has_flag:
        doc.disable_rounded_total = local_flag
    else:
        del doc.disable_rounded_total
    disabled = local_flag if has_flag else global_flag
    doc.rounded_total = 0 if disabled else doc.grand_total
    doc.is_rounded_total_disabled = Mock(side_effect=lambda: method(doc))
    # A profile flag is not the native control for a missing invoice field.
    records["POS Profile", doc.pos_profile].disable_rounded_total = 1 - global_flag
    runtime_for(monkeypatch, records)
    assert money(current(doc, False), "PayableAmount") == 230
    assert doc.is_rounded_total_disabled.call_count == 2
    assert native_runtime.db.get_single_value.call_count == (0 if has_flag else 2)
    for call in native_runtime.db.get_single_value.call_args_list:
        assert call.args == ("Global Defaults", "disable_rounded_total")


def test_consolidated_saved_adjustment_does_not_read_a_later_disable_setting(monkeypatch):
    doc, records, _ = fixture_data("invoice-template-15", 15, "SAR", False)
    doc.is_consolidated = 1
    doc.rounding_adjustment = .25
    doc.rounded_total = 230.25
    doc.is_rounded_total_disabled = Mock(side_effect=AssertionError("Unconsumed setting read"))
    runtime_for(monkeypatch, records)
    assert money(current(doc, False), "PayableAmount") == Decimal("230.25")
    doc.is_rounded_total_disabled.assert_not_called()
