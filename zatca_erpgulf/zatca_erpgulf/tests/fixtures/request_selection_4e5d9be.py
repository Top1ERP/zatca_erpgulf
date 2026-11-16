"""Frozen increment229 request-selection functions; offline reference."""

SOURCES = {
'zatca_erpgulf/zatca_erpgulf/submission_context.py': r'''
def get_submission_context(
    company_abbr, source_doc, invoice_number, endpoint, *, expected_doctype=None,
    require_issuing_unit=False,
):
    """Validate the target and select Production-purpose auth before sending.

    Production-purpose credentials are also used for simulated reporting and
    clearance; the configured environment is preserved, never forced to Core.
    No credential is loaded for an operation outside these two adapters.
    """
    if endpoint not in ("invoices/reporting/single", "invoices/clearance/single"):
        frappe.throw(_("This submission path supports reporting or clearance only."))
    if (
        source_doc.doctype not in ("Sales Invoice", "POS Invoice")
        or (expected_doctype is not None and source_doc.doctype != expected_doctype)
        or not invoice_number or source_doc.name != invoice_number
    ):
        frappe.throw(_("The ZATCA submission target must match the source invoice."))
    if require_issuing_unit:
        # Machine-specific legacy entry points must not silently fall back to
        # Company credentials. Check the saved link, not a caller-supplied DTO.
        saved_source = frappe.get_doc(source_doc.doctype, source_doc.name)
        if not saved_source.get("custom_zatca_pos_name"):
            frappe.throw(_("A saved ZATCA issuing unit is required for this XML submission path."))
    route = get_company_api_route(company_abbr, endpoint)
    authorization = get_api_authorization(
        company_abbr, source_doc, purpose=route.required_credential
    )
    return SubmissionContext(route, authorization)
''',
'zatca_erpgulf/zatca_erpgulf/api_settings.py': r'''
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
''',
'zatca_erpgulf/zatca_erpgulf/credential_settings.py': r'''
def resolve_credential_owner(company_abbr, source_doc=None) -> CredentialOwner:
    """Resolve Company, own-device, or explicitly linked-company credentials."""
    try:
        company = frappe.get_doc("Company", {"abbr": company_abbr})
        return _resolve_owner_from_saved_company(company, source_doc)
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)

def get_previous_invoice_hash(company_abbr, source_doc):
    """Read PIH from the signing owner without projecting credential fields.

    No fallback from an empty device PIH to Company PIH is permitted. Never
    initialize, repair, reset or advance a chain based on an empty saved field.
    """
    from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import (
        MISSING_PREVIOUS_HASH, previous_hash_value,
    )

    company = frappe.get_doc("Company", {"abbr": company_abbr})
    try:
        owner, _kind = _resolve_owner_record_from_saved_company(company, source_doc)
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)
    try:
        return previous_hash_value(owner.get("custom_pih"))
    except ValueError:
        pass
    # Outside the handler: do not expose the rejected field or its exception.
    frappe.throw(_(MISSING_PREVIOUS_HASH))

def get_signing_key(company_abbr, source_doc=None):
    """Load one owner snapshot and reject a key/certificate mismatch before signing."""
    try:
        owner = resolve_credential_owner(company_abbr, source_doc)
        certificate = _parse_certificate(_certificate_for_owner(owner))
        value = owner.values.get("custom_private_key")
        if not isinstance(value, str) or not value.strip():
            raise CredentialConfigurationError("private_key")
        try:
            key = serialization.load_pem_private_key(value.encode("utf-8"), password=None)
        except (TypeError, ValueError):
            raise CredentialConfigurationError("private_key") from None
        options = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if key.public_key().public_bytes(*options) != certificate.public_key().public_bytes(*options):
            raise CredentialConfigurationError("key_mismatch")
        return key
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)

def get_api_authorization(company_abbr, source_doc=None, *, purpose):
    """Resolve the same owner policy as signing, then select a purpose-specific field."""
    try:
        return authorization_for_owner(resolve_credential_owner(company_abbr, source_doc), purpose)
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)
''',
}
