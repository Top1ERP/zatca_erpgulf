"""Permissioned invoice controls on the shared owned calculation service.

Authorize the returned financial graph with the existing graph engine. Bind
selected definitions/levels and Check getters on the initial authorized invoice
and fresh access rechecks. No extra child-link SQL, transaction/cleanup/UI owner,
money coercion, active rounding policy, runtime registration or authority I/O.
"""

from dataclasses import dataclass, field

from .calculation_child_access import (
    FinancialGraphAccess, CalculationChildAccessError, _pin_tables, _require_graph_match,
)
from .calculation_child_format_access import require_field_read
from .invoice_rounding_source import (
    FIELDS, CHECKS, OVERLAP, LockedInvoiceRoundingRead, MariaDBInvoiceRoundingReader,
    _meta, _pin_read,
)
from .source_metadata import INVOICE_ROUNDING_PROFILE, project_source_metadata


class InvoiceRoundingAcquisition(FinancialGraphAccess):
    """Record/table/row/field READ precedes all metadata/connection callbacks."""

    def __init__(self, policy, actor, invoice_name, doctype, metadata_reader, *, _shared_graph=None):
        if not callable(metadata_reader):
            raise CalculationChildAccessError("calculation_invoice_rounding_dependencies")
        self._metadata, self._actor = metadata_reader, actor
        super().__init__(policy, actor, invoice_name, doctype, _shared_graph=_shared_graph)
        self.document = self._parent_load(doctype, invoice_name) if _shared_graph is None else _shared_graph.document
        self.owner = policy.ROW_TYPE.from_document(self.document)
        self.definition, self.levels, self.checks = self._state(self.document)
        self.recheck_access()

    def _state(self, doc):
        if self._policy.ROW_TYPE.from_document(doc) != self.owner:
            raise CalculationChildAccessError("calculation_invoice_rounding_owner_drift")
        applied = _meta(project_source_metadata(doc.meta, base_fields={}, profile=INVOICE_ROUNDING_PROFILE))
        if applied.name != self._doctype:
            raise CalculationChildAccessError("calculation_invoice_rounding_metadata_identity")
        runtime = self._policy._dependencies()[0]
        levels = tuple(require_field_read(doc, name, self._actor, runtime, self._policy.DENIED_MESSAGE)
            if applied.has_field(name) else None for name in FIELDS)
        checks = []
        for name in CHECKS:
            value = doc.get(name)
            if applied.has_field(name):
                if value is not None and (type(value) is not int or value not in (0, 1)):
                    raise CalculationChildAccessError("calculation_invoice_rounding_getter")
            elif value is not None:
                raise CalculationChildAccessError("calculation_invoice_rounding_absent_getter")
            checks.append((name, value))
        return applied, levels, tuple(checks)

    def recheck_access(self):
        super().recheck_access()
        expected = self.definition, self.levels, self.checks
        # Keep the first authorized object as a getter source. Loading a fresh
        # document must not silently replace or hide drift in that initial view.
        if (self._state(self.document) != expected
                or self._state(self._parent_load(self._doctype, self._name)) != expected):
            raise CalculationChildAccessError("calculation_invoice_rounding_saved_drift")

    def _applied(self):
        supplied = self._metadata(self._policy._scope, (self._doctype,))
        if type(supplied) is not dict or set(supplied) != {self._doctype}:
            raise CalculationChildAccessError("calculation_invoice_rounding_metadata_scope")
        applied = _meta(supplied[self._doctype])
        if applied != self.definition:
            raise CalculationChildAccessError("calculation_invoice_rounding_metadata_match")
        return applied

    def prepare_metadata(self):
        self.applied = self._applied()
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        super().require_financial_metadata(metadata)
        root = metadata[0]
        if any(root.get_field(name) != self.applied.get_field(name) for name in OVERLAP):
            raise CalculationChildAccessError("calculation_invoice_rounding_metadata_overlap")

    def load_for_update(self, connection, financial):
        _require_graph_match(self.tables, financial)
        self.reader = MariaDBInvoiceRoundingReader(connection)
        result = self.reader.load_for_update(financial, applied_metadata=self.applied)
        self.check_getters(result)
        return result

    def check_getters(self, observed):
        _pin_read(observed).require_saved_check_match(dict(self.checks))
        self.recheck_access()

    def require_metadata_unchanged(self):
        if self._applied() != self.applied:
            raise CalculationChildAccessError("calculation_invoice_rounding_metadata_drift")
        self.recheck_access()

    def require_unchanged(self, observed):
        self.reader.require_unchanged(observed)
        self.check_getters(observed)


@dataclass(frozen=True, repr=False)
class SavedInvoiceRoundingContext:
    """Partial protected financial/normal-getter binding, NOT rounding policy."""

    financial: object = field(repr=False)
    controls: LockedInvoiceRoundingRead = field(repr=False)
    tables: tuple = field(repr=False)
    checks: tuple = field(repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            controls = _pin_read(self.controls)
            if (financial != self.financial or controls.financial != financial.financial
                    or financial.context.settings.defaults.parent != "__default"):
                raise ValueError
            tables = _pin_tables(self.tables)
            _require_graph_match(tables, controls.financial)
            if (type(self.checks) is not tuple or len(self.checks) != len(CHECKS)
                    or any(type(row) is not tuple or len(row) != 2 for row in self.checks)
                    or tuple(row[0] for row in self.checks) != CHECKS):
                raise ValueError
            controls.require_saved_check_match(dict(self.checks))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationChildAccessError("calculation_invoice_rounding_result")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "controls", controls)
        object.__setattr__(self, "tables", tables)

    def __repr__(self):
        return "<SavedInvoiceRoundingContext protected PARTIAL inspection, NOT rounding policy>"

    def __reduce__(self):
        raise TypeError("calculation_invoice_rounding_not_serializable")
