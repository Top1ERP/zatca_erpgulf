"""Actual15/pinned16 prefix bodies on NEW private SQL evidence, no site I/O."""

from dataclasses import replace
import json
import os
import pickle
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_outstanding_prefix import (
    OutstandingPrefixCalculation, INPUT_FIELDS, ROUND_FIELDS,
)
from zatca_erpgulf.zatca_erpgulf.calculation_receivable import PAYABLE_FIELDS
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_access import SettlementAccessError
from zatca_erpgulf.zatca_erpgulf.financial_numeric_view import _native_cells, _expected
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _validate_scalar
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_access_mariadb import (
    native_case, capture, empty_pos_sources, combined_schema, defaults_schema, financial_schema, metadata_schema,
    isolated_server, connections, untouched, format_schema, field_schema, empty_sources, selected_schema, pos_schema,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, PermissionDenied, InspectionFailed, one_failure,
)
from zatca_erpgulf.zatca_erpgulf.calculation_defaults_access import FINANCIAL_DENIED_MESSAGE
from zatca_erpgulf.zatca_erpgulf.calculation_defaults_access import FINANCIAL_FAILED_MESSAGE
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guarded temporary SQL only; no tenant or authority access")


def observe(source, major, upstream16, monkeypatch, values, representation="CALCULATED"):
    """Execute unchanged primary methods; observe inputs, writes and calls."""
    plan = OutstandingPrefixCalculation(source, representation, values)
    raw = source.prefix.method.rounding.value
    oracle = framework(major, upstream16, monkeypatch, setting=raw)
    precision_values = {proof.target[2]: proof.precision.precision for proof in source.prefix.fields}
    precision_values.update((name, proof.precision) for name, proof in source.receivable.precisions)
    precision_trace = []
    doc = SimpleNamespace(**dict(values))
    doc.get = lambda name: getattr(doc, name, None)
    doc.set = lambda name, value: setattr(doc, name, value)
    rounding = True
    def precision(name, parentfield=None):
        precision_trace.append((name, parentfield, precision_values[name]) if rounding else (name, precision_values[name]))
        return precision_values[name]
    doc.precision = precision
    settings = lambda: tuple((call.args[0], raw) for call in oracle.runtime.get_system_settings.call_args_list)
    oracle.method(doc, doc, list(ROUND_FIELDS))
    rounded = tuple((name, doc.get(name)) for name in ROUND_FIELDS)
    round_settings, round_precision = settings(), tuple(precision_trace)
    rounding = False
    precision_trace.clear()
    start = len(settings())
    controller("_set_in_company_currency", major, {"flt": oracle.flt})(SimpleNamespace(doc=doc), doc, ["write_off_amount"])
    observed = dict(rounded=rounded, payable_values=tuple((name, doc.get(name)) for name in PAYABLE_FIELDS),
        round_settings=round_settings, round_precision=round_precision,
        conversion_settings=settings()[start:], conversion_precision=tuple(precision_trace))
    plan.require_match(**observed)
    return plan, observed


def fixed_values(source):
    native = source.prefix.numeric.view.financial
    cells = {cell[2]: cell for cell in _native_cells(native) if cell[0] == "header"}
    side = dict(json.loads(source.receivable.write_off._payload)["fields"])
    result = []
    for name in INPUT_FIELDS:
        if name in side: tag = _expected(side[name], "NUMERIC_FIXED", "Currency")
        else: tag = _expected(cells[name][4], "NUMERIC_FIXED", cells[name][3])
        result.append((name, _validate_scalar(tag)))
    return tuple(result)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("raw", [None, "", "Commercial Rounding"])
def test_round_then_source_round_then_fx_matches_primary_bits_and_lookup_order(defaults_operator, connections, monkeypatch, upstream16, major, raw):
    case = native_case(defaults_operator, connections)
    case.round_doc.rounding_method = raw
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'", (raw,))
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    source = capture(case, major)
    for amount in (2.675, -2.675, None):
        values = tuple(zip(INPUT_FIELDS, (amount, None, -18.98765, 0, amount, amount, 99.99, 3.1415926)))
        plan, observed = observe(source, major, upstream16, monkeypatch, values)
        assert observed["conversion_precision"] == (("write_off_amount", 2), ("base_write_off_amount", 3))
        assert len(observed["round_settings"]) == (4 if not raw and amount is not None else 1)
        assert len(observed["conversion_settings"]) == 2
        assert dict(plan.payable_values)["rounded_total"] is None
        assert type(dict(plan.payable_values)["base_rounded_total"]) is int
        assert dict(plan.payable_values)["base_write_off_amount"] != 99.99
        assert "99.99" not in repr(plan) and case.invoice.name not in repr(plan)
    observe(source, major, upstream16, monkeypatch, fixed_values(source), "NUMERIC_FIXED")
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
def test_prefix_refuses_trace_amount_source_and_derived_evidence_tampering(defaults_operator, connections, monkeypatch, upstream16):
    case = native_case(defaults_operator, connections)
    source = capture(case)
    values = tuple(zip(INPUT_FIELDS, (2.675, 0.0, 4.0, 0.0, 1.111, -2.675, 999.0, 3.1415926)))
    plan, observed = observe(source, 16, upstream16, monkeypatch, values)
    for key, wrong in (("rounded", tuple(reversed(observed["rounded"]))),
            ("payable_values", observed["payable_values"][:-1]), ("round_settings", ()),
            ("round_precision", (("grand_total", None, 2.0), *observed["round_precision"][1:])),
            ("conversion_settings", observed["conversion_settings"][:1]),
            ("conversion_precision", tuple(reversed(observed["conversion_precision"])) )):
        with pytest.raises(SettlementAccessError) as caught:
            plan.require_match(**{**observed, key: wrong})
        assert str(caught.value) == "settlement_outstanding_prefix_observation" and caught.value.__context__ is None
    other_owner = source.prefix.owner_document + 1
    other_prefix = replace(source.prefix, owner_document=other_owner,
        fields=tuple(replace(proof, owner_document=other_owner) for proof in source.prefix.fields))
    with pytest.raises(SettlementAccessError): replace(source, prefix=other_prefix)
    changed = dict(values);changed["grand_total"] += 1.0
    with pytest.raises(SettlementAccessError): OutstandingPrefixCalculation(source, "NUMERIC_FIXED", tuple(changed.items()))
    with pytest.raises(TypeError): pickle.dumps(plan)
    object.__setattr__(plan, "round_lookups", float(plan.round_lookups))
    with pytest.raises(SettlementAccessError): plan.pin()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
def test_advance_precision_read_is_authorized_before_any_callbacks(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    case.field_overrides[case.invoice.doctype, "total_advance"].values["permlevel"] = 2
    with pytest.raises(PermissionDenied): capture(case)
    case.factory.assert_not_called();case.metadata_provider.assert_not_called();case.cache.assert_not_called()
    one_failure(defaults_operator, FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
def test_prefix_handoff_preserves_null_rounded_totals_and_rejects_shifted_rate_or_amount(defaults_operator, connections, monkeypatch, upstream16):
    from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_sequence_mariadb import sequence, primary_probe
    case = native_case(defaults_operator, connections)
    result = sequence(capture(case))
    changed = dict(result.prefix.values)
    changed.update(rounded_total=None, base_rounded_total=None)
    prefix = replace(result.prefix, values=tuple(changed.items()))
    payable = replace(result.payable, values=prefix.payable_values)
    result = replace(result, prefix=prefix, payable=payable,
        change=replace(result.change, headers=payable.values[:4]),
        outstanding=replace(result.outstanding, payable=payable))
    primary_probe(result, 16, upstream16, monkeypatch)
    for name, value in (("conversion_rate", 1.3), ("grand_total", 9.7)):
        changed = dict(prefix.values);changed[name] = value
        other = replace(prefix, values=tuple(changed.items()))
        with pytest.raises(SettlementAccessError): replace(result, prefix=other)
    with pytest.raises(SettlementAccessError): replace(result, prefix=object())
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("changed", ["precision", "getter"])
def test_advance_precision_and_native_getter_remain_pinned_through_close(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def wrap(owned):
        close = owned.close.side_effect
        def finish():
            result = close()
            if changed == "precision": case.invoice._precision = {"main": {"total_advance": 3}}
            else: case.invoice.total_advance = 42.0
            return result
        owned.close.side_effect = finish
    case.before_handoff = wrap
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
def test_prefix_cannot_rebind_shared_grand_precision_cache(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    source = capture(case)
    original = source.prefix.fields[0]
    # Each declaration is individually consistent with precision2, but only
    # the actual original field proof belongs to this shared union capture.
    other = replace(original, cache=((("dict", 1), ("dict", 2)), ("int", "2")))
    prefix = replace(source.prefix, fields=(other, *source.prefix.fields[1:]))
    with pytest.raises(SettlementAccessError): replace(source, prefix=prefix)
    untouched(defaults_operator, case)
