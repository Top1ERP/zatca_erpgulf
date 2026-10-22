"""Synthetic CSID failures; no tenant, real credentials, HTTP or file writes."""

import csv
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.operation_messages import (
    CSIDProgress, CSID_PROGRESS_REVIEW, csid_local_failure, csid_request_rejection,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_lifecycle import csid_writer, pair
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import boundary, materials, ValidationError


@pytest.fixture
def display(csid_writer, monkeypatch):
    b = csid_writer
    b.environment = "Production"
    b.frappe.local = SimpleNamespace(lang="en")
    b.frappe.message_log = ["Parent-owned message"]
    b.visible = []
    b.events = []
    with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8") as source:
        b.catalog = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}

    def translate(key):
        b.translated.append(key)
        return b.catalog.get(key, key) if b.frappe.local.lang == "ar" else key

    def msgprint(value, **kwargs):
        if not b.frappe.flags.get("mute_messages"):
            b.visible.append(value)
            b.frappe.message_log.append(value)

    def throw(message, **kwargs):
        msgprint({"message": message, **kwargs})
        raise ValidationError(message)

    def publish(event, *args, **kwargs):
        b.events.append(event)

    monkeypatch.setattr(client, "_", translate)
    b.frappe.msgprint = Mock(side_effect=msgprint)
    b.frappe.throw = Mock(side_effect=throw)
    b.frappe.publish_realtime = Mock(side_effect=publish)
    b.frappe.db.rollback = Mock()
    b.frappe.delete_doc = Mock()
    b.text = translate
    return b


def invoke(b, source, purpose, identity=None):
    doc = getattr(b, source)
    function = client.create_csid if purpose == "compliance" else client.production_csid
    return inspect.unwrap(function)(identity if identity is not None else
                                   {"doctype": doc.doctype, "name": doc.name}, "TC")


def assert_no_cleanup(b):
    b.frappe.db.rollback.assert_not_called()
    b.frappe.delete_doc.assert_not_called()
    assert b.frappe.message_log[0] == "Parent-owned message"


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("stage,code", [
    (0, "CSID_PREPARATION_FAILED"), (1, "CSID_REQUEST_OUTCOME_UNKNOWN"),
    (2, "CSID_PROCESSING_UNCONFIRMED"), (3, "CSID_STORAGE_UNCONFIRMED"),
    (4, "CSID_LOCAL_COMPLETION_UNCONFIRMED"),
])
@pytest.mark.parametrize("overlay", [False, True])
def test_local_projection_is_english_and_never_confirms_remote_or_durable_success(purpose, stage, code, overlay):
    progress = CSIDProgress(stage >= 1, stage >= 2, stage >= 3, stage >= 4, overlay)
    result = csid_local_failure(purpose, progress)
    assert result["code"] == code and result["status"] == "ERROR"
    assert result["http_status"] is None and result["message"].isascii()
    assert set(result) == {"status", "purpose", "code", "message", "http_status"}


@pytest.mark.parametrize("progress", [None, {}, CSIDProgress(request_started=1),
    CSIDProgress(response_received=True), CSIDProgress(save_started=True),
    CSIDProgress(save_completed=True), CSIDProgress(overlay_started="PRIVATE")])
def test_invalid_progress_fails_with_static_diagnostic(progress):
    with pytest.raises(ValueError, match="^Invalid CSID progress\\.$"):
        csid_local_failure("compliance", progress)


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("fault,stage", [("lookup", 0), ("input", 0), ("show", 0),
    ("timeout", 1), ("connection", 1), ("runtime", 1), ("response", 2),
    ("missing-secret", 2), ("save", 3), ("partial-save", 3), ("presentation", 4)])
def test_actual_public_boundary_redacts_local_faults_and_preserves_partial_effects(display, source, purpose, lang, fault, stage):
    b = display
    doc = getattr(b, source)
    b.frappe.local.lang = lang
    b.frappe.flags = {"mute_messages": False, "parent": "unchanged"}
    identity = None
    if fault == "lookup":
        b.frappe.get_doc.side_effect = RuntimeError("PRIVATE-LOADER")
    elif fault == "input":
        identity = "PRIVATE invalid JSON"
    elif fault == "show":
        publish = b.frappe.publish_realtime.side_effect

        def show(event, *args, **kwargs):
            publish(event, *args, **kwargs)
            if event == "show_gif":
                b.frappe.msgprint("PRIVATE child popup")
                raise RuntimeError("PRIVATE-SHOW")

        b.frappe.publish_realtime.side_effect = show
    elif fault in ("timeout", "connection", "runtime"):
        kind = {"timeout": requests.exceptions.Timeout,
                "connection": requests.exceptions.ConnectionError, "runtime": RuntimeError}[fault]
        b.post.side_effect = kind("PRIVATE URL?secret=PRIVATE")
    elif fault == "response":
        b.post.return_value = None
    elif fault == "missing-secret":
        del b.data["secret"]
        b.reply.text = json.dumps(b.data)
    elif fault in ("save", "partial-save"):
        def save(**kwargs):
            assert b.frappe.flags["mute_messages"] is True
            b.frappe.msgprint("PRIVATE child storage popup")
            if fault == "partial-save":
                doc.partial_effect = "preserved"
                b.frappe.db.commit()
            raise OSError("PRIVATE-STORAGE")

        doc.save.side_effect = save
    else:
        b.frappe.msgprint.side_effect = RuntimeError("PRIVATE-PRESENTATION")
    with pytest.raises(ValidationError) as raised:
        invoke(b, source, purpose, identity)
    expected = csid_local_failure(purpose, CSIDProgress(stage >= 1, stage >= 2, stage >= 3, stage >= 4))
    assert str(raised.value) == b.text(expected["message"])
    assert len(b.visible) == 1
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert "PRIVATE" not in str(raised.value) + repr(b.visible)
    assert b.frappe.flags == {"mute_messages": False, "parent": "unchanged"}
    assert b.frappe.local.lang == lang
    assert b.post.call_count == (0 if stage == 0 else 1)
    assert doc.save.call_count == (1 if stage >= 3 else 0)
    assert b.events == ([] if fault in ("lookup", "input") else ["show_gif", "hide_gif"])
    if fault == "partial-save":
        assert doc.partial_effect == "preserved"
        b.frappe.db.commit.assert_called_once_with()
    else:
        b.frappe.db.commit.assert_not_called()
    assert_no_cleanup(b)


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("outcome", ["saved", "http", "timeout"])
def test_progress_cleanup_failure_preserves_the_primary_result_and_does_not_retry(display, source, purpose, outcome):
    b = display
    if outcome == "http":
        b.reply.status_code, b.reply.text = 401, "PRIVATE-BODY"
    if outcome == "timeout":
        b.post.side_effect = requests.exceptions.Timeout("PRIVATE-URL")
    publish = b.frappe.publish_realtime.side_effect

    def cleanup(event, *args, **kwargs):
        publish(event, *args, **kwargs)
        if event == "hide_gif":
            b.frappe.msgprint("PRIVATE cleanup popup")
            raise RuntimeError("PRIVATE-CLEANUP")

    b.frappe.publish_realtime.side_effect = cleanup
    expected = csid_request_rejection(purpose, 401, "") if outcome == "http" else csid_local_failure(
        purpose, CSIDProgress(True, outcome == "saved", outcome == "saved", outcome == "saved"))
    with pytest.raises(ValidationError) as raised:
        invoke(b, source, purpose)
    assert expected["message"] in str(raised.value)
    assert CSID_PROGRESS_REVIEW in str(raised.value)
    assert len(b.visible) == 1 and "PRIVATE" not in repr(b.visible)
    assert b.post.call_count == 1
    assert getattr(b, source).save.call_count == (1 if outcome == "saved" else 0)
    assert b.events == ["show_gif", "hide_gif"]
    assert b.frappe.flags == {}
    assert_no_cleanup(b)


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
@pytest.mark.parametrize("stage", ["lookup", "transport", "save"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
def test_cancellation_propagates_with_flags_restored_and_best_effort_progress_cleanup(display, stop, stage, purpose):
    b = display
    b.frappe.flags = {"mute_messages": False, "parent": "keep"}
    interruption = stop("synthetic cancellation")
    if stage == "lookup":
        b.frappe.get_doc.side_effect = interruption
    elif stage == "transport":
        b.post.side_effect = interruption
    else:
        b.company.save.side_effect = interruption
    with pytest.raises(stop) as raised:
        invoke(b, "company", purpose)
    assert raised.value is interruption
    assert b.frappe.flags == {"mute_messages": False, "parent": "keep"}
    assert not b.visible
    assert b.events == ([] if stage == "lookup" else ["show_gif", "hide_gif"])
    assert b.post.call_count == (0 if stage == "lookup" else 1)
    assert_no_cleanup(b)


@pytest.mark.parametrize("value", [None, False, True, "parent-owned"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
def test_parent_mute_setting_and_messages_are_not_overwritten(display, value, purpose):
    b = display
    b.frappe.flags = {"parent": "keep"} if value is None else {"parent": "keep", "mute_messages": value}
    original = dict(b.frappe.flags)
    b.post.side_effect = RuntimeError("PRIVATE")
    with pytest.raises(ValidationError):
        invoke(b, "company", purpose)
    assert b.frappe.flags == original
    assert len(b.visible) == (0 if value else 1)
    assert_no_cleanup(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
def test_early_private_worker_return_cannot_fabricate_success(display, monkeypatch, purpose):
    b = display
    name = "_create_csid" if purpose == "compliance" else "_production_csid"
    monkeypatch.setattr(client, name, lambda *args: None)
    with pytest.raises(ValidationError, match="CSID preparation failed"):
        invoke(b, "company", purpose)
    b.post.assert_not_called()
    b.company.save.assert_not_called()
    assert len(b.visible) == 1


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("lang", ["en", "ar"])
@pytest.mark.parametrize("purpose,fault", [("compliance", "identity"), ("production", "identity"),
    ("compliance", "route"), ("production", "route"), ("compliance", "csr"),
    ("production", "auth"), ("production", "request-id")])
def test_preparation_child_errors_are_muted_and_never_start_transport(display, monkeypatch, source, lang, purpose, fault):
    b = display
    doc = getattr(b, source)
    b.frappe.local.lang = lang
    identity = {} if fault == "identity" else None
    if fault == "route":
        def route(*args, **kwargs):
            b.frappe.throw("PRIVATE child configuration error")

        monkeypatch.setattr(client, "get_company_api_route" if purpose == "compliance" else "get_compliance_api_url", route)
    if fault == "csr":
        doc.custom_csr_data = ""
    if fault == "auth":
        doc.custom_basic_auth_from_csid = ""
    if fault == "request-id":
        doc.custom_compliance_request_id_ = ""
    result = csid_local_failure(purpose, CSIDProgress())
    with pytest.raises(ValidationError) as raised:
        invoke(b, source, purpose, identity)
    assert str(raised.value) == b.text(result["message"])
    assert len(b.visible) == 1 and "PRIVATE" not in repr(b.visible)
    assert raised.value.__context__ is None
    b.post.assert_not_called()
    doc.save.assert_not_called()
    assert not b.events and b.frappe.flags == {}
    assert_no_cleanup(b)


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
def test_raw_exception_is_never_stringified_for_public_failure(display, source, purpose):
    class OpaqueError(Exception):
        def __str__(self):
            raise AssertionError("Raw exception must not be inspected")

    b = display
    b.post.side_effect = OpaqueError()
    with pytest.raises(ValidationError, match="request outcome is unknown"):
        invoke(b, source, purpose)
    assert len(b.visible) == 1 and b.post.call_count == 1
    assert_no_cleanup(b)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
def test_presentation_hook_partial_message_effect_is_not_erased_or_retried(display, purpose):
    b = display
    render = b.frappe.msgprint.side_effect

    def partial(value, **kwargs):
        render(value, **kwargs)
        raise RuntimeError("PRIVATE hook failed after rendering")

    b.frappe.msgprint.side_effect = partial
    with pytest.raises(ValidationError, match="local completion could not be confirmed"):
        invoke(b, "company", purpose)
    # A custom hook's already-emitted output is not erased/rolled back. Only
    # the final app-owned error can be consolidated after that partial effect.
    assert len(b.visible) == 2
    assert "PRIVATE" not in repr(b.visible)
    assert b.post.call_count == 1 and b.company.save.call_count == 1
    assert_no_cleanup(b)
