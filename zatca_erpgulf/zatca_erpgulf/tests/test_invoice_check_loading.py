"""Actual15/pinned16 scalar saved-load versus explicit numeric-fix stages.

Only DB return values and metadata/child infrastructure are synthetic. No site,
SQL/socket, controller hooks, money persistence or complete ERP16 import.
"""

import __future__
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace, FunctionType
from unittest.mock import Mock

import frappe
from frappe.model import document as model_document
from frappe.model.document import Document as Document15
from frappe.utils import data as framework_data
from frappe.utils import get_table_name
import pytest

from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


@pytest.fixture(scope="module")
def loading16(upstream16):
    record = json.loads(Path(__file__).with_name("frappe16_precision_oracle.json").read_text())
    assert record["commit"] == "e8d41dd0061a32ee781caefe5d0b0d2bb7c15362"
    assert "The MIT License" in record["license"]
    selected = record["files"]["model/document.py"]["saved_loading"]
    namespace = {**upstream16, "CACHED_PROPERTIES": tuple(selected["cached_properties"])}
    exec(compile(selected["reserved_keywords_source"], "pinned-frappe16/reserved", "exec"), namespace)
    for name, text in selected["excerpts"].items():
        exec(compile(text, "pinned-frappe16/saved-loading/" + name, "exec", flags=__future__.annotations.compiler_flag), namespace)
    return namespace


def load_probe(major, loading16, monkeypatch, *, doctype="Sales Invoice", raw=None, amount=Decimal("8.700000000")):
    singleton = doctype == "Global Defaults"
    row = dict(name="SYNTHETIC-SAVED", docstatus=0, idx=0, is_consolidated=raw,
        disable_rounded_total=raw, grand_total=amount)
    fields = [frappe._dict(fieldname=name, fieldtype="Check", default="1") for name in ("is_consolidated", "disable_rounded_total")]
    fields.append(frappe._dict(fieldname="grand_total", fieldtype="Currency"))
    meta = SimpleNamespace(issingle=singleton, get_table_fields=lambda: [], get=lambda *args: fields)
    db = SimpleNamespace(get_value=Mock(side_effect=lambda **kwargs: frappe._dict(row)),
        get_singles_dict=Mock(side_effect=lambda *args, **kwargs: frappe._dict(row)),
        sql=Mock(side_effect=lambda *args, **kwargs: [frappe._dict(row)]), db_type="mariadb")
    runtime = SimpleNamespace(db=db, InvalidRoundingMethod=type("InvalidRoundingMethod", (Exception,), {}),
        get_system_settings=Mock(side_effect=AssertionError("Precision-free conversion must not read rounding settings")))
    if major == 15:
        monkeypatch.setattr(model_document, "frappe", runtime)
        monkeypatch.setattr(framework_data, "frappe", runtime)
        doc = Document15.__new__(Document15)
    else:
        namespace = dict(loading16)
        namespace["frappe"], namespace["numeric_fieldtypes"] = runtime, ("Check", "Currency")
        namespace["get_table_name"] = get_table_name
        # Rebind to this probe's dependency namespace, retaining function bodies.
        functions = {}
        for name in ("cint", "flt", "_fix_numeric_types", "load_from_db", "init_from_dict", "update", "get", "set", "init_valid_columns"):
            fn = loading16[name]
            copied = FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__, fn.__closure__)
            namespace[name] = copied
            if name not in ("cint", "flt"):
                functions[name] = copied
        functions["load_children_from_db"] = lambda self: None
        doc = type("PinnedScalarDocument16", (), functions)()
        doc._table_fieldnames = {}
    doc.doctype, doc.name, doc.flags, doc.meta = doctype, "SYNTHETIC-SAVED", frappe._dict(for_update=False), meta
    doc.get_valid_columns = lambda: list(row)
    original_fix = doc._fix_numeric_types
    doc._fix_numeric_types = Mock(wraps=original_fix)
    doc.load_from_db()
    return SimpleNamespace(doc=doc, row=row, db=db, singleton=singleton, runtime=runtime)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice", "Global Defaults"])
@pytest.mark.parametrize("raw", [None, 0, 1])
@pytest.mark.parametrize("amount", [None, Decimal("8.700000000")])
def test_regular_load_preserves_scalars_while_singleton_or_explicit_fix_normalizes(loading16, monkeypatch, major, doctype, raw, amount):
    case = load_probe(major, loading16, monkeypatch, doctype=doctype, raw=raw, amount=amount)
    doc = case.doc
    if case.singleton:
        assert type(doc.get("is_consolidated")) is int and doc.get("is_consolidated") == (raw or 0)
        assert type(doc.get("grand_total")) is (type(None) if amount is None else float)
        assert doc._fix_numeric_types.call_count == 1
        case.db.get_singles_dict.assert_called_once()
        case.db.get_value.assert_not_called()
        case.db.sql.assert_not_called()
    else:
        assert type(doc.get("is_consolidated")) is type(raw) and doc.get("is_consolidated") == raw
        assert type(doc.get("grand_total")) is type(amount) and doc.get("grand_total") == amount
        doc._fix_numeric_types.assert_not_called()
        (case.db.get_value if major == 15 else case.db.sql).assert_called_once()
        doc._fix_numeric_types()
        assert doc.get("is_consolidated") == (raw or 0) and type(doc.get("is_consolidated")) is int
        assert type(doc.get("grand_total")) is (type(None) if amount is None else float)
    assert case.row["is_consolidated"] is raw and case.row["grand_total"] is amount
    assert "ignore_children" not in doc.flags
    case.runtime.get_system_settings.assert_not_called()
