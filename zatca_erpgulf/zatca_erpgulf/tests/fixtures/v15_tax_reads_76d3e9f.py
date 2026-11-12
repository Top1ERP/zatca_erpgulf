"""Frozen parent tax lookup functions; synthetic test reference only."""

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
