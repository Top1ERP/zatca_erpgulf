"""Same-owned advance ceiling inputs, before outstanding/write-off recursion.

No controller, normalization, invoice/cache write, transaction or authority I/O.
Current calculated inputs remain explicit observations, not derivation proof.
"""
from dataclasses import dataclass, field
import json

from .calculation_advance_rounding import AdvanceRoundingAcquisition, SavedAdvanceRoundingRead
from .calculation_rounding_stage import RoundingStageAcquisition, SavedRoundingStageRead, pin_stage, require_call_trace
from .calculation_owner_currency_access import OwnerCurrencyAcquisition
from .calculation_child_format_access import require_field_read
from .calculation_child_cache import _precision, _MISSING, _state, _bucket, _slot
from .calculation_field_rounding_access import _require_cache, _cache_slot, _result_tag
from .calculation_precision import FieldPrecisionResolution, _requires_currency_format
from .calculation_defaults import _fold
from .source_metadata import WRITE_OFF_PROFILE, project_source_metadata, _pin_metadata
from .write_off_source import LockedWriteOffRead, MariaDBWriteOffReader, pin_write_off
from .invoice_rounding_source import _meta as validate_write_meta
from .owner_currency_source import pin_owner_currency
from .financial_source_observation import _scalar, _validate_scalar
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


def _currency_cache(root):
    mapping = getattr(root._policy._dependencies()[0].local, "field_currency", _MISSING)
    state = _state(mapping, nullable=True)
    bucket = _MISSING if mapping is _MISSING or mapping is None else _bucket(mapping, (root._doctype, root._name))
    return (state, _state(bucket)), _slot(bucket, BASE)


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
                definition = metadata.get_field(BASE)
                if definition is None:
                    raise ValueError
                defaults = stage.numeric.financial.context.settings.defaults
                needs_format = _requires_currency_format(definition, _fold(json.loads(defaults._payload)["rows"]), stage.method.erp_major)
                context = None
                if needs_format:
                    proof = next(value for value in stage.fields if value.formats is not None
                        and root_meta.applied.get_field(value.target[2]).options == definition.options)
                    context = proof.formats.formats.context
                    slot = _cache_slot(self.currency_cache, allow_null=True)
                    if slot != ("absent",) and (slot != ("str", context.currency)):
                        raise ValueError
                elif self.currency_cache is not None:
                    raise ValueError
                precision = FieldPrecisionResolution(metadata, BASE, defaults, stage.method.erp_major, context)
                _require_cache(self.precision_cache, precision)
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


class AdvanceLimitAcquisition(AdvanceRoundingAcquisition):
    """Compose write-off/party inspection with the same advance graph/handle."""
    def __init__(self, policy, actor, invoice_name, doctype, major, *, write_off_metadata, **dependencies):
        self.limit_owner = None
        self.write_definition = None
        self.base_cache = None
        self.base_currency_cache = None
        self._write_metadata = write_off_metadata
        self.limit_currency = None
        if not callable(write_off_metadata):
            raise AdvanceLimitError("advance_limit_dependencies")
        super().__init__(policy,actor,invoice_name,doctype,major,_stage_fields=STAGE_FIELDS,**dependencies)
        self.limit_owner = OwnerCurrencyAcquisition(self.root, actor, self._owner_metadata)
        self.limit_currency = tuple(_scalar(self.root.document.get("currency")))
        self.write_definition, self.write_levels, self.write_values = self._write_state(self.root.document)
        self.limit_foreign = self.limit_owner.currency != self.root.document.get("currency")
        if self.limit_foreign:
            self.base_cache = _precision(self.root.document, BASE)
        self.recheck_access()

    def _write_state(self, doc):
        meta = validate_write_meta(project_source_metadata(doc.meta,base_fields={},profile=WRITE_OFF_PROFILE),
            profile=WRITE_OFF_PROFILE,fields=LockedWriteOffRead.FIELDS,checks=LockedWriteOffRead.CHECKS)
        levels = tuple(require_field_read(doc,name,self._actor,self.root._policy._dependencies()[0],
            self.root._policy.DENIED_MESSAGE) if meta.has_field(name) else None for name in LockedWriteOffRead.FIELDS)
        values = tuple((name,tuple(_scalar(doc.get(name)))) for name in LockedWriteOffRead.FIELDS)
        if any(not meta.has_field(name) and value != ("null",) for name,value in values):
            raise AdvanceLimitError("advance_limit_absent_getter")
        return meta,levels,values

    def recheck_access(self):
        super().recheck_access()
        if self.limit_owner is not None:
            self.limit_owner.recheck_access()
        if self.write_definition is not None:
            if any(tuple(_scalar(doc.get("currency"))) != self.limit_currency for doc in
                    (self.root.document,self.root._parent_load(self.root._doctype,self.root._name))):
                raise AdvanceLimitError("advance_limit_currency_changed")
            expected=self.write_definition,self.write_levels,self.write_values
            if (self._write_state(self.root.document) != expected
                    or self._write_state(self.root._parent_load(self.root._doctype,self.root._name)) != expected):
                raise AdvanceLimitError("advance_limit_getter_changed")
            if self.limit_foreign and _precision(self.root.document,BASE) != self.base_cache:
                raise AdvanceLimitError("advance_limit_precision_changed")
            if self.base_currency_cache is not None and _currency_cache(self.root) != self.base_currency_cache:
                raise AdvanceLimitError("advance_limit_currency_cache_changed")

    def _applied_write(self):
        supplied=self._write_metadata(self.root._policy._scope,(self.root._doctype,))
        if type(supplied) is not dict or set(supplied) != {self.root._doctype} or _pin_metadata(supplied[self.root._doctype]) != self.write_definition:
            raise AdvanceLimitError("advance_limit_metadata")
        return self.write_definition

    def prepare_metadata(self):
        super().prepare_metadata()
        self.limit_owner.prepare_metadata()
        self._applied_write()
        self.recheck_access()

    def load_for_update(self, connection, financial):
        observed=super().load_for_update(connection,financial)
        if dict(json.loads(financial.financial._payload)["header"])["currency"] != list(self.limit_currency):
            raise AdvanceLimitError("advance_limit_native_currency")
        self.limit_owner.load_for_update(connection,financial)
        self.write_reader=MariaDBWriteOffReader(connection)
        self.native_write=self.write_reader.load_for_update(financial,applied_metadata=self.write_definition)
        self._check_write()
        return observed

    def _check_write(self):
        values=dict(json.loads(self.native_write._payload)["fields"])
        for name,tag in self.write_values:
            if name==AUTO:
                self.native_write.require_saved_check_match({AUTO:_validate_scalar(list(tag))})
            elif (values[name] != list(tag) and not (values[name]==["absent"] and tag==("null",))):
                raise AdvanceLimitError("advance_limit_native_getter")
        self.recheck_access()

    def complete_defaults(self,connection,observed,defaults,company_metadata):
        if self.limit_foreign and _requires_currency_format(self.write_definition.get_field(BASE),
                _fold(json.loads(defaults._payload)["rows"]),observed[0].financial.financial.erp_major):
            self.base_currency_cache=_currency_cache(self.root)
        return super().complete_defaults(connection,observed,defaults,company_metadata)

    def check_getters(self, observed):
        super().check_getters(observed)
        self._check_write()

    def require_metadata_unchanged(self):
        super().require_metadata_unchanged()
        self.limit_owner.require_metadata_unchanged()
        self._applied_write()
        self.recheck_access()

    def require_unchanged(self, observed):
        super().require_unchanged(observed)
        self.limit_owner.require_unchanged()
        self.write_reader.require_unchanged(self.native_write)
        self._check_write()

    def build_result(self,financial,observed):
        stage=RoundingStageAcquisition.build_result(self,financial,observed)
        advance=super().build_result(financial,observed)
        return SavedAdvanceLimitRead(stage,advance,self.native_write,self.limit_owner.native,self.base_cache,self.base_currency_cache)


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

    def __repr__(self):
        return "<AdvanceLimitCalculation protected ceiling comparison, NOT settlement proof>"

    def __reduce__(self):
        raise TypeError("advance_limit_calculation_not_serializable")
