"""Exact baseline financial function closure; test data, no imports or site setup.

Source: zatca_erpgulf/zatca_erpgulf/create_xml_final_part.py
Revision: 2e97708e115e31c675182647d10829d6175e7449
"""

ITEM_TAX_TEMPLATE = "Item Tax Template"

CAC_TAX_TOTAL = "cac:TaxTotal"

CBC_TAX_AMOUNT = "cbc:TaxAmount"

CAC_TAX_SUBTOTAL = "cac:TaxSubtotal"

CBC_TAXABLE_AMOUNT = "cbc:TaxableAmount"

ZERO_RATED = "Zero Rated"

OUTSIDE_SCOPE = "Services outside scope of tax / Not subject to VAT"

def _xml_local_name(tag):
    return str(tag or "").split("}", 1)[-1].split(":", 1)[-1]

def _invoice_line_nodes(invoice):
    """Find InvoiceLine nodes in both literal-prefix and namespace XML trees."""
    return [node for node in list(invoice) if _xml_local_name(node.tag) == "InvoiceLine"]

def _child_local(node, name):
    return next((child for child in list(node) if _xml_local_name(child.tag) == name), None)

def _nested_child_text(node, *names):
    current = node
    for name in names:
        current = _child_local(current, name)
        if current is None:
            return None
    return current.text

def _direct_advance_rows(sales_invoice_doc):
    if not supports_advance_deduction_schema(sales_invoice_doc):
        return []

    return [
        row
        for row in sales_invoice_doc.get(
            "custom_zatca_advance_deduction_details", []
        ) or []
        if row.get("advance_invoice")
        and _nominal_q2(row.get("allocated_total_amount")) != Decimal("0.00")
    ]

def _append_direct_advance_reference_lines(invoice, sales_invoice_doc):
    """Add one ZATCA 386 reference line for each directly allocated advance invoice."""
    rows = _direct_advance_rows(sales_invoice_doc)
    existing_ids = {
        str(_child_local(node, "ID").text)
        for node in _invoice_line_nodes(invoice)
        if _child_local(node, "ID") is not None
    }
    numeric_ids = [int(value) for value in existing_ids if value.isdigit()]
    next_line_id = max(numeric_ids, default=0) + 1
    existing_references = {
        str(_nested_child_text(node, "DocumentReference", "ID"))
        for node in _invoice_line_nodes(invoice)
        if _nested_child_text(node, "DocumentReference", "ID") is not None
    }

    for row in rows:
        if str(row.advance_invoice) in existing_references:
            continue
        while str(next_line_id) in existing_ids:
            next_line_id += 1
        line_id = str(next_line_id)
        existing_ids.add(line_id)
        next_line_id += 1
        advance = frappe.get_doc("Sales Invoice", row.advance_invoice)
        # ZATCA requires document/prepayment amounts to be positive.  The
        # return child row is intentionally stored as a negative reversal;
        # only the XML representation uses its absolute amount.
        taxable = _nominal_abs_q2(row.allocated_taxable_amount)
        tax = _nominal_abs_q2(row.allocated_tax_amount)
        tax_rate = (
            _nominal_q2(tax * Decimal("100") / taxable)
            if taxable > Decimal("0.00")
            else Decimal("0.00")
        )
        issue_date = advance.get("posting_date") or row.get("advance_invoice_date")
        issue_time = advance.get("posting_time")
        if not issue_date or not issue_time:
            frappe.throw(
                _("Advance payment Sales Invoice {0} is missing its authoritative issue date/time.").format(
                    advance.name
                )
            )
        if not is_advance_payment_invoice(advance):
            frappe.throw(
                _("Sales Invoice {0} is not marked as an advance payment invoice.").format(
                    advance.name
                )
            )

        category = advance.get("custom_zatca_tax_category") or "Standard"

        line = ET.SubElement(invoice, "cac:InvoiceLine")
        ET.SubElement(line, "cbc:ID").text = line_id
        ET.SubElement(line, "cbc:InvoicedQuantity", unitCode="PCE").text = "0.000000"
        ET.SubElement(
            line,
            "cbc:LineExtensionAmount",
            currencyID=sales_invoice_doc.currency,
        ).text = "0.00"

        docref = ET.SubElement(line, "cac:DocumentReference")
        ET.SubElement(docref, "cbc:ID").text = str(advance.name)
        existing_references.add(str(advance.name))
        if advance.get("custom_uuid"):
            ET.SubElement(docref, "cbc:UUID").text = str(advance.custom_uuid)
        ET.SubElement(docref, "cbc:IssueDate").text = str(issue_date)
        ET.SubElement(docref, "cbc:IssueTime").text = get_time_string(issue_time)
        ET.SubElement(docref, "cbc:DocumentTypeCode").text = "386"

        tax_total = ET.SubElement(line, "cac:TaxTotal")
        ET.SubElement(
            tax_total,
            "cbc:TaxAmount",
            currencyID=sales_invoice_doc.currency,
        ).text = "0.00"
        ET.SubElement(
            tax_total,
            "cbc:RoundingAmount",
            currencyID=sales_invoice_doc.currency,
        ).text = "0.00"

        subtotal = ET.SubElement(tax_total, "cac:TaxSubtotal")
        ET.SubElement(
            subtotal,
            "cbc:TaxableAmount",
            currencyID=sales_invoice_doc.currency,
        ).text = str(taxable)
        ET.SubElement(
            subtotal,
            "cbc:TaxAmount",
            currencyID=sales_invoice_doc.currency,
        ).text = str(tax)

        tax_category = ET.SubElement(subtotal, "cac:TaxCategory")
        ET.SubElement(tax_category, "cbc:ID").text = get_tax_code(category)
        ET.SubElement(tax_category, "cbc:Percent").text = f"{tax_rate:.2f}"
        ET.SubElement(
            ET.SubElement(tax_category, "cac:TaxScheme"),
            "cbc:ID",
        ).text = "VAT"

        item = ET.SubElement(line, "cac:Item")
        ET.SubElement(item, "cbc:Name").text = "Advance Payment"
        classified_tax = ET.SubElement(item, "cac:ClassifiedTaxCategory")
        ET.SubElement(classified_tax, "cbc:ID").text = get_tax_code(category)
        ET.SubElement(classified_tax, "cbc:Percent").text = f"{tax_rate:.2f}"
        ET.SubElement(
            ET.SubElement(classified_tax, "cac:TaxScheme"),
            "cbc:ID",
        ).text = "VAT"

        price = ET.SubElement(line, "cac:Price")
        ET.SubElement(
            price,
            "cbc:PriceAmount",
            currencyID=sales_invoice_doc.currency,
        ).text = "0.00"

    return invoice

def _nominal_q2(value):
    """Round to 2 decimals using HALF_UP."""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _nominal_abs_q2(value):
    return _nominal_q2(abs(value or 0))

def _nominal_tax_category_code(category):
    if category == "Standard":
        return "S"
    if category == ZERO_RATED:
        return "Z"
    if category == "Exempted":
        return "E"
    if category == OUTSIDE_SCOPE:
        return "O"
    return "S"

def _nominal_add_tax_category(parent, zatca_tax_category, tax_rate, exemption_reason_code=None, exemption_reason_text=None):
    """Append cac:TaxCategory/cac:TaxScheme under a subtotal."""
    cac_taxcategory = ET.SubElement(parent, "cac:TaxCategory")

    cbc_id = ET.SubElement(cac_taxcategory, "cbc:ID")
    cbc_id.text = _nominal_tax_category_code(zatca_tax_category)

    cbc_percent = ET.SubElement(cac_taxcategory, "cbc:Percent")
    cbc_percent.text = f"{Decimal(str(tax_rate or 0)):.2f}"

    if zatca_tax_category != "Standard" and exemption_reason_code:
        reason_map = get_exemption_reason_map()

        cbc_reason_code = ET.SubElement(cac_taxcategory, "cbc:TaxExemptionReasonCode")
        cbc_reason_code.text = exemption_reason_code

        cbc_reason = ET.SubElement(cac_taxcategory, "cbc:TaxExemptionReason")
        reason_text = resolve_exemption_reason_text(
            exemption_reason_code, exemption_reason_text
        )
        if reason_text:
            cbc_reason.text = reason_text

    cac_taxscheme = ET.SubElement(cac_taxcategory, "cac:TaxScheme")
    ET.SubElement(cac_taxscheme, "cbc:ID").text = "VAT"

def _nominal_item_net_amount(single_item, sales_invoice_doc):
    """Use line net amount as the source of truth for nominal XML too."""
    if sales_invoice_doc.currency == getattr(sales_invoice_doc, "company_currency", sales_invoice_doc.currency):
        value = single_item.get("base_net_amount")
        if value is None:
            value = single_item.get("net_amount")
        if value is None:
            value = single_item.get("base_amount")
        if value is None:
            value = single_item.get("amount")
    else:
        value = single_item.get("net_amount")
        if value is None:
            value = single_item.get("amount")
    return _nominal_abs_q2(value)

def _nominal_item_base_net_amount(single_item):
    value = single_item.get("base_net_amount")
    if value is None:
        value = single_item.get("base_amount")
    if value is None:
        value = single_item.get("net_amount")
    if value is None:
        value = single_item.get("amount")
    return _nominal_abs_q2(value)

def _nominal_tax_rate_without_template(sales_invoice_doc, single_item):
    try:
        if sales_invoice_doc.get("taxes"):
            _item_tax_amount, tax_percentage = get_item_tax_detail(sales_invoice_doc, single_item)
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

def _append_nominal_tax_totals(invoice, sales_invoice_doc, tax_breakdown):
    """
    Build nominal invoice tax totals.

    Nominal invoice behavior kept intentionally:
    - one summary-only TaxTotal in SAR
    - one detailed TaxTotal in document currency with actual taxable subtotals
      plus one negative OOS subtotal to offset the nominal value
    """
    currency = sales_invoice_doc.currency
    total_tax = _nominal_q2(sum(row["tax_amount"] for row in tax_breakdown))
    total_sar_tax = _nominal_q2(sum(row["sar_tax_amount"] for row in tax_breakdown))
    total_taxable = _nominal_q2(sum(row["taxable_amount"] for row in tax_breakdown))

    cac_taxtotal_summary = ET.SubElement(invoice, CAC_TAX_TOTAL)
    cbc_taxamount_summary = ET.SubElement(cac_taxtotal_summary, CBC_TAX_AMOUNT)
    cbc_taxamount_summary.set("currencyID", "SAR")
    cbc_taxamount_summary.text = str(total_sar_tax if currency != "SAR" else total_tax)

    cac_taxtotal_detailed = ET.SubElement(invoice, CAC_TAX_TOTAL)
    cbc_taxamount = ET.SubElement(cac_taxtotal_detailed, CBC_TAX_AMOUNT)
    cbc_taxamount.set("currencyID", currency)
    cbc_taxamount.text = str(total_tax)

    for row in tax_breakdown:
        cac_taxsubtotal = ET.SubElement(cac_taxtotal_detailed, CAC_TAX_SUBTOTAL)

        cbc_taxableamount = ET.SubElement(cac_taxsubtotal, CBC_TAXABLE_AMOUNT)
        cbc_taxableamount.set("currencyID", currency)
        cbc_taxableamount.text = str(_nominal_q2(row["taxable_amount"]))

        cbc_taxamount_2 = ET.SubElement(cac_taxsubtotal, CBC_TAX_AMOUNT)
        cbc_taxamount_2.set("currencyID", currency)
        cbc_taxamount_2.text = str(_nominal_q2(row["tax_amount"]))

        _nominal_add_tax_category(
            cac_taxsubtotal,
            row["zatca_tax_category"],
            row["tax_rate"],
            row["exemption_reason_code"] if row["zatca_tax_category"] != "Standard" else None,
            sales_invoice_doc.get("custom_exemption_reason"),
        )

    cac_taxsubtotal_2 = ET.SubElement(cac_taxtotal_detailed, CAC_TAX_SUBTOTAL)
    cbc_taxableamount_2 = ET.SubElement(cac_taxsubtotal_2, CBC_TAXABLE_AMOUNT)
    cbc_taxableamount_2.set("currencyID", currency)
    cbc_taxableamount_2.text = str(_nominal_q2(-total_taxable))

    cbc_taxamount_3 = ET.SubElement(cac_taxsubtotal_2, CBC_TAX_AMOUNT)
    cbc_taxamount_3.set("currencyID", currency)
    cbc_taxamount_3.text = "0.00"

    _nominal_add_tax_category(
        cac_taxsubtotal_2,
        OUTSIDE_SCOPE,
        Decimal("0.00"),
        "VATEX-SA-OOS",
        sales_invoice_doc.get("custom_exemption_reason"),
    )
    for child in list(cac_taxsubtotal_2):
        if child.tag == "cac:TaxCategory":
            for sub in list(child):
                if sub.tag == "cbc:TaxExemptionReason":
                    sub.text = "Nominal Invoice"

    return total_taxable, total_tax

def _build_nominal_legal_monetary_total(invoice, sales_invoice_doc, total_taxable, total_tax):
    """
    Preserve nominal invoice monetary semantics:
    - TaxExclusiveAmount = 0
    - TaxInclusiveAmount = tax only
    - AllowanceTotalAmount = taxable amount
    - PayableAmount = tax only
    """
    currency = sales_invoice_doc.currency
    total_taxable = _nominal_q2(total_taxable)
    total_tax = _nominal_q2(total_tax)

    cac_legalmonetarytotal = ET.SubElement(invoice, "cac:LegalMonetaryTotal")

    cbc_lineextensionamount = ET.SubElement(cac_legalmonetarytotal, "cbc:LineExtensionAmount")
    cbc_lineextensionamount.set("currencyID", currency)
    cbc_lineextensionamount.text = str(total_taxable)

    cbc_taxexclusiveamount = ET.SubElement(cac_legalmonetarytotal, "cbc:TaxExclusiveAmount")
    cbc_taxexclusiveamount.set("currencyID", currency)
    cbc_taxexclusiveamount.text = "0.00"

    cbc_taxinclusiveamount = ET.SubElement(cac_legalmonetarytotal, "cbc:TaxInclusiveAmount")
    cbc_taxinclusiveamount.set("currencyID", currency)
    cbc_taxinclusiveamount.text = str(total_tax)

    cbc_allowancetotalamount = ET.SubElement(cac_legalmonetarytotal, "cbc:AllowanceTotalAmount")
    cbc_allowancetotalamount.set("currencyID", currency)
    cbc_allowancetotalamount.text = str(total_taxable)

    cbc_payableamount = ET.SubElement(cac_legalmonetarytotal, "cbc:PayableAmount")
    cbc_payableamount.set("currencyID", currency)
    cbc_payableamount.text = str(total_tax)

    return cac_legalmonetarytotal

def tax_data_with_template_nominal(invoice, sales_invoice_doc):
    """
    Clean nominal invoice tax builder for invoices using Item Tax Template.

    Uses the same line-net source of truth adopted elsewhere in the app,
    while preserving nominal invoice monetary semantics.
    """
    try:
        tax_breakdown = _nominal_breakdown_with_template(sales_invoice_doc)
        total_taxable, total_tax = _append_nominal_tax_totals(
            invoice, sales_invoice_doc, tax_breakdown
        )
        _build_nominal_legal_monetary_total(
            invoice, sales_invoice_doc, total_taxable, total_tax
        )
        return invoice

    except (ValueError, AttributeError, KeyError, TypeError) as error:
        frappe.throw(
            _(
                f"Error in nominal tax data with template due to invalid value or missing data: {str(error)}"
            )
        )
        return None

    except ET.ParseError as error:
        frappe.throw(_(f"XML Parse Error in nominal tax data with template: {str(error)}"))
        return None

def tax_data_nominal(invoice, sales_invoice_doc):
    """
    Clean nominal invoice tax builder without Item Tax Template.

    Uses line net amounts as the source of truth and preserves
    nominal invoice monetary behavior.
    """
    try:
        tax_breakdown = _nominal_breakdown_without_template(sales_invoice_doc)
        total_taxable, total_tax = _append_nominal_tax_totals(
            invoice, sales_invoice_doc, tax_breakdown
        )
        _build_nominal_legal_monetary_total(
            invoice, sales_invoice_doc, total_taxable, total_tax
        )
        return invoice

    except (ValueError, AttributeError, KeyError, TypeError) as error:
        frappe.throw(
            _(
                f"Error in nominal tax data due to invalid value or missing data: {str(error)}"
            )
        )
        return None

    except ET.ParseError as error:
        frappe.throw(_(f"XML Parse Error in nominal tax data: {str(error)}"))
        return None

def get_tax_wise_detail(sales_invoice_doc,single_item):
    """getting item wise tax"""
    tax_amount, tax_rate = get_item_tax_detail(sales_invoice_doc, single_item)
    return json.dumps({str(single_item.item_code): [tax_rate, tax_amount]})

def _quantize_2(value):
    """Return a Decimal rounded to 2 decimal places using HALF_UP."""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _is_company_currency_document(sales_invoice_doc):
    return sales_invoice_doc.currency == getattr(sales_invoice_doc, "company_currency", sales_invoice_doc.currency)

def _line_net_amount(single_item, sales_invoice_doc):
    """Use line net amount as the source of truth for ZATCA XML."""
    if _is_company_currency_document(sales_invoice_doc):
        value = single_item.get("base_net_amount")
        if value is None:
            value = single_item.get("net_amount")
        if value is None:
            value = single_item.get("base_amount")
        if value is None:
            value = single_item.get("amount")
    else:
        value = single_item.get("net_amount")
        if value is None:
            value = single_item.get("amount")
    return _quantize_2(abs(value or 0))

PRICE_AMOUNT_QUANTIZER = Decimal("0.000000000001")

def _quantize_price_amount(value):
    """
    Return BT-146 / PriceAmount with controlled high precision.

    ZATCA decimal limits apply to Amount business terms such as BT-131,
    not to the unit price amount BT-146. Keeping more precision here avoids
    BR-KSA-EN16931-11 differences when document-level discounts are already
    distributed into ERPNext line net amounts.
    """
    return Decimal(str(value or 0)).quantize(
        PRICE_AMOUNT_QUANTIZER,
        rounding=ROUND_HALF_UP,
    )

def _format_price_amount(value):
    """
    Format BT-146 / PriceAmount.

    Trailing zeros are removed to keep the XML readable, but at least two
    decimal places are retained for normal prices such as 3400.00.
    """
    value = _quantize_price_amount(value)
    text = format(value, "f")

    if "." not in text:
        return f"{text}.00"

    integer_part, decimal_part = text.split(".", 1)
    decimal_part = decimal_part.rstrip("0")

    if len(decimal_part) < 2:
        decimal_part = decimal_part.ljust(2, "0")

    return f"{integer_part}.{decimal_part}"

def _line_quantity(single_item):
    """Return absolute invoice line quantity as Decimal."""
    return Decimal(str(abs(single_item.get("qty") or 0)))

def _line_net_rate(single_item, sales_invoice_doc):
    """
    Derive BT-146 / PriceAmount from BT-131 / BT-129.

    Do not depend on base_net_rate/net_rate because ERPNext may round those
    rates to two decimals after distributing invoice-level discounts. ZATCA
    validates BT-131 against quantity multiplied by BT-146, so BT-146 must be
    precise enough to reproduce the already rounded BT-131.

    If quantity is zero, return zero defensively as requested.
    """
    qty = _line_quantity(single_item)
    if qty == Decimal("0"):
        return _quantize_price_amount(0)

    line_net_amount = _line_net_amount(single_item, sales_invoice_doc)
    return _quantize_price_amount(line_net_amount / qty)

def _clean_text_value(value):
    """Strip HTML tags and normalize whitespace for ZATCA text nodes."""
    value = unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value

def _line_name(single_item):
    description = _clean_text_value(single_item.get("description"))
    if description:
        return description
    item_name = _clean_text_value(single_item.get("item_name"))
    if item_name:
        return item_name
    return _clean_text_value(single_item.get("item_code"))

def _line_tax_amount_from_net(net_amount, tax_rate):
    return (Decimal(str(net_amount)) * Decimal(str(tax_rate or 0)) / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

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

def get_tax_code(category):
    """get tax code"""
    return {"Standard": "S", "Exempted": "E", ZERO_RATED: "Z", OUTSIDE_SCOPE: "O"}.get(
        category, "S"
    )

def get_time_string(posting_time):
    """get time string"""
    try:
        return get_time(posting_time).strftime("%H:%M:%S")
    except:
        return "00:00:00"

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
