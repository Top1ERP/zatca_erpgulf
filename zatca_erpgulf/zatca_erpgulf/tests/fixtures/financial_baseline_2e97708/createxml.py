"""Exact baseline financial function closure; test data, no imports or site setup.

Source: zatca_erpgulf/zatca_erpgulf/createxml.py
Revision: 2e97708e115e31c675182647d10829d6175e7449
"""

CBC_ID = "cbc:ID"

ZATCA_DISCOUNT_REASON_MAP = {
    "41": "Bonus for works ahead of schedule", "42": "Other bonus",
    "60": "Manufacturer's consumer discount", "62": "Due to military status",
    "63": "Due to work accident", "64": "Special agreement",
    "65": "Production error discount", "66": "New outlet discount",
    "67": "Sample discount", "68": "End of range discount",
    "70": "Incoterm discount", "71": "Point of sales threshold allowance",
    "88": "Material surcharge/deduction", "95": "Discount",
    "100": "Special rebate", "102": "Fixed long term",
    "103": "Temporary", "104": "Standard", "105": "Yearly turnover",
}

def get_zatca_discount_reason_code(reason):
    """Return the official ZATCA code for an English reason description."""
    normalized = str(reason or "").strip()
    reverse_map = {value: key for key, value in ZATCA_DISCOUNT_REASON_MAP.items()}
    return reverse_map.get(normalized, "")

def _abs_rounded(value, precision=2):
    """Safely convert numeric values to absolute rounded floats."""
    try:
        return abs(round(float(value or 0.0), precision))
    except (TypeError, ValueError):
        return 0.0

def _has_document_discount(sales_invoice_doc):
    """Return True when the invoice carries a document-level discount value."""
    return (
        _abs_rounded(getattr(sales_invoice_doc, "discount_amount", 0.0), 6) > 0
        or _abs_rounded(getattr(sales_invoice_doc, "base_discount_amount", 0.0), 6) > 0
    )

def _use_line_net_amounts_discount_model(sales_invoice_doc):
    """
    Decide whether XML should rely on line net amounts instead of a document-level
    AllowanceCharge.

    This returns True when either:
    - an explicit custom flag `custom_zatca_use_line_net_amounts` is enabled, or
    - the invoice has a document-level discount and the item lines already carry
      distributed net values / line discounts that reflect that discount.
    """
    try:
        if cint(getattr(sales_invoice_doc, "custom_zatca_use_line_net_amounts", 0)) == 1:
            return True
    except Exception:
        pass

    if not _has_document_discount(sales_invoice_doc):
        return False

    total_gross = 0.0
    total_net = 0.0
    has_line_level_discount_effect = False

    for item in getattr(sales_invoice_doc, "items", []) or []:
        gross_value = item.base_amount if sales_invoice_doc.currency == "SAR" else item.amount
        net_value = (
            item.base_net_amount if sales_invoice_doc.currency == "SAR" else item.net_amount
        )
        gross_value = _abs_rounded(gross_value, 6)
        net_value = _abs_rounded(net_value, 6)

        total_gross += gross_value
        total_net += net_value

        distributed_discount = _abs_rounded(
            getattr(item, "distributed_discount_amount", 0.0), 6
        )
        line_discount = _abs_rounded(getattr(item, "discount_amount", 0.0), 6)

        if distributed_discount > 0 or line_discount > 0 or abs(gross_value - net_value) > 0.000001:
            has_line_level_discount_effect = True

    return has_line_level_discount_effect and abs(total_gross - total_net) > 0.000001

def add_document_level_discount_with_tax(invoice, sales_invoice_doc):
    """
    Adds document-level discount elements to the XML invoice,
    including allowance charges, reason codes, and tax details.
    When invoice discounts are already reflected in line net amounts,
    the document-level AllowanceCharge is intentionally skipped to avoid
    double-discounting in the XML sent to ZATCA.
    """
    try:
        if _use_line_net_amounts_discount_model(sales_invoice_doc):
            return invoice

        discount_value = (
            _abs_rounded(sales_invoice_doc.get("base_discount_amount", 0.0))
            if sales_invoice_doc.currency == "SAR"
            else _abs_rounded(sales_invoice_doc.get("discount_amount", 0.0))
        )
        if discount_value <= 0:
            return invoice

        cac_allowance_charge = ET.SubElement(invoice, "cac:AllowanceCharge")

        cbc_charge_indicator = ET.SubElement(
            cac_allowance_charge, "cbc:ChargeIndicator"
        )
        cbc_charge_indicator.text = "false"

        cbc_allowance_charge_reason_code = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReasonCode"
        )
        cbc_allowance_charge_reason_code.text = get_zatca_discount_reason_code(
            sales_invoice_doc.custom_zatca_discount_reason
        )

        cbc_allowance_charge_reason = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReason"
        )
        cbc_allowance_charge_reason.text = sales_invoice_doc.custom_zatca_discount_reason or ""

        cbc_amount = ET.SubElement(
            cac_allowance_charge, "cbc:Amount", currencyID=sales_invoice_doc.currency
        )
        cbc_amount.text = f"{discount_value:.2f}"

        cac_tax_category = ET.SubElement(cac_allowance_charge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_tax_category, CBC_ID)
        if sales_invoice_doc.custom_zatca_tax_category == "Standard":
            cbc_id.text = "S"
        elif sales_invoice_doc.custom_zatca_tax_category == "Zero Rated":
            cbc_id.text = "Z"
        elif sales_invoice_doc.custom_zatca_tax_category == "Exempted":
            cbc_id.text = "E"
        elif (
            sales_invoice_doc.custom_zatca_tax_category
            == "Services outside scope of tax / Not subject to VAT"
        ):
            cbc_id.text = "O"

        cbc_percent = ET.SubElement(cac_tax_category, "cbc:Percent")
        cbc_percent.text = f"{float(sales_invoice_doc.taxes[0].rate):.2f}"

        cac_tax_scheme = ET.SubElement(cac_tax_category, "cac:TaxScheme")
        cbc_tax_scheme_id = ET.SubElement(cac_tax_scheme, CBC_ID)
        cbc_tax_scheme_id.text = "VAT"

        return invoice

    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(
            _(
                f"Error occurred while processing allowance charge data without template: {e}"
            )
        )
        return None

def add_document_level_discount_with_tax_template(invoice, sales_invoice_doc):
    """
    Adds document-level discount elements to the XML invoice,
    including allowance charges, reason codes, and tax details.
    When invoice discounts are already reflected in line net amounts,
    the document-level AllowanceCharge is intentionally skipped to avoid
    double-discounting in the XML sent to ZATCA.
    """
    try:
        if _use_line_net_amounts_discount_model(sales_invoice_doc):
            return invoice

        discount_value = (
            _abs_rounded(sales_invoice_doc.get("base_discount_amount", 0.0))
            if sales_invoice_doc.currency == "SAR"
            else _abs_rounded(sales_invoice_doc.get("discount_amount", 0.0))
        )
        if discount_value <= 0:
            return invoice

        # Create the AllowanceCharge element
        cac_allowance_charge = ET.SubElement(invoice, "cac:AllowanceCharge")

        # ChargeIndicator
        cbc_charge_indicator = ET.SubElement(
            cac_allowance_charge, "cbc:ChargeIndicator"
        )
        cbc_charge_indicator.text = "false"  # Indicates a discount

        # AllowanceChargeReason
        cbc_allowance_charge_reason_code = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReasonCode"
        )
        cbc_allowance_charge_reason_code.text = get_zatca_discount_reason_code(
            sales_invoice_doc.custom_zatca_discount_reason
        )

        cbc_allowance_charge_reason = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReason"
        )
        cbc_allowance_charge_reason.text = sales_invoice_doc.custom_zatca_discount_reason or ""

        cbc_amount = ET.SubElement(
            cac_allowance_charge, "cbc:Amount", currencyID=sales_invoice_doc.currency
        )
        cbc_amount.text = f"{discount_value:.2f}"

        # Tax Category Section
        cac_tax_category = ET.SubElement(cac_allowance_charge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_tax_category, CBC_ID)

        vat_category_code = "Standard"
        tax_percentage = 0.0

        for item in sales_invoice_doc.items:
            item_tax_template_doc = frappe.get_doc(
                "Item Tax Template", item.item_tax_template
            )
            vat_category_code = item_tax_template_doc.custom_zatca_tax_category
            tax_percentage = (
                item_tax_template_doc.taxes[0].tax_rate
                if item_tax_template_doc.taxes
                else 15
            )
            break  # Assuming that all items will have the same tax category and percentage

        if vat_category_code == "Standard":
            cbc_id.text = "S"
        elif vat_category_code == "Zero Rated":
            cbc_id.text = "Z"
        elif vat_category_code == "Exempted":
            cbc_id.text = "E"
        elif vat_category_code == "Services outside scope of tax / Not subject to VAT":
            cbc_id.text = "O"
        else:
            frappe.throw(
                "Invalid or missing ZATCA VAT category in the Item Tax Template "
                "linked to Sales Invoice Item. Ensure each Item Tax Template "
                "includes one of the following categories: "
                "'Standard', 'Zero Rated', 'Exempted', or 'Services outside scope of tax / Not subject to VAT'."
            )

        cbc_percent = ET.SubElement(cac_tax_category, "cbc:Percent")
        cbc_percent.text = f"{tax_percentage:.2f}"

        cac_tax_scheme = ET.SubElement(cac_tax_category, "cac:TaxScheme")
        cbc_tax_scheme_id = ET.SubElement(cac_tax_scheme, CBC_ID)
        cbc_tax_scheme_id.text = "VAT"

        return invoice

    except (ET.ParseError, AttributeError, ValueError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error occurred while processing allowance charge data: {e}"))
        return None

def add_nominal_discount_tax(invoice, sales_invoice_doc):
    """
    Adds nominal discount and related tax details to the XML structure.
    When invoice discounts are already reflected in line net amounts,
    the document-level AllowanceCharge is skipped to avoid double-discounting.
    """
    try:
        if _use_line_net_amounts_discount_model(sales_invoice_doc):
            return invoice

        cac_allowance_charge = ET.SubElement(invoice, "cac:AllowanceCharge")
        cbc_charge_indicator = ET.SubElement(
            cac_allowance_charge, "cbc:ChargeIndicator"
        )
        cbc_charge_indicator.text = "false"  # Indicates a discount

        cbc_allowance_charge_reason_code = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReasonCode"
        )
        cbc_allowance_charge_reason_code.text = get_zatca_discount_reason_code(
            sales_invoice_doc.custom_zatca_discount_reason
        )

        cbc_allowance_charge_reason = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReason"
        )
        cbc_allowance_charge_reason.text = sales_invoice_doc.custom_zatca_discount_reason or ""

        cbc_amount = ET.SubElement(
            cac_allowance_charge, "cbc:Amount", currencyID=sales_invoice_doc.currency
        )

        total_line_extension = 0

        for single_item in sales_invoice_doc.items:
            line_extension_amount = abs(
                round(
                    single_item.amount / (1 + sales_invoice_doc.taxes[0].rate / 100), 2
                )
            )
            total_line_extension += round(line_extension_amount, 2)
        discount_amount = abs(round(sales_invoice_doc.discount_amount, 2))
        difference = abs(round(discount_amount - total_line_extension, 2))

        if (
            sales_invoice_doc.currency == "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 0
        ):
            base_discount_amount = sales_invoice_doc.base_total
            cbc_amount.text = f"{base_discount_amount:.2f}"

        elif (
            sales_invoice_doc.currency == "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 1
        ):
            base_discount_amount = (
                total_line_extension
                if difference == 0.01
                else sales_invoice_doc.base_discount_amount
            )
            cbc_amount.text = f"{base_discount_amount:.2f}"

        elif (
            sales_invoice_doc.currency != "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 0
        ):
            discount_amount = sales_invoice_doc.total
            cbc_amount.text = f"{discount_amount:.2f}"

        elif (
            sales_invoice_doc.currency != "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 1
        ):
            discount_amount = (
                total_line_extension
                if difference == 0.01
                else sales_invoice_doc.discount_amount
            )
            cbc_amount.text = f"{discount_amount:.2f}"

        cac_tax_category = ET.SubElement(cac_allowance_charge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_tax_category, CBC_ID)
        cbc_id.text = "O"

        cbc_percent = ET.SubElement(cac_tax_category, "cbc:Percent")
        cbc_percent.text = "0.00"

        cbc_tax_exemption_reason_code = ET.SubElement(
            cac_tax_category, "cbc:TaxExemptionReasonCode"
        )
        cbc_tax_exemption_reason_code.text = "VATEX-SA-OOS"

        cbc_tax_exemption_reason = ET.SubElement(
            cac_tax_category, "cbc:TaxExemptionReason"
        )
        cbc_tax_exemption_reason.text = getattr(sales_invoice_doc, "custom_exemption_reason", None) or "Discount"

        cac_tax_scheme = ET.SubElement(cac_tax_category, "cac:TaxScheme")
        cbc_tax_scheme_id = ET.SubElement(cac_tax_scheme, CBC_ID)
        cbc_tax_scheme_id.text = "VAT"

        return invoice

    except (ValueError, KeyError, AttributeError) as error:
        frappe.throw(_(f"Error occurred in nominal discount: {str(error)}"))
        return None
