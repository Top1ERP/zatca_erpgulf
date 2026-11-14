"""Opt-in account selection against native saved money and legacy XML.

All invoice/master documents are simulations. No site, signing, persistence,
transport or complete ERP document lifecycle is exercised.
"""
from decimal import Decimal
import inspect
from unittest.mock import Mock
import json
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.ksa_compliance.item_vat_selection import FIELD
from zatca_erpgulf.zatca_erpgulf import (
    advance_deduction, create_xml_final_part as sales, createxml, xml_tax_data,
    debug_xml, pos_debug_xml,
    tax_error, pos_financial_xml, template_vat_source as source,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_baseline_tax_compatibility import input_snapshot, render
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import (
    Document, isolated, prepare_debug_messages,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_financial_xml import current, money, runtime_for
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_vat_accounts import model, PATTERNS
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_distributed_invoice_discount import CASES, allocate
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_vat_accounts import wire_accounts


def declare(doc, records, *, position="last"):
    """Add native zero overrides without changing saved rates or money."""
    for item in doc.items:
        template = records["Item Tax Template", item.item_tax_template]
        template.company, template.doctype = doc.company, "Item Tax Template"
        own = template.taxes[0]
        setattr(template, FIELD, own.tax_type)
        others = [Document(tax_type=row.account_head, tax_rate=0)
                  for row in doc.taxes if row.account_head != own.tax_type]
        template.taxes = [own, *others] if position == "first" else [*others, own]
        item.item_tax_rate = json.dumps({row.tax_type: row.tax_rate for row in template.taxes})


def setup(monkeypatch, records, language="en"):
    runtime, notices = runtime_for(monkeypatch, records, language=language)
    runtime.get_installed_apps = Mock(return_value=[])
    translate = (lambda message: "AR:" + message) if language == "ar" else (lambda message: message)
    for module in (sales, createxml, xml_tax_data, tax_error):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", translate)
    monkeypatch.setattr(tax_error, "_zt", translate)
    for module in (sales, advance_deduction):
        monkeypatch.setattr(module, "supports_advance_deduction_schema", lambda doc: False)
    return runtime, notices


def emit(doc, family):
    if family == "pos":
        return current(doc, True)
    return render(doc, True, family, dict(discount=vars(createxml),
        tax=vars(sales if family == "nominal" else xml_tax_data), items=vars(sales)))


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("pattern", PATTERNS)
@pytest.mark.parametrize("discount", [False, True])
@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("returned", [False, True])
@pytest.mark.parametrize("family", ["sales", "pos"])
def test_selected_multirow_xml_matches_equivalent_single_row_native_source(
    monkeypatch, major, currency, pattern, discount, inclusive, returned, family,
):
    doc, records = model(major, currency, pattern=pattern, discount=discount,
                         inclusive=inclusive, returned=returned, quantity=3)
    doc.doctype = "POS Invoice" if family == "pos" else "Sales Invoice"
    runtime, notices = setup(monkeypatch, records)
    expected = ET.tostring(emit(doc, family))
    declare(doc, records)
    before = input_snapshot((doc, records))
    root = emit(doc, family)
    assert ET.tostring(root) == expected
    assert money(root, "TaxExclusiveAmount") == abs(Decimal(str(doc.net_total)))
    assert money(root, "PayableAmount") == abs(Decimal(str(doc.grand_total)))
    assert input_snapshot((doc, records)) == before
    assert not notices
    runtime.log_error.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("position", ["first", "last"])
@pytest.mark.parametrize("family", ["sales", "nominal", "pos"])
def test_zero_vat_selection_is_not_replaced_and_nominal_keeps_parent_output(monkeypatch, major, position, family):
    doc, records = model(major, pattern="zero-exempt")
    doc.custom_zatca_nominal_invoice = int(family == "nominal")
    setup(monkeypatch, records)
    # The ordinary POS compositor intentionally refuses nominal transactions.
    if family == "pos": doc.custom_zatca_nominal_invoice = 0
    baseline = ET.tostring(emit(doc, family))
    declare(doc, records, position=position)
    before = input_snapshot((doc, records))
    assert ET.tostring(emit(doc, family)) == baseline
    assert input_snapshot((doc, records)) == before


@pytest.mark.parametrize("major", [15, 16])
def test_advance_builder_and_signature_use_same_selected_rate(monkeypatch, major):
    doc, records = model(major, pattern="merged-standard")
    setup(monkeypatch, records)
    baseline = ET.Element("Invoice")
    sales.item_data_with_template_advance_invoice(baseline, doc)
    declare(doc, records)
    result = ET.Element("Invoice")
    sales.item_data_with_template_advance_invoice(result, doc)
    assert ET.tostring(result) == ET.tostring(baseline)
    for item in doc.items:
        template = records["Item Tax Template", item.item_tax_template]
        signature = tax_error._advance_tax_template_signature(template)
        assert signature == ("Standard", 15.0)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("family", ["sales", "pos"])
@pytest.mark.parametrize("fault", ["positive-other", "offset-amounts", "native-missing",
    "native-stale", "company", "compound", "extra-account", "unallocated-discount",
    "header", "category"])
def test_invalid_selected_scope_does_not_repair_money_or_fall_back(monkeypatch, major, family, fault):
    doc, records = model(major)
    declare(doc, records)
    template = records["Item Tax Template", doc.items[0].item_tax_template]
    if fault == "positive-other": template.taxes[0].tax_rate = 3
    elif fault == "offset-amounts":
        doc.taxes[0].tax_amount_after_discount_amount += 1
        doc.taxes[1].tax_amount_after_discount_amount -= 1
    elif fault == "native-missing":
        if major == 16: doc.item_wise_tax_details = []
        else: doc.items[0].item_tax_rate = "INVALID"
    elif fault == "native-stale":
        if major == 16: doc.item_wise_tax_details.pop()
        else: doc.items[0].item_tax_rate = json.dumps({doc.taxes[0].account_head: 15})
    elif fault == "company": template.company = "OTHER"
    elif fault == "compound": doc.taxes[0].charge_type = "On Previous Row Total"
    elif fault == "extra-account": doc.taxes.append(Document(name="EXTRA", account_head="FREIGHT", rate=0))
    elif fault == "unallocated-discount": doc.discount_amount = 10
    elif fault == "header": doc.grand_total += .01
    elif fault == "category": template.custom_zatca_tax_category = "Unknown"
    runtime, notices = setup(monkeypatch, records, "ar")
    before = input_snapshot((doc, records))
    error_class = pos_financial_xml.PosFinancialError if family == "pos" else source.DeclaredVatError
    with pytest.raises(error_class) as caught:
        emit(doc, family)
    assert "AR:" not in str(caught.value)
    assert len(notices) == 1 and notices[0].startswith("AR:")
    runtime.log_error.assert_called_once()
    assert "AR:" not in runtime.log_error.call_args.kwargs["message"]
    assert input_snapshot((doc, records)) == before


@pytest.mark.parametrize("major", [15, 16])
def test_missing_sales_foreign_currency_binding_is_explicit_not_guessed(monkeypatch, major):
    doc, records = model(major, "USD")
    declare(doc, records)
    del doc.company_currency
    runtime, _ = setup(monkeypatch, records)
    with pytest.raises(source.DeclaredVatError) as caught:
        emit(doc, "sales")
    assert caught.value.code == "declared_vat_currency_context"
    runtime.log_error.assert_called_once()
    assert money(emit(doc, "pos"), "PayableAmount") == Decimal(str(doc.grand_total))


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("inclusive", [False, True])
def test_included_price_preflight_allows_only_full_verified_declaration(monkeypatch, major, inclusive):
    doc, records = model(major, inclusive=inclusive, discount=True)
    runtime, _ = setup(monkeypatch, records)
    assert source.verified_declared_templates(doc, runtime=runtime, translate=str) is False
    declare(doc, records)
    assert source.verified_declared_templates(doc, runtime=runtime, translate=str) is True
    doc.taxes[0].tax_amount_after_discount_amount += .01
    with pytest.raises(source.DeclaredVatError):
        source.verified_declared_templates(doc, runtime=runtime, translate=str)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("pattern", PATTERNS)
def test_nominal_selected_source_preserves_existing_offset_and_tax_groups(monkeypatch, major, currency, pattern):
    doc, records = model(major, currency, pattern=pattern)
    doc.custom_zatca_nominal_invoice = 1
    setup(monkeypatch, records)
    baseline = ET.tostring(emit(doc, "nominal"))
    declare(doc, records)
    assert ET.tostring(emit(doc, "nominal")) == baseline


@pytest.mark.parametrize("phase", ["Phase-1", "Phase-2", "unknown"])
@pytest.mark.parametrize("enabled", [0, 1])
@pytest.mark.parametrize("rule", [0, 1])
@pytest.mark.parametrize("ownership", ["valid", "foreign", "group", "non-tax", "legacy-liability"])
def test_template_save_respects_company_phase_rule_and_account_ownership(monkeypatch, phase, enabled, rule, ownership):
    doc, records = model()
    declare(doc, records)
    template = records["Item Tax Template", doc.items[0].item_tax_template]
    template.name = "SELECTED-TEMPLATE"
    company = records["Company", doc.company]
    company.custom_zatca_invoice_enabled = enabled
    company.custom_phase_1_or_2 = phase
    company.custom_enforce_zatca_tax_category_rate_validation = rule
    account = Document(company=doc.company, is_group=0, account_type="Tax", root_type="Liability")
    if ownership == "foreign": account.company = "OTHER"
    elif ownership == "group": account.is_group = 1
    elif ownership == "non-tax": account.account_type = "Expense Account"
    elif ownership == "legacy-liability": account.account_type = ""
    records["Account", getattr(template, FIELD)] = account
    runtime, notices = setup(monkeypatch, records)
    active = phase == "Phase-2" and enabled == rule == 1
    before = input_snapshot((doc, records))
    if active and ownership not in ("valid", "legacy-liability"):
        with pytest.raises(source.DeclaredVatError) as caught:
            tax_error.validate_tax_template_category_constraints(template)
        assert caught.value.code == "declared_vat_account_ownership"
        assert len(notices) == 1
    else:
        tax_error.validate_tax_template_category_constraints(template)
        assert not notices
    assert input_snapshot((doc, records)) == before
    assert runtime.get_doc.call_count == (2 if active else 1)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("unresolved", [False, True])
def test_legacy_companion_must_be_unambiguous_when_another_item_opts_in(monkeypatch, major, unresolved):
    doc, records = model(major)
    declare(doc, records)
    template = records["Item Tax Template", doc.items[-1].item_tax_template]
    delattr(template, FIELD)
    if not unresolved:
        template.taxes = [row for row in template.taxes if row.tax_type == doc.taxes[-1].account_head]
    runtime, _ = setup(monkeypatch, records)
    if unresolved:
        with pytest.raises(source.DeclaredVatError) as caught:
            emit(doc, "sales")
        assert caught.value.code == "declared_vat_unresolved_companion_template"
    else:
        assert money(emit(doc, "sales"), "PayableAmount") == Decimal(str(doc.grand_total))


@pytest.mark.parametrize("major", [15, 16])
def test_legacy_first_row_behavior_and_explicit_monetary_delta_are_visible(monkeypatch, major):
    doc, records = model(major)
    declare(doc, records)
    for item in doc.items:
        delattr(records["Item Tax Template", item.item_tax_template], FIELD)
    setup(monkeypatch, records)
    # Legacy Sales chooses the first (zero override) row. Opt-in chooses saved
    # VAT5 + VAT15 =20; neither native net200 nor grand220 is modified.
    old = emit(doc, "sales")
    assert money(old, "PayableAmount") == 200
    for item in doc.items:
        template = records["Item Tax Template", item.item_tax_template]
        setattr(template, FIELD, template.taxes[-1].tax_type)
    assert money(emit(doc, "sales"), "PayableAmount") == 220
    assert doc.net_total == 200 and doc.grand_total == 220


@pytest.mark.parametrize("case", [CASES[0], CASES[1], CASES[3], CASES[4]], ids=lambda case: case[0])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("currency", ["SAR", "USD"])
@pytest.mark.parametrize("inclusive", [False, True])
@pytest.mark.parametrize("family", ["sales", "pos"])
def test_explicit_source_uses_native_net_and_grand_discount_allocation(
    monkeypatch, upstream16, case, major, currency, inclusive, family,
):
    # Execute pinned ERP allocation; after-discount tax observations are then
    # explicitly simulated. This is not a full ERP tax/save/GL lifecycle.
    probe = framework(major, upstream16, monkeypatch, setting="Commercial Rounding")
    doc, records = allocate(major, probe.flt, case, inclusive=inclusive, currency=currency)
    doc.doctype = "POS Invoice" if family == "pos" else "Sales Invoice"
    wire_accounts(doc, records, major)
    setup(monkeypatch, records)
    baseline = ET.tostring(emit(doc, family))
    declare(doc, records)
    before = input_snapshot((doc, records))
    result = emit(doc, family)
    assert ET.tostring(result) == baseline
    assert money(result, "PayableAmount") == Decimal(case[6])
    assert input_snapshot((doc, records)) == before


@pytest.mark.parametrize("family", ["sales", "pos"])
def test_selected_percentage_is_not_silently_requantized(monkeypatch, family):
    doc, records = model()
    declare(doc, records)
    template = records["Item Tax Template", doc.items[0].item_tax_template]
    template.taxes[-1].tax_rate = Decimal("5.123")
    setup(monkeypatch, records)
    with pytest.raises((source.DeclaredVatError, pos_financial_xml.PosFinancialError)):
        emit(doc, family)


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
@pytest.mark.parametrize("already_logged", [False, True])
def test_debug_returns_one_english_summary_and_does_not_duplicate_source_log(
    isolated, monkeypatch, module, already_logged,
):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    app.message_log = ["Parent message"]
    flags = dict(app.flags)
    error = source.DeclaredVatError("account_amount_mismatch", source.SOURCE)
    error.diagnostic_logged = already_logged
    if already_logged:
        app.log_error(title="ZATCA VAT source validation failed", message=str(error))

    def reject(*args):
        raise error

    monkeypatch.setattr(module, "removetags", reject)
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result["status"] == "error"
    assert result["notices"] == [source.SOURCE]
    assert result["technical_details"] == str(error)
    assert app.log_error.call_count == 1
    assert app.message_log == ["Parent message"] and app.flags == flags
    app.msgprint.assert_not_called()
    app.db.commit.assert_not_called()
    app.db.set_value.assert_not_called()
    module.compliance_api_call.assert_not_called()
    assert not files
