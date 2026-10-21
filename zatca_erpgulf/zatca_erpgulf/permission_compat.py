"""Quiet direct saved-row/create ACL checks for inspected Frappe 15/16 signatures.

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


def _quiet_keyword(engine):
    """Choose the explicit framework signature without TypeError retries."""
    try:
        if not callable(engine):
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
    return keyword


def saved_row_has_permission(engine, doctype, operation, *, doc, user):
    """Invoke one quiet saved-row ACL check, requiring literal True."""
    if operation not in ("read", "write"):
        raise PermissionCompatibilityError()
    keyword = _quiet_keyword(engine)
    return engine(doctype, operation, doc=doc, user=user, **{keyword: False}) is True


def doctype_has_create_permission(engine, doctype, *, user):
    """Check ordinary create ACL once, without an unsaved Document shortcut.

    This does not grant row access or replace the insert's normal permission
    checks. Unknown signatures and engine errors never cause a fallback/retry.
    """
    keyword = _quiet_keyword(engine)
    return engine(doctype, "create", doc=None, user=user, **{keyword: False}) is True
