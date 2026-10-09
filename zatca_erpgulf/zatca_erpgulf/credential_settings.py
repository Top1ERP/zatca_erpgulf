"""Read-only owner resolution shared by signing and HTTP authentication.

Only saved document identity is trusted from caller-supplied objects/JSON. Keys
and credential values are always read from the selected saved owner. No field
repair, certificate migration, key generation, save, or commit occurs here.
"""

import json
from types import MappingProxyType

import frappe
from frappe import _
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_group
from zatca_erpgulf.zatca_erpgulf.credential_material import (
    CredentialConfigurationError, CredentialOwner, authorization_for_owner,
    certificate_value, use_linked_company,
)


SECRET_FIELDS = (
    "custom_private_key", "custom_certificate", "custom_certficate",
    "custom_basic_auth_from_csid", "custom_basic_auth_from_production", "custom_final_auth_csid",
)


def _throw_configuration_error(error):
    messages = {
        "source": _("A saved Company, Sales Invoice, POS Invoice, or ZATCA Multiple Setting is required for credential selection."),
        "company": _("The ZATCA credential source does not belong to the selected company."),
        "linked_company": _("The ZATCA issuing unit requires a valid linked company."),
        "taxpayer": _("Linked ZATCA credentials require matching nonempty company Tax IDs."),
        "link_flag": _("The Use Company Certificate and Keys setting must be enabled or disabled explicitly."),
        "certificate": _("A valid saved ZATCA certificate is required for the selected credential owner."),
        "certificate_conflict": _("The ZATCA certificate fields contain different values. Review both fields before signing; no certificate was selected automatically."),
        "private_key": _("A valid saved ZATCA private key is required for the selected credential owner."),
        "key_mismatch": _("The selected ZATCA private key does not match the selected certificate."),
        "purpose": _("Unsupported ZATCA credential purpose."),
        "authorization": _("The selected ZATCA credential owner has no authorization for the requested purpose. Credentials from another purpose cannot be used."),
    }
    frappe.throw(messages[error.code])


def _get_value(doc, fieldname):
    getter = getattr(doc, "get", None)
    return getter(fieldname) if callable(getter) else getattr(doc, fieldname, None)


def resolve_credential_owner(company_abbr, source_doc=None) -> CredentialOwner:
    """Resolve Company, own-device, or explicitly linked-company credentials."""
    try:
        company = frappe.get_doc("Company", {"abbr": company_abbr})
        owner, kind = company, "company"
        if source_doc is not None:
            if isinstance(source_doc, str):
                try:
                    source_doc = json.loads(source_doc)
                except (TypeError, ValueError):
                    raise CredentialConfigurationError("source") from None
            doctype, name = _get_value(source_doc, "doctype"), _get_value(source_doc, "name")
            if (
                doctype not in ("Company", "Sales Invoice", "POS Invoice", "ZATCA Multiple Setting")
                or not isinstance(name, str) or not name.strip()
            ):
                raise CredentialConfigurationError("source")
            # Reload the saved source so a serialized DTO cannot inject an
            # unrelated issuing unit, linked-company flag, key, or certificate.
            source = company if doctype == "Company" and name == company.name else frappe.get_doc(doctype, name)
            setting = None
            if doctype == "Company":
                if source.name != company.name:
                    raise CredentialConfigurationError("company")
            elif doctype in ("Sales Invoice", "POS Invoice"):
                if source.get("company") != company.name:
                    raise CredentialConfigurationError("company")
                if source.get("custom_zatca_pos_name"):
                    setting = frappe.get_doc("ZATCA Multiple Setting", source.get("custom_zatca_pos_name"))
            else:
                setting = source
            if setting is not None:
                linked_name = setting.get("custom_linked_doctype")
                if not linked_name:
                    raise CredentialConfigurationError("linked_company")
                linked = company if linked_name == company.name else frappe.get_doc("Company", linked_name)
                if linked.name != company.name:
                    company_vat = str(company.get("tax_id") or "").strip()
                    linked_vat = str(linked.get("tax_id") or "").strip()
                    if not company_vat or not linked_vat or company_vat != linked_vat:
                        raise CredentialConfigurationError("taxpayer")
                if use_linked_company(setting.get("custom__use_company_certificate__keys")):
                    owner, kind = linked, "linked_company"
                else:
                    owner, kind = setting, "multiple_setting"
        return CredentialOwner(
            company.name, owner.doctype, owner.name, kind,
            MappingProxyType({field: owner.get(field) for field in SECRET_FIELDS}),
        )
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)


def _certificate_for_owner(owner: CredentialOwner) -> str:
    aliases = (
        get_alias_group("multiple_setting_certificate")["aliases"]
        if owner.doctype == "ZATCA Multiple Setting" else ("custom_certificate",)
    )
    return certificate_value(owner.values, aliases)


def get_signing_certificate(company_abbr, source_doc=None) -> str:
    """Preserve selected certificate text; digest/serialization policy is unchanged."""
    try:
        return _certificate_for_owner(resolve_credential_owner(company_abbr, source_doc))
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)


def _parse_certificate(content):
    # Existing storage holds the Base64 DER body, not a PEM document. Keep this
    # parsing policy aligned with the legacy signing path in this increment.
    pem = "-----BEGIN CERTIFICATE-----\n" + content + "\n-----END CERTIFICATE-----\n"
    try:
        return x509.load_pem_x509_certificate(pem.encode("utf-8"))
    except (TypeError, ValueError):
        raise CredentialConfigurationError("certificate") from None


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


def get_certificate_public_key(company_abbr, source_doc=None) -> bytes:
    """Derive QR key bytes directly, without saving a cached public key or committing."""
    try:
        certificate = _parse_certificate(get_signing_certificate(company_abbr, source_doc))
        return certificate.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)


def get_api_authorization(company_abbr, source_doc=None, *, purpose):
    """Resolve the same owner policy as signing, then select a purpose-specific field."""
    try:
        return authorization_for_owner(resolve_credential_owner(company_abbr, source_doc), purpose)
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)
