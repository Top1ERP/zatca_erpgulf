"""Framework-independent route contracts; all addresses are test inputs only."""

from dataclasses import FrozenInstanceError

import pytest

from zatca_erpgulf.zatca_erpgulf.api_routing import (
    ApiConfigurationError, ENVIRONMENT_FIELDS, GATEWAY_PATHS,
    OPERATION_CREDENTIALS, resolve_api_route,
)


def settings(environment="Production"):
    return {
        "custom_select": environment,
        **{
            field: "https://gw-fatoora.zatca.gov.sa" + GATEWAY_PATHS[name] + "/"
            for name, field in ENVIRONMENT_FIELDS.items()
        },
    }


@pytest.mark.parametrize("environment", list(ENVIRONMENT_FIELDS))
@pytest.mark.parametrize("operation,credential", list(OPERATION_CREDENTIALS.items()))
def test_all_existing_operations_have_an_explicit_environment_and_credential_purpose(environment, operation, credential):
    route = resolve_api_route(settings(environment), operation)
    assert route.environment == environment
    assert route.endpoint == operation
    assert route.required_credential == credential
    assert route.base_url_field == ENVIRONMENT_FIELDS[environment]
    assert route.url == "https://gw-fatoora.zatca.gov.sa" + GATEWAY_PATHS[environment] + "/" + operation


@pytest.mark.parametrize("environment", [None, "", "  ", "invalid", "production", 0, False])
def test_missing_or_unknown_environment_fails_closed(environment):
    with pytest.raises(ApiConfigurationError, match="^environment$"):
        resolve_api_route(settings(environment), "compliance/invoices")


@pytest.mark.parametrize("override", ["", " ", "invalid", False])
def test_explicit_invalid_override_cannot_fall_back_to_company(override):
    with pytest.raises(ApiConfigurationError, match="^environment$"):
        resolve_api_route(settings(), "compliance", environment=override)


def test_valid_override_is_local_and_does_not_change_company_selection():
    config = settings()
    route = resolve_api_route(config, "compliance", environment=" Sandbox ")
    assert route.environment == "Sandbox"
    assert config["custom_select"] == "Production"


@pytest.mark.parametrize("operation", [None, "", 0, "../compliance", "compliance?x=y",
                                       "https://example.invalid/compliance", "compliance//invoices",
                                       "compliance%2finvoices", "invoices/reporting/single#fragment"])
def test_unknown_or_ambiguous_operations_are_rejected(operation):
    with pytest.raises(ApiConfigurationError, match="^operation$"):
        resolve_api_route(settings(), operation)


@pytest.mark.parametrize("base", [
    None, "", " ", "http://example.invalid/base", "https:///base", "/relative",
    "https://user:secret@example.invalid/base", "https://example.invalid/base?secret=private-value",
    "https://example.invalid/base#fragment", "https://example.invalid/base?",
    "https://example.invalid/base#", "https://example.invalid\\base",
    "https://example.invalid/a/../base", "https://example.invalid/a/./base",
    "https://example.invalid/a//base", "https://example.invalid/%2e%2e/base",
    "https://example.invalid/a b", "https://example.invalid/a\nb",
    "https://example.invalid/\x7f", "https://example.invalid:0/base",
    "https://example.invalid:99999/base", "https://example.invalid:abc/base",
    "https://[malformed/base",
])
def test_malformed_bases_do_not_leak_the_configured_value(base):
    config = settings()
    config["custom_production_url"] = base
    with pytest.raises(ApiConfigurationError, match="^base_url$") as raised:
        resolve_api_route(config, "compliance/invoices")
    assert "private-value" not in str(raised.value)


@pytest.mark.parametrize("environment", list(ENVIRONMENT_FIELDS))
@pytest.mark.parametrize("wrong_path", list(GATEWAY_PATHS.values()))
def test_standard_gateway_base_must_match_selected_environment(environment, wrong_path):
    config = settings(environment)
    config[ENVIRONMENT_FIELDS[environment]] = "https://gw-fatoora.zatca.gov.sa" + wrong_path
    if wrong_path == GATEWAY_PATHS[environment]:
        assert resolve_api_route(config, "compliance").environment == environment
    else:
        with pytest.raises(ApiConfigurationError, match="^environment_url$"):
            resolve_api_route(config, "compliance")


@pytest.mark.parametrize("base", [
    "https://GW-FATOORA.ZATCA.GOV.SA/e-invoicing/core/",
    "https://gw-fatoora.zatca.gov.sa./e-invoicing/core/",
    "https://gw-fatoora.zatca.gov.sa:443/e-invoicing/core/",
])
def test_standard_gateway_alias_forms_cannot_hide_an_environment_mismatch(base):
    config = settings("Sandbox")
    config["custom_sandbox_url"] = base
    with pytest.raises(ApiConfigurationError, match="^environment_url$"):
        resolve_api_route(config, "compliance")


@pytest.mark.parametrize("operation", ["compliance", "compliance/invoices", "production/csids"])
def test_production_onboarding_remains_supported(operation):
    route = resolve_api_route(settings(), operation, onboarding_only=True)
    assert route.environment == "Production"
    assert route.required_credential != "production"


@pytest.mark.parametrize("operation", ["invoices/reporting/single", "invoices/clearance/single"])
def test_onboarding_cannot_select_a_live_invoice_operation(operation):
    with pytest.raises(ApiConfigurationError, match="^onboarding_operation$"):
        resolve_api_route(settings(), operation, onboarding_only=True)


def test_custom_https_gateway_is_retained_without_claiming_its_environment_is_verified():
    config = settings("Simulation")
    config["custom_simulation_url"] = " https://proxy.example.invalid:8443/configured-base "
    route = resolve_api_route(config, "/invoices/reporting/single/")
    assert route.url == "https://proxy.example.invalid:8443/configured-base/invoices/reporting/single"
    assert route.environment == "Simulation"


def test_unused_environment_fields_do_not_override_the_selected_one():
    config = settings("Sandbox")
    config["custom_production_url"] = "INVALID"
    config["custom_simulation_url"] = None
    assert resolve_api_route(config, "compliance").environment == "Sandbox"


def test_route_is_an_immutable_snapshot_without_credential_fields():
    config = settings()
    config["custom_private_key"] = "private-marker"
    route = resolve_api_route(config, "compliance")
    config["custom_select"] = "Sandbox"
    assert route.environment == "Production"
    assert "private-marker" not in repr(route)
    with pytest.raises(FrozenInstanceError):
        route.environment = "Sandbox"
