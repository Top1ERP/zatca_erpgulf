"""Legacy pre-signed XML adapters: real file reads, mocked HTTP and saved records.

Reuse the same Company/device/linked-Company fixture as the primary adapters.
No XML is signed again and no real database or remote service is accessed.
"""

import base64
import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import (
    icv, pos_submit_with_xml_qr, sales_invoice_with_xmlqr, sign_invoice_first,
    submit_poswithqr_notmultiple, submit_xml_qr_notmultiple,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import (
    Document, ValidationError, boundary, select_owner,
)


ADAPTERS = (
    (submit_xml_qr_notmultiple, "reporting_api_xml_sales_invoice_simplified", "submit_sales_invoice_simplifeid", "sales", False, 480),
    (submit_poswithqr_notmultiple, "reporting_api_xml_sales_invoice_simplified", "submit_pos_invoice_simplifeid", "pos", False, 300),
    (sales_invoice_with_xmlqr, "reporting_api_xml_sales_invoice", "submit_sales_invoice_withxmlqr", "sales", True, 300),
    (pos_submit_with_xml_qr, "reporting_api_machine", "submit_pos_withxmlqr", "pos", True, 300),
)
XML = '''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
 xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
 <cbc:UUID>test-uuid</cbc:UUID><cbc:Note>اختبار محلي فقط</cbc:Note>
 <ds:Reference Id="invoiceSignedData"><ds:DigestValue>test-hash</ds:DigestValue></ds:Reference>
</Invoice>
'''.encode("utf-8")


@pytest.fixture
def legacy_boundary(boundary, monkeypatch, tmp_path):
    b = boundary
    b.frappe.local = SimpleNamespace(site=str(tmp_path))
    b.path = tmp_path / "source.xml"
    b.path.write_bytes(XML)
    b.relative_path = "/source.xml"
    for invoice in (b.sales, b.pos):
        invoice.custom_ksa_einvoicing_xml = "/private/files/existing.xml"
        invoice.ksa_einv_qr = "/private/files/existing-qr.png"
    for module, *_ in ADAPTERS:
        monkeypatch.setattr(module, "frappe", b.frappe)
        monkeypatch.setattr(module, "_", lambda message: message)
        monkeypatch.setattr(module.requests, "post", b.post)
        for name in ("success_log", "error_log", "log_zatca_event"):
            monkeypatch.setattr(module, name, Mock())
        if hasattr(module, "format_zatca_response"):
            monkeypatch.setattr(module, "format_zatca_response", lambda *args: "TEST RESPONSE")
    # The POS machine module imports the primary reader. Restore a real legacy
    # reader because the primary fixture mocks that symbol before our test runs.
    monkeypatch.setattr(pos_submit_with_xml_qr, "xml_base64_decode", submit_xml_qr_notmultiple.xml_base64_decode)
    b.sign = Mock(side_effect=AssertionError("Existing XML must not be re-signed"))
    b.counter = Mock(side_effect=AssertionError("Existing XML must not allocate a new ICV"))
    monkeypatch.setattr(sign_invoice_first, "digital_signature", b.sign)
    monkeypatch.setattr(icv, "get_icv", b.counter)
    return b


def call_adapter(b, adapter, *, wrapper=False, source=None):
    module, method, wrapper_method, invoice_attr, *_ = adapter
    invoice = source if source is not None else getattr(b, invoice_attr)
    if wrapper:
        return getattr(module, wrapper_method)(invoice, b.relative_path, invoice.name)
    return getattr(module, method)("test-uuid", "test-hash", str(b.path), invoice.name, invoice)


def assert_artifacts_unchanged(b):
    assert b.path.read_bytes() == XML
    assert b.files == []
    for invoice in (b.sales, b.pos):
        assert invoice.custom_ksa_einvoicing_xml == "/private/files/existing.xml"
        assert invoice.ksa_einv_qr == "/private/files/existing-qr.png"
    b.sign.assert_not_called()
    b.counter.assert_not_called()


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("mode", ["company", "device", "linked"])
@pytest.mark.parametrize("environment, path", [("Sandbox", "developer-portal"), ("Simulation", "simulation"), ("Production", "core")])
@pytest.mark.parametrize("status", [200, 202, 409])
def test_legacy_route_auth_owner_and_existing_xml(legacy_boundary, adapter, mode, environment, path, status):
    b = legacy_boundary
    invoice = getattr(b, adapter[3])
    owner, header = select_owner(b, invoice, mode)
    b.company.custom_select = environment
    b.response.status_code = status
    if adapter[4] and mode == "company":
        with pytest.raises(ValidationError, match="saved ZATCA issuing unit"):
            call_adapter(b, adapter)
        b.post.assert_not_called()
        owner.save.assert_not_called()
    else:
        call_adapter(b, adapter)
        b.post.assert_called_once()
        sent = b.post.call_args.kwargs
        assert sent["url"] == f"https://example.invalid/{path}/invoices/reporting/single"
        assert sent["headers"]["Authorization"] == header
        assert sent["headers"]["Clearance-Status"] == "0"
        assert sent["timeout"] == adapter[5]
        assert base64.b64decode(sent["json"]["invoice"]) == XML
        assert sent["json"]["uuid"] == "test-uuid"
        assert sent["json"]["invoiceHash"] == "test-hash"
        assert invoice.custom_zatca_status == "REPORTED"
        assert owner.custom_pih == "test-hash"
        for other in (b.company, b.device, b.linked):
            if other is not owner:
                assert other.custom_pih == "previous"
                other.save.assert_not_called()
    assert_artifacts_unchanged(b)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("mode", ["device", "linked"])
def test_real_wrapper_extracts_existing_uuid_hash_and_preserves_files(legacy_boundary, adapter, mode):
    b = legacy_boundary
    owner, header = select_owner(b, getattr(b, adapter[3]), mode)
    call_adapter(b, adapter, wrapper=True)
    sent = b.post.call_args.kwargs
    assert sent["json"]["uuid"] == "test-uuid"
    assert sent["json"]["invoiceHash"] == "test-hash"
    assert base64.b64decode(sent["json"]["invoice"]) == XML
    assert sent["headers"]["Authorization"] == header
    assert owner.custom_pih == "test-hash"
    assert_artifacts_unchanged(b)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("failure", ["missing_auth", "invalid_environment", "other_taxpayer"])
def test_local_failure_blocks_http_without_changing_artifacts(legacy_boundary, adapter, failure):
    b = legacy_boundary
    owner, _ = select_owner(b, getattr(b, adapter[3]), "linked")
    if failure == "missing_auth":
        owner.custom_basic_auth_from_production = ""
    elif failure == "invalid_environment":
        b.company.custom_select = ""
    else:
        owner.tax_id = "OTHER-TAXPAYER"
    with pytest.raises(ValidationError):
        call_adapter(b, adapter)
    b.post.assert_not_called()
    assert owner.custom_pih == "previous"
    owner.save.assert_not_called()
    assert_artifacts_unchanged(b)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("status", [400, 401, 500])
def test_remote_rejection_does_not_update_pih_or_xml(legacy_boundary, adapter, status):
    b = legacy_boundary
    owner, _ = select_owner(b, getattr(b, adapter[3]), "linked")
    b.response.status_code = status
    with pytest.raises(ValidationError):
        call_adapter(b, adapter)
    assert owner.custom_pih == "previous"
    owner.save.assert_not_called()
    assert_artifacts_unchanged(b)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_timeout_is_not_success(legacy_boundary, adapter):
    b = legacy_boundary
    owner, _ = select_owner(b, getattr(b, adapter[3]), "device")
    b.post.side_effect = requests.Timeout("Test timeout")
    with pytest.raises(requests.Timeout):
        call_adapter(b, adapter)
    owner.save.assert_not_called()
    assert_artifacts_unchanged(b)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_owner_is_pinned_when_saved_link_changes_during_http(legacy_boundary, adapter):
    b = legacy_boundary
    invoice = getattr(b, adapter[3])
    owner, _ = select_owner(b, invoice, "linked")

    def respond(**kwargs):
        invoice.custom_zatca_pos_name = ""
        b.device.custom__use_company_certificate__keys = 0
        return b.response

    b.post.side_effect = respond
    call_adapter(b, adapter)
    assert owner.custom_pih == "test-hash"
    assert b.device.custom_pih == b.company.custom_pih == "previous"


@pytest.mark.parametrize("adapter", [ADAPTERS[2], ADAPTERS[3]])
def test_machine_requirement_uses_saved_link_not_caller_field(legacy_boundary, adapter):
    b = legacy_boundary
    saved = getattr(b, adapter[3])
    forged = Document(doctype=saved.doctype, name=saved.name, company="A", custom_zatca_pos_name="DEVICE")
    with pytest.raises(ValidationError, match="saved ZATCA issuing unit"):
        call_adapter(b, adapter, source=forged)
    b.post.assert_not_called()


def test_machine_requirement_message_has_arabic_translation():
    with (Path(__file__).resolve().parents[2] / "translations" / "ar.csv").open(encoding="utf-8", newline="") as handle:
        messages = {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}
    translated = messages["A saved ZATCA issuing unit is required for this XML submission path."]
    assert any("\u0600" <= char <= "\u06ff" for char in translated)
