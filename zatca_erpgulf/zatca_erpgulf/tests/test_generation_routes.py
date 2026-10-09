"""Generation/worker request ownership and early Compliance diversion boundaries.

Use mocked saved records/HTTP for request adapters, and real temporary sample
files for the bridge to dedicated Compliance. No production state is accessed.
"""

import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import (
    compliance_dispatch, pos_schedule_background, pos_sign, pos_submit__without_xml,
    sales_invoice_withoutxml, sign_invoice, zatca_background_sched,
)
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import (
    Document, ValidationError, boundary, select_owner,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import (
    ValidationError as IsolatedValidationError, isolated, stub_pipeline,
)


ADAPTERS = (
    (sales_invoice_withoutxml, "reporting_api_sales_withoutxml", "sales", True, False),
    (zatca_background_sched, "reporting_api_sales_withoutxml", "sales", False, True),
    (pos_submit__without_xml, "reporting_api_pos_without_xml", "pos", True, False),
    (pos_schedule_background, "reporting_api_pos_without_xml", "pos", False, True),
)
GENERATORS = (
    (sign_invoice, "zatca_call", "sales", "Sales Invoice"),
    (pos_sign, "zatca_call", "pos", "POS Invoice"),
    (sales_invoice_withoutxml, "zatca_call_withoutxml", "sales", "Sales Invoice"),
    (zatca_background_sched, "zatca_call_scheduler_background", "sales", "Sales Invoice"),
    (pos_submit__without_xml, "zatca_call_pos_without_xml", "pos", "POS Invoice"),
    (pos_schedule_background, "zatca_call_pos_without_xml_background", "pos", "POS Invoice"),
)
PASS = {"validationResults": {"status": "PASS", "errorMessages": []}}


@pytest.fixture
def generation_boundary(boundary, monkeypatch):
    b = boundary
    b.frappe.db.exists = Mock(return_value=True)
    for module, *_ in ADAPTERS:
        monkeypatch.setattr(module, "frappe", b.frappe)
        monkeypatch.setattr(module, "_", lambda message: message)
        monkeypatch.setattr(module.requests, "post", b.post)
        monkeypatch.setattr(module, "xml_base64_decode", Mock(return_value=b.xml))
        for name in ("success_log", "error_log", "log_zatca_event"):
            monkeypatch.setattr(module, name, Mock())
        if hasattr(module, "format_zatca_response"):
            monkeypatch.setattr(module, "format_zatca_response", lambda *args: "TEST RESPONSE")
    monkeypatch.setattr(compliance_dispatch, "frappe", b.frappe)
    monkeypatch.setattr(compliance_dispatch, "_", lambda message: message)
    return b


def run_reporting(b, adapter):
    module, fn, attr, *_ = adapter
    invoice = getattr(b, attr)
    return getattr(module, fn)("test-uuid", "test-hash", "unused.xml", invoice.name, invoice)


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("mode", ["company", "device", "linked"])
@pytest.mark.parametrize("environment, path", [("Sandbox", "developer-portal"), ("Simulation", "simulation"), ("Production", "core")])
@pytest.mark.parametrize("status", [200, 202, 409])
def test_generation_reporting_uses_common_owner(generation_boundary, adapter, mode, environment, path, status):
    b = generation_boundary
    invoice = getattr(b, adapter[2])
    owner, header = select_owner(b, invoice, mode)
    b.company.custom_select = environment
    b.response.status_code = status
    if adapter[3] and mode == "company":
        with pytest.raises(ValidationError, match="saved ZATCA issuing unit"):
            run_reporting(b, adapter)
        b.post.assert_not_called()
        assert b.files == []
    else:
        run_reporting(b, adapter)
        sent = b.post.call_args.kwargs
        assert sent["url"] == f"https://example.invalid/{path}/invoices/reporting/single"
        assert sent["headers"]["Authorization"] == header
        assert sent["json"] == {"uuid": "test-uuid", "invoiceHash": "test-hash", "invoice": b.xml}
        assert invoice.custom_zatca_status == "REPORTED"
        assert owner.custom_pih == "test-hash"
        assert len(b.files) == 1
        assert b.files[0].is_private == 1
        for other in (b.company, b.device, b.linked):
            if other is not owner:
                assert other.custom_pih == "previous"
                other.save.assert_not_called()


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("status", [400, 401, 500])
def test_rejection_cannot_move_pih(generation_boundary, adapter, status):
    b = generation_boundary
    owner, _ = select_owner(b, getattr(b, adapter[2]), "linked")
    b.response.status_code = status
    with pytest.raises(ValidationError):
        run_reporting(b, adapter)
    owner.save.assert_not_called()
    assert owner.custom_pih == "previous"


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_missing_auth_blocks_before_file_attachment(generation_boundary, adapter):
    b = generation_boundary
    owner, _ = select_owner(b, getattr(b, adapter[2]), "device")
    owner.custom_final_auth_csid = ""
    with pytest.raises(ValidationError, match="another purpose cannot be used"):
        run_reporting(b, adapter)
    b.post.assert_not_called()
    assert b.files == []


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("method", ["Immediate", "Batches", "Background"])
def test_existing_foreground_background_deferral_is_characterized(generation_boundary, adapter, method):
    b = generation_boundary
    owner, _ = select_owner(b, getattr(b, adapter[2]), "device")
    b.company.custom_send_invoice_to_zatca = method
    run_reporting(b, adapter)
    deferred = method == "Batches" or (adapter[4] and method == "Background")
    assert b.post.call_count == (0 if deferred else 1)
    assert owner.custom_pih == ("previous" if deferred else "test-hash")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_timeout_does_not_update_owner(generation_boundary, adapter):
    b = generation_boundary
    owner, _ = select_owner(b, getattr(b, adapter[2]), "device")
    b.post.side_effect = requests.Timeout("Test timeout")
    with pytest.raises(requests.Timeout):
        run_reporting(b, adapter)
    owner.save.assert_not_called()


@pytest.mark.parametrize("generator", GENERATORS)
@pytest.mark.parametrize("label, code", list(COMPLIANCE_TYPES.items()))
def test_legacy_sample_codes_divert_before_live_work(generation_boundary, monkeypatch, generator, label, code):
    b = generation_boundary
    module, fn, attr, doctype = generator
    source = getattr(b, attr)
    b.company.custom_validation_type = "Standard Invoice"
    dedicated = pos_sign if doctype == "POS Invoice" else sign_invoice
    check = Mock(return_value=PASS)
    monkeypatch.setattr(dedicated, "zatca_call_compliance", check)
    live = Mock(side_effect=AssertionError("Compliance reached live generation"))
    monkeypatch.setattr(module, "xml_tags", live)
    result = inspect.unwrap(getattr(module, fn))(source.name, compliance_type=code, company_abbr="TC",
                               source_doc=Document(doctype="Company", name="UNTRUSTED"))
    assert result == PASS
    assert check.call_args.kwargs["validation_type"] == label
    selected = check.call_args.kwargs["source_doc"]
    if doctype == "Sales Invoice":
        assert json.loads(selected) == {"doctype": source.doctype, "name": source.name}
    else:
        assert selected is source
    live.assert_not_called()
    source.save.assert_not_called()
    source.db_set.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    b.post.assert_not_called()


@pytest.mark.parametrize("generator", GENERATORS)
@pytest.mark.parametrize("code", [None, "", "7", True, "invalid"])
def test_malformed_code_cannot_generate_or_send(generation_boundary, monkeypatch, generator, code):
    module, fn, attr, _ = generator
    live = Mock(side_effect=AssertionError("Invalid selector reached live generation"))
    monkeypatch.setattr(module, "xml_tags", live)
    with pytest.raises(ValidationError, match="Select a valid"):
        inspect.unwrap(getattr(module, fn))(getattr(generation_boundary, attr).name, compliance_type=code)
    live.assert_not_called()
    generation_boundary.post.assert_not_called()


@pytest.mark.parametrize("generator", GENERATORS)
def test_dispatch_failure_is_not_swallowed(generation_boundary, monkeypatch, generator):
    module, fn, attr, doctype = generator
    dedicated = pos_sign if doctype == "POS Invoice" else sign_invoice
    monkeypatch.setattr(dedicated, "zatca_call_compliance", Mock(side_effect=ValidationError("remote rejected")))
    with pytest.raises(ValidationError, match="remote rejected"):
        inspect.unwrap(getattr(module, fn))(getattr(generation_boundary, attr).name, compliance_type=1)


@pytest.mark.parametrize("result", [None, {}, ("error", "unknown"), {"validationResults": {"status": "ERROR"}}])
def test_dispatch_requires_confirmed_result(generation_boundary, monkeypatch, result):
    monkeypatch.setattr(sign_invoice, "zatca_call_compliance", Mock(return_value=result))
    with pytest.raises(ValidationError, match="did not confirm"):
        sales_invoice_withoutxml.zatca_call_withoutxml("SI", compliance_type="1")


def test_dispatch_rejects_wrong_company(generation_boundary, monkeypatch):
    check = Mock()
    monkeypatch.setattr(sign_invoice, "zatca_call_compliance", check)
    with pytest.raises(ValidationError, match="does not belong"):
        sales_invoice_withoutxml.zatca_call_withoutxml("SI", compliance_type="1", company_abbr="OTHER")
    check.assert_not_called()


@pytest.mark.parametrize("generator", GENERATORS)
@pytest.mark.parametrize("rejected", [False, True])
def test_real_dedicated_bridge_uses_temporary_samples(isolated, monkeypatch, generator, rejected):
    invoice, _, _, frappe, files = isolated
    module, fn, _, doctype = generator
    invoice.doctype = doctype
    monkeypatch.setattr(module, "frappe", frappe)
    monkeypatch.setattr(compliance_dispatch, "frappe", frappe)
    monkeypatch.setattr(compliance_dispatch, "_", lambda message: message)
    dedicated = pos_sign if doctype == "POS Invoice" else sign_invoice
    monkeypatch.setattr(dedicated, "zatca_call_compliance", inspect.unwrap(dedicated.zatca_call_compliance))
    stub_pipeline(monkeypatch, dedicated, invoice)
    paths = []

    def submit(uuid, invoice_hash, path, *args):
        paths.append(Path(path))
        assert paths[-1].exists()
        if rejected:
            raise IsolatedValidationError("remote rejected")
        return PASS

    monkeypatch.setattr(dedicated, "compliance_api_call", submit)
    if rejected:
        with pytest.raises(IsolatedValidationError, match="remote rejected"):
            inspect.unwrap(getattr(module, fn))(invoice.name, compliance_type="1")
    else:
        assert inspect.unwrap(getattr(module, fn))(invoice.name, compliance_type="1") == PASS
    assert dedicated.salesinvoice_data.call_args.kwargs["purpose"] == "compliance"
    assert len(paths) == 1 and not paths[0].exists()
    assert invoice.custom_uuid == "b05809d9-7851-4767-b7e9-47af44c80cb9"
    assert invoice.custom_zatca_icv == 77
    assert invoice.custom_zatca_issuing_unit == "live-unit"
    invoice.db_set.assert_not_called()
    invoice.save.assert_not_called()
    frappe.db.commit.assert_not_called()
    assert files == []


@pytest.mark.parametrize("generator", GENERATORS)
@pytest.mark.parametrize("zero", ["0", 0])
def test_regular_generation_signs_with_its_invoice_source(isolated, monkeypatch, generator, zero):
    invoice, company, _, frappe, _ = isolated
    module, fn, _, doctype = generator
    invoice.doctype = doctype
    monkeypatch.setattr(module, "frappe", frappe)
    monkeypatch.setattr(compliance_dispatch, "frappe", frappe)
    metadata = stub_pipeline(monkeypatch, module, invoice)
    monkeypatch.setattr(module, "structuring_signedxml", Mock(return_value="unused.xml"))
    monkeypatch.setattr(module, "attach_qr_image", Mock())
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    if hasattr(module, "is_advance_payment_invoice"):
        monkeypatch.setattr(module, "is_advance_payment_invoice", lambda *args: False)
    if hasattr(module, "supports_advance_deduction_schema"):
        monkeypatch.setattr(module, "supports_advance_deduction_schema", lambda *args: False)
    method = "reporting_api" if module in (sign_invoice, pos_sign) else "reporting_api_pos_without_xml" if doctype == "POS Invoice" else "reporting_api_sales_withoutxml"
    report = Mock()
    monkeypatch.setattr(module, method, report)
    inspect.unwrap(getattr(module, fn))(invoice.name, compliance_type=zero, source_doc=company)
    report.assert_called_once()
    assert module.digital_signature.call_args.args[2] is invoice
    assert "purpose" not in metadata.call_args.kwargs
    frappe.log_error.assert_not_called()
