"""Uninstalled saved-READ acquisition of protected calculation defaults only.

Administrator/System Manager and exact invoice/Company READ precede explicit
owned SQL and cache dependencies. No certificate/route/acceptance requirement,
whitelist, provider installation, source write, fiscal resolution or HTTP.
Factory/cache provenance and complete preparation source guards remain gates.
"""

from dataclasses import dataclass, field
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import (
    ArchiveInspectionEngine, ArchiveSourceAccessError, SavedSourceRow,
    _discard, _name, _revision, _value, _verify_rows,
)
from .calculation_defaults import CalculationDefaultsRows, MariaDBCalculationDefaultsReader, _pin_rows
from .credential_bundle_access import CredentialStorageScope
from .operation_messages import mute_operation_messages
from .primary_receipt_access import _owned_saved_receipt_connection

DENIED_MESSAGE = "You do not have permission to read ZATCA calculation defaults for this saved invoice."
FAILED_MESSAGE = "ZATCA calculation defaults could not be confirmed. No settings or invoice were changed and no request was sent."
FIELDS = MappingProxyType({
    "Sales Invoice": ("company", "docstatus"),
    "POS Invoice": ("company", "docstatus"),
    "Company": (),
})
PARENT_KINDS = ("site", "global", "user")


class CalculationDefaultsAccessError(ArchiveSourceAccessError):
    """Static internal English codes, without raw settings/driver detail."""


class CalculationDefaultsSourceRow(SavedSourceRow):
    """Minimal saved ownership context, NOT financial/settings completeness."""

    FIELD_MAP = FIELDS


def _pin_source(row):
    if type(row) is not CalculationDefaultsSourceRow or row.doctype not in FIELDS:
        raise ValueError
    fields = FIELDS[row.doctype]
    if type(row.fields) is not tuple or row.fields != fields or type(row.values) is not tuple or len(row.values) != len(fields):
        raise ValueError
    pinned = CalculationDefaultsSourceRow(row.doctype, _name(row.name), _revision(row.revision), fields,
        tuple(_value(name, value) for name, value in zip(fields, row.values)))
    if pinned != row:
        raise ValueError
    return pinned


@dataclass(frozen=True, repr=False)
class SavedCalculationDefaultsRead:
    """Ephemeral protected source/actor binding; no issuance/provenance grant.

    This is not an RPC/queue/log payload or durable full preparation snapshot.
    Independent copies prevent later changes to provider-owned declarations.
    """

    scope: CredentialStorageScope = field(repr=False)
    actor: str = field(repr=False)
    sources: tuple = field(repr=False)
    defaults: CalculationDefaultsRows = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.scope) is not CredentialStorageScope or type(self.sources) is not tuple or len(self.sources) != 2:
                raise ValueError
            scope = CredentialStorageScope(self.scope.site, self.scope.storage_namespace)
            actor = _name(self.actor)
            if actor == "Guest":
                raise ValueError
            rows = tuple(_pin_source(row) for row in self.sources)
            company, invoice = rows
            if (company.doctype != "Company" or invoice.doctype not in ("Sales Invoice", "POS Invoice")
                    or invoice.values[0] != company.name or invoice.values[1] not in (0, 1, 2)):
                raise ValueError
            defaults = _pin_rows(self.defaults)
            if defaults.parent not in ("__default", "__global", actor):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationDefaultsAccessError("calculation_defaults_access_result")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "sources", rows)
        object.__setattr__(self, "defaults", defaults)

    def __repr__(self):
        return "<SavedCalculationDefaultsRead protected source-bound observation, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_defaults_access_not_serializable")


class _SavedDefaultsSource(ArchiveInspectionEngine):
    ROW_TYPE = CalculationDefaultsSourceRow
    ERROR = CalculationDefaultsAccessError
    ERROR_PREFIX = "calculation_defaults_access"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def __init__(self, scope, connection_factory):
        if type(scope) is not CredentialStorageScope or not callable(connection_factory):
            raise self.ERROR(self.ERROR_PREFIX + "_dependencies")
        self._scope = CredentialStorageScope(scope.site, scope.storage_namespace)
        self._connect = connection_factory

    def _dependencies(self):
        return frappe, (lambda text: text), has_permission, None

    def _saved_selection(self, invoice_name, doctype, actor):
        if type(doctype) is not str or doctype not in self.BINDING_TYPE.ALLOWED_DOCTYPES:
            raise self.ERROR(self.ERROR_PREFIX + "_doctype")
        _name(invoice_name)
        load, finalize = self._saved_record_access(actor)
        invoice = load(doctype, invoice_name)
        if invoice.get("docstatus") not in (0, 1, 2):
            raise self.ERROR(self.ERROR_PREFIX + "_source_status")
        load("Company", invoice.get("company"))
        return finalize()


class SavedCalculationDefaultsService:
    """Explicit local capture; fixed parent kind and trusted server dependencies.

    Parent kind is constructor-only: site=__default, global=__global, user=the
    CURRENT authorized actor. No per-call arbitrary parent or API precedence.
    Cache reader must supply the exact get_defaults_for projection for that
    scope. New owned acquisition clears pending work; recognizable ambient
    handles are never cleaned. No commit, cache refresh or source write occurs.
    """

    def __init__(self, scope, connection_factory, cache_reader, *, parent_kind="site"):
        if type(parent_kind) is not str or parent_kind not in PARENT_KINDS or not callable(cache_reader):
            raise CalculationDefaultsAccessError("calculation_defaults_access_dependencies")
        self._policy = _SavedDefaultsSource(scope, connection_factory)
        self._cache, self._parent_kind = cache_reader, parent_kind

    def __repr__(self):
        return "<SavedCalculationDefaultsService permissioned protected local read>"

    def __reduce__(self):
        raise TypeError("calculation_defaults_access_service_not_serializable")

    def capture(self, invoice_name, *, doctype="Sales Invoice"):
        """Display one localized failure, keeping parent flags/messages intact."""
        try:
            with mute_operation_messages(frappe):
                return self._capture_owned(invoice_name, doctype=doctype)
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        frappe.throw(_(DENIED_MESSAGE if denied else FAILED_MESSAGE),
            frappe.PermissionError if denied else frappe.ValidationError)

    def _capture_owned(self, invoice_name, *, doctype):
        """Recheck saved ACL/SQL membership/cache before protected disclosure.

        Fresh owned rollback excludes pre-existing pending defaults. Remaining
        factory/cache dependencies must be audited; arbitrary trusted callbacks
        are not sandboxed. SQL and cache are not locked atomically, and results
        can become stale after cleanup. Never use this as complete source proof.
        """
        connection, failure, cleanup_failure, result = None, None, None, None
        try:
            policy = self._policy
            actor = policy._actor()
            rows, _records, recheck = policy._saved_selection(invoice_name, doctype, actor)
            parent = {"site": "__default", "global": "__global", "user": actor[1]}[self._parent_kind]
            connection = _owned_saved_receipt_connection(policy, recheck)
            _verify_rows(connection, rows)
            recheck()
            reader = MariaDBCalculationDefaultsReader(connection)
            observed = reader.load_for_update(parent)
            observed.require_cache_match(parent, self._cache(policy._scope, parent))
            recheck()
            _verify_rows(connection, rows)
            reader.require_unchanged(observed)
            observed.require_cache_match(parent, self._cache(policy._scope, parent))
            _verify_rows(connection, rows)
            reader.require_unchanged(observed)
            recheck()
            result = SavedCalculationDefaultsRead(policy._scope, actor[1], rows, observed)
        except BaseException as error:
            failure = error
        finally:
            if connection is not None:
                cleanup_failure = _discard(connection)
        if failure is None and cleanup_failure is None:
            try:
                recheck()  # Deny disclosure on source/actor/ACL drift during close.
                return result
            except BaseException as error:
                failure = error
        for error in (failure, cleanup_failure):
            if error is not None and not isinstance(error, Exception):
                raise error
        denied = isinstance(failure, frappe.PermissionError)
        if denied:
            raise frappe.PermissionError(DENIED_MESSAGE)
        raise CalculationDefaultsAccessError("calculation_defaults_access_read")
