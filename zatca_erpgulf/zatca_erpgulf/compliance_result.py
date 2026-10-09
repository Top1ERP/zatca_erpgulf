"""Interpret Compliance API outcomes without HTTP, Frappe, or database access.

An HTTP success or the absence of an exception does not prove compliance.
Only an explicit validation result can complete a check. Previous completion
is tracked separately from a newly validated document; it does not mean that
the document has been reported or cleared for production.
"""


def is_already_completed_response(status_code: int, response: object) -> bool:
    """Recognize only the specific HTTP 406 previous-completion response.

    Do not filter malformed entries before ``all``: doing so can accidentally
    accept an empty iterator or hide another validation error.
    """
    if status_code != 406 or not isinstance(response, dict):
        return False
    validation = response.get("validationResults")
    if not isinstance(validation, dict) or validation.get("status") != "ERROR":
        return False
    errors = validation.get("errorMessages")
    return (
        isinstance(errors, list)
        and bool(errors)
        and all(
            isinstance(error, dict) and error.get("code") == "Submitted before"
            for error in errors
        )
    )


def compliance_result_status(response: object) -> str | None:
    """Return PASS/ALREADY_COMPLETED only for a confirmed result, else None.

    The API boundary adds the internal previous-completion marker only after
    checking HTTP 406. Aggregators also validate its payload instead of trusting
    an arbitrary truthy return value. Warnings remain successful validations;
    an embedded error always prevents a new PASS result.
    """
    if not isinstance(response, dict):
        return None
    if "_zatca_compliance_status" in response:
        if (
            response["_zatca_compliance_status"] == "ALREADY_COMPLETED"
            and is_already_completed_response(406, response)
        ):
            return "ALREADY_COMPLETED"
        return None
    validation = response.get("validationResults")
    if not isinstance(validation, dict):
        return None
    errors = validation.get("errorMessages", [])
    if (
        validation.get("status") in ("PASS", "WARNING")
        and isinstance(errors, list)
        and not errors
    ):
        return "PASS"
    return None
