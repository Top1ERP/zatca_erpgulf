"""Supplemental root party-account currency, preserving old financial profiles.

Reuse the Company link reader's bounded text, metadata and failed-session rules.
Only fixed root DocTypes/column/profile are selected; no arbitrary field or SQL.
"""

from dataclasses import dataclass

from .company_currency_source import LockedCompanyCurrencyRead, MariaDBCompanyCurrencyReader
from .source_metadata import OWNER_CURRENCY_PROFILE


class OwnerCurrencySourceError(ValueError):
    """Static English codes, without protected link or driver details."""


@dataclass(frozen=True, repr=False)
class LockedOwnerCurrencyRead(LockedCompanyCurrencyRead):
    DOCTYPES = ("Sales Invoice", "POS Invoice")
    FIELD = "party_account_currency"
    METADATA_PROFILE = OWNER_CURRENCY_PROFILE
    ROW_PROFILE = "owner-party-currency-source-sql/v1"
    DOMAIN = b"zatca-owner-party-currency-source-sql/v1\0"
    ERROR = OwnerCurrencySourceError
    ERROR_PREFIX = "owner_currency_source"

    def __repr__(self):
        return "<LockedOwnerCurrencyRead protected root link, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("owner_currency_source_not_serializable")


def pin_owner_currency(observed):
    if type(observed) is not LockedOwnerCurrencyRead:
        raise OwnerCurrencySourceError("owner_currency_source_binding")
    pinned = LockedOwnerCurrencyRead(observed.name, observed.metadata, observed._payload)
    if pinned != observed:
        raise OwnerCurrencySourceError("owner_currency_source_binding")
    return pinned


class MariaDBOwnerCurrencyReader(MariaDBCompanyCurrencyReader):
    READ_TYPE = LockedOwnerCurrencyRead
    ERROR = OwnerCurrencySourceError
    ERROR_PREFIX = "owner_currency_source"
    PIN_READ = staticmethod(pin_owner_currency)
