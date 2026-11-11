"""Frozen test-only advance wrappers from 03b4982195b8bb614125f8b87c2cd460958902bb.

Compiled only by offline parity tests with explicit synthetic dependencies.
Not imported by runtime hooks, controllers, or migrations.
"""

def item_data_advance_invoice(invoice, sales_invoice_doc):
    """
    Generate <cac:InvoiceLine> XML nodes for standard and advance invoice items.
    Uses line net values as the source of truth for the regular invoice lines.
    """
    try:
        # Add regular item lines
        for single_item in sales_invoice_doc.items:
            tax_json = get_tax_wise_detail(sales_invoice_doc, single_item)
            _item_tax_amount, item_tax_percentage = get_item_tax_detail(sales_invoice_doc, single_item)

            line_net_amount = _line_net_amount(single_item, sales_invoice_doc)
            line_net_rate = _line_net_rate(single_item, sales_invoice_doc)
            line_tax_amount = _line_tax_amount_from_net(
                line_net_amount, item_tax_percentage
            )

            line = ET.SubElement(invoice, "cac:InvoiceLine")
            ET.SubElement(line, "cbc:ID").text = str(single_item.idx)
            ET.SubElement(
                line, "cbc:InvoicedQuantity", unitCode=single_item.uom
            ).text = str(abs(single_item.qty))
            ET.SubElement(
                line, "cbc:LineExtensionAmount", currencyID=sales_invoice_doc.currency
            ).text = f"{line_net_amount:.2f}"

            tax_total = ET.SubElement(line, "cac:TaxTotal")
            ET.SubElement(
                tax_total, "cbc:TaxAmount", currencyID=sales_invoice_doc.currency
            ).text = f"{line_tax_amount:.2f}"
            ET.SubElement(
                tax_total, "cbc:RoundingAmount", currencyID=sales_invoice_doc.currency
            ).text = f"{(line_net_amount + line_tax_amount):.2f}"

            item = ET.SubElement(line, "cac:Item")
            ET.SubElement(item, "cbc:Name").text = _line_name(single_item)
            classified_tax = ET.SubElement(item, "cac:ClassifiedTaxCategory")
            tax_id = ET.SubElement(classified_tax, "cbc:ID")
            if sales_invoice_doc.custom_zatca_tax_category == "Standard":
                tax_id.text = "S"
            elif sales_invoice_doc.custom_zatca_tax_category == ZERO_RATED:
                tax_id.text = "Z"
            elif sales_invoice_doc.custom_zatca_tax_category == "Exempted":
                tax_id.text = "E"
            elif sales_invoice_doc.custom_zatca_tax_category == OUTSIDE_SCOPE:
                tax_id.text = "O"
            ET.SubElement(classified_tax, "cbc:Percent").text = f"{float(item_tax_percentage):.2f}"
            tax_scheme = ET.SubElement(classified_tax, "cac:TaxScheme")
            ET.SubElement(tax_scheme, "cbc:ID").text = "VAT"

            price = ET.SubElement(line, "cac:Price")
            ET.SubElement(
                price, "cbc:PriceAmount", currencyID=sales_invoice_doc.currency
            ).text = _format_price_amount(line_net_rate)

        _append_direct_advance_reference_lines(invoice, sales_invoice_doc)

        if (
            not _direct_advance_rows(sales_invoice_doc)
            and
            "claudion4saudi" in frappe.get_installed_apps()
            and hasattr(sales_invoice_doc, "custom_advances_copy")
            and sales_invoice_doc.custom_advances_copy
            and sales_invoice_doc.custom_advances_copy[0].reference_name
        ):
            reference_name = sales_invoice_doc.custom_advances_copy[0].reference_name
            advance_invoice = frappe.get_doc("Advance Sales Invoice", reference_name)

            for i, single_item in enumerate(advance_invoice.custom_item):
                line = ET.SubElement(invoice, "cac:InvoiceLine")
                ET.SubElement(line, "cbc:ID").text = str(
                    len(sales_invoice_doc.items) + i + 1
                )
                ET.SubElement(
                    line, "cbc:InvoicedQuantity", unitCode=single_item.uom
                ).text = "0.000000"
                ET.SubElement(
                    line,
                    "cbc:LineExtensionAmount",
                    currencyID=sales_invoice_doc.currency,
                ).text = "0.00"

                docref = ET.SubElement(line, "cac:DocumentReference")
                ET.SubElement(docref, "cbc:ID").text = reference_name
                ET.SubElement(docref, "cbc:UUID").text = (
                    sales_invoice_doc.custom_advances_copy[0].uuid
                )
                ET.SubElement(docref, "cbc:IssueDate").text = str(
                    sales_invoice_doc.custom_advances_copy[0].difference_posting_date
                )
                ET.SubElement(docref, "cbc:IssueTime").text = get_time_string(
                    sales_invoice_doc.custom_advances_copy[0].posting_time
                )
                ET.SubElement(docref, "cbc:DocumentTypeCode").text = "386"

                tax_total = ET.SubElement(line, "cac:TaxTotal")
                ET.SubElement(
                    tax_total, "cbc:TaxAmount", currencyID=sales_invoice_doc.currency
                ).text = "0"
                ET.SubElement(
                    tax_total,
                    "cbc:RoundingAmount",
                    currencyID=sales_invoice_doc.currency,
                ).text = "0"

                subtotal = ET.SubElement(tax_total, "cac:TaxSubtotal")
                ET.SubElement(
                    subtotal, "cbc:TaxableAmount", currencyID=sales_invoice_doc.currency
                ).text = str(abs(single_item.amount))
                ET.SubElement(
                    subtotal, "cbc:TaxAmount", currencyID=sales_invoice_doc.currency
                ).text = str(
                    abs(round(single_item.amount * item_tax_percentage / 100, 2))
                )

                tax_cat = ET.SubElement(subtotal, "cac:TaxCategory")
                ET.SubElement(tax_cat, "cbc:ID").text = get_tax_code(
                    sales_invoice_doc.custom_zatca_tax_category
                )
                ET.SubElement(tax_cat, "cbc:Percent").text = (
                    f"{float(item_tax_percentage):.2f}"
                )
                ET.SubElement(
                    ET.SubElement(tax_cat, "cac:TaxScheme"), "cbc:ID"
                ).text = "VAT"

                item_tag = ET.SubElement(line, "cac:Item")
                ET.SubElement(item_tag, "cbc:Name").text = (
                    f"{single_item.item_code}:{single_item.item_name}"
                )

                tax_cat_item = ET.SubElement(item_tag, "cac:ClassifiedTaxCategory")
                ET.SubElement(tax_cat_item, "cbc:ID").text = get_tax_code(
                    sales_invoice_doc.custom_zatca_tax_category
                )
                ET.SubElement(tax_cat_item, "cbc:Percent").text = (
                    f"{float(item_tax_percentage):.2f}"
                )
                ET.SubElement(
                    ET.SubElement(tax_cat_item, "cac:TaxScheme"), "cbc:ID"
                ).text = "VAT"

                ET.SubElement(
                    ET.SubElement(line, "cac:Price"),
                    "cbc:PriceAmount",
                    currencyID=sales_invoice_doc.currency,
                ).text = "0.00"

        # Final Debug
        total_lines = len(_invoice_line_nodes(invoice))

        return invoice

    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(_(f"❌ Error in item_data_advance_invoice: {str(e)}"))
        return None


def item_data_with_template_advance_invoice(invoice, sales_invoice_doc):
    """Create item XML with Item Tax Template for advance invoices using line net values."""
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
            ET.SubElement(
                cac_invoiceline, "cbc:LineExtensionAmount", currencyID=sales_invoice_doc.currency
            ).text = f"{line_net_amount:.2f}"

            cac_taxtotal_2 = ET.SubElement(cac_invoiceline, CAC_TAX_TOTAL)
            ET.SubElement(
                cac_taxtotal_2, CBC_TAX_AMOUNT, currencyID=sales_invoice_doc.currency
            ).text = f"{line_tax_amount:.2f}"
            ET.SubElement(
                cac_taxtotal_2, "cbc:RoundingAmount", currencyID=sales_invoice_doc.currency
            ).text = f"{(line_net_amount + line_tax_amount):.2f}"

            cac_item = ET.SubElement(cac_invoiceline, "cac:Item")
            ET.SubElement(cac_item, "cbc:Name").text = _line_name(single_item)

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
            ET.SubElement(cac_classifiedtaxcategory, "cbc:Percent").text = f"{float(item_tax_percentage):.2f}"
            tax_scheme = ET.SubElement(cac_classifiedtaxcategory, "cac:TaxScheme")
            ET.SubElement(tax_scheme, "cbc:ID").text = "VAT"

            price = ET.SubElement(cac_invoiceline, "cac:Price")
            ET.SubElement(
                price, "cbc:PriceAmount", currencyID=sales_invoice_doc.currency
            ).text = _format_price_amount(line_net_rate)

        _append_direct_advance_reference_lines(invoice, sales_invoice_doc)

        if (
            not _direct_advance_rows(sales_invoice_doc)
            and
            "claudion4saudi" in frappe.get_installed_apps()
            and hasattr(sales_invoice_doc, "custom_advances_copy")
            and sales_invoice_doc.custom_advances_copy
        ):
            if sales_invoice_doc.custom_advances_copy[0].reference_name:
                advance_line_id = len(sales_invoice_doc.items) + 1
                reference_name = sales_invoice_doc.custom_advances_copy[
                    0
                ].reference_name
                advance_invoice = frappe.get_doc(
                    "Advance Sales Invoice", reference_name
                )
                for i, single_item in enumerate(advance_invoice.custom_item):
                    adv_line = ET.SubElement(invoice, "cac:InvoiceLine")
                    ET.SubElement(adv_line, "cbc:ID").text = str(advance_line_id + i)
                    ET.SubElement(
                        adv_line, "cbc:InvoicedQuantity", unitCode=str(single_item.uom)
                    ).text = "0.000000"
                    ET.SubElement(
                        adv_line,
                        "cbc:LineExtensionAmount",
                        currencyID=sales_invoice_doc.currency,
                    ).text = "0.00"

                    docref = ET.SubElement(adv_line, "cac:DocumentReference")
                    ET.SubElement(docref, "cbc:ID").text = str(
                        sales_invoice_doc.custom_advances_copy[0].reference_name
                    )

                    ET.SubElement(docref, "cbc:UUID").text = str(
                        sales_invoice_doc.custom_advances_copy[0].uuid
                    )
                    ET.SubElement(docref, "cbc:IssueDate").text = str(
                        sales_invoice_doc.custom_advances_copy[
                            0
                        ].difference_posting_date
                    )
                    if (
                        sales_invoice_doc.custom_advances_copy
                        and sales_invoice_doc.custom_advances_copy[0].posting_time
                    ):
                        # Extract the first advance posting time
                        posting_time = sales_invoice_doc.custom_advances_copy[
                            0
                        ].posting_time

                        time = get_time(posting_time)
                        issue_time = time.strftime("%H:%M:%S")
                        # Format time as HH:MM:SS

                        # Create the XML element for IssueTime
                        ET.SubElement(docref, "cbc:IssueTime").text = str(issue_time)
                    else:
                        # Handle the case where posting_time is not available
                        ET.SubElement(docref, "cbc:IssueTime").text = "00:00:00"
                    ET.SubElement(docref, "cbc:DocumentTypeCode").text = "386"

                    tax_total_adv = ET.SubElement(adv_line, "cac:TaxTotal")
                    ET.SubElement(
                        tax_total_adv,
                        "cbc:TaxAmount",
                        currencyID=sales_invoice_doc.currency,
                    ).text = "0"
                    ET.SubElement(
                        tax_total_adv,
                        "cbc:RoundingAmount",
                        currencyID=sales_invoice_doc.currency,
                    ).text = "0"

                    subtotal = ET.SubElement(tax_total_adv, "cac:TaxSubtotal")
                    ET.SubElement(
                        subtotal,
                        "cbc:TaxableAmount",
                        currencyID=sales_invoice_doc.currency,
                    ).text = str(abs(single_item.amount))
                    ET.SubElement(
                        subtotal, "cbc:TaxAmount", currencyID=sales_invoice_doc.currency
                    ).text = str(
                        abs(round(single_item.amount * item_tax_percentage / 100, 2))
                    )

                    tax_cat = ET.SubElement(subtotal, "cac:TaxCategory")
                    zatca_tax_category = item_tax_template.custom_zatca_tax_category
                    tax_category_code = get_tax_code(zatca_tax_category)
                    ET.SubElement(tax_cat, "cbc:ID").text = tax_category_code
                    ET.SubElement(tax_cat, "cbc:Percent").text = (
                        f"{float(item_tax_percentage):.2f}"
                    )
                    ET.SubElement(
                        ET.SubElement(tax_cat, "cac:TaxScheme"), "cbc:ID"
                    ).text = "VAT"

                    item_tag_adv = ET.SubElement(adv_line, "cac:Item")
                    ET.SubElement(item_tag_adv, "cbc:Name").text = (
                        f"{single_item.item_code}:{single_item.item_name}"
                    )
                    tax_cat_adv = ET.SubElement(
                        item_tag_adv, "cac:ClassifiedTaxCategory"
                    )
                    ET.SubElement(tax_cat_adv, "cbc:ID").text = tax_category_code
                    ET.SubElement(tax_cat_adv, "cbc:Percent").text = (
                        f"{float(item_tax_percentage):.2f}"
                    )
                    ET.SubElement(
                        ET.SubElement(tax_cat_adv, "cac:TaxScheme"), "cbc:ID"
                    ).text = "VAT"

                    ET.SubElement(
                        ET.SubElement(adv_line, "cac:Price"),
                        "cbc:PriceAmount",
                        currencyID=sales_invoice_doc.currency,
                    ).text = "0.00"

        return invoice
    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(
            _(f"Error occurred in item template advance data processing: {str(e)}")
        )
        return None
