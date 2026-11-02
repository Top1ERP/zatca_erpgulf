"""Raw getter identity and actual15/pinned16 explicit-fix observations."""

from dataclasses import replace
from decimal import Decimal
import json
import pickle
from types import SimpleNamespace

from frappe.model.base_document import BaseDocument
from pymysql.constants import FIELD_TYPE as FT
import pytest

from zatca_erpgulf.zatca_erpgulf import financial_numeric_view as view
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import scenario, reader, load
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16


def native_case(monkeypatch, *, doctype="Sales Invoice", major=16, optional=True):
    case = scenario(doctype, optional=optional)
    handle, _ = reader(case, monkeypatch)
    case.native = load(case, handle, major)
    return case


def values(native):
    return tuple((group, row, name, financial._validate_scalar(raw))
        for group, row, name, _, raw in view._native_cells(native))


def fixed_values(native, major, upstream16, monkeypatch):
    """Execute framework numeric-fix bodies, not the product projection helper."""
    data = {(group, row, name): value for group, row, name, value in values(native)}
    grouped = {}
    for group, row, name, kind, _ in view._native_cells(native):
        grouped.setdefault((group, row), []).append(SimpleNamespace(fieldname=name, fieldtype=kind))
    for (group, row), definitions in grouped.items():
        doc = SimpleNamespace(docstatus=1,
            get=lambda name: data[group, row, name], set=lambda name, value: data.__setitem__((group, row, name), value),
            meta=SimpleNamespace(get=lambda *args: definitions))
        if major == 15:
            BaseDocument._fix_numeric_types(doc)
        else:
            monkeypatch.setitem(upstream16, "numeric_fieldtypes", tuple(view.REAL_TYPES))
            upstream16["_fix_numeric_types"](doc)
    return tuple((group, row, name, data[group, row, name]) for group, row, name, _, _ in view._native_cells(native))


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("optional", [False, True])
def test_saved_and_explicit_fixed_views_preserve_original_native_parent(monkeypatch, upstream16, doctype, major, optional):
    case = native_case(monkeypatch, doctype=doctype, major=major, optional=optional)
    before = case.native._payload, case.native.financial._payload, case.native.sha256
    saved = view.InvoiceNumericView.from_values(case.native, stage="SAVED", values=values(case.native))
    fixed = saved.observe_fixed(fixed_values(case.native, major, upstream16, monkeypatch))
    assert fixed.stage == "NUMERIC_FIXED" and saved.stage == "SAVED"
    assert saved.financial == fixed.financial == case.native
    assert saved.sha256 != fixed.sha256
    saved.require_match(values(case.native))
    assert before == (case.native._payload, case.native.financial._payload, case.native.sha256)
    assert {cell[0] for cell in json.loads(saved._payload)["cells"]} >= {"header", "items", "taxes"}


@pytest.mark.parametrize("raw", [None, Decimal("0.000000000"), Decimal("-0.000000000"), Decimal("8.700000000")])
@pytest.mark.parametrize("major", [15, 16])
def test_null_scale_and_signed_zero_follow_actual_fix_without_rounding(monkeypatch, upstream16, raw, major):
    case = scenario()
    case.records["header"][0]["grand_total"] = raw
    handle, _ = reader(case, monkeypatch)
    native = load(case, handle, major)
    saved = view.InvoiceNumericView.from_values(native, stage="SAVED", values=values(native))
    fixed = saved.observe_fixed(fixed_values(native, major, upstream16, monkeypatch))
    prior = next(cell[3] for cell in json.loads(saved._payload)["cells"] if cell[:3] == ["header", native.financial.name, "grand_total"])
    after = next(cell[3] for cell in json.loads(fixed._payload)["cells"] if cell[:3] == ["header", native.financial.name, "grand_total"])
    assert prior == financial._scalar(raw)
    assert after == (["null"] if raw is None else ["float", float(raw).hex()])


@pytest.mark.parametrize("major", [15, 16])
def test_large_derived_float_does_not_weaken_raw_scalar_bound(monkeypatch, upstream16, major):
    case = scenario()
    case.records["header"][0]["grand_total"] = Decimal("9" * 64)
    case.connection.signatures["header", "grand_total"] = [FT.NEWDECIMAL, 64, 0, True]
    handle, _ = reader(case, monkeypatch)
    native = load(case, handle, major)
    observed = view.InvoiceNumericView.from_values(native, stage="SAVED", values=values(native))
    fixed = observed.observe_fixed(fixed_values(native, major, upstream16, monkeypatch))
    assert fixed.financial == native
    with pytest.raises(ValueError): financial._scalar(1e64)


@pytest.mark.parametrize("fault", ["drop", "extra", "order", "row", "field", "float", "scale", "bool", "text", "nonfinite"])
def test_wrong_saved_values_or_membership_are_not_repaired(monkeypatch, fault):
    native = native_case(monkeypatch).native
    observed = list(values(native))
    i = next(i for i, v in enumerate(observed) if v[2] == "grand_total")
    group, row, name, value = observed[i]
    if fault == "drop": observed.pop()
    elif fault == "extra": observed.append(observed[-1])
    elif fault == "order": observed.reverse()
    else:
        replacements = {"row": (group,"OTHER",name,value), "field": (group,row,"OTHER",value),
            "float": (group,row,name,8.7), "scale": (group,row,name,Decimal("8.7")),
            "bool": (group,row,name,False), "text": (group,row,name,"8.700000000"),
            "nonfinite": (group,row,name,float("nan"))}
        observed[i] = replacements[fault]
    with pytest.raises(view.FinancialNumericViewError): view.InvoiceNumericView.from_values(native, stage="SAVED", values=tuple(observed))


def test_protected_views_cannot_drop_rebind_or_change_stage(monkeypatch):
    native = native_case(monkeypatch).native
    saved = view.InvoiceNumericView.from_values(native, stage="SAVED", values=values(native))
    with pytest.raises(view.FinancialNumericViewError): replace(saved, stage="NUMERIC_FIXED")
    with pytest.raises(view.FinancialNumericViewError): replace(saved, financial=None)
    with pytest.raises(view.FinancialNumericViewError): replace(saved, _payload=b"{}")
    assert "SYNTHETIC" not in repr(saved)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(saved)


@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("kind", sorted(view.REAL_TYPES))
def test_only_framework_converted_fieldtypes_change_representation(monkeypatch, upstream16, major, kind):
    case = scenario()
    case.raw_metas[case.doctype].definitions["grand_total"].values["fieldtype"] = kind
    case.metas[case.doctype] = project(case.raw_metas[case.doctype])
    case.observations[case.doctype] = observed_metadata(case.raw_metas[case.doctype])
    handle, _ = reader(case, monkeypatch)
    native = load(case, handle, major)
    fixed = view.InvoiceNumericView.from_values(native, stage="NUMERIC_FIXED", values=fixed_values(native, major, upstream16, monkeypatch))
    cell = next(cell[3] for cell in json.loads(fixed._payload)["cells"] if cell[2] == "grand_total")
    assert cell[0] == ("float" if kind in view.FIXED_TYPES else "decimal")


@pytest.mark.parametrize("fault", ["null_zero", "decimal", "nonfinite", "wrong_float"])
def test_fixed_observations_do_not_silently_repair_or_round_values(monkeypatch, upstream16, fault):
    case = scenario()
    if fault == "null_zero": case.records["header"][0]["grand_total"] = None
    handle, _ = reader(case, monkeypatch)
    native = load(case, handle)
    observed = list(fixed_values(native, 15, upstream16, monkeypatch))
    i = next(i for i, cell in enumerate(observed) if cell[2] == "grand_total")
    replacements = dict(null_zero=0.0, decimal=Decimal("8.700000000"), nonfinite=float("inf"), wrong_float=8.700000000001)
    observed[i] = (*observed[i][:3], replacements[fault])
    with pytest.raises(view.FinancialNumericViewError): view.InvoiceNumericView.from_values(native, stage="NUMERIC_FIXED", values=tuple(observed))
