"""Shared document-type contract for the two alternative onboarding methods."""

from dataclasses import dataclass

COMPLIANCE_TYPES = {
    "Simplified Invoice": "1",
    "Standard Invoice": "2",
    "Simplified Credit Note": "3",
    "Standard Credit Note": "4",
    "Simplified Debit Note": "5",
    "Standard Debit Note": "6",
}


@dataclass(frozen=True)
class ComplianceDocumentType:
    """Existing sample XML values; centralization does not certify their rules."""

    type_name: str
    document_code: str
    simplified: bool
    is_note: bool


_XML_TYPES = {
    "1": ComplianceDocumentType("0200000", "388", True, False),
    "2": ComplianceDocumentType("0100000", "388", False, False),
    "3": ComplianceDocumentType("0200000", "381", True, True),
    "4": ComplianceDocumentType("0100000", "381", False, True),
    "5": ComplianceDocumentType("0211000", "383", True, True),
    "6": ComplianceDocumentType("0100000", "383", False, True),
}


def compliance_document_type(value) -> ComplianceDocumentType:
    """Resolve only an explicit sample code, never the ordinary zero selector."""
    code = normalize_submission_compliance_type(value)
    if code == "0":
        raise ValueError("Select a valid ZATCA compliance document type.")
    return _XML_TYPES[code]


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
