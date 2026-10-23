"""Saved-device facade with synthetic documents/ACL/submit; no site or HTTP."""

import csv
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import device_compliance as service


class ValidationError(Exception):
    pass


class PermissionDenied(ValidationError):
    pass


@pytest.fixture
def boundary(monkeypatch):
    # Only the request-local type decorator is unwrapped; no Frappe request/site.
    monkeypatch.setattr(service, "run_device_compliance_summary", inspect.unwrap(service.run_device_compliance_summary))
    device = SimpleNamespace(doctype="ZATCA Multiple Setting", name="TEST DEVICE",
        modified=datetime(2026, 10, 23, 9), custom_linked_doctype="TEST COMPANY",
        custom_sample_invoice_number_to_test="TEST INVOICE", custom_private_key="PRIVATE-DEVICE-KEY",
        custom_validation_type="Standard Debit Note", save=Mock(), db_set=Mock())
    company = SimpleNamespace(doctype="Company", name="TEST COMPANY", abbr="TC",
        custom_validation_type="Standard Invoice", custom_select="Production", save=Mock(), db_set=Mock())
    invoice = SimpleNamespace(doctype="Sales Invoice", name="TEST INVOICE", company=company.name,
        custom_zatca_status="NOT SUBMITTED", custom_uuid="KEEP UUID", save=Mock(), db_set=Mock())
    docs = {(doc.doctype, doc.name): doc for doc in (device, company, invoice)}
    app = SimpleNamespace(flags={}, session=SimpleNamespace(user="tester@example.invalid"),
        get_doc=Mock(side_effect=lambda doctype, name: docs[doctype, name]),
        db=SimpleNamespace(commit=Mock(), get_value=Mock()),
        ValidationError=ValidationError, PermissionError=PermissionDenied)
    messages = [{"message": "Unrelated parent message"}]
    def msgprint(message, **kwargs):
        if not app.flags.get("mute_messages"):
            messages.append({"message": message, **kwargs})
    def throw(message, exc=ValidationError, **kwargs):
        msgprint(message, **kwargs)
        raise exc(message)
    app.msgprint, app.throw = msgprint, throw
    monkeypatch.setattr(service, "frappe", app)
    monkeypatch.setattr(service, "_", lambda text: text)
    acl = []
    def permission(doctype, ptype, *, doc, user, raise_exception=True):
        acl.append((doctype, ptype, doc, user, raise_exception))
        return True
    monkeypatch.setattr(service, "has_permission", permission)
    submit = Mock(return_value={"validationResults": {"status": "PASS", "errorMessages": []}})
    monkeypatch.setattr(service, "zatca_call_compliance", submit)
    return SimpleNamespace(device=device, company=company, invoice=invoice, app=app,
        messages=messages, acl=acl, submit=submit,
        run=lambda: service.run_device_compliance_summary(device.name, "2026-10-23 09:00:00"))


def no_writes(b):
    for doc in (b.device, b.company, b.invoice):
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
    b.app.db.commit.assert_not_called()
    b.app.db.get_value.assert_not_called()
    assert b.invoice.custom_zatca_status == "NOT SUBMITTED" and b.invoice.custom_uuid == "KEEP UUID"


@pytest.mark.parametrize("selection", [*service.COMPLIANCE_TYPES, None, "legacy-unknown"])
@pytest.mark.parametrize("outcome", ["PASS", "WARNING", "ALREADY", "UNKNOWN", "EXCEPTION"])
@pytest.mark.parametrize("engine", ["v15", "v16"])
def test_saved_device_summary_selects_company_label_once_without_client_credentials(boundary, monkeypatch, selection, outcome, engine):
    b = boundary
    b.company.custom_validation_type = selection
    if engine == "v16":
        def permission(doctype, ptype, *, doc, user, print_logs=True):
            b.acl.append((doctype, ptype, doc, user, print_logs))
            return True
        monkeypatch.setattr(service, "has_permission", permission)
    if outcome == "WARNING":
        b.submit.return_value = {"validationResults": {"status": "WARNING", "warningMessages": [{"code": "TEST"}]}}
    elif outcome == "ALREADY":
        b.submit.return_value = {"_zatca_compliance_status": "ALREADY_COMPLETED", "validationResults": {
            "status": "ERROR", "errorMessages": [{"code": "Submitted before"}]}}
    elif outcome == "UNKNOWN":
        b.submit.return_value = {"http_status": 200}
    elif outcome == "EXCEPTION":
        b.submit.side_effect = ValidationError('Original {"code":"TEST-FAILURE"} <script>')
    original = json.dumps(b.submit.return_value) if outcome != "EXCEPTION" else None
    monkeypatch.setattr(service, "_", lambda text: "ترجمة العرض فقط")
    result = b.run()
    label = selection if selection in service.COMPLIANCE_TYPES else "Simplified Invoice"
    assert result["single_check"] is True and len(result["results"]) == 1
    row = result["results"][0]
    assert row["type"] == label and row["status"] == ("FAIL" if outcome in ("UNKNOWN", "EXCEPTION") else "PASS")
    if outcome == "UNKNOWN":
        assert "cannot be marked as passed" in row["technical_details"]
    if outcome == "EXCEPTION":
        assert row["technical_details"] == 'Original {"code":"TEST-FAILURE"} <script>'
    if outcome != "EXCEPTION":
        assert json.dumps(b.submit.return_value) == original
    b.submit.assert_called_once_with(invoice_number=b.invoice.name, company_name=b.company.name,
        company_abbr=b.company.abbr, source_doc=json.dumps({"doctype": b.device.doctype, "name": b.device.name}),
        validation_type=label, compliance_type="1")
    assert "PRIVATE" not in json.dumps(b.submit.call_args.kwargs)
    assert [tuple(call.args) for call in b.app.get_doc.call_args_list] == [
        (b.device.doctype, b.device.name), ("Company", b.company.name), ("Sales Invoice", b.invoice.name)]
    assert [(row[0], row[1], row[3], row[4]) for row in b.acl] == [
        (doc.doctype, "read", b.app.session.user, False) for doc in (b.device, b.company, b.invoice)]
    assert b.app.flags == {} and len(b.messages) == 1
    no_writes(b)


@pytest.mark.parametrize("doctype", ["ZATCA Multiple Setting", "Company", "Sales Invoice"])
@pytest.mark.parametrize("allowed", [False, None, 1, "yes"])
def test_every_source_requires_literal_read_permission_before_submission(boundary, monkeypatch, doctype, allowed):
    def permission(kind, ptype, *, doc, user, raise_exception=True):
        assert raise_exception is False
        return allowed if kind == doctype else True
    monkeypatch.setattr(service, "has_permission", permission)
    with pytest.raises(PermissionDenied) as raised:
        boundary.run()
    assert str(raised.value) == service.DENIED and raised.value.__context__ is None
    boundary.submit.assert_not_called()
    assert len(boundary.messages) == 2 and boundary.app.flags == {}
    no_writes(boundary)


@pytest.mark.parametrize("name", [None, {}, True, "", " TEST DEVICE", "A\nB", "A\x7fB", "x" * 141])
def test_invalid_device_identity_is_rejected_before_loading(boundary, name):
    with pytest.raises(ValidationError):
        service.run_device_compliance_summary(name, "2026-10-23 09:00:00")
    boundary.app.get_doc.assert_not_called()
    boundary.submit.assert_not_called()


@pytest.mark.parametrize("revision", [None, 1, {}, "PRIVATE", "2026-99-99 09:00:00", "2026-10-23T9:00:00",
                                     "2026-10-23 09:00:00Z", datetime(2026, 10, 23, 9)])
def test_invalid_requested_revision_is_rejected_before_loading(boundary, revision):
    with pytest.raises(ValidationError):
        service.run_device_compliance_summary(boundary.device.name, revision)
    boundary.app.get_doc.assert_not_called()
    boundary.submit.assert_not_called()


@pytest.mark.parametrize("value", [datetime(2026, 10, 23, 10), "2026-10-23 09:01:00",
                                  None, datetime(2026, 10, 23, 9, tzinfo=timezone.utc)])
def test_changed_or_unknown_saved_revision_stops_before_company_load(boundary, value):
    boundary.device.modified = value
    with pytest.raises(ValidationError):
        boundary.run()
    assert boundary.app.get_doc.call_count == 1
    boundary.submit.assert_not_called()


@pytest.mark.parametrize("user", [None, "", "Guest"])
def test_missing_actor_or_guest_cannot_load_source(boundary, user):
    boundary.app.session.user = user
    with pytest.raises(PermissionDenied):
        boundary.run()
    boundary.app.get_doc.assert_not_called()


@pytest.mark.parametrize("field,value", [("custom_linked_doctype", None), ("custom_sample_invoice_number_to_test", ""),
    ("custom_linked_doctype", {}), ("custom_sample_invoice_number_to_test", "x" * 141)])
def test_saved_links_are_required_and_not_taken_from_client_fields(boundary, field, value):
    setattr(boundary.device, field, value)
    with pytest.raises(ValidationError):
        boundary.run()
    boundary.submit.assert_not_called()
    no_writes(boundary)


@pytest.mark.parametrize("doctype", ["ZATCA Multiple Setting", "Company", "Sales Invoice"])
def test_returned_row_must_match_requested_identity(boundary, doctype):
    doc = {row.doctype: row for row in (boundary.device, boundary.company, boundary.invoice)}[doctype]
    requested = boundary.device.name
    doc.name = "OTHER"
    with pytest.raises(ValidationError):
        service.run_device_compliance_summary(requested, "2026-10-23 09:00:00")
    boundary.submit.assert_not_called()


def test_cross_company_sample_is_refused_before_building(boundary):
    boundary.invoice.company = "OTHER COMPANY"
    with pytest.raises(ValidationError) as raised:
        boundary.run()
    assert str(raised.value) == service.MISMATCH
    boundary.submit.assert_not_called()
    no_writes(boundary)


@pytest.mark.parametrize("phase", ["load", "acl", "collector"])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}, {"mute_messages": "parent"}])
def test_outer_failures_never_stringify_private_errors_or_clear_parent_state(boundary, monkeypatch, phase, flags):
    b = boundary
    b.app.flags = dict(flags)
    class PrivateError(Exception):
        def __str__(self):
            raise AssertionError("Never stringify private preparation exception")
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
        monkeypatch.setattr(service, "collect_compliance_results", fail)
    with pytest.raises(ValidationError) as raised:
        b.run()
    expected = service.UNCONFIRMED if phase == "collector" else service.PREPARATION_FAILED
    assert str(raised.value) == expected and raised.value.__context__ is None
    assert b.app.flags == flags
    assert b.messages == [{"message": "Unrelated parent message"}] + ([] if flags.get("mute_messages") else
        [{"message": expected, "title": "Compliance Check Failed"}])
    b.submit.assert_not_called()
    no_writes(b)


@pytest.mark.parametrize("phase", ["load", "submit"])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_interrupts_propagate_without_clearing_parent_flags_or_retrying(boundary, phase, stop):
    target = boundary.app.get_doc if phase == "load" else boundary.submit
    target.side_effect = stop("PRIVATE-INTERRUPT")
    with pytest.raises(stop):
        boundary.run()
    assert boundary.app.flags == {} and len(boundary.messages) == 1
    assert boundary.submit.call_count == (1 if phase == "submit" else 0)
    no_writes(boundary)


def test_shared_revision_accepts_equivalent_naive_comparison_marker(boundary):
    result = service.run_device_compliance_summary(boundary.device.name, "2026-10-23T09:00:00.000000")
    assert result["results"][0]["status"] == "PASS"
    boundary.submit.assert_called_once()


def test_canonical_device_errors_have_actual_arabic_translations():
    with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8", newline="") as source:
        translations = dict(csv.reader(source))
    for key in (service.DENIED, service.CHANGED, service.MISMATCH, service.PREPARATION_FAILED, service.UNCONFIRMED):
        assert any("\u0600" <= char <= "\u06ff" for char in translations[key])
