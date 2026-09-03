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


def _item_keys(item):
    return {
        str(value)
        for fieldname in ("name", "item_code", "idx")
        if (value := _value(item, fieldname)) not in (None, "")
    }


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
    item_keys = _item_keys(item)
    rows = _value(doc, "item_wise_tax_details") or []
    if rows:
        amount = rate = 0.0
        for detail in rows:
            item_ref = str(_value(detail, "item_row", "") or "")
            if item_ref in item_keys:
                amount += _number(_value(detail, "amount"))
                rate += _number(_value(detail, "rate"))
        if amount or rate:
            return amount, rate
    v15 = _v15_details(doc)
    values = [v15[key] for key in item_keys if key in v15]
    if values:
        return sum(value[0] for value in values), sum(value[1] for value in values)
    return 0.0, 0.0
