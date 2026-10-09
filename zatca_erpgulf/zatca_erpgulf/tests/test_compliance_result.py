"""Pure result-contract tests; no Frappe installation or ZATCA access needed."""

from copy import deepcopy

import pytest

from zatca_erpgulf.zatca_erpgulf.compliance_result import (
    compliance_result_status,
    is_already_completed_response,
)


@pytest.mark.parametrize("status", ["PASS", "WARNING"])
@pytest.mark.parametrize("errors", [{}, {"errorMessages": []}])
def test_explicit_success_and_warning_are_accepted(status, errors):
    response = {"validationResults": {"status": status, **errors}}
    assert compliance_result_status(response) == "PASS"


@pytest.mark.parametrize("response", [
    None, True, 1, "PASS", [], {}, ("error in compliance", "NOT ACCEPTED"),
    {"validationResults": None}, {"validationResults": []},
    {"validationResults": "PASS"}, {"validationResults": {}},
    {"validationResults": {"status": "PENDING"}},
    {"validationResults": {"status": "ERROR"}},
    {"validationResults": {"infoMessages": [{"status": "PASS", "code": "XSD_ZATCA_VALID"}]}},
    {"_zatca_compliance_status": "ALREADY_COMPLETED"},
    {"_zatca_compliance_status": "PASS", "validationResults": {"status": "PASS"}},
])
def test_unknown_or_partial_results_do_not_prove_compliance(response):
    assert compliance_result_status(response) is None


@pytest.mark.parametrize("errors", [None, False, "", {}, "Submitted before",
                                    ["unexpected"], [{"code": "QRCODE_INVALID"}]])
def test_pass_with_invalid_or_nonempty_errors_is_rejected(errors):
    response = {"validationResults": {"status": "PASS", "errorMessages": errors}}
    assert compliance_result_status(response) is None


@pytest.mark.parametrize("errors", [None, [], {}, "Submitted before", ["unexpected"],
                                    [{"code": "Submitted before"}, None],
                                    [{"code": "Submitted before"}, {"code": "QRCODE_INVALID"}]])
def test_previous_completion_requires_every_error_to_match(errors):
    response = {"validationResults": {"status": "ERROR", "errorMessages": errors}}
    assert not is_already_completed_response(406, response)
    response["_zatca_compliance_status"] = "ALREADY_COMPLETED"
    assert compliance_result_status(response) is None


@pytest.mark.parametrize("status_code", [200, 202, 400, 401, 403, 500])
def test_previous_completion_requires_http_406(status_code):
    response = {"validationResults": {
        "status": "ERROR", "errorMessages": [{"code": "Submitted before"}],
    }}
    assert not is_already_completed_response(status_code, response)


def test_previous_completion_requires_boundary_marker_and_does_not_mutate_input():
    response = {"validationResults": {
        "status": "ERROR", "errorMessages": [{"code": "Submitted before"}],
    }}
    original = deepcopy(response)
    assert is_already_completed_response(406, response)
    assert compliance_result_status(response) is None
    assert response == original
    response["_zatca_compliance_status"] = "ALREADY_COMPLETED"
    marked = deepcopy(response)
    assert compliance_result_status(response) == "ALREADY_COMPLETED"
    assert response == marked


@pytest.mark.parametrize("validation", [None, [], "ERROR", {}, {"status": "PASS"}])
def test_previous_completion_rejects_invalid_validation_object(validation):
    assert not is_already_completed_response(406, {"validationResults": validation})
