"""Request-scoped message ownership and canonical English presentation keys.

Translate these keys in the UI, not in stored diagnostics or source generation.
No transport, language mutation, persistence, or global Frappe monkeypatching.
"""

from contextlib import contextmanager
import json


DEBUG_CREATED = "Debug XML attached successfully."
DEBUG_FAILED = "Debug XML generation failed. See technical details."
DEBUG_SKIPPED = "Debug XML was skipped for an intra-company transfer. The invoice was not changed."
DEBUG_POS_DISABLED = "ZATCA E-Invoicing is disabled for this Company. No debug XML was generated."
DEBUG_LOCAL_ONLY = (
    "ZATCA E-Invoicing is disabled for this Company. "
    "Debug XML will be generated locally only; no submission will be performed."
)
DEBUG_EXISTING = "Existing XML/QR was found. A separate debug XML will be generated."
DEBUG_ACCESS_DENIED = "You do not have permission to create a debug XML attachment for this invoice."
DEBUG_ATTACHMENT_REVIEW = "Debug XML attachment could not be confirmed. Review the source and existing files before retrying."


def csid_creation_result(purpose):
    """Success metadata only; never accept a response, token or request ID.

    A saved local result is not invoice acceptance, remote Compliance completion
    or a credential-activation/rotation authorization.
    """
    messages = {
        "compliance": "Compliance CSID generated and saved successfully.",
        "production": "Final CSID generated and saved successfully.",
    }
    if type(purpose) is not str or purpose not in messages:
        raise ValueError("Unsupported CSID purpose.")
    return {"status": "SUCCESS", "purpose": purpose, "message": messages[purpose]}


def csid_request_rejection(purpose, http_status, body):
    """Bounded allowlisted response classification, never raw-text redaction.

    Unknown codes/messages/IDs/URLs/credential fields are not copied or logged.
    This is an unconfirmed CSID response, not authority acceptance or retry
    authorization. Only exact known codes in the expected purpose are used.
    """
    csid_creation_result(purpose)  # Validate the app-owned literal purpose.
    status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
    code = "CSID_RESPONSE_UNCONFIRMED"
    message = "CSID creation was not confirmed by the response. Review the selected environment and saved onboarding settings before trying again."
    if status == 401:
        code = "CSID_AUTHENTICATION_FAILED"
        message = "ZATCA authentication failed. Check that the Compliance credentials match the selected environment and issuing unit."
    elif status == 403:
        code = "CSID_ACCESS_DENIED"
        message = "ZATCA denied access to this CSID operation. Review the selected environment and issuing-unit authorization."
    elif status == 429:
        code = "CSID_RATE_LIMITED"
        message = "ZATCA returned a rate-limit response. Review the request outcome before trying again; no automatic retry was performed."
    elif status is not None and 500 <= status <= 599:
        code = "CSID_REMOTE_ERROR"
        message = "ZATCA returned a server error during CSID creation. Review saved settings and the request outcome before trying again."
    elif status == 400 and type(body) is str and len(body) <= 65536:
        try:
            data = json.loads(body)
        except (ValueError, RecursionError):
            data = None
        codes = []
        if type(data) is dict:
            codes.append(data.get("code"))
            errors = data.get("errors")
            if type(errors) is list and len(errors) <= 16:
                codes.extend(item.get("code") for item in errors if type(item) is dict)
        # Strings only; no arbitrary object's equality/coercion behavior.
        codes = [item for item in codes if type(item) is str]
        if purpose == "compliance" and "Invalid-OTP" in codes:
            code = "CSID_INVALID_OTP"
            message = "ZATCA rejected the OTP. Check the OTP and the selected environment before trying again."
        elif purpose == "production" and "Missing-ComplianceSteps" in codes:
            code = "CSID_COMPLIANCE_INCOMPLETE"
            message = "ZATCA reports incomplete Compliance checks. Complete the required checks for the same Compliance CSID before requesting the Final CSID."
    return {"status": "ERROR", "purpose": purpose, "code": code,
            "http_status": status, "message": message}


class CSIDRequestRejected(Exception):
    """Carry only normalized English metadata, never the response or headers."""

    def __init__(self, purpose, http_status, body):
        self.result = csid_request_rejection(purpose, http_status, body)
        super().__init__(self.result["code"])


@contextmanager
def mute_operation_messages(runtime):
    """Mute only child popups; exceptions still raise and parents keep ownership.

Frappe's request-local flag is restored exactly on success, failure, nesting or
BaseException cancellation. Never clear message_log or change the UI language.
"""
    flags = runtime.flags
    existed = "mute_messages" in flags
    previous = flags.get("mute_messages")
    flags["mute_messages"] = True
    try:
        yield
    finally:
        if existed:
            flags["mute_messages"] = previous
        else:
            flags.pop("mute_messages", None)
