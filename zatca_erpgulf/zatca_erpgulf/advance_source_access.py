"""Internal permissioned metadata-only advance archive inspection.

Server providers supply a site/namespace binding, exact historical lookup and a
NEW OWNED connection. No whitelist, hook, file scan, active credential, XML
export, shared Frappe transaction writes/cleanup, commit, schema installation or authority I/O.
Provider/database origin remains a deployment audit gate, not proven here.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from zatca_erpgulf.zatca_erpgulf.advance_source_selection import ArchivedAdvanceSource
from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import parse_diagnostic_icv
from zatca_erpgulf.zatca_erpgulf.compliance_capture_access import _name, _revision, MAX_FIELD_CHARS
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope
from zatca_erpgulf.zatca_erpgulf.credential_settings import _resolve_owner_from_saved_company
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    PreparationContext, _canonical_uuid, _fingerprint, _sha256,
)
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission


DENIED_MESSAGE = "You do not have permission to inspect archived ZATCA advance sources."
FAILED_MESSAGE = "Archived ZATCA advance source inspection failed. No invoice was changed and no request was sent."
MARKERS = ("is_advance_payment", "custom_is_advance_payment")
FIELDS = MappingProxyType({
    "Company": ("abbr", "tax_id", "custom_select", *ENVIRONMENT_FIELDS.values()),
    "Sales Invoice": ("company", "docstatus", "custom_uuid", "custom_zatca_icv",
                      "custom_zatca_issuing_unit", "custom_zatca_status", "custom_zatca_pos_name"),
    "ZATCA Multiple Setting": ("custom_linked_doctype", "custom__use_company_certificate__keys"),
})


class AdvanceSourceAccessError(ValueError):
    """Static internal codes; the service emits translated, redacted failures."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class AdvanceSourceBinding:
    """Server lookup declaration, not proof of tenant or historical provenance."""

    scope: CredentialStorageScope
    context: PreparationContext
    uuid: str
    icv: int
    journal_sha256: str

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.context) is not PreparationContext:
            raise AdvanceSourceAccessError("advance_access_binding")
        if self.context.scope.doctype != "Sales Invoice":
            raise AdvanceSourceAccessError("advance_access_doctype")
        _canonical_uuid(self.uuid, "advance_access_uuid")
        _sha256(self.journal_sha256, "advance_access_revision")
        if type(self.icv) is not int or not 1 <= self.icv < 10**64:
            raise AdvanceSourceAccessError("advance_access_icv")

    def __repr__(self):
        return "AdvanceSourceBinding(<server historical declaration>)"

    def __reduce_ex__(self, protocol):
        raise AdvanceSourceAccessError("advance_access_not_pickleable")


def _value(name, value):
    if name in ("docstatus", *MARKERS, "custom__use_company_certificate__keys"):
        if value is None:
            return None
        maximum = 2 if name == "docstatus" else 1
        if type(value) is str and value in ("0", "1", "2"):
            value = int(value)
        if type(value) not in (int, bool) or not 0 <= value <= maximum:
            raise AdvanceSourceAccessError("advance_access_flag")
        return int(value)
    if name == "custom_zatca_icv":
        if value is None:
            return None
        if type(value) not in (int, str):
            raise AdvanceSourceAccessError("advance_access_icv")
        return parse_diagnostic_icv(value)
    if value is not None and (type(value) is not str or len(value) > MAX_FIELD_CHARS):
        raise AdvanceSourceAccessError("advance_access_field")
    return value


@dataclass(frozen=True, repr=False)
class _SavedRow:
    """Private non-secret revision projection, NOT a full issuance snapshot."""

    doctype: str
    name: str
    revision: str
    fields: tuple
    values: tuple = field(repr=False)

    @classmethod
    def from_document(cls, doc):
        if doc.doctype not in FIELDS:
            raise AdvanceSourceAccessError("advance_access_doctype")
        fields = FIELDS[doc.doctype]
        if doc.doctype == "Sales Invoice":
            # Standard marker wins even when zero; no truthy alias fallback.
            meta = getattr(doc, "meta", None)
            marker = next((name for name in MARKERS if meta and meta.has_field(name)), None)
            if marker is None:
                raise AdvanceSourceAccessError("advance_access_marker_schema")
            fields += (marker,)
        return cls(doc.doctype, _name(doc.name), _revision(doc.get("modified")), fields,
                   tuple(_value(name, doc.get(name)) for name in fields))


def _verify_rows(connection, rows):
    """Lock exact bounded non-secret projections before the journal lock."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@session.autocommit")
        setting = cursor.fetchone()
        if (type(setting) is not tuple or len(setting) != 1
                or type(setting[0]) is not int or setting[0] != 0):
            raise AdvanceSourceAccessError("advance_access_autocommit")
        for expected in rows:
            numeric = ("docstatus", "custom_zatca_icv", *MARKERS, "custom__use_company_certificate__keys")
            columns = ["`name`", "`modified`"] + [
                "`" + name + "`" if name in numeric else "SUBSTRING(`" + name + "`,1,%s)"
                for name in expected.fields
            ]
            limits = tuple(MAX_FIELD_CHARS + 1 for name in expected.fields if name not in numeric)
            cursor.execute("SELECT " + ",".join(columns) + " FROM `tab" + expected.doctype
                           + "` WHERE `name`=%s FOR UPDATE", (*limits, expected.name))
            raw = cursor.fetchone()
            if type(raw) is not tuple or len(raw) != 2 + len(expected.values):
                raise AdvanceSourceAccessError("advance_access_row_missing")
            actual = _SavedRow(expected.doctype, _name(raw[0]), _revision(raw[1]), expected.fields,
                               tuple(_value(name, value) for name, value in zip(expected.fields, raw[2:])))
            if actual != expected:
                raise AdvanceSourceAccessError("advance_access_source_changed")


def _discard(connection):
    """Always attempt BOTH rollback and close, preserving interruption priority."""
    errors = []
    for operation in ("rollback", "close"):
        try:
            getattr(connection, operation)()
        except BaseException as error:
            errors.append(error)
    return next((error for error in errors if not isinstance(error, Exception)),
                errors[0] if errors else None)


class ArchivedAdvanceInspectionService:
    """Internal metadata boundary; providers are server dependencies, not JSON.

    Current saved ownership/routing must match the historical declaration. Drift
    requires a separately reviewed historical-access policy, never an automatic
    fallback. Ambient ACL rechecks do NOT atomically lock permission tables.
    """

    def __init__(self, scope, lookup_provider, connection_factory):
        if (type(scope) is not CredentialStorageScope or not callable(lookup_provider)
                or not callable(connection_factory)):
            raise AdvanceSourceAccessError("advance_access_dependencies")
        self._scope, self._lookup, self._connect = scope, lookup_provider, connection_factory

    def __repr__(self):
        return "ArchivedAdvanceInspectionService(<permissioned metadata only>)"

    def __reduce_ex__(self, protocol):
        raise AdvanceSourceAccessError("advance_access_not_pickleable")

    def _actor(self):
        site, user = getattr(frappe.local, "site", None), getattr(frappe.session, "user", None)
        if (site != self._scope.site or type(user) is not str or not user or user == "Guest"
                or (user != "Administrator" and "System Manager" not in frappe.get_roles(user))):
            frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
        return site, user

    def inspect(self, invoice_name):
        """Authorize before lookup/SQL and after closure; return metadata only."""
        connection, failure, report, cleanup_failure = None, None, None, None
        try:
            actor = self._actor()
            _name(invoice_name)
            records = {}

            def load(doctype, name):
                if self._actor() != actor:
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                doc = frappe.get_doc(doctype, _name(name))
                if doc.doctype != doctype or doc.name != name:
                    raise AdvanceSourceAccessError("advance_access_identity")
                if not saved_row_has_permission(has_permission, doctype, "read", doc=doc, user=actor[1]):
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                row = _SavedRow.from_document(doc)
                identity = row.doctype, row.name
                if identity in records and records[identity] != row:
                    raise AdvanceSourceAccessError("advance_access_source_changed")
                records[identity] = row
                if self._actor() != actor:
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                return doc

            invoice = load("Sales Invoice", invoice_name)
            company = load("Company", invoice.get("company"))
            owner = _resolve_owner_from_saved_company(company, invoice, load_doc=load, include_secrets=False)
            rows = tuple(records[identity] for identity in sorted(records))

            def recheck():
                if self._actor() != actor:
                    frappe.throw(_(DENIED_MESSAGE), frappe.PermissionError)
                for row in rows:
                    if _SavedRow.from_document(load(row.doctype, row.name)) != row:
                        raise AdvanceSourceAccessError("advance_access_source_changed")

            recheck()
            binding = self._lookup(self._scope, rows)
            if type(binding) is not AdvanceSourceBinding or binding.scope != self._scope:
                raise AdvanceSourceAccessError("advance_access_binding")
            expected = binding.context.scope
            marker = records["Sales Invoice", invoice_name].fields[-1]
            if (expected.invoice_name != invoice.name or expected.company_name != company.name
                    or expected.seller_tax_id != company.get("tax_id")
                    or expected.environment != company.get("custom_select")
                    or expected.legacy_issuing_unit != invoice.get("custom_zatca_issuing_unit")
                    or binding.uuid != invoice.get("custom_uuid")
                    or binding.icv != _value("custom_zatca_icv", invoice.get("custom_zatca_icv"))
                    or _value("docstatus", invoice.get("docstatus")) != 1
                    or _value(marker, invoice.get(marker)) != 1
                    or (owner.doctype, owner.name) != (binding.context.credential_epoch.owner_doctype,
                                                     binding.context.credential_epoch.owner_name)
                    or resolve_api_route(company, binding.context.route.endpoint) != binding.context.route):
                raise AdvanceSourceAccessError("advance_access_saved_binding")
            required_status = "CLEARED" if binding.context.route.endpoint == "invoices/clearance/single" else "REPORTED"
            if invoice.get("custom_zatca_status") != required_status:
                raise AdvanceSourceAccessError("advance_access_saved_status")
            recheck()
            # Inspect recognizable ambient identities BEFORE acquisition. If a
            # framework proxy lookup fails, no owned handle has been allocated.
            ambient = frappe.db
            ambient_raw = getattr(ambient, "_conn", None)
            acquired = self._connect(self._scope)
            # Reject recognizable ambient handles WITHOUT touching their state.
            if acquired is ambient or acquired is ambient_raw:
                raise AdvanceSourceAccessError("advance_access_borrowed_connection")
            connection = acquired
            if any(not callable(getattr(connection, name, None)) for name in ("cursor", "rollback", "close")):
                raise AdvanceSourceAccessError("advance_access_connection")
            # Clear any pre-existing uncommitted observation on this OWNED handle.
            connection.rollback()
            recheck()
            _verify_rows(connection, rows)
            recheck()
            key = _fingerprint(expected.key_projection())
            journal = MariaDBJournalRepository(connection, self._scope.storage_namespace).load(key)
            selected = ArchivedAdvanceSource(journal, binding.context, binding.uuid, binding.icv, binding.journal_sha256)
            _verify_rows(connection, rows)
            recheck()
            report = selected.diagnostic_projection()
        except BaseException as error:
            failure = error
        finally:
            if connection is not None:
                cleanup_failure = _discard(connection)
        if failure is None and cleanup_failure is None:
            try:
                recheck()  # No disclosure if actor/source changes during close.
                return report
            except BaseException as error:
                failure = error
        for error in (failure, cleanup_failure):
            if error is not None and not isinstance(error, Exception):
                raise error
        denied = isinstance(failure, frappe.PermissionError)
        # Raise OUTSIDE handlers: no SQL/provider/parser exception context leaks.
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE), frappe.PermissionError if denied else frappe.ValidationError)
