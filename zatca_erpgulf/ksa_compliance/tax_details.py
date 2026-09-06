"""ERPNext 15/16 adapter for item-wise tax details."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP


def _value(row, key, default=None):
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key, default)
    return getattr(row, key, default)


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _item_row_name(item):
    """Return the child-row identifier used by ERPNext 16's tax table.

    ``Item Wise Tax Detail.item_row`` stores the child row ``name``. It is
    intentionally kept separate from the legacy ERPNext 15 key because an
    item's ``idx`` can be numerically equal to another item's ``item_code``.
    Treating both identifiers as interchangeable causes one item's tax to be
    added to another item's tax (for example item code ``8`` on row 1 and
    item code ``1`` on row 2).
    """
    value = _value(item, "name")
    return str(value) if value not in (None, "") else ""


def _legacy_item_key(item):
    """Return the exact key used by ERPNext 15 ``item_wise_tax_detail``.

    ERPNext 15 builds the JSON map with ``item.item_code or item.item_name``.
    The child-row ``name`` and display ``idx`` are not keys in that map and
    must never be used as fallbacks. In particular, using ``idx`` can make
    two unrelated entries match and double the rate/amount.
    """
    for fieldname in ("item_code", "item_name"):
        value = _value(item, fieldname)
        if value not in (None, ""):
            return str(value)
    return ""


def _normalise_v15_value(value):
    if isinstance(value, dict):
        return _number(value.get("tax_amount", value.get("amount"))), _number(value.get("tax_rate", value.get("rate")))
    if isinstance(value, (list, tuple)):
        return _number(value[1] if len(value) > 1 else 0), _number(value[0] if value else 0)
    return 0.0, 0.0


def _v15_details(doc):
    totals = defaultdict(lambda: [0.0, 0.0])
    for tax_row in (_value(doc, "taxes", []) or []):
        raw = _value(tax_row, "item_wise_tax_detail")
        if not raw:
            continue
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        for key, value in parsed.items():
            amount, rate = _normalise_v15_value(value)
            totals[str(key)][0] += amount
            totals[str(key)][1] += rate
    return totals


def _item_tax_rate_map(item):
    """Return ERPNext's per-row tax-rate map when it is available.

    ERPNext 15 keeps ``item_tax_rate`` as JSON on the item row. It is the
    only row-level source that can distinguish two rows with the same
    ``item_code``/``item_name``; the legacy ``item_wise_tax_detail`` map is
    aggregated by that key and therefore cannot provide a row-specific amount
    for duplicate rows.
    """
    raw = _value(item, "item_tax_rate")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _v15_item_tax_rate(doc, item):
    """Resolve a v15 row rate without using an aggregated tax amount."""
    item_tax_rates = _item_tax_rate_map(item)
    taxes = _value(doc, "taxes", []) or []

    if item_tax_rates:
        for tax_row in taxes:
            account_head = _value(tax_row, "account_head")
            if account_head in item_tax_rates:
                return _number(item_tax_rates[account_head])
        if len(item_tax_rates) == 1:
            return _number(next(iter(item_tax_rates.values())))

    # This is the authoritative source when all rows use invoice-level taxes.
    for tax_row in taxes:
        rate = _value(tax_row, "rate", None)
        if rate is not None:
            return _number(rate)

    return None


def _line_net_value(doc, item):
    """Return ``(found, absolute line net)`` for either currency path."""
    currency = _value(doc, "currency", "")
    fields = (
        ("base_net_amount", "base_amount", "net_amount", "amount")
        if currency == "SAR"
        else ("net_amount", "amount", "base_net_amount", "base_amount")
    )
    for fieldname in fields:
        value = _value(item, fieldname, None)
        if value is not None:
            return True, abs(_number(value))
    return False, 0.0


def _line_tax_amount(doc, item, tax_rate, fallback_amount=0.0):
    """Calculate tax from this physical row's net amount when it exists.

    ERPNext 15 aggregates the stored amount for duplicate item keys. The XML
    must not reuse that aggregate amount for each duplicate row, so the row
    net and rate are the source of truth.
    """
    if tax_rate is not None:
        found, net_amount = _line_net_value(doc, item)
        if found:
            tax = Decimal(str(net_amount)) * Decimal(str(_number(tax_rate))) / Decimal("100")
            return float(tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return _number(fallback_amount)


def get_item_tax_detail(doc, item):
    """Return ``(tax_amount, tax_rate)`` for an item on v15 or v16."""

    # ERPNext 16 stores one row per item/tax combination and references the
    # Sales Invoice Item child row by its ``name``. Match that reference
    # exactly; never include item_code or idx in this lookup.
    v16_details = _value(doc, "item_wise_tax_details", None)
    if v16_details:
        amount = rate = 0.0
        item_row_name = _item_row_name(item)
        matched = False
        for detail in v16_details:
            item_ref = str(_value(detail, "item_row", "") or "")
            if item_row_name and item_ref == item_row_name:
                matched = True
                amount += _number(_value(detail, "amount"))
                rate += _number(_value(detail, "rate"))
        if matched:
            return _line_tax_amount(doc, item, rate, amount), rate

        # A populated ERPNext 16 table is authoritative. Falling back to a
        # stale v15 JSON map for an unmatched row could reintroduce an
        # item_code/idx collision.
        return 0.0, 0.0

    if v16_details is not None:
        # An empty v16 table can occur while the invoice uses one invoice-level
        # tax row. In that case use the invoice tax rate, not stale v15 JSON.
        for tax_row in (_value(doc, "taxes", []) or []):
            tax_rate = _value(tax_row, "rate", None)
            if tax_rate is not None:
                return _line_tax_amount(doc, item, tax_rate), _number(tax_rate)
        return 0.0, 0.0

    # ERPNext 15 stores a JSON map keyed by item_code (or item_name when no
    # item_code exists). Resolve exactly one key. Do not inspect ``name`` or
    # ``idx`` here: those values identify the child row, not the JSON entry.
    legacy_key = _legacy_item_key(item)
    v15 = _v15_details(doc)
    legacy_value = v15.get(legacy_key)
    item_tax_rate = _v15_item_tax_rate(doc, item)
    if item_tax_rate is None and legacy_value is not None:
        item_tax_rate = legacy_value[1]
    if item_tax_rate is not None:
        return _line_tax_amount(
            doc,
            item,
            item_tax_rate,
            legacy_value[0] if legacy_value is not None else 0.0,
        ), item_tax_rate

    return 0.0, 0.0
