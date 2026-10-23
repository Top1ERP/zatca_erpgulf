"""Exact saved-Company drafts with synthetic ERP/ACL; no site, keys or HTTP."""

import csv
import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import csr_configuration as service


class ValidationError(Exception):
    pass


class PermissionDenied(ValidationError):
    pass


@pytest.fixture
def boundary(monkeypatch):
    # Only bypass Frappe's request-local HTTP type decorator: no site/request
    # is initialized. The real endpoint body, ACL and draft checks run below.
    for name in ("prepare_csr_config", "get_csr_config"):
        monkeypatch.setattr(service, name, inspect.unwrap(getattr(service, name)))
    doc = SimpleNamespace(doctype="Company", name="FICTIONAL COMPANY", abbr="FC",
        modified=datetime(2026, 10, 23, 9), tax_id="TEST-VAT", company_name="TEST شركة <script>",
        custom_zatca__location_for_csr_configuratoin="test city",
        custom_zatca__company_category_for_csr_configuration="TEST CATEGORY",
        custom_csr_config="OLD DRAFT", custom_private_key="PRIVATE-KEY", save=Mock(), db_set=Mock())
    messages = [{"message": "Unrelated parent message"}]
    app = SimpleNamespace(flags={}, session=SimpleNamespace(user="tester@example.invalid"),
        get_doc=Mock(return_value=doc), db=SimpleNamespace(commit=Mock(), get_value=Mock(return_value=doc.name)),
        ValidationError=ValidationError, PermissionError=PermissionDenied)

    def msgprint(msg=None, **kwargs):
        if not app.flags.get("mute_messages"):
            messages.append({"message": msg, **kwargs})

    def throw(message, exc=ValidationError, **kwargs):
        msgprint(message, **kwargs)
        raise exc(message)

    app.msgprint, app.throw = msgprint, throw
    monkeypatch.setattr(service, "frappe", app)
    monkeypatch.setattr(service, "_", lambda value: value)
    monkeypatch.setattr(service.random, "getrandbits", Mock(return_value=0x12345678))
    calls = []

    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        calls.append((doctype, ptype, doc, user, raise_exception))
        return True

    monkeypatch.setattr(service, "has_permission", permission)
    return SimpleNamespace(app=app, doc=doc, messages=messages, calls=calls,
        run=lambda: service.prepare_csr_config(doc.name, "2026-10-23 09:00:00"))


def unchanged(b):
    assert b.doc.custom_csr_config == "OLD DRAFT"
    assert b.doc.custom_private_key == "PRIVATE-KEY"
    b.doc.save.assert_not_called()
    b.doc.db_set.assert_not_called()
    b.app.db.commit.assert_not_called()


@pytest.mark.parametrize("engine", ["v15", "v16"])
@pytest.mark.parametrize("revision", ["2026-10-23 09:00:00", "2026-10-23T09:00:00.000000"])
def test_draft_uses_exact_saved_company_no_write_popup_or_credential_export(boundary, monkeypatch, engine, revision):
    b = boundary
    if engine == "v16":
        def permission(doctype, ptype, *, doc, user, print_logs=True):
            b.calls.append((doctype, ptype, doc, user, print_logs))
            return True
        monkeypatch.setattr(service, "has_permission", permission)
    before = vars(b.doc).copy()
    result = service.prepare_csr_config(b.doc.name, revision)
    assert result == {"status": "DRAFT", "company_name": b.doc.name, "modified": revision,
        "config": "csr.common.name=TST-886431145-TEST-VAT\n"
                  "csr.serial.number=1-TST|2-TST|3-12345678-1234-1234-1234-12345678\n"
                  "csr.organization.identifier=TEST-VAT\ncsr.organization.unit.name=TEST-VAT\n"
                  "csr.organization.name=TEST شركة <script>\ncsr.country.name=SA\n"
                  "csr.invoice.type=1100\ncsr.location.address=TEST CITY\n"
                  "csr.industry.business.category=TEST CATEGORY"}
    b.app.get_doc.assert_called_once_with("Company", b.doc.name)
    assert [(row[0], row[1], row[3], row[4]) for row in b.calls] == [
        ("Company", "read", b.app.session.user, False), ("Company", "write", b.app.session.user, False)]
    assert all(row[2] is b.doc for row in b.calls)
    assert b.messages == [{"message": "Unrelated parent message"}] and b.app.flags == {}
    assert vars(b.doc) == before
    unchanged(b)


@pytest.mark.parametrize("field", service.CONFIG_FIELDS)
@pytest.mark.parametrize("value", [None, 5, "a\nb", "a\rb", "a\x00b", "a\x7fb", "x" * 1025,
                                    "a\x85b", "a\u2028b", "a\u2029b"])
def test_invalid_saved_values_cannot_inject_configuration_lines(boundary, field, value):
    setattr(boundary.doc, field, value)
    with pytest.raises(ValidationError, match="bounded single-line") as raised:
        boundary.run()
    assert raised.value.__context__ is None
    assert len(boundary.messages) == 2 and boundary.app.flags == {}
    unchanged(boundary)


@pytest.mark.parametrize("field,message", list(zip(service.CONFIG_FIELDS, (
    "Tax ID (VAT number) is required.", "Location for CSR configuration is required.",
    "Company category for CSR configuration is required.", "Company name is required."))))
def test_required_values_have_one_static_failure(boundary, field, message):
    setattr(boundary.doc, field, "")
    with pytest.raises(ValidationError) as raised:
        boundary.run()
    assert str(raised.value) == message and raised.value.__context__ is None
    assert len(boundary.messages) == 2
    unchanged(boundary)


@pytest.mark.parametrize("name", [None, {}, 1, "", " ", " COMPANY", "A\nB", "A\x7fB", "x" * 141])
def test_invalid_identity_does_not_load_company(boundary, name):
    with pytest.raises(ValidationError) as raised:
        service.prepare_csr_config(name, "2026-10-23 09:00:00")
    assert str(raised.value) == service.DRAFT_INVALID
    boundary.app.get_doc.assert_not_called()
    unchanged(boundary)


@pytest.mark.parametrize("revision", [None, {}, 1, "", "2026-99-99 09:00:00", "2026-10-23T9:00:00",
    "2026-10-23 09:00:00Z", datetime(2026, 10, 23, 9), "PRIVATE"])
def test_invalid_requested_revision_does_not_load_company(boundary, revision):
    with pytest.raises(ValidationError) as raised:
        service.prepare_csr_config(boundary.doc.name, revision)
    assert str(raised.value) == service.DRAFT_INVALID
    boundary.app.get_doc.assert_not_called()


@pytest.mark.parametrize("saved", ["2026-10-23 09:01:00", datetime(2026, 10, 23, 10),
    None, datetime(2026, 10, 23, 9, tzinfo=timezone.utc)])
def test_revision_mismatch_or_unknown_is_not_a_draft(boundary, saved):
    boundary.doc.modified = saved
    with pytest.raises(ValidationError) as raised:
        boundary.run()
    assert str(raised.value) in (service.DRAFT_CHANGED, service.DRAFT_INVALID)
    unchanged(boundary)


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("allowed", [False, None, 1, "yes"])
def test_both_saved_row_permissions_require_literal_true(boundary, monkeypatch, operation, allowed):
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        assert raise_exception is False
        return allowed if ptype == operation else True
    monkeypatch.setattr(service, "has_permission", permission)
    with pytest.raises(PermissionDenied) as raised:
        boundary.run()
    assert str(raised.value) == service.DRAFT_DENIED and raised.value.__context__ is None
    unchanged(boundary)


@pytest.mark.parametrize("user", [None, "", "Guest"])
def test_guest_and_missing_session_user_cannot_load_company(boundary, user):
    boundary.app.session.user = user
    with pytest.raises(PermissionDenied):
        boundary.run()
    boundary.app.get_doc.assert_not_called()


@pytest.mark.parametrize("field,value", [("doctype", "Sales Invoice"), ("name", "OTHER")])
def test_loaded_identity_must_match_the_exact_requested_company(boundary, field, value):
    setattr(boundary.doc, field, value)
    with pytest.raises(ValidationError) as raised:
        service.prepare_csr_config("FICTIONAL COMPANY", "2026-10-23 09:00:00")
    assert str(raised.value) == service.DRAFT_INVALID and not boundary.calls
    unchanged(boundary)


@pytest.mark.parametrize("value", ["PRIVATE-DIAGNOSTIC", object()])
def test_internal_error_container_never_forwards_an_unrecognized_message(boundary, value):
    boundary.app.get_doc.side_effect = service.CSRConfigurationError(value)
    with pytest.raises(ValidationError) as raised:
        boundary.run()
    assert str(raised.value) == service.DRAFT_FAILED and raised.value.__context__ is None


@pytest.mark.parametrize("phase", ["load", "acl", "build"])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}, {"mute_messages": "parent"}])
def test_unexpected_erp_errors_are_not_stringified_and_parent_state_is_restored(boundary, monkeypatch, phase, flags):
    class SecretError(Exception):
        def __str__(self):
            raise AssertionError("Never stringify private diagnostic")
    b = boundary
    b.app.flags = dict(flags)
    def fail(*args, **kwargs):
        b.app.msgprint("PRIVATE-CHILD")
        raise SecretError()
    if phase == "load":
        b.app.get_doc.side_effect = fail
    elif phase == "acl":
        def permission(doctype, ptype, *, doc, user, raise_exception=True):
            return fail()
        monkeypatch.setattr(service, "has_permission", permission)
    else:
        monkeypatch.setattr(service, "_build_csr_config", fail)
    with pytest.raises(ValidationError) as raised:
        b.run()
    assert str(raised.value) == service.DRAFT_FAILED and raised.value.__context__ is None
    assert b.app.flags == flags
    assert b.messages == [{"message": "Unrelated parent message"}] + (
        [] if flags.get("mute_messages") else [{"message": service.DRAFT_FAILED, "title": "CSR Configuration Failed"}])
    unchanged(b)


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_cancellation_restores_flags_without_a_draft_or_error_popup(boundary, stop):
    boundary.app.get_doc.side_effect = stop("PRIVATE-CANCEL")
    with pytest.raises(stop):
        boundary.run()
    assert boundary.app.flags == {} and len(boundary.messages) == 1
    unchanged(boundary)


def test_legacy_string_contract_uses_same_builder_but_escapes_popup(boundary):
    expected = service._build_csr_config(boundary.doc)
    assert service.get_csr_config("FC") == expected
    assert len(boundary.messages) == 2
    assert "<script>" not in boundary.messages[-1]["message"]
    assert "&lt;script&gt;" in boundary.messages[-1]["message"]
    unchanged(boundary)


def test_canonical_errors_have_arabic_display_translations():
    with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8", newline="") as source:
        translations = dict(csv.reader(source))
    for key in (service.DRAFT_FAILED, service.DRAFT_DENIED, service.DRAFT_CHANGED, service.DRAFT_INVALID,
                service.DRAFT_VALUES, "CSR Configuration Failed", "Tax ID (VAT number) is required.",
                "Location for CSR configuration is required.", "Company category for CSR configuration is required.",
                "Company name is required."):
        assert any("\u0600" <= char <= "\u06ff" for char in translations[key])
