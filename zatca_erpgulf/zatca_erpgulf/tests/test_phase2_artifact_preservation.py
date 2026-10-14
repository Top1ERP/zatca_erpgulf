"""Actual Phase-2 hook with synthetic metadata, never response/image/file IO."""

import ast
from copy import deepcopy
import csv
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import phase2_artifacts as artifacts
from zatca_erpgulf.zatca_erpgulf.qr_attachment_policy import FILE_FIELDS, MAX_FILE_OBSERVATIONS
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_attachment_policy import row


class Invoice(Document):
    def get(self, name, default=None):
        if name == "custom_zatca_full_response":
            raise AssertionError("Saved response text cannot authorize repair")
        return super().get(name, default)


@pytest.fixture
def phase2_case(monkeypatch):
    doc = Invoice(doctype="Sales Invoice", name="SYNTHETIC-TIME", docstatus=1,
        ksa_einv_qr=None, custom_zatca_status="REPORTED", custom_uuid="SYNTHETIC-UNCHANGED",
        custom_ksa_einvoicing_xml="/private/files/ORIGINAL.xml", modified="2026-10-01 00:00:00",
        custom_zatca_full_response="PRIVATE-NEVER-READ", save=Mock(), db_set=Mock(), notify_update=Mock())
    forbidden = lambda: Mock(side_effect=AssertionError("No File/response/transaction side effects"))
    runtime = SimpleNamespace(get_all=Mock(return_value=[]), get_doc=forbidden(), delete_doc=forbidden(),
        msgprint=forbidden(), log_error=forbidden(), throw=forbidden(),
        db=SimpleNamespace(set_value=forbidden(), commit=forbidden(), rollback=forbidden(),
            exists=forbidden(), sql=forbidden()))
    parser, saver, response_parser, image = forbidden(), forbidden(), forbidden(), forbidden()
    monkeypatch.setattr(artifacts, "frappe", runtime)
    monkeypatch.setattr(artifacts, "_", lambda text: text)
    monkeypatch.setattr(artifacts, "_extract_qr_payload_from_xml", parser)
    monkeypatch.setattr(artifacts, "save_file", saver, raising=False)
    monkeypatch.setattr(artifacts, "_extract_response_json", response_parser, raising=False)
    monkeypatch.setattr(artifacts, "pyqrcode", SimpleNamespace(create=image), raising=False)
    return SimpleNamespace(doc=doc, runtime=runtime, parser=parser, saver=saver,
        response_parser=response_parser, image=image)


def untouched(case):
    for operation in (case.runtime.get_doc, case.runtime.delete_doc, case.runtime.msgprint,
        case.runtime.log_error, case.runtime.throw, case.runtime.db.set_value, case.runtime.db.commit,
        case.runtime.db.rollback, case.runtime.db.exists, case.runtime.db.sql,
        case.doc.save, case.doc.db_set, case.doc.notify_update,
        case.parser, case.saver, case.response_parser, case.image):
        operation.assert_not_called()


@pytest.mark.parametrize("status", ["CLEARED", "REPORTED"])
@pytest.mark.parametrize("filename", ["QR-Phase1-OLD.png", "QR-Phase2-REPORTED-OLD.png",
    "QR-ZATCA-Advance-Aware-OLD.png", "legacy-image.png"])
@pytest.mark.parametrize("field", [None, "ksa_einv_qr", "legacy_field"])
def test_current_owned_reference_preserved_regardless_of_prefix_or_field(phase2_case, status, filename, field):
    case = phase2_case
    case.doc.custom_zatca_status, case.doc.ksa_einv_qr = status, "/files/OLD.png"
    rows = [row("NEW", "/files/NEW.png", "QR-Phase2-CLEARED-NEW.png"), row(filename=filename, field=field)]
    before = deepcopy(rows)
    case.runtime.get_all.return_value = rows
    assessment = artifacts.assess_phase2_qr_reference(case.doc)
    assert assessment["action"] == "PRESERVE" and assessment["source_authenticated"] is False
    assert assessment["mutation_performed"] is False
    assert artifacts.ensure_phase2_sales_invoice_artifacts(case.doc, "on_update_after_submit") is None
    assert case.doc.ksa_einv_qr == "/files/OLD.png" and case.doc.custom_zatca_status == status
    assert rows == before
    query = case.runtime.get_all.call_args.kwargs
    assert query["filters"] == {"attached_to_doctype": "Sales Invoice", "attached_to_name": case.doc.name}
    assert query["fields"] == list(FILE_FIELDS) and query["order_by"] == "name asc"
    assert query["limit_page_length"] == MAX_FILE_OBSERVATIONS + 1
    untouched(case)


@pytest.mark.parametrize("status", ["CLEARED", "REPORTED"])
@pytest.mark.parametrize("scenario", ["empty", "orphan", "dangling", "foreign", "malformed", "xml_only", "duplicate"])
def test_missing_or_ambiguous_source_requires_review_without_raising_from_hook(phase2_case, status, scenario):
    case = phase2_case
    case.doc.custom_zatca_status = status
    if scenario in ("dangling", "foreign"):
        case.doc.ksa_einv_qr = "/files/OLD.png"
    if scenario == "orphan":
        case.runtime.get_all.return_value = [row()]
    elif scenario == "foreign":
        case.runtime.get_all.return_value = [row(invoice="FOREIGN-INVOICE")]
    elif scenario == "malformed":
        case.runtime.get_all.return_value = [{"name": "PRIVATE-INCOMPLETE"}]
    elif scenario == "xml_only":
        case.runtime.get_all.return_value = [row(filename="DEBUG-NEW.xml", field=None)]
    elif scenario == "duplicate":
        case.runtime.get_all.return_value = [row(), row()]
    current = case.doc.ksa_einv_qr
    report = artifacts.assess_phase2_qr_reference(case.doc)
    assert report["action"] == "REVIEW" and report["message"] == artifacts.REVIEW_MESSAGE
    assert "PRIVATE" not in json.dumps(report) and "FOREIGN-INVOICE" not in json.dumps(report)
    assert artifacts.ensure_phase2_sales_invoice_artifacts(case.doc, "on_submit") is None
    assert case.doc.ksa_einv_qr == current and case.doc.custom_zatca_status == status
    assert case.doc.custom_ksa_einvoicing_xml == "/private/files/ORIGINAL.xml"
    untouched(case)


@pytest.mark.parametrize("gate", ["pos", "company", "draft", "cancelled", "phase1", "not_submitted", "no_status", "bad_status"])
def test_existing_hook_scope_gates_skip_before_metadata_lookup(phase2_case, gate):
    case = phase2_case
    if gate in ("pos", "company"):
        case.doc.doctype = "POS Invoice" if gate == "pos" else "Company"
    elif gate in ("draft", "cancelled"):
        case.doc.docstatus = 0 if gate == "draft" else 2
    else:
        case.doc.custom_zatca_status = {"phase1": "Phase-1 QR Generated", "not_submitted": "Not Submitted",
            "no_status": None, "bad_status": {"PRIVATE": "INVALID"}}[gate]
    assert artifacts.ensure_phase2_sales_invoice_artifacts(case.doc) is None
    case.runtime.get_all.assert_not_called()
    untouched(case)


@pytest.mark.parametrize("name", [None, {}, " padded ", "x" * 141])
def test_invalid_source_name_requires_review_before_orm_filter(phase2_case, name):
    case = phase2_case
    case.doc.name = name
    assert artifacts.assess_phase2_qr_reference(case.doc)["action"] == "REVIEW"
    assert artifacts.ensure_phase2_sales_invoice_artifacts(case.doc) is None
    case.runtime.get_all.assert_not_called()
    untouched(case)


@pytest.mark.parametrize("rows", [None, {}, iter(())])
def test_noncollection_projection_requires_review_without_guessing(phase2_case, rows):
    phase2_case.runtime.get_all.return_value = rows
    assert artifacts.assess_phase2_qr_reference(phase2_case.doc)["action"] == "REVIEW"
    assert artifacts.ensure_phase2_sales_invoice_artifacts(phase2_case.doc) is None
    untouched(phase2_case)


@pytest.mark.parametrize("count", [MAX_FILE_OBSERVATIONS, MAX_FILE_OBSERVATIONS + 1])
def test_bound_does_not_treat_a_truncated_current_match_as_complete(phase2_case, count):
    case = phase2_case
    case.doc.ksa_einv_qr = "/files/OLD.png"
    case.runtime.get_all.return_value = [row(str(index)) for index in range(count)]
    assert artifacts.assess_phase2_qr_reference(case.doc)["action"] == (
        "PRESERVE" if count == MAX_FILE_OBSERVATIONS else "REVIEW")
    assert artifacts.ensure_phase2_sales_invoice_artifacts(case.doc) is None
    untouched(case)


@pytest.mark.parametrize("response", ["NOT JSON", '{"clearedInvoice":"WRONG","reportedInvoice":"WRONG"}', "x" * 10000])
def test_saved_response_never_creates_files_or_changes_an_accepted_label(phase2_case, response):
    case = phase2_case
    case.doc.custom_zatca_full_response = response
    assert artifacts.ensure_phase2_sales_invoice_artifacts(case.doc) is None
    assert case.doc.custom_zatca_status == "REPORTED" and case.doc.ksa_einv_qr is None
    untouched(case)


def test_arabic_review_and_absent_field_never_install_schema(phase2_case, monkeypatch):
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        translations = dict(csv.reader(stream))
    assert translations[artifacts.REVIEW_MESSAGE] != artifacts.REVIEW_MESSAGE
    monkeypatch.setattr(artifacts, "_", lambda message: translations[message])
    del phase2_case.doc.ksa_einv_qr
    report = artifacts.assess_phase2_qr_reference(phase2_case.doc)
    assert report["message"] == translations[artifacts.REVIEW_MESSAGE]
    assert artifacts.ensure_phase2_sales_invoice_artifacts(phase2_case.doc) is None
    assert not hasattr(phase2_case.doc, "ksa_einv_qr")
    untouched(phase2_case)


def test_database_errors_propagate_without_any_repair_or_transaction_cleanup(phase2_case):
    case = phase2_case
    case.runtime.get_all.side_effect = RuntimeError("SYNTHETIC database failure")
    with pytest.raises(RuntimeError, match="SYNTHETIC"):
        artifacts.ensure_phase2_sales_invoice_artifacts(case.doc)
    untouched(case)


def test_automatic_hook_repair_helpers_are_removed_but_shared_extractor_is_separate():
    tree = ast.parse(inspect.getsource(artifacts))
    forbidden = {"save", "db_set", "set_value", "commit", "rollback", "delete_doc", "save_file", "create", "open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert not {"_remove_stale_qr_files", "_save_attached_file_once", "_extract_response_json"} & functions
    hook_tree = ast.parse(inspect.getsource(artifacts.ensure_phase2_sales_invoice_artifacts))
    assert "_extract_qr_payload_from_xml" not in ast.unparse(hook_tree)
