"""Shared saved write-off acquisition and side-field precision resolution.

The enclosing calculation service owns SQL, metadata ordering and cleanup.
No controller, cache population, source write or authority I/O occurs here.
"""
import json

from .calculation_owner_currency_access import OwnerCurrencyAcquisition
from .calculation_child_format_access import require_field_read
from .calculation_child_cache import _precision, _MISSING, _state, _bucket, _slot
from .calculation_field_rounding_access import _require_cache, _cache_slot
from .calculation_precision import FieldPrecisionResolution, _requires_currency_format
from .calculation_defaults import _fold
from .source_metadata import WRITE_OFF_PROFILE, project_source_metadata, _pin_metadata
from .write_off_source import LockedWriteOffRead, MariaDBWriteOffReader
from .invoice_rounding_source import _meta
from .financial_source_observation import _scalar, _validate_scalar

AUTO = "write_off_outstanding_amount_automatically"
WRITE_FIELDS = ("write_off_amount", "base_write_off_amount")


class WriteOffAccessError(ValueError):
    """Static English codes without protected values or driver detail."""


def currency_cache(root, fieldname):
    mapping = getattr(root._policy._dependencies()[0].local, "field_currency", _MISSING)
    state = _state(mapping, nullable=True)
    bucket = _MISSING if mapping is _MISSING or mapping is None else _bucket(mapping, (root._doctype, root._name))
    return (state, _state(bucket)), _slot(bucket, fieldname)


def resolve_write_precision(stage, write_off, fieldname, precision_cache, field_currency_cache):
    """Use an existing co-owned matching root format; never guess a currency."""
    definition = write_off.metadata.applied.get_field(fieldname)
    if fieldname not in WRITE_FIELDS or definition is None or definition.fieldtype != "Currency":
        raise WriteOffAccessError("write_off_precision_field")
    defaults = stage.numeric.financial.context.settings.defaults
    needs_format = _requires_currency_format(definition, _fold(json.loads(defaults._payload)["rows"]), stage.method.erp_major)
    context = None
    if needs_format:
        root_meta = next(row.applied for row in write_off.financial.metadata if row.applied.name == write_off.financial.financial.doctype)
        proof = next(value for value in stage.fields if value.formats is not None
            and root_meta.get_field(value.target[2]).options == definition.options)
        context = proof.formats.formats.context
        slot = _cache_slot(field_currency_cache, allow_null=True)
        if slot != ("absent",) and slot != ("str", context.currency):
            raise WriteOffAccessError("write_off_currency_cache")
    elif field_currency_cache is not None:
        raise WriteOffAccessError("write_off_unused_currency_cache")
    result = FieldPrecisionResolution(write_off.metadata.applied, fieldname, defaults, stage.method.erp_major, context)
    _require_cache(precision_cache, result)
    return result


class WriteOffInputsAcquisition:
    """Bind normal/native side fields and party currency to the existing root."""

    def __init__(self, root, actor, metadata_reader, owner_metadata, precision_fields):
        if not callable(metadata_reader):
            raise WriteOffAccessError("write_off_dependencies")
        self.root, self.actor, self._metadata = root, actor, metadata_reader
        self.owner = OwnerCurrencyAcquisition(root, actor, owner_metadata)
        self.currency = tuple(_scalar(root.document.get("currency")))
        self.foreign = self.owner.currency != root.document.get("currency")
        self.definition, self.levels, self.values = self._observe(root.document)
        if precision_fields == "foreign_base":
            precision_fields = (WRITE_FIELDS[1],) if self.foreign else ()
        if type(precision_fields) is not tuple or len(set(precision_fields)) != len(precision_fields) or any(name not in WRITE_FIELDS for name in precision_fields):
            raise WriteOffAccessError("write_off_precision_selection")
        self.precision_caches = tuple((name, _precision(root.document, name)) for name in precision_fields)
        self.currency_caches = None
        self.recheck_access()

    def _observe(self, doc):
        meta = _meta(project_source_metadata(doc.meta, base_fields={}, profile=WRITE_OFF_PROFILE),
            profile=WRITE_OFF_PROFILE, fields=LockedWriteOffRead.FIELDS, checks=LockedWriteOffRead.CHECKS)
        levels = tuple(require_field_read(doc, name, self.actor, self.root._policy._dependencies()[0],
            self.root._policy.DENIED_MESSAGE) if meta.has_field(name) else None for name in LockedWriteOffRead.FIELDS)
        values = tuple((name, tuple(_scalar(doc.get(name)))) for name in LockedWriteOffRead.FIELDS)
        if any(not meta.has_field(name) and tag != ("null",) for name, tag in values):
            raise WriteOffAccessError("write_off_absent_getter")
        return meta, levels, values

    def recheck_access(self):
        self.owner.recheck_access()
        expected = self.definition, self.levels, self.values
        for doc in (self.root.document, self.root._parent_load(self.root._doctype, self.root._name)):
            if tuple(_scalar(doc.get("currency"))) != self.currency or self._observe(doc) != expected:
                raise WriteOffAccessError("write_off_getter_changed")
        if any(_precision(self.root.document, name) != sample for name, sample in self.precision_caches):
            raise WriteOffAccessError("write_off_precision_changed")
        if self.currency_caches is not None and any(currency_cache(self.root, name) != sample
                for name, sample in self.currency_caches if sample is not None):
            raise WriteOffAccessError("write_off_currency_cache_changed")

    def _applied(self):
        supplied = self._metadata(self.root._policy._scope, (self.root._doctype,))
        if type(supplied) is not dict or set(supplied) != {self.root._doctype} or _pin_metadata(supplied[self.root._doctype]) != self.definition:
            raise WriteOffAccessError("write_off_metadata")
        return self.definition

    def prepare_metadata(self):
        self.owner.prepare_metadata()
        self._applied()
        self.recheck_access()

    def load_for_update(self, connection, financial):
        if dict(json.loads(financial.financial._payload)["header"])["currency"] != list(self.currency):
            raise WriteOffAccessError("write_off_native_currency")
        self.owner.load_for_update(connection, financial)
        self.reader = MariaDBWriteOffReader(connection)
        self.native = self.reader.load_for_update(financial, applied_metadata=self.definition)
        self.check_getters()

    def check_getters(self):
        values = dict(json.loads(self.native._payload)["fields"])
        for name, tag in self.values:
            if name == AUTO:
                self.native.require_saved_check_match({AUTO: _validate_scalar(list(tag))})
            elif values[name] != list(tag) and not (values[name] == ["absent"] and tag == ("null",)):
                raise WriteOffAccessError("write_off_native_getter")
        self.recheck_access()

    def observe_currency_caches(self, defaults, major):
        if self.currency_caches is not None:
            raise WriteOffAccessError("write_off_already_completed")
        folded = _fold(json.loads(defaults._payload)["rows"])
        self.currency_caches = tuple((name, currency_cache(self.root, name)
            if _requires_currency_format(self.definition.get_field(name), folded, major) else None)
            for name, _ in self.precision_caches)
        self.recheck_access()

    def require_metadata_unchanged(self):
        self.owner.require_metadata_unchanged()
        self._applied()
        self.recheck_access()

    def require_unchanged(self):
        self.owner.require_unchanged()
        self.reader.require_unchanged(self.native)
        self.check_getters()

    def precision_cache(self, name):
        return dict(self.precision_caches).get(name)

    def field_currency_cache(self, name):
        return dict(self.currency_caches or ()).get(name)


class WriteOffStageMixin:
    """Share lifecycle hooks with advance and receivable acquisition stages.

    Concrete stages set write_inputs=None BEFORE parent initialization, because
    the parent calls recheck_access(). Bind one helper afterwards. The enclosing
    owned service remains responsible for transaction setup, rollback and close.
    """

    def recheck_access(self):
        super().recheck_access()
        if self.write_inputs is not None:
            self.write_inputs.recheck_access()

    def prepare_metadata(self):
        super().prepare_metadata()
        self.write_inputs.prepare_metadata()
        self.recheck_access()

    def load_for_update(self, connection, financial):
        observed = super().load_for_update(connection, financial)
        self.write_inputs.load_for_update(connection, financial)
        return observed

    def complete_defaults(self, connection, observed, defaults, company_metadata):
        self.write_inputs.observe_currency_caches(defaults, observed[0].financial.financial.erp_major)
        return super().complete_defaults(connection, observed, defaults, company_metadata)

    def check_getters(self, observed):
        super().check_getters(observed)
        self.write_inputs.check_getters()

    def require_metadata_unchanged(self):
        super().require_metadata_unchanged()
        self.write_inputs.require_metadata_unchanged()
        self.recheck_access()

    def require_unchanged(self, observed):
        super().require_unchanged(observed)
        self.write_inputs.require_unchanged()
