"""Compliance boundary regressions; all HTTP and Frappe I/O is mocked.

These tests exercise the real API and button functions without a site, customer,
invoice, certificate, or ZATCA connection. A transport failure must never unlock
the next onboarding step by producing a successful summary.
"""

import csv
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from zatca_erpgulf.zatca_erpgulf import sign_invoice as buttons
from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client


class LocalValidationError(Exception):
    pass


class Document(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


def raise_validation(message, *args, **kwargs):
    raise LocalValidationError(str(message))


def success_response(status="PASS"):
    return {"validationResults": {"status": status, "errorMessages": []}}


def already_completed_response():
    return {
        "validationResults": {
            "status": "ERROR",
            "errorMessages": [{"code": "Submitted before", "category": "Compliance-Check"}],
        }
    }


@pytest.fixture
def boundary(monkeypatch):
    company = Document(
        doctype="Company", name="TEST COMPANY", abbr="TC",
        custom_validation_type="ORIGINAL TYPE",
        custom_basic_auth_from_csid="mock-credential",
        custom_select="Production", db_set=Mock(),
    )
    frappe = SimpleNamespace(
        get_doc=Mock(return_value=company),
        db=SimpleNamespace(get_value=Mock(return_value=company.name)),
        throw=raise_validation, ValidationError=LocalValidationError, msgprint=Mock(),
    )
    for module in (client, buttons):
        monkeypatch.setattr(module, "frappe", frappe)
        monkeypatch.setattr(module, "_", lambda message: message)
    monkeypatch.setattr(client, "get_compliance_api_url", lambda *args: "https://example.invalid/compliance/invoices")
    monkeypatch.setattr(client, "xml_base64_decode", lambda *args: "MOCK_XML")
    request = Mock(side_effect=AssertionError("Unconfigured HTTP mock"))
    monkeypatch.setattr(client.requests, "request", request)
    return company, frappe, request


def call_client():
    return client.compliance_api_call("mock-uuid", "mock-hash", "unused.xml", "TC", None)


def run_button(company, automatic):
    # Skip only Frappe's HTTP type-validation wrapper; no site is initialized.
    if automatic:
        return inspect.unwrap(buttons.run_automatic_zatca_onboarding_checks)(company.name)
    return inspect.unwrap(buttons.run_all_compliance_summary)(company.name, "TEST-INVOICE")


def set_http_response(request, status_code, body):
    response = SimpleNamespace(
        status_code=status_code, json=Mock(return_value=body),
        text=json.dumps(body), headers={"x-request-id": "mock-request-id"}, reason="Test response",
    )
    request.side_effect = None
    request.return_value = response


@pytest.mark.parametrize("error", [requests.Timeout("mock timeout"), requests.ConnectionError("mock offline")])
def test_transport_error_raises_instead_of_returning_a_success_shaped_tuple(boundary, error):
    _, _, request = boundary
    request.side_effect = error
    with pytest.raises(LocalValidationError):
        call_client()


@pytest.mark.parametrize("status_code", [200, 202])
@pytest.mark.parametrize("payload", [None, {}, "", "OK", [], {"validationResults": {}},
                                     {"validationResults": []},
                                     {"validationResults": {"status": "PENDING"}},
                                     {"validationResults": {"status": "ERROR"}},
                                     {"validationResults": {"status": "PASS", "errorMessages": [{"code": "QRCODE_INVALID"}]}}])
def test_http_success_is_not_itself_proof_of_compliance(boundary, payload, status_code):
    _, _, request = boundary
    set_http_response(request, status_code, payload)
    with pytest.raises(LocalValidationError):
        call_client()


@pytest.mark.parametrize("status_code", [200, 202])
@pytest.mark.parametrize("validation_status", ["PASS", "WARNING"])
def test_confirmed_validation_is_preserved(boundary, status_code, validation_status):
    _, _, request = boundary
    payload = success_response(validation_status)
    set_http_response(request, status_code, payload)
    assert call_client() == payload


def test_documented_406_is_distinguished_as_previously_completed(boundary):
    _, _, request = boundary
    set_http_response(request, 406, already_completed_response())
    assert call_client()["_zatca_compliance_status"] == "ALREADY_COMPLETED"


@pytest.mark.parametrize("errors", [["unexpected value"], [{"code": "Submitted before"}, "unexpected value"],
                                    [{"code": "Submitted before"}, {"code": "QRCODE_INVALID"}]])
def test_406_cannot_skip_malformed_or_additional_errors(boundary, errors):
    _, _, request = boundary
    payload = {"validationResults": {"status": "ERROR", "errorMessages": errors}}
    set_http_response(request, 406, payload)
    with pytest.raises(LocalValidationError):
        call_client()


@pytest.mark.parametrize("status_code", [400, 401, 403, 500])
def test_http_failures_remain_failures_with_request_id(boundary, status_code):
    _, _, request = boundary
    set_http_response(request, status_code, {"message": "Mock rejection"})
    with pytest.raises(LocalValidationError, match="mock-request-id"):
        call_client()


@pytest.mark.parametrize("payload", [None, {}, ("error in compliance", "NOT ACCEPTED"),
                                     {"validationResults": {"status": "ERROR"}}])
@pytest.mark.parametrize("automatic", [False, True])
def test_both_buttons_reject_unconfirmed_results(boundary, monkeypatch, payload, automatic):
    company, _, _ = boundary
    monkeypatch.setattr(buttons, "zatca_call_compliance", Mock(return_value=payload))
    monkeypatch.setattr(buttons, "_submit_onboarding_document", Mock(return_value=payload))
    result = run_button(company, automatic)
    assert len(result["results"]) == 6
    assert all(row["status"] == "FAIL" for row in result["results"])
    if automatic:
        assert result["passed"] == 0
        assert result["failed"] == 6
        assert result["all_passed"] is False
    else:
        company.db_set.assert_not_called()
        assert company.custom_validation_type == "ORIGINAL TYPE"


@pytest.mark.parametrize("automatic", [False, True])
def test_confirmed_button_results_still_pass(boundary, monkeypatch, automatic):
    company, _, _ = boundary
    monkeypatch.setattr(buttons, "zatca_call_compliance", Mock(return_value=success_response()))
    monkeypatch.setattr(buttons, "_submit_onboarding_document", Mock(return_value=success_response()))
    result = run_button(company, automatic)
    assert all(row["status"] == "PASS" for row in result["results"])


@pytest.mark.parametrize("automatic", [False, True])
def test_previous_completion_remains_visible_in_both_button_results(boundary, monkeypatch, automatic):
    company, _, request = boundary
    set_http_response(request, 406, already_completed_response())
    monkeypatch.setattr(buttons, "zatca_call_compliance", lambda **kwargs: call_client())
    monkeypatch.setattr(buttons, "_submit_onboarding_document", lambda *args: call_client())
    result = run_button(company, automatic)
    assert len(result["results"]) == 6
    assert all(row["status"] == "PASS" for row in result["results"])
    assert all(row["compliance_status"] == "ALREADY_COMPLETED" for row in result["results"])
    assert all("Already completed" in row["message"] for row in result["results"])
    assert request.call_count == 6


@pytest.mark.parametrize("automatic", [False, True])
def test_transport_failure_propagates_through_both_buttons(boundary, monkeypatch, automatic):
    company, _, request = boundary
    # Do not leak exception details which may contain URLs or credentials.
    request.side_effect = requests.Timeout("secret-transport-detail")
    monkeypatch.setattr(buttons, "zatca_call_compliance", lambda **kwargs: call_client())
    monkeypatch.setattr(buttons, "_submit_onboarding_document", lambda *args: call_client())
    result = run_button(company, automatic)
    assert len(result["results"]) == 6
    assert all(row["status"] == "FAIL" for row in result["results"])
    assert all("secret-transport-detail" not in row["message"] for row in result["results"])
    assert request.call_count == 6
    if automatic:
        assert result["all_passed"] is False


@pytest.mark.parametrize("automatic", [False, True])
def test_one_failed_type_prevents_overall_completion(boundary, monkeypatch, automatic):
    company, _, _ = boundary
    responses = [success_response() for _ in range(6)]
    responses[2] = {"validationResults": {"status": "ERROR"}}
    submit = Mock(side_effect=responses)
    monkeypatch.setattr(buttons, "zatca_call_compliance", submit)
    monkeypatch.setattr(buttons, "_submit_onboarding_document", submit)
    result = run_button(company, automatic)
    assert [row["status"] for row in result["results"]] == [
        "PASS", "PASS", "FAIL", "PASS", "PASS", "PASS",
    ]
    if automatic:
        assert result["passed"] == 5
        assert result["failed"] == 1
        assert result["all_passed"] is False


def test_non_json_http_success_is_rejected(boundary):
    _, _, request = boundary
    set_http_response(request, 200, None)
    request.return_value.json.side_effect = ValueError("Mock non-JSON response")
    request.return_value.text = "<html>Proxy response</html>"
    with pytest.raises(LocalValidationError, match="did not confirm compliance"):
        call_client()


@pytest.mark.parametrize("response", [{}, success_response()])
def test_forged_previous_completion_marker_on_http_200_is_rejected(boundary, response):
    _, _, request = boundary
    payload = {**response, "_zatca_compliance_status": "ALREADY_COMPLETED"}
    set_http_response(request, 200, payload)
    with pytest.raises(LocalValidationError):
        call_client()


def test_new_error_messages_have_arabic_translations():
    translation_file = Path(__file__).resolve().parents[2] / "translations" / "ar.csv"
    with translation_file.open(encoding="utf-8", newline="") as source:
        translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
    for message in (
        "ZATCA did not confirm compliance. This check cannot be marked as passed.",
        "The ZATCA compliance request could not be completed. Check the connection and try again; compliance has not been confirmed.",
        "Already completed by ZATCA; treated as PASS.",
        "Select a valid ZATCA compliance document type.",
        "Debug XML was skipped for an intra-company transfer. The invoice was not changed.",
        "Select a valid ZATCA environment: Sandbox, Simulation, or Production.",
        "Unsupported ZATCA API operation.",
        "This operation is not part of ZATCA onboarding.",
        "Configure a valid HTTPS base URL for the selected ZATCA environment.",
        "The ZATCA URL does not match the selected environment.",
    ):
        assert any("\u0600" <= char <= "\u06ff" for char in translations[message])
