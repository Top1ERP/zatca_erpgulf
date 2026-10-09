"""Historical observations only; synthetic bodies are not authority acceptance."""

import base64
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from zatca_erpgulf.zatca_erpgulf import history_evidence as history
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import saved_identity, xml_bytes


def response_body(kind="reported", **values):
    body = {"validationResults": {"status": "PASS", "errorMessages": []},
            "reportingStatus": "REPORTED" if kind == "reported" else None,
            "clearanceStatus": "CLEARED" if kind == "cleared" else None}
    if kind == "cleared":
        body["clearedInvoice"] = base64.b64encode(xml_bytes()).decode()
    body.update(values)
    return body


def inspect(body, status="REPORTED"):
    return history.inspect_stored_response(json.dumps(body), status)


@pytest.mark.parametrize("kind, outcome, status", [
    ("reported", "OBSERVED_REPORTED", "REPORTED"),
    ("cleared", "OBSERVED_CLEARED", "CLEARED"),
])
@pytest.mark.parametrize("validation", ["PASS", "WARNING"])
def test_matching_declared_response_is_only_an_observation(kind, outcome, status, validation):
    body = response_body(kind)
    body["validationResults"]["status"] = validation
    raw = " \n" + json.dumps(body, ensure_ascii=False) + "\n "
    result = history.inspect_stored_response(raw, status)
    assert result.format == "JSON"
    assert result.outcome == outcome and result.issues == ()
    assert result.text_sha256 == hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(FrozenInstanceError):
        result.outcome = "ACCEPTED"
    if kind == "cleared":
        assert result.xml_candidates == (("clearedInvoice", xml_bytes()),)
        assert body["clearedInvoice"] not in repr(result)


@pytest.mark.parametrize("label", history.RESPONSE_LABELS)
@pytest.mark.parametrize("spacing", [" ", "<br>\n", "<br/> "])
def test_known_english_arabic_display_wrappers_do_not_authorize_http(label, spacing):
    text = f"Status Code: 401<br>{label}{spacing}{json.dumps(response_body())}<br><br/>"
    result = history.inspect_stored_response(text, "REPORTED")
    assert result.format == "LEGACY_DISPLAY"
    # The body declaration is observed; the contradictory display HTTP code is
    # not converted into an HTTP acceptance result or endpoint provenance.
    assert result.outcome == "OBSERVED_REPORTED"


@pytest.mark.parametrize("text, code", [
    ('{"a":1,"a":2}', "response_duplicate_key"),
    ('{"validationResults":{"status":"PASS","status":"ERROR"}}', "response_duplicate_key"),
    ('{} {}', "response_trailing_data"), ('{} DO-NOT-LEAK', "response_trailing_data"),
    ('[]', "response_object"), ('not JSON', "response_wrapper"),
    ('{"secret":"DO-NOT-LEAK"', "response_json"),
    ('prefix {unrelated} ZATCA Response: {}', "response_wrapper"),
    ('ZATCA Response: {} ZATCA Response: {}', "response_wrapper"),
    ('{"a":NaN}', "response_number"), ('{"a":Infinity}', "response_number"),
    ('{"a":1e999}', "response_number"), ('{"a":' + "9" * 65 + '}', "response_number"),
    ('{"a":[' * 1200, "response_json"),
])
def test_ambiguous_or_malformed_response_never_selects_first_json(text, code):
    found = history.inspect_stored_response(text, "REPORTED")
    assert found.format == "INVALID"
    assert found.outcome == "UNCONFIRMED"
    assert found.issues == (code,)
    assert "DO-NOT-LEAK" not in repr(found)


@pytest.mark.parametrize("value", [None, "", " ", "Not Submitted", "not submitted."])
def test_missing_response_is_not_an_acceptance_inference(value):
    result = history.inspect_stored_response(value, "CLEARED")
    assert result.format == "MISSING"
    assert result.issues == ("response_missing",)


@pytest.mark.parametrize("value, code", [
    ({}, "response_type"), (1, "response_type"),
    (b"\xff", "response_encoding"), ("\ud800", "response_encoding"),
])
def test_unusable_response_fields_are_static(value, code):
    assert history.inspect_stored_response(value, "REPORTED").issues == (code,)


def test_bytes_and_oversized_multibyte_fields(monkeypatch):
    raw = json.dumps(response_body()).encode()
    assert history.inspect_stored_response(raw, "REPORTED").outcome == "OBSERVED_REPORTED"
    monkeypatch.setattr(history, "MAX_RESPONSE_BYTES", 10)
    for value in ("x" * 11, b"x" * 11, "ع" * 6):
        assert history.inspect_stored_response(value, "REPORTED").issues == ("response_size",)


@pytest.mark.parametrize("validation", [
    None, {}, {"status": "PASS"}, {"status": "PASS", "errorMessages": None},
    {"status": "PASS", "errorMessages": [{}]},
    {"status": "ERROR", "errorMessages": []},
    {"status": "PASS", "errorMessages": [], "warningMessages": "bad"},
    {"status": "PASS", "errorMessages": [], "infoMessages": ["bad"]},
])
def test_declared_reported_status_does_not_hide_invalid_validation(validation):
    found = inspect(response_body(validationResults=validation))
    assert found.outcome == "UNCONFIRMED"
    assert "response_validation_unconfirmed" in found.issues
    assert "saved_status_response_unconfirmed" in found.issues


def test_compliance_pass_and_previously_completed_are_not_production_acceptance():
    passed = response_body("none", reportingStatus="NOT_REPORTED")
    assert inspect(passed, "Not Submitted").outcome == "UNCONFIRMED"
    previous = response_body("none", validationResults={
        "status": "ERROR", "errorMessages": [{"code": "Submitted before"}],
    })
    assert inspect(previous, "Not Submitted").outcome == "OBSERVED_REJECTED"


@pytest.mark.parametrize("status", ["Not Submitted", "CLEARED", ""])
def test_saved_status_response_disagreement_is_retained(status):
    assert "saved_status_response_mismatch" in inspect(response_body(), status).issues


def test_two_claimed_acceptance_types_are_ambiguous():
    found = inspect(response_body(clearanceStatus="CLEARED"))
    assert found.outcome == "UNCONFIRMED"
    assert "response_outcome_ambiguous" in found.issues


@pytest.mark.parametrize("status", ["UNKNOWN", True, {}])
def test_unknown_other_outcome_does_not_confirm_reported(status):
    found = inspect(response_body(clearanceStatus=status))
    assert found.outcome == "UNCONFIRMED"
    assert "response_outcome_unknown" in found.issues


def test_observed_rejection_never_overrides_saved_acceptance():
    body = response_body("none", validationResults={
        "status": "ERROR", "errorMessages": [{"code": "signed-properties-hashing"}],
    })
    found = inspect(body)
    assert found.outcome == "OBSERVED_REJECTED"
    assert found.issues == ("response_validation_rejected", "saved_status_response_unconfirmed")


@pytest.mark.parametrize("value, code", [
    (1, "response_xml_type"),
    ("%%%", "response_xml_base64"), ("ع", "response_xml_base64"),
])
def test_invalid_embedded_xml_is_reported_without_body_echo(value, code):
    found = inspect(response_body(reportedInvoice=value))
    assert code in found.issues
    assert found.xml_candidates == ()


def test_embedded_xml_size_checked_before_decode(monkeypatch):
    monkeypatch.setattr(history, "MAX_XML_BYTES", 10)
    for value in (base64.b64encode(b"x" * 20).decode(), base64.b64encode(b"x" * 11).decode()):
        assert "response_xml_size" in inspect(response_body(reportedInvoice=value)).issues


def test_missing_cleared_xml_and_wrong_xml_outcome_are_not_silenced():
    body = response_body("cleared")
    del body["clearedInvoice"]
    assert "response_cleared_xml_missing" in inspect(body, "CLEARED").issues
    body = response_body(clearedInvoice=base64.b64encode(xml_bytes()).decode())
    assert "response_xml_outcome_mismatch" in inspect(body).issues


@pytest.mark.parametrize("value", [None, "", " "])
def test_nullable_optional_xml_is_not_a_malformed_reporting_response(value):
    result = inspect(response_body(reportedInvoice=value, clearedInvoice=value))
    assert result.issues == ()
    assert result.xml_candidates == ()
    body = response_body("cleared", clearedInvoice=value)
    assert inspect(body, "CLEARED").issues == ("response_cleared_xml_missing",)


def counter_values(**changes):
    values = dict(name="legacy-key", counter_key="legacy-key", company="TEST",
                  issuing_unit="existing-chain", environment="Production", active=1,
                  last_issued_icv=77, last_invoice="INV-TEST", last_invoice_doctype="Sales Invoice")
    values.update(changes)
    return values


@pytest.mark.parametrize("api_environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("position", [77, "077", 78, "100"])
def test_counter_purpose_is_not_api_environment(api_environment, position):
    saved = saved_identity(environment=api_environment)
    assert history.compare_counter_evidence(saved, counter_values(last_issued_icv=position), "legacy-key") == ()


@pytest.mark.parametrize("changes, code", [
    ({"company": "OTHER"}, "counter_company_mismatch"),
    ({"issuing_unit": "OTHER"}, "counter_unit_mismatch"),
    ({"environment": "Simulation"}, "counter_purpose_mismatch"),
    ({"environment": "Compliance"}, "counter_purpose_mismatch"),
    ({"name": "other-key"}, "counter_key_mismatch"),
    ({"counter_key": "other-key"}, "counter_key_mismatch"),
    ({"active": 0}, "counter_inactive"), ({"active": "0"}, "counter_inactive"),
    ({"active": "unknown"}, "counter_active_invalid"),
    ({"last_issued_icv": None}, "counter_position_invalid"),
    ({"last_issued_icv": -1}, "counter_position_invalid"),
    ({"last_issued_icv": "1.2"}, "counter_position_invalid"),
    ({"last_issued_icv": "9" * 65}, "counter_position_invalid"),
    ({"last_issued_icv": 0}, "counter_below_invoice"),
    ({"last_issued_icv": 76}, "counter_below_invoice"),
    ({"last_invoice": "OTHER"}, "counter_tail_invoice_mismatch"),
    ({"last_invoice_doctype": "POS Invoice"}, "counter_tail_doctype_mismatch"),
])
def test_counter_conflicts_are_explicit_without_seed_or_rewind(changes, code):
    values = counter_values(**changes)
    before = values.copy()
    assert history.compare_counter_evidence(saved_identity(), values, "legacy-key") == (code,)
    assert values == before


def test_historical_invoice_does_not_need_to_be_the_current_counter_tail():
    values = counter_values(last_issued_icv=78, last_invoice="NEXT", last_invoice_doctype="POS Invoice")
    assert history.compare_counter_evidence(saved_identity(), values, "legacy-key") == ()


def test_missing_saved_icv_remains_unreconciled():
    assert history.compare_counter_evidence(saved_identity(icv=None), counter_values(), "legacy-key") == ("saved_icv_invalid",)
