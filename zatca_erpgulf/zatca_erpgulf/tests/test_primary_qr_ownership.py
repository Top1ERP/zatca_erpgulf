"""Scoped metadata/pre-request rejection; synthetic ERP/File/HTTP only."""

import ast
import csv
import inspect
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_qr_attachment as preflight, sign_invoice, pos_sign
from zatca_erpgulf.zatca_erpgulf.qr_attachment_policy import FILE_FIELDS, MAX_FILE_OBSERVATIONS
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_qr_transaction import primary_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_attachment_policy import row
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import (
    boundary, run_adapter, ValidationError as BoundaryError,
)


SCENARIOS = ("dangling", "foreign_url", "foreign_row", "other_doctype", "orphan",
    "duplicate", "malformed", "bad_projection", "over_limit", "bad_name", "bad_url", "missing_schema")


def configure(doc, runtime, scenario):
    owned = row(doctype=doc.doctype, invoice=doc.name)
    doc.ksa_einv_qr = owned["file_url"]
    rows = []
    if scenario == "foreign_url":
        # A global hit must not make another invoice's URL acceptable.
        runtime.db.exists = Mock(return_value=True)
    elif scenario in ("foreign_row", "other_doctype"):
        owned["attached_to_name" if scenario == "foreign_row" else "attached_to_doctype"] = "FOREIGN"
        rows = [owned]
    elif scenario == "orphan":
        doc.ksa_einv_qr, rows = None, [owned]
    elif scenario == "duplicate":
        rows = [owned, dict(owned)]
    elif scenario == "malformed":
        rows = [{"name": "PRIVATE-RAW-ROW"}]
    elif scenario == "bad_projection":
        rows = {"PRIVATE-RAW-ROW": "NOT-A-LIST"}
    elif scenario == "over_limit":
        rows = [row(str(index), doctype=doc.doctype, invoice=doc.name)
            for index in range(MAX_FILE_OBSERVATIONS + 1)]
    elif scenario == "bad_name":
        doc.name = {"PRIVATE-RAW-FILTER": "MUST-NOT-REACH-ORM"}
    elif scenario == "bad_url":
        doc.ksa_einv_qr = ["PRIVATE-RAW-URL"]
    elif scenario == "missing_schema":
        del doc.ksa_einv_qr
    runtime.get_all.return_value = rows


def assert_no_writes(doc, runtime):
    doc.db_set.assert_not_called()
    doc.save.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("filename", ["QR-Phase1-OLD.png", "QR-Phase2-OLD.png", "legacy-image.png"])
@pytest.mark.parametrize("field", [None, "ksa_einv_qr", "legacy"])
def test_current_owned_reference_preserved_without_prefix_or_newest_choice(primary_qr, doctype, filename, field):
    doc, runtime, payloads, _ = primary_qr
    doc.doctype, doc.ksa_einv_qr = doctype, "/files/OLD.png"
    old = row(doctype=doctype, filename=filename, field=field)
    newer = row("NEW", "/files/NEW.png", "QR-Phase2-CLEARED-NEW.png", doctype=doctype)
    runtime.get_all.return_value = [newer, old]
    sign_invoice.attach_qr_image("DIFFERENT-SYNTHETIC-PAYLOAD", doc, allow_phase2=True)
    assert doc.ksa_einv_qr == "/files/OLD.png" and not payloads
    runtime.get_all.assert_called_once_with("File", filters={"attached_to_doctype": doctype,
        "attached_to_name": doc.name}, fields=list(FILE_FIELDS), order_by="name asc",
        limit_page_length=MAX_FILE_OBSERVATIONS + 1)
    assert_no_writes(doc, runtime)
    runtime.db.exists.assert_not_called()
    runtime.delete_doc.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_ambiguous_metadata_cannot_preserve_generate_or_replace(primary_qr, doctype, scenario):
    doc, runtime, payloads, _ = primary_qr
    doc.doctype, doc.custom_zatca_status = doctype, "CLEARED"
    configure(doc, runtime, scenario)
    previous = doc.get("ksa_einv_qr")
    with pytest.raises(ValidationError) as error:
        sign_invoice.attach_qr_image("SYNTHETIC", doc, allow_phase2=True)
    assert str(error.value) == (preflight.MISSING_QR_FIELD if scenario == "missing_schema" else preflight.QR_REVIEW_REQUIRED)
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    assert doc.get("ksa_einv_qr") == previous and doc.custom_zatca_status == "CLEARED" and not payloads
    assert_no_writes(doc, runtime)
    runtime.db.exists.assert_not_called()
    runtime.delete_doc.assert_not_called()
    if scenario in ("bad_name", "bad_url", "missing_schema"):
        runtime.get_all.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_preflight_rejects_before_http_xml_identity_pih_or_error_persistence(boundary, module, operation, scenario):
    doc = boundary.sales if module is sign_invoice else boundary.pos
    doc.custom_zatca_status, doc.custom_zatca_full_response = "ORIGINAL", "ORIGINAL-RECEIPT"
    configure(doc, boundary.frappe, scenario)
    previous = doc.get("ksa_einv_qr")
    with pytest.raises(BoundaryError) as error:
        run_adapter(boundary, module, operation)
    assert error.value.__context__ is None
    assert_no_writes(doc, boundary.frappe)
    assert boundary.files == []
    boundary.post.assert_not_called()
    boundary.frappe.publish_realtime.assert_not_called()
    module.xml_base64_decode.assert_not_called()
    assert doc.get("ksa_einv_qr") == previous and doc.custom_zatca_status == "ORIGINAL"
    assert doc.custom_uuid == "test-existing-uuid" and doc.custom_zatca_full_response == "ORIGINAL-RECEIPT"
    for owner in (boundary.company, boundary.device, boundary.linked):
        assert owner.custom_pih == "previous"
        owner.save.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("error_type", [RuntimeError, BoundaryError])
def test_actual_query_fault_propagates_before_api_error_mutation(boundary, module, operation, error_type):
    failure = error_type("SYNTHETIC SQL fault")
    boundary.frappe.get_all.side_effect = failure
    doc = boundary.sales if module is sign_invoice else boundary.pos
    with pytest.raises(error_type) as error:
        run_adapter(boundary, module, operation)
    assert error.value is failure
    assert_no_writes(doc, boundary.frappe)
    boundary.post.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_invalid_expected_doctype_cannot_query_foreign_source(primary_qr, doctype):
    doc, runtime, _, _ = primary_qr
    doc.doctype = "POS Invoice" if doctype == "Sales Invoice" else "Sales Invoice"
    with pytest.raises(ValidationError):
        preflight.require_primary_qr_attachment(doc, expected_doctype=doctype)
    runtime.get_all.assert_not_called()
    assert_no_writes(doc, runtime)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_primary_attachment_is_not_historical_recovery_or_saved_status_authentication(primary_qr, doctype):
    doc, runtime, _, _ = primary_qr
    doc.doctype = doctype
    original_get = doc.get
    def get(key, default=None):
        assert key != "custom_zatca_status", "Current status cannot prove historical provenance"
        return original_get(key, default)
    doc.get = get
    decision = preflight.require_primary_qr_attachment(doc)
    assert decision.action == "GENERATE"  # No reference, not proof of issuance/receipt validity.
    assert_no_writes(doc, runtime)


def test_review_uses_existing_arabic_key_without_raw_context(primary_qr, monkeypatch):
    doc, runtime, _, _ = primary_qr
    configure(doc, runtime, "malformed")
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        entries = {values[0]: values[1] for values in csv.reader(stream) if len(values) >= 2}
    translated = entries[preflight.QR_REVIEW_REQUIRED]
    monkeypatch.setattr(preflight, "_", lambda text: entries[text])
    with pytest.raises(ValidationError) as error:
        preflight.require_primary_qr_attachment(doc)
    assert str(error.value) == translated and translated != preflight.QR_REVIEW_REQUIRED
    assert error.value.__context__ is None


def test_guard_has_no_public_endpoint_global_url_query_or_mutation():
    source = inspect.getsource(preflight)
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    assert "whitelist" not in source
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr in (
        "exists", "save", "db_set", "set_value", "commit", "rollback", "delete_doc", "notify_update") for node in calls)
