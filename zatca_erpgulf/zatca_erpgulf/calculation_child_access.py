"""Saved child READ and source binding for the existing calculation service.

Compose the shared actor/quiet ACL engine and native child reader. No second
SQL owner, cleanup/display pipeline, public endpoint, write or authority request.
Related Company/format/cache acquisition remains separate from these own links.
"""

from dataclasses import dataclass, field
import json
from types import SimpleNamespace

from .archive_source_access import ArchiveInspectionEngine, ArchiveSourceAccessError, SavedSourceRow, _revision
from .child_currency_source import (
    LockedChildCurrencyRead, MariaDBChildCurrencyReader, _declaration, _pin_read,
)
from .child_field_currency import ABSENT
from .financial_source_observation import HEADER_FIELDS, MAX_ROWS, TABLE_FIELDS, _child_type, _name, _validate_scalar
from .permission_compat import saved_row_has_permission
from .source_metadata import CHILD_CURRENCY_FIELDS

FIELDS = ("parent", "parenttype", "parentfield", "idx", "currency", "company")


class CalculationChildAccessError(ArchiveSourceAccessError):
    """Static English code without child, actor or native source disclosure."""


class SavedChildCurrencyRow(SavedSourceRow):
    """Minimal bound child links; nullable child revision is preserved."""

    @classmethod
    def from_document(cls, doc):
        if type(doc.doctype) is not str or doc.doctype not in CHILD_CURRENCY_FIELDS:
            raise ValueError
        parent, parenttype, parentfield = (doc.get(name) for name in FIELDS[:3])
        if (parenttype not in ("Sales Invoice", "POS Invoice") or parentfield not in TABLE_FIELDS
                or doc.doctype != _child_type(parenttype, parentfield)):
            raise ValueError
        _name(parent)
        idx = doc.get("idx")
        if type(idx) is not int or not 1 <= idx <= MAX_ROWS:
            raise ValueError
        values = tuple(doc.get(name) for name in FIELDS)
        for value in values[4:]:
            if value is not None and value != "":
                _name(value)
            elif value is not None and type(value) is not str:
                raise ValueError
        revision = doc.get("modified")
        return cls(doc.doctype, _name(doc.name), None if revision is None else _revision(revision), FIELDS, values)


def _pin_row(row):
    if type(row) is not SavedChildCurrencyRow or row.fields != FIELDS or type(row.values) is not tuple or len(row.values) != len(FIELDS):
        raise ValueError
    values = dict(zip(FIELDS, row.values), modified=row.revision)
    pinned = SavedChildCurrencyRow.from_document(SimpleNamespace(doctype=row.doctype, name=row.name, get=values.get))
    if pinned != row:
        raise ValueError
    return pinned


def _require_native_match(rows, child):
    body = json.loads(child._payload)
    root = child.financial.financial
    if len(rows) != len(body["rows"]):
        raise ValueError
    for saved, native in zip(rows, body["rows"]):
        revision = _validate_scalar(native[2])
        revision = None if revision is None else _revision(revision)
        values = dict(native[3])
        # Absent fields require get() == None; column absence is proven by SQL.
        links = tuple(None if values[name] == ["absent"] else _validate_scalar(values[name])
            for name in ("currency", "company"))
        if (saved.name != native[0] or saved.revision != revision
                or saved.doctype != child.metadata.applied.name
                or saved.values != (root.name, root.doctype, child.parentfield, native[1], *links)):
            raise ValueError


class _ChildPolicy(ArchiveInspectionEngine):
    ROW_TYPE = SavedChildCurrencyRow
    ERROR = CalculationChildAccessError
    ERROR_PREFIX = "calculation_child_access"

    def __init__(self, parent):
        self._parent, self._scope = parent, parent._scope
        self.DENIED_MESSAGE, self.FAILED_MESSAGE = parent.DENIED_MESSAGE, parent.FAILED_MESSAGE

    def _dependencies(self):
        return self._parent._dependencies()


class _SavedTableAccess:
    """Normal parent/table/child READ before metadata or SQL acquisition.

    The table permission probe uses the framework child READ engine and the
    already saved/authorized parent. It checks parentfield/permlevel even for an
    empty table; it is not an invented saved child or row-permission substitute.
    """

    def __init__(self, policy, actor, invoice_name, doctype, parentfield):
        self._policy, self._actor = policy, actor
        self._name, self._doctype, self.parentfield = invoice_name, doctype, parentfield
        self.childtype = _child_type(doctype, parentfield)
        self._parent_load, _ = policy._saved_record_access(actor)
        self._children = _ChildPolicy(policy)
        self._load, finalize = self._children._saved_record_access(actor)
        table, refs = self._membership()
        self._table = table
        rows, documents = [], []
        for ref in refs:
            doc = self._load(self.childtype, ref.name)
            row = SavedChildCurrencyRow.from_document(doc)
            if SavedChildCurrencyRow.from_document(ref) != row:
                raise CalculationChildAccessError("calculation_child_access_saved_mismatch")
            rows.append(row)
            documents.append(doc)
        self.rows = tuple(rows)
        # Keep the exact initial authorized objects; later rechecks load fresh
        # documents but must not replace the cache sources being inspected.
        self.documents, self.references = tuple(documents), tuple(refs)
        _, _, self._children_recheck = finalize()
        self.recheck_access()

    def _membership(self):
        parent = self._parent_load(self._doctype, self._name)
        definition = parent.meta.get_field(self.parentfield)
        if definition is None or definition.fieldtype != "Table" or definition.options != self.childtype:
            raise CalculationChildAccessError("calculation_child_access_table")
        level = definition.get("permlevel")
        if level is not None and (type(level) is not int or not 0 <= level < 2**31):
            raise CalculationChildAccessError("calculation_child_access_permlevel")
        runtime, _, engine, _ = self._policy._dependencies()
        probe = SimpleNamespace(doctype=self.childtype, name=None, parent=self._name,
            parenttype=self._doctype, parentfield=self.parentfield, parent_doc=parent)
        if not saved_row_has_permission(engine, self.childtype, "read", doc=probe, user=self._actor[1]):
            runtime.throw(self._policy.DENIED_MESSAGE, runtime.PermissionError)
        refs = parent.get(self.parentfield)
        if type(refs) not in (list, tuple) or len(refs) > MAX_ROWS:
            raise CalculationChildAccessError("calculation_child_access_membership")
        names = set()
        for idx, ref in enumerate(refs, 1):
            if (ref.doctype != self.childtype or type(ref.get("idx")) is not int or ref.get("idx") != idx
                    or (ref.get("parent"), ref.get("parenttype"), ref.get("parentfield")) != (self._name, self._doctype, self.parentfield)):
                raise CalculationChildAccessError("calculation_child_access_membership")
            if _name(ref.name) in names:
                raise CalculationChildAccessError("calculation_child_access_membership")
            names.add(ref.name)
        return (definition.fieldtype, definition.options, level), refs

    def recheck_access(self):
        table, refs = self._membership()
        if table != self._table or tuple(SavedChildCurrencyRow.from_document(ref) for ref in refs) != self.rows:
            raise CalculationChildAccessError("calculation_child_access_saved_drift")
        self._children_recheck()


def _pin_tables(tables):
    if type(tables) is not tuple or not 2 <= len(tables) <= len(TABLE_FIELDS):
        raise ValueError
    names = tuple(entry[0] for entry in tables)
    if names != tuple(name for name in TABLE_FIELDS if name in names) or not {"items", "taxes"} <= set(names):
        raise ValueError
    pinned = []
    for entry in tables:
        if type(entry) is not tuple or len(entry) != 2 or type(entry[1]) is not tuple:
            raise ValueError
        pinned.append((entry[0], tuple(_pin_row(row) for row in entry[1])))
    return tuple(pinned)


def _require_graph_match(tables, financial):
    body = json.loads(financial.financial._payload)
    native_tables = dict(body["tables"])
    names = tuple(name for name in TABLE_FIELDS if native_tables[name] != ["absent"])
    if tuple(name for name, _ in tables) != names:
        raise ValueError
    revisions = dict(json.loads(financial._payload)["revisions"])
    for name, saved_rows in tables:
        native = native_tables[name]["rows"]
        if len(saved_rows) != len(native):
            raise ValueError
        for saved, row, revision in zip(saved_rows, native, revisions[name]):
            modified = _validate_scalar(revision[1])
            modified = None if modified is None else _revision(modified)
            if (saved.doctype != _child_type(financial.financial.doctype, name) or saved.name != row[0]
                    or saved.values[:4] != (financial.financial.name, financial.financial.doctype, name, row[1])
                    or saved.revision != modified):
                raise ValueError


class ChildAcquisition:
    """Authorize ALL tables read by the financial parent, then one link profile."""

    def __init__(self, policy, actor, invoice_name, doctype, parentfield, metadata_reader, *, field_target=None, defer_metadata=False):
        if type(parentfield) is not str or parentfield not in TABLE_FIELDS or not callable(metadata_reader):
            raise CalculationChildAccessError("calculation_child_access_dependencies")
        self._policy, self._metadata = policy, metadata_reader
        self._name, self._doctype, self.parentfield = invoice_name, doctype, parentfield
        self._parent_load, _ = policy._saved_record_access(actor)
        present = self._present_tables()
        if parentfield not in present:
            raise CalculationChildAccessError("calculation_child_access_table")
        self._tables = tuple((name, _SavedTableAccess(policy, actor, invoice_name, doctype, name)) for name in present)
        self.tables = tuple((name, access.rows) for name, access in self._tables)
        self.rows = dict(self.tables)[parentfield]
        self.childtype = _child_type(doctype, parentfield)
        self._fields = self._field_graph()
        self.field_source = None
        if field_target is not None:
            from .calculation_child_format_access import ChildFieldAcquisition
            if type(field_target) is not tuple or len(field_target) != 2:
                raise CalculationChildAccessError("calculation_child_field_selection")
            self.field_source = ChildFieldAcquisition(self, policy, actor, *field_target)
        self.recheck_access()
        if not defer_metadata:
            self.prepare_metadata()

    def prepare_metadata(self):
        self.recheck_access()
        self.applied = self._applied()
        self.recheck_access()

    def _present_tables(self):
        parent = self._parent_load(self._doctype, self._name)
        return tuple(name for name in TABLE_FIELDS if parent.meta.get_field(name) is not None)

    def recheck_access(self):
        if self._present_tables() != tuple(name for name, _ in self._tables):
            raise CalculationChildAccessError("calculation_child_access_table_drift")
        for _, access in self._tables:
            access.recheck_access()
        if self._field_graph() != self._fields:
            raise CalculationChildAccessError("calculation_child_access_field_drift")
        if self.field_source is not None:
            self.field_source.recheck_access()

    def _field_graph(self):
        """Normal document READ does not imply READ of every higher-level field.

        Match the parent permission levels used by Document's field-level read
        filtering, including child fields. Capture only fixed financial/link
        names; permission metadata is ambient and rechecked, not a SQL ACL lock.
        """
        parent = self._parent_load(self._doctype, self._name)
        runtime = self._policy._dependencies()[0]
        actor = self._policy._actor()
        allowed = parent.meta.get_permlevel_access("read", user=actor[1])
        if type(allowed) not in (list, tuple, set) or any(type(level) is not int or level < 0 for level in allowed):
            raise CalculationChildAccessError("calculation_child_access_field_levels")
        selected = [(self._doctype, parent.meta, HEADER_FIELDS)]
        for name, _ in self._tables:
            dt = _child_type(self._doctype, name)
            selected.append((dt, runtime.get_meta(dt), tuple(dict.fromkeys((*TABLE_FIELDS[name], "currency", "company")))))
        graph = []
        for dt, meta, fields in selected:
            levels = []
            for name in fields:
                definition = meta.get_field(name)
                if definition is None:
                    levels.append((name, None))
                    continue
                raw = definition.get("permlevel")
                level = 0 if raw is None else raw
                if type(level) is not int or not 0 <= level < 2**31:
                    raise CalculationChildAccessError("calculation_child_access_field_levels")
                if actor[1] != "Administrator" and level > 0 and level not in allowed:
                    runtime.throw(self._policy.DENIED_MESSAGE, runtime.PermissionError)
                levels.append((name, level))
            graph.append((dt, tuple(levels)))
        if self._policy._actor() != actor:
            runtime.throw(self._policy.DENIED_MESSAGE, runtime.PermissionError)
        return tuple(graph)

    def _applied(self):
        supplied = self._metadata(self._policy._scope, (self.childtype,))
        if type(supplied) is not dict or set(supplied) != {self.childtype}:
            raise CalculationChildAccessError("calculation_child_access_metadata_scope")
        applied = _declaration(supplied[self.childtype])
        if applied.name != self.childtype:
            raise CalculationChildAccessError("calculation_child_access_metadata_scope")
        return applied

    def require_metadata_unchanged(self):
        if self._applied() != self.applied:
            raise CalculationChildAccessError("calculation_child_access_metadata_drift")
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        """Every table the SQL parent will read must be authorized BEFORE SQL."""
        root = metadata[0]
        if root.name != self._doctype or tuple(name for name in TABLE_FIELDS if root.has_field(name)) != tuple(name for name, _ in self._tables):
            raise CalculationChildAccessError("calculation_child_access_metadata_graph")
        metas = {meta.name: meta for meta in metadata}
        levels = {dt: dict(fields) for dt, fields in self._fields}
        for dt, fields in self._fields:
            names = HEADER_FIELDS if dt == self._doctype else TABLE_FIELDS[next(name for name, _ in self._tables if _child_type(self._doctype, name) == dt)]
            if any(metas[dt].has_field(name) != (dict(fields)[name] is not None) for name in names):
                raise CalculationChildAccessError("calculation_child_access_metadata_fields")
        if any(self.applied.has_field(name) != (levels[self.childtype][name] is not None) for name in ("currency", "company")):
            raise CalculationChildAccessError("calculation_child_access_metadata_fields")
        self.recheck_access()

    def load_for_update(self, connection, financial):
        _require_graph_match(self.tables, financial)
        self.reader = MariaDBChildCurrencyReader(connection)
        result = self.reader.load_for_update(financial, self.parentfield, applied_metadata=self.applied)
        _require_native_match(self.rows, result)
        self.recheck_access()
        return result


@dataclass(frozen=True, repr=False)
class SavedChildCalculationRead:
    """Protected saved-READ child/financial/default binding, not full authority."""

    financial: object = field(repr=False)
    child: LockedChildCurrencyRead = field(repr=False)
    tables: tuple = field(repr=False)
    sources: tuple = field(init=False, repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            child = _pin_read(self.child)
            if child.financial != financial.financial or financial != self.financial:
                raise ValueError
            tables = _pin_tables(self.tables)
            _require_graph_match(tables, child.financial)
            rows = dict(tables)[child.parentfield]
            _require_native_match(rows, child)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationChildAccessError("calculation_child_access_result")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "child", child)
        object.__setattr__(self, "tables", tables)
        object.__setattr__(self, "sources", rows)

    def resolve_currency(self, row_name, fieldname):
        """No caller-supplied Company proof substitutes for related saved READ."""
        pinned = SavedChildCalculationRead(self.financial, self.child, self.tables)
        if pinned != self:
            raise CalculationChildAccessError("calculation_child_access_result")
        return pinned.child.resolve_currency(row_name, fieldname)

    def resolve_precision(self, row_name, fieldname, *, currency_context=None):
        """Pure precision composition; supplied formats are not acquired proofs."""
        return self.resolve_currency(row_name, fieldname).resolve_precision(
            self.financial.context.settings.defaults, currency_context=currency_context)

    def require_field_currency_match(self, row_name, fieldname, *, row_entry=ABSENT, parent_entry=ABSENT):
        """Compare explicit tagged slots; no actual cache provider is installed."""
        self.resolve_currency(row_name, fieldname).require_cached_match(row_entry=row_entry, parent_entry=parent_entry)

    def __repr__(self):
        return "<SavedChildCalculationRead protected PARTIAL saved child data, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_child_access_not_serializable")
