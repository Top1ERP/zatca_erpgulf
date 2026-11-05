"""Bounded invoice Checks/Links for outstanding-entry decisions, not eligibility."""
from dataclasses import dataclass

from .invoice_rounding_source import LockedInvoiceRoundingRead, MariaDBInvoiceRoundingReader
from .financial_source_observation import HEADER_FIELDS
from .source_metadata import OUTSTANDING_GUARDS_PROFILE, OUTSTANDING_GUARDS_FIELDS


@dataclass(frozen=True, repr=False)
class LockedOutstandingGuardsRead(LockedInvoiceRoundingRead):
    FIELDS = OUTSTANDING_GUARDS_FIELDS["Sales Invoice"]
    CHECKS = ("is_return", "is_pos", "update_outstanding_for_self", "is_internal_customer")
    LINKS = (("company", "Company"), ("return_against", None), ("represents_company", "Company"))
    OVERLAP = tuple(name for name in OUTSTANDING_GUARDS_FIELDS["Sales Invoice"] if name in HEADER_FIELDS)
    METADATA_PROFILE = OUTSTANDING_GUARDS_PROFILE
    ROW_PROFILE = "invoice-outstanding-guards-source-sql/v1"
    DOMAIN = b"zatca-invoice-outstanding-guards/v1\0"

    def __repr__(self):
        return "<LockedOutstandingGuardsRead protected Checks/Links, NOT party-master verification>"


def pin_outstanding_guards(value):
    if type(value) is not LockedOutstandingGuardsRead:
        raise ValueError
    pinned = LockedOutstandingGuardsRead(value.financial, value.metadata, value._payload)
    if pinned != value:
        raise ValueError
    return pinned


class MariaDBOutstandingGuardsReader(MariaDBInvoiceRoundingReader):
    READ_TYPE = LockedOutstandingGuardsRead
    PIN_READ = staticmethod(pin_outstanding_guards)
