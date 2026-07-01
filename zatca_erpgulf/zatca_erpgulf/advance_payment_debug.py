"""Debug/local ZATCA advance payment XML generation from Payment Entry.

This module intentionally does not submit anything to ZATCA.
It creates a local XML attachment for review and future development.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from xml.dom import minidom

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime


TWOPLACES = Decimal("0.01")


def _q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _safe_text(value) -> str:
    return str(value or "").strip()


def _advance_amount(payment_entry) -> Decimal:
    received_amount = _q2(getattr(payment_entry, "received_amount", 0))
    paid_amount = _q2(getattr(payment_entry, "paid_amount", 0))

    if received_amount > Decimal("0.00"):
        return received_amount

    return paid_amount


def _payment_currency(payment_entry) -> str:
    return (
        _safe_text(getattr(payment_entry, "paid_to_account_currency", None))
        or _safe_text(getattr(payment_entry, "paid_from_account_currency", None))
        or _safe_text(getattr(payment_entry, "company_currency", None))
        or "SAR"
    )


def _require_company_advance_enabled(company: str) -> None:
    company_doc = frappe.get_doc("Company", company)

    enabled = cint(getattr(company_doc, "custom_zatca_advance_payment_enabled", 0))
    mode = _safe_text(
        getattr(company_doc, "custom_zatca_advance_payment_submission_mode", "Local Only")
    )

    if not enabled:
        frappe.throw(
            _(
                "ZATCA Advance Payment is not enabled for this company. "
                "Enable it from Company settings first."
            )
        )

    if mode == "Disabled":
        frappe.throw(
            _(
                "ZATCA Advance Payment Submission Mode is Disabled for this company."
            )
        )


def _build_debug_xml(payment_entry, advance_uuid: str) -> str:
    issue_dt = payment_entry.posting_date or now_datetime().date()
    issue_time = _safe_text(getattr(payment_entry, "posting_time", None)) or "00:00:00"
    currency = _payment_currency(payment_entry)
    amount = _advance_amount(payment_entry)

    invoice = ET.Element(
        "Invoice",
        {
            "xmlns": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "xmlns:cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "xmlns:cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "xmlns:ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
        },
    )

    ET.SubElement(invoice, "cbc:ProfileID").text = "reporting:1.0"
    ET.SubElement(invoice, "cbc:ID").text = payment_entry.name
    ET.SubElement(invoice, "cbc:UUID").text = advance_uuid
    ET.SubElement(invoice, "cbc:IssueDate").text = str(issue_dt)
    ET.SubElement(invoice, "cbc:IssueTime").text = str(issue_time)

    invoice_type = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
    invoice_type.set("name", "0100000")
    invoice_type.text = "386"

    ET.SubElement(invoice, "cbc:DocumentCurrencyCode").text = currency
    ET.SubElement(invoice, "cbc:TaxCurrencyCode").text = "SAR"

    note = ET.SubElement(invoice, "cbc:Note")
    note.text = (
        "DEBUG ONLY - Local ZATCA advance payment XML skeleton generated from "
        "ERPNext Payment Entry. This XML is not submitted to ZATCA."
    )

    supplier_party = ET.SubElement(invoice, "cac:AccountingSupplierParty")
    supplier = ET.SubElement(supplier_party, "cac:Party")
    supplier_name = ET.SubElement(supplier, "cac:PartyName")
    ET.SubElement(supplier_name, "cbc:Name").text = payment_entry.company

    customer_party = ET.SubElement(invoice, "cac:AccountingCustomerParty")
    customer = ET.SubElement(customer_party, "cac:Party")
    customer_name = ET.SubElement(customer, "cac:PartyName")
    ET.SubElement(customer_name, "cbc:Name").text = _safe_text(payment_entry.party)

    monetary_total = ET.SubElement(invoice, "cac:LegalMonetaryTotal")
    for tag in (
        "LineExtensionAmount",
        "TaxExclusiveAmount",
        "TaxInclusiveAmount",
        "PayableAmount",
    ):
        element = ET.SubElement(monetary_total, f"cbc:{tag}")
        element.set("currencyID", currency)
        element.text = str(amount)

    invoice_line = ET.SubElement(invoice, "cac:InvoiceLine")
    ET.SubElement(invoice_line, "cbc:ID").text = "1"

    quantity = ET.SubElement(invoice_line, "cbc:InvoicedQuantity")
    quantity.set("unitCode", "EA")
    quantity.text = "1"

    line_amount = ET.SubElement(invoice_line, "cbc:LineExtensionAmount")
    line_amount.set("currencyID", currency)
    line_amount.text = str(amount)

    item = ET.SubElement(invoice_line, "cac:Item")
    ET.SubElement(item, "cbc:Name").text = "Advance Payment"

    price = ET.SubElement(invoice_line, "cac:Price")
    price_amount = ET.SubElement(price, "cbc:PriceAmount")
    price_amount.set("currencyID", currency)
    price_amount.text = str(amount)

    rough = ET.tostring(invoice, encoding="utf-8")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def _attach_xml(payment_entry, xml_content: str) -> str:
    filename = f"ZATCA Advance Debug XML {payment_entry.name}.xml"

    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": filename,
            "attached_to_doctype": "Payment Entry",
            "attached_to_name": payment_entry.name,
            "is_private": 1,
            "content": xml_content,
        }
    )
    file_doc.insert(ignore_permissions=True)
    return file_doc.file_url


@frappe.whitelist()
def create_advance_xml_for_debug(payment_entry_name: str) -> dict:
    """Create local/debug ZATCA advance payment XML for a Payment Entry."""
    if not payment_entry_name:
        frappe.throw(_("Payment Entry name is required."))

    payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)

    if payment_entry.docstatus == 2:
        frappe.throw(_("Cannot create ZATCA advance debug XML for a cancelled Payment Entry."))

    if payment_entry.payment_type != "Receive":
        frappe.throw(_("ZATCA advance payment debug XML is currently supported only for Receive Payment Entries."))

    if payment_entry.party_type != "Customer":
        frappe.throw(_("ZATCA advance payment debug XML requires Party Type to be Customer."))

    if not payment_entry.company:
        frappe.throw(_("Company is required."))

    _require_company_advance_enabled(payment_entry.company)

    amount = _advance_amount(payment_entry)
    if amount <= Decimal("0.00"):
        frappe.throw(_("Advance payment amount must be greater than zero."))

    advance_uuid = str(uuid.uuid4())
    xml_content = _build_debug_xml(payment_entry, advance_uuid)
    file_url = _attach_xml(payment_entry, xml_content)

    payment_entry.db_set("custom_zatca_is_advance_payment", 1, update_modified=False)
    payment_entry.db_set("custom_zatca_advance_invoice_status", "Debug XML Created", update_modified=False)
    payment_entry.db_set("custom_zatca_advance_invoice_uuid", advance_uuid, update_modified=False)
    payment_entry.db_set("custom_zatca_advance_xml", file_url, update_modified=False)
    payment_entry.db_set("custom_zatca_advance_last_debug_at", now_datetime(), update_modified=False)
    payment_entry.db_set(
        "custom_zatca_advance_full_response",
        "Debug XML generated locally only. No ZATCA submission was performed.",
        update_modified=False,
    )

    return {
        "payment_entry": payment_entry.name,
        "uuid": advance_uuid,
        "file_url": file_url,
        "status": "Debug XML Created",
    }
