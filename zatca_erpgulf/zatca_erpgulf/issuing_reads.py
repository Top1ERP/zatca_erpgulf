"""Observe declared preparation dependencies without replacing Frappe globally."""

from .issuing_attempt import ACTIVE


DEPENDENCIES = frozenset((
    'Company', 'ZATCA Multiple Setting', 'Customer', 'Address', 'Cost Center',
    'Item Tax Template', 'Sales Taxes and Charges Template', 'POS Profile',
    'Sales Invoice', 'POS Invoice', 'Payment Entry', 'Account', 'Currency', 'Country',
))


def read_issuing_doc(runtime, *args, **kwargs):
    """Keep get_doc's arguments/result; observe only explicit saved read calls.

    Dictionary construction (File/new documents), unsupported DocTypes and all
    calls outside a preparation scope keep their earlier behavior. No cache or
    monkeypatch is installed in Frappe; the existing reader runs each time.
    """
    attempt = ACTIVE.get()
    if attempt is not None:
        attempt.require_runtime(runtime)
    document = runtime.get_doc(*args, **kwargs)
    if (attempt is not None and args and isinstance(args[0], str)
            and args[0] in DEPENDENCIES and getattr(document, 'name', None)):
        attempt.observe_record(document)
    return document


def read_issuing_cached_doc(runtime, *args, **kwargs):
    """Use a saved read for scoped dependencies; leave ordinary cache callers alone.

    An execution-local preparation must not silently combine a stale cached
    Customer/template with fresh issuer material. This does not clear any cache.
    """
    if ACTIVE.get() is not None and args and isinstance(args[0], str) and args[0] in DEPENDENCIES:
        return read_issuing_doc(runtime, *args, **kwargs)
    return runtime.get_cached_doc(*args, **kwargs)


def _observe_query(runtime, method, args, kwargs):
    attempt = ACTIVE.get()
    if attempt is not None:
        attempt.require_runtime(runtime)
    reader = runtime.db.get_value if method == 'db.get_value' else getattr(runtime, method)
    result = reader(*args, **kwargs)
    if (attempt is not None and args and isinstance(args[0], str)
            and args[0] in DEPENDENCIES):
        return attempt.observe_query(method, args, kwargs, result)
    return result


def read_issuing_all(runtime, *args, **kwargs):
    """Observe the exact discovery query, not just the selected Address/master."""
    return _observe_query(runtime, 'get_all', args, kwargs)


def read_issuing_value(runtime, *args, **kwargs):
    """Observe scalar/list/native-map lookups such as Account VAT roles."""
    return _observe_query(runtime, 'db.get_value', args, kwargs)
