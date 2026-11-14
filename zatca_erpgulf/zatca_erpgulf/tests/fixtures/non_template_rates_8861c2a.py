"""Frozen non-template rate wrappers from 8861c2a; test data only."""

def _get_item_tax_rate_without_template(sales_invoice_doc, item):
    """Get tax rate for an item from item-wise tax detail or fallback to invoice tax rate."""
    # Preserve selected zero; absent/failed lookup keeps the invoice fallback.
    try:
        if sales_invoice_doc.get("taxes"):
            tax_percentage = get_item_tax_rate(sales_invoice_doc, item, default=None)
            if tax_percentage not in (None, ""):
                return q2(tax_percentage)
    except Exception:
        pass

    if sales_invoice_doc.get("taxes"):
        return q2(sales_invoice_doc.taxes[0].get("rate", 0))
    return Decimal("0.00")

def _nominal_tax_rate_without_template(sales_invoice_doc, single_item):
    # Preserve selected zero; absent/failed lookup keeps the invoice fallback.
    try:
        if sales_invoice_doc.get("taxes"):
            tax_percentage = get_item_tax_rate(sales_invoice_doc, single_item, default=None)
            if tax_percentage not in (None, ""):
                return _nominal_q2(tax_percentage)
    except Exception:
        pass

    if sales_invoice_doc.get("taxes"):
        return _nominal_q2(sales_invoice_doc.taxes[0].get("rate", 0))
    return _nominal_q2(0)
