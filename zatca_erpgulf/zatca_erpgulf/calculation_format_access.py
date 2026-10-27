"""Related format READ/locale checks for the existing owned calculation service.

No second transaction/ACL/presentation pipeline. The parent service owns SQL
and cleanup; this component composes the shared saved-record policy, selected
format reader and protected result. No public endpoint or runtime provider.
"""

from dataclasses import dataclass, field
import json
from types import MappingProxyType, SimpleNamespace

from .archive_source_access import ArchiveInspectionEngine, ArchiveSourceAccessError, SavedSourceRow, _name, _revision
from .calculation_precision import CurrencyFormatContext
from .currency_format_source import (
    FLAG, LockedCurrencyFormatRead, MariaDBCurrencyFormatReader, _metas,
    _pin_read as _pin_format_read,
)
from .financial_source_observation import _validate_scalar

FIELDS = MappingProxyType({"Currency": ("number_format",), "Language": ("number_format",), "System Settings": (FLAG,)})


class CalculationFormatAccessError(ArchiveSourceAccessError):
    """Static English internal code, without source/actor/cache disclosure."""


class FormatSourceRow(SavedSourceRow):
    """Exact related READ projection; Singleton has NO fabricated revision."""

    @classmethod
    def from_document(cls, doc):
        if type(doc.doctype) is not str or doc.doctype not in FIELDS:
            raise CalculationFormatAccessError("calculation_format_source_type")
        fieldname = FIELDS[doc.doctype][0]
        value = doc.get(fieldname)
        if doc.doctype == "System Settings":
            if doc.name != "System Settings" or type(value) not in (int, bool) or value not in (0, 1):
                raise CalculationFormatAccessError("calculation_format_source_check")
            revision, value = None, int(value)
        else:
            revision = _revision(doc.get("modified"))
            if value is not None and (type(value) is not str or len(value.encode("utf-8")) > 4096 or "\0" in value):
                raise CalculationFormatAccessError("calculation_format_source_value")
        return cls(doc.doctype, _name(doc.name), revision, FIELDS[doc.doctype], (value,))


def _pin_row(row):
    if type(row) is not FormatSourceRow or row.doctype not in FIELDS or row.fields != FIELDS[row.doctype] or type(row.values) is not tuple or len(row.values) != 1:
        raise ValueError
    def get(name):
        return row.revision if name == "modified" else row.values[0] if name in row.fields else None
    pinned = FormatSourceRow.from_document(SimpleNamespace(doctype=row.doctype, name=row.name, get=get))
    if pinned != row:
        raise ValueError
    return pinned


def _row_context(rows):
    if type(rows) is not tuple or len(rows) != 3:
        raise ValueError
    pinned = tuple(_pin_row(row) for row in rows)
    currency, language, system = pinned
    if tuple(row.doctype for row in pinned) != ("Currency", "Language", "System Settings"):
        raise ValueError
    return CurrencyFormatContext(language.name, language.values[0], bool(system.values[0]), currency.name, currency.values[0])


def _require_related_match(rows, formats):
    formats.require_context_match(_row_context(rows))
    native = {row["doctype"]: row for row in json.loads(formats._payload)["records"]}
    for row in rows:
        if row.doctype != "System Settings" and _revision(_validate_scalar(native[row.doctype]["modified"])) != row.revision:
            raise CalculationFormatAccessError("calculation_format_access_related_revision")


class _RelatedFormatPolicy(ArchiveInspectionEngine):
    """Use the parent's exact actor/role and quiet normal READ engine."""

    ROW_TYPE = FormatSourceRow
    ERROR = CalculationFormatAccessError
    ERROR_PREFIX = "calculation_format_access"

    def __init__(self, parent):
        self._parent = parent
        self._scope = parent._scope
        self.DENIED_MESSAGE, self.FAILED_MESSAGE = parent.DENIED_MESSAGE, parent.FAILED_MESSAGE

    def _dependencies(self):
        return self._parent._dependencies()


@dataclass(frozen=True, repr=False)
class SavedInvoiceCurrencyRead:
    """Protected invoice-currency scope, not complete settings/build authority.

    The existing financial parent is imported only on reconstruction to keep
    this helper outside the parent's module initialization dependency cycle.
    """

    financial: object = field(repr=False)
    related: tuple = field(repr=False)
    formats: LockedCurrencyFormatRead = field(repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            if financial != self.financial:
                raise ValueError
            formats = _pin_format_read(self.formats)
            related = tuple(_pin_row(row) for row in self.related) if type(self.related) is tuple else ()
            _require_related_match(related, formats)
            invoice = financial.financial.financial
            body = json.loads(invoice._payload)
            if (invoice.erp_major != 16
                    or financial.context.settings.defaults.parent != "__default"
                    or dict(body["header"])["currency"] != ["str", formats.currency]):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_format_access_result")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "related", related)
        object.__setattr__(self, "formats", formats)

    def __repr__(self):
        return "<SavedInvoiceCurrencyRead protected PARTIAL currency scope, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_format_access_not_serializable")

    def resolve_precision(self, fieldname):
        """Resolve root Currency fields explicitly using the invoice currency.

        Child currency inheritance and Company base-currency options require
        their own source evidence; neither is silently assumed here.
        """
        try:
            pinned = SavedInvoiceCurrencyRead(self.financial, self.related, self.formats)
            if pinned != self or type(fieldname) is not str:
                raise ValueError
            native = pinned.financial.financial
            observed = native.financial
            meta = next(row.applied for row in native.metadata if row.applied.name == observed.doctype)
            definition = meta.get_field(fieldname)
            if definition is None or definition.fieldtype != "Currency" or definition.options != "currency":
                raise ValueError
            result = pinned.financial.resolve_precision(observed.doctype, fieldname, currency_context=pinned.formats.context)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_format_access_precision")
        return result


class FormatAcquisition:
    """Compose normal related READ, locale/currency guards and one SQL reader."""

    def __init__(self, policy, actor, invoice_name, doctype, metadata_reader, cache_reader):
        if not callable(metadata_reader) or not callable(cache_reader):
            raise CalculationFormatAccessError("calculation_format_access_dependencies")
        self._policy, self._actor, self._cache, self._metadata = policy, actor, cache_reader, metadata_reader
        self._runtime = policy._dependencies()[0]
        self.language = _name(getattr(self._runtime.local, "lang", None))
        self._invoice_name, self._doctype = invoice_name, doctype
        self._invoice_load, _ = policy._saved_record_access(actor)
        self.currency = _name(self._invoice_load(doctype, invoice_name).get("currency"))
        related = _RelatedFormatPolicy(policy)
        load, finalize = related._saved_record_access(actor)
        load("Currency", self.currency)
        load("Language", self.language)
        load("System Settings", "System Settings")
        self.rows, _, self._related_recheck = finalize()
        self.recheck_access()
        self.applied = self._applied()
        self.recheck_access()

    def recheck_access(self):
        runtime = self._runtime
        if getattr(runtime.local, "lang", None) != self.language:
            raise CalculationFormatAccessError("calculation_format_access_locale_drift")
        if self._invoice_load(self._doctype, self._invoice_name).get("currency") != self.currency:
            raise CalculationFormatAccessError("calculation_format_access_currency_drift")
        self._related_recheck()

    def _applied(self):
        supplied = self._metadata(self._policy._scope, tuple(row.doctype for row in self.rows))
        return _metas(self.language, self.currency, supplied)

    def require_financial_currency(self, observed):
        body = json.loads(observed._payload)
        if (observed.doctype, observed.name) != (self._doctype, self._invoice_name) or dict(body["header"])["currency"] != ["str", self.currency]:
            raise CalculationFormatAccessError("calculation_format_access_currency_drift")

    def load_for_update(self, connection):
        self.reader = MariaDBCurrencyFormatReader(connection, allow_missing_check=True)
        return self.reader.load_for_update(self.language, currency=self.currency, applied_metadata=self.applied)

    def check_cache(self, observed):
        _require_related_match(self.rows, observed)
        observed.require_context_match(self._cache(self._policy._scope, self.language, self.currency))
        self.recheck_access()

    def require_metadata_unchanged(self):
        if self._applied() != self.applied:
            raise CalculationFormatAccessError("calculation_format_access_metadata_drift")
        self.recheck_access()
