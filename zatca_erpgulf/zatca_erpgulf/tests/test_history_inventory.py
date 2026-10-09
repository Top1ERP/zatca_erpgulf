"""Opt-in response/counter history bridge without live database or HTTP."""

import base64
import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import counter_inventory, icv
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import OTHER_UUID, artifact_root, xml_bytes
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_inventory import (
    inventory, local_inventory, MissingDocument, PermissionDenied,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_history_evidence import response_body
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


@pytest.fixture
def history_inventory(local_inventory, monkeypatch):
    b = local_inventory
    b.invoice.custom_zatca_full_response = json.dumps(response_body())
    b.expected_key = counter_inventory.legacy_counter_key("TEST", "existing-chain", "Production")
    b.schema = True

    def add_counter(name=None, **changes):
        name = name or b.expected_key
        data = dict(company="TEST", issuing_unit="existing-chain", environment="Production",
                    counter_key=name, active=1, last_issued_icv=77,
                    last_invoice="INV-TEST", last_invoice_doctype="Sales Invoice")
        data.update(changes)
        doc = Document(name=name, doctype="ZATCA ICV Counter", check_permission=Mock(), **data)
        doc.save = Mock(side_effect=AssertionError("Counter save attempted"))
        doc.db_set = Mock(side_effect=AssertionError("Counter update attempted"))
        b.docs[doc.doctype, doc.name] = doc
        return doc

    def exists(doctype, name):
        if doctype == "DocType":
            assert name == "ZATCA ICV Counter"
            return b.schema
        assert doctype == "ZATCA ICV Counter"
        return (doctype, name) in b.docs

    def get_all(doctype, **kwargs):
        if doctype == "File":
            return b.rows
        assert doctype == "ZATCA ICV Counter"
        records = [doc for (dt, _), doc in b.docs.items() if dt == doctype
                   and all(doc.get(key) == value for key, value in kwargs["filters"].items())]
        return [{"name": doc.name} for doc in sorted(records, key=lambda doc: doc.name)[:2]]

    b.add_counter = add_counter
    b.counter = add_counter()
    b.frappe.db.exists = Mock(side_effect=exists)
    b.frappe.get_all.side_effect = get_all
    monkeypatch.setattr(counter_inventory, "frappe", b.frappe)
    # Prove the history reader cannot create/seed counters or read current auth.
    for method in ("_get_or_create_counter", "get_icv", "seed_company_counter", "_issuing_unit"):
        monkeypatch.setattr(icv, method, Mock(side_effect=AssertionError("Live ICV path called")))
    return b


def inspect_history(b):
    return inventory.inspect_saved_invoice_artifacts(
        b.invoice.doctype, b.invoice.name, include_history=True,
    )


def test_default_inventory_does_not_load_history_or_counters(history_inventory):
    b = history_inventory
    b.attach()
    report = inventory.inspect_saved_invoice_artifacts(b.invoice.doctype, b.invoice.name)
    assert "response" not in report and "counter" not in report
    assert report["scope"] == "saved_identity_and_attached_xml_only"
    b.frappe.db.exists.assert_not_called()
    b.counter.check_permission.assert_not_called()


@pytest.mark.parametrize("option", ["1", "0", 1, 0, None, "false"])
def test_history_option_is_explicit_not_truthy(history_inventory, option):
    b = history_inventory
    with pytest.raises(ValueError, match="true or false"):
        inventory.inspect_saved_invoice_artifacts("Sales Invoice", b.invoice.name, include_history=option)
    b.frappe.get_doc.assert_not_called()


def test_complete_observed_identity_still_does_not_authorize_replay(history_inventory):
    b = history_inventory
    b.attach()
    raw = b.invoice.custom_zatca_full_response
    report = inspect_history(b)
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert report["scope"] == "saved_identity_attached_xml_response_and_counter"
    assert report["response"]["outcome"] == "OBSERVED_REPORTED"
    assert report["counter"]["issues"] == []
    assert report["counter"]["candidates"][0]["issues"] == []
    assert report["history_complete"] is False
    assert report["signature_verified"] is False
    assert report["remote_acceptance_verified"] is False
    assert report["replay_authorized"] is False
    assert b.invoice.custom_zatca_full_response == raw
    b.counter.check_permission.assert_called_once_with("read")
    b.counter.save.assert_not_called()
    b.counter.db_set.assert_not_called()
    assert "DO-NOT-EXPOSE" not in json.dumps(report)
    b.frappe.get_all.assert_any_call(
        "ZATCA ICV Counter",
        filters={"company": "TEST", "issuing_unit": "existing-chain", "environment": "Production"},
        fields=["name"], order_by="name asc", limit_page_length=2,
    )


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
def test_counter_lookup_keeps_legacy_document_purpose(history_inventory, environment):
    b = history_inventory
    b.attach()
    b.company.custom_select = environment
    report = inspect_history(b)
    assert report["counter"]["purpose"] == "Production"
    assert report["counter"]["api_environment"] == environment
    assert report["counter"]["expected_key"] == b.expected_key
    assert report["state"] == "IDENTITY_CONSISTENT"


def test_pos_history_uses_same_saved_doctype_boundary(history_inventory):
    b = history_inventory
    del b.docs[b.invoice.doctype, b.invoice.name]
    b.invoice.doctype = "POS Invoice"
    b.docs[b.invoice.doctype, b.invoice.name] = b.invoice
    b.counter.last_invoice_doctype = "POS Invoice"
    b.attach()
    assert inspect_history(b)["state"] == "IDENTITY_CONSISTENT"


@pytest.mark.parametrize("issue", ["missing", "malformed", "rejected", "inconsistent"])
def test_saved_reported_status_does_not_hide_bad_response(history_inventory, issue):
    b = history_inventory
    b.attach()
    if issue == "missing":
        b.invoice.custom_zatca_full_response = "Not Submitted"
    elif issue == "malformed":
        b.invoice.custom_zatca_full_response = "DO-NOT-ECHO-malformed-JSON"
    elif issue == "rejected":
        b.invoice.custom_zatca_full_response = json.dumps(response_body(
            "none", validationResults={"status": "ERROR", "errorMessages": [{"code": "bad"}]},
        ))
    else:
        b.invoice.custom_zatca_full_response = json.dumps(response_body("cleared"))
    report = inspect_history(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["response"]["issues"]
    assert "DO-NOT-ECHO" not in json.dumps(report)


def test_stored_cleared_xml_can_supply_evidence_without_an_attachment(history_inventory):
    b = history_inventory
    b.invoice.custom_zatca_status = "CLEARED"
    b.invoice.custom_zatca_full_response = json.dumps(response_body("cleared"))
    report = inspect_history(b)
    assert report["candidates"] == []
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert report["response_candidates"][0]["source"] == "stored_response:clearedInvoice"
    assert report["response_candidates"][0]["issues"] == []
    assert "clearedInvoice" not in json.dumps(report["response"])


def test_no_xml_in_reported_response_does_not_manufacture_an_artifact(history_inventory):
    report = inspect_history(history_inventory)
    assert report["state"] == "NO_XML_EVIDENCE"
    assert report["response_candidates"] == []
    assert report["response"]["outcome"] == "OBSERVED_REPORTED"


@pytest.mark.parametrize("problem", ["syntax", "identity", "different-bytes", "invalid-base64"])
def test_response_and_attachment_are_reconciled_without_selecting_newest(history_inventory, problem):
    b = history_inventory
    _, path = b.attach()
    original = path.read_bytes()
    value = xml_bytes()
    if problem == "syntax":
        value = b"<private-bad-data>"
    elif problem == "identity":
        value = xml_bytes(artifact_root(uuid=OTHER_UUID))
    elif problem == "different-bytes":
        value = value.replace(b"><", b">\n<")
    encoded = "%%%" if problem == "invalid-base64" else base64.b64encode(value).decode()
    b.invoice.custom_zatca_full_response = json.dumps(response_body(reportedInvoice=encoded))
    report = inspect_history(b)
    assert report["state"] == ("CONFLICT" if problem in ("identity", "different-bytes") else "RECONCILIATION_REQUIRED")
    assert path.read_bytes() == original
    assert report["replay_authorized"] is False
    assert "private-bad-data" not in json.dumps(report)


def test_identical_response_and_attachment_are_listed_separately(history_inventory):
    b = history_inventory
    b.attach()
    b.invoice.custom_zatca_full_response = json.dumps(response_body(
        reportedInvoice=base64.b64encode(xml_bytes()).decode(),
    ))
    report = inspect_history(b)
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert report["response_candidates"][0]["file_sha256"] == report["candidates"][0]["file_sha256"]


@pytest.mark.parametrize("problem, code", [
    ("unit-missing", "saved_unit_missing"), ("schema-missing", "counter_schema_missing"),
    ("counter-missing", "counter_missing"),
])
def test_missing_counter_context_never_creates_one(history_inventory, problem, code):
    b = history_inventory
    b.attach()
    if problem == "unit-missing":
        b.invoice.custom_zatca_issuing_unit = ""
    elif problem == "schema-missing":
        b.schema = False
    else:
        del b.docs[b.counter.doctype, b.counter.name]
    report = inspect_history(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["counter"]["issues"] == [code]
    b.counter.save.assert_not_called()


@pytest.mark.parametrize("changes, code", [
    ({"company": "OTHER"}, "counter_company_mismatch"),
    ({"issuing_unit": "OTHER-CHAIN"}, "counter_unit_mismatch"),
    ({"environment": "Compliance"}, "counter_purpose_mismatch"),
    ({"counter_key": "OTHER-KEY"}, "counter_key_mismatch"),
    ({"active": 0}, "counter_inactive"),
    ({"last_issued_icv": 76}, "counter_below_invoice"),
    ({"last_issued_icv": "bad"}, "counter_position_invalid"),
    ({"last_invoice_doctype": "POS Invoice"}, "counter_tail_doctype_mismatch"),
])
def test_named_counter_collision_or_bad_tail_does_not_seed_or_merge(history_inventory, changes, code):
    b = history_inventory
    b.attach()
    for field, value in changes.items():
        setattr(b.counter, field, value)
    report = inspect_history(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["counter"]["candidates"][0]["issues"] == [code]
    for field, value in changes.items():
        assert getattr(b.counter, field) == value


def test_more_recent_counter_does_not_rewind_to_this_invoice(history_inventory):
    b = history_inventory
    b.attach()
    b.counter.last_issued_icv = 120
    b.counter.last_invoice = "LATER-INVOICE"
    report = inspect_history(b)
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert report["counter"]["candidates"][0]["last_issued_icv"] == "120"
    assert b.counter.last_issued_icv == 120


def test_multiple_tuple_matches_do_not_pick_largest_or_current_pointer(history_inventory):
    b = history_inventory
    b.attach()
    b.add_counter("ANOTHER", last_issued_icv=200)
    b.company.custom_zatca_icv_counter = "ANOTHER"
    report = inspect_history(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["counter"]["issues"] == ["counter_tuple_ambiguous"]
    assert len(report["counter"]["candidates"]) == 2
    assert b.counter.last_issued_icv == 77


@pytest.mark.parametrize("problem, code", [("permission", "counter_permission"), ("disappeared", "counter_record_missing")])
def test_counter_permission_and_disappearance_are_static(history_inventory, problem, code):
    b = history_inventory
    b.attach()
    if problem == "permission":
        b.counter.check_permission.side_effect = PermissionDenied()
    else:
        original = b.frappe.get_doc.side_effect

        def get_doc(doctype, name):
            if doctype == "ZATCA ICV Counter":
                raise MissingDocument()
            return original(doctype, name)

        b.frappe.get_doc.side_effect = get_doc
    report = inspect_history(b)
    candidate = report["counter"]["candidates"][0]
    assert candidate == {"counter": b.expected_key, "issues": [code]}
    assert report["state"] == "RECONCILIATION_REQUIRED"


def test_history_option_error_has_arabic_translation():
    path = Path(__file__).resolve().parents[2] / "translations" / "ar.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        translated = {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}
    assert any("\u0600" <= char <= "\u06ff" for char in translated[
        "The artifact history inspection option must be true or false."
    ])
