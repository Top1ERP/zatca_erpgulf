"""URL boundary regressions. No site, credentials, or network are required."""

import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import (
    api_settings,
    sales_invoice_with_xmlqr,
    sign_invoice,
    sign_invoice_first,
    submit_poswithqr_notmultiple,
    submit_xml_qr_notmultiple,
    wizardbutton,
)


MODULES = (
    sales_invoice_with_xmlqr, sign_invoice, sign_invoice_first,
    submit_poswithqr_notmultiple, submit_xml_qr_notmultiple, wizardbutton,
)
BASES = {
    "Sandbox": "https://example.invalid/developer-portal/",
    "Simulation": "https://example.invalid/simulation/",
    "Production": "https://example.invalid/core/",
}


class Document(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class ValidationError(Exception):
    pass


def fail(message, *args, **kwargs):
    raise ValidationError(str(message))


@pytest.fixture
def routing(monkeypatch):
    company = Document(
        name="TEST COMPANY", doctype="Company", abbr="TC", custom_select="Production",
        custom_sandbox_url=BASES["Sandbox"], custom_simulation_url=BASES["Simulation"],
        custom_production_url=BASES["Production"],
        custom_csr_data="mock-csr", custom_otp="000000", save=Mock(),
        custom_basic_auth_from_csid="mock-compliance",
        custom_basic_auth_from_production="mock-production",
        custom_compliance_request_id_="mock-compliance-request",
    )
    frappe = SimpleNamespace(
        get_doc=Mock(return_value=company), throw=fail, ValidationError=ValidationError,
        db=SimpleNamespace(get_value=Mock(return_value=company.name)),
        publish_realtime=Mock(), session=SimpleNamespace(user="TEST USER"), msgprint=Mock(),
    )
    for module in (*MODULES, api_settings):
        monkeypatch.setattr(module, "frappe", frappe)
        monkeypatch.setattr(module, "_", lambda message: message)
    return company, frappe


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("environment", list(BASES))
def test_each_legacy_entry_point_preserves_the_selected_environment(routing, module, environment):
    company, _ = routing
    company.custom_select = environment
    assert module.get_api_url("TC", "invoices/reporting/single") == BASES[environment] + "invoices/reporting/single"


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("environment", [None, "", " ", "invalid", "production"])
def test_invalid_selection_never_falls_through_to_production(routing, module, environment):
    company, _ = routing
    company.custom_select = environment
    with pytest.raises(ValidationError):
        module.get_api_url("TC", "invoices/reporting/single")


@pytest.mark.parametrize("module", MODULES)
def test_spacing_and_missing_separator_are_normalized_consistently(routing, module):
    company, _ = routing
    company.custom_select = " Sandbox "
    company.custom_sandbox_url = " https://example.invalid/developer-portal "
    assert module.get_api_url("TC", "/invoices/reporting/single") == BASES["Sandbox"] + "invoices/reporting/single"


@pytest.mark.parametrize("endpoint", ["invoices/reporting/single", "invoices/clearance/single"])
def test_onboarding_url_helper_cannot_build_live_submission_routes(routing, endpoint):
    with pytest.raises(ValidationError):
        sign_invoice_first.get_compliance_api_url("TC", endpoint)


@pytest.mark.parametrize("environment", list(BASES))
def test_create_csid_uses_selected_environment_without_changing_settings(routing, monkeypatch, environment):
    company, _ = routing
    company.custom_select = environment
    post = Mock(return_value=SimpleNamespace(status_code=400, text="Mock rejection", headers={}))
    monkeypatch.setattr(sign_invoice_first.requests, "post", post)
    with pytest.raises(ValidationError, match="Mock rejection"):
        inspect.unwrap(sign_invoice_first.create_csid)({"doctype": "Company", "name": company.name}, "TC")
    assert post.call_args.kwargs["url"] == BASES[environment] + "compliance"
    assert post.call_args.kwargs["headers"]["OTP"] == "000000"
    assert company.custom_select == environment
    company.save.assert_not_called()


@pytest.mark.parametrize("portal", [None, "", "invalid"])
def test_invalid_csid_environment_never_sends_otp(routing, monkeypatch, portal):
    company, frappe = routing
    company.custom_select = ""
    post = Mock(side_effect=AssertionError("Must not send OTP"))
    monkeypatch.setattr(sign_invoice_first.requests, "post", post)
    with pytest.raises(ValidationError, match="Select a valid ZATCA environment"):
        inspect.unwrap(sign_invoice_first.create_csid)(
            {"doctype": "Company", "name": company.name}, "TC", portal_type=portal,
        )
    post.assert_not_called()
    frappe.publish_realtime.assert_not_called()


def test_explicit_csid_override_does_not_modify_company(routing, monkeypatch):
    company, _ = routing
    post = Mock(return_value=SimpleNamespace(status_code=400, text="Mock rejection", headers={}))
    monkeypatch.setattr(sign_invoice_first.requests, "post", post)
    with pytest.raises(ValidationError, match="Sandbox"):
        inspect.unwrap(sign_invoice_first.create_csid)(
            {"doctype": "Company", "name": company.name}, "TC", portal_type="Sandbox",
        )
    assert post.call_args.kwargs["url"] == BASES["Sandbox"] + "compliance"
    assert company.custom_select == "Production"
    company.save.assert_not_called()


@pytest.mark.parametrize("environment", list(BASES))
def test_final_csid_still_uses_compliance_auth_in_selected_environment(routing, monkeypatch, environment):
    company, _ = routing
    company.custom_select = environment
    post = Mock(return_value=SimpleNamespace(status_code=400, text="Mock rejection", headers={}, reason="Test"))
    monkeypatch.setattr(sign_invoice_first.requests, "post", post)
    with pytest.raises(ValidationError, match="Mock rejection"):
        inspect.unwrap(sign_invoice_first.production_csid)(
            {"doctype": "Company", "name": company.name}, "TC",
        )
    assert post.call_args.kwargs["url"] == BASES[environment] + "production/csids"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Basic mock-compliance"


@pytest.mark.parametrize("environment", list(BASES))
def test_compliance_invoice_request_uses_onboarding_endpoint_and_auth(routing, monkeypatch, environment):
    company, _ = routing
    company.custom_select = environment
    request = Mock(return_value=SimpleNamespace(
        status_code=200, json=lambda: {"validationResults": {"status": "PASS"}},
    ))
    monkeypatch.setattr(sign_invoice_first.requests, "request", request)
    monkeypatch.setattr(sign_invoice_first, "xml_base64_decode", lambda *args: "MOCK_XML")
    result = sign_invoice_first.compliance_api_call("uuid", "hash", "unused.xml", "TC", None)
    assert result["validationResults"]["status"] == "PASS"
    assert request.call_args.kwargs["url"] == BASES[environment] + "compliance/invoices"
    assert request.call_args.kwargs["headers"]["Authorization"] == "Basic mock-compliance"


def test_diagnostics_does_not_invent_production_when_selection_is_missing(routing):
    company, _ = routing
    company.custom_select = ""
    with pytest.raises(ValidationError, match="Select a valid ZATCA environment"):
        sign_invoice_first._csid_material_diagnostics(company.name)


@pytest.mark.parametrize("operation", ["compliance", "final_csid"])
def test_missing_environment_blocks_requests_with_existing_credentials(routing, monkeypatch, operation):
    company, frappe = routing
    company.custom_select = ""
    request = Mock(side_effect=AssertionError("Must not send credentials"))
    monkeypatch.setattr(sign_invoice_first.requests, "request", request)
    monkeypatch.setattr(sign_invoice_first.requests, "post", request)
    monkeypatch.setattr(sign_invoice_first, "xml_base64_decode", lambda *args: "MOCK_XML")
    with pytest.raises(ValidationError, match="Select a valid ZATCA environment"):
        if operation == "compliance":
            sign_invoice_first.compliance_api_call("uuid", "hash", "unused.xml", "TC", None)
        else:
            inspect.unwrap(sign_invoice_first.production_csid)(
                {"doctype": "Company", "name": company.name}, "TC",
            )
    request.assert_not_called()
    frappe.publish_realtime.assert_not_called()


def test_adapter_uses_only_routing_fields_and_does_not_save_company(routing, monkeypatch):
    company, frappe = routing
    getter = Mock(wraps=company.get)
    monkeypatch.setattr(company, "get", getter)
    route = api_settings.get_company_api_route("TC", "compliance/invoices")
    assert route.required_credential == "compliance"
    assert {call.args[0] for call in getter.call_args_list} == {
        "custom_select", "custom_sandbox_url", "custom_simulation_url", "custom_production_url",
    }
    frappe.get_doc.assert_called_once_with("Company", {"abbr": "TC"})
    company.save.assert_not_called()
