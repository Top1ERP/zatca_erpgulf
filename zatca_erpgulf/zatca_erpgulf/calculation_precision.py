"""Explicit Frappe 15/16 field precision, separate from fiscal XML rounding.

Pure, bounded resolution from pinned metadata and site-scoped defaults. The
v16 currency-format branch additionally requires explicit locale/currency
declarations. No framework cache lookup, currency discovery, rounding or I/O.
"""

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from .calculation_defaults import CalculationDefaultsRows, _fold, _pin_rows
from .financial_source_observation import _canonical, _name, _scalar
from .source_metadata import SOURCE_FIELDS, SourceMetadata, _pin_metadata

NUMERIC_TYPES = frozenset(("Currency", "Float", "Percent"))
MAX_PRECISION = 64
# Shared supported spelling, independently checked against both pinned sources.
FORMAT_PRECISIONS = MappingProxyType({
    "#,###.##": 2, "#.###,##": 2, "# ###.##": 2, "# ###,##": 2,
    "#'###.##": 2, "#, ###.##": 2, "#,##,###.##": 2,
    "#,###.###": 3, "#.###": 0, "#,###": 0, "#.########": 8,
})


class FieldPrecisionError(ValueError):
    """Static English code; no raw metadata, language or settings disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _optional_text(value):
    if value is not None and (type(value) is not str or len(value.encode("utf-8")) > 4096 or "\0" in value):
        raise ValueError


def _cint(value):
    """Bounded primitive counterpart of the inspected framework int fallback.

    This converts precision SETTINGS only, never a financial amount. Matching
    framework behavior can produce zero for malformed text; it is not a fiscal
    approval. Negative/oversized resolved precision is rejected by the caller.
    """
    _scalar(value)
    if type(value) not in (str, int, bool, float, type(None)):
        raise ValueError
    if type(value) is str and len(value.encode("utf-8")) > 4096:
        raise ValueError
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return 0


def _default(values, key):
    """Exact db.get_default site-scope list rule; never use user/global overlay."""
    value = values.get(key)
    if type(value) is list:
        if value and value[0]:
            return value[0]
        # The real API leaves this ambiguous list intact. Do not turn it into a
        # guessed scalar, default precision or number-format fallback here.
        raise ValueError
    return value


@dataclass(frozen=True, repr=False)
class CurrencyFormatContext:
    """Explicit v16 lookup declarations, NOT saved/committed provenance.

    language is the actual effective language, with its supplied number-format
    value (None/blank retained). currency is an already resolved field currency;
    options/parent/Company links are not interpreted by this pure component.
    The system setting is a normalized Check, not a truthy string.
    """

    language: str = field(repr=False)
    language_number_format: str | None = field(repr=False)
    use_currency_format: bool = field(repr=False)
    currency: str | None = field(repr=False)
    currency_number_format: str | None = field(repr=False)

    def __post_init__(self):
        try:
            _name(self.language)
            _optional_text(self.language_number_format)
            _optional_text(self.currency_number_format)
            if type(self.use_currency_format) is not bool:
                raise ValueError
            if self.currency is not None:
                _name(self.currency)
            if self.use_currency_format and self.currency is None:
                raise ValueError
            if self.currency is None and self.currency_number_format is not None:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FieldPrecisionError("calculation_currency_format_context")

    def __repr__(self):
        return "<CurrencyFormatContext protected supplied lookup declarations>"

    def __reduce__(self):
        raise TypeError("calculation_precision_not_serializable")


def _pin_currency(context):
    if context is None:
        return None
    if type(context) is not CurrencyFormatContext:
        raise ValueError
    return CurrencyFormatContext(context.language, context.language_number_format,
        context.use_currency_format, context.currency, context.currency_number_format)


def _resolve(definition, defaults, major, context):
    if definition is None:
        return None, "ABSENT_FIELD"
    if definition.fieldtype not in NUMERIC_TYPES:
        return None, "NON_NUMERIC_FIELD"
    explicit = definition.get("precision")
    if explicit:
        return _cint(explicit), "FIELD_PRECISION"
    if definition.fieldtype != "Currency":
        precision = _cint(_default(defaults, "float_precision"))
        return (precision, "FLOAT_DEFAULT") if precision else (3, "FLOAT_FALLBACK")
    raw = _default(defaults, "currency_precision")
    precision = _cint(raw)
    if major == 15:
        if precision:
            return precision, "CURRENCY_DEFAULT"
        number_format = _default(defaults, "number_format") or "#,###.##"
        return FORMAT_PRECISIONS.get(number_format, 2), "SITE_NUMBER_FORMAT"
    # Version 16 preserves configured zero and malformed-but-present text's cint
    # result. Only None/blank falls through to the locale/currency format branch.
    if raw not in (None, ""):
        return precision, "CURRENCY_DEFAULT"
    if context is None:
        raise ValueError
    number_format = context.language_number_format or _default(defaults, "number_format") or "#,###.##"
    # v16 constructs the locale format FIRST, even when currency overrides it.
    precision = FORMAT_PRECISIONS[number_format]
    if context.use_currency_format and context.currency_number_format:
        return FORMAT_PRECISIONS[context.currency_number_format], "CURRENCY_NUMBER_FORMAT"
    return precision, "LOCALE_NUMBER_FORMAT"


@dataclass(frozen=True, repr=False)
class FieldPrecisionResolution:
    """Fresh precision from exact declarations, NOT a document cache or XML rule.

    Existing snapshots and raw values are not rewritten. A stale framework
    document precision cache must be checked separately before runtime adoption.
    """

    metadata: SourceMetadata = field(repr=False)
    fieldname: str = field(repr=False)
    defaults: CalculationDefaultsRows = field(repr=False)
    erp_major: int
    currency_context: CurrencyFormatContext | None = field(default=None, repr=False)
    precision: int | None = field(init=False)
    origin: str = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            metadata, defaults = _pin_metadata(self.metadata), _pin_rows(self.defaults)
            if (type(self.erp_major) is not int or self.erp_major not in (15, 16)
                    or defaults.parent != "__default" or type(self.fieldname) is not str
                    or self.fieldname not in SOURCE_FIELDS[metadata.name]):
                raise ValueError
            context = _pin_currency(self.currency_context)
            if self.erp_major == 15 and context is not None:
                raise ValueError
            precision, origin = _resolve(metadata.get_field(self.fieldname),
                _fold(json.loads(defaults._payload)["rows"]), self.erp_major, context)
            if precision is not None and (type(precision) is not int or not 0 <= precision <= MAX_PRECISION):
                raise ValueError
            context_values = None if context is None else [
                _scalar(context.language), _scalar(context.language_number_format),
                _scalar(context.use_currency_format), _scalar(context.currency), _scalar(context.currency_number_format)]
            payload = _canonical(dict(profile="calculation-field-precision/v1", erp_major=self.erp_major,
                metadata_sha256=metadata.sha256, defaults_sha256=defaults.sha256,
                fieldname=self.fieldname, currency_context=context_values, precision=precision, origin=origin))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FieldPrecisionError("calculation_field_precision")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "defaults", defaults)
        object.__setattr__(self, "currency_context", context)
        object.__setattr__(self, "precision", precision)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-calculation-field-precision/v1\0" + payload).hexdigest())

    def __repr__(self):
        return "<FieldPrecisionResolution protected fresh declarations, NOT fiscal rounding>"

    def __reduce__(self):
        raise TypeError("calculation_precision_not_serializable")

    def require_cached_match(self, cached):
        """Compare one explicit existing doc.precision result; never fill its cache."""
        try:
            pinned = FieldPrecisionResolution(self.metadata, self.fieldname, self.defaults,
                self.erp_major, self.currency_context)
            if pinned != self or type(cached) is not type(pinned.precision) or cached != pinned.precision:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FieldPrecisionError("calculation_precision_cache_mismatch")
