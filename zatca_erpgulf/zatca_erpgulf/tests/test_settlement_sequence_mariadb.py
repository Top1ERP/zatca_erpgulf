"""Bound outstanding/POS/write-off handoffs on NEW guard-owned SQL only."""

import ast
from dataclasses import replace
import os
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_guarded_payments import GuardedOutstandingEntry
from zatca_erpgulf.zatca_erpgulf.calculation_payments import PaidAmountCalculation, ChangeAmountCalculation, PAID_FIELDS, CHANGE_FIELDS
from zatca_erpgulf.zatca_erpgulf.calculation_receivable import (
    PayableAmountCalculation, OutstandingAmountCalculation, WriteOffCalculation, PAYABLE_FIELDS, AUTO,
)
from zatca_erpgulf.zatca_erpgulf.calculation_pos_adjustments import (
    PosTailInputs, PosTailCalculation, PosLimitObservation, DefaultMopObservation, DefaultMopRedistributionCalculation,
)
from zatca_erpgulf.zatca_erpgulf.calculation_pos_return_paid import PosReturnPaidCalculation
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_sequence import OutstandingSequence, WriteOffFollowup
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_access import SettlementAccessError
from zatca_erpgulf.zatca_erpgulf.calculation_outstanding_prefix import OutstandingPrefixCalculation, INPUT_FIELDS, ROUND_FIELDS
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_access_mariadb import (
    native_case, capture, empty_pos_sources, combined_schema, defaults_schema, financial_schema, metadata_schema,
    isolated_server, connections, untouched, format_schema, field_schema, empty_sources, selected_schema, pos_schema,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller, controller_text
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_outstanding_guard import primary_methods

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guarded temporary SQL only; no tenant or authority access")


def sequence(source, *, amount=5.0, grand=8.7, automatic_before=0, loyalty=1.2345):
    paid = PaidAmountCalculation(source.guarded.payment, "CALCULATED",
        (("conversion_rate", 1.2), ("loyalty_amount", loyalty)),
        tuple((name, amount if index == 0 else 0.0) for index, (name, _) in enumerate(source.guarded.payment.payment_types)))
    entry = GuardedOutstandingEntry(source.guarded, paid)
    if entry.decision.skip_balance:
        return OutstandingSequence(source, entry, None, None, None, None, None)
    prefix = OutstandingPrefixCalculation(source, "CALCULATED", tuple(zip(INPUT_FIELDS,
        (grand, 0.0, grand * 1.2, 0.0, 0.0, 0.0, 0.0, 1.2))))
    payable = PayableAmountCalculation(source.receivable, "CALCULATED", prefix.payable_values)
    change = None if source.receivable.is_return else ChangeAmountCalculation(paid, "CALCULATED", payable.values[:4])
    changes = tuple(zip(CHANGE_FIELDS, (0.0, 0.0))) if change is None else change.totals
    outstanding = OutstandingAmountCalculation(payable, "CALCULATED", (*paid.totals, *changes))
    flags = dict(source.guarded.payment.controls.normalized_checks)
    consolidated = dict(source.controls.checks)["is_consolidated"]
    queried = bool(flags["is_pos"] and consolidated)
    limit = source.pos.lookup.limit_observation() if queried else PosLimitObservation(False, None)
    tail = PosTailCalculation(PosTailInputs("Sales Invoice", flags["is_pos"], flags["is_return"],
        consolidated, "SYNTHETIC-POS", automatic_before, outstanding.amount), limit)
    returned = None
    if tail.redistributes:
        foreign = source.receivable.foreign
        total = sum(row[2] if foreign else row[1] for row in paid.payments)
        pending = payable.amount - total
        lookup = source.pos.lookup.default_observation() if pending > 0 else DefaultMopObservation(False, False, None)
        redistribution = DefaultMopRedistributionCalculation("SAR", source.receivable.party.currency,
            "SYNTHETIC-POS", payable.amount, paid.payments, lookup)
        returned = PosReturnPaidCalculation(paid, tail, redistribution, "NEW-PAYMENT" if redistribution.replaces else None)
    return OutstandingSequence(source, entry, payable, change, outstanding, tail, returned, prefix)


def primary_probe(result, major, upstream16, monkeypatch, *, methods=None, continuation=None, via_write_off=False):
    source = result.source
    raw = source.guarded.payment.stage.method.rounding.value
    probe = framework(major, upstream16, monkeypatch, setting=raw)
    precisions = {proof.target[2]: proof.precision.precision for proof in
        (*source.guarded.payment.stage.fields, *source.receivable.stage.fields, *source.prefix.fields)}
    precisions.update((name, proof.precision) for name, proof in source.receivable.precisions)
    trace, calls = [], []
    markers = dict(payable=None, balance=None, ready=False, rounding=False)
    settings = lambda: tuple((call.args[0], raw) for call in probe.runtime.get_system_settings.call_args_list)
    def segment(start): return settings()[start[0]:], tuple(trace[start[1]:])
    class Root(SimpleNamespace):
        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)
            if not markers["ready"]: return
            if name == "outstanding_amount":
                if result.outstanding is None:
                    calls.append("reset_outstanding")
                    result.entry.decision.require_match(calls=tuple(calls), reset=(name, value), continues=False)
                else:
                    calls.append("assign_outstanding")
                    selected_settings, selected_trace = segment(markers["balance"])
                    result.outstanding.require_match(amount=value, setting_trace=selected_settings, precision_trace=selected_trace)
            elif name == AUTO: calls.append("assign_automatic_write_off")
        def get(self, name): return getattr(self, name, None)
        def set(self, name, value): setattr(self, name, value)
        def precision(self, name, parentfield=None):
            trace.append((name, parentfield, precisions[name]) if markers["rounding"] else (name, precisions[name]))
            return precisions[name]
        def round_floats_in(self, doc, names):
            if names == ["paid_amount"]:
                import inspect
                actual = inspect.currentframe().f_back.f_locals["total_amount_to_pay"]
                selected_settings, selected_trace = segment(markers["payable"])
                result.payable.require_match(amount=actual, setting_trace=selected_settings, precision_trace=selected_trace)
                calls.extend(("calculate_payable", "round_paid_amount"))
                self.paid_amount = probe.flt(self.paid_amount, self.precision("paid_amount"))
                markers["balance"] = len(settings()), len(trace)
            else:
                assert names == ["grand_total", "total_advance", "write_off_amount"]
                calls.append("round_floats_in")
                start = len(settings()), len(trace)
                markers["rounding"] = True
                probe.method(self, doc, names)
                markers["rounding"] = False
                markers["rounded"] = tuple((name, doc.get(name)) for name in ROUND_FIELDS)
                markers["round_settings"], markers["round_precision"] = segment(start)
        def append(self, table, values):
            assert table == "payments"
            name = result.return_paid.appended_row_name
            self.payments.append(SimpleNamespace(name=name, base_amount=None, type=None, **values))
    prefix = result.prefix.values[:-1] if result.prefix is not None else tuple(zip(PAYABLE_FIELDS, (8.7, 0.0, 10.44, 0.0, 0.0, 0.0, 0.0)))
    doc = Root(**vars(continuation)) if continuation is not None else Root(doctype="Sales Invoice", company=result.entry.decision.inputs.company,
        is_internal_customer=result.entry.decision.inputs.is_internal_customer,
        represents_company=result.entry.decision.inputs.represents_company,
        currency="SAR", party_account_currency=source.receivable.party.currency,
        return_against=None, update_outstanding_for_self=0, pos_profile="SYNTHETIC-POS", is_pos=dict(source.guarded.payment.controls.normalized_checks)["is_pos"],
        redeem_loyalty_points=dict(source.guarded.payment.controls.normalized_checks)["redeem_loyalty_points"],
        is_return=int(source.receivable.is_return), is_consolidated=dict(source.controls.checks)["is_consolidated"],
        **dict(result.entry.paid.headers), **dict(prefix))
    if continuation is None: setattr(doc, AUTO, 0 if result.tail is None else result.tail.inputs.automatic_before)
    types = {name: None if tag == ("null",) else tag[1] for name, tag in source.guarded.payment.payment_types}
    if continuation is None:
        doc.payments = [SimpleNamespace(name=name, amount=value, base_amount=999.0, type=types[name]) for name, value in result.entry.paid.rows]
    owner = SimpleNamespace(doc=doc)
    paid_calls = []
    def paid():
        calls.append("calculate_paid_amount")
        start = len(settings()), len(trace)
        controller("calculate_paid_amount", major, {"flt": probe.flt})(owner)
        selected_settings, selected_trace = segment(start)
        actual_rows = tuple((row.name, row.amount, row.base_amount) for row in doc.payments) if doc.is_pos else ()
        totals = tuple((name, getattr(doc, name)) for name in PAID_FIELDS)
        if not paid_calls:
            result.entry.paid.require_match(payments=actual_rows, totals=totals, clear_payments=result.entry.paid.clear_payments,
                setting_trace=selected_settings, precision_trace=selected_trace)
        else:
            result.return_paid.require_match(payments=actual_rows, totals=totals,
                setting_trace=selected_settings, precision_trace=selected_trace)
        paid_calls.append(True)
    def internal():
        calls.append("is_internal_invoice")
        if methods is not None: return methods["is_internal_invoice"](owner)
        calls.append("is_internal_transfer");return False
    def internal_transfer():
        calls.append("is_internal_transfer")
        return methods["is_internal_transfer"](doc)
    doc.is_internal_transfer = internal_transfer
    def convert(doc, names):
        assert names == ["write_off_amount"]
        calls.append("convert_write_off")
        start = len(settings()), len(trace)
        controller("_set_in_company_currency", major, {"flt": probe.flt})(owner, doc, names)
        selected_settings, selected_trace = segment(start)
        result.prefix.require_match(rounded=markers["rounded"],
            payable_values=tuple((name, doc.get(name)) for name in PAYABLE_FIELDS),
            round_settings=markers["round_settings"], round_precision=markers["round_precision"],
            conversion_settings=selected_settings, conversion_precision=selected_trace)
        markers["payable"] = len(settings()), len(trace)
    def change():
        calls.append("calculate_change_amount")
        start = len(settings()), len(trace)
        controller("calculate_change_amount", major, {"flt": probe.flt})(owner)
        selected_settings, selected_trace = segment(start)
        result.change.require_match(totals=tuple((name, getattr(doc, name)) for name in CHANGE_FIELDS),
            setting_trace=selected_settings, precision_trace=selected_trace)
        markers["balance"] = len(settings()), len(trace)
    def get_value(dt, *args, **kwargs):
        if dt == "POS Profile":
            assert args == ("SYNTHETIC-POS", "write_off_limit") and not kwargs
            calls.append("get_write_off_limit")
            return source.pos.lookup.limit_observation().value
        assert dt == "POS Payment Method" and args == ({"parent": "SYNTHETIC-POS", "default": 1}, ["mode_of_payment"]) and kwargs == {"as_dict": 1}
        lookup = source.pos.lookup.default_observation()
        return SimpleNamespace(mode_of_payment=lookup.mode_of_payment) if lookup.found else None
    helper = ast.parse(controller_text("set_total_amount_to_default_mop", major))
    helper.body[0].body.append(ast.Return(ast.Tuple([ast.Name("total_paid_amount", ast.Load()), ast.Name("pending_amount", ast.Load())], ast.Load())))
    ast.fix_missing_locations(helper)
    namespace = {"frappe": SimpleNamespace(db=SimpleNamespace(get_value=get_value))}
    exec(compile(helper, "<primary redistribution with observation epilogue>", "exec"), namespace)
    def redistribute(amount):
        calls.append("redistribute_default_payment")
        total, pending = namespace["set_total_amount_to_default_mop"](owner, amount)
        plan = result.return_paid.redistribution
        append = None if not plan.replaces else (("mode_of_payment", doc.payments[0].mode_of_payment),
            ("amount", doc.payments[0].amount), ("default", doc.payments[0].default))
        plan.require_match(total_paid=total, pending=pending, replaced=plan.replaces,
            append_values=append, calls=plan.calls, setting_trace=())
    owner.calculate_paid_amount, owner.is_internal_invoice = paid, internal
    owner._set_in_company_currency, owner.calculate_change_amount = convert, change
    owner.set_total_amount_to_default_mop = redistribute
    markers["ready"] = True
    recalculations = []
    def outstanding_call():
        if via_write_off:
            selected_settings, selected_trace = segment((0, 0))
            result.reentry.followup.write_off.require_match(
                amounts=tuple((name, doc.get(name)) for name in ("write_off_amount", "base_write_off_amount")),
                recalculate=True, setting_trace=selected_settings, precision_trace=selected_trace)
        recalculations.append(True)
        controller("calculate_outstanding_amount", major, {"flt": probe.flt,
            "frappe": SimpleNamespace(db=SimpleNamespace(get_value=get_value))})(owner)
    owner.calculate_outstanding_amount = outstanding_call
    if via_write_off:
        assert continuation is not None and result.reentry is not None
        controller("calculate_write_off_amount", major, {"flt": probe.flt})(owner)
    else: outstanding_call()
    assert len(recalculations) == 1
    result.require_order(tuple(calls))
    if result.outstanding is not None:
        assert doc.outstanding_amount == result.outstanding.amount
        assert getattr(doc, AUTO) == result.tail.automatic_after
    else: assert type(doc.outstanding_amount) is int and doc.outstanding_amount == 0
    return doc


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("scenario", ["sale", "limit", "return-default", "return-no-query", "return-foreign"])
def test_bound_sequence_matches_primary_handoffs_without_extra_outstanding_recalculation(defaults_operator, connections, upstream16, monkeypatch, major, scenario):
    is_return = int(scenario.startswith("return"))
    kind = "limit" if scenario == "limit" else "default" if scenario in ("return-default", "return-foreign") else None
    case = native_case(defaults_operator, connections, kind=kind, is_return=is_return,
        consolidated=int(scenario == "limit"), foreign=scenario == "return-foreign")
    source = capture(case, major)
    amount = -12.0 if kind == "default" else -5.0 if is_return else 7.0 if kind == "limit" else 5.0
    result = sequence(source, amount=amount, grand=-8.7 if is_return else 8.7)
    doc = primary_probe(result, major, upstream16, monkeypatch)
    plan = WriteOffCalculation(source.receivable, "CALCULATED", ((AUTO, result.tail.automatic_after),
        ("outstanding_amount", result.outstanding.amount), ("conversion_rate", 1.2)))
    followup = WriteOffFollowup(result, plan)
    assert followup.write_off.recalculate is (scenario == "limit")
    if result.return_paid is not None:
        assert tuple((row.name, row.amount, row.base_amount) for row in doc.payments) == result.return_paid.payments
        assert doc.outstanding_amount == result.outstanding.amount  # No invented post-payment recalculation.
    if scenario == "return-foreign" and major == 16:
        for changes in (dict(party_currency="EUR"), dict(amount_to_pay=result.payable.amount + 0.01)):
            redistribution = replace(result.return_paid.redistribution, **changes)
            returned = replace(result.return_paid, redistribution=redistribution)
            with pytest.raises(SettlementAccessError): replace(result, return_paid=returned)
    if scenario == "sale" and major == 16:
        changed = dict(result.change.headers);changed["grand_total"] += 0.01
        wrong_change = replace(result.change, headers=tuple(changed.items()))
        with pytest.raises(SettlementAccessError): replace(result, change=wrong_change)
        with pytest.raises(SettlementAccessError): result.require_order(tuple(reversed(result.calls)))
        invalid_plan = replace(plan, values=((AUTO, 1), ("outstanding_amount", result.outstanding.amount), ("conversion_rate", 1.2)))
        with pytest.raises(SettlementAccessError): WriteOffFollowup(result, invalid_plan)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("major", [15, 16])
def test_internal_skip_still_requires_paid_before_integer_zero_reset(defaults_operator, connections, upstream16, monkeypatch, primary_methods, major):
    case = native_case(defaults_operator, connections, internal=True)
    source = capture(case, major)
    result = sequence(source)
    assert result.entry.decision.skip_balance and result.payable is None and result.tail is None
    primary_probe(result, major, upstream16, monkeypatch, methods=primary_methods[major])
    with pytest.raises(SettlementAccessError): result.require_order(result.calls[1:])
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
def test_unused_null_automatic_flag_is_retained_in_followup(defaults_operator, connections, upstream16, monkeypatch):
    case = native_case(defaults_operator, connections, auto=None)
    source = capture(case)
    result = sequence(source, automatic_before=None)
    primary_probe(result, 16, upstream16, monkeypatch)
    plan = WriteOffCalculation(source.receivable, "CALCULATED", ((AUTO, None),
        ("outstanding_amount", result.outstanding.amount), ("conversion_rate", 1.2)))
    followup = WriteOffFollowup(result, plan)
    assert result.tail.automatic_after is None and not followup.write_off.recalculate
    untouched(defaults_operator, case)
