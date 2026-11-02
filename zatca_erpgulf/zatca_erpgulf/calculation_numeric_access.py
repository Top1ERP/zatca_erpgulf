"""Saved real-number getters on the shared owned financial/defaults pipeline.

Use existing full graph READ, native data and cleanup. Pin initial/fresh parent,
saved children and embedded references without fixing a numeric type or reading
an unused setting/cache. No second SQL owner, money math, write or runtime hook.
"""

from dataclasses import dataclass, field
import json

from .calculation_child_access import FinancialGraphAccess, SavedChildCurrencyRow, _pin_tables, _require_graph_match
from .financial_source_observation import HEADER_FIELDS, TABLE_FIELDS, _canonical, _scalar
from .financial_numeric_view import InvoiceNumericView, FinancialNumericViewError, _numeric_fields, _getter, _pin_view
from .source_metadata import PROPERTIES, SourceFieldDefinition


class NumericAcquisition(FinancialGraphAccess):
    """Authorize the complete returned graph before any metadata/SQL callback."""

    def __init__(self, policy, actor, invoice_name, doctype):
        super().__init__(policy, actor, invoice_name, doctype)
        self.document = self._parent_load(doctype, invoice_name)
        self.owner = policy.ROW_TYPE.from_document(self.document)
        self._metas = self._metadata_objects(self.document)
        self.schema = self._schema(self._metas)
        self.getters = self._snapshot(original=True)
        self.recheck_access()

    def _metadata_objects(self, parent):
        runtime = self._policy._dependencies()[0]
        return ((self._doctype, parent.meta, HEADER_FIELDS),
            *((access.childtype, runtime.get_meta(access.childtype), TABLE_FIELDS[table]) for table, access in self._tables))

    @staticmethod
    def _schema(metas):
        observed = []
        for doctype, meta, fields in metas:
            if meta.name != doctype:
                raise FinancialNumericViewError("financial_numeric_metadata_identity")
            selected = []
            for name, definition in _numeric_fields(meta, fields):
                if definition.fieldname != name:
                    raise ValueError
                pinned = SourceFieldDefinition(name, _canonical([[prop, _scalar(definition.get(prop))] for prop in PROPERTIES]))
                selected.append((name, pinned))
            observed.append((doctype, tuple(selected)))
        return tuple(observed)

    def _values(self, doc, group, expected, fields):
        if group == "header":
            if self._policy.ROW_TYPE.from_document(doc) != self.owner:
                raise FinancialNumericViewError("financial_numeric_owner_drift")
        elif SavedChildCurrencyRow.from_document(doc) != expected:
            raise FinancialNumericViewError("financial_numeric_child_drift")
        return [[group, doc.name, name, _getter(doc.get(name), "SAVED", definition.fieldtype)] for name, definition in fields]

    def _snapshot(self, *, original):
        parent = self.document if original else self._parent_load(self._doctype, self._name)
        schema = dict(self.schema)
        cells = self._values(parent, "header", None, schema[self._doctype])
        for table, access in self._tables:
            docs = access.documents if original else tuple(access._load(access.childtype, row.name) for row in access.rows)
            refs = access.references if original else parent.get(table)
            if len(docs) != len(access.rows) or len(refs) != len(docs):
                raise ValueError
            fields = schema[access.childtype]
            for doc, ref, row in zip(docs, refs, access.rows):
                saved = self._values(doc, table, row, fields)
                if saved != self._values(ref, table, row, fields):
                    raise FinancialNumericViewError("financial_numeric_reference_mismatch")
                cells.extend(saved)
        return _canonical(cells)

    def recheck_access(self):
        super().recheck_access()
        fresh = self._parent_load(self._doctype, self._name)
        if self._schema(self._metas) != self.schema or self._schema(self._metadata_objects(fresh)) != self.schema:
            raise FinancialNumericViewError("financial_numeric_metadata_drift")
        if self._snapshot(original=True) != self.getters or self._snapshot(original=False) != self.getters:
            raise FinancialNumericViewError("financial_numeric_getters_changed")

    def prepare_metadata(self):
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        super().require_financial_metadata(metadata)
        applied = {meta.name: meta for meta in metadata}
        expected = tuple((doctype, _numeric_fields(applied[doctype], fields)) for doctype, _, fields in self._metas)
        if expected != self.schema:
            raise FinancialNumericViewError("financial_numeric_metadata_match")

    def load_for_update(self, connection, financial):
        # The shared service already owns and reads this exact native parent;
        # this extension issues no native SQL or separate transaction. Ordinary
        # READ/getter rechecks can still reload documents through Frappe.
        _require_graph_match(self.tables, financial)
        result = InvoiceNumericView(financial, "SAVED", _canonical(dict(profile="invoice-real-numeric-view/v1",
            financial_sha256=financial.sha256, stage="SAVED", cells=json.loads(self.getters))))
        self.check_getters(result)
        return result

    def check_getters(self, observed):
        observed = _pin_view(observed)
        if observed.stage != "SAVED" or json.loads(observed._payload)["cells"] != json.loads(self.getters):
            raise FinancialNumericViewError("financial_numeric_view_binding")
        self.recheck_access()

    def require_metadata_unchanged(self):
        self.recheck_access()

    def require_unchanged(self, observed):
        # Final native SQL checks belong to the existing parent reader. This
        # extension has no trusted provider callback to invalidate them later.
        self.check_getters(observed)


@dataclass(frozen=True, repr=False)
class SavedFinancialNumericRead:
    """Protected saved getter/native binding, NOT full calculation authority."""

    financial: object = field(repr=False)
    view: InvoiceNumericView = field(repr=False)
    tables: tuple = field(repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            view = _pin_view(self.view)
            tables = _pin_tables(self.tables)
            if financial != self.financial or view.financial != financial.financial or view.stage != "SAVED":
                raise ValueError
            if financial.context.settings.defaults.parent != "__default":
                raise ValueError
            _require_graph_match(tables, view.financial)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FinancialNumericViewError("financial_numeric_saved_result")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "view", view)
        object.__setattr__(self, "tables", tables)

    def __repr__(self):
        return "<SavedFinancialNumericRead protected PARTIAL getter proof, NOT money authority>"

    def __reduce__(self):
        raise TypeError("financial_numeric_saved_not_serializable")
