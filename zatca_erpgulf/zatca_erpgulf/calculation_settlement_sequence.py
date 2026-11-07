"""Bind existing Sales outstanding/POS/write-off comparisons in primary order.

Post-prefix amounts and execution traces remain explicit observations. This
does not execute rounding/conversion, controller recursion, document writes or
tax requests, nor attest the origin of a cached API or prefix observation.
"""

from dataclasses import dataclass, field
import json

from .calculation_settlement_access import SavedSettlementRead, SettlementAccessError
from .calculation_guarded_payments import GuardedOutstandingEntry
from .calculation_payments import ChangeAmountCalculation, _exact_values
from .calculation_receivable import PayableAmountCalculation, OutstandingAmountCalculation, WriteOffCalculation, AUTO
from .calculation_pos_adjustments import PosTailCalculation
from .calculation_pos_return_paid import PosReturnPaidCalculation
from .calculation_field_rounding_access import _result_tag
from .field_rounding import round_field_value
from .financial_source_observation import _scalar


def _same_number(left, right):
    if _result_tag(left) != _result_tag(right):
        raise ValueError


def _change(value):
    if type(value) is not ChangeAmountCalculation:
        raise ValueError
    pinned = ChangeAmountCalculation(value.paid, value.representation, value.headers)
    _exact_values(value.totals, pinned.totals)
    if pinned != value or type(value.applies) is not bool:
        raise ValueError
    return pinned


@dataclass(frozen=True, repr=False)
class OutstandingSequence:
    """Check one call through paid, guard, explicit balance prefix and POS tail."""
    source: SavedSettlementRead = field(repr=False)
    entry: GuardedOutstandingEntry = field(repr=False)
    payable: PayableAmountCalculation | None = field(repr=False)
    change: ChangeAmountCalculation | None = field(repr=False)
    outstanding: OutstandingAmountCalculation | None = field(repr=False)
    tail: PosTailCalculation | None = field(repr=False)
    return_paid: PosReturnPaidCalculation | None = field(repr=False)
    calls: tuple = field(init=False)

    def __post_init__(self):
        try:
            if type(self.source) is not SavedSettlementRead or type(self.entry) is not GuardedOutstandingEntry:
                raise ValueError
            source = self.source.pin()
            entry = GuardedOutstandingEntry(self.entry.source, self.entry.paid)
            if entry != self.entry or entry.source != source.guarded:
                raise ValueError
            calls = list(entry.decision.calls)
            payable = change = outstanding = tail = return_paid = None
            if entry.decision.skip_balance:
                if any(value is not None for value in (self.payable, self.change, self.outstanding, self.tail, self.return_paid, source.pos)):
                    raise ValueError
            else:
                if (type(self.payable) is not PayableAmountCalculation or type(self.outstanding) is not OutstandingAmountCalculation
                        or type(self.tail) is not PosTailCalculation):
                    raise ValueError
                payable = self.payable.pin()
                outstanding = OutstandingAmountCalculation(self.outstanding.payable, self.outstanding.representation, self.outstanding.values)
                if payable.source != source.receivable or outstanding.payable != payable or outstanding != self.outstanding:
                    raise ValueError
                _same_number(outstanding.amount, self.outstanding.amount)
                paid = dict(entry.paid.totals)
                # The primary rounds paid_amount once more before cash change.
                # Existing ChangeAmountCalculation consumes the earlier paid
                # result; refuse a non-idempotent handoff instead of pretending
                # the second rounding did not happen.
                stage = source.guarded.payment.stage
                proof = stage.fields[0]
                rounded_paid = round_field_value(paid["paid_amount"], precision=proof.precision.precision,
                    method=stage.method.method, erp_major=stage.method.erp_major)
                _same_number(rounded_paid, paid["paid_amount"])
                balance = dict(outstanding.values)
                for name in ("paid_amount", "base_paid_amount"):
                    _same_number(balance[name], paid[name])
                calls.extend(("convert_write_off", "calculate_payable", "round_paid_amount"))
                if source.receivable.is_return:
                    if self.change is not None:
                        raise ValueError
                else:
                    change = _change(self.change)
                    if change.paid != entry.paid:
                        raise ValueError
                    prefix = dict(payable.values)
                    _exact_values(change.headers, tuple((name, prefix[name]) for name in
                        ("grand_total", "rounded_total", "base_grand_total", "base_rounded_total")))
                    for name, value in change.totals:
                        _same_number(balance[name], value)
                    calls.append("calculate_change_amount")
                calls.append("assign_outstanding")
                tail = self.tail.pin()
                inputs = tail.inputs
                native = source.guarded.payment.controls
                checks = dict(native.normalized_checks)
                checks.update(is_pos=inputs.is_pos, is_return=inputs.is_return)
                native.require_saved_check_match(checks)
                controls = dict(source.controls.checks)
                controls["is_consolidated"] = inputs.is_consolidated
                source.controls.controls.require_saved_check_match(controls)
                source.receivable.write_off.require_saved_check_match({AUTO: inputs.automatic_before})
                header = dict(json.loads(stage.numeric.view.financial.financial._payload)["header"])
                profile = header["pos_profile"]
                expected_profile = None if profile in (["absent"], ["null"]) else profile[1]
                if inputs.doctype != "Sales Invoice" or type(inputs.pos_profile) is not type(expected_profile) or inputs.pos_profile != expected_profile:
                    raise ValueError
                _same_number(inputs.outstanding, outstanding.amount)
                needed = "limit" if tail.limit.queried else None
                if tail.limit.queried:
                    if source.pos is None or source.pos.lookup.kind != "limit":
                        raise ValueError
                    if _scalar(tail.limit.value) != _scalar(source.pos.lookup.limit_observation().value):
                        raise ValueError
                if tail.redistributes:
                    if type(self.return_paid) is not PosReturnPaidCalculation:
                        raise ValueError
                    return_paid = PosReturnPaidCalculation(self.return_paid.paid_before, self.return_paid.tail,
                        self.return_paid.redistribution, self.return_paid.appended_row_name)
                    _exact_values(return_paid.payments, self.return_paid.payments)
                    _exact_values(return_paid.totals, self.return_paid.totals)
                    if return_paid != self.return_paid or return_paid.paid_before != entry.paid or return_paid.tail != tail:
                        raise ValueError
                    redistribution = return_paid.redistribution
                    _same_number(redistribution.amount_to_pay, payable.amount)
                    if redistribution.party_currency != source.receivable.party.currency:
                        raise ValueError
                    if redistribution.lookup.queried:
                        needed = "default"
                        if (source.pos is None or source.pos.lookup.kind != "default"
                                or redistribution.lookup != source.pos.lookup.default_observation()):
                            raise ValueError
                elif self.return_paid is not None:
                    raise ValueError
                if (source.pos is None) != (needed is None):
                    raise ValueError
                calls.extend(tail.calls)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise SettlementAccessError("settlement_sequence")
        for name, value in (("source", source), ("entry", entry), ("payable", payable), ("change", change),
                ("outstanding", outstanding), ("tail", tail), ("return_paid", return_paid), ("calls", tuple(calls))):
            object.__setattr__(self, name, value)

    def pin(self):
        result = OutstandingSequence(self.source, self.entry, self.payable, self.change, self.outstanding, self.tail, self.return_paid)
        if result != self or type(self.calls) is not tuple or any(type(value) is not str for value in self.calls):
            raise SettlementAccessError("settlement_sequence")
        return result

    def require_order(self, calls):
        expected = self.pin().calls
        if type(calls) is not tuple or any(type(value) is not str for value in calls) or calls != expected:
            raise SettlementAccessError("settlement_sequence_order")

    def __repr__(self): return "<OutstandingSequence checked handoffs, NOT prefix/controller execution proof>"
    def __reduce__(self): raise TypeError("settlement_sequence_not_serializable")


@dataclass(frozen=True, repr=False)
class WriteOffFollowup:
    """Bind the next write-off plan, exposing its required recalculation.

    This is a separate controller call after the outstanding sequence. One
    requested recalculation is retained, never executed or assumed to yield zero.
    """
    sequence: OutstandingSequence = field(repr=False)
    write_off: WriteOffCalculation = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.sequence) is not OutstandingSequence or type(self.write_off) is not WriteOffCalculation:
                raise ValueError
            sequence = self.sequence.pin()
            plan = WriteOffCalculation(self.write_off.source, self.write_off.representation, self.write_off.values)
            _exact_values(plan.amounts, self.write_off.amounts)
            if (sequence.tail is None or plan != self.write_off or type(plan.recalculate) is not bool
                    or type(self.write_off.recalculate) is not bool or plan.source != sequence.source.receivable
                    or plan.representation != "CALCULATED"):
                raise ValueError
            expected = ((AUTO, sequence.tail.automatic_after), ("outstanding_amount", sequence.outstanding.amount),
                        ("conversion_rate", dict(sequence.entry.paid.headers)["conversion_rate"]))
            if tuple((name, _scalar(value)) for name, value in plan.values) != tuple(
                    (name, _scalar(value)) for name, value in expected):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise SettlementAccessError("settlement_write_off_followup")
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "write_off", plan)

    def __repr__(self): return "<WriteOffFollowup bound plan, NOT recursive outstanding/GL proof>"
    def __reduce__(self): raise TypeError("settlement_write_off_not_serializable")
