"""Read selected request-local field/precision caches without populating them.

No Document.precision/get_field_currency call, callback/provider installation,
SQL, cleanup, source write or authority I/O. Only the exact initial authorized
direct child and parent-child objects are sampled, never a new document lookup.
"""

from dataclasses import dataclass, field as hidden_field
import hashlib

from .calculation_child_access import CalculationChildAccessError
from .calculation_child_format_access import SavedChildFieldRead
from .child_field_currency import ABSENT
from .financial_source_observation import _canonical, _scalar, _validate_scalar

_MISSING = object()


def _state(value, *, nullable=False):
    if value is _MISSING:
        return ABSENT
    if value is None and nullable:
        return ("null",)
    if not isinstance(value, dict):
        raise CalculationChildAccessError("calculation_child_cache_container")
    return ("dict", id(value))


def _bucket(mapping, key):
    return dict.__getitem__(mapping, key) if dict.__contains__(mapping, key) else _MISSING


def _slot(mapping, key):
    if mapping is _MISSING:
        return ABSENT
    _state(mapping)
    return tuple(_scalar(dict.__getitem__(mapping, key))) if dict.__contains__(mapping, key) else ABSENT


def _precision(doc, fieldname):
    cache = vars(doc).get("_precision", _MISSING)
    state = _state(cache)
    main = _MISSING if cache is _MISSING else _bucket(cache, "main")
    return (state, _state(main)), _slot(main, fieldname)


@dataclass(frozen=True, repr=False)
class SavedChildCacheRead:
    """Protected scoped cache observation, not durable/committed provenance."""

    field: SavedChildFieldRead = hidden_field(repr=False)
    containers: tuple = hidden_field(repr=False)
    documents: tuple = hidden_field(repr=False)
    currencies: tuple = hidden_field(repr=False)
    precisions: tuple = hidden_field(repr=False)
    sha256: str = hidden_field(init=False)

    def __post_init__(self):
        try:
            if type(self.field) is not SavedChildFieldRead:
                raise ValueError
            original = self.field
            pinned = SavedChildFieldRead(original.parent, original.row_name, original.fieldname,
                original.company, original.company_rows, original.formats, original.related)
            if pinned != original:
                raise ValueError
            if (type(self.containers) is not tuple or len(self.containers) != 7
                    or type(self.documents) is not tuple or len(self.documents) != 2
                    or any(type(value) is not int or not 0 < value < 2**64 for value in self.documents)
                    or type(self.currencies) is not tuple or len(self.currencies) != 2
                    or type(self.precisions) is not tuple or len(self.precisions) != 2):
                raise ValueError
            for index, state in enumerate(self.containers):
                if type(state) is not tuple:
                    raise ValueError
                if state == ABSENT or index == 0 and state == ("null",):
                    continue
                if len(state) != 2 or state[0] != "dict" or type(state[1]) is not int or not 0 < state[1] < 2**64:
                    raise ValueError
            if self.containers[0][0] != "dict" and self.containers[1:3] != (ABSENT, ABSENT):
                raise ValueError
            for state, slot in zip(self.containers[1:3], self.currencies):
                if state == ABSENT and slot != ABSENT:
                    raise ValueError
            for start, slot in ((3, self.precisions[0]), (5, self.precisions[1])):
                if self.containers[start] == ABSENT and self.containers[start + 1] != ABSENT:
                    raise ValueError
                if self.containers[start + 1] == ABSENT and slot != ABSENT:
                    raise ValueError
            resolved = pinned.resolve_currency()
            resolved.require_cached_match(row_entry=self.currencies[0], parent_entry=self.currencies[1])
            precision = resolved.resolve_precision(pinned.parent.financial.context.settings.defaults,
                currency_context=None if pinned.formats is None else pinned.formats.context)
            for slot in self.precisions:
                if type(slot) is not tuple:
                    raise ValueError
                if slot != ABSENT:
                    precision.require_cached_match(_validate_scalar(list(slot)))
            settings = pinned.parent.financial.context.settings
            invoice = pinned.parent.child.financial.financial
            payload = _canonical(dict(profile="saved-child-field-cache/v1",
                key=[settings.scope.site, settings.scope.storage_namespace, settings.actor, invoice.doctype,
                    invoice.name, pinned.parent.child.parentfield, resolved.inputs.doctype, pinned.row_name, pinned.fieldname, invoice.erp_major],
                sources=[pinned.parent.child.financial.sha256, pinned.parent.child.sha256,
                    settings.defaults.sha256, None if pinned.company is None else pinned.company.sha256,
                    None if pinned.formats is None else pinned.formats.sha256],
                containers=self.containers, documents=self.documents,
                currencies=self.currencies, precisions=self.precisions))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationChildAccessError("calculation_child_cache_observation")
        object.__setattr__(self, "field", pinned)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-saved-child-field-cache/v1\0" + payload).hexdigest())

    def resolve_currency(self):
        return self._pin().field.resolve_currency()

    def resolve_precision(self):
        return self._pin().field.resolve_precision()

    def _pin(self):
        pinned = SavedChildCacheRead(self.field, self.containers, self.documents, self.currencies, self.precisions)
        if pinned != self:
            raise CalculationChildAccessError("calculation_child_cache_observation")
        return pinned

    def __repr__(self):
        return "<SavedChildCacheRead protected local cache observation, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_child_cache_not_serializable")


def observe_child_caches(field_result, selection):
    """Snapshot only the selected slots of the exact authorized input objects.

    Built-in dict operations avoid overridden mapping lookups. No cache key,
    bucket, field or document cache is created, removed or refreshed here.
    """
    access = dict(selection.children._tables)[selection.children.parentfield]
    index = next(index for index, row in enumerate(access.rows) if row.name == selection.row.name)
    direct, reference = access.documents[index], access.references[index]
    local = selection._runtime.local
    cache = getattr(local, "field_currency", _MISSING)
    global_state = _state(cache, nullable=True)
    if cache is _MISSING or cache is None:
        row = parent = _MISSING
    else:
        dt = selection.children.childtype
        row = _bucket(cache, (dt, selection.row.name))
        parent = _bucket(cache, (dt, selection.children._name))
    currency_states = (_state(row), _state(parent))
    currency_slots = (_slot(row, selection.fieldname), _slot(parent, selection.fieldname))
    direct_states, direct_slot = _precision(direct, selection.fieldname)
    reference_states, reference_slot = _precision(reference, selection.fieldname)
    return SavedChildCacheRead(field_result, (global_state, *currency_states, *direct_states, *reference_states),
        (id(direct), id(reference)), currency_slots, (direct_slot, reference_slot))
