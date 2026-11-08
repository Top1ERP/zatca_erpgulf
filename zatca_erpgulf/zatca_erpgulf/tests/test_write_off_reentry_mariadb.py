"""One real primary write-off/outstanding re-entry on NEW private SQL only."""

from dataclasses import replace
import os
import pickle
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_guarded_payments import GuardedOutstandingEntry
from zatca_erpgulf.zatca_erpgulf.calculation_payments import PaidAmountCalculation, ChangeAmountCalculation, PaymentCalculationError, CHANGE_FIELDS
from zatca_erpgulf.zatca_erpgulf.calculation_receivable import PayableAmountCalculation, OutstandingAmountCalculation, WriteOffCalculation, AUTO
from zatca_erpgulf.zatca_erpgulf.calculation_outstanding_prefix import OutstandingPrefixCalculation
from zatca_erpgulf.zatca_erpgulf.calculation_pos_adjustments import (
    PosTailInputs, PosTailCalculation, PosLimitObservation, DefaultMopObservation,
    DefaultMopRedistributionCalculation, PosAdjustmentError,
)
from zatca_erpgulf.zatca_erpgulf.calculation_pos_return_paid import PosReturnPaidCalculation
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_sequence import OutstandingSequence, WriteOffFollowup, WriteOffReentry
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_access import SettlementAccessError
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_sequence_mariadb import sequence, primary_probe
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_access_mariadb import (
    native_case, capture, empty_pos_sources, combined_schema, defaults_schema, financial_schema, metadata_schema,
    isolated_server, connections, untouched, format_schema, field_schema, empty_sources, selected_schema, pos_schema,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guarded temporary SQL only; no tenant or authority access")


def reentry(first):
    values = ((AUTO, first.tail.automatic_after), ("outstanding_amount", first.outstanding.amount),
        ("conversion_rate", dict(first.entry.paid.headers)["conversion_rate"]))
    return WriteOffReentry(WriteOffFollowup(first, WriteOffCalculation(first.source.receivable, "CALCULATED", values)))


def second_sequence(state, *, lookup=None):
    source, prior = state.source, state.paid_prior
    flags = dict(source.guarded.payment.controls.normalized_checks)
    original = state.followup.sequence.entry.paid
    if flags["is_pos"]:
        rows = tuple((name, amount) for name, amount, _ in prior.payments)
    else: rows = () if original.clear_payments else original.rows
    paid = PaidAmountCalculation(source.guarded.payment, "CALCULATED", original.headers, rows, prior)
    entry = GuardedOutstandingEntry(source.guarded, paid)
    prefix = OutstandingPrefixCalculation(source, "CALCULATED", state.prefix_values)
    payable = PayableAmountCalculation(source.receivable, "CALCULATED", prefix.payable_values)
    change = None if source.receivable.is_return else ChangeAmountCalculation(paid, "CALCULATED", payable.values[:4])
    changes = tuple(zip(CHANGE_FIELDS, (0.0, 0.0))) if change is None else change.totals
    outstanding = OutstandingAmountCalculation(payable, "CALCULATED", (*paid.totals, *changes))
    consolidated = dict(source.controls.checks)["is_consolidated"]
    limit = source.pos.lookup.limit_observation() if flags["is_pos"] and consolidated else PosLimitObservation(False, None)
    tail = PosTailCalculation(PosTailInputs("Sales Invoice", flags["is_pos"], flags["is_return"], consolidated,
        "SYNTHETIC-POS", state.automatic_before, outstanding.amount), limit)
    returned = None
    if tail.redistributes:
        total = sum(row[2] if source.receivable.foreign else row[1] for row in paid.payments)
        pending = payable.amount - total
        if pending > 0:
            selected = source.pos.lookup.default_observation() if source.pos is not None else lookup
        else: selected = DefaultMopObservation(False, False, None)
        redistribution = DefaultMopRedistributionCalculation("SAR", source.receivable.party.currency,
            "SYNTHETIC-POS", payable.amount, paid.payments, selected)
        returned = PosReturnPaidCalculation(paid, tail, redistribution, "SECOND-PAYMENT" if redistribution.replaces else None)
    return OutstandingSequence(source, entry, payable, change, outstanding, tail, returned, prefix, state)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("major,kind,is_return,foreign,is_pos,amount", [
    (15, "limit", 0, False, 1, 7.0),
    (16, "default", 1, True, 1, -12.0),
    (16, None, 0, False, 0, 5.0),
])
def test_actual_writeoff_requests_one_outstanding_call_on_previous_in_memory_state(defaults_operator, connections, upstream16, monkeypatch,
        major, kind, is_return, foreign, is_pos, amount):
    automatic = 0 if kind == "limit" else 1
    case = native_case(defaults_operator, connections, kind=kind, is_return=is_return,
        consolidated=int(kind == "limit"), foreign=foreign, auto=automatic, is_pos=is_pos)
    source = capture(case, major)
    first = sequence(source, amount=amount, grand=-8.7 if is_return else 8.7, automatic_before=automatic,
        loyalty=0.0 if kind == "limit" else 1.2345)
    first_doc = primary_probe(first, major, upstream16, monkeypatch)
    before_rows = tuple((row.name, row.amount) for row in first_doc.payments)
    state = reentry(first)
    second = second_sequence(state)
    assert second.entry.paid.rows == before_rows
    final = primary_probe(second, major, upstream16, monkeypatch, continuation=first_doc, via_write_off=True)
    assert final.outstanding_amount == second.outstanding.amount
    assert getattr(final, AUTO) == second.tail.automatic_after == 1
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    if kind == "limit":
        different_prior = replace(first.entry.paid, headers=(first.entry.paid.headers[0], ("loyalty_amount", -0.0)))
        shifted_paid = replace(second.entry.paid, headers=different_prior.headers, prior=different_prior)
        assert different_prior == first.entry.paid and shifted_paid == second.entry.paid
        with pytest.raises(SettlementAccessError):
            replace(second, entry=GuardedOutstandingEntry(source.guarded, shifted_paid))
    if is_return:
        assert second.entry.paid.rows[0][0] == "NEW-PAYMENT"
        assert final.outstanding_amount != 0  # The primary does not guarantee zero.
        assert not second.return_paid.redistribution.lookup.queried and source.pos is not None
        shifted = replace(second.return_paid.redistribution, amount_to_pay=100.0,
            lookup=source.pos.lookup.default_observation())
        with pytest.raises(PosAdjustmentError):
            PosReturnPaidCalculation(second.entry.paid, second.tail, shifted, source.guarded.payment.payment_types[0][0])
    if not is_pos:
        assert not final.payments and not second.entry.paid.rows and source.guarded.payment.payment_types
        with pytest.raises(PaymentCalculationError):
            replace(second.entry.paid, rows=first.entry.paid.rows)  # Never resurrect cleared rows.
        with pytest.raises(PaymentCalculationError): replace(second.entry.paid, prior=second.entry.paid)
        with pytest.raises(PaymentCalculationError): replace(second.entry.paid, representation="NUMERIC_FIXED")
        with pytest.raises(PaymentCalculationError):
            replace(second.entry.paid, headers=(("conversion_rate", 1.3), first.entry.paid.headers[1]))
        with pytest.raises(SettlementAccessError): replace(second, reentry=None)
        # Changing an old base write-off input leaves the converted output
        # unchanged. The exact re-entry input binding must still reject it.
        changed = dict(second.prefix.values);changed["base_write_off_amount"] += 0.01
        with pytest.raises(SettlementAccessError): replace(second, prefix=replace(second.prefix, values=tuple(changed.items())))
        stale = replace(second.tail, inputs=replace(second.tail.inputs, automatic_before=0))
        with pytest.raises(SettlementAccessError): replace(second, tail=stale)
        forged = object.__new__(WriteOffFollowup)
        object.__setattr__(forged, "sequence", second)
        object.__setattr__(forged, "write_off", state.followup.write_off)
        with pytest.raises(SettlementAccessError): WriteOffReentry(forged)  # Bounded, no third outstanding call.
    assert case.invoice.name not in repr(state)
    with pytest.raises(TypeError): pickle.dumps(state)
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
def test_inactive_null_automatic_flag_cannot_authorize_an_outstanding_reentry(defaults_operator, connections):
    case = native_case(defaults_operator, connections, auto=None)
    first = sequence(capture(case), automatic_before=None)
    values = ((AUTO, None), ("outstanding_amount", first.outstanding.amount), ("conversion_rate", 1.2))
    followup = WriteOffFollowup(first, WriteOffCalculation(first.source.receivable, "CALCULATED", values))
    assert not followup.write_off.recalculate
    with pytest.raises(SettlementAccessError) as caught: WriteOffReentry(followup)
    assert str(caught.value) == "settlement_write_off_reentry" and caught.value.__context__ is None
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
def test_newly_required_default_read_is_not_fabricated_from_uncaptured_observation(defaults_operator, connections, upstream16, monkeypatch):
    case = native_case(defaults_operator, connections, auto=1, is_return=1)
    source = capture(case)
    first = sequence(source, amount=-5.0, grand=-8.7, automatic_before=1)
    first_doc = primary_probe(first, 16, upstream16, monkeypatch)
    assert first.return_paid is not None and not first.return_paid.redistribution.lookup.queried and source.pos is None
    state = reentry(first)
    with pytest.raises(SettlementAccessError):
        second_sequence(state, lookup=DefaultMopObservation(True, True, "Cash"))
    # Execute unchanged primary bodies to prove that the new query is actually
    # reached. Stop at the missing source; do not supply a made-up SQL value.
    probe = framework(16, upstream16, monkeypatch, setting=source.prefix.method.rounding.value)
    precision = {proof.target[2]: proof.precision.precision for proof in
        (*source.guarded.payment.stage.fields, *source.receivable.stage.fields, *source.prefix.fields)}
    precision.update((name, proof.precision) for name, proof in source.receivable.precisions)
    doc = SimpleNamespace(**vars(first_doc))
    doc.get = lambda name: getattr(doc, name, None)
    doc.set = lambda name, value: setattr(doc, name, value)
    doc.precision = lambda name, parentfield=None: precision[name]
    doc.round_floats_in = lambda target, names: probe.method(doc, target, names)
    owner, queries, calls = SimpleNamespace(doc=doc), [], []
    class MissingSource(Exception): pass
    def get_value(*args, **kwargs):
        queries.append((args, kwargs));raise MissingSource
    runtime = SimpleNamespace(db=SimpleNamespace(get_value=get_value))
    owner.calculate_paid_amount = lambda: controller("calculate_paid_amount", 16, {"flt": probe.flt})(owner)
    owner.is_internal_invoice = lambda: False
    owner._set_in_company_currency = lambda target, names: controller("_set_in_company_currency", 16, {"flt": probe.flt})(owner, target, names)
    owner.set_total_amount_to_default_mop = lambda amount: controller("set_total_amount_to_default_mop", 16, {"frappe": runtime})(owner, amount)
    def outstanding():
        calls.append(True)
        controller("calculate_outstanding_amount", 16, {"flt": probe.flt, "frappe": runtime})(owner)
    owner.calculate_outstanding_amount = outstanding
    with pytest.raises(MissingSource): controller("calculate_write_off_amount", 16, {"flt": probe.flt})(owner)
    assert len(calls) == 1 and queries == [(("POS Payment Method", {"parent": "SYNTHETIC-POS", "default": 1}, ["mode_of_payment"]), {"as_dict": 1})]
    untouched(defaults_operator, case)
