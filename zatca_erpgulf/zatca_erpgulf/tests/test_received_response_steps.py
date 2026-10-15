"""Actual primary presentation/log steps, entirely mocked HTTP/ERP/File."""

import ast
import csv
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import response_processing as policy, sign_invoice, pos_sign, event_log
from zatca_erpgulf.zatca_erpgulf.tests.test_response_processing import (
    boundary, ROUTES, LOCAL_ERRORS, snapshot, inject_failure, run_adapter, ValidationError,
)


def fail_step(b, module, operation, monkeypatch, stage, error_type):
    if stage != "format":
        return inject_failure(b, module, operation, monkeypatch, stage, error_type)
    doc = b.sales if module is sign_invoice else b.pos
    observed = []
    def formatting(*args):
        observed.append(snapshot(b, doc))
        raise error_type("PRIVATE local formatting/credential/path must not be echoed")
    monkeypatch.setattr(module, "format_zatca_response", formatting)
    return doc, observed


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("status", [303, 400, 401, 403, 406, 409, 503])
@pytest.mark.parametrize("stage", ["format", "log_zatca_event", "hide"])
@pytest.mark.parametrize("error_type", LOCAL_ERRORS)
def test_local_received_step_failure_never_adds_generic_error_writes_for_any_branch(boundary, monkeypatch,
    module, operation, status, stage, error_type):
    b = boundary
    b.response.status_code = status
    doc, observed = fail_step(b, module, operation, monkeypatch, stage, error_type)
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    assert str(error.value) == policy.LOCAL_RESPONSE_REVIEW
    assert error.value.__context__ is error.value.__cause__ is None and not vars(error.value)
    assert "PRIVATE" not in str(error.value)
    b.post.assert_called_once()
    b.frappe.log_error.assert_not_called()
    for owner in (b.company, b.device, b.linked):
        assert owner.custom_pih == "previous"


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.parametrize("error_type", LOCAL_ERRORS)
def test_second_format_failure_preserves_even_prior_legacy_rejection_writes(boundary, monkeypatch,
    module, operation, status, error_type):
    b = boundary
    b.response.status_code = status
    doc = b.sales if module is sign_invoice else b.pos
    calls, observed = [], []
    def formatting(*args):
        calls.append(args)
        if len(calls) == 2:
            observed.append(snapshot(b, doc))
            raise error_type("PRIVATE late rejection presentation error")
        return "TEST RESPONSE"
    monkeypatch.setattr(module, "format_zatca_response", formatting)
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert len(calls) == 2 and len(observed) == 1 and snapshot(b, doc) == observed[0]
    assert doc.custom_zatca_status == "Not Submitted"  # Legacy rejection work already ran.
    if module is sign_invoice and operation == "reporting":
        assert doc.custom_zatca_full_response == b.response.text
    assert error.value.__context__ is None and not vars(error.value)
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("status", [200, 400, 401, 503])
def test_lazy_response_text_failure_is_inside_the_presentation_guard(boundary, monkeypatch, module, operation, status):
    b = boundary
    doc = b.sales if module is sign_invoice else b.pos
    observed = []
    class LazyResponse:
        status_code = status
        @property
        def text(self):
            observed.append(snapshot(b, doc))
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "PRIVATE lazy text failure")
    b.post.return_value = LazyResponse()
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("status", [400, 401, 503])
def test_normal_rejection_keeps_the_existing_legacy_writes_and_exception_family(boundary, module, operation, status):
    b = boundary
    b.response.status_code = status
    doc = b.sales if module is sign_invoice else b.pos
    with pytest.raises(ValidationError) as error:
        run_adapter(b, module, operation)
    assert not isinstance(error.value, policy.LocalResponseProcessingError)
    assert str(status) in str(error.value)
    if module is sign_invoice and operation == "reporting":
        assert doc.save.call_count == b.frappe.db.commit.call_count == 2
        doc.db_set.assert_not_called()
        assert doc.custom_zatca_status == "Not Submitted" and doc.custom_uuid == "test-existing-uuid"
    elif module is sign_invoice:
        assert doc.db_set.call_count == 3 and doc.custom_zatca_status == "503 Service Unavailable"
        assert doc.custom_uuid == "test-existing-uuid"
        doc.save.assert_not_called()
        b.frappe.db.commit.assert_not_called()
    else:
        # POS Reporting ALSO links request XML BEFORE HTTP. Keep that existing
        # write in the golden sequence, not just the four response-field writes.
        assert doc.db_set.call_count == 5
        expected_fields = (["custom_ksa_einvoicing_xml", "custom_uuid", "custom_zatca_status",
            "custom_zatca_full_response", "custom_zatca_full_response"] if operation == "reporting" else
            ["custom_uuid", "custom_zatca_status", "custom_zatca_full_response", "custom_zatca_full_response", "custom_zatca_status"])
        assert [call.args[0] for call in doc.db_set.call_args_list] == expected_fields
        assert doc.custom_uuid == "Not Submitted"
        assert doc.custom_zatca_status == ("Not Submitted" if operation == "reporting" else "503 Service Unavailable")
        doc.save.assert_not_called()
        b.frappe.db.commit.assert_not_called()
    assert doc.custom_zatca_full_response.startswith("Error:")  # Existing intentional-rejection wrapper is NOT fixed here.
    b.post.assert_called_once()
    for owner in (b.company, b.device, b.linked):
        owner.save.assert_not_called()


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("status", [400, 409, 503])
@pytest.mark.parametrize("stage", ["format", "log_zatca_event", "hide"])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_previously_unhandled_errors_and_interruptions_keep_exact_propagation(boundary, monkeypatch,
    module, operation, status, stage, error_type):
    b = boundary
    b.response.status_code = status
    doc, observed = fail_step(b, module, operation, monkeypatch, stage, error_type)
    with pytest.raises(error_type) as error:
        run_adapter(b, module, operation)
    assert type(error.value) is error_type
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES)
def test_pre_request_notification_failure_is_not_relabelled_as_received_response(boundary, module, operation):
    b = boundary
    def publish(event, *args, **kwargs):
        if event == "show_gif":
            raise ValueError("PRIVATE pre-request display failure")
    b.frappe.publish_realtime.side_effect = publish
    with pytest.raises(ValidationError):
        run_adapter(b, module, operation)
    b.post.assert_not_called()


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("error_type", [requests.Timeout, requests.ConnectionError])
def test_transport_unknown_never_enters_the_received_step_wrapper(boundary, module, operation, error_type):
    b = boundary
    doc = b.sales if module is sign_invoice else b.pos
    observed = []
    original = error_type("PRIVATE unknown transport")
    def post(*args, **kwargs):
        observed.append(snapshot(b, doc))
        raise original
    b.post.side_effect = post
    with pytest.raises(error_type) as error:
        run_adapter(b, module, operation)
    assert error.value is original and snapshot(b, doc) == observed[0]
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("stage", ["format", "log_zatca_event", "hide"])
def test_error_status_local_step_message_uses_existing_arabic_catalog(boundary, monkeypatch, module, operation, stage):
    b = boundary
    b.response.status_code = 401
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(policy, "_", lambda message: entries[message])
    fail_step(b, module, operation, monkeypatch, stage, ValidationError)
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert str(error.value) == entries[policy.LOCAL_RESPONSE_REVIEW]
    assert error.value.__context__ is None


def bind_actual_event_logger(b, module, monkeypatch):
    """Run the real event logger with synthetic documents/time/fallback only."""
    event_doc = SimpleNamespace(insert=Mock())
    original = b.frappe.get_doc.side_effect
    def get_doc(doctype, name=None):
        if isinstance(doctype, dict) and doctype.get("doctype") == "ZATCA ERPGulf Event Log":
            return event_doc
        return original(doctype, name)
    b.frappe.get_doc.side_effect = get_doc
    monkeypatch.setattr(event_log, "frappe", b.frappe)
    monkeypatch.setattr(event_log, "now_datetime", lambda: "2026-10-16 12:00:00")
    monkeypatch.setattr(module, "log_zatca_event", event_log.log_zatca_event)
    return event_doc


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("failure", ["insert", "commit"])
def test_real_event_logger_fallback_failure_cannot_trigger_additional_generic_api_writes(boundary, monkeypatch,
    module, operation, failure):
    b = boundary
    b.response.status_code = 401
    doc = b.sales if module is sign_invoice else b.pos
    event_doc = bind_actual_event_logger(b, module, monkeypatch)
    if failure == "insert":
        event_doc.insert.side_effect = ValidationError("PRIVATE event insert error")
    else:
        b.frappe.db.commit.side_effect = ValidationError("PRIVATE event commit error")
    observed = []
    def fallback(*args):
        observed.append(snapshot(b, doc))
        raise ValidationError("PRIVATE fallback logger error")
    b.frappe.log_error.side_effect = fallback
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    assert b.frappe.db.commit.call_count == (failure == "commit")  # Callback's own attempt, not an added API commit.
    assert str(error.value) == policy.LOCAL_RESPONSE_REVIEW and error.value.__context__ is None
    event_doc.insert.assert_called_once_with(ignore_permissions=True)
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES)
def test_existing_event_logger_swallowed_failure_is_not_mistaken_for_a_new_custody_guarantee(boundary, monkeypatch,
    module, operation):
    b = boundary
    b.response.status_code = 401
    event_doc = bind_actual_event_logger(b, module, monkeypatch)
    event_doc.insert.side_effect = ValidationError("PRIVATE swallowed event failure")
    # The real logger catches/logs the insert failure and returns None. This
    # bounded API guard cannot detect swallowed errors and MUST NOT reinterpret
    # None or rewrite logger transaction policy as an unrelated compatibility fix.
    with pytest.raises(ValidationError) as error:
        run_adapter(b, module, operation)
    assert not isinstance(error.value, policy.LocalResponseProcessingError)
    b.frappe.log_error.assert_called_once()
    b.post.assert_called_once()


@pytest.mark.parametrize("value", [None, False, 0, "unchanged", b"exact bytes"])
def test_received_step_forwards_arguments_and_return_value_without_classifying_it(monkeypatch, value):
    monkeypatch.setattr(policy, "_", lambda message: message)
    step = Mock(return_value=value)
    assert policy.run_received_response_step(step, "argument", named="keyword", validation_error_type=ValidationError) is value
    step.assert_called_once_with("argument", named="keyword")


def test_response_message_forwards_exact_text_and_status_and_helper_has_no_io(monkeypatch):
    formatter = Mock(return_value="rendered")
    response = SimpleNamespace(text="exact text", status_code=401)
    result = policy.run_received_response_step(policy.received_response_message, formatter, response,
        validation_error_type=ValidationError)
    assert result == "rendered"
    formatter.assert_called_once_with("exact text", 401)
    source = inspect.getsource(policy)
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr in (
        "commit", "rollback", "set_value", "save", "db_set", "post", "get_doc", "log_error") for node in calls)


@pytest.mark.parametrize("module,operation", ROUTES)
def test_only_presentation_log_and_hide_are_wrapped_after_transport_not_deliberate_throws(module, operation):
    tree = ast.parse(inspect.getsource(getattr(module, operation + "_api")))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    post = [node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "post"]
    wrappers = [node for node in calls if isinstance(node.func, ast.Name) and node.func.id == "response_step"]
    renders = [node for node in calls if isinstance(node.func, ast.Name) and node.func.id == "render_response"]
    assert len(post) == 1 and len(wrappers) == 3 and renders
    assert all(node.lineno > post[0].lineno for node in (*wrappers, *renders))
    assert sum(isinstance(node.args[0], ast.Name) and node.args[0].id == "log_zatca_event" for node in wrappers) == 2
    hide = [node for node in wrappers if isinstance(node.args[0], ast.Attribute)]
    assert len(hide) == 1 and hide[0].args[0].attr == "publish_realtime" and hide[0].args[1].value == "hide_gif"
    assert not any(isinstance(node.func, ast.Name) and node.func.id == "format_zatca_response" for node in calls)
