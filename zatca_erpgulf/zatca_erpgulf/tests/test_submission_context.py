"""Exercise real live adapters with entirely mocked database, files, and HTTP.

These tests characterize existing accepted-response handling. In particular,
they do not claim that a generic HTTP 409 proves acceptance at ZATCA.
"""

import base64
import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import (
    api_settings, credential_settings, pih, pos_sign, sign_invoice, submission_context,
)
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import PHASE_1_VALUE, PHASE_2_VALUE


class ValidationError(Exception):
    pass


class Document(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


def fail(message, *args, **kwargs):
    raise ValidationError(str(message))


@pytest.fixture
def boundary(monkeypatch):
    def document(doctype, name, **values):
        doc = Document(doctype=doctype, name=name, **values)
        doc.save = Mock(return_value=doc)
        doc.db_set = Mock(side_effect=lambda key, value, **kwargs: setattr(doc, key, value))
        return doc

    common = dict(
        tax_id="TEST-VAT", custom_select="Production", custom_send_invoice_to_zatca="Immediate",
        custom_send_einvoice_background=0, custom_pih="previous",
        custom_sandbox_url="https://example.invalid/developer-portal/",
        custom_simulation_url="https://example.invalid/simulation/",
        custom_production_url="https://example.invalid/core/",
        custom_basic_auth_from_csid="COMPLIANCE-MUST-NOT-BE-USED",
    )
    company = document("Company", "A", abbr="TC", custom_basic_auth_from_production="Basic COMPANY-PRODUCTION", **common)
    linked = document("Company", "B", abbr="TB", custom_basic_auth_from_production="LINKED-PRODUCTION", **common)
    device = document("ZATCA Multiple Setting", "DEVICE", custom_linked_doctype="A",
                      custom__use_company_certificate__keys="0", custom_final_auth_csid=" DEVICE-\nPRODUCTION ",
                      custom_basic_auth_from_csid="DEVICE-COMPLIANCE-MUST-NOT-BE-USED",
                      custom_send_pos_invoices_to_zatca_on_background=0, custom_pih="previous")
    sales = document("Sales Invoice", "SI", company="A", custom_zatca_pos_name="", custom_uuid="test-existing-uuid")
    pos = document("POS Invoice", "PI", company="A", custom_zatca_pos_name="", custom_uuid="test-existing-uuid")
    docs = {(doc.doctype, doc.name): doc for doc in (company, linked, device, sales, pos)}
    files = []

    def get_doc(doctype, name=None):
        if isinstance(doctype, dict):
            assert doctype["doctype"] == "File"
            values = {key: value for key, value in doctype.items() if key != "doctype"}
            file = document("File", f"FILE-{len(files)}", file_url="/private/files/test.xml", **values)
            files.append(file)
            return file
        if doctype == "Company" and isinstance(name, dict):
            assert name == {"abbr": "TC"}
            return company
        return docs[doctype, name]

    frappe = SimpleNamespace(
        get_doc=Mock(side_effect=get_doc), throw=fail, ValidationError=ValidationError,
        db=SimpleNamespace(get_value=Mock(return_value="TC"), commit=Mock(), set_value=Mock()),
        publish_realtime=Mock(), session=SimpleNamespace(user="TEST USER"), msgprint=Mock(), log_error=Mock(),
    )
    for module in (api_settings, credential_settings, submission_context, sign_invoice, pos_sign):
        monkeypatch.setattr(module, "frappe", frappe)
        monkeypatch.setattr(module, "_", lambda message: message)
    monkeypatch.setattr(pih, "frappe", frappe)
    monkeypatch.setattr(pih, "resolve_zatca_phase", lambda company: PHASE_2_VALUE)
    xml = base64.b64encode(b"<Invoice>Test only</Invoice>").decode()
    response = SimpleNamespace(status_code=200, text="TEST RESPONSE", json=lambda: {"clearedInvoice": xml})
    post = Mock(return_value=response)
    for module in (sign_invoice, pos_sign):
        monkeypatch.setattr(module.requests, "post", post)
        monkeypatch.setattr(module, "xml_base64_decode", Mock(return_value=xml))
        for name in ("success_log", "error_log", "log_zatca_event", "attach_qr_image", "set_zatca_full_response"):
            monkeypatch.setattr(module, name, Mock())
        monkeypatch.setattr(module, "format_zatca_response", lambda *args: "TEST RESPONSE")
        monkeypatch.setattr(module, "_extract_qr_payload_from_xml", lambda *args: "TEST QR")
    monkeypatch.setattr(sign_invoice, "_extract_qr_payload", lambda *args: "TEST QR")
    monkeypatch.setattr(sign_invoice, "get_b2c_submission_method", lambda company: company.custom_send_invoice_to_zatca)
    return Document(company=company, linked=linked, device=device, sales=sales, pos=pos,
                    frappe=frappe, files=files, post=post, response=response, xml=xml)


def select_owner(boundary, invoice, mode):
    if mode == "company":
        return boundary.company, "Basic COMPANY-PRODUCTION"
    invoice.custom_zatca_pos_name = "DEVICE"
    if mode == "device":
        return boundary.device, "Basic DEVICE-PRODUCTION"
    boundary.device.custom__use_company_certificate__keys = "1"
    boundary.device.custom_linked_doctype = "B"
    return boundary.linked, "Basic LINKED-PRODUCTION"


def run_adapter(boundary, module, operation):
    invoice = boundary.sales if module is sign_invoice else boundary.pos
    return getattr(module, operation + "_api")("test-uuid", "test-hash", "unused.xml", invoice.name, invoice)


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("mode", ["company", "device", "linked"])
@pytest.mark.parametrize("environment, path", [("Sandbox", "developer-portal"), ("Simulation", "simulation"), ("Production", "core")])
@pytest.mark.parametrize("status", [200, 202])
def test_live_adapters_share_route_auth_and_pih_owner(boundary, module, operation, mode, environment, path, status):
    b = boundary
    invoice = b.sales if module is sign_invoice else b.pos
    owner, header = select_owner(b, invoice, mode)
    b.company.custom_select = environment
    b.response.status_code = status
    run_adapter(b, module, operation)
    b.post.assert_called_once()
    sent = b.post.call_args.kwargs
    assert sent["url"] == f"https://example.invalid/{path}/invoices/{operation}/single"
    assert sent["headers"]["Authorization"] == header
    assert sent["headers"]["Clearance-Status"] == ("0" if operation == "reporting" else "1")
    assert sent["json"] == {"uuid": "test-uuid", "invoiceHash": "test-hash", "invoice": b.xml}
    assert invoice.custom_zatca_status == ("REPORTED" if operation == "reporting" else "CLEARED")
    assert owner.custom_pih == "test-hash"
    for other in (b.company, b.device, b.linked):
        if other is not owner:
            assert other.custom_pih == "previous"
            other.save.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("mode", ["company", "device", "linked"])
def test_missing_production_never_falls_back_or_moves_pih(boundary, module, operation, mode):
    invoice = boundary.sales if module is sign_invoice else boundary.pos
    owner, _ = select_owner(boundary, invoice, mode)
    field = "custom_final_auth_csid" if mode == "device" else "custom_basic_auth_from_production"
    setattr(owner, field, "")
    with pytest.raises(ValidationError, match="another purpose cannot be used"):
        run_adapter(boundary, module, operation)
    boundary.post.assert_not_called()
    assert boundary.files == []
    owner.save.assert_not_called()
    assert owner.custom_pih == "previous"


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("status", [400, 401, 500])
def test_http_rejection_does_not_update_any_pih_owner(boundary, module, operation, status):
    invoice = boundary.sales if module is sign_invoice else boundary.pos
    select_owner(boundary, invoice, "linked")
    boundary.response.status_code = status
    with pytest.raises(ValidationError):
        run_adapter(boundary, module, operation)
    for owner in (boundary.company, boundary.device, boundary.linked):
        assert owner.custom_pih == "previous"
        owner.save.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
def test_timeout_is_not_owner_success(boundary, module, operation):
    boundary.post.side_effect = requests.Timeout("test timeout")
    with pytest.raises(requests.Timeout):
        run_adapter(boundary, module, operation)
    boundary.company.save.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
@pytest.mark.parametrize("mode", ["company", "device", "linked"])
def test_legacy_409_handling_is_characterized_not_redefined(boundary, module, operation, mode):
    invoice = boundary.sales if module is sign_invoice else boundary.pos
    owner, _ = select_owner(boundary, invoice, mode)
    boundary.response.status_code = 409
    if module is pos_sign and operation == "clearance":
        # Existing POS clearance rejects 409. Other adapters update PIH and
        # status on 409. Consolidating response semantics is a separate gate.
        with pytest.raises(ValidationError):
            run_adapter(boundary, module, operation)
        assert owner.custom_pih == "previous"
    else:
        run_adapter(boundary, module, operation)
        assert owner.custom_pih == "test-hash"
        assert invoice.custom_zatca_status == ("REPORTED" if operation == "reporting" else "CLEARED")


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
def test_owner_is_not_reselected_after_response(boundary, module, operation):
    invoice = boundary.sales if module is sign_invoice else boundary.pos
    owner, _ = select_owner(boundary, invoice, "linked")

    def respond(**kwargs):
        invoice.custom_zatca_pos_name = ""
        boundary.device.custom__use_company_certificate__keys = 0
        boundary.device.custom_linked_doctype = "A"
        return boundary.response

    boundary.post.side_effect = respond
    run_adapter(boundary, module, operation)
    assert owner.custom_pih == "test-hash"
    assert boundary.device.custom_pih == boundary.company.custom_pih == "previous"


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
def test_batch_reporting_remains_deferred(boundary, module):
    boundary.company.custom_send_invoice_to_zatca = "Batches"
    run_adapter(boundary, module, "reporting")
    boundary.post.assert_not_called()
    boundary.company.save.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
def test_blank_environment_blocks_before_http_or_artifacts(boundary, module, operation):
    boundary.company.custom_select = ""
    with pytest.raises(ValidationError, match="valid ZATCA environment"):
        run_adapter(boundary, module, operation)
    boundary.post.assert_not_called()
    assert boundary.files == []


@pytest.mark.parametrize("endpoint", ["compliance", "production/csids", "compliance/invoices", "unknown"])
def test_live_context_cannot_select_onboarding_operations(boundary, endpoint):
    with pytest.raises(ValidationError, match="reporting or clearance only"):
        submission_context.get_submission_context("TC", boundary.sales, "SI", endpoint)
    boundary.frappe.get_doc.assert_not_called()


def test_context_rejects_mismatched_target(boundary):
    with pytest.raises(ValidationError, match="must match"):
        submission_context.get_submission_context("TC", boundary.sales, "ANOTHER", "invoices/reporting/single")


def test_context_rejects_wrong_adapter_doctype(boundary):
    with pytest.raises(ValidationError, match="must match"):
        submission_context.get_submission_context(
            "TC", boundary.pos, "PI", "invoices/reporting/single", expected_doctype="Sales Invoice",
        )


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("operation", ["reporting", "clearance"])
def test_cross_taxpayer_link_cannot_reach_http(boundary, module, operation):
    invoice = boundary.sales if module is sign_invoice else boundary.pos
    select_owner(boundary, invoice, "linked")
    boundary.linked.tax_id = "OTHER-TAXPAYER"
    with pytest.raises(ValidationError, match="matching nonempty"):
        run_adapter(boundary, module, operation)
    boundary.post.assert_not_called()
    assert boundary.files == []
    boundary.linked.save.assert_not_called()


def test_context_hides_token_and_preserves_phase1_pih_guard(boundary, monkeypatch):
    context = submission_context.get_submission_context("TC", boundary.sales, "SI", "invoices/reporting/single")
    assert "COMPANY-PRODUCTION" not in repr(context)
    monkeypatch.setattr(pih, "resolve_zatca_phase", lambda company: PHASE_1_VALUE)
    result = submission_context.record_submission_owner_success(context, "test-hash", boundary.sales, "message")
    assert result["updated"] is False
    boundary.company.save.assert_not_called()


def test_unchanged_pih_guard_remains_active(boundary):
    context = submission_context.get_submission_context("TC", boundary.sales, "SI", "invoices/reporting/single")
    result = submission_context.record_submission_owner_success(context, "previous", boundary.sales, "message")
    assert result["reason"] == "pih_already_current"
    boundary.company.save.assert_not_called()


@pytest.mark.parametrize("mode", ["company", "device", "linked"])
def test_notifications_follow_selected_owner(boundary, mode):
    owner, _ = select_owner(boundary, boundary.sales, mode)
    field = "custom_send_pos_invoices_to_zatca_on_background" if mode == "device" else "custom_send_einvoice_background"
    setattr(owner, field, 1)
    context = submission_context.get_submission_context("TC", boundary.sales, "SI", "invoices/reporting/single")
    submission_context.record_submission_owner_success(context, "test-hash", boundary.sales, "Test success")
    boundary.frappe.msgprint.assert_called_once_with("Test success")


def test_new_messages_have_arabic_translations():
    with (Path(__file__).resolve().parents[2] / "translations" / "ar.csv").open(encoding="utf-8", newline="") as handle:
        messages = {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}
    for message in ("This submission path supports reporting or clearance only.",
                    "The ZATCA submission target must match the source invoice."):
        assert any("\u0600" <= char <= "\u06ff" for char in messages[message])
