"""Frozen pre-fix invoice/template rate selector; test reference only."""

def _get_invoice_level_tax_rate(doc) -> float:
    for tax_row in getattr(doc, "taxes", []) or []:
        value = getattr(tax_row, "rate", None)

        if value not in (None, ""):
            return flt(value)

    return 0.0


def _get_invoice_level_zatca_source(doc):
    """Resolve invoice-level ZATCA fields, preferring Sales Invoice values."""
    sales_template = _get_sales_taxes_template_doc(doc)
    invoice_category = _safe_str(getattr(doc, "custom_zatca_tax_category", None))
    invoice_exemption_reason = _safe_str(getattr(doc, "custom_exemption_reason_code", None))
    invoice_rate = _get_invoice_level_tax_rate(doc)

    template_category = ""
    template_exemption_reason = ""
    template_rate = None
    if sales_template:
        template_category = _safe_str(getattr(sales_template, "custom_zatca_tax_category", None))
        template_exemption_reason = _safe_str(
            getattr(sales_template, "custom_exemption_reason_code", None)
        )
        template_rate = _get_template_rate(sales_template)

    if invoice_category:
        return {
            "source_type": "invoice",
            "source_name": _zt("Sales Invoice ZATCA fields"),
            "category": invoice_category,
            "exemption_reason": invoice_exemption_reason or template_exemption_reason,
            "rate": invoice_rate if invoice_rate else template_rate,
        }

    if template_category:
        return {
            "source_type": "sales_taxes_template",
            "source_name": _zt("Sales Taxes and Charges Template {0}").format(
                sales_template.name
            ),
            "category": template_category,
            "exemption_reason": template_exemption_reason,
            "rate": template_rate,
        }

    location = (
        _zt("Sales Invoice ZATCA fields and Sales Taxes and Charges Template")
        if sales_template
        else _zt("Sales Invoice ZATCA fields")
    )
    return {
        "source_type": "missing",
        "source_name": location,
        "category": "",
        "exemption_reason": "",
        "rate": template_rate,
    }
