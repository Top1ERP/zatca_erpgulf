"""Same-owned advance ceiling inputs, before outstanding/write-off recursion.

No controller, normalization, invoice/cache write, transaction or authority I/O.
Current calculated inputs remain explicit observations, not derivation proof.
"""
from dataclasses import dataclass, field
import json

from .calculation_advance_rounding import AdvanceRoundingAcquisition, SavedAdvanceRoundingRead
from .calculation_rounding_stage import RoundingStageAcquisition, SavedRoundingStageRead, pin_stage, require_call_trace
from .calculation_field_rounding_access import _result_tag
from .calculation_precision import FieldPrecisionResolution
# Retain the inspector's existing native-type alias for its consumers.
from .write_off_source import LockedWriteOffRead, pin_write_off
from .owner_currency_source import pin_owner_currency
from .calculation_write_off_access import WriteOffStageMixin, WriteOffInputsAcquisition, resolve_write_precision
from .financial_numeric_view import _native_cells, _expected
from .calculated_totals import AdvanceAggregateCalculation, _input_tag
from .field_rounding import round_field_value

AUTO = "write_off_outstanding_amount_automatically"
BASE = "base_write_off_amount"
STAGE_FIELDS = ("total_advance", "grand_total", "base_grand_total")
CURRENT_FIELDS = ("grand_total", "rounded_total", "conversion_rate", "write_off_amount")


class AdvanceLimitError(ValueError):
    """Static English diagnostics without protected invoice or settings values."""


@dataclass(frozen=True)
class AdvanceLimitRequest:
    """Internal fixed selection for the existing owned service."""


@dataclass(frozen=True, repr=False)
class SavedAdvanceLimitRead:
    stage: SavedRoundingStageRead = field(repr=False)
    advance: SavedAdvanceRoundingRead = field(repr=False)
    write_off: LockedWriteOffRead = field(repr=False)
    party: object = field(repr=False)
    precision_cache: tuple | None = field(repr=False)
    currency_cache: tuple | None = field(repr=False)
    base_precision: FieldPrecisionResolution | None = field(init=False, repr=False)
    foreign: bool = field(init=False)

    def __post_init__(self):
        try:
            stage = pin_stage(self.stage)
            if type(self.advance) is not SavedAdvanceRoundingRead:
                raise ValueError
            advance = self.advance.pin()
            write_off, party = pin_write_off(self.write_off), pin_owner_currency(self.party)
            native = stage.numeric.view.financial
            if (tuple(target[2] for target in stage.targets) != STAGE_FIELDS
                    or any(target[:2] != ("header", native.financial.name) for target in stage.targets)
                    or stage.do_not_round_fields is not None or advance.stage.numeric != stage.numeric
                    or advance.stage.method != stage.method or advance.stage.owner_document != stage.owner_document
                    or advance.stage.fields != (stage.fields[0],) or write_off.financial != native
                    or party.name != native.financial.name or party.metadata.applied.name != native.financial.doctype
                    or party.revision != stage.numeric.financial.context.settings.sources[1].revision):
                raise ValueError
            root_meta = next(row for row in native.metadata if row.applied.name == native.financial.doctype)
            if json.loads(party.metadata._payload)["doctype"] != json.loads(root_meta._payload)["doctype"]:
                raise ValueError
            header = dict(json.loads(native.financial._payload)["header"])
            foreign = header["currency"] != ["str", party.currency]
            metadata = write_off.metadata.applied
            if metadata.get_field("write_off_amount") is None:
                raise ValueError
            precision = None
            if foreign:
                precision = resolve_write_precision(stage, write_off, BASE, self.precision_cache, self.currency_cache)
            elif self.precision_cache is not None or self.currency_cache is not None:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise AdvanceLimitError("advance_limit_context")
        for name, value in (("stage",stage),("advance",advance),("write_off",write_off),("party",party),
                            ("foreign",foreign),("base_precision",precision)):
            object.__setattr__(self,name,value)

    def pin(self):
        pinned = SavedAdvanceLimitRead(self.stage,self.advance,self.write_off,self.party,self.precision_cache,self.currency_cache)
        if pinned != self or type(self.foreign) is not bool:
            raise AdvanceLimitError("advance_limit_context")
        return pinned

    def __repr__(self):
        return "<SavedAdvanceLimitRead protected ceiling context, NOT settlement authority>"

    def __reduce__(self):
        raise TypeError("advance_limit_not_serializable")


class AdvanceLimitAcquisition(WriteOffStageMixin, AdvanceRoundingAcquisition):
    """Compose shared write-off inputs with the existing advance graph/handle."""

    def __init__(self, policy, actor, invoice_name, doctype, major, *, write_off_metadata, **dependencies):
        self.write_inputs = None
        super().__init__(policy, actor, invoice_name, doctype, major, _stage_fields=STAGE_FIELDS, **dependencies)
        self.write_inputs = WriteOffInputsAcquisition(self.root, actor, write_off_metadata,
            self._owner_metadata, "foreign_base")
        self.recheck_access()

    def build_result(self, financial, observed):
        stage = RoundingStageAcquisition.build_result(self, financial, observed)
        advance = super().build_result(financial, observed)
        inputs = self.write_inputs
        return SavedAdvanceLimitRead(stage, advance, inputs.native, inputs.owner.native,
            inputs.precision_cache(BASE), inputs.field_currency_cache(BASE))


@dataclass(frozen=True,repr=False)
class AdvanceLimitCalculation:
    """Compare the prefix ceiling/decision; no outstanding or settlement math."""
    source: SavedAdvanceLimitRead = field(repr=False)
    aggregate: AdvanceAggregateCalculation = field(repr=False)
    representation: str
    values: tuple = field(repr=False)
    invoice_total: int | float = field(init=False,repr=False)
    blocked: bool = field(init=False)
    reset_write_off: bool = field(init=False)
    precision_trace: tuple = field(init=False,repr=False)
    setting_count: int = field(init=False,repr=False)

    def __post_init__(self):
        try:
            source=self.source.pin()
            if type(self.aggregate) is not AdvanceAggregateCalculation:
                raise ValueError
            aggregate=AdvanceAggregateCalculation(self.aggregate.source,self.aggregate.rows,self.aggregate.advance_context)
            if (aggregate != self.aggregate
                    or _result_tag(aggregate.total_allocated) != _result_tag(self.aggregate.total_allocated)
                    or _result_tag(aggregate.total_advance) != _result_tag(self.aggregate.total_advance)
                    or tuple(_result_tag(value) for value in aggregate.row_values) != tuple(_result_tag(value) for value in self.aggregate.row_values)
                    or aggregate.advance_context != source.advance
                    or type(self.representation) is not str or self.representation not in ("NUMERIC_FIXED","CALCULATED")
                    or type(self.values) is not tuple or len(self.values) != len(CURRENT_FIELDS)):
                raise ValueError
            native=source.stage.numeric.view.financial
            cells={cell[:3]:cell for cell in _native_cells(native)}
            write=dict(json.loads(source.write_off._payload)["fields"])
            for (name,value),expected in zip(self.values,CURRENT_FIELDS):
                if name != expected:
                    raise ValueError
                tag=_input_tag(value,nullable=name in ("rounded_total","write_off_amount"))
                if self.representation=="NUMERIC_FIXED":
                    original=write[name] if name=="write_off_amount" else cells["header",native.financial.name,name][4]
                    kind="Currency" if name=="write_off_amount" else cells["header",native.financial.name,name][3]
                    if tag != _expected(original,"NUMERIC_FIXED",kind):
                        raise ValueError
            values=dict(self.values)
            method=source.stage.method
            def flt(value,precision=None):
                return round_field_value(value,precision=precision,method=method.method,erp_major=method.erp_major)
            grand=values["rounded_total"] or values["grand_total"]
            precisions={proof.target[2]:proof.precision.precision for proof in source.stage.fields}
            if not source.foreign:
                total=flt(grand-flt(values["write_off_amount"]),precisions["grand_total"])
                trace=(("grand_total",precisions["grand_total"]),)
                count=1
            else:
                base_write=flt(flt(values["write_off_amount"])*values["conversion_rate"],source.base_precision.precision)
                selected="grand_total" if method.erp_major==15 else "base_grand_total"
                total=flt(grand*values["conversion_rate"],precisions[selected])-base_write
                trace=((BASE,source.base_precision.precision),(selected,precisions[selected]))
                count=2
            blocked=bool(total>0 and aggregate.total_advance>total)
            reset=not blocked and bool(dict(source.write_off.normalized_checks)[AUTO])
        except Exception:
            invalid=True
        else:
            invalid=False
        if invalid:
            raise AdvanceLimitError("advance_limit_calculation")
        for name,value in (("source",source),("aggregate",aggregate),("invoice_total",total),("blocked",blocked),
                ("reset_write_off",reset),("precision_trace",trace),("setting_count",count)):
            object.__setattr__(self,name,value)

    def require_match(self,*,invoice_total,blocked,reset_write_off,setting_trace,precision_trace):
        try:
            pinned=AdvanceLimitCalculation(self.source,self.aggregate,self.representation,self.values)
            if (pinned != self or type(self.blocked) is not bool or type(self.reset_write_off) is not bool
                    or type(self.setting_count) is not int or _result_tag(self.invoice_total) != _result_tag(pinned.invoice_total)
                    or _result_tag(invoice_total) != _result_tag(pinned.invoice_total)
                    or type(blocked) is not bool or blocked != pinned.blocked
                    or type(reset_write_off) is not bool or reset_write_off != pinned.reset_write_off):
                raise ValueError
            require_call_trace(self.source.stage.method.rounding.value,setting_trace,precision_trace,pinned.precision_trace,pinned.setting_count)
        except Exception:
            invalid=True
        else:
            invalid=False
        if invalid:
            raise AdvanceLimitError("advance_limit_observation")

    def pin(self):
        """Rebuild decisions before they authorize a derived numeric handoff."""
        try:
            result = AdvanceLimitCalculation(self.source, self.aggregate, self.representation, self.values)
            aggregate = self.aggregate
            expected = tuple((name, "allocated_amount", precision) for name, precision in aggregate.row_precisions)
            expected += ((aggregate.rows.financial.financial.name, "total_advance",
                aggregate.source.fields[0].precision.precision),)
            count = 1 + sum(row[1] is not None for row in aggregate.rows.values)
            raw = aggregate.source.method.rounding.value
            aggregate.require_match(total_advance=aggregate.total_advance,
                setting_trace=(("rounding_method", raw),) * count, precision_trace=expected)
            if (result != self or type(self.blocked) is not bool or type(self.reset_write_off) is not bool
                    or type(self.setting_count) is not int or type(self.precision_trace) is not tuple
                    or _result_tag(self.invoice_total) != _result_tag(result.invoice_total)):
                raise ValueError
            require_call_trace(None, (), self.precision_trace, result.precision_trace, 0)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise AdvanceLimitError("advance_limit_calculation")
        return result

    def __repr__(self):
        return "<AdvanceLimitCalculation protected ceiling comparison, NOT settlement proof>"

    def __reduce__(self):
        raise TypeError("advance_limit_calculation_not_serializable")


def settlement_limit_context(source, advance):
    """Reuse only co-owned proofs; acquire no second root, currency or defaults."""
    from .calculation_settlement_access import SavedSettlementRead
    if type(source) is not SavedSettlementRead:
        raise AdvanceLimitError("advance_settlement_source")
    source = source.pin()
    prefix = source.prefix
    proofs = {proof.target[2]: proof for proof in (*prefix.fields, *source.receivable.stage.fields)}
    selected = tuple(proofs[name] for name in STAGE_FIELDS)
    stage = SavedRoundingStageRead(prefix.numeric, prefix.method, tuple(proof.target for proof in selected),
        None, prefix.owner_document, selected)
    caches = {name: (precision, currency) for name, precision, currency in source.receivable.caches}
    precision, currency = caches[BASE] if source.receivable.foreign else (None, None)
    return SavedAdvanceLimitRead(stage, advance, source.receivable.write_off, source.receivable.party,
        precision, currency)


def advance_settlement_changes(source, calculation):
    """Only the aggregate assignment and conditional integer-zero reset.

    The ceiling consumes the OLD write-off amount. It must pass before the
    reset and the first outstanding call. No saved value is mutated here.
    """
    try:
        if type(calculation) is not AdvanceLimitCalculation:
            raise ValueError
        calculation = calculation.pin()
        if (calculation.blocked or calculation.representation != "NUMERIC_FIXED"
                or calculation.aggregate.rows.representation != "NUMERIC_FIXED"
                or calculation.aggregate.rows.table != "advances"
                or settlement_limit_context(source, calculation.source.advance) != calculation.source):
            raise ValueError
        changes = (("total_advance", calculation.aggregate.total_advance),)
        if calculation.reset_write_off:
            changes += (("write_off_amount", 0),)
        return changes
    except Exception:
        invalid = True
    if invalid:
        raise AdvanceLimitError("advance_settlement_transition")
