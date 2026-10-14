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
