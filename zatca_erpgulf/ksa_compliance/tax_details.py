"""ERPNext 15/16 adapter for item-wise tax details."""

from __future__ import annotations

import json
from collections import defaultdict


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


def get_item_tax_detail(doc, item):
    """Return ``(tax_amount, tax_rate)`` for an item on v15 or v16."""

    # ERPNext 16 stores one row per item/tax combination and references the
    # Sales Invoice Item child row by its ``name``. Match that reference
    # exactly; never include item_code or idx in this lookup.
    v16_details = _value(doc, "item_wise_tax_details", None)
    if v16_details is not None:
        amount = rate = 0.0
        item_row_name = _item_row_name(item)
        matched = False
        for detail in v16_details or []:
            item_ref = str(_value(detail, "item_row", "") or "")
            if item_row_name and item_ref == item_row_name:
                matched = True
                amount += _number(_value(detail, "amount"))
                rate += _number(_value(detail, "rate"))
        if matched:
            return amount, rate

        # Once the ERPNext 16 table exists, an unmatched item is authoritative
        # zero. Falling back to a stale v15 JSON map could reintroduce the
        # item_code/idx collision this adapter is designed to prevent.
        return 0.0, 0.0

    # ERPNext 15 stores a JSON map keyed by item_code (or item_name when no
    # item_code exists). Resolve exactly one key. Do not inspect ``name`` or
    # ``idx`` here: those values identify the child row, not the JSON entry.
    legacy_key = _legacy_item_key(item)
    v15 = _v15_details(doc)
    if legacy_key in v15:
        value = v15[legacy_key]
        return value[0], value[1]

    return 0.0, 0.0
