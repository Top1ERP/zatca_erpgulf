"""Internal metadata-only QR archive inspection, NOT a recovery capability.

Shared saved ACL, exact source locks, explicit journal binding and owned handle
cleanup. No whitelist/provider installation, raw XML/QR export, File operations,
image generation, current-credential reads or authority calls.
"""

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.permissions import has_permission

from .archive_source_access import (
    ArchiveInspectionEngine, ArchiveSourceAccessError, ArchiveSourceBinding,
    FIELDS, SavedSourceRow,
)
from .credential_bundle_access import CredentialStorageScope
from .journal_repository import MariaDBJournalRepository
from .qr_source_selection import ArchivedQRSource


DENIED_MESSAGE = "You do not have permission to inspect archived ZATCA QR sources."
FAILED_MESSAGE = "Archived ZATCA QR source inspection failed. No invoice was changed and no request was sent."


class QRSourceAccessError(ArchiveSourceAccessError):
    """Static QR-domain error, never a raw provider/parser exception."""


@dataclass(frozen=True, repr=False)
class QRSourceBinding(ArchiveSourceBinding):
    ERROR = QRSourceAccessError
    ERROR_PREFIX = "qr_access"


class ArchivedQRInspectionService(ArchiveInspectionEngine):
    BINDING_TYPE = QRSourceBinding
    ROW_TYPE = SavedSourceRow
    SOURCE_TYPE = ArchivedQRSource
    ERROR = QRSourceAccessError
    ERROR_PREFIX = "qr_access"
    DENIED_MESSAGE = DENIED_MESSAGE
    FAILED_MESSAGE = FAILED_MESSAGE

    def _dependencies(self):
        return frappe, _, has_permission, MariaDBJournalRepository
