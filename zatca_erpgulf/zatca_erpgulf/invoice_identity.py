"""Pure legacy identity-presence policy, not an issuance/retry coordinator."""


def has_legacy_uuid_value(value):
    """Preserve issued values while filtering known legacy status placeholders.

    This deliberately does not assert UUID syntax, provenance or acceptance.
    Tightening it could replace an existing issuance identity on retry; such a
    migration needs the original artifact and verified chain history first.
    Debug's strict UUID parser remains a separate disposable-preview policy.
    """
    value = str(value or "").strip()
    return bool(value) and value.lower() not in {
        "not submitted", "not submitted.", "none", "null", "false", "0",
    }
