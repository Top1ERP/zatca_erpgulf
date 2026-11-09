"""One owned numeric/default/method read with a selected owner precision cache.

Reuse existing acquisition lifecycles; do not combine independent captures or
call precision(), controllers, writes or HTTP. Acquire owner-field formats only
on the v16 fallback branch, after the same handle has captured native defaults.
"""

from dataclasses import dataclass, field, fields as dataclass_fields, is_dataclass
import json
import math

from .calculation_numeric_access import NumericAcquisition, SavedFinancialNumericRead
from .calculation_child_cache import _precision, _MISSING, _state, _bucket, _slot
from .calculation_rounding_access import RoundingAcquisition, SavedRoundingContext
from .calculation_precision import FieldPrecisionResolution, _requires_currency_format, PARENT_CURRENCY_SCOPES
from .calculation_defaults import _fold
from .calculation_format_access import FormatAcquisition, SavedFieldCurrencyRead
from .calculation_owner_currency_access import OwnerCurrencyAcquisition
from .child_field_currency import ABSENT
from .financial_numeric_view import FIXED_TYPES, _native_cells
from .financial_source_observation import TABLE_FIELDS, _child_type, _name, _scalar, _validate_scalar
from .field_rounding import round_field_value

MAX_STAGE_FIELDS = 64


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

    def __init__(self, policy, actor, invoice_name, doctype, target, metadata_reader, cache_reader, *,
            format_metadata=None, format_cache=None, owner_metadata=None, company_cache=None, _shared=None):
        if _shared is None:
            self.root = NumericAcquisition(policy, actor, invoice_name, doctype)
            self.method = None
        else:
            self.root, self.method = _shared
            if (type(self.root) is not NumericAcquisition or type(self.method) is not RoundingAcquisition
                    or self.root._policy is not policy or self.method._policy is not policy
                    or (self.root._name,self.root._doctype) != (invoice_name,doctype)):
                raise FieldRoundingAccessError("field_rounding_shared_source")
        self._actor = actor
        self.tables = self.root.tables
        self.target = _target(target, self.root.schema, doctype, invoice_name, self.tables)
        self.parentfield = target[0]
        self.owner_document = id(self.root.document)
        self.cache = self._cache()
        if self.method is None:
            self.method = RoundingAcquisition(policy,actor,metadata_reader,cache_reader,None)
        self.formats = None
        self.currency_cache = None
        self._format_metadata, self._format_cache = format_metadata, format_cache
        self._owner_metadata, self._company_cache_reader = owner_metadata, company_cache
        self.owner_currency = None
        self.company_cache = None
        if _shared is None:
            self.recheck_access()

    def _cache(self):
        return _precision(self.root.document, self.target[2], parentfield=self.parentfield)

    def recheck_access(self):
        self.root.recheck_access()
        self.method.recheck_access()
        self.recheck_local()
        if self.formats is not None:
            self.formats.recheck_access()
        if self.owner_currency is not None:
            self.owner_currency.recheck_access()

    def recheck_local(self):
        """Only this field's original owner/cache slots; shared sources outside."""
        if id(self.root.document) != self.owner_document or self._cache() != self.cache:
            raise FieldRoundingAccessError("field_rounding_owner_cache_changed")
        if self.currency_cache is not None and self._currency_cache() != self.currency_cache:
            raise FieldRoundingAccessError("field_rounding_currency_cache_changed")

    def _currency_cache(self):
        doc = self.root.document
        # The owner is a root invoice, never a child-shaped document with an
        # unproved parent/parenttype fallback or an in-memory parent_doc.
        if doc.get("parent") or doc.get("parenttype"):
            raise FieldRoundingAccessError("field_rounding_currency_owner")
        runtime = self.root._policy._dependencies()[0]
        mapping = getattr(runtime.local, "field_currency", _MISSING)
        state = _state(mapping, nullable=True)
        bucket = _MISSING if mapping is _MISSING or mapping is None else _bucket(mapping, (doc.doctype, doc.name))
        return (state, _state(bucket)), _slot(bucket, self.target[2])

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
        return view, method, None

    def format_scope(self, view, defaults):
        """Select one fresh precision dependency without acquiring its source."""
        native = view.financial
        doctype = native.financial.doctype if self.parentfield is None else _child_type(native.financial.doctype,self.parentfield)
        meta = next(row.applied for row in native.metadata if row.applied.name == doctype)
        definition = meta.get_field(self.target[2])
        if not _requires_currency_format(definition,_fold(json.loads(defaults._payload)["rows"]),native.financial.erp_major):
            return None
        scope = PARENT_CURRENCY_SCOPES.get(definition.options)
        if scope is None:
            raise FieldRoundingAccessError("field_rounding_currency_options")
        return scope

    def complete_defaults(self, connection, observed, defaults, company_metadata, *, _pool=None):
        """Select lazy formats only after native site defaults on THIS handle."""
        view, method, unused = observed
        if unused is not None or self.formats is not None:
            raise FieldRoundingAccessError("field_rounding_format_stage")
        native = view.financial
        scope = self.format_scope(view,defaults)
        if scope is None:
            return observed
        if self.currency_cache is None:
            self.currency_cache = self._currency_cache()
        elif self.currency_cache != self._currency_cache():
            raise FieldRoundingAccessError("field_rounding_currency_cache_changed")
        if _pool is not None and scope in _pool:
            self.formats,self.owner_currency,formats = _pool[scope]
            self._check_company_cache(initial=True)
            self.recheck_access()
            return view,method,formats
        policy = self.root._policy
        if scope == "owner":
            self.owner_currency = OwnerCurrencyAcquisition(self.root, self._actor, self._owner_metadata)
            self.owner_currency.prepare_metadata()
            self.owner_currency.load_for_update(connection, native)
        self.formats = FormatAcquisition(policy, self._actor, self.root._name, self.root._doctype,
            self._format_metadata, self._format_cache, currency_scope=scope, require_fields=True,
            owner_source=self.owner_currency)
        self.formats.require_financial_currency(native.financial)
        if scope == "company":
            self.formats.load_company_currency(connection, company_metadata)
            self._check_company_cache(initial=True)
        formats = self.formats.load_for_update(connection)
        self.formats.check_cache(formats)
        self.recheck_access()
        if _pool is not None:
            _pool[scope] = self.formats,self.owner_currency,formats
        return view, method, formats

    def _check_company_cache(self, *, initial=False):
        """Observe the selected Company API projection, never refresh it here.

        A valid local owner currency slot avoids the Company API entirely.
        Blocked/invalid slots are rejected by result reconstruction, not fixed.
        Trusted callbacks finish before final native SQL checks.
        """
        if self.formats is None or self.formats.company_source is None or _cache_slot(self.currency_cache, allow_null=True) != ABSENT:
            if self.company_cache is not None:
                raise FieldRoundingAccessError("field_rounding_company_cache_binding")
            return
        source = self.formats.company_source
        if not callable(self._company_cache_reader):
            raise FieldRoundingAccessError("field_rounding_company_cache_dependency")
        value = self._company_cache_reader(self.root._policy._scope, source.name)
        if type(value) is not str or value != source.currency:
            raise FieldRoundingAccessError("field_rounding_company_cache_mismatch")
        tag = ("str", value)
        if initial:
            self.company_cache = tag
        elif tag != self.company_cache:
            raise FieldRoundingAccessError("field_rounding_company_cache_changed")

    def check_getters(self, observed):
        view, method, formats = observed
        self.root.check_getters(view)
        self.method.check_cache(method)
        if (self.formats is None) != (formats is None):
            raise FieldRoundingAccessError("field_rounding_format_binding")
        if self.formats is not None:
            self.formats.check_cache(formats)
        self._check_company_cache()
        self.recheck_access()

    def require_metadata_unchanged(self):
        self.root.require_metadata_unchanged()
        self.method.require_metadata_unchanged()
        if self.formats is not None:
            self.formats.require_metadata_unchanged()
        if self.owner_currency is not None:
            self.owner_currency.require_metadata_unchanged()
        self.recheck_access()

    def require_unchanged(self, observed):
        # All trusted cache/metadata callbacks precede the parent's final SQL
        # checks. Reuse each source's final reader without another provider.
        view, method, formats = observed
        self.root.require_unchanged(view)
        self.method.require_unchanged(method)
        if self.owner_currency is not None:
            self.owner_currency.require_unchanged()
        if self.formats is not None:
            if self.formats.company_source is not None:
                self.formats.company_reader.require_unchanged(self.formats.company_source)
            self.formats.reader.require_unchanged(formats)
        self.recheck_access()

    def build_result(self, financial, observed):
        view, method, formats = observed
        numeric = SavedFinancialNumericRead(financial, view, self.tables)
        context = SavedRoundingContext(financial.context, view.financial.financial.erp_major,
            None, method, self.method.rows)
        currency = None if self.formats is None else SavedFieldCurrencyRead(financial,
            self.formats.rows, formats, self.formats.company_source,
            None if self.owner_currency is None else self.owner_currency.native)
        return SavedFieldRoundingRead(numeric, context, self.target, self.owner_document, self.cache,
            currency, self.currency_cache, self.company_cache)


def _cache_slot(cache, *, allow_null=False):
    if type(cache) is not tuple or len(cache) != 2:
        raise ValueError
    states, slot = cache
    if type(states) is not tuple or len(states) != 2 or type(slot) is not tuple:
        raise ValueError
    for index, state in enumerate(states):
        if allow_null and index == 0 and state == ("null",):
            continue
        if state != ABSENT and (type(state) is not tuple or len(state) != 2 or state[0] != "dict"
                or type(state[1]) is not int or not 0 < state[1] < 2**64):
            raise ValueError
    if states[0] in (ABSENT, ("null",)) and states[1] != ABSENT or states[1] == ABSENT and slot != ABSENT:
        raise ValueError
    return slot


def _require_cache(cache, resolution):
    slot = _cache_slot(cache)
    if slot != ABSENT:
        resolution.require_cached_match(_validate_scalar(list(slot)))


def _result_tag(value):
    if type(value) is int and abs(value) < 10**65:
        return "int", str(value)
    if type(value) is float and math.isfinite(value):
        return "float", value.hex()
    raise ValueError


def _resolve_field(numeric, method, target, owner_document, cache, formats, currency_cache, company_cache):
    """Resolve one field on independently reconstructed shared source values.

    This pure kernel returns data, never a source/permission grant. Both the
    ordinary constructor and the bounded stage reconstruction call it after
    rebuilding their shared numeric and rounding inputs.
    """
    native = numeric.view.financial
    if (method.override is not None
            or method.rounding is None or method.context != numeric.financial.context
            or method.erp_major != native.financial.erp_major
            or type(owner_document) is not int or not 0 < owner_document < 2**64):
        raise ValueError
    if type(target) is not tuple or len(target) != 3:
        raise ValueError
    group, row_name, name = target
    doctype = native.financial.doctype if group == "header" else _child_type(native.financial.doctype, group)
    meta = next(row.applied for row in native.metadata if row.applied.name == doctype)
    schema = ((doctype, ((name, meta.get_field(name)),)),)
    supplied = (None, None, name) if group == "header" else target
    if _target(supplied, schema, native.financial.doctype, native.financial.name, numeric.tables) != target:
        raise ValueError
    cell = next(cell for cell in _native_cells(native) if cell[:3] == target)
    needs_formats = _requires_currency_format(meta.get_field(name),
        _fold(json.loads(numeric.financial.context.settings.defaults._payload)["rows"]), method.erp_major)
    supplied_formats, formats = formats, None
    if needs_formats:
        if type(supplied_formats) is not SavedFieldCurrencyRead:
            raise ValueError
        formats = SavedFieldCurrencyRead(supplied_formats.financial, supplied_formats.related,
            supplied_formats.formats, supplied_formats.company_currency, supplied_formats.owner_currency)
        if formats != supplied_formats or formats.financial != numeric.financial:
            raise ValueError
        parentfield = None if group == "header" else group
        precision = formats.resolve_precision(name, parentfield=parentfield)
        cached = _cache_slot(currency_cache, allow_null=True)
        if cached != ABSENT:
            formats.require_field_currency_match(name, _validate_scalar(list(cached)), parentfield=parentfield)
        if formats.company_currency is not None and cached == ABSENT:
            if type(company_cache) is not tuple or company_cache != ("str",formats.company_currency.currency):
                raise ValueError
        elif company_cache is not None:
            raise ValueError
    else:
        if supplied_formats is not None or currency_cache is not None or company_cache is not None:
            raise ValueError
        precision = numeric.financial.resolve_precision(doctype, name)
    _require_cache(cache, precision)
    result = round_field_value(_validate_scalar(cell[4]), precision=precision.precision,
        method=method.method, erp_major=method.erp_major)
    return formats, precision, result


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
    formats: SavedFieldCurrencyRead | None = field(default=None, repr=False)
    currency_cache: tuple | None = field(default=None, repr=False)
    company_cache: tuple | None = field(default=None, repr=False)
    precision: FieldPrecisionResolution = field(init=False, repr=False)
    rounded_value: int | float = field(init=False, repr=False)

    def __post_init__(self):
        try:
            if type(self.numeric) is not SavedFinancialNumericRead or type(self.method) is not SavedRoundingContext:
                raise ValueError
            numeric = SavedFinancialNumericRead(self.numeric.financial, self.numeric.view, self.numeric.tables)
            method = SavedRoundingContext(self.method.context, self.method.erp_major, self.method.override,
                self.method.rounding, self.method.related)
            if numeric != self.numeric or method != self.method:
                raise ValueError
            formats, precision, result = _resolve_field(numeric, method, self.target, self.owner_document,
                self.cache, self.formats, self.currency_cache, self.company_cache)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FieldRoundingAccessError("field_rounding_saved_result")
        object.__setattr__(self, "numeric", numeric)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "formats", formats)
        object.__setattr__(self, "precision", precision)
        object.__setattr__(self, "rounded_value", result)

    def require_result_match(self, value):
        """Compare an explicitly supplied stage result, never read/mutate it."""
        try:
            pinned = SavedFieldRoundingRead(self.numeric, self.method, self.target, self.owner_document, self.cache,
                self.formats, self.currency_cache, self.company_cache)
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


def _same_checked_value(actual, expected):
    """Match a supplied graph to a freshly reconstructed private value.

    Do not call arbitrary equality methods or retain supplied derived caches.
    Dataclass constructor inputs, comparable derived fields, immutable tuples
    and exact scalars enter this comparison. Only non-comparable DERIVED caches
    are excluded; constructors rebuild them rather than copying supplied state.
    """
    if type(actual) is not type(expected):
        raise ValueError
    if actual is expected:
        return
    if is_dataclass(expected):
        for definition in dataclass_fields(expected):
            if definition.init or definition.compare:
                _same_checked_value(getattr(actual, definition.name), getattr(expected, definition.name))
    elif type(expected) is tuple:
        if len(actual) != len(expected):
            raise ValueError
        for left, right in zip(actual, expected):
            _same_checked_value(left, right)
    elif type(expected) in (type(None), bool, int, str, bytes):
        if actual != expected:
            raise ValueError
    elif type(expected) is float:
        if actual.hex() != expected.hex():
            raise ValueError
    elif _scalar(actual) != _scalar(expected):
        raise ValueError


def _pin_stage_fields(supplied_numeric, supplied_method, values):
    """Reconstruct shared sources once, then independently resolve each field.

    This boundary ALWAYS reconstructs the numeric graph and method. Each field
    must match those canonical sources, then pass the ordinary field kernel and
    an exact comparison of its supplied result. Only checked values enter fresh
    result objects. There is no cache, caller-selected bypass or trusted flag,
    and the normal single-field constructor remains independently validating.
    """
    try:
        if (type(supplied_numeric) is not SavedFinancialNumericRead
                or type(supplied_method) is not SavedRoundingContext
                or type(values) is not tuple or len(values) > MAX_STAGE_FIELDS):
            raise ValueError
        numeric = SavedFinancialNumericRead(supplied_numeric.financial, supplied_numeric.view, supplied_numeric.tables)
        method = SavedRoundingContext(supplied_method.context, supplied_method.erp_major,
            supplied_method.override, supplied_method.rounding, supplied_method.related)
        _same_checked_value(supplied_numeric, numeric)
        _same_checked_value(supplied_method, method)
        results = []
        for value in values:
            if type(value) is not SavedFieldRoundingRead:
                raise ValueError
            _same_checked_value(value.numeric, numeric)
            _same_checked_value(value.method, method)
            formats, precision, result = _resolve_field(numeric, method, value.target, value.owner_document,
                value.cache, value.formats, value.currency_cache, value.company_cache)
            # The shared sources and EVERY field input/output have now been
            # checked. Construct a fresh immutable result without recursively
            # rebuilding the same source graph for each sibling field.
            pinned = object.__new__(SavedFieldRoundingRead)
            for name, checked in (("numeric", numeric), ("method", method), ("target", value.target),
                    ("owner_document", value.owner_document), ("cache", value.cache), ("formats", formats),
                    ("currency_cache", value.currency_cache), ("company_cache", value.company_cache),
                    ("precision", precision), ("rounded_value", result)):
                object.__setattr__(pinned, name, checked)
            if set(vars(pinned)) != {definition.name for definition in dataclass_fields(SavedFieldRoundingRead)}:
                raise ValueError  # New dataclass fields must be initialized here too.
            _same_checked_value(value, pinned)
            results.append(pinned)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise FieldRoundingAccessError("field_rounding_stage_fields")
    return numeric, method, tuple(results)
