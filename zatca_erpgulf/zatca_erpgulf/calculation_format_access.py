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
from .financial_source_observation import TABLE_FIELDS, _child_type
from .company_currency_source import (
    LockedCompanyCurrencyRead, MariaDBCompanyCurrencyReader, _pin_read as _pin_company_read,
)

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
class SavedFieldCurrencyRead:
    """Protected invoice/Company-currency scope, not complete build authority.

    The existing financial parent is imported only on reconstruction to keep
    this helper outside the parent's module initialization dependency cycle.
    """

    financial: object = field(repr=False)
    related: tuple = field(repr=False)
    formats: LockedCurrencyFormatRead = field(repr=False)
    company_currency: LockedCompanyCurrencyRead | None = field(default=None, repr=False)

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
                    or financial.context.settings.defaults.parent != "__default"):
                raise ValueError
            company = None if self.company_currency is None else _pin_company_read(self.company_currency)
            header = dict(body["header"])
            if company is None:
                if header["currency"] != ["str", formats.currency]: raise ValueError
            elif (header["company"] != ["str", company.name] or company.currency != formats.currency
                    or company.metadata != financial.context.metadata[0]
                    or company.revision != financial.context.settings.sources[0].revision):
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
        object.__setattr__(self, "company_currency", company)

    def __repr__(self):
        return "<SavedFieldCurrencyRead protected PARTIAL currency scope, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_format_access_not_serializable")

    def _field(self, fieldname, parentfield):
        native = self.financial.financial
        observed = native.financial
        metas = {row.applied.name: row.applied for row in native.metadata}
        doctype = observed.doctype
        if parentfield is not None:
            if type(parentfield) is not str or parentfield not in TABLE_FIELDS:
                raise ValueError
            root = metas[doctype]
            child = _child_type(doctype, parentfield)
            table = root.get_field(parentfield)
            if table is None or table.fieldtype != "Table" or table.options != child:
                raise ValueError
            doctype = child
        definition = metas[doctype].get_field(fieldname)
        options = "currency" if self.company_currency is None else "Company:company:default_currency"
        if definition is None or definition.fieldtype != "Currency" or definition.options != options:
            raise ValueError
        return doctype

    def resolve_precision(self, fieldname, *, parentfield=None):
        """Resolve a root field or the PARENT document's child-field precision.

        This matches doc.precision(field, parentfield), not row.precision(field).
        Direct child currency/cache inheritance remains a separate boundary.
        """
        try:
            pinned = SavedFieldCurrencyRead(self.financial, self.related, self.formats, self.company_currency)
            if pinned != self or type(fieldname) is not str:
                raise ValueError
            doctype = pinned._field(fieldname, parentfield)
            result = pinned.financial.resolve_precision(doctype, fieldname, currency_context=pinned.formats.context)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_format_access_precision")
        return result

    def require_field_currency_match(self, fieldname, cached, *, parentfield=None):
        """Compare an explicit field-currency cache value; never populate it."""
        try:
            pinned = SavedFieldCurrencyRead(self.financial, self.related, self.formats, self.company_currency)
            if pinned != self or type(fieldname) is not str: raise ValueError
            pinned._field(fieldname, parentfield)
            if type(cached) is not str or cached != pinned.formats.currency: raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_field_currency_cache_mismatch")


# Preserve the increment119 protected API name without duplicating its policy.
SavedInvoiceCurrencyRead = SavedFieldCurrencyRead


class FormatAcquisition:
    """Compose normal related READ, locale/currency guards and one SQL reader."""

    def __init__(self, policy, actor, invoice_name, doctype, metadata_reader, cache_reader, *, currency_scope="invoice", child_source=None):
        if not callable(metadata_reader) or not callable(cache_reader) or currency_scope not in ("invoice", "company", "child"):
            raise CalculationFormatAccessError("calculation_format_access_dependencies")
        if currency_scope == "child":
            from .calculation_child_format_access import ChildFieldAcquisition
            if type(child_source) is not ChildFieldAcquisition:
                raise CalculationFormatAccessError("calculation_format_access_dependencies")
        elif child_source is not None:
            raise CalculationFormatAccessError("calculation_format_access_dependencies")
        self._child_source = child_source
        self._policy, self._actor, self._cache, self._metadata = policy, actor, cache_reader, metadata_reader
        self._runtime = policy._dependencies()[0]
        self.language = _name(getattr(self._runtime.local, "lang", None))
        self._invoice_name, self._doctype = invoice_name, doctype
        self._invoice_load, _ = policy._saved_record_access(actor)
        invoice = self._invoice_load(doctype, invoice_name)
        self.invoice_currency, self.company_name = _name(invoice.get("currency")), _name(invoice.get("company"))
        self.currency_scope, self.company_source = currency_scope, None
        self._company_load, _ = policy._saved_record_access(actor)
        company = self._company_load("Company", self.company_name) if currency_scope == "company" else None
        self.currency = _name(company.get("default_currency")) if company is not None else self.invoice_currency
        if child_source is not None:
            self.currency = child_source.currency
        related = _RelatedFormatPolicy(policy)
        load, finalize = related._saved_record_access(actor)
        load("Currency", self.currency)
        load("Language", self.language)
        load("System Settings", "System Settings")
        self.rows, _, self._related_recheck = finalize()
        self._related_load = load
        self._field_levels = self._related_field_levels() if child_source is not None else None
        self.recheck_access()
        self.applied = self._applied()
        self.recheck_access()

    def recheck_access(self):
        runtime = self._runtime
        if getattr(runtime.local, "lang", None) != self.language:
            raise CalculationFormatAccessError("calculation_format_access_locale_drift")
        invoice = self._invoice_load(self._doctype, self._invoice_name)
        if invoice.get("currency") != self.invoice_currency or invoice.get("company") != self.company_name:
            raise CalculationFormatAccessError("calculation_format_access_currency_drift")
        if self.currency_scope == "company" and self._company_load("Company", self.company_name).get("default_currency") != self.currency:
            raise CalculationFormatAccessError("calculation_format_access_company_currency_drift")
        self._related_recheck()
        if self._child_source is not None:
            self._child_source.recheck_access()
            if self._related_field_levels() != self._field_levels:
                raise CalculationFormatAccessError("calculation_format_access_field_drift")

    def _related_field_levels(self):
        from .calculation_child_format_access import require_field_read
        return tuple((row.doctype, require_field_read(self._related_load(row.doctype, row.name),
            FIELDS[row.doctype][0], self._actor, self._runtime, self._policy.DENIED_MESSAGE)) for row in self.rows)

    def _applied(self):
        supplied = self._metadata(self._policy._scope, tuple(row.doctype for row in self.rows))
        return _metas(self.language, self.currency, supplied)

    def require_financial_currency(self, observed):
        body = json.loads(observed._payload)
        header = dict(body["header"])
        if ((observed.doctype, observed.name) != (self._doctype, self._invoice_name)
                or header["currency"] != ["str", self.invoice_currency]
                or header["company"] != ["str", self.company_name]):
            raise CalculationFormatAccessError("calculation_format_access_currency_drift")

    def load_company_currency(self, connection, metadata):
        self.company_reader = MariaDBCompanyCurrencyReader(connection)
        self.company_source = self.company_reader.load_for_update(self.company_name, metadata=metadata)
        company = self._company_load("Company", self.company_name)
        if self.company_source.currency != self.currency or self.company_source.revision != _revision(company.get("modified")):
            raise CalculationFormatAccessError("calculation_format_access_company_currency_drift")

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
