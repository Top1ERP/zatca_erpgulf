"""ZATCA advance payment tax invoice foundation.

This module:
- Creates/updates ZATCA Advance Tax Invoice from Payment Entry.
- Performs preflight validation.
- Generates richer unsigned XML.
- Does not submit to ZATCA yet.
"""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal, ROUND_HALF_UP
from xml.dom import minidom

import frappe
from frappe import _
from frappe.utils import cint, get_link_to_form, now_datetime


TWOPLACES = Decimal("0.01")

COUNTRY_OVERRIDES = {
    "saudi arabia": "SA", "kingdom of saudi arabia": "SA", "ksa": "SA", "السعودية": "SA", "المملكة العربية السعودية": "SA",
    "jordan": "JO", "oman": "OM", "united arab emirates": "AE", "uae": "AE",
    "kuwait": "KW", "qatar": "QA", "bahrain": "BH", "egypt": "EG",
    "united states": "US", "usa": "US", "united kingdom": "GB", "uk": "GB",
}


def _q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _safe_text(value) -> str:
    return str(value or "").strip()


def _doc_value(doc, fieldname: str, default: str = ""):
    return _safe_text(getattr(doc, fieldname, default))


def _country_code(value: str) -> str:
    value = _safe_text(value)
    if not value:
        return "SA"

    lowered = value.lower()
    if lowered in COUNTRY_OVERRIDES:
        return COUNTRY_OVERRIDES[lowered]

    if len(value) == 2 and value.isalpha():
        return value.upper()

    if frappe.db.exists("Country", value):
        meta = frappe.get_meta("Country")
        for fieldname in ("code", "country_code", "iso_2", "iso_code", "alpha_2_code"):
            if meta.has_field(fieldname):
                code = _safe_text(frappe.db.get_value("Country", value, fieldname))
                if code:
                    return code.upper()[:2]

    return value[:2].upper()


def _plain_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def _require_company_advance_enabled(company: str) -> None:
    company_doc = frappe.get_doc("Company", company)
    enabled = cint(getattr(company_doc, "custom_zatca_advance_payment_enabled", 0))
    mode = _safe_text(getattr(company_doc, "custom_zatca_advance_payment_submission_mode", "Local Only"))

    if not enabled:
        frappe.throw(_("ZATCA Advance Payment is not enabled for this company. Enable it from Company settings first."))
    if mode == "Disabled":
        frappe.throw(_("ZATCA Advance Payment Submission Mode is Disabled for this company."))


def _get_or_create_advance_tax_invoice(payment_entry):
    existing = frappe.db.get_value("ZATCA Advance Tax Invoice", {"payment_entry": payment_entry.name}, "name")
    if existing:
        return frappe.get_doc("ZATCA Advance Tax Invoice", existing)

    doc = frappe.new_doc("ZATCA Advance Tax Invoice")
    doc.company = payment_entry.company
    doc.payment_entry = payment_entry.name
    doc.customer = payment_entry.party
    doc.posting_date = payment_entry.posting_date
    doc.status = "Draft"
    if doc.meta.has_field("zatca_status"):
        doc.zatca_status = "Not Submitted"
    doc.insert(ignore_permissions=True)
    return doc


def _preflight_issues(doc) -> list[str]:
    issues = []

    required = [
        ("company_name", "Company English name"),
        ("company_name_arabic", "Company Arabic name"),
        ("company_vat_number", "Company VAT number"),
        ("company_address_line1", "Company address line 1"),
        ("company_city", "Company city"),
        ("company_postal_code", "Company postal code"),
        ("company_country_code", "Company country code"),
        ("customer_name", "Customer English name"),
        ("customer_address_line1", "Customer address line 1"),
        ("customer_city", "Customer city"),
        ("customer_postal_code", "Customer postal code"),
        ("customer_country_code", "Customer country code"),
    ]

    for fieldname, label in required:
        if doc.meta.has_field(fieldname) and not _doc_value(doc, fieldname):
            issues.append(f"{label} is missing.")

    is_b2c = cint(getattr(doc, "customer_b2c", 0)) == 1 if doc.meta.has_field("customer_b2c") else 0

    if not is_b2c:
        if doc.meta.has_field("customer_name_arabic") and not _doc_value(doc, "customer_name_arabic"):
            issues.append("B2B customer Arabic name is missing.")

        vat = _doc_value(doc, "customer_vat_number")
        if not vat:
            issues.append("B2B customer VAT number is missing.")
        elif len(vat) != 15:
            issues.append("B2B customer VAT number must be exactly 15 digits.")
        elif doc.customer_country_code == "SA" and not (vat.startswith("3") and vat.endswith("3")):
            issues.append("Saudi B2B customer VAT number must start with 3 and end with 3.")

    company_vat = _doc_value(doc, "company_vat_number")
    if company_vat and (len(company_vat) != 15 or not (company_vat.startswith("3") and company_vat.endswith("3"))):
        issues.append("Company VAT number must be 15 digits and start with 3 and end with 3.")

    taxable = _q2(doc.taxable_amount)
    tax = _q2(doc.tax_amount)
    total = _q2(doc.total_amount)

    if _q2(taxable + tax) != total:
        issues.append(f"Amount mismatch: taxable {taxable} + tax {tax} must equal total {total}.")

    if taxable <= 0:
        issues.append("Taxable amount must be greater than zero.")
    if total <= 0:
        issues.append("Total amount must be greater than zero.")

    return issues


def _set_preflight_result(doc, issues: list[str]):
    if doc.meta.has_field("preflight_checked_at"):
        doc.preflight_checked_at = now_datetime()

    if issues:
        if doc.meta.has_field("preflight_status"):
            doc.preflight_status = "Failed"
        if doc.meta.has_field("preflight_details"):
            doc.preflight_details = "\n".join(f"- {issue}" for issue in issues)
        if doc.meta.has_field("zatca_status"):
            doc.zatca_status = "Failed"
    else:
        if doc.meta.has_field("preflight_status"):
            doc.preflight_status = "Passed"
        if doc.meta.has_field("preflight_details"):
            doc.preflight_details = "Preflight validation passed."
        if doc.meta.has_field("zatca_status") and doc.zatca_status in {"Not Submitted", "Failed"}:
            doc.zatca_status = "Preflight Passed"


def _run_preflight_or_throw(doc):
    doc.validate()
    issues = _preflight_issues(doc)
    _set_preflight_result(doc, issues)
    doc.save(ignore_permissions=True)

    if issues:
        frappe.throw(
            _(
                "Cannot continue because ZATCA preflight validation failed:"
                "<br><br><ul>"
                + "".join(f"<li>{issue}</li>" for issue in issues)
                + "</ul>"
            ),
            title=_("ZATCA Preflight Failed"),
        )


def _money(parent, tag: str, amount, currency: str):
    element = ET.SubElement(parent, f"cbc:{tag}")
    element.set("currencyID", currency)
    element.text = str(_q2(amount))
    return element


def _text(parent, tag: str, value):
    element = ET.SubElement(parent, tag)
    element.text = _safe_text(value)
    return element


def _postal_address(parent, prefix: str, doc):
    address = ET.SubElement(parent, "cac:PostalAddress")
    _text(address, "cbc:StreetName", _doc_value(doc, f"{prefix}_address_line1"))
    _text(address, "cbc:AdditionalStreetName", _doc_value(doc, f"{prefix}_address_line2"))
    _text(address, "cbc:CityName", _doc_value(doc, f"{prefix}_city"))
    _text(address, "cbc:PostalZone", _doc_value(doc, f"{prefix}_postal_code"))

    country = ET.SubElement(address, "cac:Country")
    _text(country, "cbc:IdentificationCode", _doc_value(doc, f"{prefix}_country_code") or _country_code(_doc_value(doc, f"{prefix}_country")))


def _supplier_party(parent, doc):
    supplier_party = ET.SubElement(parent, "cac:AccountingSupplierParty")
    party = ET.SubElement(supplier_party, "cac:Party")

    identification = ET.SubElement(party, "cac:PartyIdentification")
    id_element = ET.SubElement(identification, "cbc:ID")
    id_element.set("schemeID", "VAT")
    id_element.text = _doc_value(doc, "company_vat_number")

    _postal_address(party, "company", doc)

    tax_scheme = ET.SubElement(party, "cac:PartyTaxScheme")
    _text(tax_scheme, "cbc:CompanyID", _doc_value(doc, "company_vat_number"))
    scheme = ET.SubElement(tax_scheme, "cac:TaxScheme")
    _text(scheme, "cbc:ID", "VAT")

    legal_entity = ET.SubElement(party, "cac:PartyLegalEntity")
    _text(legal_entity, "cbc:RegistrationName", _doc_value(doc, "company_name") or doc.company)


def _customer_party(parent, doc):
    customer_party = ET.SubElement(parent, "cac:AccountingCustomerParty")
    party = ET.SubElement(customer_party, "cac:Party")

    customer_vat = _doc_value(doc, "customer_vat_number")
    if customer_vat:
        identification = ET.SubElement(party, "cac:PartyIdentification")
        id_element = ET.SubElement(identification, "cbc:ID")
        id_element.set("schemeID", "VAT")
        id_element.text = customer_vat

    _postal_address(party, "customer", doc)

    if customer_vat:
        tax_scheme = ET.SubElement(party, "cac:PartyTaxScheme")
        _text(tax_scheme, "cbc:CompanyID", customer_vat)
        scheme = ET.SubElement(tax_scheme, "cac:TaxScheme")
        _text(scheme, "cbc:ID", "VAT")

    legal_entity = ET.SubElement(party, "cac:PartyLegalEntity")
    _text(legal_entity, "cbc:RegistrationName", _doc_value(doc, "customer_name") or doc.customer)


def _tax_total(parent, doc, currency: str):
    tax_total = ET.SubElement(parent, "cac:TaxTotal")
    _money(tax_total, "TaxAmount", doc.tax_amount, currency)

    subtotal = ET.SubElement(tax_total, "cac:TaxSubtotal")
    _money(subtotal, "TaxableAmount", doc.taxable_amount, currency)
    _money(subtotal, "TaxAmount", doc.tax_amount, currency)

    category = ET.SubElement(subtotal, "cac:TaxCategory")
    _text(category, "cbc:ID", _doc_value(doc, "tax_category_code", "S") or "S")
    _text(category, "cbc:Percent", str(_q2(doc.tax_rate or 0)))
    scheme = ET.SubElement(category, "cac:TaxScheme")
    _text(scheme, "cbc:ID", "VAT")


def _build_debug_xml(doc) -> str:
    if not doc.zatca_uuid:
        doc.zatca_uuid = str(uuid.uuid4())

    currency = doc.currency or "SAR"
    issue_date = doc.posting_date or now_datetime().date()
    issue_time = _safe_text(doc.posting_time) or "00:00:00"

    invoice = ET.Element(
        "Invoice",
        {
            "xmlns": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "xmlns:cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "xmlns:cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "xmlns:ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
        },
    )

    _text(invoice, "cbc:ProfileID", "reporting:1.0")
    _text(invoice, "cbc:ID", doc.name)
    _text(invoice, "cbc:UUID", doc.zatca_uuid)
    _text(invoice, "cbc:IssueDate", str(issue_date))
    _text(invoice, "cbc:IssueTime", str(issue_time))

    invoice_type = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
    invoice_type.set("name", "0100000")
    invoice_type.text = "386"

    _text(invoice, "cbc:DocumentCurrencyCode", currency)
    _text(invoice, "cbc:TaxCurrencyCode", "SAR")
    _text(invoice, "cbc:Note", "DEBUG ONLY - unsigned local ZATCA advance tax invoice XML. No ZATCA submission was performed.")

    if _doc_value(doc, "terms"):
        _text(invoice, "cbc:Note", _plain_text(_doc_value(doc, "terms"))[:1000])

    _supplier_party(invoice, doc)
    _customer_party(invoice, doc)

    payment_means = ET.SubElement(invoice, "cac:PaymentMeans")
    _text(payment_means, "cbc:PaymentMeansCode", _doc_value(doc, "payment_means_code", "10") or "10")

    _tax_total(invoice, doc, currency)

    monetary_total = ET.SubElement(invoice, "cac:LegalMonetaryTotal")
    _money(monetary_total, "LineExtensionAmount", doc.taxable_amount, currency)
    _money(monetary_total, "TaxExclusiveAmount", doc.taxable_amount, currency)
    _money(monetary_total, "TaxInclusiveAmount", doc.total_amount, currency)
    _money(monetary_total, "AllowanceTotalAmount", 0, currency)
    _money(monetary_total, "PayableAmount", doc.total_amount, currency)

    line = ET.SubElement(invoice, "cac:InvoiceLine")
    _text(line, "cbc:ID", "1")
    qty = ET.SubElement(line, "cbc:InvoicedQuantity")
    qty.set("unitCode", "EA")
    qty.text = "1"
    _money(line, "LineExtensionAmount", doc.taxable_amount, currency)

    line_tax = ET.SubElement(line, "cac:TaxTotal")
    _money(line_tax, "TaxAmount", doc.tax_amount, currency)
    _money(line_tax, "RoundingAmount", doc.total_amount, currency)

    item = ET.SubElement(line, "cac:Item")
    _text(item, "cbc:Name", _doc_value(doc, "description", "Advance Payment") or "Advance Payment")

    category = ET.SubElement(item, "cac:ClassifiedTaxCategory")
    _text(category, "cbc:ID", _doc_value(doc, "tax_category_code", "S") or "S")
    _text(category, "cbc:Percent", str(_q2(doc.tax_rate or 0)))
    scheme = ET.SubElement(category, "cac:TaxScheme")
    _text(scheme, "cbc:ID", "VAT")

    price = ET.SubElement(line, "cac:Price")
    _money(price, "PriceAmount", doc.taxable_amount, currency)

    rough = ET.tostring(invoice, encoding="utf-8")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def _attach_xml(doc, xml_content: str) -> str:
    filename = f"ZATCA Advance Debug XML {doc.name}.xml"
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "attached_to_doctype": "ZATCA Advance Tax Invoice",
        "attached_to_name": doc.name,
        "is_private": 1,
        "content": xml_content,
    })
    file_doc.insert(ignore_permissions=True)
    return file_doc.file_url


@frappe.whitelist()
def validate_advance_for_zatca(advance_invoice_name: str) -> dict:
    doc = frappe.get_doc("ZATCA Advance Tax Invoice", advance_invoice_name)
    _run_preflight_or_throw(doc)
    return {"ok": True, "advance_tax_invoice": doc.name, "preflight_status": doc.preflight_status}


@frappe.whitelist()
def create_advance_xml_for_debug(payment_entry_name: str) -> dict:
    if not payment_entry_name:
        frappe.throw(_("Payment Entry name is required."))

    payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)

    if payment_entry.docstatus == 2:
        frappe.throw(_("Cannot create ZATCA advance tax invoice for a cancelled Payment Entry."))
    if payment_entry.payment_type != "Receive":
        frappe.throw(_("ZATCA advance tax invoice is currently supported only for Receive Payment Entries."))
    if payment_entry.party_type != "Customer":
        frappe.throw(_("ZATCA advance tax invoice requires Party Type to be Customer."))
    if not payment_entry.company:
        frappe.throw(_("Company is required."))

    _require_company_advance_enabled(payment_entry.company)

    amount = _q2(getattr(payment_entry, "paid_amount", 0))
    if amount <= Decimal("0.00"):
        frappe.throw(_("Advance payment amount must be greater than zero."))

    doc = _get_or_create_advance_tax_invoice(payment_entry)
    doc.status = "Draft"
    doc.zatca_status = "Debug XML Created"
    doc.validate()
    _run_preflight_or_throw(doc)

    xml_content = _build_debug_xml(doc)
    file_url = _attach_xml(doc, xml_content)

    doc.debug_xml = file_url
    doc.last_debug_at = now_datetime()
    doc.full_response = "Debug XML generated locally only. No ZATCA submission was performed."
    doc.zatca_status = "Debug XML Created"
    doc.save(ignore_permissions=True)

    payment_entry.db_set("custom_zatca_is_advance_payment", 1, update_modified=False)
    payment_entry.db_set("custom_zatca_advance_tax_invoice", doc.name, update_modified=False)
    payment_entry.db_set("custom_zatca_advance_invoice_status", "Debug XML Created", update_modified=False)
    payment_entry.db_set("custom_zatca_advance_invoice_uuid", doc.zatca_uuid, update_modified=False)
    payment_entry.db_set("custom_zatca_advance_xml", file_url, update_modified=False)
    payment_entry.db_set("custom_zatca_advance_last_debug_at", now_datetime(), update_modified=False)
    payment_entry.db_set("custom_zatca_advance_full_response", "Linked ZATCA Advance Tax Invoice: " + get_link_to_form("ZATCA Advance Tax Invoice", doc.name), update_modified=False)

    return {"payment_entry": payment_entry.name, "advance_tax_invoice": doc.name, "uuid": doc.zatca_uuid, "file_url": file_url, "status": "Debug XML Created"}


@frappe.whitelist()
def finalize_advance_tax_invoice(advance_invoice_name: str) -> dict:
    doc = frappe.get_doc("ZATCA Advance Tax Invoice", advance_invoice_name)
    _run_preflight_or_throw(doc)
    doc.status = "Final"
    if doc.zatca_status in {"Not Submitted", "Preflight Passed"}:
        doc.zatca_status = "Not Submitted"
    doc.save(ignore_permissions=True)
    return {"ok": True, "advance_tax_invoice": doc.name, "status": doc.status, "zatca_status": doc.zatca_status}


@frappe.whitelist()
def send_advance_to_zatca(advance_invoice_name: str) -> dict:
    doc = frappe.get_doc("ZATCA Advance Tax Invoice", advance_invoice_name)
    _run_preflight_or_throw(doc)

    company_doc = frappe.get_doc("Company", doc.company)
    mode = _safe_text(getattr(company_doc, "custom_zatca_advance_payment_submission_mode", "Local Only"))

    signing_enabled = cint(getattr(company_doc, "custom_zatca_advance_signing_enabled", 0))
    api_enabled = cint(getattr(company_doc, "custom_zatca_advance_api_submission_enabled", 0))

    if mode != "Submit to ZATCA":
        frappe.throw(
            _(
                "Company is configured as Local Only for advance payment invoices. "
                "No ZATCA submission will be performed."
            )
        )

    if not signing_enabled:
        frappe.throw(
            _(
                "ZATCA Advance Signing is not enabled for this company. "
                "Enable it only after the signing integration is tested."
            )
        )

    if not api_enabled:
        frappe.throw(
            _(
                "ZATCA Advance API Submission is not enabled for this company. "
                "Enable it only for a real pilot customer after signing/API integration is ready."
            )
        )

    doc.zatca_status = "Failed"
    doc.last_submission_at = now_datetime()
    doc.last_failed_submission_at = now_datetime() if doc.meta.has_field("last_failed_submission_at") else None

    if doc.meta.has_field("submission_attempts"):
        doc.submission_attempts = (doc.submission_attempts or 0) + 1

    doc.full_response = "ZATCA submission for advance payment invoices is not yet wired to the signing/API engine."
    doc.zatca_error_messages = "Signing/API integration is not implemented yet for advance payment invoices." if doc.meta.has_field("zatca_error_messages") else None
    doc.save(ignore_permissions=True)

    frappe.throw(_("ZATCA submission is not implemented yet for advance payment invoices. Signing/API integration must be added in a separate safe step."))


@frappe.whitelist()
def retry_advance_zatca_submission(advance_invoice_name: str) -> dict:
    return send_advance_to_zatca(advance_invoice_name)


def _clear_payment_entry_advance_fields(payment_entry_name: str) -> None:
    if not payment_entry_name or not frappe.db.exists("Payment Entry", payment_entry_name):
        return

    values = {
        "custom_zatca_is_advance_payment": 0,
        "custom_zatca_advance_tax_invoice": "",
        "custom_zatca_advance_invoice_status": "Not Created",
        "custom_zatca_advance_invoice_uuid": "",
        "custom_zatca_advance_xml": "",
        "custom_zatca_advance_last_debug_at": None,
        "custom_zatca_advance_full_response": "",
    }

    meta = frappe.get_meta("Payment Entry")
    for fieldname, value in values.items():
        if meta.has_field(fieldname):
            frappe.db.set_value("Payment Entry", payment_entry_name, fieldname, value, update_modified=False)


def _is_locked_advance_invoice(doc) -> bool:
    return doc.status == "Final" or doc.zatca_status in {"Submitted", "Cleared", "Reported"}


@frappe.whitelist()
def delete_advance_tax_invoice(advance_invoice_name: str) -> dict:
    if not advance_invoice_name:
        frappe.throw(_("ZATCA Advance Tax Invoice name is required."))

    if not frappe.db.exists("ZATCA Advance Tax Invoice", advance_invoice_name):
        return {"deleted": False, "message": "Already deleted."}

    doc = frappe.get_doc("ZATCA Advance Tax Invoice", advance_invoice_name)

    if _is_locked_advance_invoice(doc) and "System Manager" not in frappe.get_roles():
        frappe.throw(_("This ZATCA Advance Tax Invoice is locked because it is Final, Submitted, Cleared, or Reported."))

    payment_entry_name = doc.payment_entry
    _clear_payment_entry_advance_fields(payment_entry_name)

    for file_name in frappe.get_all("File", filters={"attached_to_doctype": "ZATCA Advance Tax Invoice", "attached_to_name": advance_invoice_name}, pluck="name"):
        frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)

    frappe.delete_doc("ZATCA Advance Tax Invoice", advance_invoice_name, ignore_permissions=True, force=True)
    frappe.db.commit()

    return {"deleted": True, "advance_invoice": advance_invoice_name, "payment_entry": payment_entry_name}



def _clear_payment_entry_advance_fields_on_doc(doc) -> None:
    """Clear ZATCA advance fields on an in-memory Payment Entry document."""
    if doc.doctype != "Payment Entry":
        return

    values = {
        "custom_zatca_is_advance_payment": 0,
        "custom_zatca_advance_tax_invoice": "",
        "custom_zatca_advance_invoice_status": "Not Created",
        "custom_zatca_advance_invoice_uuid": "",
        "custom_zatca_advance_xml": "",
        "custom_zatca_advance_last_debug_at": None,
        "custom_zatca_advance_full_response": "",
    }

    meta = frappe.get_meta("Payment Entry")

    for fieldname, value in values.items():
        if meta.has_field(fieldname):
            setattr(doc, fieldname, value)


def cleanup_copied_advance_fields_on_payment_entry_save(doc, event=None):
    """Prevent copied Payment Entries from keeping stale ZATCA advance links.

    A Payment Entry may keep ZATCA advance fields when duplicated from an old
    document before no_copy was enforced. Keep the link only when the linked
    ZATCA Advance Tax Invoice points back to the same Payment Entry.
    """
    if doc.doctype != "Payment Entry":
        return

    meta = frappe.get_meta("Payment Entry")

    if not meta.has_field("custom_zatca_advance_tax_invoice"):
        return

    linked_advance = getattr(doc, "custom_zatca_advance_tax_invoice", None)

    if not linked_advance:
        if meta.has_field("custom_zatca_is_advance_payment") and getattr(doc, "custom_zatca_is_advance_payment", 0):
            _clear_payment_entry_advance_fields_on_doc(doc)
        return

    if not frappe.db.exists("ZATCA Advance Tax Invoice", linked_advance):
        _clear_payment_entry_advance_fields_on_doc(doc)
        return

    linked_payment_entry = frappe.db.get_value(
        "ZATCA Advance Tax Invoice",
        linked_advance,
        "payment_entry",
    )

    if linked_payment_entry != doc.name:
        _clear_payment_entry_advance_fields_on_doc(doc)


@frappe.whitelist()
def repair_payment_entry_advance_metadata_and_copied_links() -> dict:
    """Repair Custom Field properties and clean stale copied Payment Entry links."""
    repaired_custom_fields = []
    cleaned_payment_entries = []
    repaired_docfields = []

    payment_entry_fields = {
        "custom_zatca_is_advance_payment": {
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "description": (
                "Technical marker set automatically when a ZATCA Advance Tax Invoice "
                "is generated from this Payment Entry."
            ),
        },
        "custom_zatca_advance_tax_invoice": {"no_copy": 1, "read_only": 1},
        "custom_zatca_advance_invoice_status": {"no_copy": 1, "read_only": 1},
        "custom_zatca_advance_invoice_uuid": {"no_copy": 1, "read_only": 1},
        "custom_zatca_advance_xml": {"no_copy": 1, "read_only": 1},
        "custom_zatca_advance_last_debug_at": {"no_copy": 1, "read_only": 1},
        "custom_zatca_advance_full_response": {"no_copy": 1, "read_only": 1},
    }

    for fieldname, updates in payment_entry_fields.items():
        custom_field = frappe.db.get_value(
            "Custom Field",
            {"dt": "Payment Entry", "fieldname": fieldname},
            "name",
        )

        if not custom_field:
            continue

        for key, value in updates.items():
            frappe.db.set_value("Custom Field", custom_field, key, value, update_modified=False)

        repaired_custom_fields.append(fieldname)

    zadv_no_copy_fields = {
        "payment_entry",
        "zatca_uuid",
        "status",
        "zatca_status",
        "debug_xml",
        "signed_xml",
        "qr_code",
        "invoice_hash",
        "pih",
        "icv",
        "last_debug_at",
        "full_response",
        "preflight_status",
        "preflight_checked_at",
        "preflight_details",
        "submitted_at",
        "last_submission_at",
        "has_warnings",
        "warning_details",
        "advance_amount",
        "taxable_amount",
        "tax_amount",
        "total_amount",
        "base_taxable_amount",
        "base_tax_amount",
        "base_total_amount",
        "in_words",
        "base_in_words",
        "tax_rate",
        "tax_account",
        "tax_description",
        "tax_category",
        "tax_category_code",
        "company_name",
        "company_name_arabic",
        "company_vat_number",
        "company_address",
        "company_address_line1",
        "company_address_line2",
        "company_city",
        "company_postal_code",
        "company_country",
        "company_country_code",
        "customer_name",
        "customer_name_arabic",
        "customer_vat_number",
        "customer_b2c",
        "customer_buyer_id_type",
        "customer_buyer_id",
        "customer_address",
        "customer_address_line1",
        "customer_address_line2",
        "customer_city",
        "customer_postal_code",
        "customer_country",
        "customer_country_code",
        "mode_of_payment",
        "payment_means_code",
        "company_currency",
        "exchange_rate",
    }

    for fieldname in zadv_no_copy_fields:
        docfield = frappe.db.get_value(
            "DocField",
            {"parent": "ZATCA Advance Tax Invoice", "fieldname": fieldname},
            "name",
        )

        if docfield:
            frappe.db.set_value("DocField", docfield, "no_copy", 1, update_modified=False)
            repaired_docfields.append(fieldname)

    if frappe.get_meta("Payment Entry").has_field("custom_zatca_advance_tax_invoice"):
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters=[["custom_zatca_advance_tax_invoice", "!=", ""]],
            fields=["name", "custom_zatca_advance_tax_invoice"],
        )

        for row in payment_entries:
            linked_advance = row.custom_zatca_advance_tax_invoice

            if not linked_advance or not frappe.db.exists("ZATCA Advance Tax Invoice", linked_advance):
                _clear_payment_entry_advance_fields(row.name)
                cleaned_payment_entries.append(row.name)
                continue

            linked_payment_entry = frappe.db.get_value(
                "ZATCA Advance Tax Invoice",
                linked_advance,
                "payment_entry",
            )

            if linked_payment_entry != row.name:
                _clear_payment_entry_advance_fields(row.name)
                cleaned_payment_entries.append(row.name)

    frappe.clear_cache(doctype="Payment Entry")
    frappe.clear_cache(doctype="ZATCA Advance Tax Invoice")
    frappe.db.commit()

    return {
        "repaired_custom_fields": repaired_custom_fields,
        "repaired_docfields": repaired_docfields,
        "cleaned_payment_entries": cleaned_payment_entries,
    }
