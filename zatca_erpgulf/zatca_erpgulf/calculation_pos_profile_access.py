"""Permissioned consumed POS lookups on the existing owned calculation service.

Authorize the saved financial graph, profile, table, children and consumed field
levels before metadata/SQL callbacks. Preserve initial objects alongside fresh
access checks. Do not read ORM amount/default values in place of native SQL.
No second transaction/display owner, cache, writer, runtime binding or transport.
"""

from dataclasses import dataclass, field
import json
from types import SimpleNamespace

from .archive_source_access import SavedSourceRow, _revision
from .calculation_child_access import FinancialGraphAccess, _SavedTableAccess, _pin_tables, _require_graph_match
from .calculation_child_format_access import require_field_read, link_definition
from .calculation_format_access import _RelatedFormatPolicy, CalculationFormatAccessError
from .financial_source_observation import _name, _validate_scalar
from .pos_profile_source import (
    MAX_PAYMENTS, LockedPosProfileRead, MariaDBPosProfileReader, _metas, _pin_read,
)
from .source_metadata import POS_LIMIT_PROFILE, POS_DEFAULT_PROFILE, PROFILE_FIELDS, project_source_metadata

CHILD_FIELDS = ("parent", "parenttype", "parentfield", "idx")


@dataclass(frozen=True, repr=False)
class PosProfileRequest:
    """Internal enum selection; validation stays inside the localized boundary."""
    kind: str = field(repr=False)

    def __repr__(self):
        return "<PosProfileRequest explicit consumed lookup>"

    def __reduce__(self):
        raise TypeError("pos_profile_request_not_serializable")


class PosProfileAccessRow(SavedSourceRow):
    """Related master identity/revision; no ORM limit or default-row values."""

    @classmethod
    def from_document(cls, doc):
        if type(doc.doctype) is not str or doc.doctype != "POS Profile":
            raise ValueError
        return cls("POS Profile", _name(doc.name), _revision(doc.get("modified")), (), ())


class PosPaymentAccessRow(SavedSourceRow):
    """Child ownership/revision only; payment values remain native observations."""

    @classmethod
    def from_document(cls, doc):
        if type(doc.doctype) is not str or doc.doctype != "POS Payment Method":
            raise ValueError
        values = tuple(doc.get(name) for name in CHILD_FIELDS)
        parent, parenttype, parentfield, idx = values
        if ((parenttype, parentfield) != ("POS Profile", "payments")
                or type(idx) is not int or not 1 <= idx <= MAX_PAYMENTS):
            raise ValueError
        _name(parent)
        revision = doc.get("modified")
        return cls(doc.doctype, _name(doc.name), None if revision is None else _revision(revision), CHILD_FIELDS, values)


class _PosProfilePolicy(_RelatedFormatPolicy):
    ROW_TYPE = PosProfileAccessRow


class _PosPaymentPolicy(_RelatedFormatPolicy):
    ROW_TYPE = PosPaymentAccessRow


def _child_type(doctype, parentfield):
    if (doctype, parentfield) != ("POS Profile", "payments"):
        raise ValueError
    return "POS Payment Method"


class _PosTableAccess(_SavedTableAccess):
    ROW_TYPE = PosPaymentAccessRow
    CHILD_POLICY = _PosPaymentPolicy
    CHILD_TYPE = staticmethod(_child_type)
    MAX_ROWS = MAX_PAYMENTS


def _require_related(master, payments, lookup):
    """Match normal saved identities to the exact consumed native records."""
    body = json.loads(lookup._payload)
    if (type(master) is not PosProfileAccessRow or type(master.doctype) is not str
            or type(master.fields) is not tuple or master.fields
            or type(master.values) is not tuple or master.values
            or master != PosProfileAccessRow("POS Profile", _name(master.name), _revision(master.revision), (), ())
            or master.name != lookup.profile_name
            or master.revision != _revision(_validate_scalar(body["record"]["modified"]))
            or type(payments) is not tuple or len(payments) != len(body["payments"])):
        raise ValueError
    pinned = []
    for saved, native in zip(payments, body["payments"]):
        if (type(saved) is not PosPaymentAccessRow or type(saved.fields) is not tuple
                or saved.fields != CHILD_FIELDS or type(saved.values) is not tuple):
            raise ValueError
        values = dict(zip(saved.fields, saved.values), modified=saved.revision)
        row = PosPaymentAccessRow.from_document(SimpleNamespace(doctype=saved.doctype, name=saved.name, get=values.get))
        revision = _validate_scalar(native["modified"])
        expected_revision = None if revision is None else _revision(revision)
        if (row != saved or row.name != native["name"] or row.revision != expected_revision
                or row.values != tuple(native[name] for name in CHILD_FIELDS)):
            raise ValueError
        pinned.append(row)
    return master, tuple(pinned)


class PosProfileAcquisition(FinancialGraphAccess):
    """Reuse the shared saved READ/table/field engines before any callback."""

    def __init__(self, policy, actor, invoice_name, doctype, request, metadata_reader, *, _shared_graph=None):
        if (type(request) is not PosProfileRequest or type(request.kind) is not str
                or request.kind not in ("limit", "default") or not callable(metadata_reader)):
            raise CalculationFormatAccessError("calculation_pos_profile_dependencies")
        self.kind, self._metadata, self._actor = request.kind, metadata_reader, actor
        self.profile = POS_LIMIT_PROFILE if self.kind == "limit" else POS_DEFAULT_PROFILE
        super().__init__(policy, actor, invoice_name, doctype, _shared_graph=_shared_graph)
        self.document = self._parent_load(doctype, invoice_name) if _shared_graph is None else _shared_graph.document
        self.owner = policy.ROW_TYPE.from_document(self.document)
        self.root_state = self._root_state(self.document)
        self.profile_name = self.root_state[-1]
        related = _PosProfilePolicy(policy)
        self._load_profile, finalize = related._saved_record_access(actor)
        self.profile_document = self._load_profile("POS Profile", self.profile_name)
        self.master_state = self._master_state(self.profile_document)
        self.related, _, self._related_recheck = finalize()
        self.payment_access = None
        self.payment_state = None
        if self.kind == "default":
            self.payment_access = _PosTableAccess(related, actor, self.profile_name, "POS Profile", "payments")
            self.payment_state = self._payment_state(self.profile_document)
        self._definitions()  # Validate normal metadata after all normal READ.
        self.recheck_access()

    def _root_state(self, doc):
        if self._policy.ROW_TYPE.from_document(doc) != self.owner:
            raise ValueError
        links = tuple(link_definition(doc, name, target) for name, target in
                      (("company", "Company"), ("pos_profile", "POS Profile")))
        levels = tuple(require_field_read(doc, name, self._actor, self._policy._dependencies()[0],
                       self._policy.DENIED_MESSAGE) for name in ("company", "pos_profile"))
        return links, levels, _name(doc.get("company")), _name(doc.get("pos_profile"))

    def _master_state(self, doc):
        if (doc.doctype, doc.name, doc.meta.name) != ("POS Profile", self.profile_name, "POS Profile"):
            raise ValueError
        fields = PROFILE_FIELDS[self.profile]["POS Profile"]
        meta = project_source_metadata(doc.meta, base_fields={}, profile=self.profile)
        levels = tuple(require_field_read(doc, name, self._actor, self._policy._dependencies()[0],
                       self._policy.DENIED_MESSAGE) for name in fields)
        company = _name(doc.get("company"))
        if company != self.root_state[-2]:
            raise ValueError
        return meta, levels, company

    def _payment_state(self, parent, *, meta=None):
        runtime = self._policy._dependencies()[0]
        meta = runtime.get_meta("POS Payment Method") if meta is None else meta
        if meta.name != "POS Payment Method":
            raise ValueError
        applied = project_source_metadata(meta, base_fields={}, profile=self.profile)
        # This works for empty tables too; do not fabricate a saved child row.
        view = SimpleNamespace(meta=meta)
        levels = tuple(require_field_read(view, name, self._actor, runtime,
                       self._policy.DENIED_MESSAGE, permission_parent=parent)
                       for name in PROFILE_FIELDS[self.profile]["POS Payment Method"])
        return applied, levels

    def _definitions(self):
        supplied = {"POS Profile": self.master_state[0]}
        if self.kind == "default":
            supplied["POS Payment Method"] = self.payment_state[0]
        return _metas(self.kind, supplied)

    def recheck_access(self):
        super().recheck_access()
        if (self._root_state(self.document) != self.root_state
                or self._root_state(self._parent_load(self._doctype, self._name)) != self.root_state):
            raise ValueError
        self._related_recheck()
        fresh = self._load_profile("POS Profile", self.profile_name)
        if self._master_state(self.profile_document) != self.master_state or self._master_state(fresh) != self.master_state:
            raise ValueError
        if self.payment_access is not None:
            access = self.payment_access
            access.recheck_access()
            table, refs = access._membership(self.profile_document)
            if (table != access._table or tuple(PosPaymentAccessRow.from_document(ref) for ref in refs) != access.rows
                    or any(tuple(PosPaymentAccessRow.from_document(doc) for doc in group) != access.rows
                           for group in (access.references, access.documents))
                    or self._payment_state(self.profile_document) != self.payment_state
                    or self._payment_state(fresh) != self.payment_state):
                raise ValueError
            # A fresh global Meta/record must not hide a stale original child's
            # own metadata. Check references, original saved rows and fresh rows
            # against the same selected definitions and parent field levels.
            current = tuple(access._load(access.childtype, row.name) for row in access.rows)
            for group in (access.references, access.documents, current):
                if any(self._payment_state(self.profile_document, meta=doc.meta) != self.payment_state for doc in group):
                    raise ValueError

    def _applied(self):
        expected = self._definitions()
        supplied = self._metadata(self._policy._scope, self.kind, tuple(sorted(expected)))
        if _metas(self.kind, supplied) != expected:
            raise ValueError
        return expected

    def prepare_metadata(self):
        self.applied = self._applied()
        self.recheck_access()

    def require_financial_metadata(self, metadata):
        super().require_financial_metadata(metadata)
        if tuple(metadata[0].get_field(name) for name in ("company", "pos_profile")) != self.root_state[0]:
            raise ValueError

    def load_for_update(self, connection, financial):
        _require_graph_match(self.tables, financial)
        self.reader = MariaDBPosProfileReader(connection)
        observed = self.reader.load_for_update(financial, kind=self.kind, applied_metadata=self.applied)
        self.check_getters(observed)
        return observed

    @property
    def payments(self):
        return () if self.payment_access is None else self.payment_access.rows

    def check_getters(self, observed):
        observed = _pin_read(observed)
        _require_related(self.related[0], self.payments, observed)
        if observed.kind != self.kind or observed.profile_name != self.profile_name:
            raise ValueError
        self.recheck_access()

    def complete_defaults(self, connection, observed, defaults, company_metadata):
        # The enclosing pipeline already binds defaults/Company; there is no
        # POS amount rounding/cache step to add or second reader to construct.
        return _pin_read(observed)

    def require_metadata_unchanged(self):
        if self._applied() != self.applied:
            raise ValueError
        self.recheck_access()

    def require_unchanged(self, observed):
        self.reader.require_unchanged(observed)
        self.recheck_access()

    def build_result(self, financial, observed):
        return SavedPosProfileContext(financial, observed, self.tables, self.related[0], self.payments, id(self.document))


@dataclass(frozen=True, repr=False)
class SavedPosProfileContext:
    """Protected ephemeral READ binding, not a complete POS calculation grant."""

    financial: object = field(repr=False)
    lookup: LockedPosProfileRead = field(repr=False)
    tables: tuple = field(repr=False)
    master: PosProfileAccessRow = field(repr=False)
    payments: tuple = field(repr=False)
    owner_document: int = field(repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            lookup = _pin_read(self.lookup)
            if (financial != self.financial or financial.financial != lookup.financial
                    or financial.context.settings.defaults.parent != "__default"
                    or type(self.owner_document) is not int or not 0 < self.owner_document < 2**64):
                raise ValueError
            master, payments = _require_related(self.master, self.payments, lookup)
            tables = _pin_tables(self.tables)
            _require_graph_match(tables, lookup.financial)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_pos_profile_result")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "lookup", lookup)
        object.__setattr__(self, "master", master)
        object.__setattr__(self, "payments", payments)
        object.__setattr__(self, "tables", tables)

    def pin(self):
        pinned = SavedPosProfileContext(self.financial, self.lookup, self.tables, self.master, self.payments, self.owner_document)
        if pinned != self:
            raise CalculationFormatAccessError("calculation_pos_profile_result")
        return pinned

    def __repr__(self):
        return "<SavedPosProfileContext protected PARTIAL inspection, NOT account eligibility>"

    def __reduce__(self):
        raise TypeError("calculation_pos_profile_not_serializable")
