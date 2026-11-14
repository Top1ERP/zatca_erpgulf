"""Exact baseline financial function closure; test data, no imports or site setup.

Source: zatca_erpgulf/zatca_erpgulf/posxml.py
Revision: 2e97708e115e31c675182647d10829d6175e7449
"""

def add_document_level_discount_with_tax(invoice, pos_invoice_doc):
    """function for add document level discount"""
    try:
        # Create the AllowanceCharge element
        cac_allowancecharge = ET.SubElement(invoice, "cac:AllowanceCharge")

        # ChargeIndicator
        cbc_chargeindicator = ET.SubElement(cac_allowancecharge, "cbc:ChargeIndicator")
        cbc_chargeindicator.text = "false"  # Indicates a discount

        # AllowanceChargeReason
        cbc_allowancechargereason = ET.SubElement(
            cac_allowancecharge, "cbc:AllowanceChargeReason"
        )
        cbc_allowancechargereason.text = "Discount"

        # Assuming this is within your add_document_level_discount_with_tax function
        cbc_amount = ET.SubElement(
            cac_allowancecharge, "cbc:Amount", currencyID=pos_invoice_doc.currency
        )
        base_discount_amount = pos_invoice_doc.get("discount_amount", 0.0)
        cbc_amount.text = f"{base_discount_amount:.2f}"

        # Tax Category Section
        cac_taxcategory = ET.SubElement(cac_allowancecharge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_taxcategory, "cbc:ID")

        # Determine the VAT category code from the sales_invoice_doc
        if pos_invoice_doc.custom_zatca_tax_category == "Standard":
            cbc_id.text = "S"
        elif pos_invoice_doc.custom_zatca_tax_category == "Zero Rated":
            cbc_id.text = "Z"
        elif pos_invoice_doc.custom_zatca_tax_category == "Exempted":
            cbc_id.text = "E"
        elif (
            pos_invoice_doc.custom_zatca_tax_category
            == "Services outside scope of tax / Not subject to VAT"
        ):
            cbc_id.text = "O"
        # Retrieve the VAT percentage from the first tax entry in the sales_invoice_doc
        cbc_percent = ET.SubElement(cac_taxcategory, "cbc:Percent")

        cbc_percent.text = f"{float(pos_invoice_doc.taxes[0].rate):.2f}"

        cac_taxscheme = ET.SubElement(cac_taxcategory, "cac:TaxScheme")
        cbc_taxschemeid = ET.SubElement(cac_taxscheme, "cbc:ID")
        cbc_taxschemeid.text = "VAT"
        return invoice
    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(
            _(
                f"Error occurred while processing allowance charge data without template: {e}"
            )
        )
        return None

def add_document_level_discount_with_tax_template(invoice, pos_invoice_doc):
    """add document level discount"""
    try:
        # Create the AllowanceCharge element
        cac_allowancecharge = ET.SubElement(invoice, "cac:AllowanceCharge")
        # ChargeIndicator
        cbc_chargeindicator = ET.SubElement(cac_allowancecharge, "cbc:ChargeIndicator")
        cbc_chargeindicator.text = "false"  # Indicates a discount
        # AllowanceChargeReason
        cbc_allowancechargereason = ET.SubElement(
            cac_allowancecharge, "cbc:AllowanceChargeReason"
        )
        cbc_allowancechargereason.text = "Discount"
        # Discount Amount
        cbc_amount = ET.SubElement(
            cac_allowancecharge, "cbc:Amount", currencyID=pos_invoice_doc.currency
        )
        base_discount_amount = pos_invoice_doc.get("discount_amount", 0.0)
        cbc_amount.text = f"{base_discount_amount:.2f}"
        # Tax Category Section
        cac_taxcategory = ET.SubElement(cac_allowancecharge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_taxcategory, "cbc:ID")
        # Retrieve the VAT category code from the first applicable tax template in the items
        vat_category = "Standard"
        tax_percentage = 0.0
        for item in pos_invoice_doc.items:
            item_tax_template = frappe.get_doc(
                "Item Tax Template", item.item_tax_template
            )
            vat_category = item_tax_template.custom_zatca_tax_category
            tax_percentage = (
                item_tax_template.taxes[0].tax_rate if item_tax_template.taxes else 15
            )
            break  # Assuming that all items will have the same tax category and percentage
        # Set VAT category code in the XML
        if vat_category == "Standard":
            cbc_id.text = "S"
        elif vat_category == "Zero Rated":
            cbc_id.text = "Z"
        elif vat_category == "Exempted":
            cbc_id.text = "E"
        elif vat_category == "Services outside scope of tax / Not subject to VAT":
            cbc_id.text = "O"
        else:
            frappe.throw(
                "Invalid or missing ZATCA VAT category in the Item Tax Template "
                "linked to Sales Invoice Item. Ensure each Item Tax Template "
                "includes one of the following categories: "
                "'Standard', 'Zero Rated', 'Exempted', or 'Services outside scope of tax / Not subject to VAT'."
            )

        cbc_percent = ET.SubElement(cac_taxcategory, "cbc:Percent")
        cbc_percent.text = f"{tax_percentage:.2f}"
        cac_taxscheme = ET.SubElement(cac_taxcategory, "cac:TaxScheme")
        cbc_taxschemeid = ET.SubElement(cac_taxscheme, "cbc:ID")
        cbc_taxschemeid.text = "VAT"
        return invoice
    except (ET.ParseError, AttributeError, ValueError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error occurred while processing allowance charge data: {e}"))
        return None

def add_line_item_discount(cac_price, single_item, pos_invoice_doc):
    """adding line item discount"""
    cac_allowancecharge = ET.SubElement(cac_price, "cac:AllowanceCharge")

    cbc_chargeindicator = ET.SubElement(cac_allowancecharge, "cbc:ChargeIndicator")
    cbc_chargeindicator.text = "false"  # Indicates a discount

    cbc_allowancechargereason = ET.SubElement(
        cac_allowancecharge, "cbc:AllowanceChargeReason"
    )
    cbc_allowancechargereason.text = "discount"

    cbc_amount = ET.SubElement(
        cac_allowancecharge, "cbc:Amount", currencyID=pos_invoice_doc.currency
    )
    cbc_amount.text = str(abs(single_item.discount_amount))

    cbc_baseamount = ET.SubElement(
        cac_allowancecharge, "cbc:BaseAmount", currencyID=pos_invoice_doc.currency
    )
    cbc_baseamount.text = str(abs(single_item.price_list_rate))

    return cac_price

def get_exemption_reason_map():
    """Mapping of the exception reason code accoding to the reason code"""
    return {
        "VATEX-SA-29": (
            "Financial services mentioned in Article 29 of the VAT Regulations"
        ),
        "VATEX-SA-29-7": (
            "Life insurance services mentioned in Article 29 of the VAT Regulations"
        ),
        "VATEX-SA-30": (
            "Real estate transactions mentioned in Article 30 of the VAT Regulations"
        ),
        "VATEX-SA-32": "Export of goods",
        "VATEX-SA-33": "Export of services",
        "VATEX-SA-34-1": "The international transport of Goods",
        "VATEX-SA-34-2": "International transport of passengers",
        "VATEX-SA-34-3": (
            "Services directly connected and incidental to a Supply of "
            "international passenger transport"
        ),
        "VATEX-SA-34-4": "Supply of a qualifying means of transport",
        "VATEX-SA-34-5": (
            "Any services relating to Goods or passenger transportation, as defined "
            "in article twenty five of these Regulations"
        ),
        "VATEX-SA-35": "Medicines and medical equipment",
        "VATEX-SA-36": "Qualifying metals",
        "VATEX-SA-EDU": "Private education to citizen",
        "VATEX-SA-HEA": "Private healthcare to citizen",
        "VATEX-SA-MLTRY": "Supply of qualified military goods",
        "VATEX-SA-OOS": "",
    }

def get_tax_total_from_items(pos_invoice_doc):
    """function for get tax total from items"""
    try:
        total_tax = 0
        for single_item in pos_invoice_doc.items:
            # _ = item_tax_amount
            _item_tax_amount, tax_percent = get_item_tax_detail(pos_invoice_doc, single_item)
            total_tax = total_tax + (single_item.net_amount * (tax_percent / 100))
        return total_tax
    except (AttributeError, KeyError, ValueError, TypeError) as e:
        frappe.throw(_(f"Data processing error in tax data: {str(e)}"))

def tax_data(invoice, pos_invoice_doc):
    """Function for tax data"""
    try:
        pos_profile = pos_invoice_doc.pos_profile
        if not pos_profile:
            frappe.throw(_("POS Profile is not set in the POS Invoice."))
        pos_profile_doc = frappe.get_doc("POS Profile", pos_profile)
        taxes_and_charges = pos_profile_doc.taxes_and_charges

        taxes_template_doc = frappe.get_doc(
            "Sales Taxes and Charges Template", taxes_and_charges
        )

        tax_rate = taxes_template_doc.taxes[0]

        # Handle SAR-specific logic
        if pos_invoice_doc.currency == "SAR":
            cac_taxtotal = ET.SubElement(invoice, "cac:TaxTotal")
            cbc_taxamount_sar = ET.SubElement(cac_taxtotal, "cbc:TaxAmount")
            cbc_taxamount_sar.set(
                "currencyID", "SAR"
            )  # ZATCA requires tax amount in SAR
            tax_amount_without_retention_sar = round(
                abs(get_tax_total_from_items(pos_invoice_doc)), 2
            )
            cbc_taxamount_sar.text = str(
                tax_amount_without_retention_sar
            )  # Tax amount in SAR

            if tax_rate.included_in_print_rate == 0:
                taxable_amount = pos_invoice_doc.base_total - pos_invoice_doc.get(
                    "base_discount_amount", 0.0
                )
            else:
                taxable_amount = pos_invoice_doc.base_net_total - pos_invoice_doc.get(
                    "base_discount_amount", 0.0
                )

            cac_taxtotal = ET.SubElement(invoice, "cac:TaxTotal")
            cbc_taxamount = ET.SubElement(cac_taxtotal, "cbc:TaxAmount")
            cbc_taxamount.set("currencyID", pos_invoice_doc.currency)
            tax_amount_without_retention = round(
                abs(get_tax_total_from_items(pos_invoice_doc)), 2
            )

            tax_amount_without_retention = (
                taxable_amount * float(pos_invoice_doc.taxes[0].rate) / 100
            )
            cbc_taxamount.text = f"{abs(round(tax_amount_without_retention, 2)):.2f}"
            cac_taxsubtotal = ET.SubElement(cac_taxtotal, "cac:TaxSubtotal")
            cbc_taxableamount = ET.SubElement(cac_taxsubtotal, "cbc:TaxableAmount")
            cbc_taxableamount.set("currencyID", pos_invoice_doc.currency)
            if tax_rate.included_in_print_rate == 0:
                taxable_amount = pos_invoice_doc.base_total - pos_invoice_doc.get(
                    "base_discount_amount", 0.0
                )
            else:
                taxable_amount = pos_invoice_doc.base_net_total - pos_invoice_doc.get(
                    "base_discount_amount", 0.0
                )
            cbc_taxableamount.text = str(abs(round(taxable_amount, 2)))

            # tax_rate = float(pos_invoice_doc.taxes[0].rate)
            cbc_taxamount_2 = ET.SubElement(cac_taxsubtotal, "cbc:TaxAmount")
            cbc_taxamount_2.set("currencyID", pos_invoice_doc.currency)
            cbc_taxamount_2.text = str(
                abs(
                    round(
                        taxable_amount * float(pos_invoice_doc.taxes[0].rate) / 100, 2
                    )
                )
            )
        # Handle USD-specific logic
        else:
            cac_taxtotal = ET.SubElement(invoice, "cac:TaxTotal")
            cbc_taxamount_usd_1 = ET.SubElement(cac_taxtotal, "cbc:TaxAmount")
            cbc_taxamount_usd_1.set(
                "currencyID", pos_invoice_doc.currency
            )  # USD currency
            if tax_rate.included_in_print_rate == 0:
                taxable_amount_1 = pos_invoice_doc.total - pos_invoice_doc.get(
                    "discount_amount", 0.0
                )
            else:
                taxable_amount_1 = pos_invoice_doc.net_total - pos_invoice_doc.get(
                    "discount_amount", 0.0
                )

            tax_amount_without_retention = (
                taxable_amount_1 * float(pos_invoice_doc.taxes[0].rate) / 100
            )

            cbc_taxamount_usd_1.text = str(round(tax_amount_without_retention, 2))
            cac_taxtotal = ET.SubElement(invoice, "cac:TaxTotal")
            cbc_taxamount_usd = ET.SubElement(cac_taxtotal, "cbc:TaxAmount")
            cbc_taxamount_usd.set(
                "currencyID", pos_invoice_doc.currency
            )  # USD currency
            if tax_rate.included_in_print_rate == 0:
                taxable_amount_1 = pos_invoice_doc.total - pos_invoice_doc.get(
                    "discount_amount", 0.0
                )
            else:
                taxable_amount_1 = pos_invoice_doc.net_total - pos_invoice_doc.get(
                    "discount_amount", 0.0
                )
            # tax_rate = float(pos_invoice_doc.taxes[0].rate)
            tax_amount_without_retention = (
                taxable_amount_1 * float(pos_invoice_doc.taxes[0].rate) / 100
            )
            cbc_taxamount_usd.text = str(round(tax_amount_without_retention, 2))

            # Tax Subtotal
            cac_taxsubtotal = ET.SubElement(cac_taxtotal, "cac:TaxSubtotal")
            cbc_taxableamount = ET.SubElement(cac_taxsubtotal, "cbc:TaxableAmount")
            cbc_taxableamount.set("currencyID", pos_invoice_doc.currency)
            cbc_taxableamount.text = str(abs(round(taxable_amount_1, 2)))

            cbc_taxamount_2 = ET.SubElement(cac_taxsubtotal, "cbc:TaxAmount")
            cbc_taxamount_2.set("currencyID", pos_invoice_doc.currency)
            cbc_taxamount_2.text = str(
                abs(
                    round(
                        taxable_amount_1 * float(pos_invoice_doc.taxes[0].rate) / 100, 2
                    )
                )
            )
        # Tax Category and Scheme
        cac_taxcategory_1 = ET.SubElement(cac_taxsubtotal, "cac:TaxCategory")
        cbc_id_8 = ET.SubElement(cac_taxcategory_1, "cbc:ID")

        if pos_invoice_doc.custom_zatca_tax_category == "Standard":
            cbc_id_8.text = "S"
        elif pos_invoice_doc.custom_zatca_tax_category == "Zero Rated":
            cbc_id_8.text = "Z"
        elif pos_invoice_doc.custom_zatca_tax_category == "Exempted":
            cbc_id_8.text = "E"
        elif (
            pos_invoice_doc.custom_zatca_tax_category
            == "Services outside scope of tax / Not subject to VAT"
        ):
            cbc_id_8.text = "O"

        cbc_percent_1 = ET.SubElement(cac_taxcategory_1, "cbc:Percent")
        cbc_percent_1.text = f"{float(pos_invoice_doc.taxes[0].rate):.2f}"

        # Exemption Reason (if applicable)
        exemption_reason_map = get_exemption_reason_map()
        if pos_invoice_doc.custom_zatca_tax_category != "Standard":
            cbc_taxexemptionreasoncode = ET.SubElement(
                cac_taxcategory_1, "cbc:TaxExemptionReasonCode"
            )
            cbc_taxexemptionreasoncode.text = (
                pos_invoice_doc.custom_exemption_reason_code
            )
            cbc_taxexemptionreason = ET.SubElement(
                cac_taxcategory_1, "cbc:TaxExemptionReason"
            )
            reason_code = pos_invoice_doc.custom_exemption_reason_code
            reason_text = (
                getattr(pos_invoice_doc, "custom_exemption_reason", None)
                if reason_code == "VATEX-SA-OOS"
                else exemption_reason_map.get(reason_code, "")
            )
            if reason_text:
                cbc_taxexemptionreason.text = reason_text

        # Tax Scheme
        cac_taxscheme_3 = ET.SubElement(cac_taxcategory_1, "cac:TaxScheme")
        cbc_id_9 = ET.SubElement(cac_taxscheme_3, "cbc:ID")
        cbc_id_9.text = "VAT"

        # Legal Monetary Total (adjust for both SAR and USD)
        cac_legalmonetarytotal = ET.SubElement(invoice, "cac:LegalMonetaryTotal")
        cbc_lineextensionamount = ET.SubElement(
            cac_legalmonetarytotal, "cbc:LineExtensionAmount"
        )
        cbc_lineextensionamount.set("currencyID", pos_invoice_doc.currency)
        if tax_rate.included_in_print_rate == 0:
            cbc_lineextensionamount.text = str(round(abs(pos_invoice_doc.total), 2))
        else:
            cbc_lineextensionamount.text = str(round(abs(pos_invoice_doc.net_total), 2))
        cbc_taxexclusiveamount = ET.SubElement(
            cac_legalmonetarytotal, "cbc:TaxExclusiveAmount"
        )
        cbc_taxexclusiveamount.set("currencyID", pos_invoice_doc.currency)
        if tax_rate.included_in_print_rate == 0:
            cbc_taxexclusiveamount.text = str(
                round(
                    abs(
                        pos_invoice_doc.total
                        - pos_invoice_doc.get("discount_amount", 0.0)
                    ),
                    2,
                )
            )
        else:
            cbc_taxexclusiveamount.text = str(
                round(
                    abs(
                        pos_invoice_doc.net_total
                        - pos_invoice_doc.get("discount_amount", 0.0)
                    ),
                    2,
                )
            )

        cbc_taxinclusiveamount = ET.SubElement(
            cac_legalmonetarytotal, "cbc:TaxInclusiveAmount"
        )
        cbc_taxinclusiveamount.set("currencyID", pos_invoice_doc.currency)
        if tax_rate.included_in_print_rate == 0:
            cbc_taxinclusiveamount.text = "{:.2f}".format(
                round(
                    abs(
                        pos_invoice_doc.total
                        - pos_invoice_doc.get("discount_amount", 0.0)
                    )
                    + abs(tax_amount_without_retention),
                    2,
                )
            )
        else:
            cbc_taxinclusiveamount.text = "{:.2f}".format(
                round(
                    abs(
                        pos_invoice_doc.net_total
                        - pos_invoice_doc.get("discount_amount", 0.0)
                    )
                    + abs(tax_amount_without_retention),
                    2,
                )
            )

        cbc_allowancetotalamount = ET.SubElement(
            cac_legalmonetarytotal, "cbc:AllowanceTotalAmount"
        )
        cbc_allowancetotalamount.set("currencyID", pos_invoice_doc.currency)
        cbc_allowancetotalamount.text = str(
            abs(pos_invoice_doc.get("discount_amount", 0.0))
        )

        cbc_payableamount = ET.SubElement(cac_legalmonetarytotal, "cbc:PayableAmount")
        cbc_payableamount.set("currencyID", pos_invoice_doc.currency)
        if tax_rate.included_in_print_rate == 0:
            cbc_payableamount.text = "{:.2f}".format(
                round(
                    abs(
                        pos_invoice_doc.total
                        - pos_invoice_doc.get("discount_amount", 0.0)
                    )
                    + abs(tax_amount_without_retention),
                    2,
                )
            )
        else:
            cbc_payableamount.text = "{:.2f}".format(
                round(
                    abs(
                        pos_invoice_doc.net_total
                        - pos_invoice_doc.get("discount_amount", 0.0)
                    )
                    + abs(tax_amount_without_retention),
                    2,
                )
            )
        return invoice

    except (AttributeError, KeyError, ValueError, TypeError) as e:
        frappe.throw(_(f"Data processing error in tax data: {str(e)}"))
