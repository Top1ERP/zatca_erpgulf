"""Country normalization shared by ZATCA validation and document generators."""
from __future__ import annotations

from typing import Any

from .country_code import country_code_mapping


_SAUDI_ALIASES = {"sa", "s.a.", "saudi arabia", "kingdom of saudi arabia"}


def normalize_country_code(value: Any) -> str:
    """Return an ISO-3166 alpha-2 code without changing stored ERPNext data.

    ERPNext stores Country links by name on common versions, while integrations
    and imports may provide an ISO code. Both forms are accepted.
    """
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return ""
    if normalized in _SAUDI_ALIASES:
        return "SA"
    if len(normalized) == 2 and normalized.isalpha():
        return normalized.upper()
    return country_code_mapping().get(normalized, normalized.upper())


def is_saudi_country(value: Any) -> bool:
    return normalize_country_code(value) == "SA"
