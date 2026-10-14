"""
QR codes for invoices in compliance with Saudi Arabia's ZATCA e-invoicing regulations.
Each invoice has a QR code containing critical data encoded in TLV (Tag-Length-Value) format,
which includes:
1. Seller's Name
2. VAT Number
3. Time Stamp
4. Invoice Amount
5. VAT Amount

The QR code generation follows these steps:
- Verify if the document is relevant for Saudi Arabia based on the company region.
- Check if the required "ksa_einv_qr" field exists in the document.
If not, it fails without changing schema inside the invoice transaction.
- Preserve the current owned QR; unresolved stored references require review.
- Collect required invoice data, validate it, and encode it into the TLV format.
- Convert the TLV data into a Base64 string.
- Generate a QR code image using the `pyqrcode` library and attach it to the document.
"""

import io
import os
from base64 import b64encode

import frappe
from frappe import _
from pyqrcode import create as qr_create

from erpnext import get_region

from zatca_erpgulf.zatca_erpgulf.country import is_saudi_country
from zatca_erpgulf.zatca_erpgulf.qr_timestamp import format_zatca_qr_timestamp
from zatca_erpgulf.zatca_erpgulf.qr_attachment_policy import (
    FILE_FIELDS, MAX_FILE_OBSERVATIONS, QRAttachmentPolicyError, decide_qr_reuse,
)

MISSING_QR_FIELD = "The KSA E-Invoicing QR field is missing. Complete the approved application setup before generating QR codes."
QR_REVIEW_REQUIRED = "Stored QR attachments require review. No file was deleted, relinked or replaced by the QR generator."


def _persist_phase1_qr_metadata(doc, file_url):
    """Stage only QR metadata in the CALLER's invoice transaction.

    No recursive invoice save, permission bypass, modified-time update, commit
    or rollback. One field-dictionary update keeps link/status together without
    invoking full invoice/accounting hooks. The existing File save remains in
    that transaction; its filesystem lifecycle is owned by the framework.
    """
    values = {"ksa_einv_qr": file_url, "custom_zatca_status": "Phase-1 QR Generated"}
    frappe.db.set_value(doc.doctype, doc.name, values, update_modified=False)
    # Mirror only after successful SQL. The parent owns rollback/reload on error.
    doc.ksa_einv_qr = values["ksa_einv_qr"]
    doc.custom_zatca_status = values["custom_zatca_status"]
    # In inspected Frappe 15 this queues realtime after commit; it does not commit.
    doc.notify_update()


def get_company_arabic_name(company_name: str) -> str:
    """
    Return company Arabic name using the required fallback order:
    1. company_name_in_arabic
    2. custom_company_name_in_arabic
    3. custom__company_name_in_arabic__
    """
    meta = frappe.get_meta("Company")
    fallback_fields = [
        "company_name_in_arabic",
        "custom_company_name_in_arabic",
        "custom__company_name_in_arabic__",
    ]

    for fieldname in fallback_fields:
        if meta.get_field(fieldname):
            value = frappe.db.get_value("Company", company_name, fieldname)
            if value:
                return value

    return ""


def _existing_qr_reference(doc):
    """Inspect ordinary Sales/POS links without cleanup, deletion or relinking.

    No relink, first/latest choice, physical existence check or global URL
    fallback. Parent authorization still applies; this is not a public endpoint.
    A scoped File row proves a saved link observation, not valid QR contents.
    """
    rows = frappe.get_all("File",
        filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
        fields=list(FILE_FIELDS), order_by="name asc", limit_page_length=MAX_FILE_OBSERVATIONS + 1)
    try:
        decision = decide_qr_reuse(doctype=doc.doctype, invoice_name=doc.name,
            current_url=doc.get("ksa_einv_qr"), saved_status=doc.get("custom_zatca_status"), rows=tuple(rows))
    except (TypeError, QRAttachmentPolicyError):
        needs_review = True
    else:
        needs_review = decision.action == "REVIEW"
    if needs_review:
        frappe.throw(_(QR_REVIEW_REQUIRED))
    if decision.action == "PRESERVE":
        return doc.get("ksa_einv_qr")
    return None


# Compatibility alias for old internal callers; it no longer performs cleanup.
_cleanup_qr_attachments = _existing_qr_reference


def create_qr_code(doc, method=None):  # pylint: disable=unused-argument
    """Stage a Phase-1 QR without owning the caller's transaction or schema."""
    region = get_region(doc.company)
    if not is_saudi_country(region):
        return

    # Schema setup/DDL belongs to an approved install/migration, never a hook.
    if not hasattr(doc, "ksa_einv_qr"):
        frappe.throw(_(MISSING_QR_FIELD))

    # Preserve only the current same-invoice reference, never auto-clean/relink.
    if _existing_qr_reference(doc):
        return

    meta = frappe.get_meta(doc.doctype)

    if "ksa_einv_qr" in [d.fieldname for d in meta.get_image_fields()]:
        tlv_array = []

        # Seller's Name
        seller_name = get_company_arabic_name(doc.company)

        if not seller_name:
            frappe.throw(
                _(
                    "Arabic name missing for {} in the company document. "
                    "Checked fields: company_name_in_arabic, "
                    "custom_company_name_in_arabic, "
                    "custom__company_name_in_arabic__"
                ).format(doc.company)
            )

        tag = bytes([1]).hex()
        length = bytes([len(seller_name.encode("utf-8"))]).hex()
        value = seller_name.encode("utf-8").hex()
        tlv_array.append("".join([tag, length, value]))

        # VAT Number
        tax_id = frappe.db.get_value("Company", doc.company, "tax_id")
        if not tax_id:
            frappe.throw(
                _("Tax ID missing for {} in the company document").format(doc.company)
            )

        tag = bytes([2]).hex()
        length = bytes([len(tax_id)]).hex()
        value = tax_id.encode("utf-8").hex()
        tlv_array.append("".join([tag, length, value]))

        # Time Stamp
        time_stamp = format_zatca_qr_timestamp(doc.posting_date, doc.posting_time)

        tag = bytes([3]).hex()
        length = bytes([len(time_stamp)]).hex()
        value = time_stamp.encode("utf-8").hex()
        tlv_array.append("".join([tag, length, value]))

        # Invoice Amount
        invoice_amount = str(doc.base_grand_total)
        tag = bytes([4]).hex()
        length = bytes([len(invoice_amount)]).hex()
        value = invoice_amount.encode("utf-8").hex()
        tlv_array.append("".join([tag, length, value]))

        # VAT Amount
        vat_amount = str(doc.total_taxes_and_charges)
        tag = bytes([5]).hex()
        length = bytes([len(vat_amount)]).hex()
        value = vat_amount.encode("utf-8").hex()
        tlv_array.append("".join([tag, length, value]))

        # Join bytes into one buffer
        tlv_buff = "".join(tlv_array)

        # Base64 conversion for QR Code
        base64_string = b64encode(bytes.fromhex(tlv_buff)).decode()

        qr_image = io.BytesIO()
        url = qr_create(base64_string, error="L")
        url.png(qr_image, scale=4, quiet_zone=4)

        # Make file
        filename = f"QR-Phase1-{doc.name}.png".replace(os.path.sep, "__")
        _file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": filename,
                "is_private": 0,
                "content": qr_image.getvalue(),
                "attached_to_doctype": doc.get("doctype"),
                "attached_to_name": doc.get("name"),
                "attached_to_field": "ksa_einv_qr",
            }
        )

        _file.save()

        _persist_phase1_qr_metadata(doc, _file.file_url)
