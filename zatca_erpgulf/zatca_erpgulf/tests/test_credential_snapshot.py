"""Synthetic ephemeral material; no site reads, key files or ZATCA requests."""

import base64
import csv
import hashlib
import json
import pickle
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from zatca_erpgulf.zatca_erpgulf import credential_snapshot as snapshot
from zatca_erpgulf.zatca_erpgulf import credential_settings as settings
from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialOwner
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings as route_settings
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials, boundary, ValidationError


NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


def basic(material, *, format="body", password="PRIVATE-SECRET"):
    der = material.cert.public_bytes(serialization.Encoding.DER)
    token = {
        "body": material.text.encode(), "der": der,
        "pem": material.cert.public_bytes(serialization.Encoding.PEM),
    }[format]
    username = base64.b64encode(token)
    return base64.b64encode(username + b":" + password.encode()).decode()


def owner(material, *, doctype="Company", kind="company", **changes):
    values = {
        "custom_private_key": material.pem, "custom_basic_auth_from_csid": basic(material),
        "custom_basic_auth_from_production": basic(material), "custom_final_auth_csid": basic(material),
    }
    values.update(changes)
    return CredentialOwner("SOURCE", doctype, "SOURCE" if kind == "company" else "OWNER", kind, values)


def capture(material, *, environment="Production", endpoint="invoices/reporting/single", selected_owner=None, text=None, at=NOW):
    return snapshot.CredentialSnapshot(
        selected_owner or owner(material), resolve_api_route(route_settings(environment), endpoint),
        material.text if text is None else text, at,
    )


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("endpoint", ["compliance/invoices", "invoices/reporting/single", "invoices/clearance/single"])
@pytest.mark.parametrize("doctype,kind", [("Company", "company"), ("Company", "linked_company"), ("ZATCA Multiple Setting", "multiple_setting")])
def test_one_material_binding_for_all_environments_purposes_and_owners(materials, environment, endpoint, doctype, kind):
    material = materials[0]
    captured = capture(material, environment=environment, endpoint=endpoint, selected_owner=owner(material, doctype=doctype, kind=kind))
    assert captured.certificate_der_sha256 == hashlib.sha256(material.cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    assert captured.authorization.purpose == ("compliance" if endpoint == "compliance/invoices" else "production")
    assert captured.private_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) == captured.public_key_der
    report = captured.diagnostic_projection()
    assert report["key_certificate_bound"] is report["authentication_certificate_bound"] is True
    for name in ("database_snapshot_verified", "credential_epoch_verified", "certificate_trust_verified", "revocation_verified", "taxpayer_verified", "remote_authorization_verified", "dispatch_authorized", "replay_authorized"):
        assert report[name] is False
    assert "PRIVATE-SECRET" not in repr(captured) and "PRIVATE KEY" not in repr(captured)
    assert "gw-fatoora" not in repr(captured)
    assert "PRIVATE-SECRET" not in json.dumps(report)
    assert basic(material) not in json.dumps(report)


@pytest.mark.parametrize("format", ["body", "der", "pem"])
def test_known_token_formats_bind_same_der_without_changing_header(materials, format):
    material = materials[0]
    auth = basic(material, format=format)
    captured = capture(material, selected_owner=owner(material, custom_basic_auth_from_production=auth))
    assert captured.authorization.header == "Basic " + auth
    assert captured.certificate_text == material.text


def test_same_key_certificate_renewal_is_not_same_auth_certificate(materials):
    material = materials[0]
    key = serialization.load_pem_private_key(material.pem.encode(), password=None)
    renewed = (
        x509.CertificateBuilder().subject_name(material.cert.subject).issuer_name(material.cert.issuer)
        .public_key(key.public_key()).serial_number(999)
        .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2030, 1, 1)).sign(key, hashes.SHA256())
    )
    text = base64.b64encode(renewed.public_bytes(serialization.Encoding.DER)).decode()
    with pytest.raises(snapshot.CredentialSnapshotError, match="^snapshot_auth_certificate_mismatch$"):
        capture(material, text=text)


def test_key_mismatch_fails_even_when_auth_certificate_matches(materials):
    with pytest.raises(snapshot.CredentialSnapshotError, match="^snapshot_key_mismatch$"):
        capture(materials[0], selected_owner=owner(materials[0], custom_private_key=materials[1].pem))


@pytest.mark.parametrize("value,code", [
    (None, "snapshot_private_key"), ("", "snapshot_private_key"),
    ("PRIVATE INVALID KEY", "snapshot_private_key"), ([], "snapshot_material_type"),
])
def test_bad_private_material_is_static(materials, value, code):
    with pytest.raises(snapshot.CredentialSnapshotError) as error:
        capture(materials[0], selected_owner=owner(materials[0], custom_private_key=value))
    assert str(error.value) == code


@pytest.mark.parametrize("value", [None, "", "Basic", "PRIVATE", base64.b64encode(b"not-user-and-password").decode(), base64.b64encode(b"dG9rZW4=:").decode(), base64.b64encode(b"dG9rZW4=:PRIVATE\n").decode()])
def test_malformed_authorization_never_binds(materials, value):
    with pytest.raises(snapshot.CredentialSnapshotError) as error:
        capture(materials[0], selected_owner=owner(materials[0], custom_basic_auth_from_production=value))
    assert error.value.code in ("snapshot_material_invalid", "snapshot_authorization_format")
    assert "PRIVATE" not in str(error.value)


def test_missing_purpose_cannot_fall_back_but_unrelated_purpose_is_not_captured(materials):
    material = materials[0]
    with pytest.raises(snapshot.CredentialSnapshotError, match="^snapshot_material_invalid$"):
        capture(material, selected_owner=owner(material, custom_basic_auth_from_production=""))
    captured = capture(material, selected_owner=owner(material, custom_basic_auth_from_csid=["UNRELATED"]))
    assert set(captured.owner.values) == {"custom_private_key", "custom_basic_auth_from_production"}


@pytest.mark.parametrize("at,code", [
    (None, "snapshot_utc_timestamp"), (NOW.replace(tzinfo=None), "snapshot_utc_timestamp"),
    (datetime(2025, 12, 31, tzinfo=timezone.utc), "snapshot_certificate_time"),
    (datetime(2030, 1, 1, 0, 0, 1, tzinfo=timezone.utc), "snapshot_certificate_time"),
])
def test_explicit_utc_validity_check(materials, at, code):
    with pytest.raises(snapshot.CredentialSnapshotError, match=f"^{code}$"):
        capture(materials[0], at=at)


@pytest.mark.parametrize("at", [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2030, 1, 1, tzinfo=timezone.utc)])
def test_validity_boundaries_are_inclusive(materials, at):
    assert capture(materials[0], at=at).observed_at == at


@pytest.mark.parametrize("curve", [ec.SECP256R1(), ec.SECP384R1()])
def test_non_selected_curve_fails_without_claiming_ca_trust(materials, curve):
    material = materials[0]
    key = ec.generate_private_key(curve)
    cert = (
        x509.CertificateBuilder().subject_name(material.cert.subject).issuer_name(material.cert.issuer)
        .public_key(key.public_key()).serial_number(70)
        .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2030, 1, 1)).sign(key, hashes.SHA256())
    )
    material = replace_material(material, key, cert)
    with pytest.raises(snapshot.CredentialSnapshotError, match="^snapshot_algorithm$"):
        capture(material)


def replace_material(material, key, cert):
    return type(material)(
        cert=cert, text=base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode(),
        pem=key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
    )


@pytest.mark.parametrize("attribute", ["owner", "route", "authorization", "certificate_text", "private_key", "public_key_sha256"])
def test_ephemeral_snapshot_is_frozen_and_not_pickleable(materials, attribute):
    captured = capture(materials[0])
    with pytest.raises(FrozenInstanceError):
        setattr(captured, attribute, None)
    with pytest.raises(snapshot.CredentialSnapshotError, match="^snapshot_not_serializable$"):
        pickle.dumps(captured)


def test_later_rotation_does_not_change_captured_key_certificate_or_auth(materials):
    selected_owner = owner(materials[0])
    captured = capture(materials[0], selected_owner=selected_owner)
    selected_owner.values.update(owner(materials[1]).values)
    assert captured.authorization.header == "Basic " + basic(materials[0])
    assert captured.certificate_text == materials[0].text
    assert captured.private_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) == captured.public_key_der
    with pytest.raises(TypeError):
        captured.owner.values["custom_private_key"] = "changed"


@pytest.mark.parametrize("endpoint", ["compliance", "production/csids", "wrong"])
def test_non_invoice_operations_do_not_load_saved_secrets(boundary, endpoint):
    with pytest.raises(ValidationError, match="snapshot_operation"):
        settings.capture_credential_snapshot("TC", boundary.company, endpoint, observed_at=NOW)
    boundary.frappe.get_doc.assert_not_called()


@pytest.mark.parametrize("source", ["company", "sales", "pos", "device"])
@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
def test_saved_capture_reuses_owner_policy_and_reads_company_once(boundary, materials, source, linked, purpose):
    b = boundary
    b.company.custom_select = "Production"
    b.company.custom_production_url = route_settings()["custom_production_url"]
    for doc, material in ((b.company, materials[0]), (b.linked, materials[1]), (b.device, materials[2])):
        doc.custom_basic_auth_from_csid = doc.custom_basic_auth_from_production = doc.custom_final_auth_csid = basic(material)
    b.device.custom__use_company_certificate__keys = int(linked)
    b.device.custom_linked_doctype = "B" if linked else "A"
    endpoint = "compliance/invoices" if purpose == "compliance" else "invoices/reporting/single"
    # Only identity from this caller is trusted; field/link injection is ignored.
    source_doc = getattr(b, source)
    injected = {"doctype": source_doc.doctype, "name": source_doc.name, "custom_private_key": "PRIVATE INJECTED", "custom_zatca_pos_name": "OTHER"}
    captured = settings.capture_credential_snapshot("TC", injected, endpoint, observed_at=NOW)
    expected = b.company if source == "company" else b.linked if linked else b.device
    assert captured.owner.name == expected.name
    assert captured.authorization.purpose == purpose
    company_reads = [call for call in b.frappe.get_doc.call_args_list if call.args == ("Company", {"abbr": "TC"})]
    assert len(company_reads) == 1
    assert b.frappe.db.commit.call_count == 0
    for doc in (b.company, b.device, b.linked):
        doc.save.assert_not_called()
    b.request.assert_not_called()


def test_alias_conflict_not_repaired_even_when_token_matches_one_field(boundary, materials):
    b = boundary
    b.company.custom_production_url = route_settings()["custom_production_url"]
    b.device.custom_final_auth_csid = basic(materials[2])
    b.device.custom_certficate = materials[0].text
    with pytest.raises(ValidationError, match="different values"):
        settings.capture_credential_snapshot("TC", b.device, "invoices/reporting/single", observed_at=NOW)
    b.device.save.assert_not_called()


def test_snapshot_error_has_arabic_catalog_entry_and_safe_code(boundary, monkeypatch):
    key = "ZATCA credential snapshot validation failed ({0}). Review the selected certificate, key, authentication and environment settings."
    file = Path(settings.__file__).parents[1] / "translations/ar.csv"
    with file.open(newline="", encoding="utf-8") as content:
        translations = dict(csv.reader(content))
    assert "فشل" in translations[key]
    monkeypatch.setattr(settings, "_", lambda message: translations.get(message, message))
    with pytest.raises(ValidationError, match="فشل.*snapshot_operation"):
        settings.capture_credential_snapshot("TC", boundary.company, "wrong", observed_at=NOW)


def test_pure_material_capture_has_no_database_filesystem_clock_or_network_access(materials, monkeypatch):
    selected = owner(materials[0])
    route = resolve_api_route(route_settings(), "invoices/reporting/single")

    def forbidden(*args, **kwargs):
        pytest.fail("Pure credential snapshot attempted external access")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(settings.frappe, "get_doc", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    captured = snapshot.CredentialSnapshot(selected, route, materials[0].text, NOW)
    assert captured.authorization.header == "Basic " + basic(materials[0])


def test_credential_bounds_are_checked_before_parsing(materials, monkeypatch):
    monkeypatch.setattr(snapshot, "MAX_AUTH_TEXT", 10)
    with pytest.raises(snapshot.CredentialSnapshotError, match="^snapshot_material_size$"):
        capture(materials[0])


def test_snapshot_signing_key_verifies_with_auth_certificate_public_key(materials):
    captured = capture(materials[0])
    signature = captured.private_key.sign(b"synthetic binding test, not invoice XML", ec.ECDSA(hashes.SHA256()))
    certificate = x509.load_der_x509_certificate(captured.certificate_der)
    certificate.public_key().verify(signature, b"synthetic binding test, not invoice XML", ec.ECDSA(hashes.SHA256()))


@pytest.mark.parametrize("change", [
    {"environment": "Sandbox"}, {"required_credential": "compliance"},
    {"url": "http://PRIVATE.invalid/invoices/reporting/single"},
    {"base_url_field": "other"}, {"endpoint": "production/csids"},
])
def test_manually_constructed_route_is_revalidated(materials, change):
    route = replace(resolve_api_route(route_settings(), "invoices/reporting/single"), **change)
    with pytest.raises(snapshot.CredentialSnapshotError) as error:
        snapshot.CredentialSnapshot(owner(materials[0]), route, materials[0].text, NOW)
    assert error.value.code in ("snapshot_operation", "snapshot_route")
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("change", [
    {"doctype": "User"}, {"name": ""}, {"company_name": ""},
    {"source_kind": "unknown"}, {"source_kind": "multiple_setting"}, {"values": None}, {"name": "OTHER COMPANY"},
])
def test_invalid_owner_declarations_are_not_credential_provenance(materials, change):
    with pytest.raises(snapshot.CredentialSnapshotError) as error:
        capture(materials[0], selected_owner=replace(owner(materials[0]), **change))
    assert error.value.code in ("snapshot_owner", "snapshot_material_invalid")


@pytest.mark.parametrize("token", [
    b"PRIVATE token", b"-----BEGIN CERTIFICATE-----\nPRIVATE\n-----END CERTIFICATE-----garbage",
    b"-----BEGIN CERTIFICATE-----\nPRIVATE\n-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----\nPRIVATE\n-----END CERTIFICATE-----",
    b"<PRIVATE/>",
])
def test_malformed_tokens_do_not_fall_back_to_saved_certificate(materials, token):
    username = base64.b64encode(token)
    auth = base64.b64encode(username + b":PRIVATE-SECRET").decode()
    with pytest.raises(snapshot.CredentialSnapshotError, match="^snapshot_authorization_format$"):
        capture(materials[0], selected_owner=owner(materials[0], custom_basic_auth_from_production=auth))


def test_company_material_is_frozen_before_source_reload_can_rotate_saved_object(boundary, materials):
    b = boundary
    b.company.custom_production_url = route_settings()["custom_production_url"]
    b.company.custom_basic_auth_from_production = basic(materials[0])
    b.sales.custom_zatca_pos_name = None
    original_read = b.frappe.get_doc.side_effect

    def rotate_during_reload(doctype, name):
        if (doctype, name) == ("Sales Invoice", "SI"):
            b.company.custom_private_key = materials[1].pem
            b.company.custom_certificate = materials[1].text
            b.company.custom_basic_auth_from_production = basic(materials[1])
            b.company.custom_production_url = "https://NEW.invalid/core"
        return original_read(doctype, name)

    b.frappe.get_doc.side_effect = rotate_during_reload
    captured = settings.capture_credential_snapshot("TC", b.sales, "invoices/reporting/single", observed_at=NOW)
    assert captured.authorization.header == "Basic " + basic(materials[0])
    assert captured.certificate_text == materials[0].text
    assert "NEW.invalid" not in captured.route.url
    assert captured.diagnostic_projection()["database_snapshot_verified"] is False
