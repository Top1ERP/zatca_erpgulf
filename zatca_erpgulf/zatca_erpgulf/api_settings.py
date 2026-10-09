"""Read-only Frappe adapter for the pure ZATCA route resolver."""

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.api_routing import (
    ENVIRONMENT_FIELDS, ApiConfigurationError, ApiRoute, resolve_api_route,
)


def get_company_api_route(
    company_abbr, endpoint, *, environment=None, onboarding_only=False
) -> ApiRoute:
    """Resolve routing fields without using credentials or repairing settings."""
    company = frappe.get_doc("Company", {"abbr": company_abbr})
    settings = {
        name: company.get(name)
        for name in ("custom_select", *ENVIRONMENT_FIELDS.values())
    }
    try:
        return resolve_api_route(
            settings, endpoint, environment=environment, onboarding_only=onboarding_only
        )
    except ApiConfigurationError as error:
        messages = {
            "environment": _("Select a valid ZATCA environment: Sandbox, Simulation, or Production."),
            "operation": _("Unsupported ZATCA API operation."),
            "onboarding_operation": _("This operation is not part of ZATCA onboarding."),
            "base_url": _("Configure a valid HTTPS base URL for the selected ZATCA environment."),
            "environment_url": _("The ZATCA URL does not match the selected environment."),
        }
        frappe.throw(messages[error.code])
