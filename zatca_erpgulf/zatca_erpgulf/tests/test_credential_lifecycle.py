"""Legacy certificate lifecycle evidence on synthetic projections only."""

import base64
import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from zatca_erpgulf.zatca_erpgulf import credential_settings as adapter
from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.credential_lifecycle import inspect_legacy_credential_lifecycle
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialOwner
from zatca_erpgulf.zatca_erpgulf.credential_snapshot import CredentialSnapshotError, authentication_certificate_der
from zatca_erpgulf.zatca_erpgulf.api_routing import ApiConfigurationError
from zatca_erpgulf.zatca_erpgulf.operation_messages import (
    csid_creation_result, csid_request_rejection, CSIDRequestRejected,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import basic
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials, boundary, ValidationError


NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def pair(materials):
    """Two distinct certificates share one key, as in an onboarding transition."""
    old = materials[0]
    key = serialization.load_pem_private_key(old.pem.encode(), password=None)
    cert = (
        x509.CertificateBuilder().subject_name(old.cert.subject).issuer_name(old.cert.issuer)
        .public_key(key.public_key()).serial_number(987)
        .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2030, 1, 1))
        .sign(key, hashes.SHA256())
    )
    return old, type(old)(cert=cert, text=base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode(), pem=old.pem)


def declared(pair, kind="company", mode="different"):
    compliance, production = pair
    if mode == "same":
        production = compliance
    device = kind == "multiple_setting"
    values = {
        "custom_private_key": compliance.pem,
        "custom_basic_auth_from_csid": basic(compliance) if mode not in ("missing", "production_only") else "",
        "custom_final_auth_csid" if device else "custom_basic_auth_from_production":
            basic(production) if mode not in ("missing", "compliance_only") else "",
        "custom_certificate": production.text if mode in ("different", "same", "production_only") else compliance.text if mode == "compliance_only" else "",
    }
    if device:
        values["custom_certficate"] = compliance.text if mode in ("different", "same", "compliance_only") else ""
    return CredentialOwner("SOURCE", "ZATCA Multiple Setting" if device else "Company",
                           "SOURCE" if kind == "company" else "OWNER", kind, values)


def assess(owner, environment="Production", at=NOW, fields=None):
    return inspect_legacy_credential_lifecycle(
        owner, settings(environment), observed_at=at,
        certificate_fields=fields or adapter._certificate_fields_for_owner(owner),
    )


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("kind", ["company", "linked_company", "multiple_setting"])
@pytest.mark.parametrize("mode", ["different", "same", "missing", "compliance_only", "production_only"])
def test_all_environment_owner_lifecycle_states(pair, environment, kind, mode):
    report = assess(declared(pair, kind, mode), environment)
    assert report.environment == environment
    expected = "DIFFERENT_AUTH_CERTIFICATES" if mode == "different" else "SAME_AUTH_CERTIFICATE" if mode == "same" else "INCOMPLETE_TOKEN_EVIDENCE"
    assert report.certificate_relationship == expected
    assert [value.purpose for value in report.purposes] == ["compliance", "production"]
    for value in report.purposes:
        missing = mode == "missing" or (mode == "compliance_only" and value.purpose == "production") or (mode == "production_only" and value.purpose == "compliance")
        assert value.status == ("MISSING" if missing else "TOKEN_MATERIAL_LOCALLY_BOUND")
    if mode == "different":
        assert "PURPOSE_SEPARATION_REQUIRED" in report.review_codes
        if kind == "multiple_setting":
            assert report.legacy_selection_status == "CERTIFICATE_ALIAS_CONFLICT"
            assert report.purposes[0].matching_certificate_fields == ("custom_certficate",)
            assert report.purposes[1].matching_certificate_fields == ("custom_certificate",)
        else:
            assert "COMPLIANCE_CERTIFICATE_NOT_STORED" in report.review_codes
    assert report.diagnostic_projection()["migration_authorized"] is False


def test_alias_spelling_does_not_assign_certificate_purpose(pair):
    owner = declared(pair, "multiple_setting")
    owner.values["custom_certificate"], owner.values["custom_certficate"] = owner.values["custom_certficate"], owner.values["custom_certificate"]
    report = assess(owner)
    assert report.purposes[0].matching_certificate_fields == ("custom_certificate",)
    assert report.purposes[1].matching_certificate_fields == ("custom_certficate",)
    assert report.legacy_selection_status == "CERTIFICATE_ALIAS_CONFLICT"


def test_reonboarding_company_shared_field_can_match_compliance_not_production(pair):
    owner = declared(pair)
    owner.values["custom_certificate"] = pair[0].text
    report = assess(owner)
    assert "PRODUCTION_CERTIFICATE_NOT_STORED" in report.review_codes
    assert report.purposes[0].matching_certificate_fields == ("custom_certificate",)
    assert not report.purposes[1].matching_certificate_fields


def test_same_key_is_not_same_certificate_identity(pair):
    report = assess(declared(pair))
    compliance, production = report.purposes
    assert compliance.public_key_sha256 == production.public_key_sha256
    assert compliance.certificate_der_sha256 != production.certificate_der_sha256


def test_exact_stored_text_observed_without_digest_repair(pair):
    owner = declared(pair, "multiple_setting", "same")
    text = owner.values["custom_certificate"]
    owner.values["custom_certificate"] = "\n" + text + "\n"
    before = dict(owner.values)
    report = assess(owner)
    old, new = report.stored_certificates
    assert old.certificate_der_sha256 == new.certificate_der_sha256
    assert old.exact_text_sha256 != new.exact_text_sha256
    assert report.legacy_selection_status == "SELECTABLE_BY_LEGACY_POLICY"
    assert owner.values == before


@pytest.mark.parametrize("format", ["body", "der", "pem"])
def test_shared_auth_parser_formats_are_observations_not_migration_values(pair, format):
    owner = declared(pair)
    owner.values["custom_basic_auth_from_csid"] = basic(pair[0], format=format)
    report = assess(owner)
    assert report.purposes[0].certificate_der_sha256 == hashlib.sha256(pair[0].cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    assert "COMPLIANCE_CERTIFICATE_NOT_STORED" in report.review_codes
    assert not hasattr(report.purposes[0], "certificate_text")


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("value", [None, "", " "])
def test_absent_auth_has_no_fallback(pair, purpose, value):
    owner = declared(pair)
    field = "custom_basic_auth_from_csid" if purpose == "compliance" else "custom_basic_auth_from_production"
    owner.values[field] = value
    observations = {item.purpose: item for item in assess(owner).purposes}
    assert observations[purpose].status == "MISSING"
    assert observations[purpose].certificate_der_sha256 is None
    assert observations["production" if purpose == "compliance" else "compliance"].status == "TOKEN_MATERIAL_LOCALLY_BOUND"


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("value", ["PRIVATE invalid", [], 1, "a" * (512 * 1024 + 1)])
def test_bad_auth_is_bounded_static_and_does_not_hide_other_purpose(pair, purpose, value):
    owner = declared(pair)
    field = "custom_basic_auth_from_csid" if purpose == "compliance" else "custom_basic_auth_from_production"
    owner.values[field] = value
    report = assess(owner)
    observations = {item.purpose: item for item in report.purposes}
    assert observations[purpose].status == "REVIEW_REQUIRED"
    assert observations["production" if purpose == "compliance" else "compliance"].status == "TOKEN_MATERIAL_LOCALLY_BOUND"
    assert "PRIVATE" not in json.dumps(report.diagnostic_projection())


@pytest.mark.parametrize("value", [None, "", "PRIVATE invalid", [], "a" * (64 * 1024 + 1)])
def test_rotated_missing_or_malformed_key_does_not_erase_token_identity(pair, value):
    owner = declared(pair)
    owner.values["custom_private_key"] = value
    report = assess(owner)
    assert report.certificate_relationship == "DIFFERENT_AUTH_CERTIFICATES"
    assert all(item.status == "REVIEW_REQUIRED" and item.certificate_der_sha256 for item in report.purposes)


def test_wrong_private_key_requires_review(pair, materials):
    owner = declared(pair)
    owner.values["custom_private_key"] = materials[1].pem
    assert all(item.error_code == "snapshot_key_mismatch" for item in assess(owner).purposes)


@pytest.mark.parametrize("value", ["PRIVATE invalid", [], 1, "a" * (128 * 1024 + 1), " " * (128 * 1024 + 1)])
def test_invalid_saved_certificate_does_not_block_independent_token_observation(pair, value):
    owner = declared(pair)
    owner.values["custom_certificate"] = value
    report = assess(owner)
    assert report.legacy_selection_status == "INVALID_CERTIFICATE_FIELD"
    assert report.stored_certificates[0].status == "INVALID"
    assert all(item.status == "TOKEN_MATERIAL_LOCALLY_BOUND" for item in report.purposes)
    assert "PRIVATE" not in repr(report)


def test_unmatched_saved_certificate_is_not_discarded(pair, materials):
    owner = declared(pair)
    owner.values["custom_certificate"] = materials[1].text
    report = assess(owner)
    assert "UNMATCHED_STORED_CERTIFICATE" in report.review_codes
    assert all(not item.matching_certificate_fields for item in report.purposes)


@pytest.mark.parametrize("at", [datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2031, 1, 1, tzinfo=timezone.utc)])
def test_time_invalid_keeps_identity_but_never_claims_material_ready(pair, at):
    report = assess(declared(pair), at=at)
    assert all(item.error_code == "snapshot_certificate_time" for item in report.purposes)
    assert report.certificate_relationship == "DIFFERENT_AUTH_CERTIFICATES"


@pytest.mark.parametrize("at", [None, NOW.replace(tzinfo=None), "2026-10-10"])
def test_invalid_observation_time_is_static(pair, at):
    with pytest.raises(CredentialSnapshotError, match="^snapshot_utc_timestamp$"):
        assess(declared(pair), at=at)


@pytest.mark.parametrize("fields", [[], (), ("custom_private_key",), ("custom_certificate", "custom_certificate"), (None,)])
def test_unregistered_or_ambiguous_field_declarations_rejected(pair, fields):
    with pytest.raises(CredentialSnapshotError, match="^lifecycle_certificate_fields$"):
        inspect_legacy_credential_lifecycle(declared(pair), settings(), certificate_fields=fields, observed_at=NOW)


@pytest.mark.parametrize("change", [{"name": "OTHER"}, {"doctype": "User"}, {"values": None}, {"company_name": ""}])
def test_bad_owner_never_becomes_saved_provenance(pair, change):
    with pytest.raises(CredentialSnapshotError):
        assess(replace(declared(pair), **change))


@pytest.mark.parametrize("config", [None, {}, {"custom_select": "invalid"}, {"custom_select": "Production", "custom_production_url": "http://PRIVATE.invalid"}])
def test_invalid_settings_fail_without_secret_details(pair, config):
    with pytest.raises((CredentialSnapshotError, ApiConfigurationError)) as error:
        inspect_legacy_credential_lifecycle(declared(pair), config, certificate_fields=("custom_certificate",), observed_at=NOW)
    assert "PRIVATE" not in str(error.value)


def test_public_report_is_frozen_and_never_proves_external_authority(pair):
    owner = declared(pair)
    report = assess(owner)
    with pytest.raises(FrozenInstanceError):
        report.environment = "Sandbox"
    public = report.diagnostic_projection()
    assert all(value is False for name, value in public.items() if name.endswith(("_verified", "_authorized")))
    text = repr(report) + json.dumps(public)
    assert basic(pair[0]) not in text and basic(pair[1]) not in text
    assert pair[0].pem not in text and pair[0].text not in text and pair[1].text not in text
    before = report.diagnostic_projection()
    owner.values.clear()
    assert report.diagnostic_projection() == before
    public["purposes"][0]["status"] = "FORGED"
    assert report.diagnostic_projection() == before


def test_pure_lifecycle_has_no_external_access(pair, monkeypatch):
    owner = declared(pair)

    def forbidden(*args, **kwargs):
        pytest.fail("Lifecycle assessment attempted external access")

    monkeypatch.setattr(adapter.frappe, "get_doc", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    assert assess(owner).certificate_relationship == "DIFFERENT_AUTH_CERTIFICATES"


@pytest.mark.parametrize("source", [None, "company", "sales", "pos", "device"])
@pytest.mark.parametrize("linked", [False, True])
def test_internal_adapter_reuses_saved_source_and_aliases_without_writes(boundary, materials, source, linked):
    b = boundary
    b.company.custom_production_url = settings()["custom_production_url"]
    for doc, material in ((b.company, materials[0]), (b.linked, materials[1]), (b.device, materials[2])):
        doc.custom_basic_auth_from_csid = doc.custom_basic_auth_from_production = doc.custom_final_auth_csid = basic(material)
    b.device.custom__use_company_certificate__keys = int(linked)
    b.device.custom_linked_doctype = "B" if linked else "A"
    saved = getattr(b, source) if source else None
    injected = {"doctype": saved.doctype, "name": saved.name, "custom_private_key": "PRIVATE INJECTED"} if saved else None
    report = adapter.capture_credential_lifecycle_assessment("TC", injected, observed_at=NOW)
    expected = b.company if source in (None, "company") else b.linked if linked else b.device
    assert report.owner_name == expected.name
    assert report.certificate_relationship == "SAME_AUTH_CERTIFICATE"
    assert sum(call.args == ("Company", {"abbr": "TC"}) for call in b.frappe.get_doc.call_args_list) == 1
    b.frappe.db.commit.assert_not_called()
    b.request.assert_not_called()
    for doc in (b.company, b.linked, b.device):
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()


def test_inventory_does_not_relax_legacy_alias_conflict(boundary, materials):
    b = boundary
    b.company.custom_production_url = settings()["custom_production_url"]
    b.device.custom_basic_auth_from_csid = basic(materials[0])
    b.device.custom_final_auth_csid = basic(materials[2])
    b.device.custom_certficate = materials[0].text
    report = adapter.capture_credential_lifecycle_assessment("TC", b.device, observed_at=NOW)
    assert report.legacy_selection_status == "CERTIFICATE_ALIAS_CONFLICT"
    assert report.purposes[0].error_code == "snapshot_key_mismatch"
    with pytest.raises(ValidationError, match="different values"):
        adapter.get_signing_certificate("TC", b.device)
    with pytest.raises(ValidationError, match="different values"):
        adapter.capture_credential_snapshot("TC", b.device, "compliance/invoices", observed_at=NOW)


@pytest.mark.parametrize("at", [None, NOW.replace(tzinfo=None), "2026-10-10"])
def test_internal_adapter_rejects_bad_time_before_reading_saved_credentials(boundary, at):
    with pytest.raises(ValidationError, match="snapshot_utc_timestamp"):
        adapter.capture_credential_lifecycle_assessment("TC", boundary.company, observed_at=at)
    boundary.frappe.get_doc.assert_not_called()


def test_saved_company_projection_is_not_reloaded_during_source_rotation(boundary, materials):
    b = boundary
    b.company.custom_production_url = settings()["custom_production_url"]
    b.company.custom_basic_auth_from_csid = b.company.custom_basic_auth_from_production = basic(materials[0])
    b.sales.custom_zatca_pos_name = None
    read = b.frappe.get_doc.side_effect

    def rotate(doctype, name):
        if (doctype, name) == ("Sales Invoice", "SI"):
            b.company.custom_basic_auth_from_csid = b.company.custom_basic_auth_from_production = "PRIVATE invalid"
            b.company.custom_certificate = materials[1].text
            b.company.custom_private_key = materials[1].pem
            b.company.custom_select = "Sandbox"
        return read(doctype, name)

    b.frappe.get_doc.side_effect = rotate
    report = adapter.capture_credential_lifecycle_assessment("TC", b.sales, observed_at=NOW)
    assert report.environment == "Production"
    assert report.certificate_relationship == "SAME_AUTH_CERTIFICATE"
    assert all(item.status == "TOKEN_MATERIAL_LOCALLY_BOUND" for item in report.purposes)
    assert report.diagnostic_projection()["database_snapshot_verified"] is False


@pytest.mark.parametrize("source", ["company", "device"])
def test_actual_legacy_csid_writers_reproduce_transition_without_real_http(boundary, pair, monkeypatch, source):
    """Characterization, NOT approval to display secrets or overwrite credentials."""
    b = boundary
    doc = getattr(b, source)
    doc.custom_private_key = pair[0].pem
    doc.custom_csr_data, doc.custom_otp = "TEST-CSR", "000000"
    b.company.custom_production_url = settings()["custom_production_url"]
    b.company.custom_sandbox_url = settings("Sandbox")["custom_sandbox_url"]
    monkeypatch.setattr(b.frappe, "publish_realtime", Mock(), raising=False)
    monkeypatch.setattr(b.frappe, "session", SimpleNamespace(user="TEST-OPERATOR"), raising=False)
    monkeypatch.setattr(client, "get_company_api_route", lambda *args, **kwargs: SimpleNamespace(environment="Production", url="https://example.invalid/compliance"))
    monkeypatch.setattr(client, "get_compliance_api_url", lambda *args, **kwargs: "https://example.invalid/production/csids")

    def response(material, request_id):
        data = {"binarySecurityToken": base64.b64encode(material.text.encode()).decode(), "secret": "PRIVATE-SECRET", "requestID": request_id}
        return SimpleNamespace(status_code=200, headers={}, text=json.dumps(data), json=lambda: data)

    post = Mock(side_effect=[response(pair[0], "TEST-COMPLIANCE"), response(pair[1], "TEST-FINAL")])
    monkeypatch.setattr(client.requests, "post", post)
    identity = {"doctype": doc.doctype, "name": doc.name}
    compliance_result = inspect.unwrap(client.create_csid)(identity, "TC")
    assert json.loads(compliance_result) == csid_creation_result("compliance")
    assert doc.custom_compliance_request_id_ == "TEST-COMPLIANCE"
    assert doc.custom_basic_auth_from_csid == basic(pair[0])
    final_result = inspect.unwrap(client.production_csid)(identity, "TC")
    assert json.loads(final_result) == csid_creation_result("production")
    assert "PRIVATE-SECRET" not in compliance_result + final_result + str(b.frappe.msgprint.call_args_list)
    assert doc.custom_certificate == pair[1].text
    assert doc.custom_compliance_request_id_ == "TEST-COMPLIANCE"
    assert post.call_count == 2
    assert post.call_args.kwargs["headers"]["Authorization"] == "Basic " + basic(pair[0])
    assert post.call_args.kwargs["json"] == {"compliance_request_id": "TEST-COMPLIANCE"}
    report = adapter.capture_credential_lifecycle_assessment("TC", doc, observed_at=NOW)
    assert report.certificate_relationship == "DIFFERENT_AUTH_CERTIFICATES"
    assert all(item.status == "TOKEN_MATERIAL_LOCALLY_BOUND" for item in report.purposes)
    if source == "device":
        assert doc.custom_certficate == pair[0].text
        assert report.legacy_selection_status == "CERTIFICATE_ALIAS_CONFLICT"
    else:
        assert "COMPLIANCE_CERTIFICATE_NOT_STORED" in report.review_codes
    b.frappe.db.commit.assert_not_called()


@pytest.fixture
def csid_writer(boundary, pair, monkeypatch):
    """Synthetic issuance replies and saved documents; transport never leaves VM."""
    b = boundary
    for doc in (b.company, b.device):
        doc.custom_csr_data = "PRIVATE-CSR"
        doc.custom_otp = "PRIVATE-OTP"
        doc.custom_compliance_request_id_ = "PRIVATE-ORIGINAL-REQUEST"
    b.frappe.publish_realtime = Mock()
    b.frappe.session = SimpleNamespace(user="TEST-OPERATOR")
    b.translated = []

    def translate(key):
        b.translated.append(key)
        return "DISPLAY:" + key if b.ui_arabic else key

    b.ui_arabic = False
    monkeypatch.setattr(client, "_", translate)
    monkeypatch.setattr(client, "get_company_api_route", lambda *args, **kwargs:
                        SimpleNamespace(environment=b.environment, url="https://example.invalid/compliance"))
    monkeypatch.setattr(client, "get_compliance_api_url", lambda *args, **kwargs:
                        "https://example.invalid/production/csids")
    b.data = {"binarySecurityToken": base64.b64encode(pair[0].text.encode()).decode(),
              "secret": "PRIVATE-SECRET", "requestID": "PRIVATE-RETURNED-REQUEST"}
    b.raw_body = json.dumps(b.data)
    b.reply = SimpleNamespace(status_code=200, headers={}, text=b.raw_body, json=lambda: b.data)
    b.post = Mock(return_value=b.reply)
    monkeypatch.setattr(client.requests, "post", b.post)
    return b


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("arabic", [False, True])
def test_csid_success_exports_only_english_metadata_after_save(csid_writer, pair, source, purpose, environment, arabic):
    b = csid_writer
    b.environment, b.ui_arabic = environment, arabic
    doc = getattr(b, source)

    def saved(**kwargs):
        assert kwargs == {"ignore_permissions": True}, "Legacy persistence is characterized, not approved"
        b.frappe.msgprint.assert_not_called()

    doc.save.side_effect = saved
    operation = client.create_csid if purpose == "compliance" else client.production_csid
    result = inspect.unwrap(operation)({"doctype": doc.doctype, "name": doc.name}, "TC")
    canonical = csid_creation_result(purpose)
    assert type(result) is str and json.loads(result) == canonical
    prefix = "DISPLAY:" if arabic else ""
    b.frappe.msgprint.assert_called_once_with({"title": prefix + "CSID Generation Result",
        "message": prefix + canonical["message"], "indicator": "green"})
    exported = result + repr(b.frappe.msgprint.call_args_list)
    for private in (b.raw_body, b.data["binarySecurityToken"], b.data["secret"], b.data["requestID"],
                    doc.custom_otp, doc.custom_csr_data, doc.custom_private_key):
        assert private not in exported
        assert private not in b.translated
    assert "DISPLAY:" not in result
    if purpose == "compliance":
        assert doc.custom_compliance_request_id_ == b.data["requestID"]
        assert doc.custom_basic_auth_from_csid == basic(pair[0])
    else:
        field = "custom_basic_auth_from_production" if source == "company" else "custom_final_auth_csid"
        assert getattr(doc, field) == basic(pair[0])
        assert b.post.call_args.kwargs["json"] == {"compliance_request_id": "PRIVATE-ORIGINAL-REQUEST"}
    doc.save.assert_called_once_with(ignore_permissions=True)
    assert b.post.call_count == 1
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("fault", ["save", "missing-token", "missing-secret"])
def test_csid_success_is_not_announced_before_parsing_and_save(csid_writer, source, purpose, fault):
    b = csid_writer
    b.environment = "Production"
    doc = getattr(b, source)
    if fault == "save":
        doc.save.side_effect = ValueError("Synthetic local persistence failure")
    else:
        del b.data["binarySecurityToken" if fault == "missing-token" else "secret"]
        b.reply.text = json.dumps(b.data)
    operation = client.create_csid if purpose == "compliance" else client.production_csid
    with pytest.raises(ValidationError):
        inspect.unwrap(operation)({"doctype": doc.doctype, "name": doc.name}, "TC")
    b.frappe.msgprint.assert_not_called()
    assert b.post.call_count == 1
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize("purpose", [None, "", "COMPLIANCE", "PRIVATE-SECRET", [], {}, 1, True])
def test_csid_metadata_builder_refuses_unknown_purpose_without_reflecting_input(purpose):
    with pytest.raises(ValueError, match="^Unsupported CSID purpose\\.$"):
        csid_creation_result(purpose)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503, 202, 406])
@pytest.mark.parametrize("body_kind", ["otp", "steps", "unknown", "malformed"])
def test_csid_http_classification_exports_no_response_text_or_untrusted_fields(purpose, status, body_kind):
    body = {
        "otp": json.dumps({"errors": [{"code": "Invalid-OTP", "message": "PRIVATE-ERROR"}], "secret": "PRIVATE-SECRET"}),
        "steps": json.dumps({"code": "Missing-ComplianceSteps", "message": "PRIVATE-ERROR", "binarySecurityToken": "PRIVATE-TOKEN"}),
        "unknown": json.dumps({"code": "PRIVATE-CODE", "message": "PRIVATE-ERROR"}),
        "malformed": "PRIVATE-MALFORMED <script>alert(1)</script>",
    }[body_kind]
    result = csid_request_rejection(purpose, status, body)
    assert result["status"] == "ERROR" and result["http_status"] == status
    assert set(result) == {"status", "purpose", "code", "http_status", "message"}
    assert result["purpose"] == purpose
    assert "PRIVATE" not in json.dumps(result) and "<script>" not in json.dumps(result)
    expected = {401: "CSID_AUTHENTICATION_FAILED", 403: "CSID_ACCESS_DENIED",
                429: "CSID_RATE_LIMITED", 500: "CSID_REMOTE_ERROR", 503: "CSID_REMOTE_ERROR"}.get(status, "CSID_RESPONSE_UNCONFIRMED")
    if status == 400 and purpose == "compliance" and body_kind == "otp":
        expected = "CSID_INVALID_OTP"
    if status == 400 and purpose == "production" and body_kind == "steps":
        expected = "CSID_COMPLIANCE_INCOMPLETE"
    assert result["code"] == expected
    error = CSIDRequestRejected(purpose, status, body)
    assert vars(error) == {"result": result}
    assert str(error) == result["code"] and "PRIVATE" not in repr(error)


@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("body", [None, [], {}, b"PRIVATE", 1, "x" * 65537,
    "[" * 1500 + "]" * 1500, '{"errors":[{"code":null}]}',
    '{"errors":[{"code":["Invalid-OTP"]}]}', '{"errors":[{"code":"invalid-otp"}]}'])
def test_csid_http_unknown_malformed_or_unbounded_body_is_generic(purpose, body):
    result = csid_request_rejection(purpose, 400, body)
    assert result["code"] == "CSID_RESPONSE_UNCONFIRMED"


@pytest.mark.parametrize("value", [None, True, "401", 401.0, -1, 999])
def test_csid_http_status_requires_bounded_literal_integer(value):
    result = csid_request_rejection("compliance", value, "PRIVATE-BODY")
    assert result["http_status"] is None and result["code"] == "CSID_RESPONSE_UNCONFIRMED"


@pytest.mark.parametrize("source", ["company", "device"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("arabic", [False, True])
@pytest.mark.parametrize("status,code", [(400, "Invalid-OTP"), (400, "Missing-ComplianceSteps"),
                                      (401, "PRIVATE-CODE"), (503, "PRIVATE-CODE"), (406, "PRIVATE-CODE")])
def test_csid_http_entry_raises_one_redacted_dialog_without_raw_exception_chain(csid_writer, monkeypatch, source, purpose, arabic, status, code):
    import csv
    from pathlib import Path

    b = csid_writer
    b.environment = "Production"
    doc = getattr(b, source)
    body = json.dumps({"errors": [{"code": code, "message": "PRIVATE-ERROR"}],
                       "code": code, "secret": "PRIVATE-SECRET", "binarySecurityToken": "PRIVATE-TOKEN"})
    b.reply.status_code, b.reply.text = status, body
    b.reply.headers = SimpleNamespace(get=Mock(side_effect=AssertionError("Untrusted header must not be read")))
    b.reply.reason = "PRIVATE-REASON"
    with (Path(__file__).parents[2] / "translations/ar.csv").open(encoding="utf-8") as catalog_file:
        catalog = {row[0]: row[1] for row in csv.reader(catalog_file) if len(row) >= 2}
    translated = []

    def translate(key):
        translated.append(key)
        return catalog[key] if arabic else key

    monkeypatch.setattr(client, "_", translate)
    def fail(message, **kwargs):
        raise ValidationError(message)

    b.frappe.throw = Mock(side_effect=fail)
    operation = client.create_csid if purpose == "compliance" else client.production_csid
    result = csid_request_rejection(purpose, status, body)
    with pytest.raises(ValidationError) as raised:
        inspect.unwrap(operation)({"doctype": doc.doctype, "name": doc.name}, "TC")
    expected = (catalog[result["message"]] if arabic else result["message"]) + "<br>" + (catalog["HTTP status"] if arabic else "HTTP status") + ": " + str(status)
    b.frappe.throw.assert_called_once_with(expected, title=catalog["CSID Generation Failed"] if arabic else "CSID Generation Failed")
    assert str(raised.value) == expected
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert "PRIVATE" not in repr(raised.value) and "PRIVATE" not in repr(translated)
    assert result["message"] in translated
    assert result["code"].isascii() and result["message"].isascii()
    doc.save.assert_not_called()
    b.frappe.msgprint.assert_not_called()
    b.frappe.db.commit.assert_not_called()
    assert b.post.call_count == 1


@pytest.mark.parametrize("source", ["company", "device"])
def test_legacy_key_generation_overwrites_shared_key_without_rotating_auth(boundary, materials, monkeypatch, source):
    """Generated keys stay in memory; document saves and HTTP are mocked."""
    b = boundary
    doc = getattr(b, source)
    b.company.custom_production_url = settings()["custom_production_url"]
    material = materials[0] if source == "company" else materials[2]
    doc.custom_basic_auth_from_csid = doc.custom_basic_auth_from_production = doc.custom_final_auth_csid = basic(material)
    previous = doc.custom_private_key
    private_key = client.create_private_keys("TC", {"doctype": doc.doctype, "name": doc.name})
    assert private_key.decode() == doc.custom_private_key != previous
    assert doc.custom_basic_auth_from_csid == basic(material)
    report = adapter.capture_credential_lifecycle_assessment("TC", doc, observed_at=NOW)
    assert all(item.error_code == "snapshot_key_mismatch" for item in report.purposes)
    doc.save.assert_called_once_with(ignore_permissions=True)
    b.frappe.db.commit.assert_not_called()
    b.request.assert_not_called()


@pytest.mark.parametrize("header", [None, b"Basic x", "Bearer PRIVATE", "basic PRIVATE", "Basic " + "a" * (512 * 1024 + 1)])
def test_shared_auth_decoder_rejects_unbounded_or_unnormalized_input(header):
    with pytest.raises(CredentialSnapshotError, match="^snapshot_authorization_format$"):
        authentication_certificate_der(header)
