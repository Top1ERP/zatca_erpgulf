"""Request-scoped message ownership and canonical English presentation keys.

Translate these keys in the UI, not in stored diagnostics or source generation.
No transport, language mutation, persistence, or global Frappe monkeypatching.
"""

from contextlib import contextmanager
from dataclasses import dataclass
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
CSID_FORM_REVIEW = "Review saved CSID settings before saving an already-open form or starting another CSID operation. Preserve unsaved changes before reloading."


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


@dataclass
class CSIDProgress:
    """Internal execution observations only, never remote or durable evidence."""

    request_started: bool = False
    response_received: bool = False
    save_started: bool = False
    save_completed: bool = False
    overlay_started: bool = False


CSID_PROGRESS_REVIEW = "The progress display could not be cleared. Review the form before starting another operation."


@dataclass
class CSRProgress:
    """Local observations only: a returning save is not a committed revision."""

    key_save_started: bool = False
    key_save_completed: bool = False
    csr_save_started: bool = False
    csr_save_completed: bool = False


def csr_local_failure(purpose, progress):
    """Classify local key/CSR failure without copying an exception or material.

    This does not decide rotation, restore previous credentials, infer a commit,
    or authorize another attempt. No HTTP request is part of these operations.
    """
    if type(purpose) is not str or purpose not in ("key", "csr"):
        raise ValueError("Unsupported CSR purpose.")
    if type(progress) is not CSRProgress or any(type(value) is not bool for value in vars(progress).values()):
        raise ValueError("Invalid CSR progress.")
    if ((progress.key_save_completed and not progress.key_save_started)
            or (progress.csr_save_started and not progress.key_save_completed)
            or (progress.csr_save_completed and not progress.csr_save_started)
            or (purpose == "key" and (progress.csr_save_started or progress.csr_save_completed))):
        raise ValueError("Invalid CSR progress.")
    if progress.csr_save_completed or (purpose == "key" and progress.key_save_completed):
        code = "CSR_LOCAL_COMPLETION_UNCONFIRMED"
        message = "The key or CSR save returned, but local completion could not be confirmed. Review saved key, CSR and certificate settings before another operation."
    elif progress.csr_save_started:
        code = "CSR_STORAGE_UNCONFIRMED"
        message = "CSR storage could not be confirmed after the private-key save returned. Changes may already exist. Review saved key, CSR and certificate settings before another operation; no automatic retry was performed."
    elif progress.key_save_completed:
        code = "CSR_BUILD_UNCONFIRMED"
        message = "The private-key save returned, but CSR creation did not complete. Review saved key, CSR and certificate settings before another operation; no automatic retry was performed."
    elif progress.key_save_started:
        code = "CSR_KEY_STORAGE_UNCONFIRMED"
        message = "Private-key storage could not be confirmed. Changes may already exist. Review saved key, CSR and certificate settings before another operation; no automatic retry was performed."
    else:
        code = "CSR_PREPARATION_FAILED"
        message = "Local key/CSR preparation failed before a key or CSR save was started. Review saved permissions and CSR configuration."
    return {"status": "ERROR", "purpose": purpose, "code": code, "message": message}


def csid_local_failure(purpose, progress):
    """Classify observed execution stage without accepting any raw exception.

    Entering transport does not prove sending; save returning does not prove
    commit. A failure must not authorize retries, cleanup or credential rotation.
    """
    csid_creation_result(purpose)
    if type(progress) is not CSIDProgress or any(type(value) is not bool for value in vars(progress).values()):
        raise ValueError("Invalid CSID progress.")
    if ((progress.response_received and not progress.request_started)
            or (progress.save_started and not progress.response_received)
            or (progress.save_completed and not progress.save_started)):
        raise ValueError("Invalid CSID progress.")
    if progress.save_completed:
        code = "CSID_LOCAL_COMPLETION_UNCONFIRMED"
        message = "The CSID save returned, but local completion could not be confirmed. Review saved settings and the outcome; do not generate another CSID just to refresh the form."
    elif progress.save_started:
        code = "CSID_STORAGE_UNCONFIRMED"
        message = "CSID storage could not be confirmed after a response was received. Changes may already exist. Review saved settings before trying again; no automatic retry was performed."
    elif progress.response_received:
        code = "CSID_PROCESSING_UNCONFIRMED"
        message = "A response was received, but CSID processing could not be completed. Review saved settings and the response outcome before trying again; no automatic retry was performed."
    elif progress.request_started:
        code = "CSID_REQUEST_OUTCOME_UNKNOWN"
        message = "The CSID request outcome is unknown after a connection or execution failure. Review saved settings and the onboarding status before trying again; no automatic retry was performed."
    else:
        code = "CSID_PREPARATION_FAILED"
        message = "CSID preparation failed before the request was started. Review saved Company, environment, CSR and authentication settings."
    return {"status": "ERROR", "purpose": purpose, "code": code,
            "http_status": None, "message": message}


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
