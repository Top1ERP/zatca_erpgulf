"""Saved-numeric two-call inspection with lazy same-owner POS dependencies.

Reuse the existing kernels and permissioned readers. Append names are explicit
hypothetical observation labels, not allocated/saved children or runtime identity
proof. Earlier total/advance/GL derivation and cache/provider origin stay external.
No controller, ordinary document writer, second SQL owner or authority transport.
"""

from dataclasses import dataclass, field, replace
import json

from .calculation_settlement_access import SettlementAcquisition, SettlementRequest, SavedSettlementRead, SettlementAccessError
from .calculation_pos_profile_access import PosProfileAcquisition, PosProfileRequest
from .calculation_guarded_payments import GuardedOutstandingEntry
from .calculation_payments import PaidAmountCalculation, ChangeAmountCalculation, CHANGE_FIELDS
from .calculation_receivable import PayableAmountCalculation, OutstandingAmountCalculation, WriteOffCalculation, PAYABLE_FIELDS, AUTO
from .calculation_outstanding_prefix import OutstandingPrefixCalculation, INPUT_FIELDS, _same_values
from .calculation_pos_adjustments import PosTailInputs, PosTailCalculation, PosLimitObservation, DefaultMopObservation, DefaultMopRedistributionCalculation, default_mop_balance
from .calculation_pos_return_paid import PosReturnPaidCalculation
from .calculation_settlement_sequence import OutstandingSequence, WriteOffFollowup, WriteOffReentry
from .financial_numeric_view import _native_cells, _expected
from .financial_source_observation import _validate_scalar, _name


@dataclass(frozen=True, repr=False)
class SettlementPlanRequest:
    """Bounded explicit hypothetical append labels; no financial input override."""
    append_names: tuple = field(default=(None, None), repr=False)

    def __repr__(self): return "<SettlementPlanRequest saved-numeric inspection>"
    def __reduce__(self): raise TypeError("settlement_plan_request_not_serializable")


def _labels(names):
    if type(names) is not tuple or len(names) != 2:
        raise ValueError
    for name in names:
        if name is not None: _name(name)
    if names[0] is not None and names[0] == names[1]:
        raise ValueError
    return names


def _saved_inputs(source):
    native = source.prefix.numeric.view.financial
    cells = {cell[2]: cell for cell in _native_cells(native) if cell[0] == "header"}
    side = dict(json.loads(source.receivable.write_off._payload)["fields"])
    def value(name):
        if name in side: tag, kind = side[name], "Currency"
        else: _, _, _, kind, tag = cells[name]
        return _validate_scalar(_expected(tag, "NUMERIC_FIXED", kind))
    loyalty = dict(json.loads(source.guarded.payment.controls._payload)["fields"])["loyalty_amount"]
    loyalty = None if loyalty == ["absent"] else _validate_scalar(_expected(loyalty, "NUMERIC_FIXED", "Currency"))
    headers = (("conversion_rate", value("conversion_rate")), ("loyalty_amount", loyalty))
    rows = {cell[1]: cell for cell in _native_cells(native) if cell[0] == "payments" and cell[2] == "amount"}
    amounts = tuple((name, _validate_scalar(_expected(rows[name][4], "NUMERIC_FIXED", rows[name][3])))
                    for name, _ in source.guarded.payment.payment_types)
    return headers, amounts, tuple((name, value(name)) for name in INPUT_FIELDS)


@dataclass(frozen=True, repr=False)
class _Steps:
    """Provisional component results; never a completed source/sequence grant."""
    entry: object
    prefix: object = None
    payable: object = None
    change: object = None
    outstanding: object = None
    tail: object = None
    returned: object = None


def _steps(source, headers, rows, prefix_values, automatic, append_name, lookup, *, prior=None):
    representation = "NUMERIC_FIXED" if prior is None else "CALCULATED"
    paid = PaidAmountCalculation(source.guarded.payment, representation, headers, rows, prior)
    entry = GuardedOutstandingEntry(source.guarded, paid)
    if entry.decision.skip_balance: return _Steps(entry)
    prefix = OutstandingPrefixCalculation(source, representation, prefix_values)
    payable = PayableAmountCalculation(source.receivable, "CALCULATED", prefix.payable_values)
    change = None if source.receivable.is_return else ChangeAmountCalculation(paid, "CALCULATED", payable.values[:4])
    changes = tuple(zip(CHANGE_FIELDS, (0.0, 0.0))) if change is None else change.totals
    outstanding = OutstandingAmountCalculation(payable, "CALCULATED", (*paid.totals, *changes))
    flags = dict(source.guarded.payment.controls.normalized_checks)
    consolidated = dict(source.controls.checks)["is_consolidated"]
    header = dict(json.loads(source.prefix.numeric.view.financial.financial._payload)["header"])
    profile_tag = header["pos_profile"]
    profile = None if profile_tag in (["null"], ["absent"]) else profile_tag[1]
    queried = bool(flags["is_pos"] and profile and consolidated)
    limit = lookup("limit").limit_observation() if queried else PosLimitObservation(False, None)
    tail = PosTailCalculation(PosTailInputs("Sales Invoice", flags["is_pos"], flags["is_return"], consolidated,
        profile, automatic, outstanding.amount), limit)
    returned = None
    if tail.redistributes:
        _, pending = default_mop_balance(header["currency"][1], source.receivable.party.currency, payable.amount, paid.payments)
        selected = lookup("default").default_observation() if pending > 0 else DefaultMopObservation(False, False, None)
        redistribution = DefaultMopRedistributionCalculation(header["currency"][1], source.receivable.party.currency,
            profile, payable.amount, paid.payments, selected)
        # The primary will allocate its own child name in an actual lifecycle.
        # Here require a supplied witness only if that hypothetical append occurs.
        returned = PosReturnPaidCalculation(paid, tail, redistribution, append_name if redistribution.replaces else None)
    return _Steps(entry, prefix, payable, change, outstanding, tail, returned)


def _uses(steps):
    if steps.tail is not None and steps.tail.limit.queried: return "limit"
    if steps.returned is not None and steps.returned.redistribution.lookup.queried: return "default"
    return None


def _sequence(source, steps, *, reentry=None, deferred=False):
    prefix = None if steps.prefix is None else replace(steps.prefix, source=source)
    return OutstandingSequence(source, steps.entry, steps.payable, steps.change, steps.outstanding,
        steps.tail, steps.returned, prefix, reentry, deferred)


@dataclass(frozen=True, repr=False)
class SavedSettlementPlan:
    """Complete bounded comparison; NOT actual totals/append/GL execution proof."""
    source: SavedSettlementRead = field(repr=False)
    first: OutstandingSequence = field(repr=False)
    followup: WriteOffFollowup | None = field(repr=False)
    second: OutstandingSequence | None = field(repr=False)
    lookups: tuple = field(init=False)

    def __post_init__(self):
        try:
            if type(self.first) is not OutstandingSequence or type(self.source) is not SavedSettlementRead:
                raise ValueError
            if self.second is not None:
                if (type(self.second) is not OutstandingSequence or self.second.reentry is None
                        or type(self.followup) is not WriteOffFollowup):
                    raise ValueError
                second = self.second.pin()
                followup = second.reentry.followup
                first = followup.sequence
                if followup != self.followup or first != self.first:
                    raise ValueError
            else:
                second = None
                if self.followup is not None:
                    if type(self.followup) is not WriteOffFollowup: raise ValueError
                    followup = self.followup.pin()
                    first = followup.sequence
                    if followup.write_off.recalculate or first != self.first: raise ValueError
                else:
                    followup = None
                    first = self.first.pin()
                    if not first.entry.decision.skip_balance: raise ValueError
            source = first.source
            if (self.source != source or first.reentry is not None
                    or second is not None and second.source != source):
                raise ValueError
            headers, rows, prefix_values = _saved_inputs(source)
            if first.entry.paid.representation != "NUMERIC_FIXED": raise ValueError
            _same_values(first.entry.paid.headers, headers)
            _same_values(first.entry.paid.rows, rows)
            if first.prefix is not None:
                if first.prefix.representation != "NUMERIC_FIXED": raise ValueError
                _same_values(first.prefix.values, prefix_values)
            first_use, second_use = _uses_sequence(first), None if second is None else _uses_sequence(second)
            if first.pos_deferred != (first_use is None and second_use is not None): raise ValueError
            if (source.pos is None) != (first_use is None and second_use is None): raise ValueError
            lookups = first_use, second_use
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid: raise SettlementAccessError("settlement_saved_plan")
        for name, value in (("source", source), ("first", first), ("followup", followup), ("second", second), ("lookups", lookups)):
            object.__setattr__(self, name, value)

    def pin(self):
        # Validate explicit parallel references too; the constructor canonicalizes
        # them from the checked second call when that ancestry is present.
        self.first.pin()
        if self.followup is not None: self.followup.pin()
        result = SavedSettlementPlan(self.source, self.first, self.followup, self.second)
        if (result != self or type(self.lookups) is not tuple or len(self.lookups) != 2
                or any(value is not None and (type(value) is not str or value not in ("default", "limit")) for value in self.lookups)):
            raise SettlementAccessError("settlement_saved_plan")
        return result

    def __repr__(self): return "<SavedSettlementPlan bounded comparison, NOT runtime/GL/authority acceptance>"
    def __reduce__(self): raise TypeError("settlement_saved_plan_not_serializable")


def _uses_sequence(sequence):
    if sequence.tail is not None and sequence.tail.limit.queried: return "limit"
    if sequence.return_paid is not None and sequence.return_paid.redistribution.lookup.queried: return "default"
    return None


class SettlementPlanAcquisition(SettlementAcquisition):
    """Authorize each needed dependency before its callbacks on the SAME handle."""

    def __init__(self, policy, actor, invoice_name, doctype, major, request, **dependencies):
        if type(request) is not SettlementPlanRequest or doctype != "Sales Invoice":
            raise SettlementAccessError("settlement_plan_request")
        self.append_names = _labels(request.append_names)
        self.plan = None
        self._pos_metadata = dependencies["pos_metadata"]
        super().__init__(policy, actor, invoice_name, doctype, major, SettlementRequest(), **dependencies)

    def resolve_plan(self, connection, financial, observed):
        if self.plan is not None: raise SettlementAccessError("settlement_plan_already_resolved")
        source = super().build_result(financial, observed)
        headers, rows, prefix_values = _saved_inputs(source)
        def lookup(kind):
            if self.pos is None:
                # No POS amount/default provider or SQL is invoked until this
                # related normal READ/table/child/field authorization succeeds.
                self.pos = PosProfileAcquisition(self.root._policy, self.actor, self.root._name, self.root._doctype,
                    PosProfileRequest(kind), self._pos_metadata, _shared_graph=self.root)
                self.pos.prepare_metadata()
                self.pos.require_financial_metadata(tuple(row.applied for row in financial.financial.metadata))
                self.observed_pos = self.pos.load_for_update(connection, financial.financial)
            if self.pos.kind != kind: raise SettlementAccessError("settlement_plan_lookup_kind")
            return self.observed_pos
        automatic = _validate_scalar(dict(json.loads(source.receivable.write_off._payload)["fields"])[AUTO])
        first = _steps(source, headers, rows, prefix_values, automatic, self.append_names[0], lookup)
        write_off = second = None
        if first.tail is not None:
            write_off = WriteOffCalculation(source.receivable, "CALCULATED", ((AUTO, first.tail.automatic_after),
                ("outstanding_amount", first.outstanding.amount), ("conversion_rate", dict(headers)["conversion_rate"])))
            if write_off.recalculate:
                values = dict(first.prefix.payable_values)
                values.update(write_off.amounts)
                next_values = tuple((name, values[name]) for name in PAYABLE_FIELDS) + (headers[0],)
                prior = first.returned if first.returned is not None else first.entry.paid
                flags = dict(source.guarded.payment.controls.normalized_checks)
                next_rows = tuple((name, amount) for name, amount, _ in prior.payments) if flags["is_pos"] else (
                    () if first.entry.paid.clear_payments else first.entry.paid.rows)
                second = _steps(source, headers, next_rows, next_values, first.tail.automatic_after,
                    self.append_names[1], lookup, prior=prior)
        final_source = super().build_result(financial, observed)
        deferred = _uses(first) is None and second is not None and _uses(second) is not None
        first_sequence = _sequence(final_source, first, deferred=deferred)
        followup = None if write_off is None else WriteOffFollowup(first_sequence, write_off)
        second_sequence = None if second is None else _sequence(final_source, second, reentry=WriteOffReentry(followup))
        self.plan = SavedSettlementPlan(final_source, first_sequence, followup, second_sequence)
        self.recheck_access()

    def build_result(self, financial, observed):
        if type(self.plan) is not SavedSettlementPlan or super().build_result(financial, observed) != self.plan.source:
            raise SettlementAccessError("settlement_plan_binding")
        return self.plan
