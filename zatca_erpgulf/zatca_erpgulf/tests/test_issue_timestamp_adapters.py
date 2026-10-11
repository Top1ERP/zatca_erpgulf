"""Actual metadata/QR/sample adapters with mocked ERP/files/keys, no authority."""

import base64
import csv
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import (
    advance_deduction, create_qr, createxml, posxml, qr_timestamp, sign_invoice, sign_invoice_first,
)
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES
from zatca_erpgulf.zatca_erpgulf.issue_timestamp import IssueTimestampError, resolve_issue_timestamp
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import (
    Document, ValidationError, fail, isolated,
)


@pytest.mark.parametrize("clock", ["9:05:42Z", "9:05:42+03:00", time(9, 5, 42, tzinfo=timezone.utc)])
def test_explicit_timezone_never_queries_system_settings(monkeypatch, clock):
    getter = Mock(side_effect=AssertionError("No site/settings lookup for explicit offsets"))
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", getter)
    stamp = qr_timestamp.resolve_zatca_issue_timestamp("2026-09-27", clock)
    assert stamp.qr_value == resolve_issue_timestamp("2026-09-27", clock).qr_value
    assert qr_timestamp.format_zatca_issue_datetime("2026-09-27", clock).tzinfo is timezone.utc
    getter.assert_not_called()


@pytest.mark.parametrize("clock", [timedelta(0), "9:05:42", time(9, 5, 42)])
def test_naive_values_read_configured_timezone_once(monkeypatch, clock):
    getter = Mock(return_value="Asia/Riyadh")
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", getter)
    assert qr_timestamp.format_zatca_qr_timestamp("2026-09-27", clock) == resolve_issue_timestamp(
        "2026-09-27", clock, timezone_name="Asia/Riyadh").qr_value
    getter.assert_called_once()


@pytest.mark.parametrize("failure", ["fields", "timezone", "lookup", "dst"])
def test_adapter_errors_are_static_unchained_and_arabic_keys_exist(monkeypatch, failure):
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    for message in (qr_timestamp.INVALID_FIELDS, qr_timestamp.INVALID_TIMEZONE, qr_timestamp.INVALID_DST):
        assert translations[message] != message
    monkeypatch.setattr(qr_timestamp, "_", lambda message: translations[message])
    getter = Mock(return_value="Europe/Berlin" if failure == "dst" else "UTC")
    if failure == "timezone":
        getter.return_value = "PRIVATE-INVALID-ZONE"
    elif failure == "lookup":
        getter.side_effect = RuntimeError("PRIVATE-SECRET site setting traceback")
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", getter)
    day, clock = ("2026-10-25", "02:30:00") if failure == "dst" else ("2026-09-27", "9:05:42")
    if failure == "fields":
        clock = "PRIVATE-RAW-INVOICE-TIME"
    with pytest.raises(ValueError) as error:
        qr_timestamp.format_zatca_qr_timestamp(day, clock)
    message = {"fields": qr_timestamp.INVALID_FIELDS, "timezone": qr_timestamp.INVALID_TIMEZONE,
        "lookup": qr_timestamp.INVALID_TIMEZONE, "dst": qr_timestamp.INVALID_DST}[failure]
    assert str(error.value) == translations[message] and error.value.__context__ is None
    assert "PRIVATE" not in str(error.value)
    assert getter.call_count == (0 if failure == "fields" else 1)


@pytest.mark.parametrize("module,doctype", [(createxml, "Sales Invoice"), (posxml, "POS Invoice")])
@pytest.mark.parametrize("purpose", ["production", "debug", "compliance"])
@pytest.mark.parametrize("clock", ["9:05:42", timedelta(0), "23:59:59-02:00"])
def test_xml_identity_and_time_use_one_loaded_invoice_not_a_second_revision(isolated, monkeypatch, module, doctype, purpose, clock):
    invoice, _, _, runtime, _ = isolated
    invoice.doctype, invoice.posting_date, invoice.posting_time = doctype, "2026-09-27", clock
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", lambda: "Asia/Riyadh")
    monkeypatch.setattr(qr_timestamp, "_", lambda message: message)
    runtime.get_doc.side_effect = [invoice, AssertionError("Unexpected second invoice read")]
    root, _, returned = module.salesinvoice_data(ET.Element("Invoice"), invoice.name, purpose=purpose)
    expected = resolve_issue_timestamp(invoice.posting_date, clock, timezone_name="Asia/Riyadh")
    assert root.find("cbc:IssueDate").text == expected.xml_date
    assert root.find("cbc:IssueTime").text == expected.xml_time and returned is invoice
    runtime.get_doc.assert_called_once_with(doctype, invoice.name)
    assert invoice.posting_date == "2026-09-27" and invoice.posting_time == clock
    invoice.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("module", [createxml, posxml])
@pytest.mark.parametrize("purpose", ["production", "debug", "compliance"])
@pytest.mark.parametrize("clock", [None, "24:00:00", timedelta(days=1)])
def test_invalid_time_fails_before_uuid_persistence_or_xml_append(isolated, module, purpose, clock):
    invoice, _, _, runtime, _ = isolated
    invoice.custom_uuid, invoice.posting_time = None, clock
    root = ET.Element("Invoice")
    with pytest.raises(ValidationError, match="Invalid invoice issue date or time"):
        module.salesinvoice_data(root, invoice.name, purpose=purpose)
    assert len(root) == 0 and invoice.custom_uuid is None
    invoice.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("module,doctype", [(createxml, "Sales Invoice"), (posxml, "POS Invoice")])
def test_legacy_name_based_time_wrappers_still_work(isolated, module, doctype):
    invoice, _, _, runtime, _ = isolated
    assert module.get_issue_timestamp(invoice.name) == "2026-10-09T09:05:42Z"
    assert module.get_issue_time(invoice.name) == "09:05:42Z"
    assert runtime.get_doc.call_args.args == (doctype, invoice.name)


def tlv_values(encoded):
    payload = base64.b64decode(encoded)
    values, offset = {}, 0
    while offset < len(payload):
        tag, size = payload[offset:offset + 2]
        values[tag] = payload[offset + 2:offset + 2 + size].decode()
        offset += size + 2
    assert offset == len(payload)
    return values


@pytest.fixture
def local_qr(monkeypatch):
    invoice = Document(doctype="Sales Invoice", name="SYNTHETIC-TIME", company="SYNTHETIC-COMPANY", docstatus=1,
        posting_date="2026-09-27", posting_time="9:05:42", ksa_einv_qr=None, base_grand_total=11.5,
        total_taxes_and_charges=1.5, custom_zatca_advance_deducted_taxable_amount=2, discount_amount=0,
        total=10, net_total=10, base_total=10, base_net_total=10, conversion_rate=1, currency="SAR",
        base_total_taxes_and_charges=1.5, db_set=Mock(), save=Mock(), notify_update=Mock(),
        meta=SimpleNamespace(has_field=lambda name: name == "ksa_einv_qr"))
    company = Document(company_name="SYNTHETIC-COMPANY", tax_id="300000000000003", company_name_in_arabic="شركة اختبار")
    file = Document(file_url="/files/SYNTHETIC-QR.png", save=Mock())
    runtime = SimpleNamespace(get_all=Mock(return_value=[]), get_doc=Mock(return_value=file),
        get_cached_doc=Mock(return_value=company), get_meta=Mock(return_value=SimpleNamespace(
            get_image_fields=lambda: [SimpleNamespace(fieldname="ksa_einv_qr")])), throw=fail,
        db=SimpleNamespace(exists=Mock(return_value=False), get_value=Mock(return_value=company.tax_id),
                           set_value=Mock(), commit=Mock()), delete_doc=Mock())
    payloads = []
    def image(payload, **kwargs):
        payloads.append(payload)
        return SimpleNamespace(png=lambda buffer, **options: buffer.write(b"synthetic image, not a PNG proof"))
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", lambda: "Asia/Riyadh")
    monkeypatch.setattr(qr_timestamp, "_", lambda message: message)
    monkeypatch.setattr(create_qr, "frappe", runtime)
    monkeypatch.setattr(create_qr, "get_region", lambda name: "Saudi Arabia")
    monkeypatch.setattr(create_qr, "get_company_arabic_name", lambda name: company.company_name_in_arabic)
    monkeypatch.setattr(create_qr, "qr_create", image)
    monkeypatch.setattr(create_qr, "create_custom_fields", Mock(side_effect=AssertionError("No schema write")))
    monkeypatch.setattr(advance_deduction, "frappe", runtime)
    runtime.get_doc.side_effect = lambda *args, **kwargs: company if args and args[0] == "Company" else file
    monkeypatch.setattr(advance_deduction, "is_zatca_invoice_enabled", lambda doc: True)
    monkeypatch.setattr(advance_deduction, "resolve_zatca_phase", lambda doc: "Phase-1")
    monkeypatch.setattr(advance_deduction, "supports_advance_deduction_schema", lambda doc: True)
    monkeypatch.setattr(advance_deduction, "is_advance_payment_invoice", lambda doc: True)
    import pyqrcode
    import frappe.utils.file_manager
    monkeypatch.setattr(pyqrcode, "create", image)
    saver = Mock(return_value=file)
    monkeypatch.setattr(frappe.utils.file_manager, "save_file", saver)
    return invoice, runtime, payloads, saver


@pytest.mark.parametrize("route", ["sales", "pos", "advance"])
@pytest.mark.parametrize("clock", ["9:05:42", timedelta(0), "23:59:59-02:00"])
def test_phase1_and_advance_qr_share_time_without_changing_amount_formulas(local_qr, route, clock):
    invoice, _, payloads, _ = local_qr
    invoice.posting_time = clock
    if route == "advance":
        advance_deduction.ensure_final_sales_invoice_qr_for_print(invoice)
    else:
        if route == "pos":
            invoice.doctype = "POS Invoice"
        create_qr.create_qr_code(invoice)
    assert len(payloads) == 1
    values = tlv_values(payloads[0])
    assert values[3] == resolve_issue_timestamp(invoice.posting_date, clock, timezone_name="Asia/Riyadh").qr_value
    # Characterize existing arithmetic/formatting, NOT regulatory amount proof.
    assert values[4] == ("9.50" if route == "advance" else "11.5")
    assert values[5] == ("1.50" if route == "advance" else "1.5")


@pytest.mark.parametrize("route", ["sales", "advance"])
@pytest.mark.parametrize("clock", [None, timedelta(days=1), "24:00:00"])
def test_bad_phase1_clock_cannot_save_a_new_image(local_qr, route, clock):
    invoice, runtime, payloads, saver = local_qr
    invoice.posting_time = clock
    with pytest.raises(ValueError):
        if route == "advance":
            advance_deduction.ensure_final_sales_invoice_qr_for_print(invoice)
        else:
            create_qr.create_qr_code(invoice)
    assert not payloads
    saver.assert_not_called()
    invoice.db_set.assert_not_called()
    invoice.save.assert_not_called()
    runtime.db.commit.assert_not_called()


def test_advance_phase2_guard_preserves_the_existing_authoritative_qr(local_qr, monkeypatch):
    invoice, runtime, payloads, saver = local_qr
    invoice.ksa_einv_qr, invoice.posting_time = "/files/EXISTING-ACCEPTED-QR.png", None
    monkeypatch.setattr(advance_deduction, "resolve_zatca_phase", lambda doc: advance_deduction.PHASE_2_VALUE)
    advance_deduction.ensure_final_sales_invoice_qr_for_print(invoice, force=True)
    assert invoice.ksa_einv_qr == "/files/EXISTING-ACCEPTED-QR.png" and not payloads
    saver.assert_not_called()
    runtime.db.set_value.assert_not_called()


@pytest.fixture
def xml_qr(monkeypatch):
    runtime = SimpleNamespace(throw=fail, ValidationError=ValidationError)
    monkeypatch.setattr(sign_invoice_first, "frappe", runtime)
    monkeypatch.setattr(sign_invoice_first, "_", lambda message: message)
    monkeypatch.setattr(sign_invoice_first, "tag8_publickey", Mock(return_value=b"synthetic public key"))
    monkeypatch.setattr(sign_invoice_first, "tag9_signature_ecdsa", Mock(return_value=b"synthetic signature"))
    monkeypatch.setattr(sign_invoice_first, "_is_simplified_document", lambda doc: False)
    monkeypatch.setattr(qr_timestamp, "get_system_timezone", Mock(side_effect=AssertionError("XML already has offset")))
    root = etree.Element("Invoice", nsmap={None: sign_invoice._ONBOARDING_UBL["ubl"],
        "cbc": sign_invoice._ONBOARDING_UBL["cbc"], "cac": sign_invoice._ONBOARDING_UBL["cac"]})
    # ElementTree-style root requires a QName for XPath's expected namespace.
    root.tag = "{" + sign_invoice._ONBOARDING_UBL["ubl"] + "}Invoice"
    add = sign_invoice._onboarding_element
    add(root, "cbc", "IssueDate", "2026-09-27")
    add(root, "cbc", "IssueTime", "06:05:42Z")
    add(root, "cbc", "InvoiceTypeCode", "388", name="0100000")
    supplier = add(add(root, "cac", "AccountingSupplierParty"), "cac", "Party")
    add(add(supplier, "cac", "PartyLegalEntity"), "cbc", "RegistrationName", "شركة اختبار")
    add(add(supplier, "cac", "PartyTaxScheme"), "cbc", "CompanyID", "300000000000003")
    add(add(root, "cac", "LegalMonetaryTotal"), "cbc", "PayableAmount", "11.50")
    add(add(root, "cac", "TaxTotal"), "cbc", "TaxAmount", "1.50")
    return root


def qr_tags(root):
    return sign_invoice_first.generate_tlv_xml(etree.tostring(root).decode(), "TEST", Document(doctype="Sales Invoice"))


@pytest.mark.parametrize("name,code", [("0100000", "388"), ("0200000", "388"), ("0100000", "381"),
    ("0200000", "381"), ("0100000", "383"), ("0211000", "383"), ("0200000", "386")])
def test_phase2_qr_reads_declared_xml_time_without_double_conversion(xml_qr, name, code):
    element = xml_qr.find("cbc:InvoiceTypeCode", sign_invoice._ONBOARDING_UBL)
    element.set("name", name)
    element.text = code
    assert qr_tags(xml_qr)[3] == "2026-09-27T06:05:42Z"


@pytest.mark.parametrize("field", ["IssueDate", "IssueTime"])
@pytest.mark.parametrize("change", ["missing", "duplicate", "blank", "child"])
def test_ambiguous_xml_clock_fails_before_accessing_qr_key_material(xml_qr, field, change):
    element = xml_qr.find("cbc:" + field, sign_invoice._ONBOARDING_UBL)
    if change == "missing":
        xml_qr.remove(element)
    elif change == "duplicate":
        sign_invoice._onboarding_element(xml_qr, "cbc", field, element.text)
    elif change == "blank":
        element.text = " "
    else:
        sign_invoice._onboarding_element(element, "cbc", "ID", "unexpected")
    with pytest.raises(ValidationError, match="exactly one nonempty IssueDate and IssueTime"):
        qr_tags(xml_qr)
    sign_invoice_first.tag8_publickey.assert_not_called()
    sign_invoice_first.tag9_signature_ecdsa.assert_not_called()


@pytest.mark.parametrize("label", list(COMPLIANCE_TYPES))
@pytest.mark.parametrize("instant", [datetime(2026, 9, 27, 9, 5, 42, tzinfo=timezone.utc),
    datetime(2026, 9, 28, 0, 1, tzinfo=timezone(timedelta(hours=3)))])
def test_synthetic_six_types_use_aware_utc_not_host_or_site_timezone(isolated, xml_qr, monkeypatch, label, instant):
    _, company, _, runtime, _ = isolated
    company.tax_id = "300000000000003"
    address = Document(address_line1="SYNTHETIC-ROAD", address_line2="SYNTHETIC-DISTRICT", city="Riyadh",
        pincode="12345", state="Riyadh", custom_building_number="1234")
    monkeypatch.setattr(sign_invoice, "_onboarding_address", Mock(return_value=address))
    _, content = sign_invoice._build_onboarding_invoice_xml(company, label, issue_instant=instant)
    root = etree.fromstring(content.encode())
    expected = instant.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    assert qr_tags(root)[3] == expected
    assert root.find("cbc:IssueTime", sign_invoice._ONBOARDING_UBL).text.endswith("Z")
    company.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()


def test_synthetic_sample_rejects_a_naive_clock_instead_of_guessing(isolated, monkeypatch):
    _, company, _, _, _ = isolated
    monkeypatch.setattr(sign_invoice, "_onboarding_address", Mock(return_value=Document()))
    with pytest.raises(IssueTimestampError, match="issue_timezone"):
        sign_invoice._build_onboarding_invoice_xml(company, "Standard Invoice", issue_instant=datetime(2026, 9, 27, 9, 5, 42))


def test_default_sample_clock_is_explicitly_aware_utc(isolated, xml_qr, monkeypatch):
    _, company, _, _, _ = isolated
    company.tax_id = "300000000000003"
    instant = datetime(2026, 9, 27, 9, 5, 42, tzinfo=timezone.utc)
    clock = Mock(return_value=instant)
    monkeypatch.setattr(sign_invoice, "datetime", SimpleNamespace(now=clock))
    monkeypatch.setattr(sign_invoice, "_onboarding_address", lambda name: Document(
        address_line1="SYNTHETIC-ROAD", address_line2="DISTRICT", city="Riyadh", pincode="12345", state="", custom_building_number="1234"))
    _, content = sign_invoice._build_onboarding_invoice_xml(company, "Standard Invoice")
    clock.assert_called_once_with(timezone.utc)
    root = etree.fromstring(content.encode())
    assert qr_tags(root)[3] == "2026-09-27T09:05:42Z"
    assert root.xpath("string(cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID)",
                      namespaces=sign_invoice._ONBOARDING_UBL) == str(int(instant.timestamp()))
