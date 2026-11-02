"""Explicit current-input aggregate comparisons, separate from saved equality.

Complete ordered observations bind membership/types to native financial data.
CALCULATED inputs may differ from saved money: their origin/earlier arithmetic
is external, never silently attested. No ORM, controller, SQL, cache or writes.
"""

from dataclasses import dataclass, field
import hashlib
import json
import math

from .financial_source_sql import LockedInvoiceFinancialRead, _pin_read
from .financial_source_observation import _canonical, _child_type
from .financial_numeric_view import _native_cells, _expected
from .calculation_rounding_stage import SavedRoundingStageRead, pin_stage, require_call_trace
from .calculation_precision import _requires_currency_format
from .calculation_defaults import _fold
from .calculation_field_rounding_access import _result_tag
from .field_rounding import round_field_value

ITEM_FIELDS = ("qty", "amount", "base_amount", "net_amount", "base_net_amount")
TOTAL_FIELDS = ("total", "base_total", "net_total", "base_net_total")
TABLE_FIELDS = {"items": ITEM_FIELDS, "advances": ("allocated_amount",)}


class CalculatedTotalsError(ValueError):
    """Static English codes, without protected values or source identifiers."""


def _input_tag(value, *, nullable=False):
    if value is None and nullable:
        return ["null"]
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e64:
        raise ValueError
    return list(_result_tag(value))


@dataclass(frozen=True, repr=False)
class CalculationRows:
    """Complete native-shaped current rows, NOT proof of executed calculation.

    NUMERIC_FIXED must equal the saved precision-free numeric projection.
    CALCULATED explicitly observes changed values; their prior derivation is
    outside this comparison. Neither mode authorizes persistence or sending.
    """
    financial: LockedInvoiceFinancialRead = field(repr=False)
    table: str
    representation: str
    values: tuple = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            native = _pin_read(self.financial)
            if (
                type(self.table) is not str or self.table not in TABLE_FIELDS
                or type(self.representation) is not str
                or self.representation not in ("NUMERIC_FIXED", "CALCULATED")
                or type(self.values) is not tuple
            ):
                raise ValueError
            table = dict(json.loads(native.financial._payload)["tables"])[self.table]
            if type(table) is not dict or len(table["rows"]) != len(self.values):
                raise ValueError
            names = TABLE_FIELDS[self.table]
            child_type = _child_type(native.financial.doctype, self.table)
            meta = next(row.applied for row in native.metadata if row.applied.name == child_type)
            if any(
                meta.get_field(name) is None
                or meta.get_field(name).fieldtype not in ("Currency", "Float", "Percent")
                for name in names
            ):
                raise ValueError
            cells = {cell[:3]: cell for cell in _native_cells(native)}
            encoded = []
            for actual, saved in zip(self.values, table["rows"]):
                if (
                    type(actual) is not tuple or len(actual) != len(names) + 1
                    or type(actual[0]) is not str or actual[0] != saved[0]
                ):
                    raise ValueError
                tags = [_input_tag(value, nullable=self.table == "advances") for value in actual[1:]]
                if self.representation == "NUMERIC_FIXED":
                    for name, tag in zip(names, tags):
                        cell = cells[self.table, actual[0], name]
                        if tag != _expected(cell[4], "NUMERIC_FIXED", cell[3]):
                            raise ValueError
                encoded.append([actual[0], *tags])
            payload = _canonical(dict(
                profile="calculation-current-rows/v1", financial=native.sha256,
                table=self.table, representation=self.representation, values=encoded,
            ))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculatedTotalsError("calculation_current_rows")
        object.__setattr__(self, "financial", native)
        digest = hashlib.sha256(b"zatca-current-calculation-rows/v1\0" + payload).hexdigest()
        object.__setattr__(self, "sha256", digest)

    def _pin(self):
        pinned = CalculationRows(self.financial, self.table, self.representation, self.values)
        if pinned != self:
            raise CalculatedTotalsError("calculation_current_rows")
        return pinned

    def __repr__(self):
        return "<CalculationRows protected observed current values, NOT derived-origin proof>"

    def __reduce__(self):
        raise TypeError("calculation_current_rows_not_serializable")


def _source(source, rows, table, fields):
    pinned = pin_stage(source)
    if type(rows) is not CalculationRows:
        raise ValueError
    rows = rows._pin()
    native = pinned.numeric.view.financial
    expected = tuple(("header", native.financial.name, name) for name in fields)
    if (
        rows.financial != native or rows.table != table or pinned.targets != expected
        or len(pinned.fields) != len(fields) or pinned.do_not_round_fields is not None
    ):
        raise ValueError
    return pinned, rows


def _compare_values(actual, expected):
    if type(actual) is not tuple or len(actual) != len(expected):
        raise ValueError
    for supplied, wanted in zip(actual, expected):
        if (
            type(supplied) is not tuple or len(supplied) != 2 or type(supplied[0]) is not str
            or supplied[0] != wanted[0] or _result_tag(supplied[1]) != _result_tag(wanted[1])
        ):
            raise ValueError


@dataclass(frozen=True, repr=False)
class NetTotalsCalculation:
    """Ordered item sums and one bound header round; not complete tax math."""
    source: SavedRoundingStageRead = field(repr=False)
    rows: CalculationRows = field(repr=False)
    before: tuple = field(init=False, repr=False)
    after: tuple = field(init=False, repr=False)
    total_qty: float = field(init=False, repr=False)

    def __post_init__(self):
        try:
            source, rows = _source(self.source, self.rows, "items", TOTAL_FIELDS)
            totals = [0.0] * 5
            # Match the controller's left-to-right float accumulation exactly.
            # Decimal/fsum/reordered addition changes cancellation and rounding.
            for row in rows.values:
                for index, value in enumerate(row[1:]):
                    totals[index] += value
                    if not math.isfinite(totals[index]):
                        raise ValueError
            before = tuple(zip(TOTAL_FIELDS, totals[1:]))
            after = tuple(
                (name, round_field_value(
                    value, precision=proof.precision.precision,
                    method=source.method.method, erp_major=source.method.erp_major,
                ))
                for (name, value), proof in zip(before, source.fields)
            )
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculatedTotalsError("calculation_net_totals")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "after", after)
        object.__setattr__(self, "total_qty", totals[0])

    def require_match(self, before, after, *, total_qty, setting_trace, precision_trace):
        try:
            pinned = NetTotalsCalculation(self.source, self.rows)
            if pinned != self:
                raise ValueError
            _compare_values(self.before, pinned.before)
            _compare_values(self.after, pinned.after)
            if _result_tag(self.total_qty) != _result_tag(pinned.total_qty):
                raise ValueError
            _compare_values(before, pinned.before)
            _compare_values(after, pinned.after)
            if _result_tag(total_qty) != _result_tag(pinned.total_qty):
                raise ValueError
            precisions = tuple(
                (name, None, proof.precision.precision)
                for name, proof in zip(TOTAL_FIELDS, pinned.source.fields)
            )
            raw = pinned.source.method.rounding.value
            require_call_trace(raw, setting_trace, precision_trace, precisions, 1 + (4 if not raw else 0))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculatedTotalsError("calculation_net_totals_observation")

    def __repr__(self):
        return "<NetTotalsCalculation protected derived comparison, NOT executed tax proof>"

    def __reduce__(self):
        raise TypeError("calculation_net_totals_not_serializable")


@dataclass(frozen=True, repr=False)
class AdvanceAggregateCalculation:
    """Only the noncancelled advance aggregation PREFIX; no settlement limit/FX.

    Row precision is fresh direct-row metadata/default precision. Uncaptured16
    row-currency fallback is refused, never replaced by parent-owned precision.
    Supplied precision traces still do not prove live row-cache provenance.
    """
    source: SavedRoundingStageRead = field(repr=False)
    rows: CalculationRows = field(repr=False)
    row_values: tuple = field(init=False, repr=False)
    total_allocated: int | float = field(init=False, repr=False)
    total_advance: int | float = field(init=False, repr=False)
    row_precision: int | None = field(init=False)

    def __post_init__(self):
        try:
            source, rows = _source(self.source, self.rows, "advances", ("total_advance",))
            header = dict(json.loads(rows.financial.financial._payload)["header"])
            if header["docstatus"] not in (["int", "0"], ["int", "1"]):
                raise ValueError
            precision = None
            if rows.values:
                dt = _child_type(rows.financial.financial.doctype, "advances")
                meta = next(row.applied for row in rows.financial.metadata if row.applied.name == dt)
                defaults = source.numeric.financial.context.settings.defaults
                if _requires_currency_format(
                    meta.get_field("allocated_amount"), _fold(json.loads(defaults._payload)["rows"]),
                    source.method.erp_major,
                ):
                    raise ValueError
                precision = source.numeric.financial.resolve_precision(dt, "allocated_amount").precision
            # An empty table never calls row.precision or its currency fallback.
            values = tuple(
                round_field_value(
                    row[1], precision=precision, method=source.method.method,
                    erp_major=source.method.erp_major,
                )
                for row in rows.values
            )
            # Python sum starts at int(0); legacy precision=0 may keep integers.
            allocated = sum(values)
            total = round_field_value(
                allocated, precision=source.fields[0].precision.precision,
                method=source.method.method, erp_major=source.method.erp_major,
            )
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculatedTotalsError("calculation_advance_aggregate")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "row_values", values)
        object.__setattr__(self, "total_allocated", allocated)
        object.__setattr__(self, "total_advance", total)
        object.__setattr__(self, "row_precision", precision)

    def require_match(self, *, total_advance, setting_trace, precision_trace):
        try:
            pinned = AdvanceAggregateCalculation(self.source, self.rows)
            if (
                pinned != self or type(self.row_precision) is not type(pinned.row_precision)
                or self.row_precision != pinned.row_precision
                or _result_tag(self.total_allocated) != _result_tag(pinned.total_allocated)
                or _result_tag(self.total_advance) != _result_tag(pinned.total_advance)
                or type(self.row_values) is not tuple or len(self.row_values) != len(pinned.row_values)
                or any(_result_tag(a) != _result_tag(b) for a, b in zip(self.row_values, pinned.row_values))
                or _result_tag(total_advance) != _result_tag(pinned.total_advance)
            ):
                raise ValueError
            expected = tuple((row[0], "allocated_amount", pinned.row_precision) for row in pinned.rows.values)
            expected += ((
                pinned.rows.financial.financial.name, "total_advance",
                pinned.source.fields[0].precision.precision,
            ),)
            lookups = 1 + sum(row[1] is not None for row in pinned.rows.values)
            require_call_trace(pinned.source.method.rounding.value, setting_trace, precision_trace, expected, lookups)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculatedTotalsError("calculation_advance_observation")

    def __repr__(self):
        return "<AdvanceAggregateCalculation protected prefix, NOT settlement/FX proof>"

    def __reduce__(self):
        raise TypeError("calculation_advance_aggregate_not_serializable")
