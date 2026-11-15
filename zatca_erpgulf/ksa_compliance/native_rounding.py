"""Shared native rounded-total decision with caller-owned numeric semantics.

No framework lookup, amount calculation, mutation or POS Profile fallback.
A native controller method owns schema/global-default resolution when present.
The fallback is explicit: strict POS versus older partial Sales helper inputs.
"""


class RoundingSourceError(ValueError):
    """Static source decision failure, independent of user language."""


def rounding_disabled(doc, *, flag, amount, missing_disabled=None):
    """Preserve consolidated adjustments before consulting later controls.

    Readers retain their own coercion/error policy. Keep method discovery and
    adjustment reads lazy: an unconsumed dependency cannot fail the operation.
    """
    if flag(doc.get("is_consolidated") or 0) and amount(doc.get("rounding_adjustment") or 0) != 0:
        return False
    native = getattr(doc, "is_rounded_total_disabled", None)
    if callable(native):
        return bool(flag(native() or 0))
    value = doc.get("disable_rounded_total")
    if value is None:
        if missing_disabled is None:
            raise RoundingSourceError("rounding_source")
        return missing_disabled
    return bool(flag(value or 0))
