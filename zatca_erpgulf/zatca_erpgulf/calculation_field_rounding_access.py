"""One owned numeric/default/method read with a selected owner precision cache.

Reuse existing acquisition lifecycles; do not combine independent captures or
call precision(), controllers, writes or HTTP. Currency-format fallback remains
unsupported here until its owner-field provenance is acquired on this pipeline.
"""

from dataclasses import dataclass, field
import math

from .calculation_numeric_access import NumericAcquisition, SavedFinancialNumericRead
from .calculation_child_cache import _precision
from .calculation_rounding_access import RoundingAcquisition, SavedRoundingContext
from .calculation_precision import FieldPrecisionResolution
from .child_field_currency import ABSENT
from .financial_numeric_view import FIXED_TYPES, _native_cells
from .financial_source_observation import TABLE_FIELDS, _child_type, _name, _validate_scalar
from .field_rounding import round_field_value


class FieldRoundingAccessError(ValueError):
    """Static English codes; never disclose a value, setting or cache slot."""


def _target(target, schema, root_type, root_name, tables):
    if type(target) is not tuple or len(target) != 3:
        raise ValueError
    parentfield, row_name, fieldname = target
    _name(fieldname)
    if parentfield is None:
        if row_name is not None:
            raise ValueError
        group, row_name, doctype = "header", root_name, root_type
    else:
        if type(parentfield) is not str or parentfield not in TABLE_FIELDS:
            raise ValueError
        _name(row_name)
        rows = dict(tables)[parentfield]
        if not any(row.name == row_name for row in rows):
            raise ValueError
        group, doctype = parentfield, _child_type(root_type, parentfield)
    definition = dict(dict(schema)[doctype])[fieldname]
    if definition.fieldtype not in FIXED_TYPES:
        raise ValueError
    return group, row_name, fieldname


class FieldRoundingAcquisition:
    """Compose one shared graph and existing System-setting acquisition."""

    def __init__(self, policy, actor, invoice_name, doctype, target, metadata_reader, cache_reader):
        self.root = NumericAcquisition(policy, actor, invoice_name, doctype)
        self.tables = self.root.tables
        self.target = _target(target, self.root.schema, doctype, invoice_name, self.tables)
        self.parentfield = target[0]
        self.owner_document = id(self.root.document)
        self.cache = self._cache()
        self.method = RoundingAcquisition(policy, actor, metadata_reader, cache_reader, None)
        self.recheck_access()

    def _cache(self):
        return _precision(self.root.document, self.target[2], parentfield=self.parentfield)

    def recheck_access(self):
        self.root.recheck_access()
        if id(self.root.document) != self.owner_document or self._cache() != self.cache:
            raise FieldRoundingAccessError("field_rounding_owner_cache_changed")
        self.method.recheck_access()

    def prepare_metadata(self):
        self.root.prepare_metadata()
        self.method.prepare_metadata()
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        self.root.require_financial_metadata(metadata)

    def load_for_update(self, connection, financial):
        view = self.root.load_for_update(connection, financial)
        method = self.method.load_for_update(connection)
        self.method.check_cache(method)
        self.recheck_access()
        return view, method

    def check_getters(self, observed):
        view, method = observed
        self.root.check_getters(view)
        self.method.check_cache(method)
        self.recheck_access()

    def require_metadata_unchanged(self):
        self.root.require_metadata_unchanged()
        self.method.require_metadata_unchanged()
        self.recheck_access()

    def require_unchanged(self, observed):
        # All trusted cache/metadata callbacks precede the parent's final SQL
        # checks. Reuse each source's final reader without another provider.
        view, method = observed
        self.root.require_unchanged(view)
        self.method.require_unchanged(method)
        self.recheck_access()

    def build_result(self, financial, observed):
        view, method = observed
        numeric = SavedFinancialNumericRead(financial, view, self.tables)
        context = SavedRoundingContext(financial.context, view.financial.financial.erp_major,
            None, method, self.method.rows)
        return SavedFieldRoundingRead(numeric, context, self.target, self.owner_document, self.cache)


def _require_cache(cache, resolution):
    if type(cache) is not tuple or len(cache) != 2:
        raise ValueError
    states, slot = cache
    if type(states) is not tuple or len(states) != 2 or type(slot) is not tuple:
        raise ValueError
    for state in states:
        if state != ABSENT and (type(state) is not tuple or len(state) != 2 or state[0] != "dict"
                or type(state[1]) is not int or not 0 < state[1] < 2**64):
            raise ValueError
    if states[0] == ABSENT and states[1] != ABSENT or states[1] == ABSENT and slot != ABSENT:
        raise ValueError
    if slot != ABSENT:
        resolution.require_cached_match(_validate_scalar(list(slot)))


def _result_tag(value):
    if type(value) is int and abs(value) < 10**65:
        return "int", str(value)
    if type(value) is float and math.isfinite(value):
        return "float", value.hex()
    raise ValueError


@dataclass(frozen=True, repr=False)
class SavedFieldRoundingRead:
    """Protected selected saved-value calculation, not controller/issuance proof.

    Fresh precision and existing owner-cache agreement are distinct. Missing
    cache means no entry was observed, not that a later precision call is proven.
    No supplied format declarations or caller-provided precision bypass sources.
    """

    numeric: SavedFinancialNumericRead = field(repr=False)
    method: SavedRoundingContext = field(repr=False)
    target: tuple = field(repr=False)
    owner_document: int = field(repr=False)
    cache: tuple = field(repr=False)
    precision: FieldPrecisionResolution = field(init=False, repr=False)
    rounded_value: int | float = field(init=False, repr=False)

    def __post_init__(self):
        try:
            if type(self.numeric) is not SavedFinancialNumericRead or type(self.method) is not SavedRoundingContext:
                raise ValueError
            numeric = SavedFinancialNumericRead(self.numeric.financial, self.numeric.view, self.numeric.tables)
            method = SavedRoundingContext(self.method.context, self.method.erp_major, self.method.override,
                self.method.rounding, self.method.related)
            native = numeric.view.financial
            if (numeric != self.numeric or method != self.method or method.override is not None
                    or method.rounding is None or method.context != numeric.financial.context
                    or method.erp_major != native.financial.erp_major
                    or type(self.owner_document) is not int or not 0 < self.owner_document < 2**64):
                raise ValueError
            if type(self.target) is not tuple or len(self.target) != 3:
                raise ValueError
            group, row_name, name = self.target
            doctype = native.financial.doctype if group == "header" else _child_type(native.financial.doctype, group)
            meta = next(row.applied for row in native.metadata if row.applied.name == doctype)
            schema = ((doctype, ((name, meta.get_field(name)),)),)
            supplied = (None, None, name) if group == "header" else self.target
            if _target(supplied, schema, native.financial.doctype, native.financial.name, numeric.tables) != self.target:
                raise ValueError
            cell = next(cell for cell in _native_cells(native) if cell[:3] == self.target)
            # v16 format-dependent precision deliberately fails closed here;
            # do not substitute the invoice currency for a child owner's field.
            precision = numeric.financial.resolve_precision(doctype, name)
            _require_cache(self.cache, precision)
            result = round_field_value(_validate_scalar(cell[4]), precision=precision.precision,
                method=method.method, erp_major=method.erp_major)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FieldRoundingAccessError("field_rounding_saved_result")
        object.__setattr__(self, "numeric", numeric)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "precision", precision)
        object.__setattr__(self, "rounded_value", result)

    def require_result_match(self, value):
        """Compare an explicitly supplied stage result, never read/mutate it."""
        try:
            pinned = SavedFieldRoundingRead(self.numeric, self.method, self.target, self.owner_document, self.cache)
            if (pinned != self or _result_tag(self.rounded_value) != _result_tag(pinned.rounded_value)
                    or _result_tag(value) != _result_tag(pinned.rounded_value)):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FieldRoundingAccessError("field_rounding_result_mismatch")

    def __repr__(self):
        return "<SavedFieldRoundingRead protected PARTIAL source/cache calculation, NOT controller proof>"

    def __reduce__(self):
        raise TypeError("field_rounding_saved_not_serializable")
