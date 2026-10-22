"""Operation-scoped compliance summaries; translate only in the presenter.

No transport, persistence, language changes, or replacement of Frappe functions.
Technical details retain the original exception text, not a translated/rebuilt
authority response. App-generated summary messages are canonical English.
"""

from contextlib import contextmanager

from zatca_erpgulf.zatca_erpgulf.compliance_result import compliance_result_status


COMPLETED = "Completed successfully."
WITH_WARNINGS = "Completed with warnings. See technical details."
ALREADY_COMPLETED = "Already completed by ZATCA; treated as PASS."
FAILED = "Compliance check failed. See technical details."
UNCONFIRMED = "ZATCA did not confirm compliance. This check cannot be marked as passed."


@contextmanager
def _mute_nested_messages(runtime):
    """Suppress child popups, not exceptions; preserve the caller's exact flag.

Frappe flags are request-local on v15/v16. Do not clear message_log: messages
queued by a parent operation are not owned by this batch. BaseException also
unwinds through finally, so cancellation cannot leave later messages muted.
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


def collect_compliance_results(runtime, validation_types, submit):
    """Keep all six outcomes, without treating HTTP success alone as a pass.

The caller supplies an existing submission path. No retries, logging commits,
credential changes, or acceptance rules are introduced here. Unknown errors
retain their original diagnostic text; interrupts are never converted to FAIL.
"""
    results = []
    with _mute_nested_messages(runtime):
        for validation_type in validation_types:
            try:
                response = submit(validation_type)
                outcome = compliance_result_status(response)
                if outcome is None:
                    raise runtime.ValidationError(UNCONFIRMED)
                validation = response["validationResults"]
                warnings = (
                    validation.get("status") == "WARNING"
                    or bool(validation.get("warningMessages"))
                )
                if outcome == "ALREADY_COMPLETED":
                    message = ALREADY_COMPLETED
                else:
                    message = WITH_WARNINGS if warnings else COMPLETED
                row = {
                    "type": validation_type,
                    "status": "PASS",
                    "compliance_status": outcome,
                    "message": message,
                }
                # Preserve parsed validation data for the view, including warnings.
                # This is NOT the original HTTP body and never replaces its log.
                row["validation_details"] = validation
                results.append(row)
            except Exception as error:
                results.append({
                    "type": validation_type,
                    "status": "FAIL",
                    "message": FAILED,
                    "technical_details": str(error),
                })
    return results
