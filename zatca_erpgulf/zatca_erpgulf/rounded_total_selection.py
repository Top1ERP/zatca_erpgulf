"""Native-bound consumed settings plan; no monetary calculation or source I/O.

The adjustment witness proves only the controller's truthiness guard, not money
equality, ORM normalization or accounting parity. Retain native originals and
the exact supplied getter tag separately. Unused dependencies are forbidden.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .financial_source_observation import _canonical, _scalar
from .invoice_rounding_source import LockedInvoiceRoundingRead, _pin_read as _pin_controls
from .global_rounding_source import LockedGlobalRoundingRead, _pin_read as _pin_global
from .currency_fraction_source import LockedCurrencyFractionRead, _pin_read as _pin_fraction
from .rounding_setting_source import LockedRoundingSettingRead, _pin_read as _pin_method
from .calculation_rounding import _select_method
from .rounded_total_control import _initial_branch, _disable_source, _disabled_fields, _numeric, BASE_FIELDS


class RoundingSelectionError(ValueError):
    """Static English code, without source amounts or configuration disclosure."""


def _requires_method(branch, major):
    # v16 converts disabled zero totals to base currency through precision-flt;
    # rounded() consults System Settings before even a zero's algorithm result.
    return branch is None or branch == "DISABLED" and bool(_disabled_fields(major)[1])


def _control_stage(controls, adjustment, global_rounding):
    """Reuse declared guard order with separately proved normalized Check APIs."""
    fields = dict(json.loads(controls._payload)["fields"])
    if controls.consolidated:
        if type(adjustment) is not tuple:
            raise ValueError
        getter = list(adjustment)
        normal = _numeric(getter)
        native = fields["rounding_adjustment"]
        # An absent field plus an observed None getter supplies the missing
        # witness; the older declaration-only plan still refuses bare absence.
        if native == ["absent"]:
            if getter != ["null"]:
                raise ValueError
            native = ["null"]
        if bool(normal) != bool(_numeric(native)) or _scalar(normal) != getter:
            raise ValueError
    else:
        if adjustment is not None:
            raise ValueError
        getter = None  # _initial_branch must not consume the unused getter.
    branch = _initial_branch(controls.consolidated, getter, controls.metadata.applied.has_field("rounded_total"))
    disabled = origin = None
    if branch is None:
        invoice = dict(controls.normalized_checks)["disable_rounded_total"]
        if controls.metadata.applied.has_field("disable_rounded_total"):
            if global_rounding is not None:
                raise ValueError
            selected, global_value = _scalar(invoice), None
        else:
            if type(global_rounding) is not LockedGlobalRoundingRead:
                raise ValueError
            selected, global_value = ["absent"], _scalar(global_rounding.value)
        disabled, origin, _ = _disable_source(selected, global_value)
        if disabled:
            branch = "DISABLED"
    elif global_rounding is not None:
        raise ValueError
    return branch, disabled, origin


@dataclass(frozen=True, repr=False)
class RoundingDependencyPlan:
    """Protected PARTIAL control/source plan, NOT normalized money or issuance."""

    controls: LockedInvoiceRoundingRead = field(repr=False)
    adjustment: tuple | None = field(repr=False)
    global_rounding: LockedGlobalRoundingRead | None = field(default=None, repr=False)
    fraction: LockedCurrencyFractionRead | None = field(default=None, repr=False)
    rounding: LockedRoundingSettingRead | None = field(default=None, repr=False)
    branch: str = field(init=False)
    disabled: bool | None = field(init=False)
    disable_origin: str | None = field(init=False)
    method: str | None = field(init=False)
    method_origin: str | None = field(init=False)
    zero_fields: tuple = field(init=False)
    base_conversion_fields: tuple = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            controls = _pin_controls(self.controls)
            global_rounding = None if self.global_rounding is None else _pin_global(self.global_rounding)
            fraction = None if self.fraction is None else _pin_fraction(self.fraction)
            rounding = None if self.rounding is None else _pin_method(self.rounding)
            branch, disabled, origin = _control_stage(controls, self.adjustment, global_rounding)
            needs_method = _requires_method(branch, controls.financial.financial.erp_major)
            method = method_origin = None
            zero_fields = base_fields = ()
            if branch is None:
                if fraction is None or fraction.financial != controls.financial:
                    raise ValueError
                branch = fraction.branch
                base_fields = BASE_FIELDS
            else:
                if fraction is not None:
                    raise ValueError
                if branch == "DISABLED":
                    zero_fields, base_fields = _disabled_fields(controls.financial.financial.erp_major)
            if needs_method:
                if rounding is None:
                    raise ValueError
                method, method_origin = _select_method(rounding.value, None)
            elif rounding is not None:
                raise ValueError
            body = dict(profile="native-rounded-total-selection/v1", controls=controls.sha256,
                adjustment=self.adjustment, global_rounding=None if global_rounding is None else global_rounding.sha256,
                fraction=None if fraction is None else fraction.sha256, rounding=None if rounding is None else rounding.sha256,
                branch=branch, disabled=disabled, disable_origin=origin, method=method, method_origin=method_origin,
                zero_fields=zero_fields, base_conversion_fields=base_fields)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundingSelectionError("rounded_total_selection")
        for key, value in dict(controls=controls, global_rounding=global_rounding, fraction=fraction, rounding=rounding,
                branch=branch, disabled=disabled, disable_origin=origin, method=method, method_origin=method_origin,
                zero_fields=zero_fields, base_conversion_fields=base_fields).items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-native-rounded-total-selection/v1\0" + _canonical(body)).hexdigest())

    def __repr__(self):
        return "<RoundingDependencyPlan protected PARTIAL guard plan, NOT money authority>"

    def __reduce__(self):
        raise TypeError("rounded_total_selection_not_serializable")


def _pin_plan(observed):
    if type(observed) is not RoundingDependencyPlan:
        raise ValueError
    pinned = RoundingDependencyPlan(observed.controls, observed.adjustment, observed.global_rounding, observed.fraction, observed.rounding)
    if pinned != observed:
        raise ValueError
    return pinned
