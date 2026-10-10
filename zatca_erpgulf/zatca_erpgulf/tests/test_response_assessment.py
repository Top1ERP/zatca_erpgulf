"""Synthetic HTTP/identity observations, deliberately not valid ZATCA signatures."""

import base64
import hashlib
import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

from lxml import etree
import frappe
import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import response_assessment as assessment
from zatca_erpgulf.zatca_erpgulf import response_json
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError, NS
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal, append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import OTHER_UUID, node, xml_bytes
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates, cert_node, signature
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event, start
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope


@pytest.fixture(scope="module")
def prepared(certificates):
    return candidate(certificates[0])


def body(prepared, **changes):
    values = {
        "validationResults": {"status": "PASS", "errorMessages": [], "warningMessages": [], "infoMessages": []},
        "reportingStatus": "REPORTED" if prepared.context.route.endpoint == assessment.REPORTING else None,
        "clearanceStatus": "CLEARED" if prepared.context.route.endpoint == assessment.CLEARANCE else None,
    }
    if prepared.context.route.endpoint == assessment.CLEARANCE:
        values["clearedInvoice"] = base64.b64encode(prepared.xml_bytes).decode()
    values.update(changes)
    return values


def assess(prepared, *, status=200, response=None, raw=None, late=False):
    journal = start(prepared)
    if late:
        journal = append_dispatch_event(journal, event(prepared, "TRANSPORT_UNKNOWN", 2))
    raw = json.dumps(response if response is not None else body(prepared)).encode() if raw is None else raw
    receipt = event(prepared, "HTTP_RESPONSE", 3 if late else 2, http_status=status, response_bytes=raw)
    return assessment.ResponseAssessment(append_dispatch_event(journal, receipt))


def no_authority(result):
    report = result.diagnostic_projection()
    for flag in ("remote_acceptance_verified", "network_provenance_verified", "signature_verified",
                 "invoice_hash_verified", "business_data_verified", "persistence_verified",
                 "dispatch_authorized", "replay_authorized"):
        assert report[flag] is False


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("code", ["388", "381", "383", "386"])
@pytest.mark.parametrize("status", [200, 202])
def test_expected_endpoint_contract_is_consistent_for_all_candidate_types(certificates, environment, doctype, indicator, code, status):
    prepared = candidate(certificates[0], selected_scope=scope(environment=environment, doctype=doctype), indicator=indicator, code=code)
    result = assess(prepared, status=status)
    expected = "REPORTING_ACCEPTANCE_MATCHED" if indicator.startswith("02") else "CLEARANCE_ACCEPTANCE_MATCHED"
    assert result.outcome == expected
    assert result.issues == ()
    assert result.has_warnings is (status == 202)
    assert result.warning_count == 0
    assert result.journal.candidate is prepared
    no_authority(result)


@pytest.mark.parametrize("validation_status", ["PASS", "WARNING"])
@pytest.mark.parametrize("http_status", [200, 202])
def test_warnings_preserved_without_copying_raw_messages(prepared, validation_status, http_status):
    response = body(prepared)
    response["validationResults"].update(status=validation_status, warningMessages=[{
        "type": "WARNING", "status": "WARNING", "code": "WARN", "message": "PRIVATE-BODY",
    }])
    result = assess(prepared, status=http_status, response=response)
    assert result.outcome == "REPORTING_ACCEPTANCE_MATCHED"
    assert result.has_warnings and result.warning_count == 1
    assert b"PRIVATE-BODY" in result.journal.events[-1].response_bytes
    assert "PRIVATE-BODY" not in repr(result)
    assert "PRIVATE-BODY" not in json.dumps(result.diagnostic_projection())
    no_authority(result)


@pytest.mark.parametrize("status,outcome", [
    (201, "UNCONFIRMED"), (204, "UNCONFIRMED"), (302, "UNCONFIRMED"), (303, "UNCONFIRMED"),
    (400, "HTTP_REJECTION_OBSERVED"), (401, "AUTHORIZATION_FAILED"), (403, "AUTHORIZATION_FAILED"),
    (406, "UNCONFIRMED"), (409, "DUPLICATE_UNCONFIRMED"), (413, "UNCONFIRMED"),
    (429, "UNCONFIRMED"), (500, "HTTP_FAILURE_OBSERVED"), (503, "HTTP_FAILURE_OBSERVED"),
    (504, "HTTP_FAILURE_OBSERVED"), (599, "HTTP_FAILURE_OBSERVED"),
])
def test_wrong_http_status_cannot_promote_success_shaped_body(prepared, status, outcome):
    result = assess(prepared, status=status)
    assert result.outcome == outcome
    assert "response_http_outcome_conflict" in result.issues
    assert result.returned_xml is None
    no_authority(result)


@pytest.mark.parametrize("status", [200, 202, 400, 401, 403, 409, 503])
@pytest.mark.parametrize("raw,issue", [
    (b"", "response_size"), (b"<html>PRIVATE-BODY</html>", "response_json"),
    (b"\xff", "response_encoding"), (b"[]", "response_object"), (b"{}{}", "response_trailing_data"),
    (b'ZATCA Response: {}', "response_json"), (b'{}<br>', "response_trailing_data"),
    (b'{"a":1,"a":2}', "response_duplicate_key"), (b'{"a":NaN}', "response_number"),
])
def test_malformed_body_is_not_repaired_into_acceptance(prepared, status, raw, issue):
    result = assess(prepared, status=status, raw=raw)
    assert issue in result.issues
    assert not result.outcome.endswith("ACCEPTANCE_MATCHED")
    no_authority(result)


@pytest.mark.parametrize("changes,issue", [
    ({"validationResults": None}, "response_validation_missing"),
    ({"validationResults": []}, "response_validation_missing"),
    ({"validationResults": {"status": "PASS"}}, "response_validation_messages"),
    ({"validationResults": {"status": "ERROR", "errorMessages": []}}, "response_validation_contradiction"),
    ({"validationResults": {"status": "PASS", "errorMessages": [{}]}}, "response_validation_contradiction"),
    ({"validationResults": {"status": "OTHER", "errorMessages": []}}, "response_validation_status"),
    ({"validationResults": {"status": ["PASS"], "errorMessages": []}}, "response_validation_status"),
    ({"validationResults": {"status": "PASS", "errorMessages": [], "warningMessages": "bad"}}, "response_validation_messages"),
    ({"validationResults": {"status": "PASS", "errorMessages": [], "infoMessages": [None]}}, "response_validation_messages"),
    ({"validationResults": {"status": "PASS", "errorMessages": [], "warningMessages": [{"type": "ERROR"}]}}, "response_validation_messages"),
    ({"validationResults": {"status": "PASS", "errorMessages": [], "infoMessages": [{"status": "ERROR"}]}}, "response_validation_messages"),
    ({"validationResults": {"status": "PASS", "errorMessages": [], "warningMessages": [{"message": {"secret": "PRIVATE"}}]}}, "response_validation_messages"),
    ({"reportingStatus": None}, "response_acceptance_missing"),
    ({"reportingStatus": "NOT_REPORTED"}, "response_acceptance_missing"),
    ({"reportingStatus": "OTHER"}, "response_outcome_unknown"),
    ({"reportingStatus": []}, "response_outcome_unknown"),
    ({"clearanceStatus": "CLEARED"}, "response_outcome_ambiguous"),
    ({"clearanceStatus": "NOT_CLEARED"}, "response_operation_mismatch"),
    ({"clearedInvoice": "PRIVATE"}, "response_xml_operation_mismatch"),
    ({"invoiceHash": "OTHER"}, "response_invoice_hash_mismatch"),
    ({"invoiceHash": None}, "response_invoice_hash_mismatch"),
])
def test_success_http_requires_coherent_validation_operation_and_optional_hash(prepared, changes, issue):
    result = assess(prepared, response=body(prepared, **changes))
    assert result.outcome == "UNCONFIRMED" and issue in result.issues
    assert result.returned_xml is None


def test_reporting_needs_no_returned_xml_and_matching_optional_invoice_hash(prepared):
    result = assess(prepared, response=body(prepared, invoiceHash=prepared.artifact.invoice_digest))
    assert result.outcome == "REPORTING_ACCEPTANCE_MATCHED"
    assert result.returned_xml is result.returned_xml_sha256 is None


@pytest.mark.parametrize("status", [200, 202, 400, 401, 409, 503])
def test_fatal_validation_is_rejection_only_with_matching_http_400(prepared, status):
    response = body(prepared, reportingStatus="NOT_REPORTED", validationResults={
        "status": "ERROR", "errorMessages": [{"type": "ERROR", "status": "ERROR", "code": "REJECT", "message": "PRIVATE-REJECTION"}],
    })
    result = assess(prepared, status=status, response=response)
    assert (result.outcome == "VALIDATION_REJECTION_MATCHED") is (status == 400)
    assert not result.outcome.endswith("ACCEPTANCE_MATCHED")
    assert result.returned_xml is None
    assert "PRIVATE-REJECTION" not in json.dumps(result.diagnostic_projection())
    no_authority(result)


def test_303_is_a_separate_clearance_transition_not_a_reporting_send(certificates):
    prepared = candidate(certificates[0], indicator="0100000")
    result = assess(prepared, status=303, raw=b"")
    assert result.outcome == "CLEARANCE_DISABLED_OBSERVED"
    assert result.journal.candidate.context.route.endpoint == assessment.CLEARANCE
    no_authority(result)


@pytest.mark.parametrize("changes,issue", [
    ({"reportingStatus": "REPORTED"}, "response_outcome_ambiguous"),
    ({"reportingStatus": "NOT_REPORTED"}, "response_operation_mismatch"),
    ({"reportedInvoice": "PRIVATE"}, "response_xml_operation_mismatch"),
    ({"clearanceStatus": "NOT_CLEARED"}, "response_acceptance_missing"),
])
def test_clearance_response_cannot_masquerade_as_reporting(certificates, changes, issue):
    prepared = candidate(certificates[0], indicator="0100000")
    result = assess(prepared, response=body(prepared, **changes))
    assert result.outcome == "UNCONFIRMED" and issue in result.issues
    assert result.returned_xml is None


def test_wrong_operation_rejection_remains_unconfirmed(prepared):
    response = body(prepared, reportingStatus=None, clearanceStatus="NOT_CLEARED", validationResults={
        "status": "ERROR", "errorMessages": [{"code": "REJECT"}],
    })
    result = assess(prepared, status=400, response=response)
    assert result.outcome == "HTTP_REJECTION_OBSERVED"
    assert "response_operation_mismatch" in result.issues
    no_authority(result)


@pytest.mark.parametrize("value,issue", [
    (None, "response_xml_type"), ("", "response_xml_type"), ([], "response_xml_type"),
    ("???", "response_xml_base64"), ("\u00a0YWJj", "response_xml_base64"),
    (base64.b64encode(b"bad XML").decode(), "xml_syntax"),
    (base64.b64encode(b"<!DOCTYPE Invoice><Invoice/>").decode(), "xml_doctype"),
    (base64.b64encode(b"<PRIVATE/>").decode(), "xml_root"),
])
def test_clearance_requires_safe_returned_xml(certificates, value, issue):
    prepared = candidate(certificates[0], indicator="0100000")
    result = assess(prepared, response=body(prepared, clearedInvoice=value))
    assert result.outcome == "UNCONFIRMED" and issue in result.issues
    assert result.returned_xml is None


@pytest.mark.parametrize("attribute,value,issue", [
    ("./cbc:ID", "OTHER", "response_xml_invoice_id_mismatch"),
    ("./cbc:UUID", OTHER_UUID, "response_xml_uuid_mismatch"),
    ("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", "78", "response_xml_icv_mismatch"),
    ("./cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID", "OTHER", "response_xml_seller_tax_id_mismatch"),
    (".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", base64.b64encode(b"x" * 32).decode(), "response_xml_invoice_digest_mismatch"),
    ("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", base64.b64encode(b"OTHER").decode(), "response_xml_previous_hash_mismatch"),
    ("./cbc:InvoiceTypeCode", "381", "response_xml_type_mismatch"),
])
@pytest.mark.parametrize("indicator,xml_field", [("0100000", "clearedInvoice"), ("0200000", "reportedInvoice")])
def test_wrong_invoice_xml_cannot_match_receipt(certificates, attribute, value, issue, indicator, xml_field):
    prepared = candidate(certificates[0], indicator=indicator)
    root = etree.fromstring(prepared.xml_bytes)
    root.xpath(attribute, namespaces=NS)[0].text = value
    returned = base64.b64encode(xml_bytes(root)).decode()
    result = assess(prepared, response=body(prepared, **{xml_field: returned}))
    assert result.outcome == "UNCONFIRMED" and issue in result.issues
    assert result.returned_xml is None


def test_returned_xml_type_indicator_and_ambiguous_identity_are_rejected(certificates):
    prepared = candidate(certificates[0], indicator="0100000")
    root = etree.fromstring(prepared.xml_bytes)
    root.find("cbc:InvoiceTypeCode", namespaces=NS).set("name", "0200000")
    result = assess(prepared, response=body(prepared, clearedInvoice=base64.b64encode(xml_bytes(root)).decode()))
    assert "response_xml_type_mismatch" in result.issues
    node(root, "cbc", "UUID", OTHER_UUID)
    result = assess(prepared, response=body(prepared, clearedInvoice=base64.b64encode(xml_bytes(root)).decode()))
    assert "invoice_uuid" in result.issues


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16", "UTF-16LE"])
def test_clearance_may_change_signature_qr_certificate_and_serialization(certificates, encoding):
    prepared = candidate(certificates[0], indicator="0100000")
    root = etree.fromstring(prepared.xml_bytes)
    cert_node(root).text = base64.b64encode(certificates[2]).decode()
    signature(root).find("ds:SignatureValue", namespaces=NS).text = "DIFFERENT-INVALID-SIGNATURE"
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces=NS)[0].text = "DIFFERENT-QR"
    returned = etree.tostring(root, encoding=encoding, xml_declaration=True, pretty_print=True)
    encoded = base64.b64encode(returned).decode()
    response = body(prepared, clearedInvoice=" \n" + "\r\n".join(encoded[i:i + 60] for i in range(0, len(encoded), 60)))
    result = assess(prepared, response=response)
    assert result.outcome == "CLEARANCE_ACCEPTANCE_MATCHED"
    assert result.returned_xml == returned and returned != prepared.xml_bytes
    assert result.returned_xml_sha256 == hashlib.sha256(returned).hexdigest()
    assert result.journal.candidate is prepared
    no_authority(result)


def test_metadata_match_is_explicitly_not_business_data_or_signature_proof(certificates):
    prepared = candidate(certificates[0], indicator="0100000")
    root = etree.fromstring(prepared.xml_bytes)
    node(node(root, "cac", "LegalMonetaryTotal"), "cbc", "PayableAmount", "999999.99", currencyID="SAR")
    result = assess(prepared, response=body(prepared, clearedInvoice=base64.b64encode(xml_bytes(root)).decode()))
    assert result.outcome == "CLEARANCE_ACCEPTANCE_MATCHED"
    no_authority(result)  # Declared digests are NOT recomputed by this contract.


def test_late_receipt_is_classified_without_erasing_timeout_or_identity(prepared):
    result = assess(prepared, late=True)
    assert result.outcome == "REPORTING_ACCEPTANCE_MATCHED"
    assert [entry.kind for entry in result.journal.events] == ["ATTEMPT_STARTED", "TRANSPORT_UNKNOWN", "HTTP_RESPONSE"]
    assert result.journal.candidate is prepared
    no_authority(result)


@pytest.mark.parametrize("stage", ["empty", "started", "unknown"])
def test_no_receipt_never_creates_success_or_retry_authority(prepared, stage):
    journal = DispatchJournal(prepared) if stage == "empty" else start(prepared)
    if stage == "unknown":
        journal = append_dispatch_event(journal, event(prepared, "TRANSPORT_UNKNOWN", 2))
    result = assessment.ResponseAssessment(journal)
    assert result.outcome == ("TRANSPORT_UNKNOWN" if stage == "unknown" else "NO_RESPONSE")
    assert result.returned_xml is None
    no_authority(result)


@pytest.mark.parametrize("attribute", ["journal", "outcome", "issues", "has_warnings", "warning_count", "returned_xml", "assessment_sha256"])
def test_derived_assessment_is_frozen(prepared, attribute):
    result = assess(prepared)
    with pytest.raises(FrozenInstanceError):
        setattr(result, attribute, None)


@pytest.mark.parametrize("invalid", [None, {}, [], "CLEARED", object()])
def test_no_plain_receipt_or_saved_status_as_acceptance_authority(invalid):
    with pytest.raises(assessment.ResponseAssessmentError, match="^assessment_journal$"):
        assessment.ResponseAssessment(invalid)


def test_fingerprints_and_safe_projection_are_deterministic(prepared):
    first, second = assess(prepared), assess(prepared)
    assert first.assessment_sha256 == second.assessment_sha256
    assert first.assessment_sha256 != assess(prepared, status=202).assessment_sha256
    projection = first.diagnostic_projection()
    projection["issues"].append("caller change")
    assert first.issues == ()
    assert "gateway.invalid" not in repr(first)
    assert "PRIVATE-DN" not in repr(first)
    assert "xml_bytes" not in json.dumps(first.diagnostic_projection())


def test_assessment_does_not_access_http_files_database_or_change_metadata(prepared, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Pure response classification attempted external access")

    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(frappe, "get_doc", forbidden)
    monkeypatch.setattr(frappe, "get_all", forbidden)
    monkeypatch.setattr(frappe, "db", SimpleNamespace(**{
        name: forbidden for name in ("get_value", "set_value", "sql", "commit", "rollback", "exists")
    }))
    monkeypatch.setattr("builtins.open", forbidden)
    before = prepared.diagnostic_projection()
    result = assess(prepared)
    assert result.outcome == "REPORTING_ACCEPTANCE_MATCHED"
    assert prepared.diagnostic_projection() == before


@pytest.mark.parametrize("content,issue", [
    ("{}", "response_bytes_required"), (bytearray(b"{}"), "response_bytes_required"),
    (b"null", "response_object"), (b"42", "response_object"),
    (b'"PRIVATE"', "response_object"), (b"\xef\xbb\xbf{}", "response_json"),
    (b'{}\xc2\xa0', "response_trailing_data"), (b'\xc2\xa0{}', "response_json"),
    (b'{"a":{"b":1,"b":2}}', "response_duplicate_key"),
    (b'{"a":Infinity}', "response_number"), (b'{"a":-Infinity}', "response_number"),
    (b'{"a":1e999}', "response_number"),
    (b'{"a":' + b"1" * 65 + b"}", "response_number"),
    (b'{"a":0.' + b"1" * 65 + b"}", "response_number"),
    (b"[" * 1500 + b"0" + b"]" * 1500, "response_json"),
])
def test_shared_wire_decoder_rejects_wrappers_duplicates_and_unsafe_numbers(content, issue):
    with pytest.raises(ArtifactEvidenceError) as error:
        response_json.parse_wire_response(content)
    assert error.value.code == issue


@pytest.mark.parametrize("spacing", [b" ", b"\r\n", b"\t", b" \t\r\n"])
def test_wire_decoder_allows_only_json_outer_spacing(spacing):
    assert response_json.parse_wire_response(spacing + b'{"a":1.5,"b":42}' + spacing) == {"a": 1.5, "b": 42}


def test_response_and_returned_xml_size_bounds(prepared, monkeypatch):
    monkeypatch.setattr(response_json, "MAX_RESPONSE_BYTES", 2)
    with pytest.raises(ArtifactEvidenceError, match="^response_size$"):
        response_json.parse_wire_response(b" {}")
    assert response_json.parse_wire_response(b"{}") == {}
    monkeypatch.setattr(response_json, "MAX_RESPONSE_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(assessment, "MAX_XML_BYTES", 3)
    response = body(prepared, reportedInvoice=base64.b64encode(b"abcd").decode())
    assert "response_xml_size" in assess(prepared, response=response).issues


def test_decoded_xml_bound_is_checked_even_with_permitted_base64_length(prepared, monkeypatch):
    monkeypatch.setattr(assessment, "MAX_XML_BYTES", 2)
    response = body(prepared, reportedInvoice=base64.b64encode(b"abc").decode())
    assert "response_xml_size" in assess(prepared, response=response).issues
