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

import frappe
from frappe import _
from pyqrcode import create as qr_create

from erpnext import get_region
from zatca_erpgulf.ksa_compliance.qr_amounts import QRAmountError, REVIEW, phase1_document_amounts
from zatca_erpgulf.ksa_compliance.party_names import display_aliases, first_available_name
from zatca_erpgulf.zatca_erpgulf.template_vat_source import fail_declared_vat

from zatca_erpgulf.zatca_erpgulf.country import is_saudi_country
from zatca_erpgulf.zatca_erpgulf.qr_timestamp import format_zatca_qr_timestamp
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import PHASE_2_VALUE, resolve_zatca_phase
from zatca_erpgulf.zatca_erpgulf.qr_encoding import (
    PHASE1_QR_VALUE_ERROR, Phase1QREncodingError, encode_phase1_qr,
)
from zatca_erpgulf.zatca_erpgulf.qr_attachment_policy import (
    FILE_FIELDS, MAX_FILE_OBSERVATIONS, QRAttachmentPolicyError, decide_qr_reuse,
)

MISSING_QR_FIELD = "The KSA E-Invoicing QR field is missing. Complete the approved application setup before generating QR codes."
QR_REVIEW_REQUIRED = "Stored QR attachments require review. No file was deleted, relinked or replaced by the QR generator."
SELLER_REVIEW = "The Company seller details are incomplete. Review the Arabic name and Tax ID before generating the ZATCA QR code."


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
    """Compatibility reader with the same display order and raw text policy.

    Schema-first alias readers are deliberately different. This wrapper is not
    used by the QR generator, which reads name and VAT from one loaded Company.
    """
    company = frappe.get_doc("Company", company_name)
    meta = frappe.get_meta("Company")
    return first_available_name(display_aliases("company_arabic_name"),
        has_field=meta.get_field, read=company.get, mode="qr")


def phase1_seller_identity(company, *, runtime, translate, allow_english=False):
    """Read one Company's display name/VAT without lookup, conversion or writes.

    Ordinary QR requires Arabic. The initial-advance adapter retains its English
    fallback, now only after all three registered Arabic aliases. These scalar
    observations do not prove saved-record, certificate or taxpayer provenance.
    """
    meta = runtime.get_meta("Company")
    seller = first_available_name(display_aliases("company_arabic_name"),
        has_field=meta.get_field, read=company.get, mode="qr")
    if not seller and allow_english:
        seller = company.get("company_name")
    vat = company.get("tax_id")
    missing = []
    if not seller:
        missing.append("seller name")
    if not vat:
        missing.append("Tax ID")
    if missing:
        fail_declared_vat(runtime, translate, "qr_seller_details_missing", SELLER_REVIEW,
            details="Missing: " + "; ".join(missing) + ".")
    return seller, vat


def _existing_qr_reference(doc):
    """Inspect Sales/POS links without cleanup, deletion or relinking.

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


def checked_phase1_amounts(doc, *, runtime, translate):
    """One localized source failure shared by ordinary and initial-advance QR."""
    try:
        return phase1_document_amounts(doc)
    except QRAmountError as error:
        fail_declared_vat(runtime, translate, error.code, REVIEW)


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
        # One loaded Company supplies both values; no per-alias/VAT SQL reads.
        company = frappe.get_doc("Company", doc.company)
        if resolve_zatca_phase(company) == PHASE_2_VALUE:
            # A disabled integration does not authorize a Phase-1 substitute.
            return
        seller_name, tax_id = phase1_seller_identity(company, runtime=frappe, translate=_)

        # Time Stamp
        time_stamp = format_zatca_qr_timestamp(doc.posting_date, doc.posting_time)

        amounts = checked_phase1_amounts(doc, runtime=frappe, translate=_)
        invoice_amount, vat_amount = amounts.invoice_total, amounts.vat_total
        try:
            base64_string = encode_phase1_qr(
                seller_name=seller_name, vat_number=tax_id, timestamp=time_stamp,
                invoice_total=invoice_amount, vat_total=vat_amount,
            )
        except Phase1QREncodingError as error:
            invalid_tag = error.tag
        else:
            invalid_tag = None
        if invalid_tag is not None:
            frappe.throw(_(PHASE1_QR_VALUE_ERROR).format(invalid_tag))

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
