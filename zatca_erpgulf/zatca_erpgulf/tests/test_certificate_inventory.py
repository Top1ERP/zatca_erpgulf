"""Opt-in fingerprint provenance without current credential reads or mutations."""

import base64
import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import artifact_inventory as inventory, credential_settings
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import OTHER_UUID, xml_bytes
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_inventory import PermissionDenied, local_inventory
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import (
    certificates, certificate_root, cert_node,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_history_evidence import response_body
from zatca_erpgulf.zatca_erpgulf.tests.test_history_inventory import history_inventory


def inspect(b, **options):
    return inventory.inspect_saved_invoice_artifacts(
        b.invoice.doctype, b.invoice.name, include_certificate=True, **options
    )


def test_default_inventory_does_not_inspect_embedded_certificate(local_inventory, monkeypatch):
    b = local_inventory
    b.attach()
    forbidden = Mock(side_effect=AssertionError("Opt-in certificate inspector called"))
    monkeypatch.setattr(inventory, "inspect_embedded_certificate", forbidden)
    report = inventory.inspect_saved_invoice_artifacts(b.invoice.doctype, b.invoice.name)
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert "certificate" not in report["candidates"][0]
    assert "certificate_observation" not in report
    forbidden.assert_not_called()


@pytest.mark.parametrize("option", [None, 0, 1, "true", "false", {}, []])
def test_certificate_option_is_strict_boolean(local_inventory, option):
    b = local_inventory
    with pytest.raises(ValueError, match="embedded certificate inspection option"):
        inventory.inspect_saved_invoice_artifacts(b.invoice.doctype, b.invoice.name, include_certificate=option)
    b.frappe.get_doc.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_public_cert_observation_is_not_verified_epoch_or_acceptance(local_inventory, certificates, doctype):
    b = local_inventory
    b.docs.pop((b.invoice.doctype, b.invoice.name))
    b.invoice.doctype = doctype
    b.docs[doctype, b.invoice.name] = b.invoice
    content = xml_bytes(certificate_root(certificates[0]))
    file, path = b.attach(content=content)
    report = inspect(b)
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert report["scope"] == "saved_identity_and_attached_xml_only_and_embedded_certificate"
    assert report["certificate_observation"] == {
        "version_count": 1, "public_key_count": 1, "credential_epoch_verified": False,
        "owner_verified": False, "purpose_verified": False, "trust_verified": False,
    }
    assert report["candidates"][0]["certificate"]["issues"] == []
    for key in ("signature_verified", "remote_acceptance_verified", "replay_authorized"):
        assert report[key] is False
    assert "PRIVATE-DN" not in json.dumps(report)
    assert base64.b64encode(certificates[0]).decode() not in json.dumps(report)
    assert path.read_bytes() == content
    for doc in (b.invoice, b.company, file):
        doc.check_permission.assert_called_once_with("read")
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
    b.frappe.db.set_value.assert_not_called()
    b.frappe.db.commit.assert_not_called()


def test_saved_keys_auth_and_certificate_fields_are_never_read(local_inventory, certificates, monkeypatch):
    b = local_inventory
    b.attach(content=xml_bytes(certificate_root(certificates[0])))
    forbidden = Mock(side_effect=AssertionError("Current credential path called"))
    for name in ("resolve_credential_owner", "get_signing_certificate", "get_signing_key", "get_api_authorization"):
        monkeypatch.setattr(credential_settings, name, forbidden)
    for doc in (b.company, b.invoice):
        getter = doc.get

        def guard(field, default=None, getter=getter):
            if field in credential_settings.SECRET_FIELDS:
                raise AssertionError("Current secret/certificate field read")
            return getter(field, default)

        doc.get = guard
    assert inspect(b)["state"] == "IDENTITY_CONSISTENT"
    forbidden.assert_not_called()


def test_missing_certificate_is_visible_not_taken_from_current_company(local_inventory):
    b = local_inventory
    b.attach()
    report = inspect(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["candidates"][0]["certificate"]["issues"] == ["certificate_signature_location"]
    assert report["certificate_observation"]["version_count"] == 0


def test_no_artifact_does_not_infer_certificate_from_saved_status(local_inventory):
    report = inspect(local_inventory)
    assert report["state"] == "NO_ATTACHED_XML"
    assert report["certificate_observation"]["version_count"] == 0
    assert report["replay_authorized"] is False


@pytest.mark.parametrize("source", ["attachment", "generated", "stored_response"])
def test_all_xml_sources_share_the_same_certificate_inspector(history_inventory, certificates, source):
    b = history_inventory
    content = xml_bytes(certificate_root(certificates[0]))
    options = {}
    if source == "attachment":
        b.attach(content=content)
        candidate_list = "candidates"
    elif source == "generated":
        b.frappe.only_for = Mock()
        b.frappe.db.exists.side_effect = None
        b.frappe.db.exists.return_value = False
        (b.folder / f"final_xml_after_indent_{b.invoice.name}.xml").write_bytes(content)
        options["include_generated"] = True
        candidate_list = None
    else:
        b.invoice.custom_zatca_full_response = json.dumps(response_body(reportedInvoice=base64.b64encode(content).decode()))
        options["include_history"] = True
        candidate_list = "response_candidates"
    report = inspect(b, **options)
    assert report["state"] == "IDENTITY_CONSISTENT"
    candidates = report[candidate_list] if candidate_list else report["generated"]["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["certificate"]["issues"] == []
    assert report["certificate_observation"]["version_count"] == 1


@pytest.mark.parametrize("index,keys", [(1, 1), (2, 2)])
def test_multiple_certificate_versions_remain_distinct(local_inventory, certificates, index, keys):
    b = local_inventory
    b.attach(name="first.xml", content=xml_bytes(certificate_root(certificates[0])))
    b.attach(name="other.xml", content=xml_bytes(certificate_root(certificates[index])))
    report = inspect(b)
    assert report["state"] == "CONFLICT"
    assert report["issues"] == ["artifact_bytes_conflict", "artifact_certificate_versions_differ"]
    assert report["certificate_observation"]["version_count"] == 2
    assert report["certificate_observation"]["public_key_count"] == keys
    assert all(candidate["issues"] == [] for candidate in report["candidates"])


def test_certificate_text_changes_are_not_confused_with_rotation(local_inventory, certificates):
    b = local_inventory
    root = certificate_root(certificates[0])
    b.attach(name="plain.xml", content=xml_bytes(root))
    cert_node(root).text = "\n" + cert_node(root).text + "\n"
    b.attach(name="wrapped.xml", content=xml_bytes(root))
    report = inspect(b)
    assert report["state"] == "CONFLICT"
    assert report["issues"] == ["artifact_bytes_conflict"]
    assert report["certificate_observation"]["version_count"] == 1
    text_hashes = {c["certificate"]["element_text_sha256"] for c in report["candidates"]}
    assert len(text_hashes) == 2


def test_identical_attached_and_response_bytes_keep_both_sources(history_inventory, certificates):
    b = history_inventory
    content = xml_bytes(certificate_root(certificates[0]))
    b.attach(content=content)
    b.invoice.custom_zatca_full_response = json.dumps(response_body(reportedInvoice=base64.b64encode(content).decode()))
    report = inspect(b, include_history=True)
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert report["certificate_observation"]["version_count"] == 1
    assert len(report["candidates"]) == len(report["response_candidates"]) == 1
    assert report["history_complete"] is False


def test_all_three_sources_compose_with_existing_history_and_role_gates(history_inventory, certificates):
    b = history_inventory
    b.frappe.only_for = Mock()
    original_exists = b.frappe.db.exists.side_effect
    b.frappe.db.exists.side_effect = lambda doctype, name: (
        False if doctype == "POS Invoice" else original_exists(doctype, name)
    )
    content = xml_bytes(certificate_root(certificates[0]))
    b.attach(content=content)
    (b.folder / f"final_xml_after_indent_{b.invoice.name}.xml").write_bytes(content)
    b.invoice.custom_zatca_full_response = json.dumps(response_body(reportedInvoice=base64.b64encode(content).decode()))
    report = inspect(b, include_history=True, include_generated=True)
    assert report["scope"] == "saved_identity_attached_generated_xml_response_and_counter_and_embedded_certificate"
    assert report["state"] == "IDENTITY_CONSISTENT"
    assert report["certificate_observation"]["version_count"] == 1
    assert len(report["candidates"]) == len(report["response_candidates"]) == len(report["generated"]["candidates"]) == 1
    b.frappe.only_for.assert_called_once_with("System Manager", message=True)
    b.counter.check_permission.assert_called_once_with("read")
    assert report["generated_inventory_complete"] is False
    assert report["history_complete"] is False
    assert report["replay_authorized"] is False


def test_certificate_observation_does_not_hide_saved_identity_mismatch(local_inventory, certificates):
    b = local_inventory
    b.invoice.custom_uuid = OTHER_UUID
    b.attach(content=xml_bytes(certificate_root(certificates[0])))
    report = inspect(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["candidates"][0]["issues"] == ["saved_uuid_mismatch"]
    assert report["certificate_observation"]["version_count"] == 1


def test_malformed_xml_errors_are_not_duplicated(local_inventory):
    b = local_inventory
    b.attach(content=b"not XML")
    report = inspect(b)
    assert report["candidates"][0]["issues"] == ["xml_syntax"]
    assert report["candidates"][0]["certificate"]["issues"] == ["xml_syntax"]


def test_file_permission_is_checked_before_certificate_inspection(local_inventory, certificates, monkeypatch):
    b = local_inventory
    file, _ = b.attach(content=xml_bytes(certificate_root(certificates[0])))
    file.check_permission.side_effect = PermissionDenied()
    forbidden = Mock(side_effect=AssertionError("Permission bypass"))
    monkeypatch.setattr(inventory, "inspect_embedded_certificate", forbidden)
    report = inspect(b)
    assert report["state"] == "RECONCILIATION_REQUIRED"
    assert report["candidates"][0]["issues"] == ["attachment_permission"]
    assert report["certificate_observation"]["version_count"] == 0
    forbidden.assert_not_called()


def test_certificate_diagnostic_has_arabic_translation():
    path = Path(inventory.__file__).parents[1] / "translations" / "ar.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}
    message = "The embedded certificate inspection option must be true or false."
    assert any("\u0600" <= char <= "\u06ff" for char in rows[message])
