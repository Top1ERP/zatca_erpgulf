"""Frozen pre-fix zero-discarding consumers and rate buckets; test reference only."""

def _nominal_tax_rate_without_template(sales_invoice_doc, single_item):
    try:
        if sales_invoice_doc.get("taxes"):
            tax_percentage = get_item_tax_rate(sales_invoice_doc, single_item)
            if tax_percentage not in (None, "") and tax_percentage != 0:
                return _nominal_q2(tax_percentage)
    except Exception:
        pass

    if sales_invoice_doc.get("taxes"):
        return _nominal_q2(sales_invoice_doc.taxes[0].get("rate", 0))
    return _nominal_q2(0)


def _nominal_breakdown_without_template(sales_invoice_doc):
    tax_category = sales_invoice_doc.get("custom_zatca_tax_category") or "Standard"
    exemption_reason_code = sales_invoice_doc.get("custom_exemption_reason_code")

    taxable_amount = Decimal("0.00")
    tax_amount = Decimal("0.00")
    sar_tax_amount = Decimal("0.00")
    effective_rate = None

    for item in sales_invoice_doc.items:
        item_tax_rate = _nominal_tax_rate_without_template(sales_invoice_doc, item)
        if effective_rate is None:
            effective_rate = item_tax_rate

        line_net = _nominal_item_net_amount(item, sales_invoice_doc)
        line_base_net = _nominal_item_base_net_amount(item)

        taxable_amount += line_net
        tax_amount += _nominal_q2(line_net * item_tax_rate / Decimal("100"))
        sar_tax_amount += _nominal_q2(line_base_net * item_tax_rate / Decimal("100"))

    return [{
        "zatca_tax_category": tax_category,
        "taxable_amount": _nominal_q2(taxable_amount),
        "tax_amount": _nominal_q2(tax_amount),
        "sar_tax_amount": _nominal_q2(sar_tax_amount),
        "tax_rate": _nominal_q2(effective_rate or 0),
        "exemption_reason_code": exemption_reason_code if tax_category != "Standard" else None,
    }]


def _get_item_tax_rate_without_template(sales_invoice_doc, item):
    """Get tax rate for an item from item-wise tax detail or fallback to invoice tax rate."""
    try:
        if sales_invoice_doc.get("taxes"):
            tax_percentage = get_item_tax_rate(sales_invoice_doc, item)
            if tax_percentage not in (None, "") and tax_percentage != 0:
                return q2(tax_percentage)
    except Exception:
        pass

    if sales_invoice_doc.get("taxes"):
        return q2(sales_invoice_doc.taxes[0].get("rate", 0))
    return Decimal("0.00")


def _get_tax_breakdown_without_template(sales_invoice_doc):
    """Build VAT breakdown from line net amounts for invoices without item tax template."""
    tax_category, exemption_reason_code = _get_invoice_level_zatca_tax_source(sales_invoice_doc)

    taxable_amount = _sum_line_net_amounts(sales_invoice_doc)

    # Sum tax with line-level rounding to match ERPNext / ZATCA expectations.
    total_tax = Decimal("0.00")
    effective_rate = None
    for item in sales_invoice_doc.items:
        item_tax_rate = _get_item_tax_rate_without_template(sales_invoice_doc, item)
        if effective_rate is None:
            effective_rate = item_tax_rate
        item_net_amount = _get_item_net_amount(item, sales_invoice_doc.currency)
        total_tax += q2(item_net_amount * item_tax_rate / Decimal("100"))

    total_tax = q2(total_tax)
    effective_rate = q2(effective_rate or 0)

    return [
        {
            "zatca_tax_category": tax_category,
            "taxable_amount": taxable_amount,
            "tax_amount": total_tax,
            "tax_rate": effective_rate,
            "exemption_reason_code": (
                exemption_reason_code if tax_category != "Standard" else None
            ),
        }
    ]
