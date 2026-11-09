"""Compare saved advance rows with totals consumed by a saved settlement plan.

An explicit read-only consistency report, never advance matching/relinking,
fiscal acceptance, ledger eligibility or a controller/write/transport operation.
Use existing aggregation/precision kernels; do not repair a stale saved total.
"""

from dataclasses import dataclass, field
import json

from .calculation_settlement_plan import SavedSettlementPlan
from .calculation_settlement_access import SettlementAccessError
from .calculation_rounding_stage import project_stage
from .calculated_totals import AdvanceAggregateCalculation, CalculationRows
from .financial_numeric_view import _native_cells, _expected
from .financial_source_observation import _validate_scalar
from .calculation_field_rounding_access import _result_tag
from .field_rounding import round_field_value


def _pin_aggregate(value):
    if type(value) is not AdvanceAggregateCalculation: raise ValueError
    result = AdvanceAggregateCalculation(value.source, value.rows, value.advance_context)
    if (result != value or type(value.row_values) is not tuple
            or type(value.row_precision) is not type(result.row_precision)
            or type(value.row_precisions) is not tuple or len(value.row_precisions) != len(result.row_precisions)
            or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or type(row[1]) is not int
                   for row in value.row_precisions)
            or tuple(_result_tag(v) for v in result.row_values) != tuple(_result_tag(v) for v in value.row_values)
            or _result_tag(result.total_allocated) != _result_tag(value.total_allocated)
            or _result_tag(result.total_advance) != _result_tag(value.total_advance)):
        raise ValueError
    return result


@dataclass(frozen=True, repr=False)
class SettlementAdvanceComparison:
    """MATCH/MISMATCH/NOT_CONSUMED means numeric consistency only, never PASS."""
    plan: SavedSettlementPlan = field(repr=False)
    aggregate: AdvanceAggregateCalculation = field(repr=False)
    expected: tuple = field(init=False, repr=False)
    observed: tuple = field(init=False, repr=False)
    row_count: int = field(init=False)
    status: str = field(init=False)

    def __post_init__(self):
        try:
            if type(self.plan) is not SavedSettlementPlan: raise ValueError
            plan, aggregate = self.plan.pin(), _pin_aggregate(self.aggregate)
            stage = project_stage(plan.source.prefix, ("total_advance",))
            if (aggregate.source != stage or aggregate.rows.table != "advances"
                    or aggregate.rows.representation != "NUMERIC_FIXED"
                    or aggregate.rows.financial != plan.source.prefix.numeric.view.financial):
                raise ValueError
            expected, observed = [], []
            current = aggregate.total_advance
            method = stage.method
            # calculate_total_advance already rounded the aggregate. Outstanding
            # rounds that field again, and rounds it once more on a write-off
            # re-entry. Compare those consumed values in their actual order.
            for name, sequence in (("first", plan.first), ("second", plan.second)):
                if sequence is None or sequence.prefix is None: continue
                current = round_field_value(current, precision=stage.fields[0].precision.precision,
                    method=method.method, erp_major=method.erp_major)
                expected.append((name, current))
                observed.append((name, dict(sequence.prefix.payable_values)["total_advance"]))
            if not observed: status = "NOT_CONSUMED"
            else: status = "MATCH" if tuple(_result_tag(v) for _, v in expected) == tuple(
                _result_tag(v) for _, v in observed) else "MISMATCH"
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid: raise SettlementAccessError("settlement_advance_comparison")
        for name, value in (("plan", plan), ("aggregate", aggregate), ("expected", tuple(expected)),
                ("observed", tuple(observed)), ("row_count", len(aggregate.rows.values)), ("status", status)):
            object.__setattr__(self, name, value)

    def pin(self):
        try:
            result = SettlementAdvanceComparison(self.plan, self.aggregate)
            if (result != self or type(self.row_count) is not int or type(self.status) is not str
                    or type(self.expected) is not tuple or type(self.observed) is not tuple):
                raise ValueError
            for actual, pinned in ((self.expected, result.expected), (self.observed, result.observed)):
                if (len(actual) != len(pinned) or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                        or row[0] != target[0] or _result_tag(row[1]) != _result_tag(target[1]) for row, target in zip(actual, pinned))):
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid: raise SettlementAccessError("settlement_advance_comparison")
        return result

    def __repr__(self): return "<SettlementAdvanceComparison numeric consistency, NOT advance/GL/ZATCA eligibility>"
    def __reduce__(self): raise TypeError("settlement_advance_comparison_not_serializable")


def compare_saved_advances(plan, *, advance_context=None):
    """Use only complete saved row amounts; no independent capture or defaults.

    Existing same-stage row format/cache evidence can be supplied explicitly.
    An uncaptured unset16 row-currency format is refused by the existing kernel.
    This never regenerates or reclassifies historical documents or references.
    """
    try:
        if type(plan) is not SavedSettlementPlan: raise ValueError
        stage = project_stage(plan.source.prefix, ("total_advance",))
        native = stage.numeric.view.financial
        body = json.loads(native.financial._payload)
        table = dict(body["tables"])["advances"]
        if type(table) is not dict: raise ValueError
        cells = {cell[1]: cell for cell in _native_cells(native) if cell[0] == "advances" and cell[2] == "allocated_amount"}
        values = tuple((name, _validate_scalar(_expected(cells[name][4], "NUMERIC_FIXED", cells[name][3])))
                       for name, _, _ in table["rows"])
        rows = CalculationRows(native, "advances", "NUMERIC_FIXED", values)
        aggregate = AdvanceAggregateCalculation(stage, rows, advance_context)
        return SettlementAdvanceComparison(plan, aggregate)
    except Exception:
        invalid = True
    if invalid: raise SettlementAccessError("settlement_saved_advances")
