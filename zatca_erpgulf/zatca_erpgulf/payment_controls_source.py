"""Native Sales Invoice payment/return/loyalty controls, without normalization."""
from dataclasses import dataclass
from .invoice_rounding_source import LockedInvoiceRoundingRead, MariaDBInvoiceRoundingReader
from .source_metadata import PAYMENT_CONTROLS_PROFILE, PAYMENT_CONTROLS_FIELDS


@dataclass(frozen=True, repr=False)
class LockedPaymentControlsRead(LockedInvoiceRoundingRead):
    FIELDS = PAYMENT_CONTROLS_FIELDS["Sales Invoice"]
    CHECKS = ("is_pos", "is_return", "redeem_loyalty_points")
    OVERLAP = ("is_pos", "is_return")
    METADATA_PROFILE = PAYMENT_CONTROLS_PROFILE
    ROW_PROFILE = "invoice-payment-controls-source-sql/v1"
    DOMAIN = b"zatca-invoice-payment-controls/v1\0"

    def __repr__(self):
        return "<LockedPaymentControlsRead protected native flags/loyalty, NOT settlement proof>"


def pin_payment_controls(value):
    if type(value) is not LockedPaymentControlsRead:
        raise ValueError
    pinned = LockedPaymentControlsRead(value.financial, value.metadata, value._payload)
    if pinned != value:
        raise ValueError
    return pinned


class MariaDBPaymentControlsReader(MariaDBInvoiceRoundingReader):
    READ_TYPE = LockedPaymentControlsRead
    PIN_READ = staticmethod(pin_payment_controls)
