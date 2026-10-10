"""Quiet direct saved-row ACL checks for the inspected Frappe 15/16 signatures.

Frappe 15 uses raise_exception=False to suppress permission diagnostic messages;
Frappe 16 renamed it print_logs=False. Select by the explicit engine signature,
not version strings or a TypeError retry (which could mask an internal ACL fault).
No Document ignore_permissions shortcut, permission fallback or cache mutation.
"""

from inspect import Parameter, signature


class PermissionCompatibilityError(ValueError):
    """Static unsupported-engine code, no document/user/engine representation."""

    def __init__(self):
        super().__init__("permission_engine_signature")


def saved_row_has_permission(engine, doctype, operation, *, doc, user):
    """Invoke the trusted permission engine ONCE and require literal True.

    Unknown/decorated-away signatures fail closed before invocation. Engine
    exceptions propagate to the redacted service boundary, never trigger retry.
    """
    try:
        if not callable(engine) or operation not in ("read", "write"):
            raise PermissionCompatibilityError()
        parameters = signature(engine).parameters
        keyword = next((name for name in ("print_logs", "raise_exception") if name in parameters
                        and parameters[name].kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)), None)
        if keyword is None:
            raise PermissionCompatibilityError()
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PermissionCompatibilityError()
    return engine(doctype, operation, doc=doc, user=user, **{keyword: False}) is True
