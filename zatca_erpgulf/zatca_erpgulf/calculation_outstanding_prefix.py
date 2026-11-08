"""Compare the primary outstanding prefix on the co-owned settlement source.

Round grand total, advance and write-off in order, then round the source again
before converting write-off to company currency. The original write-off field
keeps the first rounded value. Explicit CALCULATED inputs do not attest their
earlier derivation, advance allocation or controller/cache provenance. No writes.
"""

from dataclasses import dataclass, field

from .calculation_settlement_access import SavedSettlementRead, SettlementAccessError
from .calculation_receivable import PAYABLE_FIELDS, _values
from .calculation_rounding_stage import require_call_trace
from .calculated_totals import _input_tag
from .field_rounding import round_field_value

INPUT_FIELDS = (*PAYABLE_FIELDS, "conversion_rate")
ROUND_FIELDS = ("grand_total", "total_advance", "write_off_amount")


def _same_values(actual, expected):
    """Keep NULL, integer, float bits and signed zero; never coerce evidence."""
    if type(actual) is not tuple or len(actual) != len(expected):
        raise ValueError
    for row, pinned in zip(actual, expected):
        if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                or row[0] != pinned[0] or _input_tag(row[1], nullable=True) != _input_tag(pinned[1], nullable=True)):
            raise ValueError


@dataclass(frozen=True, repr=False)
class OutstandingPrefixCalculation:
    """Exact prefix comparison, not permission to run/persist a controller."""
    source: SavedSettlementRead = field(repr=False)
    representation: str
    values: tuple = field(repr=False)
    rounded: tuple = field(init=False, repr=False)
    payable_values: tuple = field(init=False, repr=False)
    round_trace: tuple = field(init=False, repr=False)
    conversion_trace: tuple = field(init=False, repr=False)
    round_lookups: int = field(init=False, repr=False)

    def __post_init__(self):
        try:
            if type(self.source) is not SavedSettlementRead:
                raise ValueError
            source = self.source.pin()
            values = _values(source.receivable, self.values, INPUT_FIELDS, self.representation)
            proofs = {proof.target[2]: proof.precision.precision for proof in source.prefix.fields}
            proofs.update((name, proof.precision) for name, proof in source.receivable.precisions)
            method = source.prefix.method
            def flt(value, name):
                return round_field_value(value, precision=proofs[name], method=method.method, erp_major=method.erp_major)
            rounded = tuple((name, flt(values[name], name)) for name in ROUND_FIELDS)
            changed = dict(values)
            changed.update(rounded)
            # Primary _set_in_company_currency rounds its source before FX,
            # does not assign that second rounding back to the source field,
            # and overwrites base_write_off_amount regardless of its old value.
            amount = flt(changed["write_off_amount"], "write_off_amount")
            changed["base_write_off_amount"] = flt(amount * values["conversion_rate"], "base_write_off_amount")
            payable_values = tuple((name, changed[name]) for name in PAYABLE_FIELDS)
            round_trace = tuple((name, None, proofs[name]) for name in ROUND_FIELDS)
            conversion_trace = tuple((name, proofs[name]) for name in ("write_off_amount", "base_write_off_amount"))
            lookups = 1 + (sum(values[name] is not None for name in ROUND_FIELDS) if not method.rounding.value else 0)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise SettlementAccessError("settlement_outstanding_prefix")
        for name, value in (("source", source), ("rounded", rounded), ("payable_values", payable_values),
                ("round_trace", round_trace), ("conversion_trace", conversion_trace), ("round_lookups", lookups)):
            object.__setattr__(self, name, value)

    def pin(self):
        try:
            result = OutstandingPrefixCalculation(self.source, self.representation, self.values)
            _same_values(self.rounded, result.rounded)
            _same_values(self.payable_values, result.payable_values)
            if result != self or type(self.round_lookups) is not int:
                raise ValueError
            require_call_trace(None, (), self.round_trace, result.round_trace, 0)
            require_call_trace(None, (), self.conversion_trace, result.conversion_trace, 0)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise SettlementAccessError("settlement_outstanding_prefix")
        return result

    def require_match(self, *, rounded, payable_values, round_settings, round_precision,
                      conversion_settings, conversion_precision):
        try:
            result = self.pin()
            _same_values(rounded, result.rounded)
            _same_values(payable_values, result.payable_values)
            raw = result.source.prefix.method.rounding.value
            require_call_trace(raw, round_settings, round_precision, result.round_trace, result.round_lookups)
            # Both conversions now consume non-NULL floats. Each primary flt
            # resolves the method independently, even when the setting is set.
            require_call_trace(raw, conversion_settings, conversion_precision, result.conversion_trace, 2)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise SettlementAccessError("settlement_outstanding_prefix_observation")

    def __repr__(self): return "<OutstandingPrefixCalculation checked prefix, NOT advance/controller provenance>"
    def __reduce__(self): raise TypeError("settlement_outstanding_prefix_not_serializable")
