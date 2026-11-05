"""Saved outstanding controls and exact return/internal entry decisions.

No rounding settings, controller execution, master-party lookup or source write.
Invoice snapshots certify only the fields the primary controller actually uses.
"""
from dataclasses import dataclass, field
import json

from .calculation_child_access import FinancialGraphAccess, _pin_tables, _require_graph_match
from .calculation_child_format_access import require_field_read
from .outstanding_guard_source import LockedOutstandingGuardsRead, MariaDBOutstandingGuardsReader, pin_outstanding_guards
from .source_metadata import OUTSTANDING_GUARDS_PROFILE, project_source_metadata, _pin_metadata
from .invoice_rounding_source import _meta
from .financial_source_observation import _scalar, _validate_scalar, _name
from .calculation_field_rounding_access import _result_tag

FIELDS = LockedOutstandingGuardsRead.FIELDS
CHECKS = LockedOutstandingGuardsRead.CHECKS
LINKS = LockedOutstandingGuardsRead.LINKS


class OutstandingGuardError(ValueError):
    """Static English codes, without private links, settings or amounts."""


@dataclass(frozen=True)
class OutstandingGuardRequest:
    """Internal saved inspection selection, not an issuance command."""


def _require_values(native, values):
    if (type(values) is not tuple or len(values) != len(FIELDS)
            or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                or row[0] != name or type(row[1]) is not tuple for row, name in zip(values, FIELDS))):
        raise ValueError
    saved = dict(values)
    native.require_saved_check_match({name: _validate_scalar(list(saved[name])) for name in CHECKS})
    fields = dict(json.loads(native._payload)["fields"])
    for name, _ in LINKS:
        tag = list(saved[name])
        value = _validate_scalar(tag)
        if value is not None and type(value) is not str:
            raise ValueError
        if fields[name] != tag and not (fields[name] == ["absent"] and tag == ["null"]):
            raise ValueError


class OutstandingGuardControlsAccess:
    """Compose on a pre-authorized graph; the enclosing service owns SQL."""

    def __init__(self, root, actor, metadata_reader):
        if not callable(metadata_reader):
            raise OutstandingGuardError("outstanding_guard_dependencies")
        self.root, self.actor, self._metadata = root, actor, metadata_reader
        self.definition, self.levels, self.values = self._observe(root.document)
        self.recheck_access()

    def _observe(self, doc):
        if self.root._policy.ROW_TYPE.from_document(doc) != self.root.owner:
            raise OutstandingGuardError("outstanding_guard_owner")
        meta = _meta(project_source_metadata(doc.meta, base_fields={}, profile=OUTSTANDING_GUARDS_PROFILE),
            profile=OUTSTANDING_GUARDS_PROFILE, fields=FIELDS, checks=CHECKS, links=LINKS)
        if meta.name != self.root._doctype:
            raise OutstandingGuardError("outstanding_guard_metadata_identity")
        levels = tuple(require_field_read(doc, name, self.actor, self.root._policy._dependencies()[0],
            self.root._policy.DENIED_MESSAGE) if meta.has_field(name) else None for name in FIELDS)
        values = tuple((name, tuple(_scalar(doc.get(name)))) for name in FIELDS)
        for name, tag in values:
            value = _validate_scalar(list(tag))
            if not meta.has_field(name) and value is not None:
                raise OutstandingGuardError("outstanding_guard_absent_getter")
            if name in CHECKS and value is not None and (type(value) is not int or value not in (0, 1)):
                raise OutstandingGuardError("outstanding_guard_check_getter")
            if name not in CHECKS and value is not None and type(value) is not str:
                raise OutstandingGuardError("outstanding_guard_link_getter")
        return meta, levels, values

    def recheck_access(self):
        self.root.recheck_access()
        expected = self.definition, self.levels, self.values
        if (self._observe(self.root.document) != expected
                or self._observe(self.root._parent_load(self.root._doctype, self.root._name)) != expected):
            raise OutstandingGuardError("outstanding_guard_getter_changed")

    def _applied(self):
        supplied = self._metadata(self.root._policy._scope, (self.root._doctype,))
        if type(supplied) is not dict or set(supplied) != {self.root._doctype} or _pin_metadata(supplied[self.root._doctype]) != self.definition:
            raise OutstandingGuardError("outstanding_guard_metadata")
        return self.definition

    def prepare_metadata(self):
        self._applied()
        self.recheck_access()

    def load_for_update(self, connection, financial):
        self.reader = MariaDBOutstandingGuardsReader(connection)
        self.native = self.reader.load_for_update(financial, applied_metadata=self.definition)
        self.check_getters()

    def check_getters(self):
        _require_values(self.native, self.values)
        self.recheck_access()

    def require_metadata_unchanged(self):
        self._applied()
        self.recheck_access()

    def require_unchanged(self):
        self.reader.require_unchanged(self.native)
        self.check_getters()

    def build_result(self, financial, tables):
        return SavedOutstandingGuardRead(financial, self.native, tables, self.values, id(self.root.document))


@dataclass(frozen=True, repr=False)
class SavedOutstandingGuardRead:
    financial: object = field(repr=False)
    controls: LockedOutstandingGuardsRead = field(repr=False)
    tables: tuple = field(repr=False)
    values: tuple = field(repr=False)
    owner_document: int = field(repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            native = pin_outstanding_guards(self.controls)
            tables = _pin_tables(self.tables)
            if (financial != self.financial or financial.financial != native.financial
                    or financial.context.settings.defaults.parent != "__default"
                    or type(self.owner_document) is not int or not 0 < self.owner_document < 2**64):
                raise ValueError
            _require_graph_match(tables, native.financial)
            _require_values(native, self.values)
        except Exception:
            raise OutstandingGuardError("outstanding_guard_context") from None
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "controls", native)
        object.__setattr__(self, "tables", tables)

    def pin(self):
        pinned = SavedOutstandingGuardRead(self.financial, self.controls, self.tables, self.values, self.owner_document)
        if pinned != self:
            raise OutstandingGuardError("outstanding_guard_context")
        return pinned

    def __repr__(self):
        return "<SavedOutstandingGuardRead protected invoice controls, NOT complete settlement>"

    def __reduce__(self):
        raise TypeError("outstanding_guard_not_serializable")


class OutstandingGuardAcquisition:
    """Inspect guards without numeric-fix, rounding-setting or cache reads."""

    def __init__(self, policy, actor, invoice_name, doctype, *, metadata_reader):
        self.root = FinancialGraphAccess(policy, actor, invoice_name, doctype)
        self.root.document = self.root._parent_load(doctype, invoice_name)
        self.root.owner = policy.ROW_TYPE.from_document(self.root.document)
        self.tables = self.root.tables
        self.controls = OutstandingGuardControlsAccess(self.root, actor, metadata_reader)

    def recheck_access(self):self.controls.recheck_access()
    def prepare_metadata(self):self.controls.prepare_metadata()
    def require_financial_metadata(self, metadata):self.root.require_financial_metadata(metadata)

    def load_for_update(self, connection, financial):
        _require_graph_match(self.tables, financial)
        self.controls.load_for_update(connection, financial)
        return self.controls.native

    def check_getters(self, observed):
        if pin_outstanding_guards(observed) != self.controls.native:
            raise OutstandingGuardError("outstanding_guard_observation")
        self.controls.check_getters()

    def complete_defaults(self, connection, observed, defaults, company_metadata):
        # This extension consumes no rounding/format dependency. Keep the
        # enclosing service's common stage lifecycle without opening a reader.
        self.check_getters(observed)
        return observed

    def require_metadata_unchanged(self):self.controls.require_metadata_unchanged()

    def require_unchanged(self, observed):
        self.check_getters(observed)
        self.controls.require_unchanged()

    def build_result(self, financial, observed):
        self.check_getters(observed)
        return self.controls.build_result(financial, self.tables)


@dataclass(frozen=True, repr=False)
class OutstandingGuardInputs:
    doctype: str
    company: str = field(repr=False)
    is_return: int | None = field(repr=False)
    is_pos: int | None = field(repr=False)
    return_against: str | None = field(repr=False)
    update_outstanding_for_self: int | None = field(repr=False)
    is_internal_customer: int | None = field(repr=False)
    represents_company: str | None = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.doctype) is not str or self.doctype not in ("Sales Invoice", "POS Invoice"):
                raise ValueError
            _name(self.company)
            for name in CHECKS:
                value = getattr(self, name)
                if value is not None and (type(value) is not int or value not in (0, 1)):
                    raise ValueError
            for name in ("return_against", "represents_company"):
                value = getattr(self, name)
                if value is not None and type(value) is not str:
                    raise ValueError
                _scalar(value)
        except Exception:
            raise OutstandingGuardError("outstanding_guard_inputs") from None

    def pin(self):
        result = OutstandingGuardInputs(self.doctype, **{name: getattr(self, name) for name in FIELDS})
        if result != self:
            raise OutstandingGuardError("outstanding_guard_inputs")
        return result

    def __repr__(self):return "<OutstandingGuardInputs supplied controls, NOT saved-source proof>"
    def __reduce__(self):raise TypeError("outstanding_guard_inputs_not_serializable")


@dataclass(frozen=True, repr=False)
class OutstandingGuardDecision:
    """Preserve the primary condition's short circuit and integer-zero reset."""
    inputs: OutstandingGuardInputs = field(repr=False)
    skip_balance: bool = field(init=False)
    calls: tuple = field(init=False, repr=False)

    def __post_init__(self):
        if type(self.inputs) is not OutstandingGuardInputs:
            raise OutstandingGuardError("outstanding_guard_decision")
        inputs = self.inputs.pin()
        calls = ["calculate_paid_amount"] if inputs.doctype == "Sales Invoice" else []
        excluded_return = bool(inputs.is_return and inputs.return_against and not inputs.update_outstanding_for_self and not inputs.is_pos)
        internal = False
        if not excluded_return:
            calls.append("is_internal_invoice")
            if inputs.doctype == "Sales Invoice":
                calls.append("is_internal_transfer")
                internal = bool(inputs.is_internal_customer and inputs.represents_company == inputs.company)
        skip = excluded_return or internal
        calls.append("reset_outstanding" if skip else "round_floats_in")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "skip_balance", skip)
        object.__setattr__(self, "calls", tuple(calls))

    @classmethod
    def from_saved(cls, source):
        if type(source) is not SavedOutstandingGuardRead:
            raise OutstandingGuardError("outstanding_guard_decision_source")
        source = source.pin()
        values = {name: _validate_scalar(list(tag)) for name, tag in source.values}
        return cls(OutstandingGuardInputs(source.controls.financial.financial.doctype, **values))

    def require_match(self, *, calls, reset, continues):
        try:
            pinned = OutstandingGuardDecision(self.inputs)
            if (pinned != self or type(self.skip_balance) is not bool or type(self.calls) is not tuple
                    or any(type(name) is not str for name in self.calls)
                    or type(calls) is not tuple or any(type(name) is not str for name in calls) or calls != pinned.calls
                    or type(continues) is not bool or continues != (not pinned.skip_balance)):
                raise ValueError
            if pinned.skip_balance:
                if type(reset) is not tuple or len(reset) != 2 or type(reset[0]) is not str or reset[0] != "outstanding_amount" or _result_tag(reset[1]) != ("int", "0"):
                    raise ValueError
            elif reset is not None:
                raise ValueError
        except Exception:
            raise OutstandingGuardError("outstanding_guard_observation") from None

    def __repr__(self):return "<OutstandingGuardDecision partial entry comparison, NOT issuance eligibility>"
    def __reduce__(self):raise TypeError("outstanding_guard_decision_not_serializable")
