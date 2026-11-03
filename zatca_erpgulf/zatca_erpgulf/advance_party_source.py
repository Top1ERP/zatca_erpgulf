"""Optional native advance party links using the shared bounded child reader.

Separate profile/domain preserve old currency/Company and financial bytes.
Prove physical absence as well as values; parent resolution and ACL are external.
"""

from dataclasses import dataclass

from .child_currency_source import LockedChildCurrencyRead, MariaDBChildCurrencyReader
from .source_metadata import ADVANCE_PARTY_PROFILE


@dataclass(frozen=True, repr=False)
class LockedAdvancePartyRead(LockedChildCurrencyRead):
    FIELDS = ("party_account_currency",)
    TARGETS = (("party_account_currency", "Currency"),)
    METADATA_PROFILE = ADVANCE_PARTY_PROFILE
    ROW_PROFILE = "advance-party-currency-source-sql/v1"
    DOMAIN = b"zatca-advance-party-currency-source/v1\0"
    PARENTFIELDS = ("advances",)

    def __repr__(self):
        return "<LockedAdvancePartyRead protected optional native links, NOT ACL proof>"


def pin_advance_party(value):
    if type(value) is not LockedAdvancePartyRead:
        raise ValueError
    pinned = LockedAdvancePartyRead(value.financial, value.parentfield, value.metadata, value._payload)
    if pinned != value:
        raise ValueError
    return pinned


class MariaDBAdvancePartyReader(MariaDBChildCurrencyReader):
    READ_TYPE = LockedAdvancePartyRead
    PIN_READ = staticmethod(pin_advance_party)
