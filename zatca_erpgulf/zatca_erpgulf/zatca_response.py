"""Utilities for keeping ZATCA response bodies machine-readable.

The response body is an audit artifact. It must not be translated or
re-serialized before it is written to an invoice or an event log. Older
submission modules build a translated display message which contains the
response body; :func:`extract_raw_response` removes that display wrapper at
the persistence boundary while preserving the original JSON bytes.
"""

import json


def _as_text(response_text):
    """Return a response body as text without changing its contents."""
    if response_text is None:
        return ""
    if isinstance(response_text, bytes):
        return response_text.decode("utf-8", errors="replace")
    # Accept a requests.Response without calling ``json()``. Calling json()
    # would lose whitespace and key ordering from the authority's body.
    if hasattr(response_text, "text") and not isinstance(response_text, str):
        return _as_text(response_text.text)
    if isinstance(response_text, (dict, list)):
        return json.dumps(response_text, ensure_ascii=False, separators=(",", ":"))
    return str(response_text)


def extract_raw_response(response_text):
    """Extract the raw ZATCA body from a stored response/display value.

    Legacy paths sometimes store a message such as ``ZATCA Response:
    {"validationResults": ...}`` in ``custom_zatca_full_response``. This
    function returns the exact JSON substring in that message. A body that is
    already valid JSON is returned byte-for-byte (including whitespace).
    Non-JSON values such as ``Not Submitted`` remain unchanged for backwards
    compatibility.
    """
    text = _as_text(response_text)
    if not text:
        return text

    # A genuine response body must be preserved exactly, including leading or
    # trailing whitespace exposed by the HTTP client.
    try:
        json.loads(text)
    except (TypeError, ValueError):
        pass
    else:
        return text

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            _value, end = decoder.raw_decode(text[index:])
        except (TypeError, ValueError):
            continue
        return text[index : index + end]

    return text


def format_zatca_response(response_text, status_code=None):
    """Return the exact response body supplied by ZATCA.

    ``status_code`` is intentionally not injected into the body. Callers
    already display it outside the response, while the value passed here is
    kept in the signature for compatibility with existing integrations.
    """
    del status_code
    return response_text


def normalize_zatca_full_response(doc, method=None):  # pylint: disable=unused-argument
    """Normalize the invoice response field immediately before saving.

    This hook is side-effect free: it only changes the in-memory document.
    Frappe persists the value in the same transaction as the invoice, without
    an extra save/commit or API call.
    """
    if not hasattr(doc, "get"):
        return

    current = doc.get("custom_zatca_full_response")
    if current in (None, ""):
        return

    raw_response = extract_raw_response(current)
    if raw_response == current:
        return

    if hasattr(doc, "set"):
        doc.set("custom_zatca_full_response", raw_response)
    else:
        setattr(doc, "custom_zatca_full_response", raw_response)


def set_zatca_full_response(doc, response_text, **db_set_kwargs):
    """Persist one normalized response through a direct ``db_set`` call.

    A few legacy submission paths use ``db_set`` instead of ``save`` and thus
    do not run document events. They call this helper so those paths use the
    same storage contract as normal save paths.
    """
    raw_response = extract_raw_response(response_text)
    doc.db_set("custom_zatca_full_response", raw_response, **db_set_kwargs)
    return raw_response
