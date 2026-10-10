"""Read-only owner resolution shared by signing and HTTP authentication.

Only saved document identity is trusted from caller-supplied objects/JSON. Keys
and credential values are always read from the selected saved owner. No field
repair, certificate migration, key generation, save, or commit occurs here.
"""

import json
from dataclasses import dataclass, field
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
        return _resolve_owner_from_saved_company(company, source_doc)
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)


def _resolve_owner_from_saved_company(company, source_doc, *, load_doc=None, include_secrets=True):
    """Reuse one owner policy, optionally with a permission-checked loader.

    Existing callers retain their behavior. Internal metadata inspection supplies
    its own checked loader and omits credential-field projections entirely.
    """
    load_doc = frappe.get_doc if load_doc is None else load_doc
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
        # Caller data supplies identity only. Saved source/device links are reloaded.
        source = company if doctype == "Company" and name == company.name else load_doc(doctype, name)
        setting = None
        if doctype == "Company":
            if source.name != company.name:
                raise CredentialConfigurationError("company")
        elif doctype in ("Sales Invoice", "POS Invoice"):
            if source.get("company") != company.name:
                raise CredentialConfigurationError("company")
            if source.get("custom_zatca_pos_name"):
                setting = load_doc("ZATCA Multiple Setting", source.get("custom_zatca_pos_name"))
        else:
            setting = source
        if setting is not None:
            linked_name = setting.get("custom_linked_doctype")
            if not linked_name:
                raise CredentialConfigurationError("linked_company")
            linked = company if linked_name == company.name else load_doc("Company", linked_name)
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
        MappingProxyType({field: owner.get(field) for field in SECRET_FIELDS} if include_secrets else {}),
    )


@dataclass(frozen=True)
class _CompanyProjection:
    """Freeze one saved Company row before reloading the source/device records."""

    name: str
    doctype: str
    values: object = field(repr=False)

    def get(self, key):
        return self.values.get(key)


def capture_credential_snapshot(company_abbr, source_doc, endpoint, *, observed_at):
    """Read-only future pipeline adapter, NOT a cross-row atomic DB transaction.

    No current generator/request uses this capture. A service must supply verified
    transaction/source/epoch provenance before adopting it or dispatching HTTP.
    """
    from zatca_erpgulf.zatca_erpgulf.api_routing import ApiConfigurationError, resolve_api_route
    from zatca_erpgulf.zatca_erpgulf.credential_snapshot import (
        OPERATIONS, CredentialSnapshot, CredentialSnapshotError,
    )

    try:
        if type(endpoint) is not str or endpoint not in OPERATIONS:
            raise CredentialSnapshotError("snapshot_operation")
        company = _capture_saved_company_projection(company_abbr)
        route = resolve_api_route(company.values, endpoint)
        owner = _resolve_owner_from_saved_company(company, source_doc)
        return CredentialSnapshot(owner, route, _certificate_for_owner(owner), observed_at)
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)
    except (ApiConfigurationError, CredentialSnapshotError) as error:
        frappe.throw(_(
            "ZATCA credential snapshot validation failed ({0}). Review the selected certificate, key, authentication and environment settings."
        ).format(error.code))


def _capture_saved_company_projection(company_abbr, *, load_doc=None, include_secrets=True):
    """One frozen Company projection, not atomic source/device/linked-row reads."""
    from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS

    load_doc = frappe.get_doc if load_doc is None else load_doc
    saved = load_doc("Company", {"abbr": company_abbr})
    values = MappingProxyType({
        name: saved.get(name) for name in (
            "tax_id", "custom_select", *ENVIRONMENT_FIELDS.values(),
            *(SECRET_FIELDS if include_secrets else ()),
        )
    })
    return _CompanyProjection(saved.name, saved.doctype, values)


def capture_credential_lifecycle_assessment(company_abbr, source_doc, *, observed_at):
    """Internal read-only legacy inventory; no public endpoint or migration.

    Safe public observations only. A future operator service must enforce its own
    permissions and transaction/provenance policy before exposing this result.
    """
    from zatca_erpgulf.zatca_erpgulf.api_routing import ApiConfigurationError
    from zatca_erpgulf.zatca_erpgulf.credential_lifecycle import inspect_legacy_credential_lifecycle
    from zatca_erpgulf.zatca_erpgulf.credential_snapshot import CredentialSnapshotError, validate_snapshot_time

    try:
        validate_snapshot_time(observed_at)
        company = _capture_saved_company_projection(company_abbr)
        owner = _resolve_owner_from_saved_company(company, source_doc)
        return inspect_legacy_credential_lifecycle(
            owner, company.values, certificate_fields=_certificate_fields_for_owner(owner), observed_at=observed_at,
        )
    except CredentialConfigurationError as error:
        _throw_configuration_error(error)
    except (ApiConfigurationError, CredentialSnapshotError) as error:
        frappe.throw(_(
            "ZATCA credential snapshot validation failed ({0}). Review the selected certificate, key, authentication and environment settings."
        ).format(error.code))


def _certificate_fields_for_owner(owner: CredentialOwner) -> tuple[str, ...]:
    return tuple(
        get_alias_group("multiple_setting_certificate")["aliases"]
        if owner.doctype == "ZATCA Multiple Setting" else ("custom_certificate",)
    )


def _certificate_for_owner(owner: CredentialOwner) -> str:
    return certificate_value(owner.values, _certificate_fields_for_owner(owner))


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
