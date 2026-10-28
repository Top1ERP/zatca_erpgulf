"""Direct-child semantics against installed15/pinned16; synthetic inputs only."""

from copy import deepcopy
from dataclasses import replace
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import frappe
from frappe.model.meta import get_field_currency
from frappe.utils import cstr
import pytest

from zatca_erpgulf.zatca_erpgulf import child_field_currency as source
from zatca_erpgulf.zatca_erpgulf.calculation_precision import CurrencyFormatContext
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16, declarations
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project


def text(value):
    return source.NULL if value is None else ("str", value)


def inputs(doctype="Sales Invoice", **changes):
    values = dict(doctype=doctype + " Item", name="SYNTHETIC-ROW", parenttype=doctype,
        parent="SYNTHETIC-INVOICE", parentfield="items", row_currency=source.ABSENT,
        row_company=source.ABSENT, parent_has_currency=True, parent_currency=text("USD"))
    values.update(changes)
    return source.ChildCurrencyInputs(**values)


def resolution(*, declared=None, major=16, options="currency", explicit=None):
    declared = declared or inputs()
    raw = AppliedMeta(declared.doctype, ("amount",))
    raw.definitions["amount"].values.update(fieldtype="Currency", options=options, precision=explicit)
    return source.ChildFieldCurrencyResolution(project(raw), "amount", declared, major)


def oracle(upstream16, monkeypatch, declared, major, options, *, cache=None):
    """Execute unchanged helper control flow with ONLY synthetic dependencies."""
    doc = frappe._dict({name: getattr(declared, name)
        for name in ("doctype", "name", "parenttype", "parent", "parentfield")})
    for key, value in (("currency", declared.row_currency), ("company", declared.row_company)):
        if value != source.ABSENT:
            doc[key] = source._text(value)
    if declared.parent_doc_currency != source.ABSENT:
        doc.parent_doc = frappe._dict(currency=source._text(declared.parent_doc_currency))
    parent_read = Mock(return_value=source._text(declared.parent_currency))
    company_read = Mock(return_value=source._text(declared.company_lookup[1]) if declared.company_lookup else None)
    meta_read = Mock(return_value=SimpleNamespace(has_field=lambda name: name == "currency" and declared.parent_has_currency))
    runtime = SimpleNamespace(local=SimpleNamespace(field_currency=deepcopy(cache or {})),
        _dict=frappe._dict, db=SimpleNamespace(get_value=parent_read), get_meta=meta_read,
        get_cached_value=company_read)
    definition = frappe._dict(fieldname="amount", fieldtype="Currency", options=options)
    if major == 15:
        monkeypatch.setattr(frappe, "local", runtime.local)
        monkeypatch.setattr(frappe, "db", runtime.db, raising=False)
        monkeypatch.setattr(frappe, "get_meta", meta_read)
        monkeypatch.setattr(frappe, "get_cached_value", company_read)
        currency = get_field_currency(definition, doc)
    else:
        upstream16["frappe"], upstream16["cstr"] = runtime, cstr
        currency = upstream16["get_field_currency"](definition, doc)
    if parent_read.called:
        parent_read.assert_called_once_with(declared.parenttype, declared.parent, "currency")
    if company_read.called:
        company_read.assert_called_once_with("Company", source._text(declared.row_company), "default_currency")
    return SimpleNamespace(currency=currency, cache=runtime.local.field_currency,
        parent_read=parent_read, company_read=company_read, meta_read=meta_read)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("own", [source.ABSENT, source.NULL, text(""), text("SAR"), text("USD")])
@pytest.mark.parametrize("parent", [text("USD"), source.NULL, text("")])
def test_plain_currency_matches_helper_lookup_and_exact_cache_owner(upstream16, monkeypatch, doctype, major, own, parent):
    declared = inputs(doctype, row_currency=own, parent_currency=parent)
    fresh = resolution(declared=declared, major=major)
    actual = oracle(upstream16, monkeypatch, declared, major, "currency")
    assert fresh.currency == actual.currency
    if fresh.currency:
        assert actual.cache == {fresh.cache_key: {"amount": fresh.currency}}
        assert fresh.cache_key == (declared.doctype, declared.name if source._text(own) else declared.parent)
    else:
        assert not actual.cache and fresh.cache_key is None
    assert actual.parent_read.call_count == (0 if source._text(own) else 1)
    actual.company_read.assert_not_called()


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("parent_has", [False, True])
@pytest.mark.parametrize("parent_doc", [source.ABSENT, source.NULL, text(""), text("EUR")])
def test_parent_doc_fallback_is_v16_only_and_requires_parent_field(upstream16, monkeypatch, major, parent_has, parent_doc):
    declared = inputs(parent_has_currency=parent_has,
        parent_currency=source.NULL if parent_has else source.ABSENT, parent_doc_currency=parent_doc)
    fresh = resolution(declared=declared, major=major)
    actual = oracle(upstream16, monkeypatch, declared, major, "currency")
    assert fresh.currency == actual.currency == ("EUR" if major == 16 and parent_has and parent_doc == text("EUR") else None)
    assert fresh.origin == ("PARENT_DOCUMENT_CURRENCY" if fresh.currency else "UNRESOLVED")
    assert actual.parent_read.call_count == int(parent_has)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("company", [source.ABSENT, source.NULL, text(""), text("SYNTHETIC-CHILD-CO")])
@pytest.mark.parametrize("looked_up", [source.NULL, text(""), text("SAR")])
def test_colon_option_uses_only_child_company_and_parent_cache_key(upstream16, monkeypatch, doctype, major, company, looked_up):
    present = bool(source._text(company))
    declared = inputs(doctype, row_currency=text("EUR"), row_company=company,
        company_lookup=(source._text(company), looked_up) if present else ())
    fresh = resolution(declared=declared, major=major, options="Company:company:default_currency")
    actual = oracle(upstream16, monkeypatch, declared, major, "Company:company:default_currency")
    assert fresh.currency == actual.currency
    assert actual.company_read.call_count == int(present)
    actual.parent_read.assert_not_called()
    actual.meta_read.assert_not_called()
    assert fresh.cache_key == ((declared.doctype, declared.parent) if fresh.currency else None)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("own", [source.ABSENT, text("USD")])
@pytest.mark.parametrize("row_entry", [source.ABSENT, source.NULL, text(""), text("USD"), text("SAR")])
@pytest.mark.parametrize("parent_entry", [source.ABSENT, source.NULL, text(""), text("USD"), text("SAR")])
def test_effective_existing_cache_precedence_and_stale_detection(upstream16, monkeypatch, major, own, row_entry, parent_entry):
    declared = inputs(row_currency=own)
    fresh = resolution(declared=declared, major=major)
    cache = {}
    for key, slot in ((declared.name, row_entry), (declared.parent, parent_entry)):
        if slot != source.ABSENT:
            cache[(declared.doctype, key)] = {"amount": source._text(slot)}
    original = deepcopy(cache)
    actual = oracle(upstream16, monkeypatch, declared, major, "currency", cache=cache)
    if actual.currency != fresh.currency:
        with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_cache_mismatch$"):
            fresh.require_cached_match(row_entry=row_entry, parent_entry=parent_entry)
    else:
        fresh.require_cached_match(row_entry=row_entry, parent_entry=parent_entry)
    assert actual.parent_read.call_count == int(not (source._text(row_entry) or source._text(parent_entry) or source._text(own)))
    assert cache == original


@pytest.mark.parametrize("major", [15, 16])
def test_parent_doctype_cache_is_not_the_child_parent_cache(upstream16, monkeypatch, major):
    declared = inputs()
    actual = oracle(upstream16, monkeypatch, declared, major, "currency",
        cache={(declared.parenttype, declared.parent): {"amount": "SAR"}})
    assert actual.currency == resolution(declared=declared, major=major).currency == "USD"
    actual.parent_read.assert_called_once()


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("entry", [source.ABSENT, source.NULL, text(""), text("USD"), text("SAR")])
def test_equal_row_and_parent_names_share_one_cache_slot(upstream16, monkeypatch, major, entry):
    declared = inputs(name="SYNTHETIC-INVOICE")
    fresh = resolution(declared=declared, major=major)
    cache = {} if entry == source.ABSENT else {(declared.doctype, declared.name): {"amount": source._text(entry)}}
    actual = oracle(upstream16, monkeypatch, declared, major, "currency", cache=cache)
    if actual.currency == fresh.currency:
        fresh.require_cached_match(row_entry=entry, parent_entry=entry)
    else:
        with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_cache_mismatch$"):
            fresh.require_cached_match(row_entry=entry, parent_entry=entry)
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_cache_mismatch$"):
        fresh.require_cached_match(row_entry=text("USD"), parent_entry=text("SAR"))


@pytest.mark.parametrize("major", [15, 16])
def test_cached_parent_company_currency_cannot_substitute_for_missing_child_link(upstream16, monkeypatch, major):
    declared = inputs()
    fresh = resolution(declared=declared, major=major, options="Company:company:default_currency")
    assert fresh.currency is None
    actual = oracle(upstream16, monkeypatch, declared, major, "Company:company:default_currency",
        cache={(declared.doctype, declared.parent): {"amount": "SAR"}})
    assert actual.currency == "SAR"
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_cache_mismatch$"):
        fresh.require_cached_match(parent_entry=text("SAR"))


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("explicit,default,expected", [("4", "", 4), (None, "2", 2), (None, "0", 0)])
def test_configured_precision_does_not_need_a_resolved_currency(major, explicit, default, expected):
    fresh = resolution(major=major, explicit=explicit, options="Company:company:default_currency")
    _, defaults = declarations(values={"currency_precision": default})
    result = fresh.resolve_precision(defaults)
    assert result.precision == (2 if major == 15 and default == "0" and not explicit else expected)
    assert result.currency_context is None


@pytest.mark.parametrize("currency,expected", [("USD", 3), ("SAR", 8)])
def test_direct_child_currency_is_bound_to_consumed_format(currency, expected):
    fresh = resolution(declared=inputs(row_currency=text(currency)))
    _, defaults = declarations(values={"currency_precision": ""})
    context = CurrencyFormatContext("ar", None, True, currency, "#,###.###" if currency == "USD" else "#.########")
    assert fresh.resolve_precision(defaults, currency_context=context).precision == expected
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_precision$"):
        fresh.resolve_precision(defaults, currency_context=replace(context, currency="EUR"))


def test_unresolved_currency_allows_locale_only_without_querying_currency_none():
    fresh = resolution(options="Company:company:default_currency")
    _, defaults = declarations(values={"currency_precision": ""})
    context = CurrencyFormatContext("ar", "#.########", False, None, None)
    assert fresh.resolve_precision(defaults, currency_context=context).precision == 8
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_precision$"):
        fresh.resolve_precision(defaults, currency_context=CurrencyFormatContext("ar", None, True, "SAR", "#.########"))


@pytest.mark.parametrize("change", [
    {"parenttype": "Customer"}, {"doctype": "POS Invoice Item"}, {"parentfield": "company"},
    {"name": ""}, {"parent": ""}, {"parent_has_currency": 1},
    {"parent_has_currency": False}, {"row_currency": ["str", "SAR"]},
    {"row_currency": ("str", False)}, {"row_currency": ("str", "X" * 4097)},
    {"row_company": ("str", "secret\0")}, {"parent_doc_currency": ("other",)},
    {"company_lookup": ("OTHER", text("SAR"))},
    {"row_company": text("A"), "company_lookup": ("B", text("SAR"))},
])
def test_invalid_or_cross_bound_inputs_are_refused_without_disclosure(change):
    with pytest.raises(source.ChildFieldCurrencyError) as caught:
        inputs(**change)
    assert str(caught.value) == "child_currency_inputs" and caught.value.__context__ is None


@pytest.mark.parametrize("options", [None, "", "other_currency", "Company:company:default_currency:extra"])
def test_unreviewed_options_are_not_guessed(options):
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_resolution$"):
        resolution(options=options)


def test_missing_company_lookup_is_not_a_known_null_currency():
    declared = inputs(row_company=text("SYNTHETIC-CO"))
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_resolution$"):
        resolution(declared=declared, options="Company:company:default_currency")
    assert resolution(declared=replace(declared, company_lookup=("SYNTHETIC-CO", source.NULL)),
        options="Company:company:default_currency").currency is None


@pytest.mark.parametrize("fault", ["parent_metadata", "child_metadata", "field_type", "field_name", "version_bool", "version_text", "version_unknown"])
def test_unrelated_metadata_and_version_are_refused(fault):
    fresh = resolution()
    changes = {}
    if fault in ("parent_metadata", "child_metadata", "field_type"):
        raw = AppliedMeta("Sales Invoice" if fault == "parent_metadata" else "POS Invoice Item" if fault == "child_metadata" else fresh.inputs.doctype, ("amount",))
        raw.definitions["amount"].values.update(fieldtype="Data" if fault == "field_type" else "Currency", options="currency")
        changes["metadata"] = project(raw)
    elif fault == "field_name":
        changes["fieldname"] = "unselected"
    else:
        changes["erp_major"] = True if fault == "version_bool" else "16" if fault == "version_text" else 17
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_resolution$"):
        replace(fresh, **changes)


@pytest.mark.parametrize("bad", [False, 0, 1, ["str", "USD"], text("X" * 4097), text("USD\0"), ("str", False)])
def test_malformed_cache_is_refused_even_if_other_entry_would_win(bad):
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_cache_mismatch$"):
        resolution().require_cached_match(row_entry=text("USD"), parent_entry=bad)


def test_absent_null_blank_are_distinct_declarations_with_same_fresh_behavior():
    observed = [resolution(declared=inputs(row_currency=value)) for value in (source.ABSENT, source.NULL, text(""))]
    assert {item.currency for item in observed} == {"USD"}
    assert len({item.sha256 for item in observed}) == 3


@pytest.mark.parametrize("target", ["inputs", "currency", "origin", "cache_key", "sha256"])
def test_reconstruction_rejects_tampered_derived_values_before_cache_use(target):
    fresh = resolution()
    if target == "inputs":
        object.__setattr__(fresh.inputs, "row_currency", ["str", "SAR"])
    else:
        object.__setattr__(fresh, target, "PRIVATE-TAMPER")
    with pytest.raises(source.ChildFieldCurrencyError, match="^child_currency_cache_mismatch$"):
        fresh.require_cached_match(row_entry=text("USD"))


def test_protected_representation_and_no_pickle():
    fresh = resolution()
    assert "SYNTHETIC" not in repr(fresh) + repr(fresh.inputs)
    for value in (fresh, fresh.inputs):
        with pytest.raises(TypeError, match="not_serializable"):
            pickle.dumps(value)
