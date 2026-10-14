"""Synthetic attachment metadata and actual mocked ordinary generator only."""

import ast
import csv
from dataclasses import FrozenInstanceError
import inspect
from itertools import permutations
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import create_qr, qr_attachment_policy as policy
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError


def row(name="FILE-OLD", url="/files/OLD.png", filename="QR-Phase2-OLD.png", *, doctype="Sales Invoice", invoice="SYNTHETIC-TIME", field="ksa_einv_qr"):
    return dict(name=name, file_url=url, file_name=filename, attached_to_doctype=doctype,
                attached_to_name=invoice, attached_to_field=field)


def decide(rows=(), current=None, status=None, **changes):
    values = dict(doctype="Sales Invoice", invoice_name="SYNTHETIC-TIME", current_url=current,
                  saved_status=status, rows=rows)
    values.update(changes)
    return policy.decide_qr_reuse(**values)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("filename", ["QR-Phase1-OLD.png", "QR-Phase2-CLEARED-OLD.png", "QR-ZATCA-Advance-Aware-OLD.png", "legacy-image.png", None])
@pytest.mark.parametrize("field", ["ksa_einv_qr", None, "legacy_field"])
def test_current_same_invoice_reference_preserved_without_filename_or_field_priority(doctype, filename, field):
    rows = (row(doctype=doctype, filename=filename, field=field),)
    assert decide(rows, current="/files/OLD.png", status="CLEARED", doctype=doctype).action == "PRESERVE"


def test_newest_official_or_different_phase_filename_never_overrides_current():
    old = row()
    newer = row("FILE-NEW", "/files/NEW.png", "QR-Phase1-NEW.png")
    unknown = row("OTHER", "/files/OTHER.png", "legacy.png")
    for rows in permutations((old, newer, unknown)):
        decision = decide(rows, current="/files/OLD.png")
        assert decision.action == "PRESERVE" and decision.reason == "qr_current_owned"
    assert old["file_url"] == "/files/OLD.png"  # No mutation or sorted/latest selection.


def test_duplicate_rows_for_same_current_url_need_no_row_selection_or_deletion():
    first = row()
    duplicate_content = row("FILE-SECOND", filename="QR-Phase1-OTHER.png")
    assert decide((first, duplicate_content), current="/files/OLD.png").action == "PRESERVE"
    with pytest.raises(policy.QRAttachmentPolicyError, match="qr_attachment_duplicate_row"):
        decide((first, first), current="/files/OLD.png")


@pytest.mark.parametrize("filename,field", [("QR-Phase1-ONE.png", None), ("qr_phase2_old.png", None),
    ("QR-ZATCA-Advance-Aware-OLD.png", None), ("arbitrary-image.png", "ksa_einv_qr")])
@pytest.mark.parametrize("count", [1, 2])
def test_no_automatic_relink_even_for_single_unlinked_candidate(filename, field, count):
    rows = tuple(row(str(index), "/files/" + str(index), filename, field=field) for index in range(count))
    result = decide(rows)
    assert result.action == "REVIEW" and result.reason == "qr_unlinked_candidates"


@pytest.mark.parametrize("status", ["REPORTED", "CLEARED", "reported", "cleared"])
def test_phase2_status_with_missing_reference_cannot_fall_back_to_phase1_generation(status):
    assert decide(status=status).reason == "qr_phase2_status_without_link"
    assert decide(status=status).action == "REVIEW"


@pytest.mark.parametrize("current", ["/files/MISSING.png", "https://example.invalid/qr.png", "/files/A%20B.png"])
def test_current_missing_owned_row_needs_review_not_global_url_existence(current):
    assert decide(current=current).action == "REVIEW"
    assert decide((row(),), current=current).action == "REVIEW"


@pytest.mark.parametrize("status", [None, "", "Not Submitted", "Phase-1 QR Generated"])
def test_new_generation_only_without_stored_reference_or_qr_candidates(status):
    ordinary = row(filename="invoice.xml", field=None)
    assert decide((ordinary,), status=status).action == "GENERATE"
    assert decide(status=status).action == "GENERATE"


@pytest.mark.parametrize("change", [{"attached_to_doctype": "POS Invoice"}, {"attached_to_name": "OTHER-INVOICE"}])
def test_query_cannot_smuggle_foreign_owned_file(change):
    candidate = row()
    candidate.update(change)
    with pytest.raises(policy.QRAttachmentPolicyError, match="qr_attachment_owner"):
        decide((candidate,), current=candidate["file_url"])


@pytest.mark.parametrize("key,value", [("name", ""), ("file_name", "PRIVATE\x00NAME"),
    ("file_url", b"PRIVATE-URL"), ("attached_to_field", "x" * 141)])
def test_malformed_rows_static_errors_no_private_content(key, value):
    candidate = row()
    candidate[key] = value
    with pytest.raises(policy.QRAttachmentPolicyError) as error:
        decide((candidate,))
    assert str(error.value) == "qr_attachment_text" and error.value.__context__ is None


@pytest.mark.parametrize("rows", [[], None, (None,), ({"name": "PRIVATE-NAME"},)])
def test_complete_typed_bounded_projection_required(rows):
    with pytest.raises(policy.QRAttachmentPolicyError):
        decide(rows)


def test_limit_requires_review_even_if_current_url_was_in_truncated_prefix():
    rows = tuple(row(str(index)) for index in range(policy.MAX_FILE_OBSERVATIONS))
    assert decide(rows, current="/files/OLD.png").action == "PRESERVE"
    assert decide(rows + (row("EXTRA"),), current="/files/OLD.png").reason == "qr_attachment_limit"
    decision = decide()
    with pytest.raises(FrozenInstanceError):
        decision.action = "PRESERVE"


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_actual_generator_keeps_current_older_phase2_and_all_other_rows(local_qr, doctype):
    doc, runtime, payloads, _ = local_qr
    doc.doctype, doc.ksa_einv_qr, doc.custom_zatca_status = doctype, "/files/OLD.png", "CLEARED"
    rows = [row("NEW", "/files/NEW.png", "QR-Phase1-NEW.png", doctype=doctype), row(doctype=doctype)]
    runtime.get_all.return_value = rows
    create_qr.create_qr_code(doc)
    assert doc.ksa_einv_qr == "/files/OLD.png" and doc.custom_zatca_status == "CLEARED" and not payloads
    assert runtime.get_all.call_args.kwargs["filters"] == {"attached_to_doctype": doctype, "attached_to_name": doc.name}
    assert runtime.get_all.call_args.kwargs["limit_page_length"] == policy.MAX_FILE_OBSERVATIONS + 1
    runtime.delete_doc.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.exists.assert_not_called()
    runtime.db.commit.assert_not_called()
    assert len(rows) == 2


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("case", ["dangling", "foreign", "orphan", "overlimit", "phase2_missing", "malformed"])
def test_actual_review_path_never_writes_deletes_generates_or_clears_link(local_qr, doctype, case):
    doc, runtime, payloads, _ = local_qr
    doc.doctype = doctype
    if case in ("dangling", "foreign"):
        doc.ksa_einv_qr = "/files/OLD.png"
    if case == "foreign":
        runtime.get_all.return_value = [row(doctype=doctype, invoice="FOREIGN")]
    elif case == "orphan":
        runtime.get_all.return_value = [row(doctype=doctype)]
    elif case == "overlimit":
        runtime.get_all.return_value = [row(str(index), doctype=doctype) for index in range(policy.MAX_FILE_OBSERVATIONS + 1)]
    elif case == "phase2_missing":
        doc.custom_zatca_status = "REPORTED"
    elif case == "malformed":
        runtime.get_all.return_value = [{"name": "PRIVATE-ROW"}]
    current = doc.ksa_einv_qr
    runtime.db.exists.return_value = True  # Global presence MUST NOT authorize it.
    with pytest.raises(ValidationError) as error:
        create_qr.create_qr_code(doc)
    assert str(error.value) == create_qr.QR_REVIEW_REQUIRED and error.value.__context__ is None
    assert doc.ksa_einv_qr == current and not payloads
    runtime.delete_doc.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.exists.assert_not_called()
    runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()


def test_no_delete_or_relink_in_compatibility_helper_source():
    tree = ast.parse(inspect.getsource(create_qr._cleanup_qr_attachments))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("delete_doc", "set_value", "save", "commit", "rollback", "exists")


def test_review_message_translated_to_arabic_without_private_error_context(local_qr, monkeypatch):
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    assert entries[create_qr.QR_REVIEW_REQUIRED] != create_qr.QR_REVIEW_REQUIRED
    monkeypatch.setattr(create_qr, "_", lambda message: entries[message])
    doc, runtime, _, _ = local_qr
    runtime.get_all.return_value = [{"name": "PRIVATE-MALFORMED"}]
    with pytest.raises(ValidationError) as error:
        create_qr.create_qr_code(doc)
    assert str(error.value) == entries[create_qr.QR_REVIEW_REQUIRED] and error.value.__context__ is None
