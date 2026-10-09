"""Shared document-type contract for the two alternative onboarding methods."""

COMPLIANCE_TYPES = {
    "Simplified Invoice": "1",
    "Standard Invoice": "2",
    "Simplified Credit Note": "3",
    "Standard Credit Note": "4",
    "Simplified Debit Note": "5",
    "Standard Debit Note": "6",
}


def resolve_compliance_type(validation_type, fallback="0") -> str:
    """Resolve a label while preserving legacy callers' explicit numeric code."""
    code = str(COMPLIANCE_TYPES.get(validation_type, fallback))
    if code not in COMPLIANCE_TYPES.values():
        raise ValueError("Select a valid ZATCA compliance document type.")
    return code


def normalize_submission_compliance_type(value) -> str:
    """Normalize legacy selectors before a generator can allocate live identity.

    Zero selects ordinary generation. Only the six documented sample codes may
    select Compliance; malformed values must not fall through into live work.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Select a valid ZATCA compliance document type.")
    code = str(value).strip()
    if code != "0" and code not in COMPLIANCE_TYPES.values():
        raise ValueError("Select a valid ZATCA compliance document type.")
    return code
