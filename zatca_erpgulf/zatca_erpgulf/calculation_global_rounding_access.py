"""Permissioned single-value Check inspection on the shared owned service.

Normal Singleton READ proves access and pins the field definition/level, not the
effective value: an in-memory document default can differ from get_single_value.
No second ACL/SQL/cleanup/UI engine, invoice decision or runtime registration.
"""

from dataclasses import dataclass, field

from .archive_source_access import SavedSourceRow
from .calculation_format_access import CalculationFormatAccessError, _RelatedFormatPolicy
from .calculation_rounding_access import _SingletonSettingAcquisition
from .global_rounding_source import (
    DOCTYPE, FIELD, LockedGlobalRoundingRead, MariaDBGlobalRoundingReader, _meta, _pin_read,
)


class GlobalRoundingAccessRow(SavedSourceRow):
    """Identity-only normal READ; never project a document-default Check value."""

    @classmethod
    def from_document(cls, doc):
        if (doc.doctype, doc.name) != (DOCTYPE, DOCTYPE):
            raise ValueError
        return cls(DOCTYPE, DOCTYPE, None, (), ())


class _GlobalRoundingPolicy(_RelatedFormatPolicy):
    ROW_TYPE = GlobalRoundingAccessRow


class GlobalRoundingAcquisition(_SingletonSettingAcquisition):
    """Fixed Global Check inspection, not automatic invoice-source selection."""

    DOCTYPE, FIELD, FIELDTYPE = DOCTYPE, FIELD, "Check"
    POLICY, READER = _GlobalRoundingPolicy, MariaDBGlobalRoundingReader
    PIN_META, PIN_READ = staticmethod(_meta), staticmethod(_pin_read)
    ERROR_PREFIX = "calculation_global_rounding"

    def __init__(self, policy, actor, metadata_reader, cache_reader):
        super().__init__(policy, actor, metadata_reader, cache_reader)

    def _validate_document(self, doc):
        # Access/metadata only. Never coerce or substitute this document value.
        pass

    def _require_saved_match(self, observed):
        # The normal document is not a get_single_value value/cache projection.
        pass

    def _require_cache_match(self, observed, cached):
        observed.require_cache_match(cached)


@dataclass(frozen=True, repr=False)
class SavedGlobalRoundingContext:
    """Partial protected inspection; no active invoice branch or amount result."""

    context: object = field(repr=False)
    erp_major: int
    global_rounding: LockedGlobalRoundingRead = field(repr=False)
    related: tuple = field(repr=False)

    def __post_init__(self):
        try:
            from .calculation_defaults_access import SavedCalculationContextRead
            if (type(self.context) is not SavedCalculationContextRead or type(self.erp_major) is not int
                    or self.erp_major not in (15, 16) or type(self.related) is not tuple or len(self.related) != 1):
                raise ValueError
            context = SavedCalculationContextRead(self.context.settings, self.context.metadata)
            if context != self.context or context.settings.defaults.parent != "__default":
                raise ValueError
            native = _pin_read(self.global_rounding)
            row = self.related[0]
            if (type(row) is not GlobalRoundingAccessRow or (row.doctype, row.name, row.revision, row.fields, row.values)
                    != (DOCTYPE, DOCTYPE, None, (), ())):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationFormatAccessError("calculation_global_rounding_result")
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "global_rounding", native)

    def __repr__(self):
        return "<SavedGlobalRoundingContext protected PARTIAL inspection, NOT invoice policy>"

    def __reduce__(self):
        raise TypeError("calculation_global_rounding_not_serializable")
