"""Synthetic shared-fragment/first-invoice tests; no site or authority access.

Presence/selection tests are not proof of genesis policy, authentic history,
atomic issuance or remote acceptance. Existing UUID/counter behavior stays.
"""

import base64
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import createxml, credential_settings, icv, posxml, sign_invoice
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES, compliance_document_type
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import (
    INITIAL_PREVIOUS_HASH, MISSING_PREVIOUS_HASH, QR_PLACEHOLDER, append_additional_references,
    append_compliance_type, append_invoice_metadata,
)
from zatca_erpgulf.zatca_erpgulf.invoice_identity import has_legacy_uuid_value
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import (
    Document, ValidationError, fail, isolated,
)


ADAPTERS = ((createxml, "Sales Invoice"), (posxml, "POS Invoice"))
EXPECTED_TYPES = (
    ("0200000", "388", True, False), ("0100000", "388", False, False),
    ("0200000", "381", True, True), ("0100000", "381", False, True),
    ("0211000", "383", True, True), ("0100000", "383", False, True),
)
FIXED_UUID = "b05809d9-7851-4767-b7e9-47af44c80cb9"


def synthetic_hash(label):
    return base64.b64encode(hashlib.sha256(label.encode()).digest()).decode()


class HashRecord(Document):
    def get(self, key, default=None):
        # Even masked credentials must not be projected by a PIH read.
        assert key not in credential_settings.SECRET_FIELDS
        return super().get(key, default)


@pytest.fixture
def hash_boundary(monkeypatch):
    company = HashRecord(doctype="Company", name="A", abbr="TC", tax_id="SYNTHETIC-VAT",
        custom_pih=synthetic_hash("company"), save=Mock(), db_set=Mock())
    linked = HashRecord(doctype="Company", name="B", tax_id="SYNTHETIC-VAT",
        custom_pih=synthetic_hash("linked"), save=Mock(), db_set=Mock())
    device = HashRecord(doctype="ZATCA Multiple Setting", name="DEVICE",
        custom_linked_doctype="A", custom__use_company_certificate__keys=0,
        custom_pih=synthetic_hash("device"), save=Mock(), db_set=Mock())
    sales = HashRecord(doctype="Sales Invoice", name="SI", company="A",
        custom_zatca_pos_name=None, save=Mock(), db_set=Mock())
    pos = HashRecord(doctype="POS Invoice", name="PI", company="A",
        custom_zatca_pos_name=None, save=Mock(), db_set=Mock())
    docs = {(doc.doctype, doc.name): doc for doc in (company, linked, device, sales, pos)}

    def load(doctype, name):
        if doctype == "Company" and isinstance(name, dict):
            assert name == {"abbr": "TC"}
            return company
        return docs[doctype, name]

    runtime = SimpleNamespace(get_doc=Mock(side_effect=load), throw=fail,
        ValidationError=ValidationError, db=SimpleNamespace(commit=Mock(), set_value=Mock()),
        msgprint=Mock(), log_error=Mock())
    for module in (createxml, posxml, credential_settings):
        monkeypatch.setattr(module, "frappe", runtime)
        monkeypatch.setattr(module, "_", lambda message: message)
    return SimpleNamespace(company=company, linked=linked, device=device, sales=sales,
                           pos=pos, runtime=runtime, docs=docs)


def assert_no_writes(b):
    for doc in b.docs.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
    b.runtime.db.commit.assert_not_called()
    b.runtime.db.set_value.assert_not_called()
    b.runtime.msgprint.assert_not_called()
    b.runtime.log_error.assert_not_called()


def select(b, module, owner, flag=0):
    source = b.sales if module is createxml else b.pos
    source.custom_zatca_pos_name = None if owner == "company" else b.device.name
    b.device.custom__use_company_certificate__keys = flag
    b.device.custom_linked_doctype = "B" if owner == "linked" else "A"
    return source


def embedded_hash(root):
    return root.find("cac:AdditionalDocumentReference").find("cac:Attachment").find("cbc:EmbeddedDocumentBinaryObject").text


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("owner,flag", [
    ("company", 0), ("device", 0), ("device", "0"), ("device", False),
    ("linked", 1), ("linked", "1"), ("linked", " 1 "), ("linked", True),
])
def test_pih_uses_shared_signing_owner_policy_without_reading_secrets(hash_boundary, module, doctype, owner, flag):
    b = hash_boundary
    source = select(b, module, owner, flag)
    holder = getattr(b, owner)
    selected = credential_settings._resolve_owner_from_saved_company(b.company, source, include_secrets=False)
    assert (selected.doctype, selected.name) == (holder.doctype, holder.name)
    root = module.additional_reference(ET.Element("Invoice"), "TC", source)
    assert embedded_hash(root) == holder.custom_pih
    assert [ref.find("cbc:ID").text for ref in root.findall("cac:AdditionalDocumentReference")] == ["PIH", "QR"]
    assert [child.tag for child in root] == ["cac:AdditionalDocumentReference"] * 2 + ["cac:Signature"]
    assert_no_writes(b)


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("owner,flag", [("company", 0), ("device", 0), ("linked", "1")])
@pytest.mark.parametrize("value", [None, "", " \n\t", 0, False, b"hash", ["hash"]])
def test_missing_pih_never_invents_a_first_hash_or_falls_back(hash_boundary, module, doctype, owner, flag, value):
    b = hash_boundary
    source = select(b, module, owner, flag)
    getattr(b, owner).custom_pih = value
    root = ET.Element("Invoice")
    with pytest.raises(ValidationError) as error:
        module.additional_reference(root, "TC", source)
    assert str(error.value) == MISSING_PREVIOUS_HASH and len(root) == 0
    assert getattr(b, owner).custom_pih == value
    assert_no_writes(b)


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("owner,flag", [("company", 0), ("device", "0"), ("linked", "1")])
def test_preserve_exact_hash_even_when_other_owners_are_empty(hash_boundary, module, doctype, owner, flag):
    b = hash_boundary
    source = select(b, module, owner, flag)
    for other in ("company", "device", "linked"):
        getattr(b, other).custom_pih = None
    holder = getattr(b, owner)
    holder.custom_pih = " \n" + synthetic_hash("configured-start-or-tail") + "\n"
    root = module.additional_reference(ET.Element("Invoice"), "TC", source)
    assert embedded_hash(root) == holder.custom_pih
    assert_no_writes(b)


@pytest.mark.parametrize("module,doctype", ADAPTERS)
def test_caller_cannot_redirect_saved_source_hash(hash_boundary, module, doctype):
    b = hash_boundary
    saved = select(b, module, "company")
    forged = Document(doctype=doctype, name=saved.name, company="B", custom_zatca_pos_name="DEVICE")
    root = module.additional_reference(ET.Element("Invoice"), "TC", forged)
    assert embedded_hash(root) == b.company.custom_pih
    assert_no_writes(b)


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("fault", ["invoice_company", "taxpayer", "link_flag", "missing_link"])
def test_invalid_saved_settings_fail_before_xml_append(hash_boundary, module, doctype, fault):
    b = hash_boundary
    source = select(b, module, "linked", "1")
    if fault == "invoice_company":
        source.company = "B"
    elif fault == "taxpayer":
        b.linked.tax_id = "OTHER-SYNTHETIC-VAT"
    elif fault == "link_flag":
        b.device.custom__use_company_certificate__keys = "true"
    else:
        b.device.custom_linked_doctype = ""
    root = ET.Element("Invoice")
    with pytest.raises(ValidationError):
        module.additional_reference(root, "TC", source)
    assert len(root) == 0
    assert_no_writes(b)


def test_missing_pih_has_arabic_display_translation(hash_boundary, monkeypatch):
    catalog = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with catalog.open() as stream:
        translations = {row[0]: row[1] for row in csv.reader(stream) if len(row) >= 2}
    translated = translations[MISSING_PREVIOUS_HASH]
    assert translated != MISSING_PREVIOUS_HASH
    monkeypatch.setattr(credential_settings, "_", lambda message: translations.get(message, message))
    hash_boundary.company.custom_pih = None
    with pytest.raises(ValidationError) as error:
        createxml.additional_reference(ET.Element("Invoice"), "TC", hash_boundary.sales)
    assert str(error.value) == translated and error.value.__context__ is None
    assert_no_writes(hash_boundary)


def test_reference_fragments_keep_legacy_order_and_attributes():
    root = append_additional_references(ET.Element("Invoice"), "SYNTHETIC<&>HASH")
    assert embedded_hash(root) == "SYNTHETIC<&>HASH"
    assert b"SYNTHETIC&lt;&amp;&gt;HASH" in ET.tostring(root)
    refs = root.findall("cac:AdditionalDocumentReference")
    objects = [ref.find("cac:Attachment").find("cbc:EmbeddedDocumentBinaryObject") for ref in refs]
    assert [value.attrib for value in objects] == [{"mimeCode": "text/plain"}] * 2
    assert objects[1].text == QR_PLACEHOLDER
    assert root.find("cac:Signature").find("cbc:ID").text == "urn:oasis:names:specification:ubl:signature:Invoice"
    assert root.find("cac:Signature").find("cbc:SignatureMethod").text == "urn:oasis:names:specification:ubl:dsig:enveloped:xades"


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("purpose", ["production", "debug", "compliance"])
@pytest.mark.parametrize("is_pos", [0, 1])
def test_metadata_adapters_have_identical_element_order(isolated, monkeypatch, module, doctype, purpose, is_pos):
    doc, _, _, runtime, _ = isolated
    doc.doctype, doc.is_pos, doc.custom_uuid = doctype, is_pos, FIXED_UUID
    if purpose == "production":
        if module is createxml:
            monkeypatch.setattr(module, "_get_or_create_sales_invoice_uuid", lambda source: FIXED_UUID)
        else:
            monkeypatch.setattr(module.uuid, "uuid1", lambda: FIXED_UUID)
    else:
        monkeypatch.setattr(module, "preview_invoice_uuid", lambda value, mode: FIXED_UUID)
    root, value, returned = module.salesinvoice_data(ET.Element("Invoice"), doc.name, purpose=purpose)
    assert value == FIXED_UUID and returned is doc
    assert [(child.tag, child.text) for child in root] == [
        ("cbc:ProfileID", "reporting:1.0"), ("cbc:ID", doc.name), ("cbc:UUID", FIXED_UUID),
        ("cbc:IssueDate", "2026-10-09"), ("cbc:IssueTime", "09:05:42Z"),
    ]
    doc.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("module,doctype", ADAPTERS)
def test_invalid_purpose_fails_without_partial_metadata(isolated, module, doctype):
    doc, _, _, _, _ = isolated
    doc.doctype, doc.custom_uuid = doctype, None
    root = ET.Element("Invoice")
    with pytest.raises(ValidationError, match="Unsupported non-production"):
        module.salesinvoice_data(root, doc.name, purpose="typo")
    assert len(root) == 0
    doc.db_set.assert_not_called()


def test_metadata_exact_legacy_bytes():
    root = append_invoice_metadata(ET.Element("Invoice"), "SYNTHETIC<&>", FIXED_UUID, "2026-10-09T09:05:42Z")
    assert ET.tostring(root) == (
        b'<Invoice><cbc:ProfileID>reporting:1.0</cbc:ProfileID><cbc:ID>SYNTHETIC&lt;&amp;&gt;</cbc:ID>'
        b'<cbc:UUID>b05809d9-7851-4767-b7e9-47af44c80cb9</cbc:UUID>'
        b'<cbc:IssueDate>2026-10-09</cbc:IssueDate><cbc:IssueTime>09:05:42Z</cbc:IssueTime></Invoice>'
    )


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("code", list(COMPLIANCE_TYPES.values()))
@pytest.mark.parametrize("shape", ["string", "integer", "padded"])
def test_all_sample_types_share_exact_contract(hash_boundary, module, doctype, code, shape):
    value = int(code) if shape == "integer" else " " + code + " " if shape == "padded" else code
    expected = EXPECTED_TYPES[int(code) - 1]
    spec = compliance_document_type(value)
    assert (spec.type_name, spec.document_code, spec.simplified, spec.is_note) == expected
    root = module.invoice_typecode_compliance(ET.Element("Invoice"), value)
    assert len(root) == 1 and root[0].tag == "cbc:InvoiceTypeCode"
    assert root[0].attrib == {"name": expected[0]} and root[0].text == expected[1]
    assert_no_writes(hash_boundary)


@pytest.mark.parametrize("value", [None, False, True, 0, "0", "", "7", 1.0, [], {}])
def test_invalid_sample_selector_has_no_partial_xml(value):
    root = ET.Element("Invoice")
    with pytest.raises(ValueError, match="Select a valid"):
        append_compliance_type(root, value)
    assert len(root) == 0


@pytest.mark.parametrize("label", list(COMPLIANCE_TYPES))
def test_automatic_onboarding_uses_same_sample_spec(isolated, monkeypatch, label):
    from lxml import etree

    _, company, _, runtime, _ = isolated
    company.tax_id = "300000000000003"
    monkeypatch.setattr(sign_invoice, "_onboarding_address", lambda name: Document(
        address_line1="SYNTHETIC-ROAD", address_line2="DISTRICT", city="Riyadh",
        pincode="12345", state="", custom_building_number="1234"))
    _, content = sign_invoice._build_onboarding_invoice_xml(company, label,
        issue_instant=datetime(2026, 9, 27, 9, 5, 42, tzinfo=timezone.utc))
    root = etree.fromstring(content.encode())
    element = root.find("cbc:InvoiceTypeCode", sign_invoice._ONBOARDING_UBL)
    expected = EXPECTED_TYPES[int(COMPLIANCE_TYPES[label]) - 1]
    assert element.attrib == {"name": expected[0]} and element.text == expected[1]
    assert bool(root.find("cac:BillingReference", sign_invoice._ONBOARDING_UBL) is not None) == expected[3]
    company.db_set.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("label", list(COMPLIANCE_TYPES))
@pytest.mark.parametrize("saved_pih", [None, "", synthetic_hash("existing-owner-tail")])
def test_sample_seed_fallback_is_published_and_never_writes_company(isolated, monkeypatch, label, saved_pih):
    from lxml import etree

    _, company, _, runtime, _ = isolated
    company.tax_id, company.custom_pih = "300000000000003", saved_pih
    monkeypatch.setattr(sign_invoice, "_onboarding_address", lambda name: Document(
        address_line1="SYNTHETIC-ROAD", address_line2="DISTRICT", city="Riyadh",
        pincode="12345", state="", custom_building_number="1234"))
    _, content = sign_invoice._build_onboarding_invoice_xml(company, label,
        issue_instant=datetime(2026, 9, 27, 9, 5, 42, tzinfo=timezone.utc))
    root = etree.fromstring(content.encode())
    found = root.xpath("string(cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject)",
                       namespaces=sign_invoice._ONBOARDING_UBL)
    assert found == (saved_pih or INITIAL_PREVIOUS_HASH)
    assert company.custom_pih == saved_pih
    company.db_set.assert_not_called()
    runtime.db.set_value.assert_not_called()
    runtime.db.commit.assert_not_called()


@pytest.mark.parametrize("value,expected", [
    (None, False), (False, False), (0, False), ("", False), (" \n", False),
    ("NOT SUBMITTED", False), ("not submitted.\n", False), ("None", False),
    ("null", False), ("FALSE", False), ("0", False), (FIXED_UUID, True),
    (" " + FIXED_UUID + " ", True), ("legacy-non-UUID-identity", True),
])
def test_shared_identity_filter_preserves_legacy_retry_semantics(value, expected):
    assert createxml._is_valid_zatca_uuid_value is has_legacy_uuid_value
    assert sign_invoice._is_valid_zatca_uuid_value is has_legacy_uuid_value
    assert has_legacy_uuid_value(value) is expected


@pytest.mark.parametrize("module,doctype", ADAPTERS)
@pytest.mark.parametrize("value", [None, False, "0", "7"])
def test_public_sample_adapter_rejects_invalid_selector(hash_boundary, module, doctype, value):
    root = ET.Element("Invoice")
    with pytest.raises(ValidationError, match="Select a valid"):
        module.invoice_typecode_compliance(root, value)
    assert len(root) == 0
    assert_no_writes(hash_boundary)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("purpose", ["Production", "Compliance", "Debug"])
def test_first_counter_characterization_without_pih_initialization(isolated, doctype, purpose):
    doc, company, _, runtime, _ = isolated
    doc.doctype, doc.custom_zatca_icv = doctype, None
    company.custom_pih = before = synthetic_hash("configured-start")
    runtime.db.sql.return_value = [SimpleNamespace(last_issued_icv=0)]
    runtime.db.get_value.return_value = None
    assert icv.get_icv(doc, purpose) == "1" and company.custom_pih == before
    company.db_set.assert_not_called()
    if purpose == "Debug":
        icv._get_or_create_counter.assert_not_called()
        runtime.db.set_value.assert_not_called()
        doc.db_set.assert_not_called()
    elif purpose == "Compliance":
        icv._get_or_create_counter.assert_called_once_with(doc.company, "test-unit", "Compliance")
        doc.db_set.assert_not_called()
    else:
        assert doc.db_set.call_args_list[0].args == ("custom_zatca_icv", 1)
