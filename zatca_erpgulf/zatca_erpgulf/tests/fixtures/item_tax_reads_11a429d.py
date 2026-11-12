"""Frozen parent item readers; test data, not an installed runtime module."""

def _append_sales_invoice_item_lines(invoice, sales_invoice_doc, *, has_template):
    """Append regular Sales item lines, then existing direct-advance references.

    Keep template acquisition, ordinary tax-detail reads, Decimal/price helpers,
    field-read order and XML child/attribute order from the legacy builders.
    The plain category path rereads its source; the template path reads once.
    Advance wrappers retain their own rate acquisition and reference tails.
    """
    for single_item in sales_invoice_doc.items:
        if has_template:
            item_tax_template = frappe.get_doc(
                ITEM_TAX_TEMPLATE, single_item.item_tax_template
            )
            item_tax_percentage = (
                item_tax_template.taxes[0].tax_rate if item_tax_template.taxes else 15
            )
        else:
            tax_json = get_tax_wise_detail(sales_invoice_doc, single_item)
            _item_tax_amount, item_tax_percentage = get_item_tax_detail(
                sales_invoice_doc, single_item
            )
        line_net_amount = _line_net_amount(single_item, sales_invoice_doc)
        line_net_rate = _line_net_rate(single_item, sales_invoice_doc)
        line_tax_amount = _line_tax_amount_from_net(line_net_amount, item_tax_percentage)
        _append_sales_invoice_line(
            invoice, sales_invoice_doc, single_item, line_net_amount, line_net_rate,
            line_tax_amount, item_tax_percentage,
            has_template=has_template, item_tax_template=item_tax_template if has_template else None,
            layout="ordinary",
        )
    _append_direct_advance_reference_lines(invoice, sales_invoice_doc)
    return invoice


def item_data(invoice, sales_invoice_doc):
    """
    Create item XML without Item Tax Template using line net values as source of truth.
    """
    try:
        return _append_sales_invoice_item_lines(
            invoice, sales_invoice_doc, has_template=False
        )
    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(_(f"Error occurred in item data processing: {str(e)}"))
        return None


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

            _append_sales_invoice_line(
                invoice, sales_invoice_doc, single_item, line_net_amount, line_net_rate,
                line_tax_amount, item_tax_percentage,
                has_template=False, item_tax_template=None,
                layout="advance_plain",
            )

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

                subtotal = _append_legacy_advance_tax_subtotal(
                    line, sales_invoice_doc, single_item
                )
                ET.SubElement(
                    subtotal, "cbc:TaxAmount", currencyID=sales_invoice_doc.currency
                ).text = str(
                    _legacy_advance_tax_amount(single_item.amount, item_tax_percentage)
                )
                _append_legacy_advance_line_details(
                    line, subtotal, sales_invoice_doc, single_item, item_tax_percentage
                )

        # Final Debug
        total_lines = len(_invoice_line_nodes(invoice))

        return invoice

    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(_(f"❌ Error in item_data_advance_invoice: {str(e)}"))
        return None
