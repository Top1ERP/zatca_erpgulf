"""Generated CSRs and unsigned synthetic XML observations; never real acceptance."""

import base64
import json
import pickle
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta, timezone
from uuid import UUID, uuid4, uuid5

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID

from zatca_erpgulf.zatca_erpgulf import compliance_evidence as evidence
from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import inspect_invoice_artifact
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings as route_settings
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle import cipher, seal, record, connection, NAMESPACE, VERSION, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle_access import operator, service, InspectionFailed, PermissionDenied
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture, basic
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import content
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import SELLER, UUID as XML_UUID


def csr(material, functionality="1100", *, titles=None, identifiers=None, names=1, include_san=True):
    key = serialization.load_pem_private_key(material.pem.encode(), password=None)
    builder = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "PRIVATE-CSR-SUBJECT")]))
    if include_san:
        attributes = [x509.NameAttribute(NameOID.TITLE, value) for value in (titles if titles is not None else [functionality])]
        attributes += [x509.NameAttribute(NameOID.USER_ID, value) for value in (identifiers if identifiers is not None else [SELLER])]
        builder = builder.add_extension(x509.SubjectAlternativeName([
            x509.DirectoryName(x509.Name(attributes)) for _ in range(names)]), critical=False)
    return builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)


def requirements(material, cipher, *, environment="Production", functionality="1100", **changes):
    envelope = seal(cipher, capture(material, endpoint="compliance/invoices", environment=environment))
    values = dict(storage_namespace=NAMESPACE, manifest=envelope.manifest, csr_der=csr(material, functionality))
    values.update(changes)
    return evidence.ComplianceRequirements(**values), envelope


def request(material, step="SIMPLIFIED", **changes):
    _, code, prefix = evidence.STEP_CLASSIFICATION[step]
    xml = content(material.cert.public_bytes(serialization.Encoding.DER), code=code, indicator=prefix + "00000")
    xml = xml.replace(XML_UUID.encode(), str(uuid5(UUID(NAMESPACE), step)).encode())
    observed = inspect_invoice_artifact(xml)
    body = dict(invoiceHash=observed.invoice_digest, uuid=observed.uuid, invoice=base64.b64encode(xml).decode())
    body.update(changes)
    return json.dumps(body, separators=(",", ":")).encode()


def response(status="PASS", *, step="SIMPLIFIED", previous=False):
    return {"validationResults": {"status": "ERROR" if previous else status,
        "infoMessages": [], "warningMessages": [] if status != "WARNING" else [
            {"type": "WARNING", "status": "WARNING", "code": "TEST", "message": "PRIVATE-RESPONSE-MESSAGE"}],
        "errorMessages": [{"type": "ERROR", "status": "ERROR", "code": "Submitted before",
            "category": "Compliance-Check", "message": "Compliance check already completed for " + step + "."}]
            if previous else []}}


def exchange(req, material, *, step="SIMPLIFIED", status=200, body=None, **changes):
    values = dict(requirements=req, exchange_id=str(uuid4()),
        route=resolve_api_route(route_settings(req.manifest.slot.environment), "compliance/invoices"),
        started_at=NOW + timedelta(seconds=1), received_at=NOW + timedelta(seconds=2),
        request_bytes=request(material, step), http_status=status,
        response_bytes=json.dumps(body if body is not None else response(step=step, previous=status == 406)).encode())
    values.update(changes)
    return evidence.ComplianceExchangeObservation(**values)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("functionality,required", [("1000", 3), ("0100", 3), ("1100", 6)])
@pytest.mark.parametrize("status", [200, 202, 406])
def test_complete_profiles_bind_one_version_without_remote_authority(materials, cipher, environment, functionality, required, status):
    req, _ = requirements(materials[0], cipher, environment=environment, functionality=functionality)
    checks = tuple(exchange(req, materials[0], step=step, status=status,
        body=response("WARNING" if status == 202 else "PASS", step=step, previous=status == 406)) for step in req.required_steps)
    observed = evidence.ComplianceCheckSet(req, checks)
    report = observed.diagnostic_projection()
    assert report["state"] == "COMPLETE_MATCHED_OBSERVATIONS" and not report["missing_steps"]
    assert len(report["required_steps"]) == required
    assert all(value is False for name, value in report.items() if name.endswith(("_verified", "_authorized")))
    assert all(check.outcome == ("ALREADY_COMPLETED_MATCHED_OBSERVATION" if status == 406 else "PASS_MATCHED_OBSERVATION") for check in checks)
    printable = json.dumps(report) + repr(observed) + repr(req) + repr(checks)
    for private in (materials[0].pem, materials[0].text, basic(materials[0]), "PRIVATE-CSR-SUBJECT",
                    "PRIVATE-RESPONSE-MESSAGE", "gw-fatoora", checks[0].request_bytes.decode()):
        assert private not in printable
    assert checks[0].request_bytes == request(materials[0], req.required_steps[0])


@pytest.mark.parametrize("step", list(evidence.STEP_CLASSIFICATION))
def test_one_result_cannot_complete_six_steps_and_identical_delivery_is_deduplicated(materials, cipher, step):
    req, _ = requirements(materials[0], cipher)
    found = exchange(req, materials[0], step=step)
    report = evidence.ComplianceCheckSet(req, (found, found)).diagnostic_projection()
    assert len(report["exchanges"]) == 1 and len(report["missing_steps"]) == 5
    assert step not in report["missing_steps"]


@pytest.mark.parametrize("change", ["version", "flow", "request_id", "namespace", "csr"])
def test_different_flow_version_request_namespace_or_csr_cannot_be_combined(materials, cipher, change):
    req, _ = requirements(materials[0], cipher)
    if change == "namespace":
        other = replace(req, storage_namespace=str(uuid4()))
    elif change == "csr":
        other = replace(req, csr_der=csr(materials[0], "1000"))
    else:
        field = {"version": "version_id", "flow": "flow_id", "request_id": "compliance_request_id"}[change]
        other = replace(req, manifest=replace(req.manifest, **{field: str(uuid4())}))
    with pytest.raises(evidence.ComplianceEvidenceError, match="compliance_exchange_binding"):
        evidence.ComplianceCheckSet(req, (exchange(other, materials[0]),))


@pytest.mark.parametrize("change", ["status", "response", "request", "time"])
def test_same_attempt_cannot_be_overwritten_with_changed_observation(materials, cipher, change):
    req, _ = requirements(materials[0], cipher)
    first = exchange(req, materials[0])
    values = {"status": {"http_status": 202}, "response": {"response_bytes": json.dumps(response("WARNING")).encode()},
        "request": {"request_bytes": first.request_bytes + b" "}, "time": {"received_at": NOW + timedelta(seconds=3)}}[change]
    with pytest.raises(evidence.ComplianceEvidenceError, match="compliance_exchange_conflict"):
        evidence.ComplianceCheckSet(req, (first, replace(first, **values)))


def test_gateways_cannot_be_mixed_even_under_same_environment(materials, cipher):
    req, _ = requirements(materials[0], cipher)
    first = exchange(req, materials[0])
    route = resolve_api_route({"custom_select": "Production", "custom_production_url": "https://gateway.invalid/phase2"}, "compliance/invoices")
    with pytest.raises(evidence.ComplianceEvidenceError, match="compliance_exchange_gateway"):
        evidence.ComplianceCheckSet(req, (first, exchange(req, materials[0], route=route)))


def test_sample_uuid_cannot_represent_two_different_xml_artifacts(materials, cipher):
    req, _ = requirements(materials[0], cipher)
    first = exchange(req, materials[0])
    body = json.loads(request(materials[0], "STANDARD"))
    xml = base64.b64decode(body["invoice"]).replace(body["uuid"].encode(), first.invoice_uuid.encode())
    body.update(uuid=first.invoice_uuid, invoice=base64.b64encode(xml).decode())
    other = exchange(req, materials[0], request_bytes=json.dumps(body).encode())
    with pytest.raises(evidence.ComplianceEvidenceError, match="compliance_sample_uuid_conflict"):
        evidence.ComplianceCheckSet(req, (first, other))


def test_new_attempt_same_artifact_can_be_observed_without_issuing_again(materials, cipher):
    req, _ = requirements(materials[0], cipher)
    first = exchange(req, materials[0], status=None, received_at=None, response_bytes=None)
    later = exchange(req, materials[0])
    report = evidence.ComplianceCheckSet(req, (first, later)).diagnostic_projection()
    assert len(report["exchanges"]) == 2 and len(report["missing_steps"]) == 5
    assert report["replay_authorized"] is False


def test_total_wire_size_is_bounded_with_idempotent_duplicates_not_counted_twice(materials, cipher, monkeypatch):
    req, _ = requirements(materials[0], cipher)
    first, second = exchange(req, materials[0]), exchange(req, materials[0])
    monkeypatch.setattr(evidence, "MAX_CHECK_SET_BYTES", len(first.request_bytes) + len(first.response_bytes))
    assert len(evidence.ComplianceCheckSet(req, (first, first)).diagnostic_projection()["exchanges"]) == 1
    with pytest.raises(evidence.ComplianceEvidenceError, match="compliance_check_set_size"):
        evidence.ComplianceCheckSet(req, (first, second))


@pytest.mark.parametrize("mutation", ["wrong_step", "mixed_error", "empty_error", "wrong_category", "info", "warning", "local_marker", "missing_message"])
def test_406_requires_raw_exact_previous_completion_for_the_xml_type(materials, cipher, mutation):
    req, _ = requirements(materials[0], cipher)
    body = response(previous=True)
    validation = body["validationResults"]
    if mutation == "wrong_step":
        validation["errorMessages"][0]["message"] = "Compliance check already completed for STANDARD."
    elif mutation == "mixed_error":
        validation["errorMessages"].append({"code": "QRCODE_INVALID"})
    elif mutation == "empty_error":
        validation["errorMessages"] = []
    elif mutation == "wrong_category":
        validation["errorMessages"][0]["category"] = "Other"
    elif mutation in ("info", "warning"):
        validation[mutation + "Messages"].append({})
    elif mutation == "local_marker":
        body["_zatca_compliance_status"] = "ALREADY_COMPLETED"
    else:
        validation["errorMessages"][0].pop("message")
    found = exchange(req, materials[0], status=406, body=body)
    assert found.outcome == "UNCONFIRMED"
    assert len(evidence.ComplianceCheckSet(req, (found,)).diagnostic_projection()["missing_steps"]) == 6


@pytest.mark.parametrize("status", [200, 202])
@pytest.mark.parametrize("mutation", ["missing_validation", "missing_errors", "error", "wrong_status", "bad_list", "bad_entry", "marker", "duplicate", "trailing", "html"])
def test_200_or_202_without_consistent_validation_does_not_complete(materials, cipher, status, mutation):
    req, _ = requirements(materials[0], cipher)
    body = response()
    validation = body["validationResults"]
    if mutation == "missing_validation":
        body.clear()
    elif mutation == "missing_errors":
        validation.pop("errorMessages")
    elif mutation == "error":
        validation["errorMessages"] = [{"code": "signed-properties-hashing"}]
    elif mutation == "wrong_status":
        validation["status"] = "SUCCESS"
    elif mutation == "bad_list":
        validation["warningMessages"] = "PRIVATE-SECRET"
    elif mutation == "bad_entry":
        validation["infoMessages"] = [{"type": "ERROR"}]
    elif mutation == "marker":
        body["_zatca_compliance_status"] = "PASS"
    wire = json.dumps(body).encode()
    if mutation == "duplicate":
        wire = b'{"validationResults":{},"validationResults":{}}'
    elif mutation == "trailing":
        wire += b"{}"
    elif mutation == "html":
        wire = b"<html>PRIVATE-SECRET</html>"
    found = exchange(req, materials[0], status=status, response_bytes=wire)
    assert found.outcome == "UNCONFIRMED"


@pytest.mark.parametrize("status", [400, 401, 403, 409, 500, 503])
def test_http_rejection_cannot_be_success_shaped_even_with_pass_body(materials, cipher, status):
    req, _ = requirements(materials[0], cipher)
    found = exchange(req, materials[0], status=status)
    assert found.outcome not in ("PASS_MATCHED_OBSERVATION", "ALREADY_COMPLETED_MATCHED_OBSERVATION")
    if status in (401, 403):
        assert found.outcome == "AUTHORIZATION_FAILED"


def test_timeout_stays_unknown_and_cannot_enable_any_step(materials, cipher):
    req, _ = requirements(materials[0], cipher)
    found = exchange(req, materials[0], status=None, received_at=None, response_bytes=None)
    assert found.outcome == "TRANSPORT_UNKNOWN"
    assert len(evidence.ComplianceCheckSet(req, (found,)).diagnostic_projection()["missing_steps"]) == 6


@pytest.mark.parametrize("change", ["fields", "uuid", "hash", "certificate", "taxpayer", "type", "bad_base64", "string", "duplicate", "oversized"])
def test_request_must_bind_exact_body_xml_identity_certificate_and_taxpayer(materials, cipher, change):
    req, _ = requirements(materials[0], cipher)
    body = json.loads(request(materials[0]))
    if change == "fields":
        body["Authorization"] = "PRIVATE-SECRET"
    elif change == "uuid":
        body["uuid"] = str(uuid4())
    elif change == "hash":
        body["invoiceHash"] = base64.b64encode(b"x" * 32).decode()
    elif change == "certificate":
        body = json.loads(request(materials[1]))
    elif change in ("taxpayer", "type"):
        xml = content(materials[0].cert.public_bytes(serialization.Encoding.DER),
                      seller="311111111111113" if change == "taxpayer" else SELLER,
                      code="386" if change == "type" else "388")
        body["invoice"] = base64.b64encode(xml).decode()
    elif change == "bad_base64":
        body["invoice"] = "PRIVATE-SECRET***"
    wire = json.dumps(body).encode()
    if change == "string":
        wire = wire.decode()
    elif change == "duplicate":
        wire = b'{"invoice":null,"invoice":null}'
    elif change == "oversized":
        wire = b"x" * (evidence.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(evidence.ComplianceEvidenceError) as error:
        exchange(req, materials[0], request_bytes=wire)
    assert "PRIVATE-SECRET" not in str(error.value)


@pytest.mark.parametrize("change", ["key", "bad_der", "pem", "trailing", "signature", "missing_san", "two_names", "no_title", "two_titles", "unknown_map", "reserved_map", "no_uid", "two_uids", "bad_uid", "uid_prefix", "uid_suffix", "size", "production"])
def test_csr_signature_key_san_functionality_and_taxpayer_are_bounded(materials, cipher, change):
    req, _ = requirements(materials[0], cipher)
    data = req.csr_der
    manifest = req.manifest
    if change == "key":
        data = csr(materials[1])
    elif change == "bad_der":
        data = b"PRIVATE-SECRET"
    elif change == "pem":
        data = x509.load_der_x509_csr(data).public_bytes(serialization.Encoding.PEM)
    elif change == "trailing":
        data += b"x"
    elif change == "signature":
        data = data[:-1] + bytes([data[-1] ^ 1])
    elif change == "missing_san":
        data = csr(materials[0], include_san=False)
    elif change == "two_names":
        data = csr(materials[0], names=2)
    elif change == "no_title":
        data = csr(materials[0], titles=[])
    elif change == "two_titles":
        data = csr(materials[0], titles=["1000", "0100"])
    elif change in ("unknown_map", "reserved_map"):
        data = csr(materials[0], functionality="0000" if change == "unknown_map" else "1110")
    elif change == "no_uid":
        data = csr(materials[0], identifiers=[])
    elif change == "two_uids":
        data = csr(materials[0], identifiers=[SELLER, "311111111111113"])
    elif change == "bad_uid":
        data = csr(materials[0], identifiers=["١" * 15])
    elif change == "uid_prefix":
        data = csr(materials[0], identifiers=["0" + SELLER[1:]])
    elif change == "uid_suffix":
        data = csr(materials[0], identifiers=[SELLER[:-1] + "0"])
    elif change == "size":
        data = b"x" * (evidence.MAX_CSR_BYTES + 1)
    else:
        manifest = replace(manifest, slot=replace(manifest.slot, purpose="production"), parent_compliance_version_id=str(uuid4()))
    with pytest.raises(evidence.ComplianceEvidenceError):
        replace(req, csr_der=data, manifest=manifest)


@pytest.mark.parametrize("change", ["endpoint", "environment", "purpose", "base_field", "url", "version_id", "naive_time", "non_utc", "before_preparation", "response_before_start", "bool_status", "invalid_status", "empty_body", "oversized_body", "unknown_with_receipt"])
def test_exchange_scope_and_receipt_boundaries(materials, cipher, change):
    req, _ = requirements(materials[0], cipher)
    found = exchange(req, materials[0])
    changes = {}
    if change in ("endpoint", "environment", "purpose", "base_field", "url"):
        route_values = {"endpoint": {"endpoint": "invoices/reporting/single"}, "environment": {"environment": "Sandbox"},
            "purpose": {"required_credential": "production"}, "base_field": {"base_url_field": "custom_sandbox_url"}, "url": {"url": "http://gateway.invalid/compliance/invoices"}}[change]
        changes["route"] = replace(found.route, **route_values)
    else:
        changes = {"version_id": {"exchange_id": "latest"}, "naive_time": {"started_at": NOW.replace(tzinfo=None)},
            "non_utc": {"started_at": NOW.astimezone(timezone(timedelta(hours=3)))},
            "before_preparation": {"started_at": NOW - timedelta(seconds=1)},
            "response_before_start": {"received_at": NOW}, "bool_status": {"http_status": True},
            "invalid_status": {"http_status": 600}, "empty_body": {"response_bytes": b""},
            "oversized_body": {"response_bytes": b"x" * (evidence.MAX_RESPONSE_BYTES + 1)},
            "unknown_with_receipt": {"http_status": None}}[change]
    with pytest.raises(evidence.ComplianceEvidenceError):
        replace(found, **changes)


@pytest.mark.parametrize("change", ["namespace", "manifest", "gateway", "taxpayer", "denied", "none", "type"])
def test_permissioned_service_checks_authenticated_staged_scope_before_report(operator, materials, cipher, change):
    req, envelope = requirements(materials[0], cipher)
    operator.documents["Company", "SOURCE"].values["tax_id"] = SELLER
    checks = tuple(exchange(req, materials[0], step=step) for step in req.required_steps)
    if change == "namespace":
        req = replace(req, storage_namespace=str(uuid4()))
        checks = tuple(exchange(req, materials[0], step=step) for step in req.required_steps)
    elif change == "manifest":
        req = replace(req, manifest=replace(req.manifest, compliance_request_id="OTHER_REQUEST"))
        checks = tuple(exchange(req, materials[0], step=step) for step in req.required_steps)
    elif change == "gateway":
        route = resolve_api_route({"custom_select": "Production", "custom_production_url": "https://gateway.invalid/phase2"}, "compliance/invoices")
        checks = tuple(exchange(req, materials[0], step=step, route=route) for step in req.required_steps)
    elif change == "taxpayer":
        operator.documents["Company", "SOURCE"].values["tax_id"] = "311111111111113"
    elif change == "denied":
        operator.denied.add(("Company", "SOURCE"))
    check_set = None if change == "none" else {} if change == "type" else evidence.ComplianceCheckSet(req, checks)
    database, _ = connection([(0,), record(envelope)])
    inspector, provider = service(operator, database, cipher)
    with pytest.raises(PermissionDenied if change == "denied" else InspectionFailed):
        inspector.inspect_compliance_checks("TC", None, version_id=VERSION, check_set=check_set)
    if change in ("denied", "none", "type"):
        provider.assert_not_called()
    database.commit.assert_not_called()


def test_permissioned_service_reports_complete_observations_but_cannot_activate(operator, materials, cipher):
    req, envelope = requirements(materials[0], cipher)
    operator.documents["Company", "SOURCE"].values["tax_id"] = SELLER
    check_set = evidence.ComplianceCheckSet(req, tuple(exchange(req, materials[0], step=step) for step in req.required_steps))
    database, _ = connection([(0,), record(envelope)])
    inspector, _ = service(operator, database, cipher)
    report = inspector.inspect_compliance_checks("TC", None, version_id=VERSION, check_set=check_set)
    assert report["state"] == "COMPLETE_MATCHED_OBSERVATIONS"
    assert report["activation_authorized"] is report["compliance_completion_verified"] is False
    database.commit.assert_not_called()


def test_observations_are_frozen_private_and_not_pickleable(materials, cipher):
    req, _ = requirements(materials[0], cipher)
    found = exchange(req, materials[0])
    check_set = evidence.ComplianceCheckSet(req, (found,))
    for value in (req, found, check_set):
        with pytest.raises(evidence.ComplianceEvidenceError, match="compliance_not_pickleable"):
            pickle.dumps(value)
        with pytest.raises(FrozenInstanceError):
            value.requirements = None
    report = check_set.diagnostic_projection()
    report["required_steps"].clear()
    assert len(check_set.requirements.required_steps) == 6


@pytest.mark.parametrize("values", [[], (None,), tuple([None] * (evidence.MAX_EXCHANGES + 1))])
def test_bounded_exchange_collection(materials, cipher, values):
    req, _ = requirements(materials[0], cipher)
    with pytest.raises(evidence.ComplianceEvidenceError):
        evidence.ComplianceCheckSet(req, values)
