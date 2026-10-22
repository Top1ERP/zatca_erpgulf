"""Protect live invoice identity/artifacts from diagnostic and compliance paths.

All Frappe, signing, and HTTP boundaries are mocked. File assertions use only
pytest temporary directories or the temporary sample file being submitted.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    createxml, debug_xml, icv, pos_debug_xml, pos_sign, posxml, sign_invoice,
    qr_timestamp,
)
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES, resolve_compliance_type
from zatca_erpgulf.zatca_erpgulf.nonproduction import preview_invoice_uuid, temporary_compliance_xml
from zatca_erpgulf.zatca_erpgulf.operation_messages import (
    DEBUG_CREATED, DEBUG_FAILED, DEBUG_SKIPPED, DEBUG_POS_DISABLED,
    DEBUG_LOCAL_ONLY, DEBUG_EXISTING,
)


class Document(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class ValidationError(Exception):
    pass


def fail(message, *args, **kwargs):
    raise ValidationError(str(message))


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    invoice = Document(
        doctype="Sales Invoice", name="TEST-INVOICE", company="TEST COMPANY",
        customer="TEST CUSTOMER", currency="SAR", is_return=0, is_debit_note=0,
        custom_uuid="b05809d9-7851-4767-b7e9-47af44c80cb9", custom_zatca_icv=77,
        custom_zatca_issuing_unit="live-unit", custom_zatca_status="REPORTED",
        custom_zatca_full_response="live-response", custom_zatca_pos_name=None,
        custom_zatca_nominal_invoice=0, custom_xml=None, items=[],
        posting_date="2026-10-09", posting_time="09:05:42Z",
        db_set=Mock(), save=Mock(),
    )
    company = Document(
        doctype="Company", name=invoice.company, abbr="TC", tax_id="SELLER",
        custom_validation_type="Standard Invoice", custom_send_invoice_to_zatca="Live",
        db_set=Mock(),
    )
    customer = Document(tax_id="BUYER")
    attachment = Document(save=Mock())
    files = []

    def get_doc(doctype, name=None):
        if isinstance(doctype, dict):
            if doctype["doctype"] == "File":
                files.append(doctype)
                return attachment
            return company
        return {"Sales Invoice": invoice, "POS Invoice": invoice,
                "Company": company, "Customer": customer}[doctype]

    frappe = SimpleNamespace(
        flags={"mute_messages": False},
        get_doc=Mock(side_effect=get_doc),
        db=SimpleNamespace(
            exists=Mock(return_value=True), get_value=Mock(return_value=company.name),
            set_value=Mock(), commit=Mock(),
            sql=Mock(return_value=[SimpleNamespace(last_issued_icv=2)]),
        ),
        get_meta=Mock(return_value=SimpleNamespace(has_field=lambda *args, **kwargs: True)),
        get_installed_apps=Mock(return_value=[]), get_all=Mock(return_value=[]),
        delete_doc=Mock(), throw=fail, ValidationError=ValidationError,
        DoesNotExistError=ValidationError, msgprint=Mock(), log_error=Mock(),
        get_traceback=Mock(return_value="Mock traceback"), local=SimpleNamespace(site=str(tmp_path)),
    )
    for module in (createxml, posxml, debug_xml, pos_debug_xml, icv, sign_invoice, pos_sign):
        monkeypatch.setattr(module, "frappe", frappe)
        monkeypatch.setattr(module, "_", lambda message: message)
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", lambda: "UTC")
    monkeypatch.setattr(qr_timestamp, "_", lambda message: message)
    monkeypatch.setattr(icv, "_issuing_unit", lambda *args: "test-unit")
    monkeypatch.setattr(icv, "_get_or_create_counter", Mock(return_value="test-counter"))
    monkeypatch.setattr(icv, "now_datetime", lambda: "2026-10-09 09:05:42")
    return invoice, company, customer, frappe, files


@pytest.mark.parametrize("module", [createxml, posxml])
@pytest.mark.parametrize("purpose", ["debug", "compliance"])
@pytest.mark.parametrize("existing_uuid", [None, "not submitted", "b05809d9-7851-4767-b7e9-47af44c80cb9"])
def test_preview_metadata_never_persists_uuid(isolated, module, purpose, existing_uuid):
    invoice, _, _, frappe, _ = isolated
    invoice.custom_uuid = existing_uuid
    _, value, returned = module.salesinvoice_data(
        ET.Element("Invoice"), invoice.name, purpose=purpose,
    )
    UUID(value)
    assert returned is invoice
    assert invoice.custom_uuid == existing_uuid
    invoice.db_set.assert_not_called()
    frappe.db.commit.assert_not_called()
    if purpose == "compliance":
        assert value != existing_uuid
    elif existing_uuid and existing_uuid != "not submitted":
        assert value == existing_uuid


def test_live_sales_uuid_reuse_remains_unchanged(isolated):
    invoice, _, _, _, _ = isolated
    _, value, _ = createxml.salesinvoice_data(ET.Element("Invoice"), invoice.name)
    assert value == invoice.custom_uuid
    invoice.db_set.assert_not_called()


def test_live_sales_missing_uuid_is_still_persisted(isolated):
    invoice, _, _, _, _ = isolated
    invoice.custom_uuid = None
    _, value, _ = createxml.salesinvoice_data(ET.Element("Invoice"), invoice.name)
    UUID(value)
    invoice.db_set.assert_called_once_with("custom_uuid", value, commit=True, update_modified=False)
    assert invoice.custom_uuid == value


def test_unknown_preview_purpose_cannot_allocate_live_identity(isolated):
    invoice, _, _, _, _ = isolated
    with pytest.raises(ValidationError, match="Unsupported non-production"):
        createxml.salesinvoice_data(ET.Element("Invoice"), invoice.name, purpose="typo")
    invoice.db_set.assert_not_called()


def test_compliance_counter_does_not_write_invoice_identity(isolated):
    invoice, _, _, frappe, _ = isolated
    assert icv.get_icv(invoice, "Compliance") == "3"
    invoice.db_set.assert_not_called()
    assert invoice.custom_zatca_icv == 77
    assert invoice.custom_zatca_issuing_unit == "live-unit"
    assert all(call.args[0] == "ZATCA ICV Counter" for call in frappe.db.set_value.call_args_list)
    frappe.db.commit.assert_not_called()
    icv._get_or_create_counter.assert_called_once_with(invoice.company, "test-unit", "Compliance")


def test_live_counter_allocation_and_reuse_remain_unchanged(isolated):
    invoice, _, _, frappe, _ = isolated
    assert icv.get_icv(invoice) == "77"
    frappe.db.sql.assert_not_called()
    invoice.custom_zatca_icv = None
    assert icv.get_icv(invoice) == "3"
    assert invoice.db_set.call_args_list[0].args == ("custom_zatca_icv", 3)
    assert invoice.db_set.call_args_list[1].args == ("custom_zatca_issuing_unit", "test-unit")
    icv._get_or_create_counter.assert_called_once_with(invoice.company, "test-unit", "Production")


def test_debug_counter_reuses_existing_value_without_writes(isolated):
    invoice, _, _, frappe, _ = isolated
    assert icv.get_icv(invoice, "Debug", debug=True) == "77"
    invoice.db_set.assert_not_called()
    frappe.db.set_value.assert_not_called()
    frappe.db.sql.assert_not_called()


def test_debug_without_icv_only_reads_the_next_value(isolated):
    invoice, _, _, frappe, _ = isolated
    invoice.custom_zatca_icv = None
    frappe.db.get_value.return_value = 10
    assert icv.get_icv(invoice, "Debug", debug=True) == "11"
    invoice.db_set.assert_not_called()
    frappe.db.set_value.assert_not_called()
    frappe.db.sql.assert_not_called()
    icv._get_or_create_counter.assert_not_called()


def stub_pipeline(monkeypatch, module, invoice):
    """Leave routing/file lifetime real; replace cryptography and tax work."""
    metadata = Mock(return_value=(ET.Element("Invoice"), "test-uuid", invoice))
    monkeypatch.setattr(module, "salesinvoice_data", metadata)
    monkeypatch.setattr(module, "xml_tags", lambda: ET.Element("Invoice"))
    for name in (
        "invoice_typecode_compliance", "invoice_typecode_simplified", "invoice_typecode_standard",
        "doc_reference", "doc_reference_compliance", "additional_reference", "company_data",
        "customer_data", "delivery_and_payment_means", "delivery_and_paymentmeans",
        "delivery_and_payment_means_for_compliance", "delivery_and_paymentmeans_for_compliance",
        "add_document_level_discount_with_tax", "tax_data", "item_data",
    ):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, Mock(side_effect=lambda root, *args, **kwargs: root))
    for name in ("xml_structuring", "removetags", "canonicalize_xml", "digital_signature",
                 "certificate_hash", "generate_signed_properties_hash", "populate_the_ubl_extensions_output",
                 "update_qr_toxml"):
        monkeypatch.setattr(module, name, Mock(return_value="<Invoice>sample</Invoice>"))
    monkeypatch.setattr(module, "getinvoicehash", lambda *args: (b"hash", "encoded-hash"))
    monkeypatch.setattr(module, "extract_certificate_details", lambda *args: ("issuer", "serial"))
    monkeypatch.setattr(module, "signxml_modify", lambda *args: ("<Invoice/>", {}, "timestamp"))
    monkeypatch.setattr(module, "generate_tlv_xml", lambda *args: {})
    monkeypatch.setattr(
        module, "structuring_signedxml",
        Mock(side_effect=AssertionError("Live file writer called")), raising=False,
    )
    return metadata


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
def test_debug_attaches_from_memory_without_touching_live_file(isolated, monkeypatch, tmp_path, module):
    invoice, _, _, frappe, files = isolated
    if module is pos_debug_xml:
        invoice.doctype = "POS Invoice"
    metadata = stub_pipeline(monkeypatch, module, invoice)
    monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
    monkeypatch.setattr(module, "resolve_zatca_phase", lambda *args: "Phase-1")
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    if hasattr(module, "is_advance_payment_invoice"):
        monkeypatch.setattr(module, "is_advance_payment_invoice", lambda *args: False)
    api = Mock(side_effect=AssertionError("Debug attempted HTTP"))
    monkeypatch.setattr(module, "compliance_api_call", api)
    live_file = tmp_path / "private" / "files" / f"final_xml_after_indent_{invoice.name}.xml"
    live_file.parent.mkdir(parents=True)
    live_file.write_text("LIVE-ARTIFACT", encoding="utf-8")
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result["status"] == "success", result
    assert live_file.read_text(encoding="utf-8") == "LIVE-ARTIFACT"
    assert len(files) == 1
    assert files[0]["file_name"].startswith("DEBUG_INVOICE_")
    assert "sample" in files[0]["content"]
    assert files[0]["is_private"] == 1
    assert metadata.call_args.kwargs["purpose"] == "debug"
    assert result["message"] == DEBUG_CREATED
    assert result["file_name"] == f"DEBUG_INVOICE_{invoice.name}.xml"
    assert result["notices"] == []
    assert frappe.flags == {"mute_messages": False}
    frappe.msgprint.assert_not_called()
    invoice.save.assert_not_called()
    invoice.db_set.assert_not_called()
    frappe.db.commit.assert_not_called()
    api.assert_not_called()


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
def test_intra_company_debug_does_not_change_invoice_status(isolated, monkeypatch, module):
    invoice, company, customer, frappe, _ = isolated
    customer.tax_id = company.tax_id
    monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result == {"status": "skipped", "message": DEBUG_SKIPPED, "notices": []}
    frappe.msgprint.assert_not_called()
    invoice.save.assert_not_called()
    frappe.db.commit.assert_not_called()
    assert invoice.custom_zatca_status == "REPORTED"
    assert invoice.custom_zatca_full_response == "live-response"


def prepare_debug_messages(isolated, monkeypatch, module):
    invoice, _, _, app, _ = isolated
    if module is pos_debug_xml:
        invoice.doctype = "POS Invoice"
    stub_pipeline(monkeypatch, module, invoice)
    monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
    monkeypatch.setattr(module, "resolve_zatca_phase", lambda *args: "Phase-1")
    monkeypatch.setattr(module, "get_alias_value", lambda *args: 1)
    if hasattr(module, "is_advance_payment_invoice"):
        monkeypatch.setattr(module, "is_advance_payment_invoice", lambda *args: False)
    monkeypatch.setattr(module, "compliance_api_call", Mock(side_effect=AssertionError("Debug attempted HTTP")))
    app.local.lang = "ar"
    monkeypatch.setattr(module, "_", lambda message: "ترجمة العرض فقط")


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
@pytest.mark.parametrize("flags", [{}, {"mute_messages": False}, {"mute_messages": True}])
def test_debug_failure_keeps_english_summary_original_details_and_parent_state(isolated, monkeypatch, module, flags):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    app.flags = dict(flags)
    app.message_log = ["Parent-owned message"]
    original = 'Synthetic original هيئة {"code":"mock-failure","request_id":"unchanged"}'

    def fail_locally(*args):
        assert app.flags["mute_messages"] is True
        raise ValidationError(original)

    monkeypatch.setattr(module, "removetags", fail_locally)
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result == {"status": "error", "message": DEBUG_FAILED, "technical_details": original, "notices": []}
    assert app.flags == flags and app.local.lang == "ar"
    assert app.message_log == ["Parent-owned message"]
    app.msgprint.assert_not_called()
    assert app.log_error.call_count == 1
    traceback_text, title = app.log_error.call_args.args
    assert original in traceback_text
    assert title == f"Debug XML Error for invoice {invoice.name}"
    assert not files
    invoice.db_set.assert_not_called()
    invoice.save.assert_not_called()
    app.db.commit.assert_not_called()
    module.compliance_api_call.assert_not_called()


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
def test_debug_disabled_setting_keeps_each_existing_generation_policy(isolated, monkeypatch, module):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: False)
    if module is pos_debug_xml:
        monkeypatch.setattr(module, "xml_tags", Mock(side_effect=AssertionError("Disabled POS must not generate XML")))
    result = inspect.unwrap(module.debug_call)(invoice.name)
    if module is pos_debug_xml:
        assert result == {"status": "skipped", "message": DEBUG_POS_DISABLED, "notices": []}
        assert not files
        module.xml_tags.assert_not_called()
    else:
        assert result["status"] == "success" and result["message"] == DEBUG_CREATED
        assert result["notices"] == [DEBUG_LOCAL_ONLY]
        assert len(files) == 1
    app.msgprint.assert_not_called()
    app.db.commit.assert_not_called()
    invoice.save.assert_not_called()
    module.compliance_api_call.assert_not_called()


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
def test_debug_existing_artifact_notice_does_not_skip_or_replace_generation_policy(isolated, monkeypatch, module):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    monkeypatch.setattr(module, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(module, "is_qr_and_xml_attached", lambda *args: True)
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result["status"] == "success"
    assert result["notices"] == [DEBUG_EXISTING]
    assert len(files) == 1 and files[0]["file_name"].startswith("DEBUG_INVOICE_")
    app.msgprint.assert_not_called()
    module.compliance_api_call.assert_not_called()


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_debug_cancellation_restores_flags_without_logging_or_conversion(isolated, monkeypatch, module, stop):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    interrupt = stop("synthetic cancellation")
    monkeypatch.setattr(module, "removetags", Mock(side_effect=interrupt))
    with pytest.raises(stop) as raised:
        inspect.unwrap(module.debug_call)(invoice.name)
    assert raised.value is interrupt
    assert app.flags == {"mute_messages": False}
    assert not files
    app.log_error.assert_not_called()
    module.compliance_api_call.assert_not_called()


def test_pos_debug_background_existing_selector_error_is_visible_not_a_success(isolated, monkeypatch):
    """Known generation defect remains an adoption gate, NOT an accepted result."""
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    company.custom_send_invoice_to_zatca = "Background"
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    monkeypatch.delattr(pos_debug_xml, "bypass_background_check", raising=False)
    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name)
    assert result["status"] == "error" and result["message"] == DEBUG_FAILED
    assert "bypass_background_check" in result["technical_details"]
    assert not files
    assert app.flags == {"mute_messages": False}
    invoice.save.assert_not_called()
    app.db.commit.assert_not_called()
    pos_debug_xml.compliance_api_call.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
@pytest.mark.parametrize("rejected", [False, True])
def test_dedicated_compliance_uses_disposable_file(isolated, monkeypatch, module, rejected):
    invoice, _, _, _, _ = isolated
    if module is pos_sign:
        invoice.doctype = "POS Invoice"
    metadata = stub_pipeline(monkeypatch, module, invoice)
    paths = []

    def submit(uuid, invoice_hash, path, *args):
        paths.append(Path(path))
        assert "sample" in paths[-1].read_text(encoding="utf-8")
        assert invoice.name not in paths[-1].name
        if rejected:
            fail("Mock remote rejection")
        return {"validationResults": {"status": "PASS", "errorMessages": []}}

    monkeypatch.setattr(module, "compliance_api_call", submit)
    call = inspect.unwrap(module.zatca_call_compliance)
    if rejected:
        with pytest.raises(ValidationError, match="Mock remote rejection"):
            call(invoice.name, company_abbr="TC")
    else:
        result = call(invoice.name, company_abbr="TC")
        assert result["validationResults"]["status"] == "PASS"
    assert len(paths) == 1
    assert not paths[0].exists()
    assert metadata.call_args.kwargs["purpose"] == "compliance"
    assert module.digital_signature.call_args.args[2] is invoice


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
def test_explicit_check_type_does_not_depend_on_company_selection(isolated, monkeypatch, module):
    invoice, company, _, _, _ = isolated
    stub_pipeline(monkeypatch, module, invoice)
    monkeypatch.setattr(module, "compliance_api_call", Mock(return_value={}))
    for label, code in COMPLIANCE_TYPES.items():
        inspect.unwrap(module.zatca_call_compliance)(
            invoice.name, company_abbr="TC", validation_type=label,
        )
        assert module.invoice_typecode_compliance.call_args.args[1] == code
        assert company.custom_validation_type == "Standard Invoice"
    company.db_set.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
def test_legacy_single_check_keeps_company_selection_precedence(isolated, monkeypatch, module):
    invoice, _, _, _, _ = isolated
    stub_pipeline(monkeypatch, module, invoice)
    monkeypatch.setattr(module, "compliance_api_call", Mock(return_value={}))
    inspect.unwrap(module.zatca_call_compliance)(
        invoice.name, company_abbr="TC", compliance_type="1",
    )
    assert module.invoice_typecode_compliance.call_args.args[1] == "2"


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
def test_wrong_company_is_rejected_before_signing_or_sending(isolated, monkeypatch, module):
    invoice, _, _, _, _ = isolated
    invoice.company = "DIFFERENT COMPANY"
    stub_pipeline(monkeypatch, module, invoice)
    api = Mock(side_effect=AssertionError("Must not submit across companies"))
    monkeypatch.setattr(module, "compliance_api_call", api)
    with pytest.raises(ValidationError, match="belongs to Company"):
        inspect.unwrap(module.zatca_call_compliance)(invoice.name, company_abbr="TC")
    module.digital_signature.assert_not_called()
    api.assert_not_called()


@pytest.mark.parametrize("module", [sign_invoice, pos_sign])
def test_invalid_explicit_type_is_not_replaced_by_legacy_default(isolated, monkeypatch, module):
    invoice, _, _, _, _ = isolated
    stub_pipeline(monkeypatch, module, invoice)
    with pytest.raises(ValidationError, match="Select a valid"):
        inspect.unwrap(module.zatca_call_compliance)(
            invoice.name, company_abbr="TC", compliance_type="1", validation_type="invalid",
        )
    module.salesinvoice_data.assert_not_called()


@pytest.mark.parametrize("wrong_company", [False, True])
def test_single_summary_integrates_with_the_existing_isolated_generator(isolated, monkeypatch, wrong_company):
    invoice, company, _, app, _ = isolated
    company.check_permission = Mock()
    invoice.check_permission = Mock()
    stub_pipeline(monkeypatch, sign_invoice, invoice)
    # Skip only the nested Frappe HTTP type wrapper, which needs request-local
    # framework flags. Keep the real generator body and all its source checks.
    monkeypatch.setattr(sign_invoice, "zatca_call_compliance", inspect.unwrap(sign_invoice.zatca_call_compliance))
    api = Mock(return_value={"validationResults": {"status": "PASS"}})
    monkeypatch.setattr(sign_invoice, "compliance_api_call", api)
    if wrong_company:
        invoice.company = "OTHER FICTIONAL COMPANY"
    result = inspect.unwrap(sign_invoice.run_single_compliance_summary)(company.name, invoice.name)
    row = result["results"][0]
    assert row["type"] == "Standard Invoice"
    if wrong_company:
        assert row["status"] == "FAIL" and "belongs to Company" in row["technical_details"]
        api.assert_not_called()
        sign_invoice.digital_signature.assert_not_called()
    else:
        assert row["status"] == "PASS"
        api.assert_called_once()
        assert sign_invoice.invoice_typecode_compliance.call_args.args[1] == "2"
    assert app.flags == {"mute_messages": False}
    invoice.db_set.assert_not_called()
    invoice.save.assert_not_called()
    company.db_set.assert_not_called()
    app.db.commit.assert_not_called()


def test_batch_passes_types_without_mutating_company(isolated, monkeypatch):
    invoice, company, _, _, _ = isolated
    submit = Mock(return_value={"validationResults": {"status": "PASS"}})
    monkeypatch.setattr(sign_invoice, "zatca_call_compliance", submit)
    result = inspect.unwrap(sign_invoice.run_all_compliance_summary)(company.name, invoice.name)
    assert [call.kwargs["validation_type"] for call in submit.call_args_list] == list(COMPLIANCE_TYPES)
    assert all(row["status"] == "PASS" for row in result["results"])
    company.db_set.assert_not_called()
    assert company.custom_validation_type == "Standard Invoice"


@pytest.mark.parametrize("code", ["1", "2", "3", "4", "5", "6"])
def test_type_resolver_preserves_legacy_numeric_fallback(code):
    assert resolve_compliance_type(None, fallback=code) == code


def test_pure_preview_rejects_an_unknown_purpose():
    with pytest.raises(ValueError, match="Unsupported non-production"):
        preview_invoice_uuid(None, "Production")


@pytest.mark.parametrize("rejected", [False, True])
def test_temporary_xml_is_private_unique_exact_and_removed(rejected):
    content = '<?xml version="1.0" encoding="UTF-8"?>\n<Invoice>اختبار</Invoice>\n'
    paths = []
    try:
        with temporary_compliance_xml(content) as first, temporary_compliance_xml(content) as second:
            paths = [Path(first), Path(second)]
            assert first != second
            for path in paths:
                assert path.read_bytes() == content.encode("utf-8")
                assert path.stat().st_mode & 0o077 == 0
            if rejected:
                raise ValidationError("Mock rejection")
    except ValidationError:
        assert rejected
    assert all(not path.exists() for path in paths)


def test_synthetic_onboarding_uses_the_same_temporary_file_contract(isolated, monkeypatch):
    _, company, _, _, _ = isolated
    payload = "<Invoice>synthetic</Invoice>"
    monkeypatch.setattr(sign_invoice, "_prepare_signed_onboarding_document", lambda *args: ("uuid", "hash", payload))
    seen = []

    def submit(uuid, invoice_hash, path, abbr, source_doc):
        seen.append(Path(path))
        assert seen[-1].read_text(encoding="utf-8") == payload
        assert source_doc is None
        return {"validationResults": {"status": "PASS"}}

    monkeypatch.setattr(sign_invoice, "compliance_api_call", submit)
    assert sign_invoice._submit_onboarding_document(company, "Standard Invoice")["validationResults"]["status"] == "PASS"
    assert not seen[0].exists()
