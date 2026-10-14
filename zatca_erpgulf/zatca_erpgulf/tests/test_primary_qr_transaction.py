"""Shared Sales/POS QR adapter, mocked File/image/ERP only; no submissions."""

import ast
import csv
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import pos_sign, sign_invoice, primary_qr_attachment
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_attachment_policy import row as stored_row
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError


@pytest.fixture
def primary_qr(local_qr, monkeypatch):
    doc, runtime, payloads, saver = local_qr
    runtime.ValidationError = ValidationError
    runtime.db.rollback = Mock(side_effect=AssertionError("Caller owns rollback"))
    monkeypatch.setattr(sign_invoice, "frappe", runtime)
    monkeypatch.setattr(sign_invoice, "_", lambda text: text)
    monkeypatch.setattr(primary_qr_attachment, "frappe", runtime)
    monkeypatch.setattr(primary_qr_attachment, "_", lambda text: text)
    monkeypatch.setattr(sign_invoice, "is_zatca_invoice_enabled", lambda company: True)
    monkeypatch.setattr(sign_invoice, "resolve_zatca_phase", lambda company: sign_invoice.PHASE_2_VALUE)
    def image(payload, **options):
        assert options == {"error": "L"}
        payloads.append(payload)
        def png(buffer, **image_options):
            assert image_options == {"scale": 4, "quiet_zone": 4}
            buffer.write(b"synthetic image, not a PNG proof")
        return SimpleNamespace(png=png)
    monkeypatch.setattr(sign_invoice, "qr_create", image)
    return doc, runtime, payloads, saver


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("status", ["Not Submitted", "REPORTED", "CLEARED"])
@pytest.mark.parametrize("label", ["REPORTED", "CLEARED"])
def test_only_qr_link_is_staged_without_invoice_events_or_status_changes(primary_qr, doctype, status, label):
    doc, runtime, payloads, _ = primary_qr
    doc.doctype, doc.custom_zatca_status = doctype, status
    doc.modified, doc.modified_by = "2026-10-01 00:00:00", "original@example.test"
    doc.custom_uuid, doc.pending_business_change = "ORIGINAL-UUID", "DO-NOT-SAVE"
    file = runtime.get_doc({"doctype": "File"})
    runtime.get_doc.reset_mock()
    sign_invoice.attach_qr_image("SYNTHETIC-PAYLOAD", doc, allow_phase2=True, phase2_status=label)
    runtime.db.set_value.assert_called_once_with(doctype, doc.name,
        {"ksa_einv_qr": "/files/SYNTHETIC-QR.png"}, update_modified=False)
    assert doc.ksa_einv_qr == "/files/SYNTHETIC-QR.png" and doc.custom_zatca_status == status
    assert doc.custom_uuid == "ORIGINAL-UUID" and doc.pending_business_change == "DO-NOT-SAVE"
    assert (doc.modified, doc.modified_by) == ("2026-10-01 00:00:00", "original@example.test")
    assert payloads == ["SYNTHETIC-PAYLOAD"]
    values = runtime.get_doc.call_args.args[0]
    assert values == {"doctype": "File", "file_name": f"QR-Phase2-{label}-{doc.name}.png",
        "attached_to_doctype": doctype, "attached_to_name": doc.name, "is_private": 1,
        "content": b"synthetic image, not a PNG proof", "attached_to_field": "ksa_einv_qr"}
    runtime.get_doc.assert_called_once_with(values)
    file.save.assert_called_once_with(ignore_permissions=True)
    doc.db_set.assert_not_called()
    doc.save.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.rollback.assert_not_called()
    doc.notify_update.assert_called_once()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("stage", ["image", "file", "metadata", "notify"])
def test_parent_receives_failure_without_helper_commit_or_rollback(primary_qr, monkeypatch, doctype, stage):
    doc, runtime, _, _ = primary_qr
    doc.doctype, doc.custom_zatca_status = doctype, "REPORTED"
    file = runtime.get_doc({"doctype": "File"})
    runtime.get_doc.reset_mock()
    failure = RuntimeError("SYNTHETIC failure")
    if stage == "image":
        monkeypatch.setattr(sign_invoice, "qr_create", Mock(side_effect=failure))
    elif stage == "file":
        file.save.side_effect = failure
    elif stage == "metadata":
        runtime.db.set_value.side_effect = failure
    else:
        doc.notify_update.side_effect = failure
    with pytest.raises(RuntimeError, match="SYNTHETIC failure"):
        sign_invoice.attach_qr_image("SYNTHETIC", doc, allow_phase2=True)
    assert doc.custom_zatca_status == "REPORTED"
    doc.db_set.assert_not_called()
    doc.save.assert_not_called()
    runtime.db.commit.assert_not_called()
    runtime.db.rollback.assert_not_called()
    if stage != "notify":
        assert doc.ksa_einv_qr is None
        doc.notify_update.assert_not_called()
    if stage in ("image", "file"):
        runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("arabic", [False, True])
def test_missing_schema_is_static_translated_and_never_created(primary_qr, monkeypatch, doctype, arabic):
    doc, runtime, payloads, _ = primary_qr
    doc.doctype = doctype
    del doc.ksa_einv_qr
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    message = sign_invoice.MISSING_QR_FIELD
    if arabic:
        monkeypatch.setattr(sign_invoice, "_", lambda text: translations[text])
        monkeypatch.setattr(primary_qr_attachment, "_", lambda text: translations[text])
        message = translations[message]
        assert message != sign_invoice.MISSING_QR_FIELD
    with pytest.raises(ValidationError) as error:
        sign_invoice.attach_qr_image("SYNTHETIC", doc, allow_phase2=True)
    assert str(error.value) == message and error.value.__context__ is None
    assert not payloads
    runtime.get_doc.assert_not_called()
    runtime.db.exists.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_phase2_default_guard_remains_noop_even_without_schema(primary_qr, doctype):
    doc, runtime, payloads, _ = primary_qr
    doc.doctype = doctype
    del doc.ksa_einv_qr
    sign_invoice.attach_qr_image("SYNTHETIC", doc)
    assert not payloads
    runtime.get_doc.assert_not_called()
    runtime.db.set_value.assert_not_called()


@pytest.mark.parametrize("enabled,phase", [(False, "Phase-2"), (True, "Phase-1")])
def test_legacy_non_phase2_dispatch_still_generates(primary_qr, monkeypatch, enabled, phase):
    doc, runtime, payloads, _ = primary_qr
    monkeypatch.setattr(sign_invoice, "is_zatca_invoice_enabled", lambda company: enabled)
    monkeypatch.setattr(sign_invoice, "resolve_zatca_phase", lambda company: phase)
    sign_invoice.attach_qr_image("SYNTHETIC", doc)
    assert payloads == ["SYNTHETIC"]
    assert runtime.db.set_value.call_count == 1


def test_owned_url_is_preserved_without_global_lookup_or_authenticity_claim(primary_qr):
    doc, runtime, payloads, _ = primary_qr
    doc.ksa_einv_qr = "/files/LEGACY.png"
    runtime.db.exists.return_value = True
    runtime.get_all.return_value = [stored_row(url=doc.ksa_einv_qr)]
    sign_invoice.attach_qr_image("SYNTHETIC", doc, allow_phase2=True)
    runtime.db.exists.assert_not_called()
    assert not payloads
    runtime.db.set_value.assert_not_called()
    doc.notify_update.assert_not_called()


def test_shared_adapter_has_no_schema_or_transaction_ownership():
    assert pos_sign.attach_qr_image is sign_invoice.attach_qr_image
    source = inspect.getsource(sign_invoice.attach_qr_image) + inspect.getsource(sign_invoice._persist_attached_qr_metadata)
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    assert "create_custom_fields" not in inspect.getsource(sign_invoice)
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr in ("commit", "rollback", "db_set") for node in calls)
    assert not any(isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
        and node.func.value.id in ("doc", "sales_invoice_doc") and node.func.attr == "save" for node in calls)
