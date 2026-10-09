"""Read-only Frappe bridge with bounded files in pytest temporary directories."""

import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import artifact_inventory as inventory
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import (
    OTHER_UUID, SELLER, UUID, artifact_root, xml_bytes,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document


class PermissionDenied(Exception):
    pass


class MissingDocument(Exception):
    pass


@pytest.fixture
def local_inventory(monkeypatch, tmp_path):
    folder = tmp_path / "private" / "files"
    folder.mkdir(parents=True)
    documents, rows = {}, []

    def document(doctype, name, **values):
        doc = Document(doctype=doctype, name=name, check_permission=Mock(), **values)
        doc.save = Mock(side_effect=AssertionError("Diagnostic attempted save"))
        doc.db_set = Mock(side_effect=AssertionError("Diagnostic attempted db_set"))
        documents[doctype, name] = doc
        return doc

    company = document("Company", "TEST", tax_id=SELLER, custom_select="Production",
                       custom_private_key="DO-NOT-EXPOSE-PRIVATE-KEY",
                       custom_basic_auth_from_production="DO-NOT-EXPOSE-AUTH")
    invoice = document("Sales Invoice", "INV-TEST", company=company.name,
                       custom_uuid=UUID, custom_zatca_icv=77,
                       custom_zatca_issuing_unit="existing-chain", custom_zatca_status="REPORTED")

    def attach(name="sample.xml", content=None, **changes):
        if content is None:
            content = xml_bytes()
        path = folder / name
        path.write_bytes(content)
        values = dict(file_name=name, file_url="/private/files/" + name, is_private=1,
                      attached_to_doctype=invoice.doctype, attached_to_name=invoice.name)
        values.update(changes)
        doc = document("File", f"FILE-{len(rows)}", **values)
        rows.append({"name": doc.name, "file_name": name})
        return doc, path

    def get_doc(doctype, name):
        if (doctype, name) not in documents:
            raise MissingDocument()
        return documents[doctype, name]

    def throw(message):
        raise ValueError(message)

    forbidden = Mock(side_effect=AssertionError("Diagnostic attempted database mutation"))
    fake = SimpleNamespace(
        get_doc=Mock(side_effect=get_doc), get_all=Mock(return_value=rows),
        get_site_path=Mock(side_effect=lambda *parts: str(tmp_path.joinpath(*parts))),
        db=SimpleNamespace(set_value=forbidden, commit=forbidden, sql=forbidden),
        PermissionError=PermissionDenied, DoesNotExistError=MissingDocument, throw=throw,
    )
    monkeypatch.setattr(inventory, "frappe", fake)
    monkeypatch.setattr(inventory, "_", lambda message: message)
    return SimpleNamespace(invoice=invoice, company=company, attach=attach,
                           docs=documents, rows=rows, folder=folder, frappe=fake)


def inspect(b):
    return inventory.inspect_saved_invoice_artifacts(b.invoice.doctype, b.invoice.name)


def test_consistent_identity_is_neither_acceptance_nor_replay_authority(local_inventory):
    b = local_inventory
    file, path = b.attach()
    before = path.read_bytes()
    result = inspect(b)
    assert result["state"] == "IDENTITY_CONSISTENT"
    assert result["issues"] == []
    candidate = result["candidates"][0]
    assert (candidate["uuid"], candidate["icv"], candidate["seller_tax_id"]) == (UUID, 77, SELLER)
    assert candidate["issues"] == []
    assert result["signature_verified"] is False
    assert result["remote_acceptance_verified"] is False
    assert result["replay_authorized"] is False
    assert result["scope"] == "saved_identity_and_attached_xml_only"
    assert path.read_bytes() == before
    b.frappe.get_all.assert_called_once_with(
        "File", filters={"attached_to_doctype": "Sales Invoice", "attached_to_name": "INV-TEST"},
        fields=["name", "file_name"], order_by="creation asc",
    )
    for doc in (b.invoice, b.company, file):
        doc.check_permission.assert_called_once_with("read")
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    assert b.company.custom_private_key == "DO-NOT-EXPOSE-PRIVATE-KEY"


def test_pos_uses_same_reader_and_saved_ownership(local_inventory):
    b = local_inventory
    b.docs.pop((b.invoice.doctype, b.invoice.name))
    b.invoice.doctype = "POS Invoice"
    b.docs[b.invoice.doctype, b.invoice.name] = b.invoice
    b.attach()
    assert inspect(b)["state"] == "IDENTITY_CONSISTENT"


@pytest.mark.parametrize("private", [1, "1", True])
def test_private_checkbox_representations(local_inventory, private):
    b = local_inventory
    b.attach(is_private=private)
    assert inspect(b)["state"] == "IDENTITY_CONSISTENT"


@pytest.mark.parametrize("doctype", ["Company", "Purchase Invoice", "", None])
def test_invalid_target_has_no_record_or_file_io(local_inventory, doctype):
    b = local_inventory
    with pytest.raises(ValueError, match="Only Sales Invoice"):
        inventory.inspect_saved_invoice_artifacts(doctype, "INV-TEST")
    b.frappe.get_doc.assert_not_called()
    b.frappe.get_all.assert_not_called()


@pytest.mark.parametrize("name", ["", " ", None, 1, {}])
def test_missing_target_has_no_record_io(local_inventory, name):
    with pytest.raises(ValueError, match="invoice name is required"):
        inventory.inspect_saved_invoice_artifacts("Sales Invoice", name)
    local_inventory.frappe.get_doc.assert_not_called()


@pytest.mark.parametrize("target", ["invoice", "company"])
def test_read_permission_is_required_before_file_discovery(local_inventory, target):
    b = local_inventory
    getattr(b, target).check_permission.side_effect = PermissionDenied()
    with pytest.raises(PermissionDenied):
        inspect(b)
    b.frappe.get_all.assert_not_called()


def test_missing_company_blocks_inspection(local_inventory):
    b = local_inventory
    b.invoice.company = ""
    with pytest.raises(ValueError, match="Company is required"):
        inspect(b)
    b.frappe.get_all.assert_not_called()


@pytest.mark.parametrize("changes, expected", [
    ({"custom_uuid": "Not Submitted"}, "saved_uuid_missing"),
    ({"custom_uuid": "garbage"}, "saved_uuid_invalid"),
    ({"custom_uuid": OTHER_UUID}, "saved_uuid_mismatch"),
    ({"custom_zatca_icv": 78}, "saved_icv_mismatch"),
    ({"custom_zatca_issuing_unit": ""}, "saved_unit_missing"),
])
def test_saved_field_conflicts_are_not_repaired(local_inventory, changes, expected):
    b = local_inventory
    b.attach()
    for key, value in changes.items():
        setattr(b.invoice, key, value)
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert result["candidates"][0]["issues"] == [expected]
    for key, value in changes.items():
        assert getattr(b.invoice, key) == value


@pytest.mark.parametrize("body", [
    lambda: xml_bytes(artifact_root(invoice_id="OTHER-INVOICE")),
    lambda: xml_bytes(artifact_root(seller="OTHER-VAT")),
])
def test_attachment_label_is_not_proof_of_xml_ownership(local_inventory, body):
    b = local_inventory
    b.attach(content=body())
    assert inspect(b)["state"] == "RECONCILIATION_REQUIRED"


def test_identical_copies_are_reported_without_selecting_or_deleting(local_inventory):
    b = local_inventory
    b.attach("one.xml")
    b.attach("two.xml")
    report = inspect(b)
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert len(report["candidates"]) == 2
    assert len(list(b.folder.iterdir())) == 2


def test_equal_identity_with_different_bytes_remains_a_conflict(local_inventory):
    b = local_inventory
    b.attach("first.xml")
    b.attach("second.xml", xml_bytes().replace(b"><", b">\n<"))
    report = inspect(b)
    assert report["state"] == "CONFLICT"
    assert report["issues"] == ["artifact_bytes_conflict"]
    assert all(candidate["issues"] == [] for candidate in report["candidates"])
    assert report["replay_authorized"] is False


def test_malformed_candidate_does_not_disappear_behind_a_good_one(local_inventory):
    b = local_inventory
    b.attach("bad.xml", b"<Private-data-do-not-leak>")
    b.attach("good.xml")
    report = inspect(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["candidates"][0]["issues"] == ["xml_syntax"]
    assert report["candidates"][1]["issues"] == []
    assert "Private-data-do-not-leak" not in json.dumps(report)


@pytest.mark.parametrize("name", ["DEBUG_INVOICE_INV-TEST.xml", "debug_invoice_inv.xml", "qr.png", "note.txt"])
def test_debug_and_non_xml_are_not_issuance_evidence(local_inventory, name):
    b = local_inventory
    b.attach(name)
    result = inspect(b)
    assert result["state"] == "NO_ATTACHED_XML"
    assert result["candidates"] == []
    assert len(result["skipped"]) == 1
    assert len(b.frappe.get_doc.call_args_list) == 2


@pytest.mark.parametrize("changes, code", [
    ({"is_private": 0}, "attachment_not_private"),
    ({"is_private": "0"}, "attachment_not_private"),
    ({"attached_to_doctype": "POS Invoice"}, "attachment_owner"),
    ({"attached_to_name": "OTHER"}, "attachment_owner"),
    ({"file_name": "DEBUG_INVOICE_test.xml"}, "attachment_kind"),
    ({"file_name": "test.png"}, "attachment_kind"),
    ({"file_url": "https://example.invalid/test.xml"}, "attachment_path"),
    ({"file_url": "/files/test.xml"}, "attachment_path"),
    ({"file_url": "/private/files/../test.xml"}, "attachment_path"),
    ({"file_url": "/private/files/%2e%2e%2ftest.xml"}, "attachment_path"),
    ({"file_url": "/private/files/..\\test.xml"}, "attachment_path"),
    ({"file_url": "/private/files/%00test.xml"}, "attachment_path"),
    ({"file_url": None}, "attachment_path"),
    ({"file_url": "/private/files/"}, "attachment_path"),
])
def test_ineligible_paths_and_stale_attachment_metadata_are_not_read(local_inventory, changes, code):
    b = local_inventory
    b.attach(**changes)
    b.frappe.get_site_path.side_effect = AssertionError("Unsafe candidate reached filesystem")
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert result["candidates"][0]["issues"] == [code]
    b.frappe.get_site_path.assert_not_called()


def test_unicode_and_percent_encoded_local_basename(local_inventory):
    b = local_inventory
    b.attach("فاتورة اختبار.xml", file_url="/private/files/فاتورة%20اختبار.xml")
    assert inspect(b)["state"] == "IDENTITY_CONSISTENT"


@pytest.mark.parametrize("problem, code", [
    ("missing", "attachment_read"), ("directory", "attachment_file_type"),
    ("empty", "xml_size"), ("outside-symlink", "attachment_path"),
    ("inside-symlink", "attachment_read"),
    ("fifo", "attachment_file_type"),
])
def test_file_failures_are_static_and_do_not_stop_other_candidates(local_inventory, problem, code):
    b = local_inventory
    _, path = b.attach("bad.xml")
    path.unlink()
    if problem == "directory":
        path.mkdir()
    elif problem == "empty":
        path.write_bytes(b"")
    elif problem == "fifo":
        os.mkfifo(path)
    elif problem == "outside-symlink":
        path.symlink_to(b.folder.parent)
    elif problem == "inside-symlink":
        _, good_path = b.attach("linked.xml")
        path.symlink_to(good_path)
    b.attach("good.xml")
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert result["candidates"][0]["issues"] == [code]
    assert result["candidates"][-1]["issues"] == []
    assert str(b.folder) not in json.dumps(result)


def test_size_limit_is_checked_before_xml_read(local_inventory, monkeypatch):
    b = local_inventory
    b.attach()
    monkeypatch.setattr(inventory, "MAX_XML_BYTES", 10)
    report = inspect(b)
    assert report["candidates"][0]["issues"] == ["xml_size"]


@pytest.mark.parametrize("problem, code", [("permission", "attachment_permission"), ("missing-record", "attachment_missing")])
def test_file_record_failure_preserves_other_candidates(local_inventory, problem, code):
    b = local_inventory
    doc, _ = b.attach("bad.xml")
    if problem == "permission":
        doc.check_permission.side_effect = PermissionDenied()
    else:
        del b.docs["File", doc.name]
    b.attach("good.xml")
    result = inspect(b)
    assert result["candidates"][0]["issues"] == [code]
    assert result["candidates"][1]["issues"] == []


def test_new_fatal_diagnostic_messages_have_arabic_translations():
    path = Path(__file__).resolve().parents[2] / "translations" / "ar.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        translations = {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}
    for message in (
        "Only Sales Invoice and POS Invoice artifact inspection is supported.",
        "An invoice name is required for artifact inspection.",
        "Company is required for invoice artifact inspection.",
    ):
        assert any("\u0600" <= char <= "\u06ff" for char in translations[message])
