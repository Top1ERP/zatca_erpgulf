"""
This module contains utilities for ZATCA 2024 e-invoicing.
Includes functions for XML parsing, API interactions, and custom handling.
"""

from decimal import Decimal, ROUND_DOWN
import re
from html import unescape
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
from frappe.utils.data import get_time
from decimal import Decimal, ROUND_HALF_UP
import frappe
import json
from frappe import _
from zatca_erpgulf.zatca_erpgulf.xml_tax_data import (
    get_tax_for_item,
    get_exemption_reason_map,
)


ITEM_TAX_TEMPLATE = "Item Tax Template"
CAC_TAX_TOTAL = "cac:TaxTotal"
CBC_TAX_AMOUNT = "cbc:TaxAmount"
CAC_TAX_SUBTOTAL = "cac:TaxSubtotal"
CBC_TAXABLE_AMOUNT = "cbc:TaxableAmount"
ZERO_RATED = "Zero Rated"
OUTSIDE_SCOPE = "Services outside scope of tax / Not subject to VAT"


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


def _nominal_add_tax_category(parent, zatca_tax_category, tax_rate, exemption_reason_code=None):
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
        if exemption_reason_code in reason_map:
            cbc_reason.text = reason_map[exemption_reason_code]

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
        item_code = single_item.get("item_code")
        if (
            sales_invoice_doc.get("taxes")
            and sales_invoice_doc.taxes[0].get("item_wise_tax_detail")
            and item_code
        ):
            _item_tax_amount, tax_percentage = get_tax_for_item(
                sales_invoice_doc.taxes[0].item_wise_tax_detail,
                item_code,
            )
            if tax_percentage not in (None, ""):
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

def add_line_item_discount(cac_price, single_item, sales_invoice_doc):
    """
    Adds a line item discount and related details to the XML structure.

    In the net-based XML approach, document discounts are already reflected in
    line net rate / line net amount. To avoid double-discounting in ZATCA XML,
    this helper intentionally returns without adding XML nodes.
    """
    return cac_price


def get_tax_wise_detail(sales_invoice_doc,single_item):
    """getting item wise tax"""
    if int(frappe.__version__.split(".", 1)[0]) == 16 and sales_invoice_doc.item_wise_tax_details:
                tax_rate = float(f"{sales_invoice_doc.item_wise_tax_details[0].rate:.1f}")
                tax_amount = sales_invoice_doc.item_wise_tax_details[0].amount

                # build JSON exactly like v15
                tax_json = json.dumps({
                    single_item.item_code: [tax_rate, float(tax_amount)]
                })
    else:
        tax_json = sales_invoice_doc.taxes[0].item_wise_tax_detail
    return tax_json


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


def _line_net_rate(single_item, sales_invoice_doc):
    """Use line net rate as the source of truth for ZATCA XML."""
    if _is_company_currency_document(sales_invoice_doc):
        value = single_item.get("base_net_rate")
        if value is None:
            value = single_item.get("net_rate")
        if value is None:
            value = single_item.get("base_rate")
        if value is None:
            value = single_item.get("rate")
    else:
        value = single_item.get("net_rate")
        if value is None:
            value = single_item.get("rate")
    return _quantize_2(abs(value or 0))


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
            _item_tax_amount, item_tax_percentage = get_tax_for_item(
                tax_json, single_item.item_code
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
            cbc_priceamount.text = f"{line_net_rate:.2f}"

        return invoice
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
            _item_tax_amount, item_tax_percentage = get_tax_for_item(
                tax_json, single_item.item_code
            )

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
            ).text = f"{line_net_rate:.2f}"

        if (
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
        total_lines = len(invoice.findall("cac:InvoiceLine"))

        return invoice

    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(_(f"❌ Error in item_data_advance_invoice: {str(e)}"))
        return None


# --- Helper Function ---
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


def custom_round(value):
    """Rounding CCording to our need"""
    # Convert the value to a Decimal for accurate handling
    decimal_value = Decimal(str(value))

    # Check if the number has less than 3 decimal places
    if decimal_value.as_tuple().exponent >= -2:
        # If there are less than 3 decimal places, return the original value as float
        return float(decimal_value)

    # Extract the third decimal digit accurately
    third_digit = int((decimal_value * 1000) % 10)

    # Check if the third digit is strictly greater than 5
    if third_digit > 5:
        # Increment the rounded result by 0.01 to ensure rounding up
        return float(decimal_value.quantize(Decimal("0.01")))
    elif third_digit == 5:
        # If the third digit is exactly 5, ensure we round down as desired
        return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    else:
        # Otherwise, round normally to 2 decimal places using ROUND_DOWN
        return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


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
            cbc_priceamount.text = f"{line_net_rate:.2f}"

        return invoice
    except (ValueError, KeyError, TypeError) as e:
        frappe.throw(_(f"Error occurred in item template data processing: {str(e)}"))
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
            ).text = f"{line_net_rate:.2f}"

        if (
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
                    if zatca_tax_category == "Standard":
                        cbc_id_12.text = "S"
                    elif zatca_tax_category == ZERO_RATED:
                        cbc_id_12.text = "Z"
                    elif zatca_tax_category == "Exempted":
                        cbc_id_12.text = "E"
                    elif zatca_tax_category == OUTSIDE_SCOPE:
                        cbc_id_12.text = "O"
                    ET.SubElement(tax_cat, "cbc:ID").text = cbc_id_12.text
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
                    ET.SubElement(tax_cat_adv, "cbc:ID").text = cbc_id_12.text
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


def xml_structuring(invoice):
    """
    Xml structuring and final saving of the xml into private files
    """
    try:

        tree = ET.ElementTree(invoice)
        # xml_file_path = frappe.local.site + "/private/files/xml_files_{invoice_number}.xml"
        # # Save the XML tree to a file
        # with open(xml_file_path, "wb") as file:
        #     tree.write(file, encoding="utf-8", xml_declaration=True)

        # # Read the XML file and format it
        # with open(xml_file_path, "r", encoding="utf-8") as file:
            # xml_string = file.read()
        xml_string = ET.tostring(invoice, encoding="utf-8", method="xml")

        # Format the XML string to make it pretty
        xml_dom = minidom.parseString(xml_string)
        pretty_xml_string = xml_dom.toprettyxml(indent="  ")

        # Write the formatted XML to the final file
        # final_xml_path = f"{frappe.local.site}/private/files/finalzatcaxml_{invoice_number}.xml"

        # with open(final_xml_path, "w", encoding="utf-8") as file:
        #     file.write(pretty_xml_string)
        return pretty_xml_string
    except (FileNotFoundError, IOError):
        frappe.throw(
            _(
                "File operation error occurred while structuring the XML. "
                "Please contact your system administrator."
            )
        )

    except ET.ParseError:
        frappe.throw(
            _(
                "Error occurred in XML parsing or formatting. "
                "Please check the XML structure for errors. "
                "If the problem persists, contact your system administrator."
            )
        )
    except UnicodeDecodeError:
        frappe.throw(
            _(
                "Encoding error occurred while processing the XML file. "
                "Please contact your system administrator."
            )
        )
