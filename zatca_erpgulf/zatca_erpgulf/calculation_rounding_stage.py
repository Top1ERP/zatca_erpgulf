"""Bounded ordered field-stage acquisition on the existing owned pipeline.

One numeric graph/native read and method source serve a single target document.
Reuse per-field policy and share format SQL by parent currency scope. No
controller execution, document mutation, runtime registration or authority I/O.
"""

from dataclasses import dataclass, field

from .calculation_numeric_access import NumericAcquisition, SavedFinancialNumericRead
from .calculation_rounding_access import RoundingAcquisition, SavedRoundingContext
from .calculation_field_rounding_access import (
    FieldRoundingAcquisition, _target, _result_tag, _pin_stage_fields, MAX_STAGE_FIELDS,
)
from .financial_numeric_view import _native_cells, _expected, _getter
from .financial_source_observation import _name


class RoundingStageError(ValueError):
    """Static English diagnostics, without selected values or settings."""


@dataclass(frozen=True, repr=False)
class RoundingStageRequest:
    """Internal selection only; validation stays inside the localized service."""
    fieldnames: tuple
    parentfield: str | None = None
    row_name: str | None = None
    do_not_round_fields: tuple | None = None


def _names(value, *, empty=False):
    if type(value) is not tuple or not (0 if empty else 1) <= len(value) <= MAX_STAGE_FIELDS:
        raise ValueError
    for name in value:
        _name(name)
    if len(set(value)) != len(value):
        raise ValueError
    return value


def _skips(value, major):
    if value is None:
        return ()
    if major != 16:
        raise ValueError
    return _names(value,empty=True)


class RoundingStageAcquisition:
    """Compose existing field policies; never invoke independent captures."""

    def __init__(self, policy, actor, invoice_name, doctype, request, major, **dependencies):
        if type(request) is not RoundingStageRequest:
            raise RoundingStageError("rounding_stage_selection")
        self.request = request
        self.names = _names(request.fieldnames)
        self.skips = _skips(request.do_not_round_fields,major)
        self.root = NumericAcquisition(policy,actor,invoice_name,doctype)
        self.tables = self.root.tables
        self.targets = tuple(_target((request.parentfield,request.row_name,name),self.root.schema,
            doctype,invoice_name,self.tables) for name in self.names)
        self.method = RoundingAcquisition(policy,actor,dependencies["metadata_reader"],dependencies["cache_reader"],None)
        self.fields = tuple(FieldRoundingAcquisition(policy,actor,invoice_name,doctype,
            (request.parentfield,request.row_name,name),_shared=(self.root,self.method),**dependencies)
            for name in self.names if name not in self.skips)
        self.recheck_access()

    def recheck_access(self):
        self.root.recheck_access()
        self.method.recheck_access()
        for selected in self.fields:
            selected.recheck_local()
        for source in self._sources():
            source.recheck_access()

    def _sources(self):
        unique = {}
        for selected in self.fields:
            for source in (selected.formats,selected.owner_currency):
                if source is not None:unique[id(source)] = source
        return tuple(unique.values())

    def prepare_metadata(self):
        self.root.prepare_metadata()
        self.method.prepare_metadata()
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        self.root.require_financial_metadata(metadata)

    def load_for_update(self, connection, financial):
        view = self.root.load_for_update(connection,financial)
        method = self.method.load_for_update(connection)
        self.method.check_cache(method)
        return view,method,()

    def complete_defaults(self, connection, observed, defaults, company_metadata):
        view,method,prior = observed
        if prior:
            raise RoundingStageError("rounding_stage_already_completed")
        # Observe every consumed currency slot BEFORE any format provider can
        # mutate another selected field's cache. One pool exists on THIS owner.
        for selected in self.fields:
            if selected.format_scope(view,defaults) is not None:
                selected.currency_cache = selected._currency_cache()
        pool = {}
        fields = tuple(selected.complete_defaults(connection,(view,method,None),defaults,
            company_metadata,_pool=pool) for selected in self.fields)
        self.recheck_access()
        return view,method,fields

    def check_getters(self, observed):
        view,method,fields = observed
        self.root.check_getters(view)
        self.method.check_cache(method)
        if len(fields) != len(self.fields):
            raise RoundingStageError("rounding_stage_field_binding")
        checked = set()
        for selected,value in zip(self.fields,fields):
            if (type(value) is not tuple or len(value) != 3 or value[:2] != (view,method)
                    or (selected.formats is None) != (value[2] is None)):
                raise RoundingStageError("rounding_stage_field_binding")
            if selected.formats is not None and id(selected.formats) not in checked:
                selected.formats.check_cache(value[2])
                checked.add(id(selected.formats))
            selected._check_company_cache()
        self.recheck_access()

    def require_metadata_unchanged(self):
        self.method.require_metadata_unchanged()
        for source in self._sources():
            source.require_metadata_unchanged()
        self.recheck_access()

    def require_unchanged(self, observed):
        view,method,fields = observed
        self.root.require_unchanged(view)
        self.method.require_unchanged(method)
        checked = set()
        for selected,value in zip(self.fields,fields):
            if selected.owner_currency is not None and id(selected.owner_currency) not in checked:
                selected.owner_currency.require_unchanged()
                checked.add(id(selected.owner_currency))
            source = selected.formats
            if source is not None and id(source) not in checked:
                if source.company_source is not None:
                    source.company_reader.require_unchanged(source.company_source)
                source.reader.require_unchanged(value[2])
                checked.add(id(source))
        self.recheck_access()

    def build_result(self, financial, observed):
        view,method,fields = observed
        numeric = SavedFinancialNumericRead(financial,view,self.tables)
        context = SavedRoundingContext(financial.context,view.financial.financial.erp_major,None,method,self.method.rows)
        results = tuple(selected.build_result(financial,value) for selected,value in zip(self.fields,fields))
        return SavedRoundingStageRead(numeric,context,self.targets,self.request.do_not_round_fields,
            id(self.root.document),results)


def pin_stage(value):
    """Reconstruct a supplied stage; this is consistency, not source authority."""
    if type(value) is not SavedRoundingStageRead:
        raise RoundingStageError("rounding_stage_result")
    pinned = SavedRoundingStageRead(
        value.numeric, value.method, value.targets, value.do_not_round_fields,
        value.owner_document, value.fields,
    )
    if pinned != value:
        raise RoundingStageError("rounding_stage_result")
    return pinned


def require_call_trace(raw, settings, precision, expected_precision, lookups):
    """Shared exact trace comparison for saved and explicitly derived stages."""
    if (
        type(settings) is not tuple or len(settings) != lookups
        or settings != (("rounding_method", raw),) * lookups
        or any(
            type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str
            or type(entry[1]) is not type(raw) for entry in settings
        )
        or type(precision) is not tuple or len(precision) != len(expected_precision)
    ):
        raise RoundingStageError("rounding_stage_trace")
    for actual, expected in zip(precision, expected_precision):
        if (
            type(actual) is not tuple or len(actual) != len(expected)
            or any(type(a) is not type(e) or a != e for a, e in zip(actual, expected))
        ):
            raise RoundingStageError("rounding_stage_trace")


def project_stage(stage, fieldnames):
    """Select an ordered same-owner substage; acquire no new cache or SQL.

    A composite acquisition can capture a field union once and give existing
    strict calculators their original stage shapes. Reordering is not allowed.
    """
    try:
        stage = pin_stage(stage)
        names = _names(fieldnames)
        selected = tuple(target for target in stage.targets if target[2] in names)
        if stage.do_not_round_fields is not None or tuple(target[2] for target in selected) != names:
            raise ValueError
        fields = tuple(value for value in stage.fields if value.target in selected)
        result = SavedRoundingStageRead(stage.numeric, stage.method, selected, None, stage.owner_document, fields)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise RoundingStageError("rounding_stage_projection")
    return result


@dataclass(frozen=True, repr=False)
class SavedRoundingStageRead:
    """Same-parent ordered source comparison; NOT actual execution authority.

    Trace/snapshot inputs are explicit observations supplied by a trusted caller.
    Their origin and the active controller object's identity remain external.
    """
    numeric: SavedFinancialNumericRead = field(repr=False)
    method: SavedRoundingContext = field(repr=False)
    targets: tuple = field(repr=False)
    do_not_round_fields: tuple | None = field(repr=False)
    owner_document: int = field(repr=False)
    fields: tuple = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.numeric) is not SavedFinancialNumericRead or type(self.method) is not SavedRoundingContext:
                raise ValueError
            numeric, method, fields = _pin_stage_fields(self.numeric, self.method, self.fields)
            if (numeric != self.numeric or method != self.method or method.context != numeric.financial.context
                    or method.erp_major != numeric.view.financial.financial.erp_major or method.override is not None
                    or type(self.owner_document) is not int or not 0 < self.owner_document < 2**64
                    or type(self.targets) is not tuple or not self.targets or type(self.fields) is not tuple):
                raise ValueError
            names = _names(tuple(target[2] for target in self.targets))
            skips = _skips(self.do_not_round_fields,method.erp_major)
            cells = {cell[:3]:cell for cell in _native_cells(numeric.view.financial)}
            group = self.targets[0][:2]
            if any(type(target) is not tuple or len(target) != 3 or target[:2] != group
                    or target not in cells or cells[target][3] not in ("Currency","Float","Percent") for target in self.targets):
                raise ValueError
            expected = tuple(target for target in self.targets if target[2] not in skips)
            if tuple(value.target for value in fields) != expected or any(value.numeric != numeric
                    or value.method != method or value.owner_document != self.owner_document for value in fields):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundingStageError("rounding_stage_result")
        object.__setattr__(self,"numeric",numeric)
        object.__setattr__(self,"method",method)
        object.__setattr__(self,"fields",fields)

    def require_stage_match(self, before, after, *, setting_trace, precision_trace, input_stage="SAVED"):
        """Compare a COMPLETE ordered explicit stage, including skipped getters.

        No document/controller is read, run or changed here. NULL/blank settings
        cause flt/rounded to repeat the lookup for each processed non-NULL value.
        """
        try:
            pinned = SavedRoundingStageRead(self.numeric,self.method,self.targets,self.do_not_round_fields,self.owner_document,self.fields)
            if pinned != self or type(input_stage) is not str or input_stage not in ("SAVED","NUMERIC_FIXED"):
                raise ValueError
            if type(before) is not tuple or type(after) is not tuple or len(before) != len(self.targets) or len(after) != len(self.targets):
                raise ValueError
            cells = {cell[:3]:cell for cell in _native_cells(pinned.numeric.view.financial)}
            results = {value.target:value for value in pinned.fields}
            raw = pinned.method.rounding.value
            lookups = 1
            expected_precision = []
            for target,original,changed in zip(pinned.targets,before,after):
                if (type(original) is not tuple or len(original) != 2 or type(changed) is not tuple or len(changed) != 2
                        or type(original[0]) is not str or type(changed[0]) is not str
                        or original[0] != target[2] or changed[0] != target[2]):
                    raise ValueError
                cell = cells[target]
                tag = _expected(cell[4],input_stage,cell[3])
                if _getter(original[1],input_stage,cell[3]) != tag:
                    raise ValueError
                if target in results:
                    result = results[target]
                    result.require_result_match(changed[1])
                    expected_precision.append((target[2],None if target[0] == "header" else target[0],result.precision.precision))
                    if not raw and original[1] is not None:
                        lookups += 1
                elif _getter(changed[1],input_stage,cell[3]) != tag:
                    raise ValueError
            require_call_trace(raw,setting_trace,precision_trace,expected_precision,lookups)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundingStageError("rounding_stage_observation")

    def __repr__(self):
        return "<SavedRoundingStageRead protected PARTIAL ordered comparison, NOT execution proof>"

    def __reduce__(self):
        raise TypeError("rounding_stage_not_serializable")
