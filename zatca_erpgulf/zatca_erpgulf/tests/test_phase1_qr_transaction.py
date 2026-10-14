"""Mocked real Phase-1 builder, no tenant/image/network or parent transaction."""

import ast
import csv
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import create_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr, tlv_values
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_generation_stages_one_metadata_update_without_recursive_save_or_commit(local_qr, doctype):
    doc, runtime, payloads, _ = local_qr
    doc.doctype = doctype
    create_qr.create_qr_code(doc)
    runtime.db.set_value.assert_called_once_with(doctype, doc.name,
        {"ksa_einv_qr": "/files/SYNTHETIC-QR.png", "custom_zatca_status": "Phase-1 QR Generated"}, update_modified=False)
    assert doc.ksa_einv_qr == "/files/SYNTHETIC-QR.png" and doc.custom_zatca_status == "Phase-1 QR Generated"
    assert len(payloads) == 1
    assert tlv_values(payloads[0])[4] == "11.5"
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()
    doc.notify_update.assert_called_once()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("status", ["", "Not Submitted", "Phase-1 QR Generated"])
def test_no_incidental_invoice_changes_or_modified_time_rewrite(local_qr, doctype, status):
    doc, runtime, _, _ = local_qr
    doc.doctype, doc.custom_zatca_status = doctype, status
    doc.modified, doc.modified_by = "2026-10-01 00:00:00", "original@example.test"
    doc.pending_unrelated_change = "MUST-NOT-SAVE-THIS-FIELD"
    create_qr.create_qr_code(doc)
    values = runtime.db.set_value.call_args.args[2]
    assert set(values) == {"ksa_einv_qr", "custom_zatca_status"}
    assert doc.modified == "2026-10-01 00:00:00" and doc.modified_by == "original@example.test"
    assert doc.pending_unrelated_change == "MUST-NOT-SAVE-THIS-FIELD"
    doc.save.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("stage", ["image", "file", "metadata", "notify"])
def test_failures_propagate_without_commit_rollback_or_recursive_invoice_save(local_qr, monkeypatch, doctype, stage):
    doc, runtime, _, _ = local_qr
    doc.doctype = doctype
    runtime.db.rollback = Mock(side_effect=AssertionError("Parent owns rollback"))
    file = runtime.get_doc({"doctype": "File"})
    runtime.get_doc.reset_mock()
    failure = RuntimeError("SYNTHETIC failure")
    if stage == "image":
        monkeypatch.setattr(create_qr, "qr_create", Mock(side_effect=failure))
    elif stage == "file":
        file.save.side_effect = failure
    elif stage == "metadata":
        runtime.db.set_value.side_effect = failure
    else:
        doc.notify_update.side_effect = failure
    with pytest.raises(RuntimeError, match="SYNTHETIC failure"):
        create_qr.create_qr_code(doc)
    runtime.db.commit.assert_not_called()
    runtime.db.rollback.assert_not_called()
    doc.save.assert_not_called()
    doc.db_set.assert_not_called()
    if stage in ("image", "file"):
        runtime.db.set_value.assert_not_called()
    if stage != "notify":
        assert doc.ksa_einv_qr is None
        doc.notify_update.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_missing_field_fails_before_attachment_schema_or_metadata_write(local_qr, monkeypatch, doctype):
    doc, runtime, payloads, _ = local_qr
    doc.doctype = doctype
    del doc.ksa_einv_qr
    with pytest.raises(ValidationError, match="QR field is missing"):
        create_qr.create_qr_code(doc)
    assert not payloads
    runtime.get_all.assert_not_called()
    runtime.get_doc.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_non_saudi_path_still_skips_missing_schema_without_setup(local_qr, monkeypatch, doctype):
    doc, runtime, payloads, _ = local_qr
    doc.doctype = doctype
    del doc.ksa_einv_qr
    monkeypatch.setattr(create_qr, "get_region", lambda name: "Germany")
    create_qr.create_qr_code(doc)
    assert not payloads
    runtime.get_all.assert_not_called()
    runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_existing_link_is_retained_without_metadata_status_or_transaction_change(local_qr, doctype):
    doc, runtime, payloads, _ = local_qr
    doc.doctype, doc.ksa_einv_qr, doc.custom_zatca_status = doctype, "/files/EXISTING.png", "REPORTED"
    runtime.db.exists.return_value = True
    create_qr.create_qr_code(doc)
    assert doc.ksa_einv_qr == "/files/EXISTING.png" and doc.custom_zatca_status == "REPORTED"
    assert not payloads
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()


def test_inspected_actual_v15_notify_registers_after_commit_not_immediate_publication(local_qr, monkeypatch):
    import frappe.model.document as framework
    doc, _, _, _ = local_qr
    publisher = Mock()
    monkeypatch.setattr(framework, "frappe", SimpleNamespace(flags=SimpleNamespace(in_patch=False),
        session=SimpleNamespace(user="operator@example.test"), publish_realtime=publisher))
    doc.modified = "2026-10-14 00:00:00"
    doc.meta.get = lambda name: False
    framework.Document.notify_update(doc)
    assert len(publisher.call_args_list) == 2
    assert all(call.kwargs["after_commit"] is True for call in publisher.call_args_list)


def test_generator_has_no_schema_commit_rollback_or_recursive_invoice_save_calls():
    source = inspect.getsource(create_qr)
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr in ("commit", "rollback") for node in calls)
    assert not any(isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                   and node.func.value.id == "doc" and node.func.attr in ("save", "db_set") for node in calls)
    assert "create_custom_fields" not in source


def test_missing_schema_message_has_arabic_translation(local_qr, monkeypatch):
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    translated = entries[create_qr.MISSING_QR_FIELD]
    assert translated != create_qr.MISSING_QR_FIELD
    monkeypatch.setattr(create_qr, "_", lambda message: entries[message])
    doc = local_qr[0]
    del doc.ksa_einv_qr
    with pytest.raises(ValidationError, match=translated):
        create_qr.create_qr_code(doc)


def test_both_qr_fields_are_already_declared_in_installation_fixtures():
    fixtures = Path(__file__).resolve().parents[2] / "fixtures/custom_field.json"
    fields = json.loads(fixtures.read_text())
    declared = [row for row in fields if row.get("fieldname") == "ksa_einv_qr"]
    assert {(row["dt"], row["fieldtype"]) for row in declared} == {
        ("Sales Invoice", "Attach Image"), ("POS Invoice", "Attach Image")}
    assert len(declared) == 2
