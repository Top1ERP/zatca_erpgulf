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
from zatca_erpgulf.zatca_erpgulf.compliance_archive import ComplianceArchiveCipher
from zatca_erpgulf.zatca_erpgulf.credential_bundle import (
    CredentialBundleCipher, CredentialBundleError, CredentialSlot, _validate,
)
from zatca_erpgulf.zatca_erpgulf.credential_bundle_repository import MariaDBCredentialBundleRepository
from zatca_erpgulf.zatca_erpgulf.credential_settings import (
    _capture_saved_company_projection, _resolve_owner_from_saved_company,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid
from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission


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
    """Trusted provider's transaction and storage ciphers, never an API payload.

    This contract does not establish secure key custody or prove database origin.
    A deployment must provide and audit those independently of the caller.
    The dedicated archive cipher is required only for archive inspection; None
    preserves existing metadata/supplied-observation inspection construction.
    """

    scope: CredentialStorageScope
    connection: object = field(repr=False, compare=False)
    cipher: CredentialBundleCipher = field(repr=False, compare=False)
    archive_cipher: ComplianceArchiveCipher | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.cipher) is not CredentialBundleCipher:
            raise CredentialBundleError("bundle_resource_binding")
        if not callable(getattr(self.connection, "cursor", None)):
            raise CredentialBundleError("bundle_resource_binding")
        if self.archive_cipher is not None and type(self.archive_cipher) is not ComplianceArchiveCipher:
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
        """Permissioned metadata for one exact slot/version, never active material."""
        return self._inspect(company_abbr, source_doc, endpoint, version_id=version_id)

    def inspect_compliance_checks(self, company_abbr, source_doc, *, version_id, check_set):
        """Permissioned local observations only, not a final-CSID activation gate."""
        return self._inspect(
            company_abbr, source_doc, "compliance/invoices", version_id=version_id,
            check_set=check_set, include_checks=True,
        )

    def inspect_compliance_archive(self, company_abbr, source_doc, *, version_id, exchange_ids):
        """Read a bounded explicit selection, NOT all attempts or remote completion.

        No supplied wire observations, namespace, keys or endpoint are accepted.
        Absence/failure aborts the entire report; there is no partial success.
        """
        return self._inspect(
            company_abbr, source_doc, "compliance/invoices", version_id=version_id,
            exchange_ids=exchange_ids, include_archive=True,
        )

    def _inspect(self, company_abbr, source_doc, endpoint, *, version_id, check_set=None,
                 include_checks=False, exchange_ids=None, include_archive=False):
        """Inspect an explicit saved slot/version; no latest/default/env override.

        Saved links, flags and routing are used, never caller-supplied credential
        values. ACL checks are independent of Document.ignore_permissions and
        frappe.flags.in_test. Reads are not a cross-row atomic settings snapshot.
        """
        def checked_load(doctype, name):
            saved = frappe.get_doc(doctype, name)
            # Use the permission engine directly: Document.check_permission can
            # honor ignore_permissions; that flag must not bypass this boundary.
            if not saved_row_has_permission(has_permission, doctype, "read", doc=saved, user=actor[1]):
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            return saved

        try:
            actor = self._check_actor()
            if include_archive:
                from zatca_erpgulf.zatca_erpgulf.compliance_evidence import MAX_EXCHANGES

                if (type(exchange_ids) is not tuple or not 1 <= len(exchange_ids) <= MAX_EXCHANGES
                        or include_checks):
                    raise CredentialBundleError("bundle_archive_selection")
                for identity in exchange_ids:
                    _validate(identity, "bundle_archive_exchange_id", _canonical_uuid)
                if len(set(exchange_ids)) != len(exchange_ids):
                    raise CredentialBundleError("bundle_archive_selection")
            if include_checks:
                from zatca_erpgulf.zatca_erpgulf.compliance_evidence import ComplianceCheckSet

                if type(check_set) is not ComplianceCheckSet:
                    raise CredentialBundleError("bundle_check_set_binding")
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
            if include_archive and type(resources.archive_cipher) is not ComplianceArchiveCipher:
                raise CredentialBundleError("bundle_archive_resource")
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
            if include_archive:
                return self._archive_report(resources, sealed, company, route, actor, exchange_ids)
            if include_checks:
                if (check_set.requirements.storage_namespace != self._scope.storage_namespace
                        or check_set.requirements.manifest.encode() != sealed.manifest_bytes
                        or check_set.requirements.seller_tax_id != str(company.get("tax_id") or "").strip()
                        or any(exchange.route != route for exchange in check_set.exchanges)):
                    raise CredentialBundleError("bundle_check_set_binding")
                return check_set.diagnostic_projection()
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

    def _archive_report(self, resources, sealed, company, route, actor, exchange_ids):
        """Authenticated at-rest evidence only, never trusted network provenance.

        The caller retains responsibility for rollback/closure on success AND
        failure. Reads acquire locks; there is no atomic Frappe settings/ACL
        snapshot and this selection does not establish completeness of history.
        """
        from zatca_erpgulf.zatca_erpgulf.compliance_archive_repository import MariaDBComplianceArchiveRepository
        from zatca_erpgulf.zatca_erpgulf.compliance_evidence import (
            MAX_CHECK_SET_BYTES, ComplianceCheckSet,
        )

        if type(resources.archive_cipher) is not ComplianceArchiveCipher:
            raise CredentialBundleError("bundle_archive_resource")
        repository = MariaDBComplianceArchiveRepository(
            resources.connection, self._scope.storage_namespace, resources.cipher, resources.archive_cipher,
        )
        histories, observations, total_bytes = [], [], 0
        for identity in exchange_ids:
            if self._check_actor() != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            history = repository.load(sealed.manifest.slot, sealed.manifest.version_id, identity)
            if self._check_actor() != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            current = history.current_observation
            if (current.exchange_id != identity
                    or current.requirements.storage_namespace != self._scope.storage_namespace
                    or current.requirements.manifest.encode() != sealed.manifest_bytes
                    or current.requirements.seller_tax_id != str(company.get("tax_id") or "").strip()
                    or current.route != route):
                raise CredentialBundleError("bundle_archive_source_binding")
            # Count BOTH protected records, including repeated request/CSR bytes.
            # Abort before keeping another history; never truncate into success.
            for observation in (history.start, history.receipt):
                if observation is not None:
                    total_bytes += (len(observation.request_bytes) + len(observation.response_bytes or b"")
                                    + len(observation.requirements.csr_der))
            if total_bytes > MAX_CHECK_SET_BYTES:
                raise CredentialBundleError("bundle_archive_selection_size")
            histories.append(history.diagnostic_projection())
            observations.append(current)
        checks = ComplianceCheckSet(observations[0].requirements, tuple(observations))
        report = {"state": "AUTHENTICATED_ARCHIVED_OBSERVATIONS", "selection_is_complete_history": False,
                  "checks": checks.diagnostic_projection(), "histories": histories}
        if self._check_actor() != actor:
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        return report
