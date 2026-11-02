"""Declared ERP rounded-total control flow, separate from amount calculation.

Select dependencies and versioned write plans from existing observations. Never
round/recalculate/write amounts, convert Decimal amounts to float, discover a
record/cache, or authorize XML/QR/submission. Runtime adoption is still staged.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
import math

from .calculation_settings_observation import CalculationSettingsObservation
from .calculation_rounding import _select_method
from .financial_source_observation import _canonical, _scalar, _validate_scalar

BASE_FIELDS = ("rounding_adjustment", "rounded_total")


class RoundedTotalControlError(ValueError):
    """Static English code, without source amounts or configuration values."""


def _check(encoded):
    value = _validate_scalar(encoded)
    if value is not None and not (type(value) is bool or type(value) is int and value in (0, 1)):
        raise ValueError
    return bool(value)


def _numeric(encoded):
    value = _validate_scalar(encoded)
    if value is not None and type(value) not in (Decimal, int, float):
        raise ValueError
    if ((type(value) is Decimal and not value.is_finite())
            or (type(value) is float and not math.isfinite(value))):
        raise ValueError
    return value


def _fraction_branch(encoded):
    """Classify normalized CONFIGURATION, using the shared scalar bounds.

    The existing contract bounds integer digits and Decimal digits/exponents;
    accepted positive values stay finite/nonzero under the framework's flt.
    Floats are already finite binary values. No amount cast or new range rule.
    """
    value = _numeric(encoded)
    if value is None or value == 0:
        return "WHOLE_UNIT_THEN_FIELD_PRECISION"
    if value < 0:
        raise ValueError
    return "CURRENCY_FRACTION_THEN_FIELD_PRECISION"


def _initial_branch(consolidated, adjustment, rounded_present):
    """Share the controller's short-circuit order without calculating money."""
    if consolidated and _numeric(adjustment):
        return "PRESERVE_CONSOLIDATED_ADJUSTMENT"
    if not rounded_present:
        return "NO_ROUNDED_TOTAL_FIELD"
    return None


def _disable_source(invoice_value, global_value=None):
    """Field presence wins over Global Defaults, including a false value."""
    origin = "INVOICE_FIELD"
    selected = invoice_value
    if selected == ["absent"]:
        selected, origin = global_value, "GLOBAL_DEFAULTS"
    return _check(selected), origin, tuple(selected)


def _disabled_fields(major):
    if major == 15:
        return ("rounded_total", "base_rounded_total", "rounding_adjustment"), ()
    return ("rounded_total", "rounding_adjustment"), BASE_FIELDS


@dataclass(frozen=True, repr=False)
class RoundedTotalControl:
    """Protected supplied control plan, NOT native/effective amount authority.

    is_consolidated is an explicit additional declaration: the old financial
    snapshot does not contain it. Absence must not silently mean False. Source
    acquisition/provenance and complete installed/controller parity stay open.
    """

    settings: CalculationSettingsObservation = field(repr=False)
    is_consolidated: bool = field(repr=False)
    erp_major: int = field(init=False)
    branch: str = field(init=False)
    disabled: bool | None = field(init=False)
    disable_origin: str | None = field(init=False)
    disable_value: tuple | None = field(init=False, repr=False)
    currency: str | None = field(init=False, repr=False)
    fraction_value: tuple | None = field(init=False, repr=False)
    method: str | None = field(init=False)
    method_origin: str | None = field(init=False)
    zero_fields: tuple = field(init=False)
    base_conversion_fields: tuple = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            if type(self.settings) is not CalculationSettingsObservation or type(self.is_consolidated) is not bool:
                raise ValueError
            settings = CalculationSettingsObservation(self.settings.settings, self.settings._payload)
            if settings != self.settings:
                raise ValueError
            financial = settings.settings.financial
            header = dict(json.loads(financial._payload)["header"])
            records = {(row["doctype"], row["name"]): dict(row["header"])
                for row in json.loads(settings._payload)["records"]}
            disabled = origin = disable_value = currency = fraction = method = method_origin = None
            zero_fields, base_fields = (), ()
            branch = _initial_branch(self.is_consolidated, header["rounding_adjustment"], header["rounded_total"] != ["absent"])
            if branch is None:
                selected = header["disable_rounded_total"]
                global_value = records["Global Defaults", "Global Defaults"]["disable_rounded_total"] if selected == ["absent"] else None
                disabled, origin, disable_value = _disable_source(selected, global_value)
                if disabled:
                    branch = "DISABLED"
                    zero_fields, base_fields = _disabled_fields(financial.erp_major)
                else:
                    currency = _validate_scalar(header["currency"])
                    selected = records["Currency", currency]["smallest_currency_fraction_value"]
                    branch, fraction = _fraction_branch(selected), tuple(selected)
                    # Even a nonzero fraction ends with flt(value, precision).
                    # Its rounding method remains a consumed System dependency.
                    raw = records["System Settings", "System Settings"]["rounding_method"]
                    method, method_origin = _select_method(_validate_scalar(raw, absent=True), None)
                    base_fields = BASE_FIELDS
            body = dict(profile="declared-rounded-total-control/v1", settings_sha256=settings.sha256,
                erp_major=financial.erp_major, is_consolidated=self.is_consolidated, branch=branch,
                disabled=disabled, disable_origin=origin, disable_value=disable_value, currency=currency,
                fraction_value=fraction, method=method, method_origin=method_origin,
                zero_fields=zero_fields, base_conversion_fields=base_fields)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundedTotalControlError("rounded_total_control")
        object.__setattr__(self, "settings", settings)
        for key, value in body.items():
            if key not in ("profile", "settings_sha256", "is_consolidated"):
                object.__setattr__(self, key, value)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-rounded-total-control/v1\0" + _canonical(body)).hexdigest())

    def require_disable_cache_match(self, cached):
        """Compare a supplied consumed API projection; never fetch/repair caches."""
        try:
            pinned = RoundedTotalControl(self.settings, self.is_consolidated)
            if pinned != self:
                raise ValueError
            if pinned.disable_value is not None:
                encoded = _scalar(cached)
                _check(encoded)
                if tuple(encoded) != pinned.disable_value:
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundedTotalControlError("rounded_total_disable_cache_mismatch")

    def __repr__(self):
        return "<RoundedTotalControl protected supplied plan, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("rounded_total_control_not_serializable")
