"""Child field/own-Company selection for the SAME owned calculation service.

No transaction, cleanup, presentation, cache repair or runtime registration.
Related formats reuse FormatAcquisition; precision reuses the pure child policy.
"""

from dataclasses import dataclass, field
from types import SimpleNamespace

from .archive_source_access import ArchiveInspectionEngine, SavedSourceRow, _revision
from .calculation_child_access import CalculationChildAccessError, SavedChildCalculationRead
from .child_field_currency import ABSENT
from .company_currency_source import LockedCompanyCurrencyRead, MariaDBCompanyCurrencyReader, _pin_read as _pin_company
from .currency_format_source import LockedCurrencyFormatRead, _pin_read as _pin_formats
from .financial_source_observation import TABLE_FIELDS, _canonical, _name, _scalar


class CompanyCurrencyRow(SavedSourceRow):
    """Normal saved Company READ binds the actual selected currency value."""

    @classmethod
    def from_document(cls, doc):
        if doc.doctype != "Company":
            raise ValueError
        return cls("Company", _name(doc.name), _revision(doc.get("modified")),
            ("default_currency",), (_name(doc.get("default_currency")),))


def _pin_company_row(row):
    if (type(row) is not CompanyCurrencyRow or row.fields != ("default_currency",)
            or type(row.values) is not tuple or len(row.values) != 1):
        raise ValueError
    pinned = CompanyCurrencyRow.from_document(SimpleNamespace(doctype=row.doctype, name=row.name,
        get={"modified": row.revision, "default_currency": row.values[0]}.get))
    if pinned != row:
        raise ValueError
    return pinned


def require_field_read(doc, fieldname, actor, runtime, denied_message):
    """Use ordinary field levels on related records, not document READ alone."""
    df = doc.meta.get_field(fieldname)
    if df is None:
        raise CalculationChildAccessError("calculation_child_related_field")
    level = df.get("permlevel")
    level = 0 if level is None else level
    allowed = doc.meta.get_permlevel_access("read", user=actor[1])
    if (type(level) is not int or not 0 <= level < 2**31 or type(allowed) not in (list, tuple, set)
            or any(type(value) is not int or value < 0 for value in allowed)):
        raise CalculationChildAccessError("calculation_child_related_field")
    if actor[1] != "Administrator" and level > 0 and level not in allowed:
        runtime.throw(denied_message, runtime.PermissionError)
    return level


class _CompanyPolicy(ArchiveInspectionEngine):
    ROW_TYPE = CompanyCurrencyRow
    ERROR = CalculationChildAccessError
    ERROR_PREFIX = "calculation_child_company"

    def __init__(self, parent):
        self._parent, self._scope = parent, parent._scope
        self.DENIED_MESSAGE, self.FAILED_MESSAGE = parent.DENIED_MESSAGE, parent.FAILED_MESSAGE

    def _dependencies(self):
        return self._parent._dependencies()


class ChildFieldAcquisition:
    """Select one already authorized row/field before metadata callbacks.

    Fresh saved selection supports own currency or the explicit own-Company
    option. Missing own Company is unresolved, never a parent Company fallback.
    No in-memory parent_doc currency is substituted for the saved invoice.
    """

    def __init__(self, children, policy, actor, row_name, fieldname):
        if type(fieldname) is not str or fieldname not in TABLE_FIELDS[children.parentfield]:
            raise CalculationChildAccessError("calculation_child_field_selection")
        _name(row_name)
        matches = [row for row in children.rows if row.name == row_name]
        if len(matches) != 1:
            raise CalculationChildAccessError("calculation_child_field_selection")
        self.children, self._policy, self._actor = children, policy, actor
        self.row, self.fieldname = matches[0], fieldname
        self._runtime = policy._dependencies()[0]
        self._parent_load, _ = policy._saved_record_access(actor)
        parent = self._parent_load(children._doctype, children._name)
        self.invoice_currency = _name(parent.get("currency"))
        self.definition, options = self._definition()
        self.company_source, self.company_rows, self._company_recheck = None, (), None
        self.company_name = None
        if options == "currency":
            self.currency = _name(self.row.values[4] or self.invoice_currency)
        elif options == "Company:company:default_currency":
            self.currency = None
            # Frappe resolves this option from the CHILD's own Company only.
            # An absent/NULL/blank link is a valid unresolved selection, not
            # permission to read the parent Company or Currency(None).
            if self.row.values[5] not in (None, ""):
                self.company_name = _name(self.row.values[5])
                company = _CompanyPolicy(policy)
                self._company_load, finalize = company._saved_record_access(actor)
                doc = self._company_load("Company", self.company_name)
                self.currency = _name(doc.get("default_currency"))
                self.company_level = self._company_field(doc)
                self.company_rows, _, self._company_recheck = finalize()
        else:
            raise CalculationChildAccessError("calculation_child_field_options")
        self.recheck_access()

    def _definition(self):
        df = self._runtime.get_meta(self.children.childtype).get_field(self.fieldname)
        if df is None or df.fieldtype != "Currency":
            raise CalculationChildAccessError("calculation_child_field_definition")
        return _canonical([_scalar(df.fieldtype), _scalar(df.options), _scalar(df.get("precision"))]), df.options

    def _company_field(self, doc):
        df = doc.meta.get_field("default_currency")
        if df is None or df.fieldtype != "Link" or df.options != "Currency":
            raise CalculationChildAccessError("calculation_child_company_field")
        return require_field_read(doc, "default_currency", self._actor, self._runtime, self._policy.DENIED_MESSAGE)

    def recheck_access(self):
        parent = self._parent_load(self.children._doctype, self.children._name)
        if parent.get("currency") != self.invoice_currency or self._definition()[0] != self.definition:
            raise CalculationChildAccessError("calculation_child_field_drift")
        if self._company_recheck is not None:
            self._company_recheck()
            if self._company_field(self._company_load("Company", self.company_name)) != self.company_level:
                raise CalculationChildAccessError("calculation_child_company_field_drift")

    def require_financial_metadata(self, metadata):
        df = next(meta for meta in metadata if meta.name == self.children.childtype).get_field(self.fieldname)
        if df is None or _canonical([_scalar(df.fieldtype), _scalar(df.options), _scalar(df.get("precision"))]) != self.definition:
            raise CalculationChildAccessError("calculation_child_field_metadata")
        if self.company_name is not None:
            df = metadata[0].get_field("default_currency")
            if df is None or df.fieldtype != "Link" or df.options != "Currency":
                raise CalculationChildAccessError("calculation_child_company_metadata")
        self.recheck_access()

    def load_for_update(self, connection, metadata, child):
        if self.company_name is not None:
            self.company_reader = MariaDBCompanyCurrencyReader(connection)
            self.company_source = self.company_reader.load_for_update(self.company_name, metadata=metadata)
            saved = self.company_rows[0]
            if self.company_source.currency != self.currency or self.company_source.revision != saved.revision:
                raise CalculationChildAccessError("calculation_child_company_native")
        resolved = child.resolve_currency(self.row.name, self.fieldname, company_currency=self.company_source)
        if resolved.currency != self.currency:
            raise CalculationChildAccessError("calculation_child_currency_native")
        self.recheck_access()

    def require_unchanged(self):
        if self.company_source is not None:
            self.company_reader.require_unchanged(self.company_source)
        self.recheck_access()


@dataclass(frozen=True, repr=False)
class SavedChildFieldRead:
    """One bound child field with authorized Company/format evidence, not XML."""

    parent: SavedChildCalculationRead = field(repr=False)
    row_name: str = field(repr=False)
    fieldname: str = field(repr=False)
    company: LockedCompanyCurrencyRead | None = field(default=None, repr=False)
    company_rows: tuple = field(default=(), repr=False)
    formats: LockedCurrencyFormatRead | None = field(default=None, repr=False)
    related: tuple = field(default=(), repr=False)

    def __post_init__(self):
        try:
            from .calculation_format_access import _pin_row, _require_related_match
            if type(self.parent) is not SavedChildCalculationRead:
                raise ValueError
            parent = SavedChildCalculationRead(self.parent.financial, self.parent.child, self.parent.tables)
            if parent != self.parent or type(self.company_rows) is not tuple or type(self.related) is not tuple:
                raise ValueError
            if parent.financial.context.settings.defaults.parent != "__default":
                raise ValueError
            company = None if self.company is None else _pin_company(self.company)
            rows = tuple(_pin_company_row(row) for row in self.company_rows)
            resolved = parent.child.resolve_currency(self.row_name, self.fieldname, company_currency=company)
            if resolved.currency is not None:
                _name(resolved.currency)
            if company is not None and resolved.metadata.get_field(self.fieldname).options != "Company:company:default_currency":
                raise ValueError
            if company is None:
                if rows:
                    raise ValueError
            elif (len(rows) != 1 or rows[0].name != company.name or rows[0].revision != company.revision
                    or rows[0].values != (company.currency,) or company.metadata != parent.financial.context.metadata[0]):
                raise ValueError
            formats = None if self.formats is None else _pin_formats(self.formats)
            related = tuple(_pin_row(row) for row in self.related)
            major = parent.financial.financial.financial.erp_major
            if major == 15:
                if formats is not None or related:
                    raise ValueError
            else:
                if formats is None or formats.currency != resolved.currency:
                    raise ValueError
                _require_related_match(related, formats)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationChildAccessError("calculation_child_field_result")
        object.__setattr__(self, "parent", parent)
        object.__setattr__(self, "company", company)
        object.__setattr__(self, "company_rows", rows)
        object.__setattr__(self, "formats", formats)
        object.__setattr__(self, "related", related)

    def resolve_currency(self):
        pinned = SavedChildFieldRead(self.parent, self.row_name, self.fieldname, self.company, self.company_rows, self.formats, self.related)
        if pinned != self:
            raise CalculationChildAccessError("calculation_child_field_result")
        return pinned.parent.child.resolve_currency(pinned.row_name, pinned.fieldname, company_currency=pinned.company)

    def resolve_precision(self):
        return self.resolve_currency().resolve_precision(self.parent.financial.context.settings.defaults,
            currency_context=None if self.formats is None else self.formats.context)

    def require_field_currency_match(self, *, row_entry=ABSENT, parent_entry=ABSENT):
        self.resolve_currency().require_cached_match(row_entry=row_entry, parent_entry=parent_entry)

    def require_cached_precision_match(self, cached):
        self.resolve_precision().require_cached_match(cached)

    def __repr__(self):
        return "<SavedChildFieldRead protected PARTIAL child Company/formats, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_child_field_not_serializable")
