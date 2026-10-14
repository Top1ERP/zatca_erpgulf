"""Post-response error boundary with mocked HTTP/ERP/File, never an authority."""

import ast
import csv
import inspect
from pathlib import Path
import pytest

from zatca_erpgulf.zatca_erpgulf import sign_invoice, pos_sign, response_processing as policy
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import (
    boundary, run_adapter, ValidationError,
)


ROUTES = ((sign_invoice, "reporting"), (sign_invoice, "clearance"),
    (pos_sign, "reporting"), (pos_sign, "clearance"))
LOCAL_ERRORS = (ValueError, TypeError, KeyError, ValidationError)
FIELDS = ("custom_uuid", "custom_zatca_status", "custom_zatca_full_response",
    "custom_ksa_einvoicing_xml", "ksa_einv_qr")


def snapshot(b, doc):
    return (tuple(doc.get(field) for field in FIELDS), doc.save.call_count,
        doc.db_set.call_count, b.frappe.db.commit.call_count, b.frappe.db.set_value.call_count,
        b.frappe.get_doc.call_count)


def inject_failure(b, module, operation, monkeypatch, stage, error_type):
    """Snapshot at the failure, not before legitimate legacy response writes."""
    doc = b.sales if module is sign_invoice else b.pos
    observed = []
    def fail_local(*args, **kwargs):
        observed.append(snapshot(b, doc))
        raise error_type("PRIVATE-LOCAL-FAILURE credential/path/response must not be echoed")
    if stage in ("log_zatca_event", "record_submission_owner_success", "success_log"):
        monkeypatch.setattr(module, stage, fail_local)
    elif stage == "image":
        monkeypatch.setattr(module, "attach_qr_image", fail_local)
    elif stage == "json":
        b.response.json = fail_local
    elif stage == "extract":
        name = "_extract_qr_payload" if operation == "reporting" else "_extract_qr_payload_from_xml"
        monkeypatch.setattr(module, name, fail_local)
    elif stage == "file":
        original = b.frappe.get_doc.side_effect
        def get_doc(doctype, name=None):
            result = original(doctype, name)
            if isinstance(doctype, dict):
                result.save.side_effect = fail_local
            return result
        b.frappe.get_doc.side_effect = get_doc
    elif stage == "invoice_save":
        doc.save.side_effect = fail_local
    elif stage == "hide":
        def publish(event, *args, **kwargs):
            if event == "hide_gif":
                fail_local()
        b.frappe.publish_realtime.side_effect = publish
    else:
        raise AssertionError("Unknown synthetic failure stage")
    return doc, observed


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("status", [200, 202])
@pytest.mark.parametrize("error_type", LOCAL_ERRORS)
@pytest.mark.parametrize("stage", ["log_zatca_event", "record_submission_owner_success", "success_log"])
def test_processing_error_does_not_run_generic_failure_writes_or_retry(boundary, monkeypatch, module, operation, status, error_type, stage):
    b = boundary
    b.response.status_code = status
    doc, observed = inject_failure(b, module, operation, monkeypatch, stage, error_type)
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    assert str(error.value) == policy.LOCAL_RESPONSE_REVIEW
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert "PRIVATE" not in str(error.value) and not vars(error.value)
    b.post.assert_called_once()
    b.frappe.log_error.assert_not_called()


ARTIFACT_STAGES = tuple((module, operation, stage)
    for module, operation in ((sign_invoice, "reporting"), (sign_invoice, "clearance"), (pos_sign, "clearance"))
    for stage in ("file", "extract", "image")) + (
    (sign_invoice, "clearance", "json"), (pos_sign, "clearance", "json"),
    (sign_invoice, "reporting", "invoice_save"),
    (sign_invoice, "reporting", "hide"), (pos_sign, "reporting", "hide"),
    (sign_invoice, "clearance", "hide"), (pos_sign, "clearance", "hide"))


@pytest.mark.parametrize("module,operation,stage", ARTIFACT_STAGES)
@pytest.mark.parametrize("status", [200, 202])
def test_artifact_parse_image_and_notification_failures_are_local_review(boundary, monkeypatch, module, operation, stage, status):
    b = boundary
    b.response.status_code = status
    doc, observed = inject_failure(b, module, operation, monkeypatch, stage, ValidationError)
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES[:-1])
@pytest.mark.parametrize("stage", ["log_zatca_event", "success_log"])
def test_legacy_409_error_boundary_does_not_assert_duplicate_acceptance(boundary, monkeypatch, module, operation, stage):
    b = boundary
    b.response.status_code = 409
    doc, observed = inject_failure(b, module, operation, monkeypatch, stage, ValueError)
    with pytest.raises(policy.LocalResponseProcessingError):
        run_adapter(b, module, operation)
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES)
def test_previously_unhandled_runtime_errors_still_propagate_without_failure_writes(boundary, monkeypatch, module, operation):
    b = boundary
    doc, observed = inject_failure(b, module, operation, monkeypatch, "log_zatca_event", RuntimeError)
    with pytest.raises(RuntimeError, match="PRIVATE-LOCAL-FAILURE") as error:
        run_adapter(b, module, operation)
    assert type(error.value) is RuntimeError
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    b.post.assert_called_once()


@pytest.mark.parametrize("module,operation", ROUTES)
def test_review_message_is_arabic_when_translation_is_arabic(boundary, monkeypatch, module, operation):
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    translated = entries[policy.LOCAL_RESPONSE_REVIEW]
    monkeypatch.setattr(policy, "_", lambda message: entries[message])
    inject_failure(boundary, module, operation, monkeypatch, "log_zatca_event", ValueError)
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        run_adapter(boundary, module, operation)
    assert str(error.value) == translated and translated != policy.LOCAL_RESPONSE_REVIEW
    assert error.value.__context__ is None


def test_review_signal_cannot_be_mistaken_for_legacy_validation_or_success(monkeypatch):
    import frappe
    monkeypatch.setattr(policy, "_", lambda message: message)
    assert issubclass(policy.LocalResponseProcessingError, RuntimeError)
    assert not issubclass(policy.LocalResponseProcessingError, (ValueError, frappe.ValidationError))
    with pytest.raises(policy.LocalResponseProcessingError) as error:
        policy.raise_local_response_review()
    assert str(error.value) == policy.LOCAL_RESPONSE_REVIEW and not vars(error.value)
    source = inspect.getsource(policy)
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr in (
        "commit", "rollback", "set_value", "save", "db_set", "post", "get_doc", "log_error") for node in calls)
