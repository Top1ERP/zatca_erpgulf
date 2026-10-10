"""Actual-signature-shaped ACL fakes; not a Frappe 16 runtime rehearsal."""

from functools import wraps
from inspect import signature
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission, PermissionCompatibilityError


@pytest.mark.parametrize("version", [15, 16])
@pytest.mark.parametrize("value", [True, False, 1, None, "yes"])
def test_explicit_engine_signature_selects_quiet_parameter_once(version, value):
    calls, saved = [], object()
    def v15(doctype, ptype="read", doc=None, user=None, raise_exception=True, *, parent_doctype=None, debug=False):
        calls.append((doctype, ptype, doc, user, raise_exception))
        return value
    def v16(doctype, ptype="read", doc=None, user=None, *, parent_doctype=None, print_logs=True, debug=False):
        calls.append((doctype, ptype, doc, user, print_logs))
        return value
    engine = v15 if version == 15 else v16
    @wraps(engine)
    def decorated(*args, **kwargs):
        return engine(*args, **kwargs)
    assert saved_row_has_permission(decorated, "Company", "write", doc=saved, user="manager") is (value is True)
    assert calls == [("Company", "write", saved, "manager", False)]


@pytest.mark.parametrize("version", [15, 16])
def test_internal_typeerror_never_retries_with_another_keyword(version):
    calls = []
    def v15(doctype, ptype, *, doc, user, raise_exception):
        calls.append(raise_exception)
        raise TypeError("PRIVATE-SECRET internal permission error")
    def v16(doctype, ptype, *, doc, user, print_logs):
        calls.append(print_logs)
        raise TypeError("PRIVATE-SECRET internal permission error")
    with pytest.raises(TypeError):
        saved_row_has_permission(v15 if version == 15 else v16, "Company", "read", doc=object(), user="manager")
    assert calls == [False]


@pytest.mark.parametrize("kind", ["generic", "missing", "positional_only", "uncallable", "bad_operation", "bad_signature"])
def test_unsupported_engine_fails_before_acl_and_without_context(kind):
    engine = Mock()
    if kind == "missing":
        def shape(doctype, operation, *, doc, user):
            pass
        engine.__signature__ = signature(shape)
    elif kind == "positional_only":
        def shape(raise_exception, /, doctype, operation, *, doc, user):
            pass
        engine.__signature__ = signature(shape)
    elif kind == "uncallable":
        engine = None
    elif kind == "bad_signature":
        engine.__signature__ = "PRIVATE-SECRET invalid"
    with pytest.raises(PermissionCompatibilityError) as raised:
        saved_row_has_permission(engine, "Company", "submit" if kind == "bad_operation" else "read", doc=object(), user="manager")
    assert raised.value.__context__ is None and "PRIVATE-SECRET" not in str(raised.value)
    if engine is not None:
        engine.assert_not_called()
