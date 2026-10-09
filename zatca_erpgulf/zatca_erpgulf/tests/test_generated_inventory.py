"""Opt-in generated XML evidence, using only mocked records and temporary files."""

import csv
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import artifact_inventory as inventory
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import MAX_XML_BYTES
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import (
    OTHER_UUID, artifact_root, xml_bytes,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_inventory import (
    PermissionDenied, local_inventory,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_history_inventory import history_inventory


@pytest.fixture
def generated_inventory(local_inventory):
    b = local_inventory
    b.frappe.only_for = Mock()
    b.frappe.db.exists = Mock(return_value=False)
    b.path = b.folder / f"final_xml_after_indent_{b.invoice.name}.xml"
    return b


def inspect(b, **options):
    return inventory.inspect_saved_invoice_artifacts(
        b.invoice.doctype, b.invoice.name, include_generated=True, **options
    )


def rename_invoice(b, name):
    b.docs.pop((b.invoice.doctype, b.invoice.name))
    b.invoice.name = name
    b.docs[b.invoice.doctype, name] = b.invoice
    b.path = b.folder / f"final_xml_after_indent_{name}.xml"


def test_default_does_not_read_generated_file_or_check_operator_role(generated_inventory):
    b = generated_inventory
    b.path.write_bytes(b"NOT XML")
    result = inventory.inspect_saved_invoice_artifacts(b.invoice.doctype, b.invoice.name)
    assert result["state"] == "NO_ATTACHED_XML"
    assert "generated" not in result
    b.frappe.only_for.assert_not_called()
    b.frappe.db.exists.assert_not_called()
    b.frappe.get_site_path.assert_not_called()


def test_matching_generated_metadata_does_not_authorize_replay(generated_inventory):
    b = generated_inventory
    content = xml_bytes()
    b.path.write_bytes(content)
    result = inspect(b)
    assert result["state"] == "IDENTITY_CONSISTENT"
    assert result["scope"] == "saved_identity_attached_and_generated_xml"
    assert result["generated"]["status"] == "PRESENT"
    candidate = result["generated"]["candidates"][0]
    assert candidate["issues"] == []
    assert candidate["file_sha256"] == hashlib.sha256(content).hexdigest()
    assert candidate["source"] == "generated_signed_xml"
    for flag in ("generated_inventory_complete", "signature_verified",
                 "remote_acceptance_verified", "replay_authorized"):
        assert result[flag] is False
    b.frappe.only_for.assert_called_once_with("System Manager", message=True)
    b.frappe.db.exists.assert_called_once_with("POS Invoice", b.invoice.name)
    assert b.path.read_bytes() == content
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    for doc in (b.invoice, b.company):
        doc.check_permission.assert_called_once_with("read")
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.frappe.db.set_value.assert_not_called()


def test_loose_mode_requires_operator_role_before_any_file_access(generated_inventory):
    b = generated_inventory
    b.frappe.only_for.side_effect = PermissionDenied()
    with pytest.raises(PermissionDenied):
        inspect(b)
    b.frappe.get_all.assert_not_called()
    b.frappe.get_site_path.assert_not_called()
    b.frappe.db.exists.assert_not_called()


@pytest.mark.parametrize("target", ["invoice", "company"])
def test_document_read_permission_is_still_required(generated_inventory, target):
    b = generated_inventory
    getattr(b, target).check_permission.side_effect = PermissionDenied()
    with pytest.raises(PermissionDenied):
        inspect(b)
    b.frappe.only_for.assert_not_called()
    b.frappe.get_site_path.assert_not_called()


@pytest.mark.parametrize("option", [None, 0, 1, "true", "false", [], {}])
def test_generated_option_is_strict_boolean(generated_inventory, option):
    b = generated_inventory
    with pytest.raises(ValueError, match="generated XML inspection option"):
        inventory.inspect_saved_invoice_artifacts(
            b.invoice.doctype, b.invoice.name, include_generated=option
        )
    b.frappe.get_doc.assert_not_called()


def test_missing_file_is_absence_not_non_issuance(generated_inventory):
    b = generated_inventory
    result = inspect(b)
    assert result["state"] == "NO_XML_EVIDENCE"
    assert result["generated"] == {"status": "MISSING", "issues": [], "candidates": []}
    assert result["replay_authorized"] is False


def test_missing_generated_file_does_not_invalidate_matching_attachment(generated_inventory):
    b = generated_inventory
    b.attach()
    assert inspect(b)["state"] == "IDENTITY_CONSISTENT"


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_cross_doctype_name_collision_is_not_silently_selected(generated_inventory, doctype):
    b = generated_inventory
    b.docs.pop((b.invoice.doctype, b.invoice.name))
    b.invoice.doctype = doctype
    b.docs[doctype, b.invoice.name] = b.invoice
    b.frappe.db.exists.return_value = "OTHER-DOCUMENT-NAME-NOT-TO-EXPOSE"
    b.path.write_bytes(xml_bytes())
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert result["generated"]["issues"] == ["generated_doctype_ambiguous"]
    other = "POS Invoice" if doctype == "Sales Invoice" else "Sales Invoice"
    b.frappe.db.exists.assert_called_once_with(other, b.invoice.name)
    assert "OTHER-DOCUMENT" not in json.dumps(result)
    assert b.frappe.get_doc.call_count == 2


@pytest.mark.parametrize("name", ["../other", "nested/INV", r"nested\INV", "INV\x00NAME", ".", ".."])
def test_unsafe_invoice_name_never_becomes_a_path(generated_inventory, name):
    b = generated_inventory
    rename_invoice(b, name)
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert result["generated"]["issues"] == ["generated_name_unsafe"]
    b.frappe.db.exists.assert_not_called()
    b.frappe.get_site_path.assert_not_called()


@pytest.mark.parametrize("name", ["INV عربي 01", "INV%2fTEST", "INV..TEST"])
def test_valid_literal_basename_is_not_url_decoded_or_sanitized(generated_inventory, name):
    b = generated_inventory
    rename_invoice(b, name)
    b.path.write_bytes(xml_bytes(artifact_root(invoice_id=name)))
    assert inspect(b)["state"] == "IDENTITY_CONSISTENT"


@pytest.mark.parametrize("content", [b"", b"not XML", b"<invoice>", b"x" * (MAX_XML_BYTES + 1)])
def test_malformed_or_oversized_file_requires_reconciliation(generated_inventory, content):
    b = generated_inventory
    b.path.write_bytes(content)
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert result["generated"]["candidates"][0]["issues"]
    assert b.path.read_bytes() == content


@pytest.mark.parametrize("kind,code", [
    ("directory", "generated_file_type"), ("fifo", "generated_file_type"),
    ("inside_symlink", "generated_read"), ("outside_symlink", "generated_path"),
    ("dangling_symlink", "generated_read"),
])
def test_nonregular_or_symlink_file_is_never_followed(generated_inventory, tmp_path, kind, code):
    b = generated_inventory
    if kind == "directory":
        b.path.mkdir()
    elif kind == "fifo":
        os.mkfifo(b.path)
    else:
        target = b.folder / "other.xml" if kind == "inside_symlink" else tmp_path / "other.xml"
        if kind != "dangling_symlink":
            target.write_bytes(xml_bytes())
        b.path.symlink_to(target)
    result = inspect(b)
    assert result["generated"]["status"] == "UNREADABLE"
    assert result["generated"]["candidates"][0]["issues"] == [code]


def test_mismatched_metadata_is_not_trusted_based_on_filename(generated_inventory):
    b = generated_inventory
    b.path.write_bytes(xml_bytes(artifact_root(uuid=OTHER_UUID)))
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert "saved_uuid_mismatch" in result["generated"]["candidates"][0]["issues"]


def test_different_exact_bytes_are_preserved_as_conflicting_sources(generated_inventory):
    b = generated_inventory
    b.attach()
    b.path.write_bytes(xml_bytes() + b"\n")
    result = inspect(b)
    assert result["state"] == "CONFLICT"
    assert result["issues"] == ["artifact_bytes_conflict"]
    assert result["candidates"][0]["issues"] == []
    assert result["generated"]["candidates"][0]["issues"] == []


def test_same_bytes_keep_both_sources_without_selecting_a_winner(generated_inventory):
    b = generated_inventory
    b.attach()
    b.path.write_bytes(xml_bytes())
    result = inspect(b)
    assert result["state"] == "IDENTITY_CONSISTENT"
    assert len(result["candidates"]) == len(result["generated"]["candidates"]) == 1


def test_generated_mode_never_scans_directory_or_reads_unsigned_files(generated_inventory, monkeypatch):
    b = generated_inventory
    b.path.write_bytes(xml_bytes())
    (b.folder / f"finalzatcaxml_{b.invoice.name}.xml").write_bytes(b"DO-NOT-READ")
    forbidden = Mock(side_effect=AssertionError("Directory scan attempted"))
    for method in ("iterdir", "glob", "rglob"):
        monkeypatch.setattr(Path, method, forbidden)
    assert inspect(b)["state"] == "IDENTITY_CONSISTENT"
    forbidden.assert_not_called()


@pytest.mark.parametrize("error", [PermissionError("PRIVATE-PATH"), OSError("PRIVATE-PATH"),
                                   ValueError("PRIVATE-PATH")])
def test_os_failures_are_static_and_do_not_expose_paths(generated_inventory, monkeypatch, error):
    b = generated_inventory
    b.path.write_bytes(xml_bytes())
    monkeypatch.setattr(inventory.os, "open", Mock(side_effect=error))
    result = inspect(b)
    assert result["state"] == "RECONCILIATION_REQUIRED"
    assert result["generated"]["candidates"][0]["issues"] == ["generated_read"]
    assert "PRIVATE-PATH" not in json.dumps(result)


def test_generated_option_error_has_arabic_translation():
    translations = Path(inventory.__file__).parents[1] / "translations" / "ar.csv"
    with translations.open(encoding="utf-8", newline="") as handle:
        rows = dict((row[0], row[1]) for row in csv.reader(handle) if len(row) >= 2)
    message = "The generated XML inspection option must be true or false."
    assert message in rows
    assert any("\u0600" <= char <= "\u06ff" for char in rows[message])


def test_history_and_generated_options_compose_without_counter_mutation(history_inventory):
    b = history_inventory
    b.add_counter()
    b.frappe.only_for = Mock()
    original_exists = b.frappe.db.exists.side_effect
    b.frappe.db.exists.side_effect = lambda doctype, name=None: (
        False if doctype == "POS Invoice" else original_exists(doctype, name)
    )
    path = b.folder / f"final_xml_after_indent_{b.invoice.name}.xml"
    path.write_bytes(xml_bytes())
    result = inspect(b, include_history=True)
    assert result["scope"] == "saved_identity_attached_generated_xml_response_and_counter"
    assert result["state"] == "IDENTITY_CONSISTENT"
    assert result["response"]["outcome"] == "OBSERVED_REPORTED"
    assert result["history_complete"] is False
    assert result["counter"]["issues"] == []
