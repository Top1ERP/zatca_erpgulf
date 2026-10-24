"""Conservative shared-key preservation, not certificate validity or rotation.

Presence of any issued/unknown legacy material requires review. Neither expiry,
invalid tokens, alias priority nor an environment change authorizes replacement.
No parsing, decryption, transport, persistence, cleanup or retry belongs here.
"""


PROTECTED_CREDENTIAL_FIELDS = (
    "custom_certificate", "custom_certficate", "custom_basic_auth_from_csid",
    "custom_basic_auth_from_production", "custom_final_auth_csid",
    "custom_compliance_request_id_",
)
KEY_PRESERVATION_REQUIRED = (
    "Existing ZATCA certificate, authentication or onboarding-reference data requires preservation. "
    "Do not replace the shared key/CSR through this operation. Use a separately reviewed renewal "
    "workflow; do not clear saved credentials to bypass this check."
)
CREDENTIAL_STATE_UNCONFIRMED = (
    "Saved ZATCA credential state could not be verified. Key/CSR replacement is blocked. "
    "Review the saved settings; do not clear credential fields to bypass this check."
)


class CSRKeyPreservationError(ValueError):
    """Static code/message only; never retain a record, value or exception."""

    def __init__(self, code):
        self.code = "CSR_KEY_PRESERVATION_REQUIRED" if type(code) is str and code == "existing" else "CSR_CREDENTIAL_STATE_UNCONFIRMED"
        self.message = KEY_PRESERVATION_REQUIRED if self.code == "CSR_KEY_PRESERVATION_REQUIRED" else CREDENTIAL_STATE_UNCONFIRMED
        super().__init__(self.code)


def require_unissued_key_target(values):
    """Require an exact app-owned projection with only None/empty text values.

    This is not an assertion of no remote issuance or of an atomic saved source.
    Keys/CSR/OTP alone are deliberately outside this issued-material projection.
    Whitespace and masked values are present, not silently normalized to empty.
    Unknown types fail closed without truth testing/stringifying private values.
    """
    if type(values) is not dict or set(values) != set(PROTECTED_CREDENTIAL_FIELDS):
        raise CSRKeyPreservationError("state")
    if any(value is not None and type(value) is not str for value in values.values()):
        raise CSRKeyPreservationError("state")
    if any(type(value) is str and value != "" for value in values.values()):
        raise CSRKeyPreservationError("existing")
