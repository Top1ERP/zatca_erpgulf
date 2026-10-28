"""Declared Frappe rounding-method selection, separate from fiscal rounding.

Reuse the existing settings observation without changing its bytes. This pure
policy selects a method only: no amounts, Decimal/float conversion, SQL, cache
lookup, framework defaults, source discovery, writes or runtime registration.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .calculation_settings_observation import CalculationSettingsObservation
from .financial_source_observation import _canonical, _validate_scalar

METHODS = frozenset(("Banker's Rounding", "Banker's Rounding (legacy)", "Commercial Rounding"))
LEGACY_METHOD = "Banker's Rounding (legacy)"


class RoundingMethodError(ValueError):
    """Static English codes; never disclose source or rejected setting values."""


def _text(value):
    if value is not None and (type(value) is not str or len(value.encode("utf-8")) > 4096 or "\0" in value):
        raise ValueError


def _select_method(raw, override):
    """Shared declared/native selection; never discover or normalize a value."""
    _text(override)
    if override:
        method, origin = override, "EXPLICIT_OVERRIDE"
    else:
        _text(raw)
        method, origin = (raw, "SYSTEM_SETTING") if raw else (LEGACY_METHOD, "LEGACY_DEFAULT")
    if method not in METHODS:
        raise ValueError
    return method, origin


@dataclass(frozen=True, repr=False)
class RoundingMethodResolution:
    """Method from explicit supplied settings, NOT authorized effective source.

    An override wins; otherwise use System Settings, then the legacy fallback.
    The declared ERP version and original scalar presence remain source-bound.
    A missing setting declaration does not prove missing tabSingles storage or
    exclude document defaults. Authorized native/cache acquisition remains open.
    """

    settings: CalculationSettingsObservation = field(repr=False)
    override: str | None = field(default=None, repr=False)
    erp_major: int = field(init=False)
    method: str = field(init=False)
    origin: str = field(init=False)
    uses_system_setting: bool = field(init=False)
    system_setting: tuple = field(init=False, repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            if type(self.settings) is not CalculationSettingsObservation:
                raise ValueError
            settings = CalculationSettingsObservation(self.settings.settings, self.settings._payload)
            if settings != self.settings:
                raise ValueError
            _text(self.override)
            system = next(record for record in json.loads(settings._payload)["records"]
                if record["doctype"] == "System Settings")
            encoded = dict(system["header"])["rounding_method"]
            raw = _validate_scalar(encoded, absent=True)
            method, origin = _select_method(raw, self.override)
            major = settings.settings.financial.erp_major
            payload = _canonical(dict(profile="declared-rounding-method/v1", erp_major=major,
                settings_sha256=settings.sha256, override=self.override, method=method, origin=origin))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundingMethodError("calculation_rounding_method")
        object.__setattr__(self, "settings", settings)
        object.__setattr__(self, "erp_major", major)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "uses_system_setting", not bool(self.override))
        object.__setattr__(self, "system_setting", tuple(encoded))
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-declared-rounding-method/v1\0" + payload).hexdigest())

    def require_system_cache_match(self, cached):
        """Compare an explicit cache/API projection only when actually consumed.

        Never read/populate a cache. An override leaves its unused cache value
        unexamined and uncertified. NULL/absent decode to API None; blank remains
        blank. Equal selected methods alone do not prove equal source values.
        """
        try:
            pinned = RoundingMethodResolution(self.settings, self.override)
            if pinned != self:
                raise ValueError
            if pinned.uses_system_setting:
                _text(cached)
                if cached != _validate_scalar(list(pinned.system_setting), absent=True):
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundingMethodError("calculation_rounding_cache_mismatch")

    def __repr__(self):
        return "<RoundingMethodResolution protected supplied settings, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_rounding_not_serializable")
