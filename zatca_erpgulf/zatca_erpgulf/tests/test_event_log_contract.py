"""Diagnostic writer contracts, synthetic Frappe only; never HTTP/site init."""

import ast
import csv
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from werkzeug.local import Local, LocalProxy

from zatca_erpgulf.zatca_erpgulf import event_log, response_processing
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import ValidationError, Document


def source_event_meta(*, tuple_fields=False):
    """Synthetic merged source metadata; never Frappe/site metadata discovery."""
    root = Path(event_log.__file__).parent
    schema = json.loads((root / "doctype/zatca_erpgulf_event_log/zatca_erpgulf_event_log.json").read_text())
    custom = json.loads((root.parent / "fixtures/custom_field.json").read_text())
    fields = [Document(**field) for field in schema["fields"]]
    fields.extend(Document(**field) for field in custom if field.get("dt") == event_log.EVENT_LOG_DOCTYPE)
    meta = Document(name=schema["name"], fields=tuple(fields) if tuple_fields else fields)
    meta.get_field = lambda name: next((field for field in meta.fields if field.fieldname == name), None)
    return meta


@pytest.fixture
def writer(monkeypatch):
    doc = SimpleNamespace(insert=Mock())
    runtime = SimpleNamespace(get_doc=Mock(return_value=doc),
        get_meta=Mock(return_value=source_event_meta()),
        db=SimpleNamespace(commit=Mock(), rollback=Mock(), _conn=object()), log_error=Mock())
    clock = Mock(return_value="2026-10-16 12:00:00")
    monkeypatch.setattr(event_log, "frappe", runtime)
    monkeypatch.setattr(event_log, "now_datetime", clock)
    monkeypatch.setattr(event_log, "_", lambda message: message)
    monkeypatch.setattr(response_processing, "_", lambda message: message)
    return SimpleNamespace(doc=doc, runtime=runtime, clock=clock)


BODIES = (
    (' \n{"validationResults": {"status": "ERROR"}}\n ', ' \n{"validationResults": {"status": "ERROR"}}\n '),
    ('Status Code: 400<br>ZATCA Response: {"a":1}<br>', '{"a":1}'),
    ('الرد: {"message":"اختبار"}', '{"message":"اختبار"}'),
    (None, ""), ("Not Submitted", "Not Submitted"), (b'{"a":1}', '{"a":1}'),
    (b"\xff", "\ufffd"), ({"a": 1}, '{"a":1}'),
)


@pytest.mark.parametrize("stage", ["metadata", "clock", "normalizer", "document", "source_before", "source_after", "insert"])
@pytest.mark.parametrize("change", ["wrapper", "raw", "detached", "proxy_target"])
def test_staging_refuses_parent_identity_drift_without_cleaning_or_reconnecting(writer, monkeypatch, stage, change):
    parent, raw = writer.runtime.db, writer.runtime.db._conn
    replacement = SimpleNamespace(_conn=raw, commit=Mock(), rollback=Mock(), close=Mock(), connect=Mock())
    local = Local()
    local.db = parent
    if change == "proxy_target":
        writer.runtime.db = LocalProxy(local, "db")
    def mutate():
        if change == "wrapper":
            writer.runtime.db = replacement  # Same raw handle, different owner.
        elif change == "raw":
            parent._conn = object()
        elif change == "detached":
            parent._conn = None
        else:
            local.db = replacement  # The proxy object itself does not change.
    check = Mock(return_value=True)
    if stage in ("source_before", "source_after"):
        def source_check():
            if check.call_count == (1 if stage == "source_before" else 2):
                mutate()
            return True
        check.side_effect = source_check
    elif stage == "normalizer":
        def normalize(text):
            mutate()
            return text
        monkeypatch.setattr(event_log, "extract_raw_response", normalize)
    else:
        target = {"metadata": writer.runtime.get_meta, "clock": writer.clock,
            "document": writer.runtime.get_doc, "insert": writer.doc.insert}[stage]
        returned = target.return_value
        def changed(*args, **kwargs):
            mutate()
            return returned
        target.side_effect = changed
    with pytest.raises(RuntimeError) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "PRIVATE BODY", "Observed", source_recheck=check)
    assert str(raised.value) == "Diagnostic database context changed or is unavailable. Review the retained response and any staged event. Do not resend automatically."
    assert raised.value.__context__ is raised.value.__cause__ is None and not vars(raised.value)
    assert writer.doc.insert.call_count == (stage in ("insert", "source_after"))
    parent.commit.assert_not_called()
    parent.rollback.assert_not_called()
    for action in (replacement.commit, replacement.rollback, replacement.close, replacement.connect):
        action.assert_not_called()
    writer.runtime.log_error.assert_not_called()


def test_stable_context_local_proxy_does_not_confuse_proxy_with_database_owner(writer):
    local = Local()
    local.db = writer.runtime.db
    writer.runtime.db = LocalProxy(local, "db")
    assert event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Observed") is event_log.EventLogWriteResult.INSERT_RETURNED
    local.db.commit.assert_not_called()
    local.db.rollback.assert_not_called()


@pytest.mark.parametrize("unavailable", ["database", "raw", "raw_attribute", "unbound_proxy", "attribute_fault"])
def test_staging_unavailable_parent_fails_before_metadata_without_implicit_initialization(writer, unavailable):
    parent = writer.runtime.db
    if unavailable == "database":
        writer.runtime.db = None
    elif unavailable == "raw":
        parent._conn = None
    elif unavailable == "raw_attribute":
        del parent._conn
    elif unavailable == "unbound_proxy":
        writer.runtime.db = LocalProxy(Local(), "db")
    else:
        class FaultedOwner:
            @property
            def _conn(self):
                raise RuntimeError("PRIVATE owner details")
        writer.runtime.db = FaultedOwner()
    with pytest.raises(event_log.EventLogParentError) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "PRIVATE BODY", "Observed")
    assert str(raised.value) == event_log.EVENT_LOG_PARENT_REVIEW
    assert raised.value.__context__ is raised.value.__cause__ is None and not vars(raised.value)
    writer.runtime.get_meta.assert_not_called()
    writer.runtime.get_doc.assert_not_called()
    parent.commit.assert_not_called()
    parent.rollback.assert_not_called()
    writer.runtime.log_error.assert_not_called()


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_parent_identity_interruptions_are_not_masked_or_cleaned(writer, late, error_type):
    parent, raw = writer.runtime.db, writer.runtime.db._conn
    original = error_type("PRIVATE interrupted identity read")
    class InterruptedOwner:
        reads = 0
        @property
        def _conn(self):
            self.reads += 1
            if self.reads > int(late):
                raise original
            return raw
    writer.runtime.db = InterruptedOwner()
    with pytest.raises(error_type) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "PRIVATE BODY", "Observed")
    assert raised.value is original
    writer.runtime.get_doc.assert_not_called()
    parent.commit.assert_not_called()
    parent.rollback.assert_not_called()


def test_parent_review_is_arabic_and_acknowledges_possible_insert(writer, monkeypatch):
    with (Path(event_log.__file__).parents[1] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(event_log, "_", lambda message: entries[message])
    writer.doc.insert.side_effect = lambda **options: setattr(writer.runtime.db, "_conn", None)
    with pytest.raises(event_log.EventLogParentError) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "PRIVATE BODY", "Observed")
    assert str(raised.value) == entries[event_log.EVENT_LOG_PARENT_REVIEW]
    assert raised.value.__context__ is None
    writer.doc.insert.assert_called_once_with(ignore_permissions=False)
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.db.rollback.assert_not_called()


def test_legacy_logger_is_not_gated_by_new_parent_identity_preflight(writer):
    writer.runtime.db._conn = None
    assert event_log.log_zatca_event("TEST-INVOICE", "TEST-BODY", "Observed") is None
    writer.doc.insert.assert_called_once_with(ignore_permissions=True)
    writer.runtime.db.commit.assert_called_once()
    writer.runtime.get_meta.assert_not_called()


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
    assert writer.runtime.get_meta.call_count == staged


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
    insert = [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == "_insert_zatca_event"]
    preflight = [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == "require_event_log_schema"]
    assert sorted(call.func.id if isinstance(call.func, ast.Name) else call.func.attr for call in calls) == sorted([
        "_pin_event_parent", "require_event_log_schema", "get_meta", "parent_check",
        "parent_check", "_recheck_event_source", "parent_check", "_insert_zatca_event"])
    assert len(insert) == len(preflight) == 1
    assert preflight[0].lineno < insert[0].lineno
    assert any(keyword.arg == "ignore_permissions" and keyword.value.value is False for keyword in insert[0].keywords)
    assert list(event_log.EventLogWriteResult) == [event_log.EventLogWriteResult.INSERT_RETURNED]
    for helper in (event_log._pin_event_parent, event_log._event_parent_identity):
        helper_tree = ast.parse(inspect.getsource(helper))
        forbidden = {"connect", "get_connection", "ping", "commit", "rollback", "close", "sql", "begin", "savepoint"}
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden for node in ast.walk(helper_tree))
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


def test_source_schema_defines_diagnostic_status_without_changing_legacy_fields_or_permissions():
    root = Path(event_log.__file__).parent
    schema = json.loads((root / "doctype/zatca_erpgulf_event_log/zatca_erpgulf_event_log.json").read_text())
    custom = json.loads((root.parent / "fixtures/custom_field.json").read_text())
    assert event_log.require_event_log_schema(source_event_meta()) is None
    field = next(field for field in schema["fields"] if field["fieldname"] == "status")
    assert field == {"fieldname": "status", "fieldtype": "Data", "label": "Diagnostic Status", "read_only": 1,
        "description": "Diagnostic label only; not evidence of authority acceptance or durable receipt storage."}
    assert schema["field_order"].count("status") == 1
    assert len([field for field in custom if field.get("dt") == schema["name"] and field["fieldname"] == "custom_uuid"]) == 1
    assert not any(field.get("dt") == schema["name"] and field["fieldname"] == "status" for field in custom)
    assert schema["permissions"] == [{"create": 1, "delete": 1, "email": 1, "export": 1,
        "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1}]


@pytest.mark.parametrize("tuple_fields", [False, True])
@pytest.mark.parametrize("fieldname", list(event_log.EVENT_LOG_FIELD_TYPES))
@pytest.mark.parametrize("defect", ["missing", "duplicate", "wrong_type", "virtual", "fetched"])
def test_missing_conflicting_or_nonstored_fields_fail_before_any_diagnostic_write(writer, tuple_fields, fieldname, defect):
    meta = source_event_meta()
    field = meta.get_field(fieldname)
    if defect == "missing":
        meta.fields.remove(field)
    elif defect == "duplicate":
        meta.fields.append(Document(**vars(field)))
    elif defect == "wrong_type":
        field.fieldtype = "Select" if fieldname != "api_response" else "Small Text"
    elif defect == "virtual":
        field.is_virtual = 1
    else:
        field.fetch_from = "PRIVATE.source"
    if tuple_fields:
        meta.fields = tuple(meta.fields)
    writer.runtime.get_meta.return_value = meta
    with pytest.raises(event_log.EventLogSchemaError) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "PRIVATE BODY", "Success")
    assert str(raised.value) == event_log.EVENT_LOG_SCHEMA_REVIEW
    assert raised.value.__context__ is raised.value.__cause__ is None and not vars(raised.value)
    writer.runtime.get_doc.assert_not_called()
    writer.clock.assert_not_called()
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.db.rollback.assert_not_called()
    writer.runtime.log_error.assert_not_called()


@pytest.mark.parametrize("fieldname", [name for name, fieldtype in event_log.EVENT_LOG_FIELD_TYPES.items() if fieldtype == "Data"])
@pytest.mark.parametrize("length,valid", [(None, True), (0, True), (140, True), (255, True),
    (139, False), (-1, False), ("140", False), (True, False), (140.5, False)])
def test_data_width_is_not_silently_narrowed(writer, fieldname, length, valid):
    meta = writer.runtime.get_meta.return_value
    meta.get_field(fieldname).length = length
    if valid:
        assert event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Success") is event_log.EventLogWriteResult.INSERT_RETURNED
    else:
        with pytest.raises(event_log.EventLogSchemaError):
            event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Success")
        writer.runtime.get_doc.assert_not_called()
    writer.runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("flag", ["issingle", "istable", "is_virtual"])
@pytest.mark.parametrize("value", [1, "0", "PRIVATE invalid flag"])
def test_nonordinary_or_malformed_table_metadata_fails_without_insert(writer, flag, value):
    setattr(writer.runtime.get_meta.return_value, flag, value)
    with pytest.raises(event_log.EventLogSchemaError):
        event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Warning")
    writer.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("error_type", ERRORS)
def test_metadata_acquisition_error_keeps_original_propagation_and_no_side_effect(writer, error_type):
    error = error_type("PRIVATE metadata acquisition")
    writer.runtime.get_meta.side_effect = error
    with pytest.raises(error_type) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Warning")
    assert raised.value is error
    writer.runtime.get_doc.assert_not_called()
    writer.clock.assert_not_called()
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.log_error.assert_not_called()


@pytest.mark.parametrize("defect", ["wrong_name", "no_fields", "mapping_fields", "bad_row", "wrong_lookup", "lookup_error"])
def test_malformed_or_unreadable_metadata_is_static_review_not_a_private_error_export(writer, defect):
    meta = writer.runtime.get_meta.return_value
    if defect == "wrong_name":
        meta.name = "PRIVATE foreign doctype"
    elif defect == "no_fields":
        meta.fields = None
    elif defect == "mapping_fields":
        meta.fields = {"PRIVATE": "invalid fields container"}
    elif defect == "bad_row":
        meta.fields.append(object())
    elif defect == "wrong_lookup":
        meta.get_field = lambda name: Document(fieldname="PRIVATE wrong field", fieldtype="Data")
    else:
        meta.get_field = Mock(side_effect=ValueError("PRIVATE lookup driver error"))
    with pytest.raises(event_log.EventLogSchemaError) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "PRIVATE body", "Success")
    assert str(raised.value) == event_log.EVENT_LOG_SCHEMA_REVIEW
    assert raised.value.__context__ is raised.value.__cause__ is None
    assert not vars(raised.value)
    writer.runtime.get_doc.assert_not_called()
    writer.runtime.db.commit.assert_not_called()


def test_schema_error_and_new_source_labels_have_arabic_catalog_entries(writer, monkeypatch):
    path = Path(event_log.__file__).parents[1] / "translations/ar.csv"
    with path.open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    labels = (event_log.EVENT_LOG_SCHEMA_REVIEW, "Diagnostic Status",
        "Diagnostic label only; not evidence of authority acceptance or durable receipt storage.")
    assert all(entries[label] and entries[label] != label for label in labels)
    monkeypatch.setattr(event_log, "_", lambda message: entries[message])
    writer.runtime.get_meta.return_value.fields = []
    with pytest.raises(event_log.EventLogSchemaError) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "PRIVATE BODY", "Success")
    assert str(raised.value) == entries[event_log.EVENT_LOG_SCHEMA_REVIEW]
    assert raised.value.__context__ is None
