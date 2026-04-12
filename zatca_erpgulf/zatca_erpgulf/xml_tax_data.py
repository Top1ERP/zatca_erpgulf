"""
This module contains utilities for ZATCA 2024 e-invoicing.
Includes functions for XML parsing, API interactions, and custom handling.

Modified to build invoice totals and tax breakdowns from line-level net amounts,
so distributed invoice discounts are reflected in item net values and are not
sent again as document-level allowance amounts.
"""

import json
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _

TAX_CALCULATION_ERROR = "Tax Calculation Error"
CAC_TAX_TOTAL = "cac:TaxTotal"
TWOPLACES = Decimal("0.01")


def q2(value):
    """Quantize to 2 decimal places using ROUND_HALF_UP."""
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def abs_q2(value):
    """Absolute quantized decimal."""
    return q2(abs(value))


def get_exemption_reason_map():
    """Mapping of the exception reason code according to the reason code."""
    return {
        "VATEX-SA-29": (
            "Financial services mentioned in Article 29 of the VAT Regulations."
        ),
        "VATEX-SA-29-7": (
            "Life insurance services mentioned in Article 29 of the VAT Regulations."
        ),
        "VATEX-SA-30": (
            "Real estate transactions mentioned in Article 30 of the VAT Regulations."
        ),
        "VATEX-SA-32": "Export of goods.",
        "VATEX-SA-33": "Export of services.",
        "VATEX-SA-34-1": "The international transport of Goods.",
        "VATEX-SA-34-2": "International transport of passengers.",
        "VATEX-SA-34-3": (
            "Services directly connected and incidental to a Supply of "
            "international passenger transport."
        ),
        "VATEX-SA-34-4": "Supply of a qualifying means of transport.",
        "VATEX-SA-34-5": (
            "Any services relating to Goods or passenger transportation, as defined "
            "in article twenty five of these Regulations."
        ),
        "VATEX-SA-35": "Medicines and medical equipment.",
        "VATEX-SA-36": "Qualifying metals.",
        "VATEX-SA-EDU": "Private education to citizen.",
        "VATEX-SA-HEA": "Private healthcare to citizen.",
        "VATEX-SA-MLTRY": "Supply of qualified military goods",
        "VATEX-SA-OOS": (
            "The reason is a free text, has to be provided by the taxpayer on a "
            "case-by-case basis."
        ),
    }


def get_tax_for_item(full_string, item):
    """
    Extracts the tax amount and tax percentage for a specific item
    from a JSON-encoded string.
    """
    try:
        data = json.loads(full_string)
        tax_percentage = data.get(item, [0, 0])[0]
        tax_amount = data.get(item, [0, 0])[1]
        return tax_amount, tax_percentage
    except json.JSONDecodeError as e:
        frappe.throw(_("JSON decoding error occurred in tax for item: " + str(e)))
    except KeyError as e:
        frappe.throw(_(f"Key error occurred while accessing item '{item}': " + str(e)))
    except TypeError as e:
        frappe.throw(_("Type error occurred in tax for item: " + str(e)))
    return None, None


def get_tax_total_from_items(sales_invoice_doc):
    """Get tax total for items using line-level net amounts and line-level rounding."""
    try:
        total_tax = Decimal("0.00")
        for single_item in sales_invoice_doc.items:
            _item_tax_amount, tax_percent = get_tax_for_item(
                sales_invoice_doc.taxes[0].item_wise_tax_detail,
                single_item.item_code,
            )
            net_amount = _get_item_net_amount(single_item, sales_invoice_doc.currency)
            tax_percent = Decimal(str(tax_percent or 0))
            line_tax = q2(net_amount * tax_percent / Decimal("100"))
            total_tax += line_tax
        return q2(total_tax)
    except AttributeError as e:
        frappe.throw(
            _(
                f"AttributeError in get_tax_total_from_items: {str(e)}",
                TAX_CALCULATION_ERROR,
            )
        )
    except KeyError as e:
        frappe.throw(
            _(f"KeyError in get_tax_total_from_items: {str(e)}", TAX_CALCULATION_ERROR)
        )
    except TypeError as e:
        frappe.throw(
            _(f"TypeError in get_tax_total_from_items: {str(e)}", TAX_CALCULATION_ERROR)
        )
    return Decimal("0.00")


def _get_zatca_category_code(category):
    """Map ZATCA category label to XML code."""
    if category == "Standard":
        return "S"
    if category == "Zero Rated":
        return "Z"
    if category == "Exempted":
        return "E"
    if category == "Services outside scope of tax / Not subject to VAT":
        return "O"
    return "S"


def _add_tax_category(parent, zatca_tax_category, tax_rate, exemption_reason_code=None):
    """Append cac:TaxCategory and cac:TaxScheme."""
    cac_taxcategory = ET.SubElement(parent, "cac:TaxCategory")

    cbc_id = ET.SubElement(cac_taxcategory, "cbc:ID")
    cbc_id.text = _get_zatca_category_code(zatca_tax_category)

    cbc_percent = ET.SubElement(cac_taxcategory, "cbc:Percent")
    cbc_percent.text = f"{Decimal(str(tax_rate)):.2f}"

    if zatca_tax_category != "Standard" and exemption_reason_code:
        exemption_reason_map = get_exemption_reason_map()

        cbc_reason_code = ET.SubElement(
            cac_taxcategory, "cbc:TaxExemptionReasonCode"
        )
        cbc_reason_code.text = exemption_reason_code

        cbc_reason = ET.SubElement(cac_taxcategory, "cbc:TaxExemptionReason")
        if exemption_reason_code in exemption_reason_map:
            cbc_reason.text = exemption_reason_map[exemption_reason_code]

    cac_taxscheme = ET.SubElement(cac_taxcategory, "cac:TaxScheme")
    cbc_scheme_id = ET.SubElement(cac_taxscheme, "cbc:ID")
    cbc_scheme_id.text = "VAT"


# ---------------------------------------------------------------------------
# Line-based helpers (new source of truth)
# ---------------------------------------------------------------------------

def _get_item_net_amount(item, currency):
    """Get line net amount using invoice currency/company currency consistently."""
    if currency == "SAR":
        value = (
            item.get("base_net_amount")
            if item.get("base_net_amount") is not None
            else item.get("base_amount", 0)
        )
    else:
        value = (
            item.get("net_amount")
            if item.get("net_amount") is not None
            else item.get("amount", 0)
        )
    return q2(abs(value or 0))


def _get_item_tax_rate_without_template(sales_invoice_doc, item):
    """Get tax rate for an item from item-wise tax detail or fallback to invoice tax rate."""
    try:
        item_code = item.get("item_code")
        if (
            sales_invoice_doc.get("taxes")
            and sales_invoice_doc.taxes[0].get("item_wise_tax_detail")
            and item_code
        ):
            _tax_amount, tax_percentage = get_tax_for_item(
                sales_invoice_doc.taxes[0].item_wise_tax_detail,
                item_code,
            )
            if tax_percentage not in (None, ""):
                return q2(tax_percentage)
    except Exception:
        pass

    if sales_invoice_doc.get("taxes"):
        return q2(sales_invoice_doc.taxes[0].get("rate", 0))
    return Decimal("0.00")


def _sum_line_net_amounts(sales_invoice_doc):
    """Sum all line net amounts; distributed discount is already reflected here."""
    total = Decimal("0.00")
    for item in sales_invoice_doc.items:
        total += _get_item_net_amount(item, sales_invoice_doc.currency)
    return q2(total)


def _get_tax_breakdown_without_template(sales_invoice_doc):
    """Build VAT breakdown from line net amounts for invoices without item tax template."""
    tax_category = sales_invoice_doc.get("custom_zatca_tax_category") or "Standard"
    exemption_reason_code = sales_invoice_doc.get("custom_exemption_reason_code")

    taxable_amount = _sum_line_net_amounts(sales_invoice_doc)

    # Sum tax with line-level rounding to match ERPNext / ZATCA expectations.
    total_tax = Decimal("0.00")
    effective_rate = None
    for item in sales_invoice_doc.items:
        item_tax_rate = _get_item_tax_rate_without_template(sales_invoice_doc, item)
        if effective_rate is None:
            effective_rate = item_tax_rate
        item_net_amount = _get_item_net_amount(item, sales_invoice_doc.currency)
        total_tax += q2(item_net_amount * item_tax_rate / Decimal("100"))

    total_tax = q2(total_tax)
    effective_rate = q2(effective_rate or 0)

    return [
        {
            "zatca_tax_category": tax_category,
            "taxable_amount": taxable_amount,
            "tax_amount": total_tax,
            "tax_rate": effective_rate,
            "exemption_reason_code": (
                exemption_reason_code if tax_category != "Standard" else None
            ),
        }
    ]


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


def _get_prepaid_amount(sales_invoice_doc):
    """Get prepaid amount from custom advances if present."""
    if not hasattr(sales_invoice_doc, "custom_advances_copy"):
        return Decimal("0.00")

    if not sales_invoice_doc.custom_advances_copy:
        return Decimal("0.00")

    valid_advances = [
        x for x in sales_invoice_doc.custom_advances_copy
        if getattr(x, "reference_name", None)
    ]
    if not valid_advances:
        return Decimal("0.00")

    total = sum(Decimal(str(x.advance_amount)) for x in valid_advances)
    return q2(total)


def _validate_tax_equations(
    currency,
    tax_exclusive_amount,
    tax_amount,
    tax_inclusive_amount,
    payable_amount,
    prepaid_amount=Decimal("0.00"),
    tax_subtotal_amount=None,
    context="",
):
    """
    Validate internal XML equations before sending to ZATCA.
    Raises frappe.throw on mismatch.
    """
    tax_exclusive_amount = q2(tax_exclusive_amount)
    tax_amount = q2(tax_amount)
    tax_inclusive_amount = q2(tax_inclusive_amount)
    payable_amount = q2(payable_amount)
    prepaid_amount = q2(prepaid_amount)

    expected_tax_inclusive = q2(tax_exclusive_amount + tax_amount)
    if tax_inclusive_amount != expected_tax_inclusive:
        frappe.throw(
            _(
                f"ZATCA pre-validation failed {context}: "
                f"TaxInclusiveAmount mismatch in {currency}. "
                f"Expected {expected_tax_inclusive} = TaxExclusiveAmount "
                f"{tax_exclusive_amount} + TaxAmount {tax_amount}, "
                f"but found {tax_inclusive_amount}."
            )
        )

    expected_payable = q2(tax_inclusive_amount - prepaid_amount)
    if payable_amount != expected_payable:
        frappe.throw(
            _(
                f"ZATCA pre-validation failed {context}: "
                f"PayableAmount mismatch in {currency}. "
                f"Expected {expected_payable} = TaxInclusiveAmount "
                f"{tax_inclusive_amount} - PrepaidAmount {prepaid_amount}, "
                f"but found {payable_amount}."
            )
        )

    if tax_subtotal_amount is not None:
        tax_subtotal_amount = q2(tax_subtotal_amount)
        if tax_subtotal_amount != tax_amount:
            frappe.throw(
                _(
                    f"ZATCA pre-validation failed {context}: "
                    f"TaxSubtotal TaxAmount mismatch in {currency}. "
                    f"TaxTotal is {tax_amount}, but TaxSubtotal is {tax_subtotal_amount}."
                )
            )


def _build_legal_monetary_total(
    invoice,
    currency,
    line_extension_amount,
    tax_exclusive_amount,
    tax_amount,
    discount_amount,
    prepaid_amount=Decimal("0.00"),
):
    """Create cac:LegalMonetaryTotal block."""
    totals = ET.SubElement(invoice, "cac:LegalMonetaryTotal")

    line_extension_amount = q2(line_extension_amount)
    tax_exclusive_amount = q2(tax_exclusive_amount)
    tax_amount = q2(tax_amount)
    discount_amount = q2(discount_amount)
    prepaid_amount = q2(prepaid_amount)

    cbc_lineextensionamount = ET.SubElement(totals, "cbc:LineExtensionAmount")
    cbc_lineextensionamount.set("currencyID", currency)
    cbc_lineextensionamount.text = str(line_extension_amount)

    cbc_taxexclusiveamount = ET.SubElement(totals, "cbc:TaxExclusiveAmount")
    cbc_taxexclusiveamount.set("currencyID", currency)
    cbc_taxexclusiveamount.text = str(tax_exclusive_amount)

    tax_inclusive_amount = q2(tax_exclusive_amount + tax_amount)

    cbc_taxinclusiveamount = ET.SubElement(totals, "cbc:TaxInclusiveAmount")
    cbc_taxinclusiveamount.set("currencyID", currency)
    cbc_taxinclusiveamount.text = str(tax_inclusive_amount)

    cbc_allowancetotalamount = ET.SubElement(totals, "cbc:AllowanceTotalAmount")
    cbc_allowancetotalamount.set("currencyID", currency)
    cbc_allowancetotalamount.text = str(discount_amount)

    if prepaid_amount > Decimal("0.00"):
        cbc_prepaidamount = ET.SubElement(totals, "cbc:PrepaidAmount")
        cbc_prepaidamount.set("currencyID", currency)
        cbc_prepaidamount.text = str(prepaid_amount)

    payable_amount = q2(tax_inclusive_amount - prepaid_amount)

    cbc_payableamount = ET.SubElement(totals, "cbc:PayableAmount")
    cbc_payableamount.set("currencyID", currency)
    cbc_payableamount.text = str(payable_amount)

    _validate_tax_equations(
        currency=currency,
        tax_exclusive_amount=tax_exclusive_amount,
        tax_amount=tax_amount,
        tax_inclusive_amount=tax_inclusive_amount,
        payable_amount=payable_amount,
        prepaid_amount=prepaid_amount,
        context="[LegalMonetaryTotal]",
    )

    return totals


def tax_data(invoice, sales_invoice_doc):
    """Extract tax data without item tax template, using line-level net amounts."""
    try:
        currency = sales_invoice_doc.currency
        prepaid_amount = _get_prepaid_amount(sales_invoice_doc)

        tax_breakdown = _get_tax_breakdown_without_template(sales_invoice_doc)
        taxable_amount = q2(sum(row["taxable_amount"] for row in tax_breakdown))
        line_extension_amount = taxable_amount
        total_tax, subtotal_tax_sum = _append_tax_totals(
            invoice, currency, tax_breakdown, sales_invoice_doc
        )

        # Discount already distributed to item net amounts.
        discount_amount = Decimal("0.00")

        _validate_tax_equations(
            currency=currency,
            tax_exclusive_amount=taxable_amount,
            tax_amount=total_tax,
            tax_inclusive_amount=q2(taxable_amount + total_tax),
            payable_amount=q2(q2(taxable_amount + total_tax) - prepaid_amount),
            prepaid_amount=prepaid_amount,
            tax_subtotal_amount=subtotal_tax_sum,
            context="[tax_data]",
        )

        _build_legal_monetary_total(
            invoice=invoice,
            currency=currency,
            line_extension_amount=line_extension_amount,
            tax_exclusive_amount=taxable_amount,
            tax_amount=total_tax,
            discount_amount=discount_amount,
            prepaid_amount=prepaid_amount,
        )

        return invoice

    except Exception as e:
        frappe.throw(_(f"Data processing error in tax data: {str(e)}"))
        return None


def tax_data_with_template(invoice, sales_invoice_doc):
    """Add tax data with item tax template to the XML using line-level net amounts."""
    try:
        currency = sales_invoice_doc.currency
        prepaid_amount = _get_prepaid_amount(sales_invoice_doc)

        tax_breakdown = _get_tax_breakdown_with_template(sales_invoice_doc)
        tax_exclusive_amount = q2(sum(row["taxable_amount"] for row in tax_breakdown))
        line_extension_amount = tax_exclusive_amount

        total_tax, subtotal_tax_sum = _append_tax_totals(
            invoice, currency, tax_breakdown, sales_invoice_doc
        )

        # Discount already distributed to item net amounts.
        discount_amount = Decimal("0.00")

        _validate_tax_equations(
            currency=currency,
            tax_exclusive_amount=tax_exclusive_amount,
            tax_amount=total_tax,
            tax_inclusive_amount=q2(tax_exclusive_amount + total_tax),
            payable_amount=q2(q2(tax_exclusive_amount + total_tax) - prepaid_amount),
            prepaid_amount=prepaid_amount,
            tax_subtotal_amount=subtotal_tax_sum,
            context="[tax_data_with_template]",
        )

        _build_legal_monetary_total(
            invoice=invoice,
            currency=currency,
            line_extension_amount=line_extension_amount,
            tax_exclusive_amount=tax_exclusive_amount,
            tax_amount=total_tax,
            discount_amount=discount_amount,
            prepaid_amount=prepaid_amount,
        )

        return invoice

    except Exception as e:
        frappe.throw(_(f"Data processing error in tax data template: {str(e)}"))
        return None
