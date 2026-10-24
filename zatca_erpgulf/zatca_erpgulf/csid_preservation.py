"""Conservative saved Final-auth protection, not complete credential custody.

    Both legacy spellings/purposes are checked on the actual write target.
    Certificate-only/remote state is not inferred from absent authentication.
"""

from zatca_erpgulf.zatca_erpgulf.credential_presence import classify_saved_credential_presence


FINAL_AUTH_FIELDS = ("custom_basic_auth_from_production", "custom_final_auth_csid")
FINAL_AUTH_PRESERVATION_REQUIRED = (
    "Saved Final-CSID authentication data already exists. This operation cannot replace the shared "
    "certificate or authentication. Review the existing credentials and use a separately reviewed "
    "renewal workflow; do not clear saved fields to bypass this check."
)
FINAL_AUTH_STATE_UNCONFIRMED = (
    "Saved Final-CSID authentication state could not be verified. CSID creation is blocked. "
    "Review saved settings before another operation; do not clear credential fields to bypass this check."
)


class CSIDPreservationError(ValueError):
    """Accept a static selector only, never credential/response diagnostics."""

    def __init__(self, code):
        existing = type(code) is str and code == "existing"
        self.code = "CSID_FINAL_AUTH_PRESERVATION_REQUIRED" if existing else "CSID_FINAL_AUTH_STATE_UNCONFIRMED"
        self.message = FINAL_AUTH_PRESERVATION_REQUIRED if existing else FINAL_AUTH_STATE_UNCONFIRMED
        super().__init__(self.code)


def require_no_saved_final_auth(values):
    """Stop on either populated auth field, including the nonpreferred spelling.

    Missing Final auth does not prove safe renewal, no active certificate, remote
    completion or verified source/credential epoch. The caller must not infer it.
    """
    status = classify_saved_credential_presence(values, FINAL_AUTH_FIELDS)
    if status == "UNKNOWN":
        raise CSIDPreservationError("state")
    if status == "PRESENT":
        raise CSIDPreservationError("existing")
