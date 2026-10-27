"""Field precision versus installed v15 and pinned v16 function excerpts.

The v16 oracle executes ONLY reviewed helper excerpts with synthetic dependencies;
it is not an installed ERP16 runtime. No site, Redis, HTTP or real default is read.
"""

import ast
import __future__
from dataclasses import dataclass, FrozenInstanceError
import json
from pathlib import Path
import pickle
from types import SimpleNamespace

import frappe
from frappe.database.database import Database
from frappe.model.base_document import BaseDocument
from frappe.model.meta import get_field_precision
from frappe.utils import data as framework_data
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_precision as source
from zatca_erpgulf.zatca_erpgulf import calculation_defaults as defaults
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import load, row
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project


def declarations(*, kind="Currency", explicit=None, values=None, parent="__default", present=True):
    raw = AppliedMeta("Sales Invoice", ("grand_total",) if present else ())
    if present: raw.definitions["grand_total"].values.update(fieldtype=kind, precision=explicit)
    values = {"currency_precision": "2"} if values is None else values
    rows = [row("DEFAULT-" + str(index), key=key, value=value, parent=parent, offset=index)
        for index, (key, value) in enumerate(values.items())]
    return project(raw), load(rows, parent)[0]


def context(**changes):
    values = dict(language="ar", language_number_format=None,
        use_currency_format=False, currency="SAR", currency_number_format=None)
    values.update(changes)
    return source.CurrencyFormatContext(**values)


@pytest.fixture(scope="module")
def upstream16():
    """Strip dependency imports, preserving helper control flow verbatim.

    The source JSON records the full-file hashes and MIT notice. The installed
    Python is 3.10; the complete v16 Document file has newer Python syntax and
    is deliberately NEVER imported. Only these parseable excerpts are executed.
    """
    record = json.loads(Path(__file__).with_name("frappe16_precision_oracle.json").read_text())
    assert record["commit"] == "e8d41dd0061a32ee781caefe5d0b0d2bb7c15362"
    assert "The MIT License" in record["license"]
    namespace = {"dataclass": dataclass, "_dict": frappe._dict}
    class DependenciesOnly(ast.NodeTransformer):
        def visit_ImportFrom(self, node): return None
        def visit_ClassDef(self, node):
            node.decorator_list = [ast.Name(id="dataclass", ctx=ast.Load())]
            return self.generic_visit(node)
    for filename in ("utils/number_format.py", "utils/data.py", "locale.py", "model/meta.py", "model/document.py"):
        excerpts = record["files"][filename]["excerpts"]
        order = ("NUMBER_FORMAT_MAP", "NumberFormat") if filename.endswith("number_format.py") else tuple(excerpts)
        for name in order:
            tree = DependenciesOnly().visit(ast.parse(excerpts[name]))
            ast.fix_missing_locations(tree)
            exec(compile(tree, "pinned-frappe16/" + filename, "exec", flags=__future__.annotations.compiler_flag), namespace)
    return namespace


def oracle(major, upstream16, monkeypatch, definition, values, selected_context=None):
    def get_default(key):
        # Actual installed db.get_default list semantics, no SQL/default lookup.
        return Database.get_default(SimpleNamespace(get_defaults=lambda key, parent: values.get(key)), key)
    database = SimpleNamespace(get_default=get_default)
    if major == 15:
        monkeypatch.setattr(frappe, "db", database)
        return get_field_precision(definition)
    ctx = selected_context or context()
    database.get_value = lambda doctype, currency, field, cache: ctx.currency_number_format
    runtime = SimpleNamespace(db=database, local=SimpleNamespace(lang=ctx.language),
        get_system_settings=lambda field: ctx.use_currency_format,
        client_cache=SimpleNamespace(get_doc=lambda doctype, name: frappe._dict(number_format=ctx.language_number_format)))
    upstream16["frappe"] = runtime
    upstream16["get_field_currency"] = lambda df, doc: ctx.currency
    return upstream16["get_field_precision"](definition, currency=ctx.currency)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("kind", ["Currency", "Float", "Percent"])
@pytest.mark.parametrize("explicit", [None, "", 0, "0", False, 2, "2", 2.9, "2.9", "bad"])
@pytest.mark.parametrize("values", [
    {}, {"currency_precision": "0", "float_precision": "0"},
    {"currency_precision": "3", "float_precision": "4"},
    {"currency_precision": "bad", "float_precision": "bad"},
    {"number_format": "#.########"}, {"number_format": "#.###"},
])
def test_fresh_resolution_matches_real15_or_pinned16_helpers(upstream16, monkeypatch, major, kind, explicit, values):
    metadata, captured = declarations(kind=kind, explicit=explicit, values=values)
    selected_context = context() if major == 16 else None
    result = source.FieldPrecisionResolution(metadata, "grand_total", captured, major, selected_context)
    df = frappe._dict(fieldtype=kind, precision=explicit)
    assert result.precision == oracle(major, upstream16, monkeypatch, df, values, selected_context)
    assert result.metadata == metadata and result.metadata is not metadata
    assert result.defaults == captured and result.defaults is not captured


@pytest.mark.parametrize("number_format", tuple(source.FORMAT_PRECISIONS))
@pytest.mark.parametrize("major", [15, 16])
def test_format_precision_map_matches_actual_sources(upstream16, monkeypatch, number_format, major):
    metadata, captured = declarations(values={"number_format": number_format})
    result = source.FieldPrecisionResolution(metadata, "grand_total", captured, major, context() if major == 16 else None)
    assert result.precision == oracle(major, upstream16, monkeypatch,
        frappe._dict(fieldtype="Currency", precision=None), {"number_format": number_format})
    assert source.FORMAT_PRECISIONS[number_format] == framework_data.get_number_format_info(number_format)[2]
    assert source.FORMAT_PRECISIONS[number_format] == upstream16["NUMBER_FORMAT_MAP"][number_format][2]


@pytest.mark.parametrize("language_format", [None, "", "#.###", "#.########"])
@pytest.mark.parametrize("currency_format", [None, "", "#,###.###", "#.###"])
@pytest.mark.parametrize("use_currency", [False, True])
def test_v16_language_and_currency_format_precedence(upstream16, monkeypatch, language_format, currency_format, use_currency):
    metadata, captured = declarations(values={"number_format": "#,###.##"})
    ctx = source.CurrencyFormatContext("ar", language_format, use_currency, "SAR", currency_format)
    result = source.FieldPrecisionResolution(metadata, "grand_total", captured, 16, ctx)
    assert result.precision == oracle(16, upstream16, monkeypatch,
        frappe._dict(fieldtype="Currency", precision=None), {"number_format": "#,###.##"}, ctx)
    assert result.origin == ("CURRENCY_NUMBER_FORMAT" if use_currency and currency_format else "LOCALE_NUMBER_FORMAT")


def test_zero_default_is_a_real_version_difference_not_an_xml_rule():
    metadata, captured = declarations(values={"currency_precision": "0", "number_format": "#.########"})
    assert source.FieldPrecisionResolution(metadata, "grand_total", captured, 15).precision == 8
    assert source.FieldPrecisionResolution(metadata, "grand_total", captured, 16).precision == 0
    metadata, captured = declarations(explicit="0", values={"currency_precision": "5"})
    assert source.FieldPrecisionResolution(metadata, "grand_total", captured, 15).precision == 0
    assert source.FieldPrecisionResolution(metadata, "grand_total", captured, 16).precision == 0


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("kind", ["Data", "Int", "Long Int", "Check", "Date", "Time", "Rating", "Duration"])
def test_non_numeric_doc_precision_is_none_not_a_two_decimal_default(major, kind):
    metadata, captured = declarations(kind=kind)
    result = source.FieldPrecisionResolution(metadata, "grand_total", captured, major)
    assert result.precision is None and result.origin == "NON_NUMERIC_FIELD"
    result.require_cached_match(None)


@pytest.mark.parametrize("major", [15, 16])
def test_selected_absent_field_remains_none(major):
    metadata, captured = declarations(present=False)
    result = source.FieldPrecisionResolution(metadata, "grand_total", captured, major)
    assert result.precision is None and result.origin == "ABSENT_FIELD"


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("first", ["0", "2", ""])
def test_default_multivalue_rule_is_exact_and_ambiguous_false_first_is_refused(major, first):
    metadata, _ = declarations()
    captured = load([row(value=first), row("SECOND", value="4", offset=1)])[0]
    if first:
        result = source.FieldPrecisionResolution(metadata, "grand_total", captured, major)
        expected = (0 if major == 16 else 2) if first == "0" else 2
        assert result.precision == expected
    else:
        with pytest.raises(source.FieldPrecisionError): source.FieldPrecisionResolution(metadata, "grand_total", captured, major)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("unknown", ["not-a-format", "#,###.####"])
def test_unknown_format_falls_back_in15_but_fails_closed_in16(major, unknown):
    metadata, captured = declarations(values={"number_format": unknown})
    if major == 15: assert source.FieldPrecisionResolution(metadata, "grand_total", captured, major).precision == 2
    else:
        with pytest.raises(source.FieldPrecisionError): source.FieldPrecisionResolution(metadata, "grand_total", captured, major, context())


def test_v16_invalid_locale_is_not_hidden_by_a_valid_currency_override():
    metadata, captured = declarations(values={})
    ctx = source.CurrencyFormatContext("ar", "INVALID", True, "SAR", "#,###.##")
    with pytest.raises(source.FieldPrecisionError): source.FieldPrecisionResolution(metadata, "grand_total", captured, 16, ctx)


@pytest.mark.parametrize("fault", ["version", "bool_version", "scope", "field", "negative", "large", "metadata", "defaults", "context", "missing_v16_context", "v15_context"])
def test_unconfirmed_inputs_are_static_without_raw_diagnostics(fault):
    metadata, captured = declarations()
    kwargs = dict(metadata=metadata, fieldname="grand_total", defaults=captured, erp_major=15)
    if fault == "version": kwargs["erp_major"] = 17
    elif fault == "bool_version": kwargs["erp_major"] = True
    elif fault == "scope": kwargs["defaults"] = declarations(parent="__global")[1]
    elif fault == "field": kwargs["fieldname"] = "PRIVATE-UNKNOWN"
    elif fault in ("negative", "large"): kwargs["metadata"] = declarations(explicit="-1" if fault == "negative" else "65")[0]
    elif fault == "metadata": object.__setattr__(metadata, "sha256", "f" * 64)
    elif fault == "defaults": object.__setattr__(captured, "sha256", "f" * 64)
    elif fault == "context": kwargs.update(erp_major=16, currency_context="PRIVATE-CONTEXT")
    elif fault == "missing_v16_context": kwargs.update(erp_major=16, defaults=declarations(values={})[1])
    else: kwargs["currency_context"] = context()
    with pytest.raises(source.FieldPrecisionError) as caught: source.FieldPrecisionResolution(**kwargs)
    assert str(caught.value) == "calculation_field_precision" and caught.value.__context__ is None


@pytest.mark.parametrize("changes", [
    {"language": ""}, {"language": None}, {"language_number_format": 2},
    {"use_currency_format": "0"}, {"use_currency_format": 1},
    {"use_currency_format": True, "currency": None},
    {"currency": None, "currency_number_format": "#,###.##"}, {"currency_number_format": "X" * 4097},
])
def test_currency_context_is_explicit_bounded_and_typed(changes):
    values = dict(language="ar", language_number_format=None, use_currency_format=False, currency="SAR", currency_number_format=None)
    values.update(changes)
    with pytest.raises(source.FieldPrecisionError) as caught: source.CurrencyFormatContext(**values)
    assert str(caught.value) == "calculation_currency_format_context"


@pytest.mark.parametrize("major", [15, 16])
def test_actual_document_cache_stays_stale_and_must_be_compared_not_refreshed(upstream16, monkeypatch, major):
    values = {"currency_precision": "2"}
    df = frappe._dict(fieldtype="Currency", precision=None, fieldname="grand_total")
    metadata = SimpleNamespace(get_field=lambda field: df)
    doc = SimpleNamespace(doctype="Sales Invoice", meta=metadata)
    if major == 15:
        monkeypatch.setattr(frappe, "get_meta", lambda doctype: metadata)
        monkeypatch.setattr(frappe, "db", SimpleNamespace(get_default=lambda key: values.get(key)))
        precision = BaseDocument.precision
    else:
        oracle(16, upstream16, monkeypatch, df, values)
        upstream16["frappe"].get_meta = lambda doctype: metadata
        precision = upstream16["precision"]
    assert precision(doc, "grand_total") == 2
    values["currency_precision"] = "4"
    assert precision(doc, "grand_total") == 2
    selected, captured = declarations(values=values)
    resolved = source.FieldPrecisionResolution(selected, "grand_total", captured, major)
    before = dict(doc._precision["main"])
    with pytest.raises(source.FieldPrecisionError, match="^calculation_precision_cache_mismatch$"):
        resolved.require_cached_match(precision(doc, "grand_total"))
    assert dict(doc._precision["main"]) == before and resolved.precision == 4


@pytest.mark.parametrize("cached", [True, 2.0, "2", None, 3])
def test_cache_comparison_rejects_equal_but_differently_typed_or_changed_values(cached):
    metadata, captured = declarations()
    resolved = source.FieldPrecisionResolution(metadata, "grand_total", captured, 15)
    with pytest.raises(source.FieldPrecisionError): resolved.require_cached_match(cached)


def test_protected_results_bind_exact_parents_and_reject_modified_derived_precision():
    metadata, captured = declarations()
    resolved = source.FieldPrecisionResolution(metadata, "grand_total", captured, 15)
    resolved.require_cached_match(2)
    assert "grand_total" not in repr(resolved)
    with pytest.raises(FrozenInstanceError): resolved.precision = 8
    for value in (resolved, context()):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(value)
    object.__setattr__(resolved, "precision", 9)
    with pytest.raises(source.FieldPrecisionError): resolved.require_cached_match(9)
