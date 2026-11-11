"""Frozen test-only builders from 499d56db5ed360a91edb50ed8e02364dcb146e7e.

Loaded only by offline parity tests with explicit synthetic dependencies.
Not imported by runtime hooks, controllers, or migration code.
"""

def item_data(invoice, sales_invoice_doc):
    """
    Create item XML without Item Tax Template using line net values as source of truth.
    """
    try:
        for single_item in sales_invoice_doc.items:
            tax_json = get_tax_wise_detail(sales_invoice_doc, single_item)
            _item_tax_amount, item_tax_percentage = get_item_tax_detail(sales_invoice_doc, single_item)

            line_net_amount = _line_net_amount(single_item, sales_invoice_doc)
            line_net_rate = _line_net_rate(single_item, sales_invoice_doc)
            line_tax_amount = _line_tax_amount_from_net(
                line_net_amount, item_tax_percentage
            )

            cac_invoiceline = ET.SubElement(invoice, "cac:InvoiceLine")
            ET.SubElement(cac_invoiceline, "cbc:ID").text = str(single_item.idx)
            cbc_invoicedquantity = ET.SubElement(
                cac_invoiceline, "cbc:InvoicedQuantity"
            )
            cbc_invoicedquantity.set("unitCode", str(single_item.uom))
            cbc_invoicedquantity.text = str(abs(single_item.qty))

            cbc_lineextensionamount_1 = ET.SubElement(
                cac_invoiceline, "cbc:LineExtensionAmount"
            )
            cbc_lineextensionamount_1.set("currencyID", sales_invoice_doc.currency)
            cbc_lineextensionamount_1.text = f"{line_net_amount:.2f}"

            cac_taxtotal_2 = ET.SubElement(cac_invoiceline, CAC_TAX_TOTAL)
            cbc_taxamount_3 = ET.SubElement(cac_taxtotal_2, CBC_TAX_AMOUNT)
            cbc_taxamount_3.set("currencyID", sales_invoice_doc.currency)
            cbc_taxamount_3.text = f"{line_tax_amount:.2f}"

            cbc_roundingamount = ET.SubElement(cac_taxtotal_2, "cbc:RoundingAmount")
            cbc_roundingamount.set("currencyID", sales_invoice_doc.currency)
            cbc_roundingamount.text = f"{(line_net_amount + line_tax_amount):.2f}"

            cac_item = ET.SubElement(cac_invoiceline, "cac:Item")
            cbc_name = ET.SubElement(cac_item, "cbc:Name")
            cbc_name.text = _line_name(single_item)

            cac_classifiedtaxcategory = ET.SubElement(
                cac_item, "cac:ClassifiedTaxCategory"
            )
            cbc_id_11 = ET.SubElement(cac_classifiedtaxcategory, "cbc:ID")
            if sales_invoice_doc.custom_zatca_tax_category == "Standard":
                cbc_id_11.text = "S"
            elif sales_invoice_doc.custom_zatca_tax_category == ZERO_RATED:
                cbc_id_11.text = "Z"
            elif sales_invoice_doc.custom_zatca_tax_category == "Exempted":
                cbc_id_11.text = "E"
            elif sales_invoice_doc.custom_zatca_tax_category == OUTSIDE_SCOPE:
                cbc_id_11.text = "O"
            cbc_percent_2 = ET.SubElement(cac_classifiedtaxcategory, "cbc:Percent")
            cbc_percent_2.text = f"{float(item_tax_percentage):.2f}"
            cac_taxscheme_4 = ET.SubElement(cac_classifiedtaxcategory, "cac:TaxScheme")
            ET.SubElement(cac_taxscheme_4, "cbc:ID").text = "VAT"

            cac_price = ET.SubElement(cac_invoiceline, "cac:Price")
            cbc_priceamount = ET.SubElement(cac_price, "cbc:PriceAmount")
            cbc_priceamount.set("currencyID", sales_invoice_doc.currency)
            cbc_priceamount.text = _format_price_amount(line_net_rate)

        _append_direct_advance_reference_lines(invoice, sales_invoice_doc)

        return invoice
    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(_(f"Error occurred in item data processing: {str(e)}"))
        return None


def item_data_with_template(invoice, sales_invoice_doc):
    """Create item XML with Item Tax Template using line net values as source of truth."""
    try:
        for single_item in sales_invoice_doc.items:
            item_tax_template = frappe.get_doc(
                ITEM_TAX_TEMPLATE, single_item.item_tax_template
            )
            item_tax_percentage = (
                item_tax_template.taxes[0].tax_rate if item_tax_template.taxes else 15
            )

            line_net_amount = _line_net_amount(single_item, sales_invoice_doc)
            line_net_rate = _line_net_rate(single_item, sales_invoice_doc)
            line_tax_amount = _line_tax_amount_from_net(
                line_net_amount, item_tax_percentage
            )

            cac_invoiceline = ET.SubElement(invoice, "cac:InvoiceLine")
            ET.SubElement(cac_invoiceline, "cbc:ID").text = str(single_item.idx)
            cbc_invoicedquantity = ET.SubElement(
                cac_invoiceline, "cbc:InvoicedQuantity"
            )
            cbc_invoicedquantity.set("unitCode", str(single_item.uom))
            cbc_invoicedquantity.text = str(abs(single_item.qty))

            cbc_lineextensionamount_1 = ET.SubElement(
                cac_invoiceline, "cbc:LineExtensionAmount"
            )
            cbc_lineextensionamount_1.set("currencyID", sales_invoice_doc.currency)
            cbc_lineextensionamount_1.text = f"{line_net_amount:.2f}"

            cac_taxtotal_2 = ET.SubElement(cac_invoiceline, CAC_TAX_TOTAL)
            cbc_taxamount_3 = ET.SubElement(cac_taxtotal_2, CBC_TAX_AMOUNT)
            cbc_taxamount_3.set("currencyID", sales_invoice_doc.currency)
            cbc_taxamount_3.text = f"{line_tax_amount:.2f}"

            cbc_roundingamount = ET.SubElement(cac_taxtotal_2, "cbc:RoundingAmount")
            cbc_roundingamount.set("currencyID", sales_invoice_doc.currency)
            cbc_roundingamount.text = f"{(line_net_amount + line_tax_amount):.2f}"

            cac_item = ET.SubElement(cac_invoiceline, "cac:Item")
            cbc_name = ET.SubElement(cac_item, "cbc:Name")
            cbc_name.text = _line_name(single_item)

            cac_classifiedtaxcategory = ET.SubElement(
                cac_item, "cac:ClassifiedTaxCategory"
            )
            cbc_id_11 = ET.SubElement(cac_classifiedtaxcategory, "cbc:ID")
            zatca_tax_category = item_tax_template.custom_zatca_tax_category
            if zatca_tax_category == "Standard":
                cbc_id_11.text = "S"
            elif zatca_tax_category == ZERO_RATED:
                cbc_id_11.text = "Z"
            elif zatca_tax_category == "Exempted":
                cbc_id_11.text = "E"
            elif zatca_tax_category == OUTSIDE_SCOPE:
                cbc_id_11.text = "O"

            cbc_percent_2 = ET.SubElement(cac_classifiedtaxcategory, "cbc:Percent")
            cbc_percent_2.text = f"{float(item_tax_percentage):.2f}"

            cac_taxscheme_4 = ET.SubElement(cac_classifiedtaxcategory, "cac:TaxScheme")
            ET.SubElement(cac_taxscheme_4, "cbc:ID").text = "VAT"

            cac_price = ET.SubElement(cac_invoiceline, "cac:Price")
            cbc_priceamount = ET.SubElement(cac_price, "cbc:PriceAmount")
            cbc_priceamount.set("currencyID", sales_invoice_doc.currency)
            cbc_priceamount.text = _format_price_amount(line_net_rate)

        _append_direct_advance_reference_lines(invoice, sales_invoice_doc)

        return invoice
    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(_(f"Error occurred in item template data processing: {str(e)}"))
        return None
