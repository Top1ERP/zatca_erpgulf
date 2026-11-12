"""Preflight category-source/rate consistency and existing gates, offline only."""

import csv
from decimal import Decimal
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import tax_error as checks, xml_tax_data as xml
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document, ValidationError, fail

REFERENCE = Path(__file__).parent / "fixtures" / "tax_source_d14984b.py"
REFERENCE_SHA256 = "e03faef00051fbafa21aee98b8334b46d9d108458ea94e5cb80a7ead116277ed"
RATE_CASES = [
    ([0], 0.0), (["0"], 0.0), ([Decimal("0.00")], 0.0),
    ([15], 15.0), ([], None), ([None, "", 0, 15], 0.0),
]
WATCHED = {"taxes", "rate", "tax_rate", "taxes_and_charges", "custom_zatca_tax_category",
           "custom_exemption_reason_code", "name"}


class Record(Document):
    def __getattribute__(self, name):
        if name in WATCHED:
            state = object.__getattribute__(self, "__dict__")
            if "trace" in state:
                state["trace"].append((state["role"], name))
        return super().__getattribute__(name)


@pytest.fixture
def environment(monkeypatch):
    trace = []
    template = Record(role="template", trace=trace, name="SYNTHETIC-TEMPLATE",
        custom_zatca_tax_category="Standard", custom_exemption_reason_code="VATEX-SA-32",
        taxes=[Record(role="template-tax", trace=trace, rate=15)])
    records = {("Sales Taxes and Charges Template", "SYNTHETIC-TEMPLATE"): template}
    meta = SimpleNamespace(has_field=lambda name: True)
    runtime = SimpleNamespace(get_doc=Mock(side_effect=lambda dt, name: records[dt, name]),
        get_meta=Mock(return_value=meta), throw=Mock(side_effect=fail), msgprint=Mock(), log_error=Mock(),
        db=SimpleNamespace(exists=Mock(side_effect=lambda dt, name: (dt, name) in records),
                           commit=Mock(), set_value=Mock()))
    for module in (checks, xml):
        monkeypatch.setattr(module, "frappe", runtime)
    language = SimpleNamespace(value="en")
    with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8") as stream:
        translations = dict(row[:2] for row in csv.reader(stream) if len(row) >= 2)
    translate = Mock(side_effect=lambda message, lang=None: translations.get(message, message) if lang == "ar" else message)
    monkeypatch.setattr(checks, "_get_zatca_user_language", lambda: language.value)
    monkeypatch.setattr(checks, "_", translate)
    monkeypatch.setattr(xml, "_", lambda message, *args: message)
    content = REFERENCE.read_bytes()
    assert hashlib.sha256(content).hexdigest() == REFERENCE_SHA256
    parent = dict(vars(checks))
    exec(compile(content, str(REFERENCE), "exec"), parent)
    return SimpleNamespace(trace=trace, template=template, records=records, runtime=runtime,
                           language=language, translations=translations, translate=translate, parent=parent)


def invoice(env, rates, category="Zero Rated", doctype="Sales Invoice"):
    return Record(role="invoice", trace=env.trace, doctype=doctype, name="SYNTHETIC-INVOICE", company=None,
        taxes_and_charges="SYNTHETIC-TEMPLATE", custom_zatca_tax_category=category,
        custom_exemption_reason_code="VATEX-SA-32", custom_exemption_reason="Synthetic transaction reason",
        custom_zatca_export_invoice=0, currency="SAR", save=Mock(), db_set=Mock(),
        items=[Document(name="ROW", idx=1, item_code="ITEM", item_name="Synthetic", amount=100,
                        base_amount=100, net_amount=100, base_net_amount=100)],
        taxes=[Record(role="invoice-tax-" + str(i), trace=env.trace, rate=rate, tax_amount=0,
                      base_tax_amount=0, item_wise_tax_detail="") for i, rate in enumerate(rates)])


def no_writes(env, doc):
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    env.runtime.db.commit.assert_not_called()
    env.runtime.db.set_value.assert_not_called()
    env.runtime.msgprint.assert_not_called()
    env.runtime.log_error.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("category", ["Standard", "Zero Rated", "", None])
@pytest.mark.parametrize("template_category", ["Standard", "Zero Rated", ""])
@pytest.mark.parametrize("rates,expected_invoice_rate", RATE_CASES)
@pytest.mark.parametrize("template_rate", [0, 15])
def test_priority_metadata_and_reads_keep_zero_and_invoice_rate_ownership(
    environment, doctype, category, template_category, rates, expected_invoice_rate, template_rate,
):
    env = environment
    doc = invoice(env, rates, category, doctype)
    env.template.custom_zatca_tax_category = template_category
    env.template.taxes[0].rate = template_rate
    outputs = []
    for operation in (env.parent["_get_invoice_level_zatca_source"], checks._get_invoice_level_zatca_source):
        env.trace.clear()
        env.runtime.db.exists.reset_mock()
        env.runtime.get_doc.reset_mock()
        result = operation(doc)
        outputs.append((result, env.trace[:], env.runtime.db.exists.call_args_list[:], env.runtime.get_doc.call_args_list[:]))
    old, new = outputs
    assert {key: value for key, value in old[0].items() if key not in ("rate", "source_name")} == {
        key: value for key, value in new[0].items() if key not in ("rate", "source_name")}
    assert old[1:] == new[1:]
    if not category and template_category:
        assert new[0]["source_name"] == "Sales Taxes and Charges Template SYNTHETIC-TEMPLATE or Sales Invoice ZATCA fields"
    else:
        assert new[0]["source_name"] == old[0]["source_name"]
    expected = template_rate if expected_invoice_rate is None or not (category or template_category) else expected_invoice_rate
    assert new[0]["rate"] == expected
    assert checks._get_invoice_level_tax_rate(doc) == (0.0 if expected_invoice_rate is None else expected_invoice_rate)
    assert checks._get_invoice_level_tax_rate(doc, default=None) == expected_invoice_rate
    no_writes(env, doc)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("category_owner", ["invoice", "template"])
@pytest.mark.parametrize("category", ["Standard", "Zero Rated", "Exempted", "Services outside scope of tax / Not subject to VAT"])
@pytest.mark.parametrize("rate", [0, 15])
@pytest.mark.parametrize("major", [15, 16])
def test_existing_strict_rules_assess_the_same_invoice_rate_as_xml_helpers(
    environment, doctype, category_owner, category, rate, major,
):
    env = environment
    doc = invoice(env, [rate], category if category_owner == "invoice" else "", doctype)
    env.template.custom_zatca_tax_category = category
    env.template.taxes[0].rate = 15 if rate == 0 else 0
    reason = "VATEX-SA-OOS" if category == "Services outside scope of tax / Not subject to VAT" else "VATEX-SA-32"
    doc.custom_exemption_reason_code = env.template.custom_exemption_reason_code = reason
    if rate:
        doc.taxes[0].tax_amount = doc.taxes[0].base_tax_amount = 15
    if major == 16:
        doc.item_wise_tax_details = [Document(item_row="ROW", rate=rate, amount=15 if rate else 0)]
    company = Document(custom_enforce_zatca_tax_category_source_validation=1)
    valid = (category == "Standard") == bool(rate)
    if valid:
        checks.validate_zatca_tax_category_and_exemption_reason(doc, company, enforce_source_consistency=True)
    else:
        with pytest.raises(ValidationError):
            checks.validate_zatca_tax_category_and_exemption_reason(doc, company, enforce_source_consistency=True)
    selected = checks._get_invoice_level_zatca_source(doc)
    assert selected["rate"] == rate
    xml_category, xml_reason = xml._get_invoice_level_zatca_tax_source(doc)
    rows = xml._get_tax_breakdown_without_template(doc)
    assert selected["category"] == xml_category == category
    assert selected["exemption_reason"] == xml_reason == reason
    assert len(rows) == 1 and rows[0]["tax_rate"] == Decimal(str(rate)).quantize(Decimal("0.01"))
    no_writes(env, doc)


@pytest.mark.parametrize("language", ["en", "ar"])
@pytest.mark.parametrize("category_owner", ["invoice", "template"])
def test_conflicting_standard_template_no_longer_falsely_rejects_declared_zero_category(
    environment, language, category_owner,
):
    env = environment
    env.language.value = language
    doc = invoice(env, [0], "Zero Rated" if category_owner == "invoice" else "")
    env.template.custom_zatca_tax_category = "Zero Rated" if category_owner == "template" else "Standard"
    env.template.taxes[0].rate = 15
    old = env.parent["_get_invoice_level_zatca_source"](doc)
    with pytest.raises(ValidationError):
        checks._validate_category_rate_consistency(old["category"], old["rate"], old["source_name"],
                                                 exemption_reason_code=old["exemption_reason"], doc=doc)
    env.runtime.throw.reset_mock()
    checks.validate_zatca_tax_category_and_exemption_reason(doc,
        Document(custom_enforce_zatca_tax_category_source_validation=1), enforce_source_consistency=True)
    env.runtime.throw.assert_not_called()
    no_writes(env, doc)


@pytest.mark.parametrize("language", ["en", "ar"])
def test_existing_rejection_message_uses_user_language_and_no_extra_popup(environment, language):
    env = environment
    env.language.value = language
    doc = invoice(env, [15], "")
    env.template.custom_zatca_tax_category = "Zero Rated"
    env.template.taxes[0].rate = 0
    company = Document(custom_enforce_zatca_tax_category_source_validation=1)
    key = "Zero-rated, exempt, or out-of-scope ZATCA categories must have a zero tax rate in {0}."
    with pytest.raises(ValidationError) as error:
        checks.validate_zatca_tax_category_and_exemption_reason(doc, company, enforce_source_consistency=True)
    source = checks._get_invoice_level_zatca_source(doc)["source_name"]
    expected = (env.translations[key] if language == "ar" else key).format(source)
    assert str(error.value) == expected
    assert env.runtime.throw.call_count == 1
    env.runtime.msgprint.assert_not_called()
    no_writes(env, doc)


@pytest.mark.parametrize("requested", [False, True])
@pytest.mark.parametrize("setting", [0, 1, None, "absent"])
@pytest.mark.parametrize("metadata_present", [False, True])
def test_source_consistency_setting_retains_existing_missing_and_explicit_off_behavior(
    environment, requested, setting, metadata_present,
):
    env = environment
    doc = invoice(env, [0], "Standard")
    company = Document()
    if setting != "absent":
        company.custom_enforce_zatca_tax_category_source_validation = setting
    env.runtime.get_meta.return_value = SimpleNamespace(has_field=lambda name: metadata_present)
    enabled = requested and (not metadata_present or setting in (1, "absent"))
    if enabled:
        with pytest.raises(ValidationError, match="requires a tax rate greater than zero"):
            checks.validate_zatca_tax_category_and_exemption_reason(doc, company, enforce_source_consistency=requested)
    else:
        checks.validate_zatca_tax_category_and_exemption_reason(doc, company, enforce_source_consistency=requested)
        env.runtime.throw.assert_not_called()
    assert env.runtime.get_meta.call_count == (1 if requested else 0)
    no_writes(env, doc)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_disabled_company_submit_entry_still_exits_before_source_rules(environment, doctype):
    env = environment
    doc = invoice(env, [0], "Standard", doctype)
    doc.company = "SYNTHETIC-COMPANY"
    company = Document(custom_zatca_invoice_enabled=0)
    env.records[("Company", doc.company)] = company
    checks.validate_sales_invoice_taxes(doc)
    assert env.runtime.get_doc.call_count == 1
    env.runtime.get_meta.assert_not_called()
    env.runtime.db.exists.assert_not_called()
    no_writes(env, doc)


@pytest.mark.parametrize("template_exists", [False, True])
def test_absent_rate_falls_back_but_absent_template_is_not_invented(environment, template_exists):
    env = environment
    doc = invoice(env, [None, ""], "Zero Rated")
    if not template_exists:
        env.records.clear()
    selected = checks._get_invoice_level_zatca_source(doc)
    assert selected["category"] == "Zero Rated"
    assert selected["rate"] == (15 if template_exists else None)
    assert env.runtime.get_doc.call_count == int(template_exists)
    no_writes(env, doc)


@pytest.mark.parametrize("language", ["en", "ar"])
@pytest.mark.parametrize("owner", ["invoice", "template"])
@pytest.mark.parametrize("invoice_reason,template_reason,expected", [
    ("DECLARED-INVOICE", "DECLARED-TEMPLATE", "DECLARED-INVOICE"),
    ("DECLARED-INVOICE", "", "DECLARED-INVOICE"),
    ("", "DECLARED-TEMPLATE", "DECLARED-TEMPLATE"),
    ("", "", ""),
])
def test_reason_precedence_matches_xml_even_when_category_comes_from_template(
    environment, language, owner, invoice_reason, template_reason, expected,
):
    env = environment
    env.language.value = language
    doc = invoice(env, [0], "Zero Rated" if owner == "invoice" else "")
    doc.custom_exemption_reason_code = invoice_reason
    env.template.custom_zatca_tax_category = "Zero Rated"
    env.template.custom_exemption_reason_code = template_reason
    env.template.taxes[0].rate = 0
    selected = checks._get_invoice_level_zatca_source(doc)
    old = env.parent["_get_invoice_level_zatca_source"](doc)
    if owner == "template":
        assert old["exemption_reason"] == template_reason
    assert selected["exemption_reason"] == xml._get_invoice_level_zatca_tax_source(doc)[1] == expected
    company = Document(custom_enforce_zatca_tax_category_source_validation=1)
    if expected:
        checks.validate_zatca_tax_category_and_exemption_reason(doc, company, enforce_source_consistency=True)
    else:
        with pytest.raises(ValidationError):
            checks.validate_zatca_tax_category_and_exemption_reason(doc, company, enforce_source_consistency=True)
        assert env.runtime.throw.call_count == 1
    no_writes(env, doc)


@pytest.mark.parametrize("language", ["en", "ar"])
def test_template_only_label_is_retained_when_invoice_supplies_no_override(environment, language):
    env = environment
    env.language.value = language
    doc = invoice(env, [], "")
    doc.custom_exemption_reason_code = ""
    selected = checks._get_invoice_level_zatca_source(doc)
    key = "Sales Taxes and Charges Template {0}"
    assert selected["source_name"] == (env.translations[key] if language == "ar" else key).format("SYNTHETIC-TEMPLATE")
    assert selected["rate"] == 15
    no_writes(env, doc)
