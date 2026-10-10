"""Permissioned, metadata-only STAGING inspection; deliberately not whitelisted.

The server constructs this service with a tenant binding and a trusted resource
provider. No request parameter selects a namespace, storage key or connection.
All saved-row ACL checks precede invoking that provider. No active selection,
plaintext return, key discovery, SQL installation, HTTP or credential write is
performed. The caller owns transaction rollback/closure, including on failure.
"""

import re
from dataclasses import dataclass, field

import frappe
from frappe import _
from frappe.permissions import has_permission

from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route
from zatca_erpgulf.zatca_erpgulf.credential_bundle import (
    CredentialBundleCipher, CredentialBundleError, CredentialSlot, _validate,
)
from zatca_erpgulf.zatca_erpgulf.credential_bundle_repository import MariaDBCredentialBundleRepository
from zatca_erpgulf.zatca_erpgulf.credential_settings import (
    _capture_saved_company_projection, _resolve_owner_from_saved_company,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid


DENIED_MESSAGE = "You do not have permission to inspect staged ZATCA credentials."
FAILED_MESSAGE = "Staged ZATCA credential inspection failed. No credential was activated."


@dataclass(frozen=True)
class CredentialStorageScope:
    """Server-provisioned binding, NOT a tenant identity proven by this object."""

    site: str
    storage_namespace: str

    def __post_init__(self):
        if type(self.site) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", self.site) is None:
            raise CredentialBundleError("bundle_site")
        _validate(self.storage_namespace, "bundle_namespace", _canonical_uuid)


@dataclass(frozen=True, repr=False)
class CredentialStorageResources:
    """Trusted provider's transaction and storage cipher, never an API payload.

    This contract does not establish secure key custody or prove database origin.
    A deployment must provide and audit those independently of the caller.
    """

    scope: CredentialStorageScope
    connection: object = field(repr=False, compare=False)
    cipher: CredentialBundleCipher = field(repr=False, compare=False)

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.cipher) is not CredentialBundleCipher:
            raise CredentialBundleError("bundle_resource_binding")
        if not callable(getattr(self.connection, "cursor", None)):
            raise CredentialBundleError("bundle_resource_binding")

    def __repr__(self):
        return "CredentialStorageResources(<server-owned protected resources>)"

    def __reduce_ex__(self, protocol):
        raise CredentialBundleError("bundle_not_pickleable")


class StagedCredentialInspectionService:
    """Internal operator boundary; there is intentionally no decrypt/export API.

    ``resource_provider(scope)`` is a trusted server dependency invoked only after
    role/site and every saved source/owner-row permission check succeeds. It must
    not log keys, discover an arbitrary database, or return an active credential.
    It owns cleanup when acquisition fails; its caller closes/rolls back acquired
    resources. This service never commits, rolls back or closes a shared resource.
    """

    def __init__(self, scope, resource_provider):
        if type(scope) is not CredentialStorageScope or not callable(resource_provider):
            raise CredentialBundleError("bundle_service_binding")
        self._scope, self._resource_provider = scope, resource_provider

    def __repr__(self):
        return "StagedCredentialInspectionService(<server-bound metadata inspection>)"

    def __reduce_ex__(self, protocol):
        raise CredentialBundleError("bundle_not_pickleable")

    def _check_actor(self):
        site = getattr(frappe.local, "site", None)
        user = getattr(frappe.session, "user", None)
        if (site != self._scope.site or type(user) is not str or not user or user == "Guest"
                or (user != "Administrator" and "System Manager" not in frappe.get_roles(user))):
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        return site, user

    def inspect(self, company_abbr, source_doc, endpoint, *, version_id):
        """Inspect an explicit saved slot/version; no latest/default/env override.

        Saved links, flags and routing are used, never caller-supplied credential
        values. ACL checks are independent of Document.ignore_permissions and
        frappe.flags.in_test. Reads are not a cross-row atomic settings snapshot.
        """
        def checked_load(doctype, name):
            saved = frappe.get_doc(doctype, name)
            # Use the permission engine directly: Document.check_permission can
            # honor ignore_permissions; that flag must not bypass this boundary.
            if has_permission(doctype, "read", doc=saved, user=actor[1], raise_exception=False) is not True:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            return saved

        try:
            actor = self._check_actor()
            _validate(version_id, "bundle_version", _canonical_uuid)
            if type(endpoint) is not str or endpoint not in (
                "compliance/invoices", "production/csids",
                "invoices/reporting/single", "invoices/clearance/single",
            ):
                raise CredentialBundleError("bundle_operation")
            company = _capture_saved_company_projection(
                company_abbr, load_doc=checked_load, include_secrets=False,
            )
            route = resolve_api_route(company.values, endpoint)
            owner = _resolve_owner_from_saved_company(
                company, source_doc, load_doc=checked_load, include_secrets=False,
            )
            slot = CredentialSlot(owner.doctype, owner.name, route.environment, route.required_credential)
            if self._check_actor() != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            resources = self._resource_provider(self._scope)
            if type(resources) is not CredentialStorageResources or resources.scope != self._scope:
                raise CredentialBundleError("bundle_resource_binding")
            if self._check_actor() != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            sealed = MariaDBCredentialBundleRepository(
                resources.connection, self._scope.storage_namespace, resources.cipher,
            ).load(slot, version_id)
            # Shared linked-owner slots do not permit another Company's staged
            # declaration to masquerade as this source's onboarding evidence.
            if sealed.manifest.company_name != owner.company_name or sealed.manifest.source_kind != owner.source_kind:
                raise CredentialBundleError("bundle_source_binding")
            if self._check_actor() != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            return sealed.manifest.diagnostic_projection()
        except frappe.PermissionError:
            denied = True
        except Exception:
            # Includes acquisition, missing saved records and driver failures.
            # Never render provider/parser/database exceptions containing secrets.
            denied = False
        # Outside the exception handler: secret-bearing provider/driver exceptions
        # must not be chained into the public exception or its server traceback.
        if denied:
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        frappe.throw(_(FAILED_MESSAGE))
