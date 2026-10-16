"""Diagnostic writer contracts, synthetic Frappe only; never HTTP/site init."""

import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import event_log, response_processing
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import ValidationError


@pytest.fixture
def writer(monkeypatch):
    doc = SimpleNamespace(insert=Mock())
    runtime = SimpleNamespace(get_doc=Mock(return_value=doc),
        db=SimpleNamespace(commit=Mock(), rollback=Mock()), log_error=Mock())
    clock = Mock(return_value="2026-10-16 12:00:00")
    monkeypatch.setattr(event_log, "frappe", runtime)
    monkeypatch.setattr(event_log, "now_datetime", clock)
    monkeypatch.setattr(response_processing, "_", lambda message: message)
    return SimpleNamespace(doc=doc, runtime=runtime, clock=clock)


BODIES = (
    (' \n{"validationResults": {"status": "ERROR"}}\n ', ' \n{"validationResults": {"status": "ERROR"}}\n '),
    ('Status Code: 400<br>ZATCA Response: {"a":1}<br>', '{"a":1}'),
    ('الرد: {"message":"اختبار"}', '{"message":"اختبار"}'),
    (None, ""), ("Not Submitted", "Not Submitted"), (b'{"a":1}', '{"a":1}'),
    (b"\xff", "\ufffd"), ({"a": 1}, '{"a":1}'),
)


@pytest.mark.parametrize("body,expected", BODIES)
@pytest.mark.parametrize("uuid,title", [(None, None), ("TEST-UUID", "TEST-TITLE"), ("", "")])
@pytest.mark.parametrize("staged", [False, True])
def test_exact_diagnostic_payload_and_distinct_permission_transaction_contract(writer, body, expected, uuid, title, staged):
    callback = event_log.stage_zatca_event if staged else event_log.log_zatca_event
    result = callback("TEST-INVOICE", body, "Failed (HTTP 400)", uuid=uuid, title=title)
    writer.runtime.get_doc.assert_called_once_with({
        "doctype": "ZATCA ERPGulf Event Log", "invoice_number": "TEST-INVOICE",
        "title": title or "ZATCA API Call for TEST-INVOICE", "time": "2026-10-16 12:00:00",
        "api_response": expected, "custom_uuid": uuid or "", "status": "Failed (HTTP 400)",
    })
    writer.doc.insert.assert_called_once_with(ignore_permissions=not staged)
    assert result is (event_log.EventLogWriteResult.INSERT_RETURNED if staged else None)
    assert writer.runtime.db.commit.call_count == (not staged)
    writer.runtime.db.rollback.assert_not_called()
    writer.runtime.log_error.assert_not_called()


ERRORS = (ValueError, TypeError, KeyError, ValidationError, PermissionError, RuntimeError, KeyboardInterrupt, SystemExit)


@pytest.mark.parametrize("error_type", ERRORS)
@pytest.mark.parametrize("stage", ["clock", "normalizer", "get_doc", "insert"])
def test_staged_errors_propagate_same_object_without_fallback_commit_retry_or_redaction_claim(writer, monkeypatch, stage, error_type):
    error = error_type("PRIVATE synthetic error; owner must not export raw exceptions")
    target = {"clock": writer.clock, "get_doc": writer.runtime.get_doc, "insert": writer.doc.insert}.get(stage)
    if stage == "normalizer":
        monkeypatch.setattr(event_log, "extract_raw_response", Mock(side_effect=error))
    else:
        target.side_effect = error
    with pytest.raises(error_type) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Warning")
    assert raised.value is error
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.db.rollback.assert_not_called()
    writer.runtime.log_error.assert_not_called()
    assert writer.doc.insert.call_count == (stage == "insert")


@pytest.mark.parametrize("error_type", [ValueError, TypeError, KeyError, ValidationError])
@pytest.mark.parametrize("stage", ["clock", "normalizer", "get_doc", "insert"])
def test_explicit_received_step_converts_staged_errors_without_committing_or_swallowing(writer, monkeypatch, stage, error_type):
    target = {"clock": writer.clock, "get_doc": writer.runtime.get_doc, "insert": writer.doc.insert}.get(stage)
    error = error_type("PRIVATE staging fault")
    if stage == "normalizer":
        monkeypatch.setattr(event_log, "extract_raw_response", Mock(side_effect=error))
    else:
        target.side_effect = error
    with pytest.raises(response_processing.LocalResponseProcessingError) as raised:
        response_processing.run_received_response_step(event_log.stage_zatca_event,
            "TEST-INVOICE", "TEST-BODY", "Warning", validation_error_type=ValidationError)
    assert str(raised.value) == response_processing.LOCAL_RESPONSE_REVIEW
    assert raised.value.__context__ is raised.value.__cause__ is None and not vars(raised.value)
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.db.rollback.assert_not_called()
    writer.runtime.log_error.assert_not_called()


@pytest.mark.parametrize("stage", ["clock", "normalizer", "get_doc", "insert", "commit"])
@pytest.mark.parametrize("error_type", [ValueError, ValidationError, PermissionError, RuntimeError])
def test_legacy_failure_still_calls_fallback_once_and_returns_none(writer, monkeypatch, stage, error_type):
    error = error_type("SYNTHETIC legacy diagnostic error")
    target = {"clock": writer.clock, "get_doc": writer.runtime.get_doc,
        "insert": writer.doc.insert, "commit": writer.runtime.db.commit}.get(stage)
    if stage == "normalizer":
        monkeypatch.setattr(event_log, "extract_raw_response", Mock(side_effect=error))
    else:
        target.side_effect = error
    assert event_log.log_zatca_event("TEST-INVOICE", "TEST-BODY", "Failed") is None
    writer.runtime.log_error.assert_called_once_with(f"Failed to log ZATCA Event: {str(error)}", "ZATCA Event Log")
    assert writer.runtime.db.commit.call_count == (stage == "commit")
    writer.runtime.db.rollback.assert_not_called()


def test_staging_has_no_permission_override_catch_transaction_or_runtime_caller():
    tree = ast.parse(inspect.getsource(event_log.stage_zatca_event))
    assert not any(isinstance(node, (ast.Try, ast.ExceptHandler)) for node in ast.walk(tree))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert len(calls) == 1 and calls[0].func.id == "_insert_zatca_event"
    assert any(keyword.arg == "ignore_permissions" and keyword.value.value is False for keyword in calls[0].keywords)
    assert list(event_log.EventLogWriteResult) == [event_log.EventLogWriteResult.INSERT_RETURNED]
    # Refactoring the legacy wrapper must not silently switch any invoice path
    # to staging before independent receipt custody/parent lifecycle is ready.
    root = Path(event_log.__file__).parent
    for path in root.glob("*.py"):
        if path.name != "event_log.py":
            assert "stage_zatca_event" not in path.read_text(), path.name


@pytest.mark.parametrize("insert_result", [None, False, "UNVERIFIED CALLBACK VALUE"])
def test_result_means_call_returned_not_framework_value_or_durability(writer, insert_result):
    writer.doc.insert.return_value = insert_result
    result = event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Success")
    assert result is event_log.EventLogWriteResult.INSERT_RETURNED
    assert result.value == "INSERT_RETURNED"  # NOT the caller's diagnostic Success label.
    writer.runtime.db.commit.assert_not_called()


def test_source_schema_gap_is_characterized_not_silently_migrated():
    root = Path(event_log.__file__).parent
    schema = json.loads((root / "doctype/zatca_erpgulf_event_log/zatca_erpgulf_event_log.json").read_text())
    custom = json.loads((root.parent / "fixtures/custom_field.json").read_text())
    fields = {field["fieldname"] for field in schema["fields"]}
    fields.update(field["fieldname"] for field in custom if field.get("dt") == "ZATCA ERPGulf Event Log")
    assert {"title", "invoice_number", "time", "api_response", "custom_uuid"} <= fields
    # Source metadata lacks the legacy payload's status field. ORM insert return
    # cannot certify field coverage. Installed schema may differ: no site lookup.
    assert "status" not in fields
