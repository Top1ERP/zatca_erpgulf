"""Advance print-hook preservation with synthetic documents and no file IO.

Existing amount formulas are characterized, not certified as regulatory evidence.
No advance search, allocation, eligibility or historical-data repair is performed.
"""

import ast
from copy import deepcopy
import csv
import inspect
from pathlib import Path

import pytest

from zatca_erpgulf.zatca_erpgulf import advance_deduction, create_qr
from zatca_erpgulf.zatca_erpgulf.qr_attachment_policy import MAX_FILE_OBSERVATIONS
from zatca_erpgulf.zatca_erpgulf.tests.test_issue_timestamp_adapters import local_qr, tlv_values
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import ValidationError
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_attachment_policy import row


def assert_no_mutation(case):
    doc, runtime, payloads, saver = case
    assert not payloads
    saver.assert_not_called()
    runtime.delete_doc.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.exists.assert_not_called()
    runtime.db.commit.assert_not_called()
    doc.db_set.assert_not_called()
    doc.save.assert_not_called()
    doc.notify_update.assert_not_called()


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("filename", ["QR-ZATCA-Advance-Aware-OLD.png", "QR-Phase2-REPORTED-OLD.png", "legacy.png"])
@pytest.mark.parametrize("status", ["Phase-1 QR Generated", "REPORTED", "CLEARED"])
def test_initial_advance_current_owned_link_preserved_even_when_forced(local_qr, force, filename, status):
    doc, runtime, _, _ = local_qr
    doc.ksa_einv_qr, doc.custom_zatca_status = "/files/OLD.png", status
    doc.posting_time = None  # Preserving must not regenerate from today's settings/time.
    rows = [row(filename=filename, field=None), row("NEW", "/files/NEW.png", "QR-Phase1-NEW.png")]
    runtime.get_all.return_value = rows
    before = deepcopy(rows)
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=force)
    assert doc.ksa_einv_qr == "/files/OLD.png" and doc.custom_zatca_status == status
    assert rows == before
    query = runtime.get_all.call_args.kwargs
    assert query["filters"] == {"attached_to_doctype": "Sales Invoice", "attached_to_name": doc.name}
    assert query["limit_page_length"] == MAX_FILE_OBSERVATIONS + 1
    assert_no_mutation(local_qr)


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("case", ["dangling", "orphan", "foreign", "malformed", "limit", "reported", "cleared"])
def test_initial_advance_ambiguous_reference_requires_review_without_repair(local_qr, force, case):
    doc, runtime, _, _ = local_qr
    if case in ("dangling", "foreign"):
        doc.ksa_einv_qr = "/files/OLD.png"
    if case == "orphan":
        runtime.get_all.return_value = [row()]
    elif case == "foreign":
        runtime.get_all.return_value = [row(invoice="FOREIGN")]
    elif case == "malformed":
        runtime.get_all.return_value = [{"name": "PRIVATE-MALFORMED"}]
    elif case == "limit":
        runtime.get_all.return_value = [row(str(index)) for index in range(MAX_FILE_OBSERVATIONS + 1)]
    elif case in ("reported", "cleared"):
        doc.custom_zatca_status = case.upper()
    current, status = doc.ksa_einv_qr, doc.get("custom_zatca_status")
    with pytest.raises(ValidationError) as error:
        advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=force)
    assert str(error.value) == create_qr.QR_REVIEW_REQUIRED and error.value.__context__ is None
    assert doc.ksa_einv_qr == current and doc.get("custom_zatca_status") == status
    assert_no_mutation(local_qr)


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("current", [None, "/files/QR-ZATCA-Advance-Aware-OLD.png", "/files/MISSING.png"])
def test_final_invoice_not_touched_even_if_old_filename_looks_wrong(local_qr, monkeypatch, force, current):
    doc, runtime, _, _ = local_qr
    doc.ksa_einv_qr = current
    runtime.get_all.side_effect = AssertionError("A print hook must not inspect final-invoice repair candidates")
    monkeypatch.setattr(advance_deduction, "is_advance_payment_invoice", lambda doc: False)
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=force)
    assert doc.ksa_einv_qr == current
    runtime.get_all.assert_not_called()
    assert_no_mutation(local_qr)


@pytest.mark.parametrize("gate", ["doctype", "phase2", "schema", "draft", "cancelled", "field", "zero", "negative"])
def test_ineligible_print_paths_skip_before_attachment_query(local_qr, monkeypatch, gate):
    doc, runtime, _, _ = local_qr
    if gate == "doctype":
        doc.doctype = "POS Invoice"
    elif gate == "phase2":
        monkeypatch.setattr(advance_deduction, "resolve_zatca_phase", lambda doc: advance_deduction.PHASE_2_VALUE)
    elif gate == "schema":
        monkeypatch.setattr(advance_deduction, "supports_advance_deduction_schema", lambda doc: False)
    elif gate in ("draft", "cancelled"):
        doc.docstatus = 0 if gate == "draft" else 2
    elif gate == "field":
        doc.meta.has_field = lambda name: False
    else:
        doc.custom_zatca_advance_deducted_taxable_amount = 0 if gate == "zero" else -1
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=True)
    runtime.get_all.assert_not_called()
    assert_no_mutation(local_qr)


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("old", [False, True])
@pytest.mark.parametrize("foreign", [False, True])
def test_first_generation_keeps_old_date_amount_fx_and_status_behavior(local_qr, force, old, foreign):
    doc, runtime, payloads, saver = local_qr
    doc.custom_zatca_status = "Not Submitted"
    if old:
        doc.posting_date = "2020-01-01"  # Age alone does not reject or change allocation.
    if foreign:
        doc.currency, doc.conversion_rate = "USD", 3.75
        doc.base_total, doc.base_net_total, doc.base_total_taxes_and_charges = 37.5, 37.5, 5.625
    before = (doc.posting_date, doc.total, doc.net_total, doc.conversion_rate,
        doc.custom_zatca_advance_deducted_taxable_amount, doc.total_taxes_and_charges)
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=force)
    tags = tlv_values(payloads[0])
    assert tags[4] == ("35.62" if foreign else "9.50")
    assert tags[5] == ("5.62" if foreign else "1.50")
    assert tags[3] == ("2020-01-01T06:05:42Z" if old else "2026-09-27T06:05:42Z")
    assert doc.ksa_einv_qr == "/files/SYNTHETIC-QR.png" and doc.custom_zatca_status == "Not Submitted"
    saver.assert_called_once()
    runtime.db.set_value.assert_called_once_with("Sales Invoice", doc.name, "ksa_einv_qr",
        "/files/SYNTHETIC-QR.png", update_modified=False)
    assert before == (doc.posting_date, doc.total, doc.net_total, doc.conversion_rate,
        doc.custom_zatca_advance_deducted_taxable_amount, doc.total_taxes_and_charges)
    runtime.db.commit.assert_not_called()
    runtime.delete_doc.assert_not_called()
    doc.db_set.assert_not_called()
    doc.save.assert_not_called()


@pytest.mark.parametrize("failure", ["file", "metadata"])
def test_first_generation_propagates_failure_without_taking_transaction_ownership(local_qr, failure):
    doc, runtime, _, saver = local_qr
    if failure == "file":
        saver.side_effect = RuntimeError("SYNTHETIC File failure")
    else:
        runtime.db.set_value.side_effect = RuntimeError("SYNTHETIC metadata failure")
    with pytest.raises(RuntimeError, match="SYNTHETIC"):
        advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=True)
    assert doc.ksa_einv_qr is None
    runtime.db.commit.assert_not_called()
    doc.save.assert_not_called()


@pytest.mark.parametrize("discount", [0, 2])
@pytest.mark.parametrize("foreign", [False, True])
def test_existing_discount_and_base_amount_selection_is_unchanged(local_qr, discount, foreign):
    doc, _, payloads, _ = local_qr
    doc.discount_amount, doc.net_total = discount, 8
    if foreign:
        doc.currency, doc.conversion_rate = "USD", 3.75
        doc.base_total, doc.base_net_total, doc.base_total_taxes_and_charges = 37.5, 30, 5.625
    advance_deduction.ensure_final_sales_invoice_qr_for_print(doc)
    expected = { (False, 0): "9.50", (False, 2): "7.50",
        (True, 0): "35.62", (True, 2): "28.12" }
    assert tlv_values(payloads[0])[4] == expected[foreign, discount]
    assert doc.net_total == 8 and doc.discount_amount == discount


def test_advance_review_uses_existing_arabic_message(local_qr, monkeypatch):
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        messages = dict(csv.reader(stream))
    translated = messages[create_qr.QR_REVIEW_REQUIRED]
    assert translated != create_qr.QR_REVIEW_REQUIRED
    monkeypatch.setattr(create_qr, "_", lambda message: messages[message])
    doc, runtime, _, _ = local_qr
    runtime.get_all.return_value = [row()]
    with pytest.raises(ValidationError) as error:
        advance_deduction.ensure_final_sales_invoice_qr_for_print(doc, force=True)
    assert str(error.value) == translated and error.value.__context__ is None
    assert_no_mutation(local_qr)


def test_hook_has_no_delete_commit_rollback_or_recursive_invoice_save():
    tree = ast.parse(inspect.getsource(advance_deduction.ensure_final_sales_invoice_qr_for_print))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("delete_doc", "commit", "rollback", "db_set", "sql")
            if node.func.attr == "save":
                assert isinstance(node.func.value, ast.Name) and node.func.value.id == "file_doc"
    assert advance_deduction._existing_qr_reference is create_qr._existing_qr_reference
