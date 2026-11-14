"""POS financial compatibility entry points and XML formatting.

Ordinary POS monetary and line generation delegates to pos_financial_xml. Keep
historical public imports available for supported integrations; they are not
used to choose the canonical financial calculation.
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from frappe import _
# Keep the full-detail import available as an integration compatibility alias.
from zatca_erpgulf.ksa_compliance.tax_details import (
    get_item_tax_detail,
    get_item_tax_rate,
)
import frappe
from zatca_erpgulf.zatca_erpgulf.pos_financial_xml import (
    render_pos_section as _render_pos_financials,
)
from zatca_erpgulf.zatca_erpgulf.posxml import (
    get_exemption_reason_map,
    add_line_item_discount,
)


ITEM_TAX_TEMPLATE = "Item Tax Template"
CAC_TAX_TOTAL = "cac:TaxTotal"
CBC_TAX_AMOUNT = "cbc:TaxAmount"


def tax_data_with_template(invoice, pos_invoice_doc):
    """Generate reconciled POS financial XML from final ERP line nets."""
    return _render_pos_financials(invoice, pos_invoice_doc,
        has_template=True, section="totals",
        runtime=frappe, translate=_, read_rate=get_item_tax_rate)


def item_data(invoice, pos_invoice_doc):
    """Generate reconciled POS financial XML from final ERP line nets."""
    return _render_pos_financials(invoice, pos_invoice_doc,
        has_template=False, section="lines",
        runtime=frappe, translate=_, read_rate=get_item_tax_rate)


def item_data_with_template(invoice, pos_invoice_doc):
    """Generate reconciled POS financial XML from final ERP line nets."""
    return _render_pos_financials(invoice, pos_invoice_doc,
        has_template=True, section="lines",
        runtime=frappe, translate=_, read_rate=get_item_tax_rate)


def xml_structuring(invoice):
    """function for xml structuring"""
    try:
        empty_elements = [
            element.tag
            for element in invoice.iter()
            if len(element) == 0
            and not (element.text or "").strip()
            # The ds/xades signature skeleton is populated by the signing
            # step after XML structuring; do not validate it as invoice data.
            and not str(element.tag).startswith(("ds:", "xades:"))
        ]
        if empty_elements:
            frappe.throw(
                _(
                    "ZATCA XML contains empty elements: {0}. "
                    "Populate mandatory values or omit optional fields before signing."
                ).format(", ".join(empty_elements))
            )

        # xml_file_path = f"{frappe.local.site}/private/files/xml_files_{invoice_number}.xml"
        tree = ET.ElementTree(invoice)
        xml_string = ET.tostring(invoice, encoding="utf-8", method="xml")
        xml_dom = minidom.parseString(xml_string)
        pretty_xml_string = xml_dom.toprettyxml(
            indent="  "
        )  # created xml into formatted xml form
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
        return None

    except ET.ParseError:
        frappe.throw(
            _(
                "Error occurred in XML parsing or formatting. "
                "Please check the XML structure for errors. "
                "If the problem persists, contact your system administrator."
            )
        )
        return None
    except UnicodeDecodeError:
        frappe.throw(
            _(
                "Encoding error occurred while processing the XML file. "
                "Please contact your system administrator."
            )
        )
        return None


# Stable code identities let the compositor recognize unchanged public adapters.
_CANONICAL_POS_BUILDERS = {
    "tax_data_with_template": tax_data_with_template,
    "item_data": item_data,
    "item_data_with_template": item_data_with_template,
}
