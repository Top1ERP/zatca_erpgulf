"""Three saved-Company workflows with synthetic ERP/ACL/delegates only."""

import csv
import inspect
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import company_compliance as service
from zatca_erpgulf.zatca_erpgulf import device_compliance as device_service
from zatca_erpgulf.zatca_erpgulf.tests.test_device_compliance import (
    boundary as device_boundary, no_writes, ValidationError, PermissionDenied,
)


@pytest.fixture
def boundary(device_boundary, monkeypatch):
    b = device_boundary
    monkeypatch.setattr(service, "run_company_compliance_summary", inspect.unwrap(service.run_company_compliance_summary))
    monkeypatch.setattr(service, "frappe", b.app)
    monkeypatch.setattr(service, "_", lambda text: text)
    monkeypatch.setattr(service, "has_permission", device_service.has_permission)
    b.company.modified = datetime(2026, 10, 23, 9)
    b.company.custom_sample_invoice_number_to_test = b.invoice.name
    b.delegates = {mode: Mock(return_value={"results": [], "mode": mode}) for mode in service.MODES}
    for mode, name in (("single", "run_single_compliance_summary"), ("all", "run_all_compliance_summary"),
                       ("automatic", "run_automatic_zatca_onboarding_checks")):
        monkeypatch.setattr(service, name, b.delegates[mode])
    b.run = lambda mode="all": service.run_company_compliance_summary(b.company.name, "2026-10-23 09:00:00", mode)
    return b


def no_delegate(b):
    for delegated in b.delegates.values():
        delegated.assert_not_called()
    no_writes(b)


@pytest.mark.parametrize("mode", service.MODES)
@pytest.mark.parametrize("engine", ["v15", "v16"])
@pytest.mark.parametrize("result", [None, {}, {"results": []}, {"all_passed": False}, {"results": [{"status": "FAIL"}]}])
def test_one_exact_delegate_and_unchanged_english_result(boundary, monkeypatch, mode, engine, result):
    b = boundary
    if engine == "v16":
        def permission(doctype, ptype, *, doc, user, print_logs=True):
            b.acl.append((doctype, ptype, doc, user, print_logs))
            return True
        monkeypatch.setattr(service, "has_permission", permission)
    b.delegates[mode].return_value = result
    def delegated(*args):
        assert b.app.flags["mute_messages"] is True
        b.app.msgprint("PRIVATE-CHILD")
        return result
    b.delegates[mode].side_effect = delegated
    monkeypatch.setattr(service, "_", lambda text: "ترجمة العرض فقط")
    assert b.run(mode) is result, "Facade neither invents acceptance nor translates the delegated result"
    b.delegates[mode].assert_called_once_with(*((b.company.name,) if mode == "automatic" else (b.company.name, b.invoice.name)))
    assert sum(item.call_count for item in b.delegates.values()) == 1
    expected = [("Company", b.company.name)] + ([] if mode == "automatic" else [("Sales Invoice", b.invoice.name)])
    assert [call.args for call in b.app.get_doc.call_args_list] == expected
    assert [(row[0], row[1], row[3], row[4]) for row in b.acl] == [
        (doctype, "read", b.app.session.user, False) for doctype, name in expected]
    assert b.app.flags == {} and len(b.messages) == 1
    no_writes(b)


@pytest.mark.parametrize("mode,doctype", [(mode, "Company") for mode in service.MODES] +
    [(mode, "Sales Invoice") for mode in ("single", "all")])
@pytest.mark.parametrize("allowed", [False, None, 1, "yes"])
def test_read_denial_on_any_required_source_prevents_all_delegates(boundary, monkeypatch, mode, doctype, allowed):
    def permission(kind, ptype, *, doc, user, raise_exception=True):
        assert raise_exception is False
        return allowed if kind == doctype else True
    monkeypatch.setattr(service, "has_permission", permission)
    with pytest.raises(PermissionDenied) as raised:
        boundary.run(mode)
    assert str(raised.value) == service.DENIED and raised.value.__context__ is None
    no_delegate(boundary)


@pytest.mark.parametrize("name", [None, {}, True, "", " COMPANY", "A\nB", "A\x7fB", "x" * 141])
def test_invalid_identity_prevents_company_loading(boundary, name):
    with pytest.raises(ValidationError):
        service.run_company_compliance_summary(name, "2026-10-23 09:00:00", "all")
    boundary.app.get_doc.assert_not_called()
    no_delegate(boundary)


@pytest.mark.parametrize("revision", [None, {}, True, "", "PRIVATE", "2026-99-99 09:00:00", "2026-10-23T9:00:00", "2026-10-23 09:00:00Z"])
def test_invalid_revision_prevents_company_loading(boundary, revision):
    with pytest.raises(ValidationError):
        service.run_company_compliance_summary(boundary.company.name, revision, "all")
    boundary.app.get_doc.assert_not_called()
    no_delegate(boundary)


@pytest.mark.parametrize("mode", [None, {}, True, 1, "", "SINGLE", "single ", "reporting"])
def test_client_cannot_select_an_unknown_or_live_dispatch_mode(boundary, mode):
    with pytest.raises(ValidationError):
        boundary.run(mode)
    boundary.app.get_doc.assert_not_called()
    no_delegate(boundary)


@pytest.mark.parametrize("revision", [datetime(2026, 10, 23, 10), "2026-10-23 09:01:00", None, datetime(2026, 10, 23, 9, tzinfo=timezone.utc)])
def test_saved_company_revision_must_match_before_any_invoice_load(boundary, revision):
    boundary.company.modified = revision
    with pytest.raises(ValidationError):
        boundary.run()
    assert boundary.app.get_doc.call_count == 1
    no_delegate(boundary)


@pytest.mark.parametrize("user", [None, "", "Guest"])
def test_actor_required_before_loading(boundary, user):
    boundary.app.session.user = user
    with pytest.raises(PermissionDenied):
        boundary.run()
    boundary.app.get_doc.assert_not_called()
    no_delegate(boundary)


@pytest.mark.parametrize("doctype,field", [(doctype, field) for doctype in ("Company", "Sales Invoice") for field in ("doctype", "name")])
def test_loaded_identity_must_match_the_exact_selected_source(boundary, doctype, field):
    selected = boundary.company.name
    setattr(boundary.company if doctype == "Company" else boundary.invoice, field, "OTHER")
    with pytest.raises(ValidationError):
        service.run_company_compliance_summary(selected, "2026-10-23 09:00:00", "all")
    no_delegate(boundary)


@pytest.mark.parametrize("mode", ["single", "all"])
def test_cross_company_invoice_refused_before_dispatch(boundary, mode):
    boundary.invoice.company = "OTHER"
    with pytest.raises(ValidationError) as raised:
        boundary.run(mode)
    assert str(raised.value) == service.MISMATCH
    no_delegate(boundary)


@pytest.mark.parametrize("value", [None, "", {}, "A\nB", "x" * 141])
@pytest.mark.parametrize("mode", ["single", "all"])
def test_nonautomatic_modes_require_saved_sample_invoice(boundary, value, mode):
    boundary.company.custom_sample_invoice_number_to_test = value
    with pytest.raises(ValidationError):
        boundary.run(mode)
    no_delegate(boundary)


@pytest.mark.parametrize("value", [None, "", {}, "A\nB", "x" * 141])
def test_automatic_mode_does_not_read_or_require_a_sample_invoice(boundary, value):
    boundary.company.custom_sample_invoice_number_to_test = value
    assert boundary.run("automatic") is boundary.delegates["automatic"].return_value
    boundary.app.get_doc.assert_called_once_with("Company", boundary.company.name)
    no_writes(boundary)


@pytest.mark.parametrize("value", [None, "", {}])
def test_saved_abbreviation_required_before_delegation(boundary, value):
    boundary.company.abbr = value
    with pytest.raises(ValidationError):
        boundary.run("automatic")
    no_delegate(boundary)


@pytest.mark.parametrize("mode", service.MODES)
@pytest.mark.parametrize("phase", ["load", "acl", "delegate"])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}, {"mute_messages": "parent"}])
def test_faults_restore_parent_messages_and_never_stringify_private_errors(boundary, monkeypatch, mode, phase, flags):
    b = boundary
    b.app.flags = dict(flags)
    class PrivateError(Exception):
        def __str__(self):
            raise AssertionError("Never stringify private error")
    def fail(*args, **kwargs):
        b.app.msgprint("PRIVATE-CHILD")
        raise PrivateError()
    if phase == "load":
        b.app.get_doc.side_effect = fail
    elif phase == "acl":
        def permission(doctype, ptype, *, doc, user, raise_exception=True):
            return fail()
        monkeypatch.setattr(service, "has_permission", permission)
    else:
        b.delegates[mode].side_effect = fail
    with pytest.raises(ValidationError) as raised:
        b.run(mode)
    expected = service.UNCONFIRMED if phase == "delegate" else service.PREPARATION_FAILED
    assert str(raised.value) == expected and raised.value.__context__ is None
    assert b.app.flags == flags
    assert b.messages == [{"message": "Unrelated parent message"}] + ([] if flags.get("mute_messages") else
        [{"message": expected, "title": "Compliance Check Failed"}])
    assert sum(item.call_count for item in b.delegates.values()) == (1 if phase == "delegate" else 0)
    no_writes(b)


@pytest.mark.parametrize("mode", service.MODES)
@pytest.mark.parametrize("phase", ["load", "delegate"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_cancellation_restores_flags_and_never_retries(boundary, mode, phase, stop):
    target = boundary.app.get_doc if phase == "load" else boundary.delegates[mode]
    target.side_effect = stop("PRIVATE-STOP")
    with pytest.raises(stop):
        boundary.run(mode)
    assert boundary.app.flags == {} and len(boundary.messages) == 1
    assert sum(item.call_count for item in boundary.delegates.values()) == (1 if phase == "delegate" else 0)
    no_writes(boundary)


def test_error_keys_have_actual_arabic_translations():
    with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8", newline="") as source:
        translations = dict(csv.reader(source))
    for key in (service.DENIED, service.CHANGED, service.MISMATCH, service.PREPARATION_FAILED, service.UNCONFIRMED):
        assert any("\u0600" <= char <= "\u06ff" for char in translations[key])
