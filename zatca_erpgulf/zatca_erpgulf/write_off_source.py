"""Native write-off fields through the shared bounded root-controls reader."""
from dataclasses import dataclass

from .invoice_rounding_source import LockedInvoiceRoundingRead, MariaDBInvoiceRoundingReader
from .source_metadata import WRITE_OFF_PROFILE, WRITE_OFF_FIELDS


@dataclass(frozen=True, repr=False)
class LockedWriteOffRead(LockedInvoiceRoundingRead):
    FIELDS = WRITE_OFF_FIELDS["Sales Invoice"]
    CHECKS = ("write_off_outstanding_amount_automatically",)
    OVERLAP = ()
    METADATA_PROFILE = WRITE_OFF_PROFILE
    ROW_PROFILE = "invoice-write-off-source-sql/v1"
    DOMAIN = b"zatca-invoice-write-off-source/v1\0"

    def __repr__(self):
        return "<LockedWriteOffRead protected native amounts/Check, NOT fiscal authority>"


def pin_write_off(value):
    if type(value) is not LockedWriteOffRead:
        raise ValueError
    pinned = LockedWriteOffRead(value.financial, value.metadata, value._payload)
    if pinned != value:
        raise ValueError
    return pinned


class MariaDBWriteOffReader(MariaDBInvoiceRoundingReader):
    READ_TYPE = LockedWriteOffRead
    PIN_READ = staticmethod(pin_write_off)
