"""Saved/native plain party-link resolution for direct advance precision.

Reuse the existing parent-party, optional-child and format readers on the same
owned graph/handle. A child party link is not its transaction currency. No
parent_doc substitution, cache population, transaction ownership or writes.
"""

from dataclasses import dataclass, field
import json
from types import SimpleNamespace

from .advance_party_source import MariaDBAdvancePartyReader, pin_advance_party
from .calculation_owner_currency_access import OwnerCurrencyAcquisition
from .calculation_child_format_access import require_field_read
from .calculation_child_cache import observe_child_cache_slots
from .calculation_field_rounding_access import _cache_slot, _require_cache
from .calculation_format_access import FormatAcquisition, _require_related_match
from .currency_format_source import _pin_read as pin_formats
from .owner_currency_source import pin_owner_currency
from .child_field_currency import ABSENT, ChildCurrencyInputs, _resolve, _text, require_currency_cache
from .financial_source_observation import _scalar
from .source_metadata import ADVANCE_PARTY_PROFILE, project_source_metadata, _pin_metadata

PARTY = "party_account_currency"
AMOUNT = "allocated_amount"
CHILD = "Sales Invoice Advance"


class AdvancePartyError(ValueError):
    """Static English diagnostics, without selected link or monetary values."""


def _resolved(native, parent, name):
    row = next(row for row in json.loads(native._payload)["rows"] if row[0] == name)
    tagged = tuple(dict(row[3])[PARTY])
    financial = native.financial.financial
    # Plain-link options use the same framework algorithm as `currency`.
    # Here those generic inputs are bound to PARTY columns, never currency.
    inputs = ChildCurrencyInputs(CHILD, name, financial.doctype, financial.name, "advances",
        tagged, ABSENT, parent is not None, ABSENT if parent is None else ("str", parent.currency))
    currency, origin, owner = _resolve("currency", inputs, financial.erp_major)
    return inputs, currency, None if owner is None else (CHILD, owner)


@dataclass(frozen=True, repr=False)
class SavedAdvancePartyRead:
    """Protected same-source party formats/caches, NOT executed ORM proof."""
    financial: object = field(repr=False)
    native: object = field(repr=False)
    parent: object = field(repr=False)
    samples: tuple = field(repr=False)
    formats: tuple = field(repr=False)
    resolutions: tuple = field(init=False, repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationFinancialRead
            if type(self.financial) is not SavedCalculationFinancialRead:
                raise ValueError
            financial = SavedCalculationFinancialRead(self.financial.context, self.financial.financial)
            native = pin_advance_party(self.native)
            parent = None if self.parent is None else pin_owner_currency(self.parent)
            if native.financial != financial.financial or native.financial.financial.erp_major != 16:
                raise ValueError
            rows = json.loads(native._payload)["rows"]
            uses_parent = any(not _text(tuple(dict(row[3])[PARTY])) for row in rows)
            if (parent is not None) != uses_parent:
                raise ValueError
            if parent is not None:
                root = native.financial.financial
                root_meta = next(meta for meta in native.financial.metadata if meta.applied.name == root.doctype)
                if (parent.name != root.name or parent.metadata.applied.name != root.doctype
                        or parent.revision != financial.context.settings.sources[1].revision
                        or json.loads(parent.metadata._payload)["doctype"] != json.loads(root_meta._payload)["doctype"]):
                    raise ValueError
            if (type(self.samples) is not tuple or type(self.formats) is not tuple
                    or len(self.samples) != len(rows) or len(self.formats) != len(rows)):
                raise ValueError
            resolutions = []
            for row, sample, selected in zip(rows, self.samples, self.formats):
                if type(sample) is not tuple or len(sample) != 4:
                    raise ValueError
                containers, documents, currencies, precisions = sample
                if (type(containers) is not tuple or len(containers) != 7
                        or type(documents) is not tuple or len(documents) != 2
                        or any(type(value) is not int or not 0 < value < 2**64 for value in documents)
                        or type(currencies) is not tuple or len(currencies) != 2
                        or type(precisions) is not tuple or len(precisions) != 2
                        or type(selected) is not tuple or len(selected) != 3 or selected[0] != row[0]):
                    raise ValueError
                formats = pin_formats(selected[1])
                _require_related_match(selected[2], formats)
                inputs, currency, key = _resolved(native, parent, row[0])
                if formats.currency != currency:
                    raise ValueError
                for index in (0, 1):
                    _cache_slot(((containers[0], containers[index + 1]), currencies[index]), allow_null=True)
                require_currency_cache(currency, key, inputs, *currencies)
                precision = financial.resolve_precision(CHILD, AMOUNT, currency_context=formats.context)
                definition = next(meta.applied for meta in native.financial.metadata if meta.applied.name == CHILD).get_field(AMOUNT)
                if definition.options != PARTY or type(precision.precision) is not int:
                    raise ValueError
                _require_cache((containers[3:5], precisions[0]), precision)
                _require_cache((containers[5:7], precisions[1]), precision)
                resolutions.append((row[0], precision))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise AdvancePartyError("advance_party_result")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "native", native)
        object.__setattr__(self, "parent", parent)
        object.__setattr__(self, "resolutions", tuple(resolutions))

    def pin(self):
        pinned = SavedAdvancePartyRead(self.financial, self.native, self.parent, self.samples, self.formats)
        if pinned != self:
            raise AdvancePartyError("advance_party_result")
        return pinned

    def __repr__(self):
        return "<SavedAdvancePartyRead protected saved/native party context, NOT execution proof>"

    def __reduce__(self):
        raise TypeError("advance_party_not_serializable")


class AdvancePartySelection:
    """Small format-policy selection with an explicitly authorized currency."""
    def __init__(self, group, row):
        self.group, self.row = group, row
        self.children = SimpleNamespace(_tables=group.root._tables, parentfield="advances",
            childtype=CHILD, _name=group.root._name)
        self.fieldname, self._runtime = AMOUNT, group.runtime
        own = dict(group.values)[row.name]
        self.currency = _text(own) or (None if group.parent is None else group.parent.currency)

    def recheck_access(self):
        self.group.recheck_access()


class AdvancePartyAcquisition:
    """Authorize all saved party links before any new metadata provider."""
    def __init__(self, root, actor, metadata, owner_metadata, format_metadata, format_cache):
        if not callable(metadata):
            raise AdvancePartyError("advance_party_dependencies")
        self.root, self.actor, self._metadata = root, actor, metadata
        self.runtime = root._policy._dependencies()[0]
        self.definition, self.level, self.values = self._observe()
        self.parent = None
        if any(not _text(value) for name, value in self.values):
            self.parent = OwnerCurrencyAcquisition(root, actor, owner_metadata)
        self.selections = tuple(AdvancePartySelection(self, row) for row in dict(root.tables)["advances"])
        self.samples = tuple(observe_child_cache_slots(row) for row in self.selections)
        pool = {}
        self.formats = []
        for selected in self.selections:
            if selected.currency not in pool:
                pool[selected.currency] = FormatAcquisition(root._policy, actor, root._name, root._doctype,
                    format_metadata, format_cache, currency_scope="child", child_source=selected, _defer_metadata=True)
            self.formats.append(pool[selected.currency])
        self.unique_formats = tuple(pool.values())
        self.captured = {}
        self.recheck_access()

    def _observe(self):
        meta = project_source_metadata(self.runtime.get_meta(CHILD), base_fields={}, profile=ADVANCE_PARTY_PROFILE)
        definition = meta.get_field(PARTY)
        if definition is not None and (definition.fieldtype != "Link" or definition.options != "Currency"):
            raise AdvancePartyError("advance_party_definition")
        level = None
        if definition is not None:
            level = require_field_read(self.root._parent_load(self.root._doctype, self.root._name),
                "advances", self.actor, self.runtime, self.root._policy.DENIED_MESSAGE)
            meta_view = SimpleNamespace(get_field=self.runtime.get_meta(CHILD).get_field,
                get_permlevel_access=self.root.document.meta.get_permlevel_access)
            field_level = require_field_read(SimpleNamespace(meta=meta_view), PARTY, self.actor,
                self.runtime, self.root._policy.DENIED_MESSAGE)
            level = level, field_level
        access = dict(self.root._tables)["advances"]
        fresh_refs = self.root._parent_load(self.root._doctype, self.root._name).get("advances")
        values = []
        for row, direct, ref, fresh_ref in zip(access.rows, access.documents, access.references, fresh_refs):
            value = tuple(_scalar(direct.get(PARTY)))
            _text(value)
            fresh = access._load(CHILD, row.name)
            if (any(tuple(_scalar(doc.get(PARTY))) != value for doc in (ref, fresh, fresh_ref))
                    or definition is None and value != ("null",)):
                raise AdvancePartyError("advance_party_getters")
            values.append((row.name, ABSENT if definition is None else value))
        return meta, level, tuple(values)

    def recheck_access(self):
        self.root.recheck_access()
        if self._observe() != (self.definition, self.level, self.values):
            raise AdvancePartyError("advance_party_getter_changed")
        if self.parent is not None:
            self.parent.recheck_access()

    def load(self, connection, financial):
        supplied = self._metadata(self.root._policy._scope, (CHILD,))
        if type(supplied) is not dict or set(supplied) != {CHILD} or _pin_metadata(supplied[CHILD]) != self.definition:
            raise AdvancePartyError("advance_party_metadata")
        if self.parent is not None:
            self.parent.prepare_metadata()
            self.parent.load_for_update(connection, financial)
        self.reader = MariaDBAdvancePartyReader(connection)
        self.native = self.reader.load_for_update(financial, "advances", applied_metadata=self.definition)
        if tuple((row[0], tuple(dict(row[3])[PARTY])) for row in json.loads(self.native._payload)["rows"]) != self.values:
            raise AdvancePartyError("advance_party_native_getter")
        for source in self.unique_formats:
            source.prepare_metadata()
            source.require_financial_currency(financial.financial)
            self.captured[id(source)] = source.load_for_update(connection)
        self.check()

    def check(self):
        self.recheck_access()
        if tuple(observe_child_cache_slots(row) for row in self.selections) != self.samples:
            raise AdvancePartyError("advance_party_cache_changed")
        for source in self.unique_formats:
            source.check_cache(self.captured[id(source)])

    def require_metadata_unchanged(self):
        supplied = self._metadata(self.root._policy._scope, (CHILD,))
        if type(supplied) is not dict or set(supplied) != {CHILD} or supplied[CHILD] != self.definition:
            raise AdvancePartyError("advance_party_metadata_changed")
        if self.parent is not None:
            self.parent.require_metadata_unchanged()
        for source in self.unique_formats:
            source.require_metadata_unchanged()
        self.check()

    def require_unchanged(self):
        self.reader.require_unchanged(self.native)
        if self.parent is not None:
            self.parent.require_unchanged()
        for source in self.unique_formats:
            source.reader.require_unchanged(self.captured[id(source)])
        self.check()

    def build_result(self, financial):
        return SavedAdvancePartyRead(financial, self.native, None if self.parent is None else self.parent.native,
            self.samples, tuple((row.row.name, self.captured[id(source)], source.rows)
                for row, source in zip(self.selections, self.formats)))
