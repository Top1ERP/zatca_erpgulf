"""Permissioned invoice-Currency fraction on the shared owned financial service.

Normal Currency READ binds identity/revision/field access, not a document-default
or ORM value in place of the consumed post-flt database API projection. Reuse the
financial graph and related READ engines. No extra SQL owner/cleanup/UI pipeline,
money calculation, active rounding branch, runtime registration or authority I/O.
"""

from dataclasses import dataclass, field
import json

from .archive_source_access import SavedSourceRow, _name, _revision
from .calculation_child_access import FinancialGraphAccess, _pin_tables, _require_graph_match
from .calculation_child_format_access import require_field_read
from .calculation_format_access import _RelatedFormatPolicy, CalculationFormatAccessError
from .currency_fraction_source import (
    FIELD, LockedCurrencyFractionRead, MariaDBCurrencyFractionReader, _meta, _pin_read,
)
from .financial_source_observation import _canonical, _scalar, _validate_scalar
from .source_metadata import CURRENCY_FRACTION_PROFILE, PROPERTIES, SourceFieldDefinition, project_source_metadata


class FractionAccessRow(SavedSourceRow):
    """Normal Currency access/revision only; never read its configuration value."""

    @classmethod
    def from_document(cls, doc):
        if doc.doctype != "Currency":
            raise ValueError
        return cls("Currency", _name(doc.name), _revision(doc.get("modified")), (), ())


class _FractionPolicy(_RelatedFormatPolicy):
    ROW_TYPE = FractionAccessRow


def _link_definition(doc):
    if doc.meta.name != doc.doctype:
        raise ValueError
    df = doc.meta.get_field("currency")
    if df is None or df.get("fieldname") != "currency" or df.fieldtype != "Link" or df.options != "Currency":
        raise ValueError
    return SourceFieldDefinition("currency", _canonical([[name, _scalar(df.get(name))] for name in PROPERTIES]))


def _require_related(row, fraction):
    revision = _revision(_validate_scalar(json.loads(fraction._payload)["record"]["modified"]))
    if (type(row) is not FractionAccessRow or type(row.doctype) is not str or row.doctype != "Currency"
            or type(row.fields) is not tuple or row.fields or type(row.values) is not tuple or row.values):
        raise ValueError
    pinned = FractionAccessRow("Currency", _name(row.name), _revision(row.revision), (), ())
    if pinned != row or (pinned.name, pinned.revision) != (fraction.currency, revision):
        raise ValueError
    return pinned


class FractionAcquisition:
    """Full graph plus related record/field READ precedes every callback."""

    def __init__(self, policy, actor, invoice_name, doctype, metadata_reader, cache_reader, *, financial_graph=None):
        if not callable(metadata_reader) or not callable(cache_reader):
            raise CalculationFormatAccessError("calculation_fraction_dependencies")
        self._metadata, self._cache, self._actor = metadata_reader, cache_reader, actor
        self.graph = financial_graph if financial_graph is not None else FinancialGraphAccess(policy, actor, invoice_name, doctype)
        if (not isinstance(self.graph, FinancialGraphAccess) or self.graph._policy is not policy
                or (self.graph._name, self.graph._doctype) != (invoice_name, doctype)):
            raise CalculationFormatAccessError("calculation_fraction_graph")
        self._policy, self._name, self._doctype = policy, invoice_name, doctype
        self.tables, self._parent_load = self.graph.tables, self.graph._parent_load
        self.document = self._parent_load(doctype, invoice_name)
        self.owner = policy.ROW_TYPE.from_document(self.document)
        self.link, self.link_level, self.currency = self._root_state(self.document)
        related = _FractionPolicy(policy)
        self._load_currency, finalize = related._saved_record_access(actor)
        self.currency_document = self._load_currency("Currency", self.currency)
        self.definition, self.level = self._currency_state(self.currency_document)
        self.rows, _, self._related_recheck = finalize()
        self.recheck_access()

    def _root_state(self, doc):
        if self._policy.ROW_TYPE.from_document(doc) != self.owner:
            raise CalculationFormatAccessError("calculation_fraction_owner_drift")
        definition = _link_definition(doc)
        level = require_field_read(doc, "currency", self._actor, self._policy._dependencies()[0], self._policy.DENIED_MESSAGE)
        return definition, level, _name(doc.get("currency"))

    def _currency_state(self, doc):
        if (doc.doctype, doc.name) != ("Currency", self.currency):
            raise ValueError
        applied = _meta(project_source_metadata(doc.meta, base_fields={}, profile=CURRENCY_FRACTION_PROFILE))
        level = require_field_read(doc, FIELD, self._actor, self._policy._dependencies()[0], self._policy.DENIED_MESSAGE)
        return applied, level

    def recheck_access(self):
        self.graph.recheck_access()
        expected = self.link, self.link_level, self.currency
        if (self._root_state(self.document) != expected
                or self._root_state(self._parent_load(self._doctype, self._name)) != expected):
            raise CalculationFormatAccessError("calculation_fraction_invoice_drift")
        self._related_recheck()
        expected = self.definition, self.level
        if (self._currency_state(self.currency_document) != expected
                or self._currency_state(self._load_currency("Currency", self.currency)) != expected):
            raise CalculationFormatAccessError("calculation_fraction_field_drift")

    def _applied(self):
        supplied = self._metadata(self._policy._scope, ("Currency",))
        if type(supplied) is not dict or set(supplied) != {"Currency"}:
            raise ValueError
        applied = _meta(supplied["Currency"])
        if applied != self.definition:
            raise CalculationFormatAccessError("calculation_fraction_metadata_match")
        return applied

    def prepare_metadata(self):
        self.applied = self._applied()
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        self.graph.require_financial_metadata(metadata)
        if metadata[0].get_field("currency") != self.link:
            raise CalculationFormatAccessError("calculation_fraction_link_metadata")

    def load_for_update(self, connection, financial):
        _require_graph_match(self.tables, financial)
        self.reader = MariaDBCurrencyFractionReader(connection)
        observed = self.reader.load_for_update(financial, applied_metadata=self.applied)
        self.check_getters(observed)
        return observed

    def check_getters(self, observed):
        observed = _pin_read(observed)
        _require_related(self.rows[0], observed)
        if observed.currency != self.currency:
            raise ValueError
        observed.require_effective_cache_match(self._cache(self._policy._scope, self.currency))
        self.recheck_access()

    def require_metadata_unchanged(self):
        if self._applied() != self.applied:
            raise CalculationFormatAccessError("calculation_fraction_metadata_drift")
        self.recheck_access()

    def require_unchanged(self, observed):
        # No trusted cache/metadata callback may run after final native checks.
        self.reader.require_unchanged(observed)
        self.recheck_access()


@dataclass(frozen=True, repr=False)
class SavedCurrencyFractionContext:
    """Protected partial financial/access/API inspection, NOT rounding policy."""

    financial: object = field(repr=False)
    fraction: LockedCurrencyFractionRead = field(repr=False)
    tables: tuple = field(repr=False)
    related: tuple = field(repr=False)
    invoice_currency: str = field(repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            fraction = _pin_read(self.fraction)
            if (financial != self.financial or fraction.financial != financial.financial
                    or financial.context.settings.defaults.parent != "__default"
                    or self.invoice_currency != fraction.currency or type(self.invoice_currency) is not str
                    or type(self.related) is not tuple or len(self.related) != 1):
                raise ValueError
            related = (_require_related(self.related[0], fraction),)
            tables = _pin_tables(self.tables)
            _require_graph_match(tables, fraction.financial)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_fraction_result")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "fraction", fraction)
        object.__setattr__(self, "tables", tables)
        object.__setattr__(self, "related", related)

    def __repr__(self):
        return "<SavedCurrencyFractionContext protected PARTIAL inspection, NOT rounding policy>"

    def __reduce__(self):
        raise TypeError("calculation_fraction_not_serializable")
