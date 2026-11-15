# Frozen increment221 monetary helpers; test data only.

def _append_tax_totals(invoice, currency, tax_breakdown, sales_invoice_doc):
    """
    Append the required invoice-level cac:TaxTotal blocks and return
    (document_currency_tax_total, subtotal_tax_sum).

    ZATCA requires:
    1) exactly one TaxTotal WITH TaxSubtotal(s), and
    2) exactly one TaxTotal WITHOUT TaxSubtotal(s) when TaxCurrencyCode exists.

    TaxCurrencyCode is always SAR in KSA invoices, so we always generate:
    - one detailed TaxTotal in the document currency (with TaxSubtotal blocks)
    - one summary-only TaxTotal in SAR (without TaxSubtotal)
    """
    total_tax = q2(sum(row["tax_amount"] for row in tax_breakdown))
    subtotal_tax_sum = Decimal("0.00")

    # 1) Detailed TaxTotal (with TaxSubtotal) in document currency
    cac_taxtotal_detailed = ET.SubElement(invoice, CAC_TAX_TOTAL)
    cbc_taxamount_detailed = ET.SubElement(cac_taxtotal_detailed, "cbc:TaxAmount")
    cbc_taxamount_detailed.set("currencyID", currency)
    cbc_taxamount_detailed.text = str(total_tax)

    for row in tax_breakdown:
        cac_taxsubtotal = ET.SubElement(cac_taxtotal_detailed, "cac:TaxSubtotal")

        cbc_taxableamount = ET.SubElement(cac_taxsubtotal, "cbc:TaxableAmount")
        cbc_taxableamount.set("currencyID", currency)
        cbc_taxableamount.text = str(q2(row["taxable_amount"]))

        cbc_taxamount_2 = ET.SubElement(cac_taxsubtotal, "cbc:TaxAmount")
        cbc_taxamount_2.set("currencyID", currency)
        cbc_taxamount_2.text = str(q2(row["tax_amount"]))

        subtotal_tax_sum += q2(row["tax_amount"])

        _add_tax_category(
            cac_taxsubtotal,
            row["zatca_tax_category"],
            row["tax_rate"],
            row["exemption_reason_code"]
            if row["zatca_tax_category"] != "Standard"
            else None,
            sales_invoice_doc.get("custom_exemption_reason"),
        )

    # 2) Summary-only TaxTotal (without TaxSubtotal) in SAR
    if currency == "SAR":
        accounting_tax_total = total_tax
    else:
        accounting_tax_total = q2(sales_invoice_doc.base_total_taxes_and_charges or 0)

    cac_taxtotal_summary = ET.SubElement(invoice, CAC_TAX_TOTAL)
    cbc_taxamount_summary = ET.SubElement(cac_taxtotal_summary, "cbc:TaxAmount")
    cbc_taxamount_summary.set("currencyID", "SAR")
    cbc_taxamount_summary.text = str(accounting_tax_total)

    return total_tax, q2(subtotal_tax_sum)


def _get_payable_rounding_amount(sales_invoice_doc):
    """Return BT-114 in document currency when ERPNext rounding is enabled."""
    if int(getattr(sales_invoice_doc, "disable_rounded_total", 0) or 0):
        return Decimal("0.00")
    return q2(getattr(sales_invoice_doc, "rounding_adjustment", 0) or 0)


def _previous_pos_rounding_disabled(doc):
    """Read native controls without recalculation or a POS-profile override.

    POS may have no disable_rounded_total field: AccountsController then reads
    Global Defaults. A consolidated invoice's existing nonzero adjustment
    bypasses that disabled branch in both inspected controller versions.
    """
    if _flag(doc, "is_consolidated") and _number(doc.get("rounding_adjustment") or 0) != 0:
        return False
    native = getattr(doc, "is_rounded_total_disabled", None)
    if callable(native):
        return _number(native() or 0) != 0
    if doc.get("disable_rounded_total") is None:
        raise PosFinancialError("rounding_source", MISSING)
    return _flag(doc, "disable_rounded_total")
