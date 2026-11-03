"""Co-owned root/advance precision acquisition, without running a controller.

Reuse the numeric graph, direct-child link/Company/format policies and root
rounding stage. Only consumed v16 row formats are acquired. No second parent
capture, transaction, cache population, write, RPC or authority request.
The standard party_account_currency option uses distinct native row/parent
sources when v16 defaults are unset; never substitute invoice currency.
"""

from dataclasses import dataclass, field
import json

from .calculation_rounding_stage import (
    RoundingStageAcquisition, RoundingStageRequest, SavedRoundingStageRead, pin_stage,
)
from .calculation_child_access import ChildAcquisition, SavedChildCalculationRead
from .calculation_child_format_access import ChildFieldAcquisition, SavedChildFieldRead
from .calculation_child_cache import (
    SavedChildCacheRead, observe_child_cache_slots, _precision,
)
from .calculation_field_rounding_access import _require_cache
from .calculation_format_access import FormatAcquisition
from .calculation_precision import NUMERIC_TYPES, _requires_currency_format
from .calculation_defaults import _fold
from .calculation_advance_party import SavedAdvancePartyRead, AdvancePartyAcquisition

FIELD = "allocated_amount"


class AdvanceRoundingError(ValueError):
    """Static English codes, without financial/cache/provider values."""


@dataclass(frozen=True)
class AdvanceRoundingRequest:
    """Internal fixed selection; no caller-selected table, row or provider."""


def _rows(stage):
    native = stage.numeric.view.financial
    table = dict(json.loads(native.financial._payload)["tables"])["advances"]
    if type(table) is not dict:
        raise ValueError
    return tuple(row[0] for row in table["rows"])


def _needs_formats(stage):
    native = stage.numeric.view.financial
    meta = next(row.applied for row in native.metadata if row.applied.name == "Sales Invoice Advance")
    defaults = stage.numeric.financial.context.settings.defaults
    return bool(_rows(stage)) and _requires_currency_format(
        meta.get_field(FIELD), _fold(json.loads(defaults._payload)["rows"]), stage.method.erp_major,
    )


@dataclass(frozen=True, repr=False)
class SavedAdvanceRoundingRead:
    """Same-owned row precision/cache evidence, NOT active controller proof."""

    stage: SavedRoundingStageRead = field(repr=False)
    caches: tuple = field(repr=False)
    fields: tuple = field(repr=False)
    party: SavedAdvancePartyRead | None = field(default=None, repr=False)
    row_precisions: tuple = field(init=False, repr=False)

    def __post_init__(self):
        try:
            stage = pin_stage(self.stage)
            native = stage.numeric.view.financial
            if (stage.targets != (("header", native.financial.name, "total_advance"),)
                    or stage.do_not_round_fields is not None
                    or type(self.caches) is not tuple or type(self.fields) is not tuple):
                raise ValueError
            names = _rows(stage)
            if len(self.caches) != len(names):
                raise ValueError
            needs_formats = _needs_formats(stage)
            party = self.party
            if party is not None:
                if type(party) is not SavedAdvancePartyRead or not needs_formats:
                    raise ValueError
                party = party.pin()
                if party.financial != stage.numeric.financial or len(party.samples) != len(names):
                    raise ValueError
            if len(self.fields) != (len(names) if needs_formats and party is None else 0):
                raise ValueError
            # Every row uses the same metadata/site defaults on this branch.
            # Resolve once, while checking each original cache independently.
            shared_precision = None
            if names and not needs_formats:
                shared_precision = stage.numeric.financial.resolve_precision("Sales Invoice Advance", FIELD)
            resolutions = []
            for index, (name, cache) in enumerate(zip(names, self.caches)):
                if (type(cache) is not tuple or len(cache) != 4 or type(cache[0]) is not str or cache[0] != name
                        or type(cache[1]) is not tuple or len(cache[1]) != 2
                        or any(type(value) is not int or not 0 < value < 2**64 for value in cache[1])):
                    raise ValueError
                if party is not None:
                    sample = party.samples[index]
                    if (sample[1] != cache[1] or sample[3] != (cache[2][1], cache[3][1])
                            or sample[0][3:5] != cache[2][0] or sample[0][5:7] != cache[3][0]
                            or party.resolutions[index][0] != name):
                        raise ValueError
                    precision = party.resolutions[index][1]
                elif needs_formats:
                    observed = self.fields[index]
                    if type(observed) is not SavedChildCacheRead:
                        raise ValueError
                    observed = observed._pin()
                    selected = observed.field
                    if (selected.row_name != name or selected.fieldname != FIELD
                            or selected.parent.child.parentfield != "advances"
                            or selected.parent.financial != stage.numeric.financial
                            or selected.parent.tables != stage.numeric.tables
                            or observed.documents != cache[1]
                            or observed.precisions != (cache[2][1], cache[3][1])
                            or observed.containers[3:5] != cache[2][0]
                            or observed.containers[5:7] != cache[3][0]):
                        raise ValueError
                    precision = observed.resolve_precision()
                else:
                    precision = shared_precision
                if type(precision.precision) is not int:
                    raise ValueError
                _require_cache(cache[2], precision)
                _require_cache(cache[3], precision)
                resolutions.append((name, precision.precision))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise AdvanceRoundingError("advance_rounding_result")
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "party", party)
        object.__setattr__(self, "row_precisions", tuple(resolutions))

    def pin(self):
        pinned = SavedAdvanceRoundingRead(self.stage, self.caches, self.fields, self.party)
        if pinned != self or type(self.row_precisions) is not tuple or any(
            type(value) is not tuple or len(value) != 2 or type(value[0]) is not str
            or type(value[1]) is not int or value != expected
            for value, expected in zip(self.row_precisions, pinned.row_precisions)
        ) or len(self.row_precisions) != len(pinned.row_precisions):
            raise AdvanceRoundingError("advance_rounding_result")
        return pinned

    def __repr__(self):
        return "<SavedAdvanceRoundingRead protected row/root context, NOT execution proof>"

    def __reduce__(self):
        raise TypeError("advance_rounding_not_serializable")


class AdvanceRoundingAcquisition(RoundingStageAcquisition):
    """One graph/handle for the header stage and every consumed direct row."""

    def __init__(self, policy, actor, invoice_name, doctype, major, *, child_metadata, party_metadata=None, **dependencies):
        self.party = None
        self.children = None
        self.child_fields = ()
        self.row_formats = ()
        self.slot_samples = ()
        self.precision_samples = None
        self._child_metadata = child_metadata
        self._party_metadata = party_metadata
        self._owner_metadata = dependencies.get("owner_metadata")
        self._format_metadata = dependencies.get("format_metadata")
        self._format_cache = dependencies.get("format_cache")
        self._actor = actor
        super().__init__(policy, actor, invoice_name, doctype,
            RoundingStageRequest(("total_advance",)), major, **dependencies)
        if "advances" not in dict(self.root.tables):
            raise AdvanceRoundingError("advance_rounding_table")
        definition = dict(dict(self.root.schema)["Sales Invoice Advance"]).get(FIELD)
        if definition is None or definition.fieldtype not in NUMERIC_TYPES:
            raise AdvanceRoundingError("advance_rounding_numeric_field")
        self.precision_samples = self._precision_samples()
        self.recheck_access()

    def _precision_samples(self):
        access = dict(self.root._tables)["advances"]
        return tuple(
            (row.name, (id(direct), id(reference)), _precision(direct, FIELD), _precision(reference, FIELD))
            for row, direct, reference in zip(access.rows, access.documents, access.references)
        )

    def recheck_access(self):
        super().recheck_access()
        if self.precision_samples is not None and self._precision_samples() != self.precision_samples:
            raise AdvanceRoundingError("advance_rounding_precision_cache_changed")
        if self.children is not None:
            self.children.recheck_access()
        for selected in self.child_fields:
            selected.recheck_access()
        if self.slot_samples and tuple(observe_child_cache_slots(row) for row in self.child_fields) != self.slot_samples:
            raise AdvanceRoundingError("advance_rounding_currency_cache_changed")
        for source, observed in self._unique_formats():
            source.recheck_access()
        if self.party is not None:
            self.party.recheck_access()

    def _unique_formats(self):
        return tuple({id(source): (source, observed) for source, observed in self.row_formats}.values())

    def complete_defaults(self, connection, observed, defaults, company_metadata):
        view, method, prior = observed
        if prior or self.children is not None or self.party is not None:
            raise AdvanceRoundingError("advance_rounding_already_completed")
        native = view.financial
        meta = next(row.applied for row in native.metadata if row.applied.name == "Sales Invoice Advance")
        needed = bool(self.precision_samples) and _requires_currency_format(
            meta.get_field(FIELD), _fold(json.loads(defaults._payload)["rows"]), native.financial.erp_major,
        )
        if needed:
            if meta.get_field(FIELD).options == "party_account_currency":
                self.party = AdvancePartyAcquisition(self.root, self._actor, self._party_metadata,
                    self._owner_metadata, self._format_metadata, self._format_cache)
                self.party.load(connection, native)
                result = super().complete_defaults(connection, observed, defaults, company_metadata)
                self.party.check()
                return result
            self.children = ChildAcquisition(self.root._policy, self._actor, self.root._name,
                self.root._doctype, "advances", self._child_metadata, defer_metadata=True, _shared_graph=self.root)
            self.child_fields = tuple(ChildFieldAcquisition(self.children, self.root._policy, self._actor,
                row.name, FIELD) for row in self.children.rows)
            # Observe ALL consumed slots before any metadata/format callback
            # can warm another row or the root stage's existing currency cache.
            self.slot_samples = tuple(observe_child_cache_slots(row) for row in self.child_fields)
            pool, formats = {}, []
            for selected in self.child_fields:
                key = selected.currency
                if key not in pool:
                    pool[key] = FormatAcquisition(self.root._policy, self._actor, self.root._name,
                        self.root._doctype, self.fields[0]._format_metadata, self.fields[0]._format_cache,
                        currency_scope="child", child_source=selected, _defer_metadata=True)
                formats.append((pool[key], None))
            self.row_formats = tuple(formats)
            # All related READ/field levels are now checked. No child/format
            # metadata provider has run before the last row's authorization.
            self.children.prepare_metadata()
            self.children.require_financial_metadata(tuple(row.applied for row in native.metadata))
            applied = (company_metadata.applied, *(row.applied for row in native.metadata))
            for selected in self.child_fields:
                selected.require_financial_metadata(applied)
            self.native_children = self.children.load_for_update(connection, native)
            for selected in self.child_fields:
                selected.load_for_update(connection, company_metadata, self.native_children)
            # Same-currency rows share one format source. Their own links and
            # Company evidence still retain separate access/source rechecks.
            captured_formats = {}
            for source in pool.values():
                source.prepare_metadata()
                source.require_financial_currency(native.financial)
                captured = source.load_for_update(connection)
                source.check_cache(captured)
                captured_formats[id(source)] = captured
            self.row_formats = tuple((source, captured_formats[id(source)]) for source, unused in self.row_formats)
            self.recheck_access()
        result = super().complete_defaults(connection, observed, defaults, company_metadata)
        self.recheck_access()
        return result

    def check_getters(self, observed):
        super().check_getters(observed)
        for source, formats in self._unique_formats():
            source.check_cache(formats)
        self.recheck_access()
        if self.party is not None:
            self.party.check()

    def require_metadata_unchanged(self):
        super().require_metadata_unchanged()
        if self.children is not None:
            self.children.require_metadata_unchanged()
        for source, formats in self._unique_formats():
            source.require_metadata_unchanged()
        self.recheck_access()
        if self.party is not None:
            self.party.require_metadata_unchanged()

    def require_unchanged(self, observed):
        super().require_unchanged(observed)
        if self.children is not None:
            self.children.reader.require_unchanged(self.native_children)
            for selected in self.child_fields:
                selected.require_unchanged()
        for source, formats in self._unique_formats():
            source.reader.require_unchanged(formats)
        self.recheck_access()
        if self.party is not None:
            self.party.require_unchanged()

    def build_result(self, financial, observed):
        stage = super().build_result(financial, observed)
        fields = ()
        if self.children is not None:
            parent = SavedChildCalculationRead(financial, self.native_children, self.tables)
            fields = tuple(
                SavedChildCacheRead(SavedChildFieldRead(parent, selected.row.name, FIELD,
                    selected.company_source, selected.company_rows, formats, source.rows), *slots)
                for selected, (source, formats), slots in zip(self.child_fields, self.row_formats, self.slot_samples)
            )
        return SavedAdvanceRoundingRead(stage, self.precision_samples, fields,
            None if self.party is None else self.party.build_result(financial))
