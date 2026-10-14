"""Advance-only metadata inspection using the shared owned-read engine.

Compatibility entry points and marker precedence remain unchanged. No advance
search, allocation, age/settlement policy, export, mutation or authority call.
"""

from dataclasses import dataclass
from types import MappingProxyType

import frappe
from frappe import _
from frappe.permissions import has_permission

from .advance_source_selection import ArchivedAdvanceSource
# Keep the former private metadata helpers importable for diagnostic consumers.
from .archive_source_access import (
    ArchiveInspectionEngine, ArchiveSourceAccessError, ArchiveSourceBinding,
    FIELDS as _COMMON_FIELDS, MARKERS, SavedSourceRow, _value, _verify_rows, _discard,
)
from .credential_bundle_access import CredentialStorageScope
from .journal_repository import MariaDBJournalRepository


DENIED_MESSAGE = "You do not have permission to inspect archived ZATCA advance sources."
FAILED_MESSAGE = "Archived ZATCA advance source inspection failed. No invoice was changed and no request was sent."
FIELDS = MappingProxyType({dt: fields for dt, fields in _COMMON_FIELDS.items() if dt != "POS Invoice"})


class AdvanceSourceAccessError(ArchiveSourceAccessError):
    """Static advance-domain compatibility error."""


@dataclass(frozen=True, repr=False)
class AdvanceSourceBinding(ArchiveSourceBinding):
    ALLOWED_DOCTYPES = ("Sales Invoice",)
    ERROR = AdvanceSourceAccessError
    ERROR_PREFIX = "advance_access"


class _SavedRow(SavedSourceRow):
    FIELD_MAP = FIELDS
    ADVANCE_MARKERS = MARKERS


class ArchivedAdvanceInspectionService(ArchiveInspectionEngine):
    BINDING_TYPE = AdvanceSourceBinding
    ROW_TYPE = _SavedRow
    SOURCE_TYPE = ArchivedAdvanceSource
    ERROR = AdvanceSourceAccessError
    ERROR_PREFIX = "advance_access"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        return frappe, _, has_permission, MariaDBJournalRepository

    def _check_domain(self, binding, invoice, records):
        marker = records["Sales Invoice", invoice.name].fields[-1]
        if _value(marker, invoice.get(marker)) != 1:
            raise AdvanceSourceAccessError("advance_access_saved_binding")
