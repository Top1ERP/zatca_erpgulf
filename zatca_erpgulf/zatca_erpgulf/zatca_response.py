"""Preserve ZATCA API responses exactly as received.

The response body is a machine-readable audit artifact. It must not be
translated, re-serialized, or have fields removed before it is written to an
invoice or an event log. The function name is retained as a compatibility
shim because older submission paths import it directly.
"""


def format_zatca_response(response_text, status_code=None):
    """Return the exact response body supplied by ZATCA.

    ``status_code`` is intentionally not injected into the body. Callers
    already display it outside the response, while the value passed here is
    kept in the signature for compatibility with existing integrations.
    """
    del status_code
    return response_text
