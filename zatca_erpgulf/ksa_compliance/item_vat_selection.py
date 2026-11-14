"""Explicit Item Tax Template VAT ownership, without framework or I/O.

Absence of the optional field leaves every legacy source policy untouched.
Selection declares one VAT row. Other rows are numeric zero overrides, never
other positive taxes/charges to silently discard. No role is guessed from an
account name, account type, row order or first positive rate.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

FIELD = "custom_zatca_vat_account"
MESSAGE = "Review the VAT account selected on the Item Tax Template. Select exactly one matching row and keep other tax rows at zero."


class VatSelectionError(ValueError):
    """Stable English diagnostic, independent of user language."""


def declared_account(template):
    """Read physically present data; a missing field must not opt a source in."""
    values = template if isinstance(template, dict) else vars(template)
    return values.get(FIELD)


def _value(record, key, default=None):
    return record.get(key, default) if isinstance(record, dict) else getattr(record, key, default)


def _rate(value):
    if isinstance(value, bool):
        raise VatSelectionError("declared_vat_invalid_rate")
    try:
        rate = Decimal(str(value))
        if rate.is_finite() and rate >= 0:
            return rate
    except (InvalidOperation, ValueError, TypeError):
        pass
    raise VatSelectionError("declared_vat_invalid_rate")


@dataclass(frozen=True)
class VatSelection:
    account: str
    row: object
    rate: Decimal
    excluded_accounts: tuple


def select_declared_vat(template, *, company=None):
    account = declared_account(template)
    if account in (None, ""):
        return None
    if not isinstance(account, str) or not account.strip():
        raise VatSelectionError("declared_vat_invalid_account")
    if company is not None and _value(template, "company") != company:
        raise VatSelectionError("declared_vat_company_mismatch")
    selected, excluded, seen = None, [], set()
    for row in _value(template, "taxes", []) or []:
        name = _value(row, "tax_type")
        if not isinstance(name, str) or not name or name in seen:
            raise VatSelectionError("declared_vat_duplicate_or_missing_account")
        seen.add(name)
        rate = _rate(_value(row, "tax_rate"))
        if name == account:
            selected = row, rate
        elif rate != 0:
            raise VatSelectionError("declared_vat_nonzero_other_row")
        else:
            excluded.append(name)
    if selected is None:
        raise VatSelectionError("declared_vat_account_not_in_template")
    return VatSelection(account, selected[0], selected[1], tuple(excluded))
