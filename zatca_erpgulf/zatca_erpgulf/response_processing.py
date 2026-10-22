"""Static local-processing failure signal, NOT an authority outcome/receipt.

No response body, identity, credentials, retry, database or transaction ownership.
This signal must bypass legacy ValidationError handlers that persist a generic
submission failure. Raise it outside their except blocks to avoid chaining raw
local exception data into the operator-facing review error.
"""

from frappe import _


LOCAL_RESPONSE_REVIEW = "A ZATCA response was received, but local processing did not complete. No automatic retry was performed. Review the response and local artifacts before submitting again; acceptance and durable receipt storage are not confirmed by this message."


class LocalResponseProcessingError(RuntimeError):
    """A review-required failure, never a success return or rejection verdict.

    Deliberately not ValueError/ValidationError: old generator handlers for those
    types must not swallow this error or reclassify it as an authority failure.
    """


def raise_local_response_review():
    """Call after leaving the legacy exception handler; retain no raw exception."""
    raise LocalResponseProcessingError(_(LOCAL_RESPONSE_REVIEW))


def run_received_response_step(step, *args, validation_error_type, **kwargs):
    """Guard ONE local processing step AFTER a response was received.

    The caller supplies its framework ValidationError class (also in v15/v16
    shaped tests). Deliberate HTTP-rejection throws MUST NOT use this wrapper.
    Known formerly caught local failures become the static review signal OUTSIDE
    their handler, not a generic authority failure. Unhandled RuntimeError and
    interruptions keep their old propagation. There is no retry, commit/rollback,
    raw exception retention or guarantee that the callback itself did not write.
    This includes explicitly selected rejection-persistence callbacks, but never
    the caller's deliberate remote-rejection throw. Prior callback commits and
    partially mutated in-memory documents are not undone; reload/review is needed.
    """
    try:
        return step(*args, **kwargs)
    except (ValueError, TypeError, KeyError, validation_error_type):
        pass  # Raise below, after the raw exception handler has finished.
    raise_local_response_review()


def received_response_message(formatter, response):
    """Use THROUGH run_received_response_step, including response-property reads.

    Forward exactly the existing text/status without caching or reclassifying it.
    This small adapter lets the guard cover lazy text decoding as well as the
    formatter itself. It neither stores a response nor evaluates acceptance.
    """
    return formatter(response.text, response.status_code)


def received_response_text(response):
    """Read THROUGH the step guard for legacy unformatted response messages.

    Preserve the original value exactly; do not add formatting, caching or JSON
    normalization to POS paths that previously displayed the raw response text.
    """
    return response.text


def received_response_text_step(step, response, *args, **kwargs):
    """Call THROUGH the guard so lazy log-payload reads stay inside the step.

    Forward the original text/arguments/result; do not normalize, store, inspect
    truthiness or classify success-log output as authority acceptance evidence.
    """
    return step(response.text, *args, **kwargs)
