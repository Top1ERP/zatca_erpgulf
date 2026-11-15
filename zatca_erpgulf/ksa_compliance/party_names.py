"""Party display-name mechanics, separate from schema alias and issuer policy.

The registry owns field order. Existing Sales/POS/QR readers deliberately keep
their distinct blank/format and duplicate-name rules. No framework, cache,
database, VAT validation, transliteration or signing dependency belongs here.
"""

import re
import unicodedata

from .field_alias_registry import FIELD_ALIAS_GROUPS


SALES_NOISE_WORDS = frozenset({
    "company", "co", "co.", "corp", "corporation", "inc", "inc.", "ltd", "ltd.",
    "llc", "llp", "est", "est.", "factory", "trading", "group", "holding", "holdings",
    " المؤسسة", "شركة", "شركه", "مؤسسة", "مؤسسه", "محددودة", "محدودة", "ذ", "م", "م.",
})
POS_NOISE_WORDS = frozenset({"company", "co", "ltd", "llc", "corp", "inc", "شركة", "مؤسسة"})


def display_aliases(group):
    """Return an immutable view; never reorder the schema-compatibility aliases."""
    return tuple(FIELD_ALIAS_GROUPS[group]["display_aliases"])


def first_available_name(fieldnames, *, has_field, read, mode="sales"):
    """Read lazily with the caller's historical empty/format policy.

    Sales skips whitespace after stripping and preserves numeric zero as text.
    POS tests truthiness before stripping, so whitespace stops its fallback.
    QR preserves the first truthy raw value, including surrounding whitespace.
    These are compatibility rules, not complete legal-name validation.
    """
    if mode not in ("sales", "pos", "qr"):
        raise ValueError("party_name_mode")
    for fieldname in fieldnames:
        if not has_field(fieldname):
            continue
        value = read(fieldname)
        if mode == "sales":
            if value is not None:
                value = str(value).strip()
                if value:
                    return value
        elif value:
            return value if mode == "qr" else str(value).strip()
    return ""


def normalize_name(value, *, mode):
    """Comparison-only normalization; never overwrite the rendered name."""
    if mode not in ("sales", "pos"):
        raise ValueError("party_name_mode")
    if mode == "sales" and not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).lower()
    if mode == "sales":
        value = re.sub(r"[ـ]", "", value.strip())
    value = re.sub(r"[^\w\s؀-ۿ]", " ", value)
    noise = SALES_NOISE_WORDS if mode == "sales" else POS_NOISE_WORDS
    return " ".join(token for token in value.split() if token not in noise)


def script_type(value):
    """Preserve Sales' cross-script duplicate protection, without transliteration."""
    if not value:
        return "other"
    arabic = bool(re.search(r"[؀-ۿ]", value))
    latin = bool(re.search(r"[A-Za-z]", value))
    return "mixed" if arabic and latin else "arabic" if arabic else "latin" if latin else "other"


def unique_names(names, *, similar, clean):
    """Keep caller order and comparison overrides; only Sales cleans each input."""
    result = []
    for name in names:
        value = str(name or "").strip() if clean else name
        if value and not any(similar(value, prior) for prior in result):
            result.append(value)
    return result
