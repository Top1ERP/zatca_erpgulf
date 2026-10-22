"""Operation-scoped compliance summaries; translate only in the presenter.

No transport, persistence, language changes, or replacement of Frappe functions.
Technical details retain the original exception text, not a translated/rebuilt
authority response. App-generated summary messages are canonical English.
"""

from zatca_erpgulf.zatca_erpgulf.compliance_result import compliance_result_status
from zatca_erpgulf.zatca_erpgulf.operation_messages import mute_operation_messages


COMPLETED = "Completed successfully."
WITH_WARNINGS = "Completed with warnings. See technical details."
ALREADY_COMPLETED = "Already completed by ZATCA; treated as PASS."
FAILED = "Compliance check failed. See technical details."
UNCONFIRMED = "ZATCA did not confirm compliance. This check cannot be marked as passed."


def collect_compliance_results(runtime, validation_types, submit):
    """Keep all six outcomes, without treating HTTP success alone as a pass.

The caller supplies an existing submission path. No retries, logging commits,
credential changes, or acceptance rules are introduced here. Unknown errors
retain their original diagnostic text; interrupts are never converted to FAIL.
"""
    results = []
    with mute_operation_messages(runtime):
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
