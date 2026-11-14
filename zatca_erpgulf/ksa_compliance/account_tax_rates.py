"""Read native rates by physical item and tax account without choosing VAT.

Callers own fiscal roles and monetary reconciliation. In particular, a Tax
account type or a positive rate does not declare VAT ownership. This strict
reader never sums unrelated rates or reads cumulative/item tax amounts. Its
indexes live for one preparation only; it performs no framework or site calls.
The existing permissive legacy tax-detail APIs are deliberately unchanged.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from types import MappingProxyType


class AccountTaxRateError(ValueError):
    """Stable English code; never include untrusted document payloads."""


def _get(record, key, default=None):
    getter = getattr(record, "get", None)
    if not callable(getter):
        raise AccountTaxRateError("account_rate_shape")
    return getter(key, default)


def _name(value):
    if not isinstance(value, str) or not value:
        raise AccountTaxRateError("account_rate_identity")
    return value


def _rate(value):
    if isinstance(value, bool):
        raise AccountTaxRateError("account_rate_value")
    try:
        number = Decimal(str(value))
        if number.is_finite() and number >= 0:
            return number
    except (InvalidOperation, TypeError, ValueError):
        pass
    raise AccountTaxRateError("account_rate_value")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AccountTaxRateError("account_rate_duplicate_key")
        result[key] = value
    return result


def _item_map(item):
    raw = _get(item, "item_tax_rate")
    if raw in (None, ""):
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw, object_pairs_hook=_unique_object)
        except (ValueError, TypeError) as error:
            if isinstance(error, AccountTaxRateError):
                raise
            raise AccountTaxRateError("account_rate_item_map") from None
    if not isinstance(raw, dict):
        raise AccountTaxRateError("account_rate_item_map")
    return raw


@dataclass(frozen=True)
class ItemAccountRates:
    """An immutable rate projection, not VAT-role or acceptance evidence."""

    source: str
    _rates: object

    def rate(self, item, account):
        try:
            return self._rates[_name(_get(item, "name"))][_name(account)]
        except KeyError:
            raise AccountTaxRateError("account_rate_missing_pair") from None


def index_item_account_rates(doc):
    """Bind native rate observations to every current item/account pair.

    v15 follows the controller's per-account item map, then invoice-row rate.
    Do not use item-code aggregated JSON or a singleton-map heuristic.

    A present v16 detail table owns this decision. Require exact physical
    item_row/tax_row references and complete pairs, including explicit zero
    observations for other accounts. Empty, dangling, duplicate or partial
    detail tables cannot fall back to stale v15 maps. NOT_APPLICABLE_TAX is
    outside this numeric projection and requires separate fiscal review.
    """
    items = {}
    for item in _get(doc, "items", []) or []:
        name = _name(_get(item, "name"))
        if name in items:
            raise AccountTaxRateError("account_rate_duplicate_item")
        items[name] = item
    accounts, tax_names = {}, {}
    for row in _get(doc, "taxes", []) or []:
        account, name = _name(_get(row, "account_head")), _name(_get(row, "name"))
        if account in accounts or name in tax_names:
            raise AccountTaxRateError("account_rate_duplicate_tax")
        accounts[account], tax_names[name] = row, account
    if not items or not accounts:
        raise AccountTaxRateError("account_rate_empty_scope")

    result = {name: {} for name in items}
    details = _get(doc, "item_wise_tax_details")
    if details is not None:
        if not isinstance(details, (list, tuple)) or not details:
            raise AccountTaxRateError("account_rate_v16_empty")
        for detail in details:
            item_name, tax_name = _name(_get(detail, "item_row")), _name(_get(detail, "tax_row"))
            if item_name not in items or tax_name not in tax_names:
                raise AccountTaxRateError("account_rate_dangling_reference")
            account = tax_names[tax_name]
            if account in result[item_name]:
                raise AccountTaxRateError("account_rate_duplicate_pair")
            result[item_name][account] = _rate(_get(detail, "rate"))
        if any(set(rates) != set(accounts) for rates in result.values()):
            raise AccountTaxRateError("account_rate_missing_pair")
        source = "v16-physical-item-tax-pairs"
    else:
        for name, item in items.items():
            item_map = _item_map(item)
            result[name] = {
                account: _rate(item_map[account] if account in item_map else _get(row, "rate"))
                for account, row in accounts.items()
            }
        source = "v15-account-map-or-invoice-rate"
    return ItemAccountRates(source, MappingProxyType({
        name: MappingProxyType(rates) for name, rates in result.items()
    }))
