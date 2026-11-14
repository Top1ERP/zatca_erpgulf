"""Exact pre-group-rounding functions from d3286d5; test data only."""

def _new_tax_rate_bucket(category, rate, exemption_reason_code, *, include_sar=False):
    """Create zeroed accumulators; callers own source selection and rounding."""
    row = {
        "zatca_tax_category": category,
        "taxable_amount": Decimal("0.00"),
        "tax_amount": Decimal("0.00"),
    }
    if include_sar:
        row["sar_tax_amount"] = Decimal("0.00")
    row["tax_rate"] = rate
    row["exemption_reason_code"] = exemption_reason_code if category != "Standard" else None
    return row

def _get_tax_breakdown_without_template(sales_invoice_doc):
    """Build separate net/tax subtotals for each selected non-template rate."""
    tax_category, exemption_reason_code = _get_invoice_level_zatca_tax_source(sales_invoice_doc)
    # Retain the original whole-document net read/validation before rate reads.
    taxable_amount = _sum_line_net_amounts(sales_invoice_doc)
    groups = {}
    for item in sales_invoice_doc.items:
        item_tax_rate = _get_item_tax_rate_without_template(sales_invoice_doc, item)
        item_net_amount = _get_item_net_amount(item, sales_invoice_doc.currency)
        # NaN does not equal itself; use a stable diagnostic key.
        rate_key = item_tax_rate if item_tax_rate.is_finite() else None
        if rate_key not in groups:
            groups[rate_key] = _new_tax_rate_bucket(
                tax_category, item_tax_rate, exemption_reason_code
            )
        row = groups[rate_key]
        row["taxable_amount"] += item_net_amount
        row["tax_amount"] += q2(item_net_amount * item_tax_rate / Decimal("100"))

    if not groups:
        groups[Decimal("0.00")] = _new_tax_rate_bucket(
            tax_category, Decimal("0.00"), exemption_reason_code
        )
        groups[Decimal("0.00")]["taxable_amount"] = taxable_amount
    elif len(groups) == 1:
        # Keep the original aggregate source for homogeneous invoices.
        next(iter(groups.values()))["taxable_amount"] = taxable_amount
    for row in groups.values():
        row["taxable_amount"] = q2(row["taxable_amount"])
        row["tax_amount"] = q2(row["tax_amount"])
        row["tax_rate"] = q2(row["tax_rate"])
    return list(groups.values())

def _get_tax_breakdown_with_template(sales_invoice_doc):
    """Build VAT breakdown from line net amounts grouped by item tax template category."""
    tax_category_totals = {}
    currency = sales_invoice_doc.currency

    for item in sales_invoice_doc.items:
        item_tax_template = frappe.get_doc("Item Tax Template", item.item_tax_template)
        zatca_tax_category = item_tax_template.custom_zatca_tax_category
        tax_rate = (
            Decimal(str(item_tax_template.taxes[0].tax_rate))
            if item_tax_template.taxes
            else Decimal("15.00")
        )
        exemption_reason_code = item_tax_template.custom_exemption_reason_code
        item_net_amount = _get_item_net_amount(item, currency)

        key = (zatca_tax_category, q2(tax_rate), exemption_reason_code)
        if key not in tax_category_totals:
            tax_category_totals[key] = {
                "zatca_tax_category": zatca_tax_category,
                "taxable_amount": Decimal("0.00"),
                "tax_amount": Decimal("0.00"),
                "tax_rate": q2(tax_rate),
                "exemption_reason_code": exemption_reason_code,
            }

        tax_category_totals[key]["taxable_amount"] += item_net_amount
        tax_category_totals[key]["tax_amount"] += q2(item_net_amount * q2(tax_rate) / Decimal("100"))

    result = []
    for _, totals in tax_category_totals.items():
        totals["taxable_amount"] = q2(totals["taxable_amount"])
        totals["tax_amount"] = q2(totals["tax_amount"])
        result.append(totals)

    return result

def _nominal_breakdown_without_template(sales_invoice_doc):
    """Group nominal values by selected rate without inferring tax categories."""
    tax_category = sales_invoice_doc.get("custom_zatca_tax_category") or "Standard"
    exemption_reason_code = sales_invoice_doc.get("custom_exemption_reason_code")
    groups = {}

    for item in sales_invoice_doc.items:
        item_tax_rate = _nominal_tax_rate_without_template(sales_invoice_doc, item)
        # Preserve the original net/base acquisition order and per-line rounding.
        line_net = _nominal_item_net_amount(item, sales_invoice_doc)
        line_base_net = _nominal_item_base_net_amount(item)
        # NaN does not equal itself; use a stable diagnostic key.
        rate_key = item_tax_rate if item_tax_rate.is_finite() else None
        if rate_key not in groups:
            groups[rate_key] = _new_tax_rate_bucket(
                tax_category, item_tax_rate, exemption_reason_code, include_sar=True
            )
        row = groups[rate_key]
        row["taxable_amount"] += line_net
        row["tax_amount"] += _nominal_q2(line_net * item_tax_rate / Decimal("100"))
        row["sar_tax_amount"] += _nominal_q2(line_base_net * item_tax_rate / Decimal("100"))

    if not groups:
        # Keep the prior empty-table row rather than dropping required subtotals.
        groups[Decimal("0.00")] = _new_tax_rate_bucket(
            tax_category, Decimal("0.00"), exemption_reason_code, include_sar=True
        )
    for row in groups.values():
        row["taxable_amount"] = _nominal_q2(row["taxable_amount"])
        row["tax_amount"] = _nominal_q2(row["tax_amount"])
        row["sar_tax_amount"] = _nominal_q2(row["sar_tax_amount"])
        row["tax_rate"] = _nominal_q2(row["tax_rate"])
    return list(groups.values())

def _nominal_breakdown_with_template(sales_invoice_doc):
    tax_category_totals = {}

    for item in sales_invoice_doc.items:
        item_tax_template = frappe.get_doc(ITEM_TAX_TEMPLATE, item.item_tax_template)
        zatca_tax_category = item_tax_template.custom_zatca_tax_category
        tax_rate = (
            Decimal(str(item_tax_template.taxes[0].tax_rate))
            if item_tax_template.taxes
            else Decimal("15.00")
        )
        exemption_reason_code = item_tax_template.custom_exemption_reason_code

        line_net = _nominal_item_net_amount(item, sales_invoice_doc)
        line_base_net = _nominal_item_base_net_amount(item)

        key = (zatca_tax_category, _nominal_q2(tax_rate), exemption_reason_code)
        if key not in tax_category_totals:
            tax_category_totals[key] = {
                "zatca_tax_category": zatca_tax_category,
                "taxable_amount": Decimal("0.00"),
                "tax_amount": Decimal("0.00"),
                "sar_tax_amount": Decimal("0.00"),
                "tax_rate": _nominal_q2(tax_rate),
                "exemption_reason_code": exemption_reason_code,
            }

        tax_category_totals[key]["taxable_amount"] += line_net
        tax_category_totals[key]["tax_amount"] += _nominal_q2(line_net * _nominal_q2(tax_rate) / Decimal("100"))
        tax_category_totals[key]["sar_tax_amount"] += _nominal_q2(line_base_net * _nominal_q2(tax_rate) / Decimal("100"))

    result = []
    for _, totals in tax_category_totals.items():
        totals["taxable_amount"] = _nominal_q2(totals["taxable_amount"])
        totals["tax_amount"] = _nominal_q2(totals["tax_amount"])
        totals["sar_tax_amount"] = _nominal_q2(totals["sar_tax_amount"])
        result.append(totals)

    return result
