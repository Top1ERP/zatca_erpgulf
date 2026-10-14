"""Supplied synthetic journals/XML, no authentic signatures or remote outcomes."""

import base64
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import pickle

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import qr_source_selection as selection
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError, NS
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import OTHER_UUID, node, xml_bytes
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import start
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope
from zatca_erpgulf.zatca_erpgulf.tests.test_response_assessment import assess, body


ORIGINAL = base64.b64encode(b"PRIVATE-ORIGINAL-QR: synthetic bytes, NOT valid ZATCA TLV").decode()
RETURNED = base64.b64encode(b"PRIVATE-RETURNED-QR: synthetic bytes, NOT valid ZATCA TLV").decode()
QR_PATH = "./cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject"


def prepared_qr(der, *, indicator="0200000", doctype="Sales Invoice", environment="Production", code="388"):
    original = candidate(der, selected_scope=scope(doctype=doctype, environment=environment), indicator=indicator, code=code)
    root = etree.fromstring(original.xml_bytes)
    node(root, "cbc", "IssueDate", "2026-09-27")
    node(root, "cbc", "IssueTime", "00:05:42+03:00")
    root.find(QR_PATH, NS).text = ORIGINAL
    return replace(original, xml_bytes=xml_bytes(root))


@pytest.fixture(scope="module")
def prepared(certificates):
    return prepared_qr(certificates[0])


def changed_return(prepared, *, payload=RETURNED):
    root = etree.fromstring(prepared.xml_bytes)
    root.find(QR_PATH, NS).text = payload
    return xml_bytes(root)


def receipt(prepared, *, returned=None, status=200):
    field = "clearedInvoice" if prepared.invoice_type_indicator.startswith("01") else "reportedInvoice"
    response = body(prepared, **({field: base64.b64encode(returned).decode()} if returned is not None else {}))
    return assess(prepared, status=status, response=response).journal


def select(observed_journal, **changes):
    values = dict(journal=observed_journal, expected_context=observed_journal.candidate.context,
        expected_uuid=observed_journal.candidate.artifact.uuid, expected_icv=observed_journal.candidate.artifact.icv,
        expected_journal_sha256=observed_journal.journal_sha256)
    values.update(changes)
    return selection.ArchivedQRSource(**values)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("code", ["388", "381", "383", "386"])
@pytest.mark.parametrize("status", [200, 202])
def test_exact_endpoint_source_selection_for_all_candidate_modes(certificates, environment, doctype, indicator, code, status):
    prepared = prepared_qr(certificates[0], environment=environment, doctype=doctype, indicator=indicator, code=code)
    returned = changed_return(prepared)
    result = select(receipt(prepared, returned=returned, status=status))
    clearance = indicator.startswith("01")
    assert result.source_kind == ("CLEARANCE_RETURNED_XML" if clearance else "REPORTING_REQUEST_XML")
    assert result.xml_bytes == (returned if clearance else prepared.xml_bytes)
    assert result.qr_payload == (RETURNED if clearance else ORIGINAL)
    assert (result.issue_date, result.issue_time) == ("2026-09-27", "00:05:42+03:00")
    assert result.xml_sha256 == hashlib.sha256(result.xml_bytes).hexdigest()
    assert result.qr_payload_sha256 == hashlib.sha256(result.qr_payload.encode()).hexdigest()
    assert result.decoded_qr_byte_length == len(base64.b64decode(result.qr_payload))
    assert result.has_warnings is (status == 202)
    report = result.diagnostic_projection()
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "PRIVATE" not in repr(result) and "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("key,value,code", [
    ("journal", None, "qr_source_binding"), ("expected_context", {}, "qr_source_binding"),
    ("expected_journal_sha256", "0" * 64, "qr_source_revision_mismatch"),
    ("expected_journal_sha256", "PRIVATE-INVALID", "qr_source_revision"),
    ("expected_uuid", OTHER_UUID, "qr_source_identity_mismatch"),
    ("expected_uuid", "PRIVATE-INVALID", "qr_source_uuid"),
    ("expected_icv", 1, "qr_source_identity_mismatch"), ("expected_icv", True, "qr_source_icv"),
    ("expected_icv", "77", "qr_source_icv"), ("expected_icv", 0, "qr_source_icv"),
])
def test_exact_expected_binding_required_and_errors_are_static(prepared, key, value, code):
    with pytest.raises(selection.QRSourceSelectionError) as error:
        select(receipt(prepared), **{key: value})
    assert str(error.value) == code and error.value.__context__ is None


def test_context_mismatch_cannot_switch_company_environment_epoch_or_source_revision(prepared):
    changed = replace(prepared.context, source_snapshot_sha256="0" * 64)
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_context_mismatch"):
        select(receipt(prepared), expected_context=changed)


@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("xpath,value", [
    ("./cbc:ID", "FOREIGN-INVOICE"), ("./cbc:UUID", OTHER_UUID),
    ("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", "78"),
    ("./cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", "399999999999993"),
    ("./cbc:InvoiceTypeCode", "383"),
    (".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", base64.b64encode(b"x" * 32).decode()),
])
def test_wrong_returned_identity_type_or_digest_never_yields_a_qr(certificates, indicator, xpath, value):
    original = prepared_qr(certificates[0], indicator=indicator)
    root = etree.fromstring(changed_return(original))
    root.xpath(xpath, namespaces=NS)[0].text = value
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_response_unconfirmed"):
        select(receipt(original, returned=xml_bytes(root)))


@pytest.mark.parametrize("http", [303, 400, 401, 403, 406, 409, 500])
def test_unconfirmed_http_observation_cannot_authorize_source(prepared, http):
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_response_unconfirmed"):
        select(receipt(prepared, status=http))


@pytest.mark.parametrize("state", ["no_attempt", "in_flight"])
def test_missing_receipt_is_not_repaired_by_qr_presence(prepared, state):
    journal = DispatchJournal(prepared) if state == "no_attempt" else start(prepared)
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_response_unconfirmed"):
        select(journal)


@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("field,value", [("IssueDate", "2026-09-28"), ("IssueTime", "21:05:42Z")])
def test_returned_clock_drift_is_not_normalized(certificates, indicator, field, value):
    original = prepared_qr(certificates[0], indicator=indicator)
    root = etree.fromstring(changed_return(original))
    root.find("cbc:" + field, NS).text = value
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_returned_clock_mismatch"):
        select(receipt(original, returned=xml_bytes(root)))


@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
def test_equivalent_instant_with_changed_lexical_clock_requires_review(certificates, indicator):
    original = prepared_qr(certificates[0], indicator=indicator)
    root = etree.fromstring(changed_return(original))
    root.find("cbc:IssueDate", NS).text = "2026-09-26"
    root.find("cbc:IssueTime", NS).text = "21:05:42Z"
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_returned_clock_mismatch"):
        select(receipt(original, returned=xml_bytes(root)))


@pytest.mark.parametrize("payload", ["", "not-base64", "AB==", " Zg==", "Zg==\n", "شركة", "A"])
def test_qr_payload_requires_nonempty_canonical_bounded_base64(prepared, payload):
    root = etree.fromstring(prepared.xml_bytes)
    root.find(QR_PATH, NS).text = payload
    with pytest.raises(selection.QRSourceSelectionError):
        selection._payload(xml_bytes(root))


@pytest.mark.parametrize("mutation", ["missing", "duplicate_reference", "duplicate_id", "duplicate_attachment",
    "duplicate_payload", "nested_payload", "wrong_namespace", "nested_reference"])
def test_no_first_nested_or_localname_fallback(prepared, mutation):
    root = etree.fromstring(prepared.xml_bytes)
    reference = root.find("./cac:AdditionalDocumentReference[cbc:ID='QR']", NS)
    payload = reference.find("cac:Attachment/cbc:EmbeddedDocumentBinaryObject", NS)
    if mutation == "missing":
        root.remove(reference)
    elif mutation == "duplicate_reference":
        root.append(deepcopy(reference))
    elif mutation == "duplicate_id":
        reference.append(deepcopy(reference.find("cbc:ID", NS)))
    elif mutation == "duplicate_attachment":
        reference.append(deepcopy(reference.find("cac:Attachment", NS)))
    elif mutation == "duplicate_payload":
        payload.getparent().append(deepcopy(payload))
    elif mutation == "nested_payload":
        node(payload, "cbc", "ID", "PRIVATE")
    elif mutation == "wrong_namespace":
        payload.tag = "{urn:untrusted}EmbeddedDocumentBinaryObject"
    else:
        root.remove(reference)
        node(root, "cac", "BillingReference").append(reference)
    with pytest.raises(selection.QRSourceSelectionError):
        selection._payload(xml_bytes(root))


def test_bounds_before_base64_decode_and_doctype_never_loads_resources(prepared, monkeypatch):
    monkeypatch.setattr(selection, "MAX_QR_BASE64_CHARS", 4)
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_payload"):
        selection._payload(prepared.xml_bytes)
    doctype = prepared.xml_bytes.replace(b"?>", b'?>\n<!DOCTYPE Invoice SYSTEM "file:///PRIVATE-NEVER-READ">', 1)
    with pytest.raises(ArtifactEvidenceError, match="xml_doctype"):
        selection._payload(doctype)


@pytest.mark.parametrize("field", ["IssueDate", "IssueTime"])
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "bad_value"])
def test_invalid_original_clock_stops_before_source_extraction(prepared, field, mutation):
    root = etree.fromstring(prepared.xml_bytes)
    element = root.find("cbc:" + field, NS)
    if mutation == "missing":
        root.remove(element)
    elif mutation == "duplicate":
        root.append(deepcopy(element))
    else:
        element.text = "PRIVATE-INVALID"
    original = replace(prepared, xml_bytes=xml_bytes(root))
    with pytest.raises(selection.QRSourceSelectionError) as error:
        select(receipt(original))
    assert "PRIVATE" not in str(error.value) and error.value.__context__ is None


def test_reporting_does_not_substitute_returned_qr_when_original_qr_is_missing(prepared):
    root = etree.fromstring(prepared.xml_bytes)
    root.find(QR_PATH, NS).text = ""
    original = replace(prepared, xml_bytes=xml_bytes(root))
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_payload"):
        select(receipt(original, returned=changed_return(prepared)))


def test_immutable_redacted_not_pickleable_and_never_enables_recovery(prepared):
    result = select(receipt(prepared))
    with pytest.raises(FrozenInstanceError):
        result.qr_payload = RETURNED
    with pytest.raises(selection.QRSourceSelectionError, match="qr_source_not_pickleable"):
        pickle.dumps(result)
    report = result.diagnostic_projection()
    report["recovery_authorized"] = True
    assert result.diagnostic_projection()["recovery_authorized"] is False
    assert result.xml_bytes is prepared.xml_bytes
    assert "TEST" not in repr(result) and result.qr_payload not in repr(result)
