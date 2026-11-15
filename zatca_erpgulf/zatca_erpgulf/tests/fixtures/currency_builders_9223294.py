# Frozen increment220 currency-sensitive builders; test data only.

def _nominal_breakdown_without_template(sales_invoice_doc):
    """Group nominal values by selected rate without inferring tax categories."""
    tax_category = sales_invoice_doc.get("custom_zatca_tax_category") or "Standard"
    exemption_reason_code = sales_invoice_doc.get("custom_exemption_reason_code")
    groups = {}
    sar_bases = {}

    for item in sales_invoice_doc.items:
        item_tax_rate = _nominal_tax_rate_without_template(sales_invoice_doc, item)
        # Keep line net/base reads and their existing currency quantization.
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
        sar_bases[rate_key] = sar_bases.get(rate_key, Decimal("0.00")) + line_base_net

    if not groups:
        # Keep the prior empty-table row rather than dropping required subtotals.
        groups[Decimal("0.00")] = _new_tax_rate_bucket(
            tax_category, Decimal("0.00"), exemption_reason_code, include_sar=True
        )
    for rate_key, row in groups.items():
        row["taxable_amount"] = _nominal_q2(row["taxable_amount"])
        row["tax_amount"] = vat_from_group(row["taxable_amount"], row["tax_rate"])
        row["sar_tax_amount"] = vat_from_group(sar_bases.get(rate_key, Decimal("0.00")), row["tax_rate"])
        row["tax_rate"] = _nominal_q2(row["tax_rate"])
    return list(groups.values())


def _nominal_breakdown_with_template(sales_invoice_doc):
    tax_category_totals = {}
    sar_bases = {}

    vat_context = DeclaredVatContext(sales_invoice_doc, frappe, _)
    for item in sales_invoice_doc.items:
        item_tax_template = vat_context.get_template(item.item_tax_template)
        zatca_tax_category = item_tax_template.custom_zatca_tax_category
        selected_vat_row = vat_context.row(item_tax_template)
        if selected_vat_row is not None:
            tax_rate = Decimal(str(selected_vat_row.tax_rate))
        else:
            tax_rate = (
                Decimal(str(item_tax_template.taxes[0].tax_rate))
                if item_tax_template.taxes else Decimal("15.00")
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
        sar_bases[key] = sar_bases.get(key, Decimal("0.00")) + line_base_net

    result = []
    for key, totals in tax_category_totals.items():
        totals["taxable_amount"] = _nominal_q2(totals["taxable_amount"])
        totals["tax_amount"] = vat_from_group(totals["taxable_amount"], totals["tax_rate"])
        totals["sar_tax_amount"] = vat_from_group(sar_bases[key], totals["tax_rate"])
        result.append(totals)

    return result


def _append_sales_invoice_item_lines(invoice, sales_invoice_doc, *, has_template):
    """Append regular Sales item lines, then existing direct-advance references.

    Resolve plain tax details once per item; unused legacy JSON is not built.
    Keep template acquisition, Decimal/price helpers, the remaining field reads
    and XML child/attribute order from the legacy builders.
    The plain category path rereads its source; the template path reads once.
    Advance wrappers retain their own rate acquisition and reference tails.
    """
    vat_context = DeclaredVatContext(sales_invoice_doc, frappe, _)
    for single_item in sales_invoice_doc.items:
        if has_template:
            item_tax_template = vat_context.get_template(single_item.item_tax_template)
            selected_vat_row = vat_context.row(item_tax_template)
            item_tax_percentage = (
                selected_vat_row.tax_rate if selected_vat_row is not None else
                item_tax_template.taxes[0].tax_rate if item_tax_template.taxes else 15
            )
        else:
            item_tax_percentage = get_item_tax_rate(
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


def item_data_advance_invoice(invoice, sales_invoice_doc):
    """
    Generate <cac:InvoiceLine> XML nodes for standard and advance invoice items.
    Uses line net values as the source of truth for the regular invoice lines.
    """
    try:
        # Add regular item lines
        for single_item in sales_invoice_doc.items:
            item_tax_percentage = get_item_tax_rate(sales_invoice_doc, single_item)

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


def item_data_with_template_advance_invoice(invoice, sales_invoice_doc):
    """Create item XML with Item Tax Template for advance invoices using line net values."""
    try:
        vat_context = DeclaredVatContext(sales_invoice_doc, frappe, _)
        for single_item in sales_invoice_doc.items:
            item_tax_template = vat_context.get_template(single_item.item_tax_template)
            selected_vat_row = vat_context.row(item_tax_template)
            item_tax_percentage = (
                selected_vat_row.tax_rate if selected_vat_row is not None else
                item_tax_template.taxes[0].tax_rate if item_tax_template.taxes else 15
            )

            line_net_amount = _line_net_amount(single_item, sales_invoice_doc)
            line_net_rate = _line_net_rate(single_item, sales_invoice_doc)
            line_tax_amount = _line_tax_amount_from_net(
                line_net_amount, item_tax_percentage
            )

            _append_sales_invoice_line(
                invoice, sales_invoice_doc, single_item, line_net_amount, line_net_rate,
                line_tax_amount, item_tax_percentage,
                has_template=True, item_tax_template=item_tax_template,
                layout="advance_template",
            )

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

                    subtotal = _append_legacy_advance_tax_subtotal(
                        adv_line, sales_invoice_doc, single_item
                    )
                    ET.SubElement(
                        subtotal, "cbc:TaxAmount", currencyID=sales_invoice_doc.currency
                    ).text = str(
                        _legacy_advance_tax_amount(single_item.amount, item_tax_percentage)
                    )
                    _append_legacy_advance_line_details(
                        adv_line, subtotal, sales_invoice_doc, single_item, item_tax_percentage,
                        has_template=True, item_tax_template=item_tax_template,
                    )

        return invoice
    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(
            _(f"Error occurred in item template advance data processing: {str(e)}")
        )
        return None
