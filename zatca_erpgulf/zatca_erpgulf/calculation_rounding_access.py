"""Compose rounding READ/native/cache evidence on the shared owned service.

No second ACL engine, transaction, cleanup or display pipeline. Explicit method
overrides skip the unused related setting completely. No runtime registration.
"""

from dataclasses import dataclass, field

from .archive_source_access import SavedSourceRow
from .calculation_format_access import CalculationFormatAccessError, _RelatedFormatPolicy
from .calculation_child_format_access import require_field_read
from .calculation_rounding import _select_method, _text
from .financial_source_observation import _canonical, _scalar
from .rounding_setting_source import MariaDBRoundingSettingReader, LockedRoundingSettingRead, _meta, _pin_read


class RoundingSourceRow(SavedSourceRow):
    """One normal Singleton READ; no fabricated modified timestamp."""

    @classmethod
    def from_document(cls, doc):
        if (doc.doctype, doc.name) != ("System Settings", "System Settings"):
            raise ValueError
        value = doc.get("rounding_method")
        _text(value)
        return cls("System Settings", "System Settings", None, ("rounding_method",), (value,))


class _RoundingPolicy(_RelatedFormatPolicy):
    ROW_TYPE = RoundingSourceRow


def _definition(df):
    if df is None or df.fieldtype != "Select":
        raise ValueError
    return _canonical([_scalar(df.fieldtype), _scalar(df.options), _scalar(df.get("default"))])


class RoundingAcquisition:
    """Related record/field READ precedes all trusted metadata/cache/SQL calls."""

    def __init__(self, policy, actor, metadata_reader, cache_reader, override):
        _select_method(None, override)  # Validate even when the setting is skipped.
        self.override, self.rows, self.reader = override, (), None
        self._policy, self._actor = policy, actor
        self.active = not bool(override)
        if not self.active:
            return
        if not callable(metadata_reader) or not callable(cache_reader):
            raise CalculationFormatAccessError("calculation_rounding_dependencies")
        self._metadata, self._cache = metadata_reader, cache_reader
        related = _RoundingPolicy(policy)
        self._load, finalize = related._saved_record_access(actor)
        self._runtime = policy._dependencies()[0]
        doc = self._load("System Settings", "System Settings")
        self.definition, self.level = self._field(doc)
        _select_method(doc.get("rounding_method"), None)
        self.rows, _, self._recheck = finalize()
        self.recheck_access()

    def _field(self, doc):
        definition = _definition(doc.meta.get_field("rounding_method"))
        level = require_field_read(doc, "rounding_method", self._actor, self._runtime, self._policy.DENIED_MESSAGE)
        return definition, level

    def recheck_access(self):
        if not self.active:
            return
        self._recheck()
        if self._field(self._load("System Settings", "System Settings")) != (self.definition, self.level):
            raise CalculationFormatAccessError("calculation_rounding_field_drift")

    def _applied(self):
        supplied = self._metadata(self._policy._scope, ("System Settings",))
        if type(supplied) is not dict or set(supplied) != {"System Settings"}:
            raise ValueError
        applied = _meta(supplied["System Settings"])
        if _definition(applied.get_field("rounding_method")) != self.definition:
            raise ValueError
        return applied

    def prepare_metadata(self):
        if self.active:
            self.applied = self._applied()
            self.recheck_access()

    def load_for_update(self, connection):
        if not self.active:
            return None
        self.reader = MariaDBRoundingSettingReader(connection)
        return self.reader.load_for_update(applied_metadata=self.applied)

    def check_cache(self, observed):
        if not self.active:
            return
        observed = _pin_read(observed)
        if self.rows[0].values != (observed.value,):
            raise CalculationFormatAccessError("calculation_rounding_native_mismatch")
        cached = self._cache(self._policy._scope)
        _text(cached)
        if cached != observed.value:
            raise CalculationFormatAccessError("calculation_rounding_cache_mismatch")
        self.recheck_access()

    def require_metadata_unchanged(self):
        if not self.active:
            return
        if self._applied() != self.applied:
            raise CalculationFormatAccessError("calculation_rounding_metadata_drift")
        self.recheck_access()

    def require_unchanged(self, observed):
        if not self.active:
            return
        self.reader.require_unchanged(observed)
        self.recheck_access()


@dataclass(frozen=True, repr=False)
class SavedRoundingContext:
    """Protected invoice-context/default/rounding binding, not amount authority."""

    context: object = field(repr=False)
    erp_major: int
    override: str | None = field(default=None, repr=False)
    rounding: LockedRoundingSettingRead | None = field(default=None, repr=False)
    related: tuple = field(default=(), repr=False)
    method: str = field(init=False)
    origin: str = field(init=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationContextRead
            if type(self.context) is not SavedCalculationContextRead or type(self.erp_major) is not int or self.erp_major not in (15, 16):
                raise ValueError
            context = SavedCalculationContextRead(self.context.settings, self.context.metadata)
            if context != self.context or context.settings.defaults.parent != "__default" or type(self.related) is not tuple:
                raise ValueError
            rounding = None if self.rounding is None else _pin_read(self.rounding)
            if self.override:
                if rounding is not None or self.related:
                    raise ValueError
                method, origin = _select_method(None, self.override)
            else:
                if rounding is None or len(self.related) != 1:
                    raise ValueError
                row = self.related[0]
                if (type(row) is not RoundingSourceRow or (row.doctype, row.name, row.revision, row.fields, row.values)
                        != ("System Settings", "System Settings", None, ("rounding_method",), (rounding.value,))):
                    raise ValueError
                method, origin = _select_method(rounding.value, self.override)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_rounding_result")
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "rounding", rounding)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "origin", origin)

    def __repr__(self):
        return "<SavedRoundingContext protected PARTIAL saved sources, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_rounding_not_serializable")
