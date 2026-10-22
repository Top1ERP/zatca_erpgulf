"""Request-scoped message ownership and canonical English presentation keys.

Translate these keys in the UI, not in stored diagnostics or source generation.
No transport, language mutation, persistence, or global Frappe monkeypatching.
"""

from contextlib import contextmanager


DEBUG_CREATED = "Debug XML attached successfully."
DEBUG_FAILED = "Debug XML generation failed. See technical details."
DEBUG_SKIPPED = "Debug XML was skipped for an intra-company transfer. The invoice was not changed."
DEBUG_POS_DISABLED = "ZATCA E-Invoicing is disabled for this Company. No debug XML was generated."
DEBUG_LOCAL_ONLY = (
    "ZATCA E-Invoicing is disabled for this Company. "
    "Debug XML will be generated locally only; no submission will be performed."
)
DEBUG_EXISTING = "Existing XML/QR was found. A separate debug XML will be generated."


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
