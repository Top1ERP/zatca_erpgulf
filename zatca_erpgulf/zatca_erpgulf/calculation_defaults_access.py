"""Uninstalled saved-READ acquisition of defaults, metadata and financial rows.

Administrator/System Manager and exact invoice/Company READ precede explicit
owned SQL and cache dependencies. No certificate/route/acceptance requirement,
whitelist, provider installation, source write, fiscal resolution or HTTP.
Factory/cache provenance and complete preparation source guards remain gates.
"""

from dataclasses import dataclass, field
import json
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import (
    ArchiveInspectionEngine, ArchiveSourceAccessError, SavedSourceRow,
    _discard, _name, _revision, _value, _verify_rows,
)
from .calculation_defaults import CalculationDefaultsRows, MariaDBCalculationDefaultsReader, _pin_rows
from .calculation_precision import FieldPrecisionResolution
from .credential_bundle_access import CredentialStorageScope
from . import financial_source_observation as financial
from .financial_source_sql import (
    LockedInvoiceFinancialRead, MariaDBInvoiceFinancialReader,
    _manifest as _financial_manifest, _pin_read as _pin_financial_read,
)
from .metadata_source import (
    MariaDBMetadataSourceReader, SelectedMetadataRows, _pin_rows as _pin_metadata_rows,
)
from .operation_messages import mute_operation_messages
from .primary_receipt_access import _owned_saved_receipt_connection
from .source_metadata import _pin_metadata

DENIED_MESSAGE = "You do not have permission to read ZATCA calculation defaults for this saved invoice."
FAILED_MESSAGE = "ZATCA calculation defaults could not be confirmed. No settings or invoice were changed and no request was sent."
FINANCIAL_DENIED_MESSAGE = "You do not have permission to read ZATCA financial data for this saved invoice."
FINANCIAL_FAILED_MESSAGE = "ZATCA invoice financial data and calculation settings could not be confirmed. No settings or invoice were changed and no request was sent."
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


def _pin_saved_defaults(observed):
    if type(observed) is not SavedCalculationDefaultsRead:
        raise ValueError
    pinned = SavedCalculationDefaultsRead(observed.scope, observed.actor, observed.sources, observed.defaults)
    if pinned != observed:
        raise ValueError
    return pinned


@dataclass(frozen=True, repr=False)
class SavedCalculationContextRead:
    """Protected PARTIAL defaults plus invoice/Company metadata, not issuance.

    The two source metadata types are exact, independently pinned and must cover
    every minimal saved-row column. Other financial dependencies are not claimed.
    """

    settings: SavedCalculationDefaultsRead = field(repr=False)
    metadata: tuple[SelectedMetadataRows, ...] = field(repr=False)

    def __post_init__(self):
        try:
            settings = _pin_saved_defaults(self.settings)
            expected = tuple(row.doctype for row in settings.sources)
            if type(self.metadata) is not tuple or len(self.metadata) != len(expected):
                raise ValueError
            metadata = tuple(_pin_metadata_rows(row) for row in self.metadata)
            if tuple(row.applied.name for row in metadata) != expected:
                raise ValueError
            for selected, schema in zip(settings.sources, metadata):
                if any(not schema.applied.has_field(name) for name in selected.fields):
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationDefaultsAccessError("calculation_context_access_result")
        object.__setattr__(self, "settings", settings)
        object.__setattr__(self, "metadata", metadata)

    def __repr__(self):
        return "<SavedCalculationContextRead protected PARTIAL declarations, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_context_access_not_serializable")


@dataclass(frozen=True, repr=False)
class SavedCalculationFinancialRead:
    """Protected PARTIAL native financial/default binding, never build authority.

    The overlapping invoice metadata, identity, revision, Company and status
    must agree. Neither source hash is a complete preparation fingerprint.
    Raw SQL scalars remain distinct from ORM values and fiscal XML formatting.
    """

    context: SavedCalculationContextRead = field(repr=False)
    financial: LockedInvoiceFinancialRead = field(repr=False)

    def __post_init__(self):
        try:
            if type(self.context) is not SavedCalculationContextRead:
                raise ValueError
            context = SavedCalculationContextRead(self.context.settings, self.context.metadata)
            if context != self.context:
                raise ValueError
            observed = _pin_financial_read(self.financial)
            invoice = context.settings.sources[1]
            body = json.loads(observed.financial._payload)
            header = dict(body["header"])
            root_metadata = next(row for row in observed.metadata if row.applied.name == invoice.doctype)
            if ((observed.financial.doctype, observed.financial.name) != (invoice.doctype, invoice.name)
                    or _revision(financial._validate_scalar(body["modified"])) != invoice.revision
                    or header["company"] != financial._scalar(invoice.values[0])
                    or header["docstatus"] != financial._scalar(invoice.values[1])
                    or root_metadata != context.metadata[1]):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationDefaultsAccessError("calculation_financial_access_result")
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "financial", observed)

    def __repr__(self):
        return "<SavedCalculationFinancialRead protected PARTIAL native SQL, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_financial_access_not_serializable")

    def resolve_precision(self, doctype, fieldname, *, currency_context=None):
        """Resolve one captured invoice/child field without another SQL/ORM read.

        A v16 currency fallback needs explicit trusted format declarations;
        field-currency/locale acquisition is not guessed here. The result is
        fresh precision, not a stored document cache or authority XML rule.
        """
        try:
            pinned = SavedCalculationFinancialRead(self.context, self.financial)
            if pinned != self or type(doctype) is not str:
                raise ValueError
            metadata = {row.applied.name: row.applied for row in pinned.financial.metadata}
            result = FieldPrecisionResolution(metadata[doctype], fieldname,
                pinned.context.settings.defaults, pinned.financial.financial.erp_major,
                currency_context)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationDefaultsAccessError("calculation_financial_precision")
        return result


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

    def __init__(self, scope, connection_factory, cache_reader, *,
            parent_kind="site", applied_metadata_reader=None):
        if type(parent_kind) is not str or parent_kind not in PARENT_KINDS or not callable(cache_reader):
            raise CalculationDefaultsAccessError("calculation_defaults_access_dependencies")
        self._policy = _SavedDefaultsSource(scope, connection_factory)
        if applied_metadata_reader is not None and not callable(applied_metadata_reader):
            raise CalculationDefaultsAccessError("calculation_context_access_dependencies")
        self._cache, self._parent_kind = cache_reader, parent_kind
        self._metadata = applied_metadata_reader

    def __repr__(self):
        return "<SavedCalculationDefaultsService permissioned protected local read>"

    def __reduce__(self):
        raise TypeError("calculation_defaults_access_service_not_serializable")

    def capture(self, invoice_name, *, doctype="Sales Invoice"):
        """Display one localized failure, keeping parent flags/messages intact."""
        return self._capture_display(invoice_name, doctype=doctype, include_metadata=False)

    def capture_context(self, invoice_name, *, doctype="Sales Invoice"):
        """Explicit metadata/default composition on ONE owned SQL transaction.

        The server must configure an applied_metadata_reader(scope, types).
        No request selects arbitrary metadata types or supplies framework Meta.
        """
        return self._capture_display(invoice_name, doctype=doctype, include_metadata=True)

    def capture_financial_context(self, invoice_name, *, erp_major, doctype="Sales Invoice"):
        """Read invoice-owned native data and defaults on the same owned handle.

        Explicit ERP major is a declaration, not an installed-version check.
        Linked parties/templates/settings, ORM parity and fiscal policy remain
        outside this partial read. There is no RPC or implicit runtime caller.
        """
        return self._capture_display(invoice_name, doctype=doctype, include_metadata=True,
            include_financial=True, erp_major=erp_major)

    def _capture_display(self, invoice_name, *, doctype, include_metadata,
            include_financial=False, erp_major=None):
        try:
            with mute_operation_messages(frappe):
                return self._capture_owned(invoice_name, doctype=doctype, include_metadata=include_metadata,
                    include_financial=include_financial, erp_major=erp_major)
        except frappe.PermissionError:
            denied = True
        except Exception:
            denied = False
        denied_message = FINANCIAL_DENIED_MESSAGE if include_financial else DENIED_MESSAGE
        failed_message = FINANCIAL_FAILED_MESSAGE if include_financial else FAILED_MESSAGE
        frappe.throw(_(denied_message if denied else failed_message),
            frappe.PermissionError if denied else frappe.ValidationError)

    def _applied_metadata(self, rows, *, include_financial=False):
        if self._metadata is None:
            raise CalculationDefaultsAccessError("calculation_context_access_dependencies")
        required = tuple(row.doctype for row in rows)
        pinned = self._metadata_family(required)
        for row, meta in zip(rows, pinned):
            if any(not meta.has_field(name) for name in row.fields):
                raise CalculationDefaultsAccessError("calculation_context_access_metadata_fields")
        if include_financial:
            root = pinned[1]
            children = tuple(sorted(financial._child_type(root.name, table)
                for table in financial.TABLE_FIELDS if root.has_field(table)))
            extended = self._metadata_family((*required, *children))
            if extended[:2] != pinned:
                raise CalculationDefaultsAccessError("calculation_context_access_metadata_drift")
            _financial_manifest(root.name, {meta.name: meta for meta in extended[1:]})
            return extended
        return pinned

    def _metadata_family(self, required):
        """Pin exactly the server-derived type set; never accept extra records."""
        supplied = self._metadata(self._policy._scope, required)
        if type(supplied) is not dict or set(supplied) != set(required):
            raise CalculationDefaultsAccessError("calculation_context_access_metadata_scope")
        pinned = tuple(_pin_metadata(supplied[name]) for name in required)
        if tuple(meta.name for meta in pinned) != required:
            raise CalculationDefaultsAccessError("calculation_context_access_metadata_scope")
        return pinned

    def _capture_owned(self, invoice_name, *, doctype, include_metadata=False,
            include_financial=False, erp_major=None):
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
            if include_financial and (type(erp_major) is not int or erp_major not in (15, 16)):
                raise CalculationDefaultsAccessError("calculation_financial_access_version")
            applied = self._applied_metadata(rows, include_financial=include_financial) if include_metadata else ()
            if include_metadata:
                recheck()
            parent = {"site": "__default", "global": "__global", "user": actor[1]}[self._parent_kind]
            connection = _owned_saved_receipt_connection(policy, recheck)
            _verify_rows(connection, rows)
            recheck()
            metadata_reader = MariaDBMetadataSourceReader(connection) if include_metadata else None
            # The financial reader owns invoice/child metadata reads; avoid a
            # second initial read of the same invoice declaration here.
            metadata = tuple(metadata_reader.load_for_update(meta)
                for meta in (applied[:1] if include_financial else applied))
            if include_financial:
                financial_reader = MariaDBInvoiceFinancialReader(connection)
                observed_financial = financial_reader.load_for_update(doctype, invoice_name,
                    erp_major=erp_major, applied_metadata={meta.name: meta for meta in applied[1:]})
                root_metadata = next(row for row in observed_financial.metadata if row.applied.name == doctype)
                context_metadata = (*metadata, root_metadata)
            else:
                context_metadata = metadata
            reader = MariaDBCalculationDefaultsReader(connection)
            observed = reader.load_for_update(parent)
            observed.require_cache_match(parent, self._cache(policy._scope, parent))
            recheck()
            _verify_rows(connection, rows)
            reader.require_unchanged(observed)
            observed.require_cache_match(parent, self._cache(policy._scope, parent))
            if include_metadata:
                if self._applied_metadata(rows, include_financial=include_financial) != applied:
                    raise CalculationDefaultsAccessError("calculation_context_access_metadata_drift")
                recheck()
            _verify_rows(connection, rows)
            reader.require_unchanged(observed)
            for declaration in metadata:
                metadata_reader.require_unchanged(declaration)
            if include_financial:
                financial_reader.require_unchanged(observed_financial)
            recheck()
            result = SavedCalculationDefaultsRead(policy._scope, actor[1], rows, observed)
            if include_metadata:
                result = SavedCalculationContextRead(result, context_metadata)
            if include_financial:
                result = SavedCalculationFinancialRead(result, observed_financial)
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
