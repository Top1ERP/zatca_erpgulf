"""Explicit post-balance POS comparisons; no lookup, document or request writes.

Lookup results are supplied observations, NOT native POS Profile provenance.
Preserve the inspected controller's currency units, lazy queries and row effects.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from .financial_source_observation import _scalar, _name, MAX_ROWS
from .calculated_totals import _input_tag
from .calculation_field_rounding_access import _result_tag


class PosAdjustmentError(ValueError):
    """Static English codes without profile links or amounts."""


def _check(value):
    if value is not None and (type(value) is not int or value not in (0, 1)):
        raise ValueError


def _link(value):
    if value is not None and type(value) is not str:
        raise ValueError
    _scalar(value)


@dataclass(frozen=True, repr=False)
class PosTailInputs:
    doctype: str
    is_pos: int | None
    is_return: int | None
    is_consolidated: int | None
    pos_profile: str | None = field(repr=False)
    automatic_before: int | None
    outstanding: int | float | None = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.doctype) is not str or self.doctype not in ("Sales Invoice", "POS Invoice"):
                raise ValueError
            for value in (self.is_pos, self.is_return, self.is_consolidated, self.automatic_before):_check(value)
            _link(self.pos_profile)
            _input_tag(self.outstanding, nullable=True)
        except Exception:
            raise PosAdjustmentError("pos_tail_inputs") from None

    def pin(self):
        return PosTailInputs(self.doctype,self.is_pos,self.is_return,self.is_consolidated,self.pos_profile,self.automatic_before,self.outstanding)

    def __repr__(self):return "<PosTailInputs supplied post-balance controls, NOT saved proof>"
    def __reduce__(self):raise TypeError("pos_tail_inputs_not_serializable")


@dataclass(frozen=True, repr=False)
class PosLimitObservation:
    queried: bool
    value: int | float | Decimal | None = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.queried) is not bool or not self.queried and self.value is not None:
                raise ValueError
            if self.value is not None and type(self.value) not in (int,float,Decimal):
                raise ValueError
            _scalar(self.value)
        except Exception:
            raise PosAdjustmentError("pos_limit_observation") from None

    def pin(self):return PosLimitObservation(self.queried,self.value)
    def __repr__(self):return "<PosLimitObservation supplied get_value result, NOT profile evidence>"
    def __reduce__(self):raise TypeError("pos_limit_observation_not_serializable")


@dataclass(frozen=True, repr=False)
class PosTailCalculation:
    """Compare only the suffix AFTER the actual outstanding assignment."""
    inputs: PosTailInputs = field(repr=False)
    limit: PosLimitObservation = field(repr=False)
    automatic_after: int | None = field(init=False)
    assigns_automatic: bool = field(init=False)
    redistributes: bool = field(init=False)
    calls: tuple = field(init=False,repr=False)

    def __post_init__(self):
        try:
            if type(self.inputs) is not PosTailInputs or type(self.limit) is not PosLimitObservation:
                raise ValueError
            inputs,limit=self.inputs.pin(),self.limit.pin()
            sales=inputs.doctype=="Sales Invoice"
            queried=bool(sales and inputs.is_pos and inputs.pos_profile and inputs.is_consolidated)
            if limit.queried!=queried:raise ValueError
            calls=[];assigns=False
            if queried:
                calls.append("get_write_off_limit")
                # This flt has NO precision or rounding-setting lookup. Native
                # Currency Decimal/NULL is retained in the input observation.
                number=0.0 if limit.value is None else float(limit.value)
                if number and abs(inputs.outstanding)<=number:
                    assigns=True;calls.append("assign_automatic_write_off")
            redistributes=bool(sales and inputs.is_pos and inputs.is_return and not inputs.is_consolidated)
            if redistributes:calls.extend(("redistribute_default_payment","calculate_paid_amount"))
            automatic=1 if assigns else inputs.automatic_before
        except Exception:
            raise PosAdjustmentError("pos_tail_calculation") from None
        for name,value in (("inputs",inputs),("limit",limit),("automatic_after",automatic),
                ("assigns_automatic",assigns),("redistributes",redistributes),("calls",tuple(calls))):
            object.__setattr__(self,name,value)

    def pin(self):
        pinned=PosTailCalculation(self.inputs,self.limit)
        if (pinned!=self or type(self.assigns_automatic) is not bool or type(self.redistributes) is not bool
                or type(self.automatic_after) is not type(pinned.automatic_after) or type(self.calls) is not tuple
                or any(type(value) is not str for value in self.calls)):
            raise PosAdjustmentError("pos_tail_calculation")
        return pinned

    def require_match(self,*,automatic_after,assigns_automatic,redistributes,calls,setting_trace):
        try:
            pinned=self.pin()
            if (type(automatic_after) is not type(pinned.automatic_after) or automatic_after!=pinned.automatic_after
                    or type(assigns_automatic) is not bool or assigns_automatic!=pinned.assigns_automatic
                    or type(redistributes) is not bool or redistributes!=pinned.redistributes
                    or type(calls) is not tuple or any(type(v) is not str for v in calls) or calls!=pinned.calls
                    or type(setting_trace) is not tuple or setting_trace!=()):
                raise ValueError
        except Exception:
            raise PosAdjustmentError("pos_tail_observation") from None

    def __repr__(self):return "<PosTailCalculation post-balance comparison, NOT profile/GL approval>"
    def __reduce__(self):raise TypeError("pos_tail_not_serializable")


@dataclass(frozen=True, repr=False)
class DefaultMopObservation:
    queried: bool
    found: bool
    mode_of_payment: str | None = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.queried) is not bool or type(self.found) is not bool or self.found and not self.queried:
                raise ValueError
            if not self.found and self.mode_of_payment is not None:raise ValueError
            _link(self.mode_of_payment)
        except Exception:
            raise PosAdjustmentError("default_mop_observation") from None

    def pin(self):return DefaultMopObservation(self.queried,self.found,self.mode_of_payment)
    def __repr__(self):return "<DefaultMopObservation supplied row result, NOT default-row selection proof>"
    def __reduce__(self):raise TypeError("default_mop_not_serializable")


def _require_append(actual, expected):
    if expected is None:
        if actual is not None:raise ValueError
        return
    if (type(actual) is not tuple or len(actual)!=3
            or any(type(row) is not tuple or len(row)!=2 or type(row[0]) is not str or row[0]!=target[0] for row,target in zip(actual,expected))
            or type(actual[0][1]) is not type(expected[0][1]) or actual[0][1]!=expected[0][1]
            or _result_tag(actual[1][1])!=_result_tag(expected[1][1])
            or type(actual[2][1]) is not int or actual[2][1]!=1):
        raise ValueError


@dataclass(frozen=True, repr=False)
class DefaultMopRedistributionCalculation:
    """Plan exact row replacement in party currency, without FX correction.

    No per-row flt or rounding occurs in the primary summation. NULL selected
    amounts fail rather than becoming zero. Loyalty is not in this row sum.
    """
    currency: str = field(repr=False)
    party_currency: str = field(repr=False)
    pos_profile: str | None = field(repr=False)
    amount_to_pay: int | float = field(repr=False)
    rows: tuple = field(repr=False)
    lookup: DefaultMopObservation = field(repr=False)
    total_paid: int | float = field(init=False,repr=False)
    pending: int | float = field(init=False,repr=False)
    replaces: bool = field(init=False)
    append_values: tuple | None = field(init=False,repr=False)
    calls: tuple = field(init=False,repr=False)

    def __post_init__(self):
        try:
            for name in (self.currency,self.party_currency):
                if type(name) is not str or not name:raise ValueError
                _scalar(name)
            _link(self.pos_profile);_input_tag(self.amount_to_pay,nullable=False)
            if type(self.rows) is not tuple or len(self.rows)>MAX_ROWS or type(self.lookup) is not DefaultMopObservation:
                raise ValueError
            lookup=self.lookup.pin();total=0;names=set()
            for row in self.rows:
                if type(row) is not tuple or len(row)!=3 or type(row[0]) is not str or not row[0] or row[0] in names:raise ValueError
                _name(row[0]);names.add(row[0])
                _input_tag(row[1],nullable=True);_input_tag(row[2],nullable=True)
                total+=row[1] if self.party_currency==self.currency else row[2]
            _input_tag(total,nullable=False)
            pending=self.amount_to_pay-total;_input_tag(pending,nullable=False)
            queried=pending>0
            if lookup.queried!=queried:raise ValueError
            replaces=bool(queried and lookup.found)
            append=(('mode_of_payment',lookup.mode_of_payment),('amount',pending),('default',1)) if replaces else None
            calls=("get_default_mop",) if queried else ()
            if replaces:calls+=("replace_payments","append_payment")
        except Exception:
            raise PosAdjustmentError("default_mop_redistribution") from None
        for name,value in (("lookup",lookup),("total_paid",total),("pending",pending),
                ("replaces",replaces),("append_values",append),("calls",calls)):
            object.__setattr__(self,name,value)

    def pin(self):
        pinned=DefaultMopRedistributionCalculation(self.currency,self.party_currency,self.pos_profile,self.amount_to_pay,self.rows,self.lookup)
        _require_append(self.append_values,pinned.append_values)
        if (pinned!=self or type(self.replaces) is not bool or type(self.calls) is not tuple
                or any(type(name) is not str for name in self.calls)
                or _result_tag(self.total_paid)!=_result_tag(pinned.total_paid) or _result_tag(self.pending)!=_result_tag(pinned.pending)):
            raise PosAdjustmentError("default_mop_redistribution")
        return pinned

    def require_match(self,*,total_paid,pending,replaced,append_values,calls,setting_trace):
        try:
            pinned=self.pin()
            if (_result_tag(total_paid)!=_result_tag(pinned.total_paid) or _result_tag(pending)!=_result_tag(pinned.pending)
                    or type(replaced) is not bool or replaced!=pinned.replaces or type(calls) is not tuple
                    or any(type(value) is not str for value in calls) or calls!=pinned.calls
                    or type(setting_trace) is not tuple or setting_trace!=()):
                raise ValueError
            _require_append(append_values,pinned.append_values)
        except Exception:
            raise PosAdjustmentError("default_mop_observation_mismatch") from None

    def __repr__(self):return "<DefaultMopRedistributionCalculation row plan, NOT FX/payment eligibility>"
    def __reduce__(self):raise TypeError("default_mop_calculation_not_serializable")
