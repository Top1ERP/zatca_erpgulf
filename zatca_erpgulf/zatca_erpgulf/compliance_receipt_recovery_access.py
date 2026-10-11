"""Internal permissioned LOCAL receipt recovery, never an authority request.

Shared capture policy reloads saved source/owner/ACL without legacy secrets.
Explicit server providers supply protected keys and owned transactions only.
No whitelist, runtime button/hook, queue, schema, credential activation or HTTP.
"""

from dataclasses import dataclass, field

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.compliance_archive import ComplianceArchiveCipher
from zatca_erpgulf.zatca_erpgulf.compliance_capture_access import _SavedComplianceSourceService, ComplianceSourceError
from zatca_erpgulf.zatca_erpgulf.compliance_receipt_recovery import ComplianceReceiptRecovery, _validate_recovery_input
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope


DENIED_MESSAGE = "You do not have permission to reconcile staged ZATCA compliance receipts."
FAILED_MESSAGE = "Staged ZATCA receipt reconciliation failed. No new request was sent and no credential was activated. Keep the original receipt; do not resend automatically."


@dataclass(frozen=True, repr=False)
class ComplianceReceiptRecoveryResources:
    """Explicit server resources; no transport/clock or already-open connection.

    Construction proves only shape/key separation, not tenant origin or custody.
    The provider owns failed acquisition and must never return borrowed handles.
    """

    scope: CredentialStorageScope
    bundle_cipher: CredentialBundleCipher
    archive_cipher: ComplianceArchiveCipher
    connection_factory: object = field(compare=False)

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope:
            raise ComplianceSourceError("source_resources")
        ComplianceReceiptRecovery(self.scope.storage_namespace, self.bundle_cipher, self.archive_cipher,
                                  connection_factory=self.connection_factory)

    def __repr__(self):
        return "ComplianceReceiptRecoveryResources(<protected local dependencies>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceSourceError("source_not_pickleable")


class StagedComplianceReceiptRecoveryService(_SavedComplianceSourceService):
    """Permissioned internal server input/output, NOT an operator JSON endpoint.

    Requires current saved owner/Company/route/CSR binding. Changed routing or
    owner needs a separately reviewed historical recovery policy, never fallback.
    The source revisions observed here are current recovery-time projections,
    NOT evidence that they generated the historical request/XML or certificate.
    Original protected receipt custody remains the caller's responsibility even
    when access is revoked or an interruption/error prevents returning a result.
    """

    _denied_message = DENIED_MESSAGE

    def __init__(self, scope, resource_provider):
        if type(scope) is not CredentialStorageScope or not callable(resource_provider):
            raise ComplianceSourceError("source_dependencies")
        self._scope, self._provider = scope, resource_provider

    def __repr__(self):
        return "StagedComplianceReceiptRecoveryService(<permissioned local recovery>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceSourceError("source_not_pickleable")

    def persist_receipt(self, company_abbr, source_doc, result):
        """Authorize before provider; lock current saved rows around receipt write.

        No shared Frappe commit/rollback. Ambient ACL is repeated before/after
        owned SQL and after closure, but never asserted to be atomic revocation.
        """
        try:
            actor = self._actor()
            observation = _validate_recovery_input(result, self._scope.storage_namespace)
            selected_actor, route, rows, checked_load = self._saved_source(company_abbr, source_doc, observation.requirements)
            if selected_actor != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            if route != observation.route:
                raise ComplianceSourceError("source_route_binding")
            self._recheck_source(actor, rows, checked_load)
            resources = self._provider(self._scope)
            if type(resources) is not ComplianceReceiptRecoveryResources or resources.scope != self._scope:
                raise ComplianceSourceError("source_resources")
            self._recheck_source(actor, rows, checked_load)

            def guard(connection, retained):
                if retained is not result:
                    raise ComplianceSourceError("source_exchange_binding")
                self._recheck_source(actor, rows, checked_load, connection=connection)
                return True

            recovery = ComplianceReceiptRecovery(self._scope.storage_namespace, resources.bundle_cipher,
                resources.archive_cipher, connection_factory=resources.connection_factory, source_guard=guard)
            recovered = recovery.persist_receipt(result)
            # A committed receipt is not undone if permission changes on close.
            # Refuse result disclosure; the caller MUST retain its original input.
            self._recheck_source(actor, rows, checked_load)
            return recovered
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        # No provider/parser/SQL exception context in translated operator errors.
        if denied:
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        frappe.throw(_(FAILED_MESSAGE))
