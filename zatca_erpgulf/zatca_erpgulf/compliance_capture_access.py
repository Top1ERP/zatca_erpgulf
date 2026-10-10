"""Internal permissioned staged Compliance capture; NO public/live adoption.

Saved source identities, routing and owner selection are reloaded through the
permission engine. Exact non-secret row revisions are checked with FOR UPDATE
in the reservation transaction and a separate closed preflight transaction.
Server providers must supply owned tenant connections and protected keys; this
module neither discovers them nor proves their origin. ACL is checked through
Frappe, NOT atomically locked in the owned SQL transaction. No lock survives HTTP.
This is not source-to-XML, CSR issuance, remote receipt or epoch attestation.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from zatca_erpgulf.zatca_erpgulf.compliance_archive import ComplianceArchiveCipher
from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceCaptureCoordinator
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import ComplianceExchangeObservation, ComplianceRequirements
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher, _key_id, _validate
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope
from zatca_erpgulf.zatca_erpgulf.credential_settings import (
    _capture_saved_company_projection, _resolve_owner_from_saved_company,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid
from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission


DENIED_MESSAGE = "You do not have permission to run staged ZATCA compliance checks."
FAILED_MESSAGE = "Staged ZATCA compliance capture failed. No credential was activated. Do not resend automatically."
MAX_FIELD_CHARS = 4096
# SQL identifiers are exclusively server-owned constants, never request strings.
# Missing installed custom columns fail closed; no alternate/schema repair path.
SOURCE_FIELDS = MappingProxyType({
    "Company": ("abbr", "tax_id", "custom_select", *ENVIRONMENT_FIELDS.values()),
    "Sales Invoice": ("company", "custom_zatca_pos_name"),
    "POS Invoice": ("company", "custom_zatca_pos_name"),
    "ZATCA Multiple Setting": ("custom_linked_doctype", "custom__use_company_certificate__keys"),
})
FLAG_FIELD = "custom__use_company_certificate__keys"


class ComplianceSourceError(ValueError):
    """Internal static code; no names, row values, SQL or provider exceptions."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _name(value):
    if (type(value) is not str or not 0 < len(value) <= 140 or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ComplianceSourceError("source_identity")
    return value


def _revision(value):
    if type(value) is str:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?", value) is None:
            raise ComplianceSourceError("source_revision")
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ComplianceSourceError("source_revision") from None
    if type(value) is not datetime or value.tzinfo is not None:
        # Frappe/MariaDB modified is a naive DATETIME, NOT UTC capture time.
        raise ComplianceSourceError("source_revision")
    return value.isoformat(timespec="microseconds")


def _value(name, value):
    if name == FLAG_FIELD:
        if value is None:
            return None
        if type(value) in (int, bool) and value in (0, 1):
            return int(value)
        if type(value) is str and value in ("0", "1"):
            return int(value)
        raise ComplianceSourceError("source_flag")
    if value is not None and (type(value) is not str or len(value) > MAX_FIELD_CHARS):
        raise ComplianceSourceError("source_field")
    return value


@dataclass(frozen=True, repr=False)
class SavedComplianceSourceRow:
    """Exact private non-secret projection; revision includes unprojected edits.

    A modified timestamp is a comparison marker, NOT an authoritative epoch or
    a complete invoice snapshot. Never publish names, Tax IDs or configured URLs.
    """

    doctype: str
    name: str
    revision: str
    values: tuple = field(repr=False)

    def __post_init__(self):
        if type(self.doctype) is not str or self.doctype not in SOURCE_FIELDS:
            raise ComplianceSourceError("source_doctype")
        _name(self.name)
        if type(self.revision) is not str or _revision(self.revision) != self.revision:
            raise ComplianceSourceError("source_revision")
        if type(self.values) is not tuple or len(self.values) != len(SOURCE_FIELDS[self.doctype]):
            raise ComplianceSourceError("source_row")
        for name, value in zip(SOURCE_FIELDS[self.doctype], self.values):
            normalized = _value(name, value)
            if normalized != value or type(normalized) is not type(value):
                raise ComplianceSourceError("source_row")

    @classmethod
    def from_document(cls, saved):
        doctype = saved.doctype
        if type(doctype) is not str or doctype not in SOURCE_FIELDS:
            raise ComplianceSourceError("source_doctype")
        return cls(doctype, saved.name, _revision(saved.get("modified")), tuple(
            _value(name, saved.get(name)) for name in SOURCE_FIELDS[doctype]))

    def __repr__(self):
        return "SavedComplianceSourceRow(<protected saved revision>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceSourceError("source_not_pickleable")


def verify_saved_source_rows(connection, rows):
    """Check bounded explicit rows in the caller-owned transaction; no cleanup.

    The caller MUST roll back and close the whole transaction after ANY failure.
    No schema discovery/installation, secrets, Frappe DB or autocommit fallback.
    Sorted locks precede bundle/archive locks. Database origin is a provider duty.
    """
    if (type(rows) is not tuple or not 1 <= len(rows) <= 4
            or any(type(row) is not SavedComplianceSourceRow for row in rows)
            or tuple((row.doctype, row.name) for row in rows) != tuple(sorted(set(
                (row.doctype, row.name) for row in rows)))):
        raise ComplianceSourceError("source_selection")
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@session.autocommit")
        autocommit = cursor.fetchone()
        if type(autocommit) is not tuple or len(autocommit) != 1 or type(autocommit[0]) is not int or autocommit[0] != 0:
            raise ComplianceSourceError("source_autocommit")
        for expected in rows:
            columns = ["`modified`"] + [
                "`" + name + "`" if name == FLAG_FIELD else "SUBSTRING(`" + name + "`,1,%s)"
                for name in SOURCE_FIELDS[expected.doctype]]
            limits = tuple(MAX_FIELD_CHARS + 1 for name in SOURCE_FIELDS[expected.doctype] if name != FLAG_FIELD)
            cursor.execute("SELECT " + ",".join(columns) + " FROM `tab" + expected.doctype + "` WHERE `name`=%s FOR UPDATE",
                           (*limits, expected.name))
            raw = cursor.fetchone()
            if type(raw) is not tuple or len(raw) != 1 + len(expected.values):
                raise ComplianceSourceError("source_row_missing")
            actual = SavedComplianceSourceRow(expected.doctype, expected.name, _revision(raw[0]), tuple(
                _value(name, value) for name, value in zip(SOURCE_FIELDS[expected.doctype], raw[1:])))
            if actual != expected:
                raise ComplianceSourceError("source_changed")
    return True


@dataclass(frozen=True, repr=False)
class ComplianceCaptureResources:
    """Server-only dependencies; constructing this is NOT origin/key attestation.

    Provider owns failed acquisition. Factories return NEW OWNED transactions,
    not shared frappe.db/borrowed handles. No connection is opened by this object.
    """

    scope: CredentialStorageScope
    bundle_cipher: CredentialBundleCipher
    archive_cipher: ComplianceArchiveCipher
    key_id: str
    connection_factory: object = field(compare=False)
    transport: object = field(compare=False)
    clock: object = field(compare=False)

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope:
            raise ComplianceSourceError("source_resources")
        _key_id(self.key_id)
        # Reuse the coordinator's exact key separation/dependency validation.
        ComplianceCaptureCoordinator(self.scope.storage_namespace, self.bundle_cipher, self.archive_cipher, self.key_id,
            connection_factory=self.connection_factory, transport=self.transport, clock=self.clock)

    def __repr__(self):
        return "ComplianceCaptureResources(<protected server dependencies>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceSourceError("source_not_pickleable")


class StagedComplianceCaptureService:
    """Not whitelisted, no default providers or UI/button/worker adoption.

    This conservative onboarding operator policy requires System Manager (or
    Administrator) AND read/write ACL on every source/device/linked-owner row.
    Supplied requirements/body are private SERVER inputs, not a client body API.
    The result is a protected recovery envelope, never an operator JSON payload.
    """

    def __init__(self, scope, resource_provider):
        if type(scope) is not CredentialStorageScope or not callable(resource_provider):
            raise ComplianceSourceError("source_dependencies")
        self._scope, self._provider = scope, resource_provider

    def __repr__(self):
        return "StagedComplianceCaptureService(<permissioned internal capture>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceSourceError("source_not_pickleable")

    def _actor(self):
        site, user = getattr(frappe.local, "site", None), getattr(frappe.session, "user", None)
        if (site != self._scope.site or type(user) is not str or not user or user == "Guest"
                or (user != "Administrator" and "System Manager" not in frappe.get_roles(user))):
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        return site, user

    def capture(self, company_abbr, source_doc, requirements, *, exchange_id, request_bytes):
        """Resolve saved routing/owner without projecting legacy secrets.

        ACL precedes providers and is repeated before each guarded transaction.
        Ambient ACL reads are not a cross-connection atomic permission snapshot.
        No settings/counter/UUID/customer/invoice or active credential is written.
        """
        try:
            actor = self._actor()
            _name(company_abbr)
            _validate(exchange_id, "source_exchange", _canonical_uuid)
            if type(requirements) is not ComplianceRequirements or requirements.storage_namespace != self._scope.storage_namespace:
                raise ComplianceSourceError("source_requirements")
            records = {}

            def checked_load(doctype, name):
                if self._actor() != actor:
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                saved = frappe.get_doc(doctype, name)
                if (saved.doctype != doctype
                        or (type(name) is str and saved.name != name)
                        or (type(name) is dict and (name != {"abbr": company_abbr} or saved.get("abbr") != company_abbr))):
                    raise ComplianceSourceError("source_identity")
                for operation in ("read", "write"):
                    # Bypass neither ACL via ignore_permissions nor in_test.
                    if not saved_row_has_permission(has_permission, doctype, operation, doc=saved, user=actor[1]):
                        frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                row = SavedComplianceSourceRow.from_document(saved)
                identity = row.doctype, row.name
                if identity in records and records[identity] != row:
                    raise ComplianceSourceError("source_changed")
                records[identity] = row
                if self._actor() != actor:
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                return saved

            company = _capture_saved_company_projection(company_abbr, load_doc=checked_load, include_secrets=False)
            route = resolve_api_route(company.values, "compliance/invoices")
            owner = _resolve_owner_from_saved_company(company, source_doc, load_doc=checked_load, include_secrets=False)
            manifest, slot = requirements.manifest, requirements.manifest.slot
            if (manifest.company_name != owner.company_name or manifest.source_kind != owner.source_kind
                    or slot.owner_doctype != owner.doctype or slot.owner_name != owner.name
                    or slot.environment != route.environment or slot.purpose != "compliance"
                    or requirements.seller_tax_id != str(company.get("tax_id") or "").strip()):
                raise ComplianceSourceError("source_material_binding")
            # Pure request validation BEFORE the provider can access storage keys.
            ComplianceExchangeObservation(requirements, exchange_id, route, manifest.prepared_at, None, request_bytes, None, None)
            rows = tuple(records[identity] for identity in sorted(records))
            if self._actor() != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            resources = self._provider(self._scope)
            if type(resources) is not ComplianceCaptureResources or resources.scope != self._scope:
                raise ComplianceSourceError("source_resources")

            def guard(connection, start):
                if (start.requirements != requirements or start.route != route or start.exchange_id != exchange_id
                        or start.request_bytes != request_bytes):
                    raise ComplianceSourceError("source_exchange_binding")
                if self._actor() != actor:
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                for row in rows:
                    if SavedComplianceSourceRow.from_document(checked_load(row.doctype, row.name)) != row:
                        raise ComplianceSourceError("source_changed")
                verify_saved_source_rows(connection, rows)
                # ACL may change during SQL. Repeat it without releasing row
                # locks; never claim the external permission tables are locked.
                for row in rows:
                    checked_load(row.doctype, row.name)
                return True

            def guarded_transport(request):
                # Commit/close/clock can fail or change actor context after the
                # SQL guard. Recheck actor/saved ACL before releasing this request
                # to the actual transport dependency. No owned SQL lock survives.
                # Failure is conservatively TRANSPORT_UNKNOWN_NO_REPLAY because
                # the low-level coordinator cannot attest a callback's behavior.
                if self._actor() != actor:
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                for row in rows:
                    checked_load(row.doctype, row.name)
                return resources.transport(request)

            if self._actor() != actor:
                frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
            coordinator = ComplianceCaptureCoordinator(self._scope.storage_namespace, resources.bundle_cipher,
                resources.archive_cipher, resources.key_id, connection_factory=resources.connection_factory,
                transport=guarded_transport, clock=resources.clock, source_guard=guard)
            return coordinator.capture(requirements, exchange_id=exchange_id, route=route, request_bytes=request_bytes)
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        # Raise outside handlers: no secret-bearing provider/parser/SQL context.
        if denied:
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        frappe.throw(_(FAILED_MESSAGE))
