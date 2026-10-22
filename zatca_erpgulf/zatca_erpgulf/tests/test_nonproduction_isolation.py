"""Protect live invoice identity/artifacts from diagnostic and compliance paths.

All Frappe, signing, and HTTP boundaries are mocked. File assertions use only
pytest temporary directories or the temporary sample file being submitted.
"""

import inspect
from copy import deepcopy
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
    DEBUG_LOCAL_ONLY, DEBUG_EXISTING, DEBUG_ACCESS_DENIED, DEBUG_ATTACHMENT_REVIEW,
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
        modified="2026-10-23 09:00:00",
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
        modified="2026-10-23 08:00:00",
        custom_validation_type="Standard Invoice", custom_send_invoice_to_zatca="Live",
        db_set=Mock(),
    )
    customer = Document(tax_id="BUYER")
    files = []

    def get_doc(doctype, name=None):
        if isinstance(doctype, dict):
            if doctype["doctype"] == "File":
                files.append(doctype)
                attachment = Document(**doctype, flags={})
                attachment.save = Mock(side_effect=lambda: setattr(attachment, "name", f"MOCK-FILE-{len(files)}"))
                return attachment
            return company
        return {"Sales Invoice": invoice, "POS Invoice": invoice,
                "Company": company, "Customer": customer}[doctype]

    def has_permission(doctype, ptype="read", doc=None, user=None, raise_exception=True):
        return True

    frappe = SimpleNamespace(
        session=SimpleNamespace(user="mock.operator"), has_permission=has_permission,
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
    assert result["file_name"] == files[0]["file_name"]
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
    if module is pos_debug_xml:
        invoice.doctype = "POS Invoice"
    monkeypatch.setattr(module, "is_zatca_invoice_enabled", lambda *args: True)
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result == {"status": "skipped", "message": DEBUG_SKIPPED, "notices": []}
    frappe.msgprint.assert_not_called()
    invoice.save.assert_not_called()
    frappe.db.commit.assert_not_called()
    assert invoice.custom_zatca_status == "REPORTED"
    assert invoice.custom_zatca_full_response == "live-response"


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
@pytest.mark.parametrize("version", [15, 16])
@pytest.mark.parametrize("denied", ["invoice-read", "invoice-write", "company-read", "file-create"])
def test_debug_entry_requires_saved_source_and_create_acl_before_generation(isolated, monkeypatch, module, version, denied):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)

    def allowed(dt, op):
        key = ("company-read" if dt == "Company" else "file-create" if dt == "File" else "invoice-" + op)
        return key != denied

    def v15(dt, op, doc=None, user=None, raise_exception=True):
        assert raise_exception is False
        return allowed(dt, op)

    def v16(dt, op, doc=None, user=None, *, print_logs=True):
        assert print_logs is False
        return allowed(dt, op)

    app.has_permission = v15 if version == 15 else v16
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result == {"status": "error", "message": DEBUG_FAILED,
                      "technical_details": DEBUG_ACCESS_DENIED, "notices": [DEBUG_ACCESS_DENIED]}
    assert not files
    module.salesinvoice_data.assert_not_called()
    module.digital_signature.assert_not_called()
    app.delete_doc.assert_not_called()
    app.db.commit.assert_not_called()


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
@pytest.mark.parametrize("drift", ["source", "company", "actor"])
def test_debug_entry_rechecks_source_before_creating_attachment(isolated, monkeypatch, module, drift):
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    formatter = module.format_zatca_signed_xml

    def changed(value):
        result = formatter(value)
        if drift == "actor":
            app.session.user = "another.operator"
        else:
            (invoice if drift == "source" else company).modified = "2026-10-23 11:00:00"
        return result

    monkeypatch.setattr(module, "format_zatca_signed_xml", changed)
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result["status"] == "error" and result["technical_details"] == DEBUG_ATTACHMENT_REVIEW
    assert not files
    app.delete_doc.assert_not_called()
    app.db.commit.assert_not_called()
    assert app.flags == {"mute_messages": False}


@pytest.mark.parametrize("module", [debug_xml, pos_debug_xml])
def test_debug_private_engine_fault_is_logged_but_not_returned_to_ui(isolated, monkeypatch, module):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)

    def faulty(dt, op, doc=None, user=None, raise_exception=True):
        raise TypeError("PRIVATE diagnostic engine fault")

    app.has_permission = faulty
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert result == {"status": "error", "message": DEBUG_FAILED,
                      "technical_details": DEBUG_ATTACHMENT_REVIEW, "notices": [DEBUG_ATTACHMENT_REVIEW]}
    assert "PRIVATE diagnostic engine fault" in app.log_error.call_args.args[0]
    assert not files
    module.salesinvoice_data.assert_not_called()


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
@pytest.mark.parametrize("version", [15, 16])
@pytest.mark.parametrize("file_read", [True, False])
def test_debug_entry_returns_only_authorized_attachment_projection(isolated, monkeypatch, module, version, file_read):
    invoice, _, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, module)
    loader = app.get_doc.side_effect
    saved = []

    def get_doc(dt, name=None):
        doc = loader(dt, name)
        if isinstance(dt, dict) and dt.get("doctype") == "File":
            original = doc.save.side_effect

            def save():
                original()
                doc.file_url = "/private/files/DEBUG_MOCK.xml"
                saved.append(doc)

            doc.save.side_effect = save
        return doc

    def v15(dt, op, doc=None, user=None, raise_exception=True):
        assert raise_exception is False
        return file_read if (dt, op) == ("File", "read") else True

    def v16(dt, op, doc=None, user=None, *, print_logs=True):
        assert print_logs is False
        return file_read if (dt, op) == ("File", "read") else True

    app.get_doc.side_effect = get_doc
    app.has_permission = v15 if version == 15 else v16
    result = inspect.unwrap(module.debug_call)(invoice.name)
    assert len(saved) == len(files) == 1
    saved[0].save.assert_called_once_with()
    if file_read:
        assert result == {"status": "success", "message": DEBUG_CREATED, "notices": [],
            "file_name": saved[0].file_name, "attachment": {
                "name": saved[0].name, "file_name": saved[0].file_name,
                "file_url": "/private/files/DEBUG_MOCK.xml", "is_private": 1,
                "attached_to_doctype": invoice.doctype, "attached_to_name": invoice.name,
            }}
    else:
        assert result == {"status": "error", "message": DEBUG_FAILED,
            "technical_details": DEBUG_ATTACHMENT_REVIEW, "notices": [DEBUG_ATTACHMENT_REVIEW]}
    assert app.flags == {"mute_messages": False} and app.local.lang == "ar"
    app.msgprint.assert_not_called()
    app.db.commit.assert_not_called()
    app.delete_doc.assert_not_called()
    invoice.db_set.assert_not_called()
    invoice.save.assert_not_called()
    module.compliance_api_call.assert_not_called()


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


def test_pos_debug_background_generates_only_a_local_artifact(isolated, monkeypatch):
    """Regression for the old undefined, unused Background selector."""
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    company.custom_send_invoice_to_zatca = "Background"
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    monkeypatch.delattr(pos_debug_xml, "bypass_background_check", raising=False)
    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name)
    assert result["status"] == "success" and result["message"] == DEBUG_CREATED
    assert len(files) == 1 and files[0]["file_name"] == result["file_name"]
    assert files[0]["is_private"] == 1
    assert app.flags == {"mute_messages": False}
    invoice.save.assert_not_called()
    app.db.commit.assert_not_called()
    pos_debug_xml.compliance_api_call.assert_not_called()


@pytest.mark.parametrize("phase", ["Phase-1", "Phase-2"])
@pytest.mark.parametrize("method", ["Background", "Live", "Batches", "Immediate", "", None])
@pytest.mark.parametrize("b2c", [0, 1])
@pytest.mark.parametrize("compliance_type", ["0", "1", "2", "3", "4", "5", "6"])
def test_pos_debug_type_selection_is_independent_of_live_scheduling(
    isolated, monkeypatch, tmp_path, phase, method, b2c, compliance_type,
):
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    company.custom_send_invoice_to_zatca = method
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: phase)
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    monkeypatch.setattr(pos_debug_xml, "get_alias_value", lambda group, *args: b2c if group == "customer_b2c" else "")
    transport = SimpleNamespace(request=Mock(), post=Mock())
    monkeypatch.setattr(pos_debug_xml, "requests", transport)
    monkeypatch.setattr(pos_debug_xml, "get_api_url", Mock())
    snapshot = deepcopy({key: value for key, value in vars(invoice).items() if not callable(value)})
    originals = {tmp_path / "signed.xml": b"ORIGINAL-SYNTHETIC-SIGNED-XML",
                 tmp_path / "qr.png": b"ORIGINAL-SYNTHETIC-QR"}
    for path, value in originals.items():
        path.write_bytes(value)

    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name, compliance_type=compliance_type)

    if compliance_type == "0" and not b2c:
        assert result["status"] == "error" and result["message"] == DEBUG_FAILED
        assert "Customer should be B2C" in result["technical_details"]
        assert not files
        pos_debug_xml.invoice_typecode_simplified.assert_not_called()
        pos_debug_xml.invoice_typecode_compliance.assert_not_called()
    else:
        assert result["status"] == "success" and result["message"] == DEBUG_CREATED
        assert result["notices"] == []
        assert len(files) == 1 and files[0]["file_name"] == result["file_name"]
        assert files[0]["is_private"] == 1 and files[0]["attached_to_doctype"] == "POS Invoice"
        if compliance_type == "0":
            pos_debug_xml.invoice_typecode_simplified.assert_called_once()
            pos_debug_xml.invoice_typecode_compliance.assert_not_called()
        else:
            assert pos_debug_xml.invoice_typecode_compliance.call_args.args[1] == compliance_type
            pos_debug_xml.invoice_typecode_simplified.assert_not_called()
        assert pos_debug_xml.salesinvoice_data.call_args.kwargs["purpose"] == "debug"
        assert pos_debug_xml.doc_reference.call_args.kwargs["debug"] is True
    assert {key: value for key, value in vars(invoice).items() if not callable(value)} == snapshot
    assert all(path.read_bytes() == value for path, value in originals.items())
    assert app.flags == {"mute_messages": False} and app.local.lang == "ar"
    invoice.save.assert_not_called()
    invoice.db_set.assert_not_called()
    company.db_set.assert_not_called()
    app.db.commit.assert_not_called()
    app.db.set_value.assert_not_called()
    app.db.sql.assert_not_called()
    app.msgprint.assert_not_called()
    app.delete_doc.assert_not_called()
    pos_debug_xml.get_api_url.assert_not_called()
    pos_debug_xml.compliance_api_call.assert_not_called()
    transport.request.assert_not_called()
    transport.post.assert_not_called()


@pytest.mark.parametrize("phase,schema,unique,pos_name,gpos,xml,qr,attached,error,notice", [
    ("Phase-2", True, True, None, False, False, False, False, "POS name is required", False),
    ("Phase-2", True, True, "MOCK-POS", False, False, False, False, None, False),
    ("Phase-2", True, True, "MOCK-POS", True, True, True, False, None, True),
    ("Phase-2", True, True, None, True, True, True, False, "POS name is required", False),
    ("Phase-2", False, True, None, False, False, False, False, None, False),
    ("Phase-1", True, True, None, False, False, False, False, None, False),
    ("Phase-1", True, False, None, True, True, False, False, "qr_code", False),
    ("Phase-2", True, False, None, True, True, False, False, "qr_code", False),
    ("Phase-2", True, False, None, True, True, True, False, None, False),
    ("Phase-2", True, False, None, False, False, False, True, None, True),
    ("Phase-1", True, False, None, False, False, False, True, None, False),
    ("Phase-2", False, True, None, False, False, False, True, None, True),
])
def test_pos_debug_preserves_phase_schema_pos_gpos_and_existing_artifact_checks(
    isolated, monkeypatch, phase, schema, unique, pos_name, gpos, xml, qr, attached, error, notice,
):
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    company.custom_send_invoice_to_zatca = "Background"
    invoice.custom_unique_id = "MOCK-UNIQUE" if unique else None
    invoice.custom_zatca_pos_name = pos_name
    invoice.custom_xml = "<Original/>" if xml else None
    invoice.custom_qr_code = "ORIGINAL-QR" if qr else None
    monkeypatch.setattr(pos_debug_xml, "_", lambda message: message)
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: phase)
    app.get_meta.return_value.has_field = lambda field: schema
    app.get_installed_apps.return_value = ["gpos"] if gpos else []
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", Mock(return_value=attached))
    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name)
    if error:
        assert result["status"] == "error" and error in result["technical_details"]
        assert not files
        pos_debug_xml.salesinvoice_data.assert_not_called()
    else:
        assert result["status"] == "success" and len(files) == 1
        assert result["notices"] == ([DEBUG_EXISTING] if notice else [])
    assert invoice.custom_xml == ("<Original/>" if xml else None)
    assert invoice.custom_qr_code == ("ORIGINAL-QR" if qr else None)
    invoice.save.assert_not_called()
    invoice.db_set.assert_not_called()
    app.db.commit.assert_not_called()
    pos_debug_xml.compliance_api_call.assert_not_called()


@pytest.mark.parametrize("phase", ["Phase-1", "Phase-2"])
@pytest.mark.parametrize("method", ["Background", "Live"])
@pytest.mark.parametrize("template", [False, True])
def test_pos_debug_keeps_existing_explicit_tax_adapter_choice(isolated, monkeypatch, phase, method, template):
    invoice, company, _, _, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    company.custom_send_invoice_to_zatca = method
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: phase)
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    for name in ("add_document_level_discount_with_tax_template", "tax_data_with_template", "item_data_with_template"):
        monkeypatch.setattr(pos_debug_xml, name, Mock(side_effect=lambda root, *args: root))
    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name, any_item_has_tax_template=template)
    assert result["status"] == "success" and len(files) == 1
    for plain, with_template in (("tax_data", "tax_data_with_template"), ("item_data", "item_data_with_template"),
                                 ("add_document_level_discount_with_tax", "add_document_level_discount_with_tax_template")):
        assert getattr(pos_debug_xml, with_template if template else plain).call_count == 1
        getattr(pos_debug_xml, plain if template else with_template).assert_not_called()


def test_pos_debug_does_not_read_or_add_live_background_configuration(isolated, monkeypatch):
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)

    class LocalSettings(Document):
        @property
        def custom_send_invoice_to_zatca(self):
            raise AssertionError("Debug must not read live scheduling")

    settings = LocalSettings(**{key: value for key, value in vars(company).items() if key != "custom_send_invoice_to_zatca"})
    get_doc = app.get_doc.side_effect
    app.get_doc.side_effect = lambda doctype, name=None: settings if doctype == "Company" else get_doc(doctype, name)
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name)
    assert result["status"] == "success" and len(files) == 1
    assert tuple(inspect.signature(inspect.unwrap(pos_debug_xml.debug_call)).parameters) == (
        "invoice_number", "compliance_type", "any_item_has_tax_template", "company_abbr", "source_doc",
    )
    app.db.commit.assert_not_called()
    pos_debug_xml.compliance_api_call.assert_not_called()


def test_pos_debug_background_still_rejects_buyer_id_without_type(isolated, monkeypatch):
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    company.custom_send_invoice_to_zatca = "Background"
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(pos_debug_xml, "_", lambda message: message)
    monkeypatch.setattr(pos_debug_xml, "get_alias_value", lambda group, *args: "MOCK-ID" if group == "customer_buyer_id" else "")
    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name)
    assert result["status"] == "error" and "Buyer ID must be blank" in result["technical_details"]
    assert not files
    pos_debug_xml.salesinvoice_data.assert_not_called()
    pos_debug_xml.compliance_api_call.assert_not_called()
    invoice.save.assert_not_called()
    app.db.commit.assert_not_called()


def test_pos_debug_background_does_not_turn_signing_failure_into_success(isolated, monkeypatch):
    invoice, company, _, app, files = isolated
    prepare_debug_messages(isolated, monkeypatch, pos_debug_xml)
    company.custom_send_invoice_to_zatca = "Background"
    monkeypatch.setattr(pos_debug_xml, "resolve_zatca_phase", lambda *args: "Phase-2")
    monkeypatch.setattr(pos_debug_xml, "is_qr_and_xml_attached", lambda *args: False)
    monkeypatch.setattr(pos_debug_xml, "digital_signature", Mock(side_effect=ValidationError("Synthetic signing failure")))
    result = inspect.unwrap(pos_debug_xml.debug_call)(invoice.name)
    assert result == {"status": "error", "message": DEBUG_FAILED,
                      "technical_details": "Synthetic signing failure", "notices": []}
    assert not files
    assert app.flags == {"mute_messages": False}
    pos_debug_xml.digital_signature.assert_called_once()
    pos_debug_xml.compliance_api_call.assert_not_called()
    invoice.save.assert_not_called()
    app.db.commit.assert_not_called()


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
