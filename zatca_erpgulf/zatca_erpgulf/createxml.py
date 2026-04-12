"""
This module contains utilities for ZATCA 2024 e-invoicing.
Includes functions for XML parsing, API interactions, and custom handling.
"""

import re
import uuid
import unicodedata
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from frappe import _
import frappe
from frappe.utils.data import get_time
from frappe.utils import cint
from zatca_erpgulf.zatca_erpgulf.country_code import country_code_mapping

CBC_ID = "cbc:ID"
DS_TRANSFORM = "ds:Transform"


def _abs_rounded(value, precision=2):
    """Safely convert numeric values to absolute rounded floats."""
    try:
        return abs(round(float(value or 0.0), precision))
    except (TypeError, ValueError):
        return 0.0


def _has_document_discount(sales_invoice_doc):
    """Return True when the invoice carries a document-level discount value."""
    return (
        _abs_rounded(getattr(sales_invoice_doc, "discount_amount", 0.0), 6) > 0
        or _abs_rounded(getattr(sales_invoice_doc, "base_discount_amount", 0.0), 6) > 0
    )


def _use_line_net_amounts_discount_model(sales_invoice_doc):
    """
    Decide whether XML should rely on line net amounts instead of a document-level
    AllowanceCharge.

    This returns True when either:
    - an explicit custom flag `custom_zatca_use_line_net_amounts` is enabled, or
    - the invoice has a document-level discount and the item lines already carry
      distributed net values / line discounts that reflect that discount.
    """
    try:
        if cint(getattr(sales_invoice_doc, "custom_zatca_use_line_net_amounts", 0)) == 1:
            return True
    except Exception:
        pass

    if not _has_document_discount(sales_invoice_doc):
        return False

    total_gross = 0.0
    total_net = 0.0
    has_line_level_discount_effect = False

    for item in getattr(sales_invoice_doc, "items", []) or []:
        gross_value = item.base_amount if sales_invoice_doc.currency == "SAR" else item.amount
        net_value = (
            item.base_net_amount if sales_invoice_doc.currency == "SAR" else item.net_amount
        )
        gross_value = _abs_rounded(gross_value, 6)
        net_value = _abs_rounded(net_value, 6)

        total_gross += gross_value
        total_net += net_value

        distributed_discount = _abs_rounded(
            getattr(item, "distributed_discount_amount", 0.0), 6
        )
        line_discount = _abs_rounded(getattr(item, "discount_amount", 0.0), 6)

        if distributed_discount > 0 or line_discount > 0 or abs(gross_value - net_value) > 0.000001:
            has_line_level_discount_effect = True

    return has_line_level_discount_effect and abs(total_gross - total_net) > 0.000001


def get_icv_code(invoice_number):
    """
    Extracts the numeric part from the invoice number to generate the ICV code.
    """
    try:
        icv_code = re.sub(
            r"\D", "", invoice_number
        )  # taking the number part only  from doc name
        return icv_code
    except TypeError as e:
        frappe.throw(_("Type error in getting ICV number: " + str(e)))
        return None
    except re.error as e:
        frappe.throw(_("Regex error in getting ICV number: " + str(e)))
        return None


def get_issue_time(invoice_number):
    """
    Extracts and formats the posting time of a Sales Invoice as HH:MM:SS.
    """
    doc = frappe.get_doc("Sales Invoice", invoice_number)
    time = get_time(doc.posting_time)
    issue_time = time.strftime("%H:%M:%S")  # time in format of  hour,mints,secnds
    return issue_time




def _get_customer_address(sales_invoice_doc, customer_doc):
    """Return customer address doc when available, otherwise None."""
    address = None
    if int(frappe.__version__.split(".", maxsplit=1)[0]) == 13:
        if getattr(sales_invoice_doc, "customer_address", None):
            address = frappe.get_doc("Address", sales_invoice_doc.customer_address)
    else:
        if getattr(customer_doc, "customer_primary_address", None):
            address = frappe.get_doc("Address", customer_doc.customer_primary_address)
    return address


def _get_customer_country_code(sales_invoice_doc, customer_doc, address=None):
    """Resolve customer country code from address; default blank/missing to SA."""
    country_dict = country_code_mapping()

    if address is None:
        address = _get_customer_address(sales_invoice_doc, customer_doc)

    country_name = None
    if address and getattr(address, "country", None):
        country_name = str(address.country).strip()

    if not country_name:
        return "SA"

    mapped = country_dict.get(country_name.lower())
    return mapped or "SA"


def _is_export_invoice(sales_invoice_doc, customer_doc=None, address=None):
    """
    Treat invoice as export only when:
    1) the explicit export checkbox is enabled, and
    2) the customer country is outside Saudi Arabia.

    If the export checkbox is enabled while the customer country resolves to SA,
    stop processing and show a clear validation error.
    """
    export_checked = cint(getattr(sales_invoice_doc, "custom_zatca_export_invoice", 0)) == 1
    if not export_checked:
        return False

    if customer_doc is None:
        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)

    country_code = _get_customer_country_code(sales_invoice_doc, customer_doc, address)
    country_code = (country_code or "SA").upper()

    if country_code == "SA":
        frappe.throw(
            _(
                'ZATCA Export Invoice cannot be enabled when the customer country is Saudi Arabia. '
                'Please disable "ZATCA Export Invoice" or select a customer address outside Saudi Arabia.'
            )
        )

    return True


def _first_available_value(doc, fieldnames):
    """Return first non-empty value from the given field list when the field exists."""
    meta = frappe.get_meta(doc.doctype)
    for fieldname in fieldnames:
        if meta.get_field(fieldname):
            value = getattr(doc, fieldname, None)
            if value is not None:
                value = str(value).strip()
                if value:
                    return value
    return ""


# Common corporate suffixes/noise to ignore in high-similarity comparison.
_NAME_NOISE_WORDS = {
    "company", "co", "co.", "corp", "corporation", "inc", "inc.", "ltd", "ltd.",
    "llc", "llp", "est", "est.", "factory", "trading", "group", "holding", "holdings",
    " المؤسسة", "شركة", "شركه", "مؤسسة", "مؤسسه", "محددودة", "محدودة", "ذ", "م", "م.",
}


def _normalize_name_for_similarity(value):
    """Normalize text so cosmetic differences do not create duplicate PartyName entries."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).lower().strip()
    value = re.sub(r"[ـ]", "", value)
    value = re.sub(r"[^\w\s؀-ۿ]", " ", value)
    tokens = [token for token in value.split() if token and token not in _NAME_NOISE_WORDS]
    return " ".join(tokens)


def _script_type(value):
    """Return rough script bucket for text: arabic, latin, mixed, or other."""
    if not value:
        return "other"
    has_arabic = bool(re.search(r"[؀-ۿ]", value))
    has_latin = bool(re.search(r"[A-Za-z]", value))
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "arabic"
    if has_latin:
        return "latin"
    return "other"


def _names_are_highly_similar(name1, name2, threshold=0.90):
    """Treat two names as duplicates when they differ only cosmetically.

    Arabic-vs-English representations are kept as separate names by default because
    text similarity alone is not reliable across scripts.
    """
    if not name1 or not name2:
        return False

    normalized_1 = _normalize_name_for_similarity(name1)
    normalized_2 = _normalize_name_for_similarity(name2)

    if not normalized_1 or not normalized_2:
        return False

    if normalized_1 == normalized_2:
        return True

    script_1 = _script_type(normalized_1)
    script_2 = _script_type(normalized_2)
    if script_1 != script_2 and {script_1, script_2} == {"arabic", "latin"}:
        return False

    return SequenceMatcher(None, normalized_1, normalized_2).ratio() >= threshold


def _deduplicate_names(names):
    """Keep names in order, dropping blanks and near-duplicates."""
    unique_names = []
    for name in names:
        clean_name = str(name or "").strip()
        if not clean_name:
            continue
        if any(_names_are_highly_similar(clean_name, existing) for existing in unique_names):
            continue
        unique_names.append(clean_name)
    return unique_names


def _get_company_display_names(company_doc, sales_invoice_doc=None):
    """Return supplier names in preferred order: Arabic first, then English if distinct."""
    arabic_name = _first_available_value(
        company_doc,
        [
            "company_name_in_arabic",
            "custom_company_name_in_arabic",
            "custom__company_name_in_arabic__",
        ],
    )
    english_name = str(getattr(company_doc, "company_name", "") or getattr(sales_invoice_doc, "company", "") or "").strip()
    return _deduplicate_names([arabic_name, english_name])


def _get_customer_display_names(customer_doc):
    """Return customer names in preferred order: Arabic first, then English if distinct."""
    arabic_name = _first_available_value(
        customer_doc,
        [
            "customer_name_in_arabic",
            "custom_customer_name_in_arabic",
            "zatca_customer_name_in_arabic",
        ],
    )
    english_name = str(getattr(customer_doc, "customer_name", "") or "").strip()
    return _deduplicate_names([arabic_name, english_name])


def _append_party_names(party_element, names):
    """Append one or more cac:PartyName/cbc:Name nodes in the given order."""
    for name in _deduplicate_names(names):
        cac_party_name = ET.SubElement(party_element, "cac:PartyName")
        cbc_name = ET.SubElement(cac_party_name, "cbc:Name")
        cbc_name.text = name

def billing_reference_for_credit_and_debit_note(invoice, sales_invoice_doc):
    """
    Adds billing reference details for credit and debit notes to the invoice XML.
    """
    try:
        # details of original invoice
        cac_billingreference = ET.SubElement(invoice, "cac:BillingReference")
        cac_invoicedocumentreference = ET.SubElement(
            cac_billingreference, "cac:InvoiceDocumentReference"
        )
        cbc_id13 = ET.SubElement(cac_invoicedocumentreference, CBC_ID)
        cbc_id13.text = (
            sales_invoice_doc.return_against
        )  # field from return against invoice.

        return invoice
    except (ValueError, KeyError, AttributeError) as error:
        frappe.throw(
            _(
                f"Error occurred while adding billing reference for credit/debit note: {str(error)}"
            )
        )
        return None


def xml_tags():
    """
    Creates an XML Invoice document with UBL, XAdES, and digital signature elements.
    """
    try:
        invoice = ET.Element(
            "Invoice", xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
        )
        invoice.set(
            "xmlns:cac",
            "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        )
        invoice.set(
            "xmlns:cbc",
            "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        )
        invoice.set(
            "xmlns:ext",
            "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
        )
        ubl_extensions = ET.SubElement(invoice, "ext:UBLExtensions")
        ubl_extension = ET.SubElement(ubl_extensions, "ext:UBLExtension")
        extension_uri = ET.SubElement(ubl_extension, "ext:ExtensionURI")
        extension_uri.text = "urn:oasis:names:specification:ubl:dsig:enveloped:xades"
        extension_content = ET.SubElement(ubl_extension, "ext:ExtensionContent")
        ubl_document_signatures = ET.SubElement(
            extension_content, "sig:UBLDocumentSignatures"
        )
        ubl_document_signatures.set(
            "xmlns:sig",
            "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
        )
        ubl_document_signatures.set(
            "xmlns:sac",
            "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
        )
        ubl_document_signatures.set(
            "xmlns:sbc",
            "urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2",
        )
        signature_information = ET.SubElement(
            ubl_document_signatures, "sac:SignatureInformation"
        )
        invoice_id = ET.SubElement(signature_information, CBC_ID)
        invoice_id.text = "urn:oasis:names:specification:ubl:signature:1"
        referenced_signatureid = ET.SubElement(
            signature_information, "sbc:ReferencedSignatureID"
        )
        referenced_signatureid.text = (
            "urn:oasis:names:specification:ubl:signature:Invoice"
        )
        signature = ET.SubElement(signature_information, "ds:Signature")
        signature.set("Id", "signature")
        signature.set("xmlns:ds", "http://www.w3.org/2000/09/xmldsig#")
        signed_info = ET.SubElement(signature, "ds:SignedInfo")
        canonicalization_method = ET.SubElement(
            signed_info, "ds:CanonicalizationMethod"
        )
        canonicalization_method.set("Algorithm", "http://www.w3.org/2006/12/xml-c14n11")
        signature_method = ET.SubElement(signed_info, "ds:SignatureMethod")
        signature_method.set(
            "Algorithm", "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
        )
        reference = ET.SubElement(signed_info, "ds:Reference")
        reference.set("Id", "invoiceSignedData")
        reference.set("URI", "")
        transforms = ET.SubElement(reference, "ds:Transforms")
        transform = ET.SubElement(transforms, DS_TRANSFORM)
        transform.set("Algorithm", "http://www.w3.org/TR/1999/REC-xpath-19991116")
        xpath = ET.SubElement(transform, "ds:XPath")
        xpath.text = "not(//ancestor-or-self::ext:UBLExtensions)"
        transform2 = ET.SubElement(transforms, DS_TRANSFORM)
        transform2.set("Algorithm", "http://www.w3.org/TR/1999/REC-xpath-19991116")
        xpath2 = ET.SubElement(transform2, "ds:XPath")
        xpath2.text = "not(//ancestor-or-self::cac:Signature)"
        transform3 = ET.SubElement(transforms, DS_TRANSFORM)
        transform3.set("Algorithm", "http://www.w3.org/TR/1999/REC-xpath-19991116")
        xpath3 = ET.SubElement(transform3, "ds:XPath")
        xpath3.text = (
            "not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])"
        )
        transform4 = ET.SubElement(transforms, DS_TRANSFORM)
        transform4.set("Algorithm", "http://www.w3.org/2006/12/xml-c14n11")
        diges_method = ET.SubElement(reference, "ds:DigestMethod")
        diges_method.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
        diges_value = ET.SubElement(reference, "ds:DigestValue")
        diges_value.text = "O/vEnAxjLAlw8kQUy8nq/5n8IEZ0YeIyBFvdQA8+iFM="
        reference2 = ET.SubElement(signed_info, "ds:Reference")
        reference2.set("URI", "#xadesSignedProperties")
        reference2.set("Type", "http://www.w3.org/2000/09/xmldsig#SignatureProperties")
        digest_method1 = ET.SubElement(reference2, "ds:DigestMethod")
        digest_method1.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
        digest_value1 = ET.SubElement(reference2, "ds:DigestValue")
        digest_value1.text = "YjQwZmEyMjM2NDU1YjQwNjM5MTFmYmVkO="
        signature_value = ET.SubElement(signature, "ds:SignatureValue")
        signature_value.text = "MEQCIDGBRHiPo6yhXIQ9df6pMEkufcGnoqYaS+O8Jn"
        keyinfo = ET.SubElement(signature, "ds:KeyInfo")
        x509data = ET.SubElement(keyinfo, "ds:X509Data")
        x509certificate = ET.SubElement(x509data, "ds:X509Certificate")
        x509certificate.text = (
            "MIID6TCCA5CgAwIBAgITbwAAf8tem6jngr16DwABAAB/yzAKBggqhkjOPQQ"
        )
        object_data = ET.SubElement(signature, "ds:Object")
        qualifyingproperties = ET.SubElement(object_data, "xades:QualifyingProperties")
        qualifyingproperties.set("Target", "signature")
        qualifyingproperties.set("xmlns:xades", "http://uri.etsi.org/01903/v1.3.2#")
        signedproperties = ET.SubElement(qualifyingproperties, "xades:SignedProperties")
        signedproperties.set("Id", "xadesSignedProperties")
        signedsignatureproperties = ET.SubElement(
            signedproperties, "xades:SignedSignatureProperties"
        )
        signingtime = ET.SubElement(signedsignatureproperties, "xades:SigningTime")
        signingtime.text = "2024-01-24T11:36:34Z"
        signingcertificate = ET.SubElement(
            signedsignatureproperties, "xades:SigningCertificate"
        )
        cert = ET.SubElement(signingcertificate, "xades:Cert")
        certdigest = ET.SubElement(cert, "xades:CertDigest")
        digest_method2 = ET.SubElement(certdigest, "ds:DigestMethod")
        digest_value2 = ET.SubElement(certdigest, "ds:DigestValue")
        digest_method2.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
        digest_value2.text = "YTJkM2JhYTcwZTBhZTAxOGYwODMyNzY3"
        issuerserial = ET.SubElement(cert, "xades:IssuerSerial")
        x509issuername = ET.SubElement(issuerserial, "ds:X509IssuerName")
        x509serialnumber = ET.SubElement(issuerserial, "ds:X509SerialNumber")
        x509issuername.text = "CN=TSZEINVOICE-SubCA-1, DC=extgazt, DC=gov, DC=local"
        x509serialnumber.text = "2475382886904809774818644480820936050208702411"
        return invoice
    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Error in XML tags formation: {e}"))
        return None


def salesinvoice_data(invoice, invoice_number):
    """
    Populates the Sales Invoice XML with key elements and metadata.
    """
    try:
        sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)

        cbc_profile_id = ET.SubElement(invoice, "cbc:ProfileID")
        cbc_profile_id.text = "reporting:1.0"

        cbc_id = ET.SubElement(invoice, CBC_ID)
        cbc_id.text = str(sales_invoice_doc.name)

        cbc_uuid = ET.SubElement(invoice, "cbc:UUID")
        cbc_uuid.text = str(uuid.uuid1())
        uuid1 = cbc_uuid.text

        cbc_issue_date = ET.SubElement(invoice, "cbc:IssueDate")
        cbc_issue_date.text = str(sales_invoice_doc.posting_date)

        cbc_issue_time = ET.SubElement(invoice, "cbc:IssueTime")
        cbc_issue_time.text = get_issue_time(invoice_number)

        return invoice, uuid1, sales_invoice_doc
    except (AttributeError, ValueError, frappe.ValidationError) as e:
        frappe.throw(_(("Error occurred in SalesInvoice data: " f"{str(e)}")))
        return None


def invoice_typecode_compliance(invoice, compliance_type):
    """
    Creates and populates XML tags for a UBL Invoice document.
    """

    # 0 is default. Not for compliance test. But normal reporting or clearance call.
    # 1 is for compliance test. Simplified invoice
    # 2 is for compliance test. Standard invoice
    # 3 is for compliance test. Simplified Credit Note
    # 4 is for compliance test. Standard Credit Note
    # 5 is for compliance test. Simplified Debit Note
    # 6 is for compliance test. Standard Debit Note
    # frappe.throw(str("here 5 " + str(compliance_type)))
    try:

        if compliance_type == "1":  # simplified invoice
            cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
            cbc_invoicetypecode.set("name", "0200000")
            cbc_invoicetypecode.text = "388"

        elif compliance_type == "2":  # standard invoice
            cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
            cbc_invoicetypecode.set("name", "0100000")
            cbc_invoicetypecode.text = "388"

        elif compliance_type == "3":  # simplified Credit note
            cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
            cbc_invoicetypecode.set("name", "0200000")
            cbc_invoicetypecode.text = "381"

        elif compliance_type == "4":  # Standard Credit note
            cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
            cbc_invoicetypecode.set("name", "0100000")
            cbc_invoicetypecode.text = "381"

        elif compliance_type == "5":  # simplified Debit note
            cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
            cbc_invoicetypecode.set("name", "0211000")
            cbc_invoicetypecode.text = "383"

        elif compliance_type == "6":  # Standard Debit note
            cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
            cbc_invoicetypecode.set("name", "0100000")
            cbc_invoicetypecode.text = "383"
        return invoice

    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Error occurred in compliance typecode: {e}"))
        return None


def invoice_typecode_simplified(invoice, sales_invoice_doc):
    """
    Sets the InvoiceTypeCode for a simplified invoice based on sales invoice document attributes.
    Export flag is derived from customer country, not the custom checkbox.
    """
    try:
        cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
        base_code = "02"
        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        export_flag = _is_export_invoice(sales_invoice_doc, customer_doc)
        checkbox_map = [
            bool(getattr(sales_invoice_doc, "custom_zatca_third_party_invoice", 0)),
            bool(getattr(sales_invoice_doc, "custom_zatca_nominal_invoice", 0)),
            export_flag,
            bool(getattr(sales_invoice_doc, "custom_summary_invoice", 0)),
            bool(getattr(sales_invoice_doc, "custom_self_billed_invoice", 0)),
        ]
        five_digit_code = "".join("1" if checkbox else "0" for checkbox in checkbox_map)
        final_code = base_code + five_digit_code
        if sales_invoice_doc.is_return == 1:
            cbc_invoicetypecode.set("name", final_code)
            cbc_invoicetypecode.text = "381"
        elif getattr(sales_invoice_doc, "is_debit_note", 0) == 1:
            cbc_invoicetypecode.set("name", final_code)
            cbc_invoicetypecode.text = "383"
        else:
            cbc_invoicetypecode.set("name", final_code)
            cbc_invoicetypecode.text = "388"

        return invoice
    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Error occurred in simplified invoice typecode: {e}"))
        return None


def invoice_typecode_standard(invoice, sales_invoice_doc):
    """
    Sets the InvoiceTypeCode for a standard invoice based on sales invoice document attributes.
    Export flag is derived from customer country, not the custom checkbox.
    """
    try:
        cbc_invoicetypecode = ET.SubElement(invoice, "cbc:InvoiceTypeCode")
        base_code = "01"
        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        export_flag = _is_export_invoice(sales_invoice_doc, customer_doc)
        checkbox_map = [
            bool(getattr(sales_invoice_doc, "custom_zatca_third_party_invoice", 0)),
            bool(getattr(sales_invoice_doc, "custom_zatca_nominal_invoice", 0)),
            export_flag,
            bool(getattr(sales_invoice_doc, "custom_summary_invoice", 0)),
            bool(getattr(sales_invoice_doc, "custom_self_billed_invoice", 0)),
        ]

        five_digit_code = "".join("1" if checkbox else "0" for checkbox in checkbox_map)
        final_code = base_code + five_digit_code
        if sales_invoice_doc.is_return == 1:
            cbc_invoicetypecode.set("name", final_code)
            cbc_invoicetypecode.text = "381"
        elif getattr(sales_invoice_doc, "is_debit_note", 0) == 1:
            cbc_invoicetypecode.set("name", final_code)
            cbc_invoicetypecode.text = "383"
        else:
            cbc_invoicetypecode.set("name", final_code)
            cbc_invoicetypecode.text = "388"

        return invoice
    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Error in standard invoice type code: {e}"))
        return None


def doc_reference(invoice, sales_invoice_doc, invoice_number):
    """
    Adds document reference elements to the XML invoice,
    including currency codes and additional document references.
    """
    try:
        cbc_documentcurrencycode = ET.SubElement(invoice, "cbc:DocumentCurrencyCode")
        cbc_documentcurrencycode.text = sales_invoice_doc.currency
        cbc_taxcurrencycode = ET.SubElement(invoice, "cbc:TaxCurrencyCode")
        cbc_taxcurrencycode.text ="SAR" # SAR is as zatca requires tax amount in SAR
        # if sales_invoice_doc.is_return == 1:
        if sales_invoice_doc.is_return == 1 or sales_invoice_doc.is_debit_note == 1:
            invoice = billing_reference_for_credit_and_debit_note(
                invoice, sales_invoice_doc
            )
        cac_additionaldocumentreference = ET.SubElement(
            invoice, "cac:AdditionalDocumentReference"
        )
        cbc_id_1 = ET.SubElement(cac_additionaldocumentreference, CBC_ID)
        cbc_id_1.text = "ICV"
        cbc_uuid_1 = ET.SubElement(cac_additionaldocumentreference, "cbc:UUID")
        cbc_uuid_1.text = str(get_icv_code(invoice_number))
        return invoice
    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Error occurred in reference doc: {e}"))
        return None


def doc_reference_compliance(
    invoice, sales_invoice_doc, invoice_number, compliance_type
):
    """
    Adds document reference elements to the XML invoice, including currency codes,
    billing references,and additional document references.
    """
    try:
        cbc_documentcurrencycode = ET.SubElement(invoice, "cbc:DocumentCurrencyCode")
        cbc_documentcurrencycode.text = sales_invoice_doc.currency
        cbc_taxcurrencycode = ET.SubElement(invoice, "cbc:TaxCurrencyCode")
        cbc_taxcurrencycode.text = "SAR"

        if compliance_type in {"3", "4", "5", "6"}:
            cac_billingreference = ET.SubElement(invoice, "cac:BillingReference")
            cac_invoicedocumentreference = ET.SubElement(
                cac_billingreference, "cac:InvoiceDocumentReference"
            )
            cbc_id13 = ET.SubElement(cac_invoicedocumentreference, CBC_ID)
            cbc_id13.text = "6666666"  # field from return against invoice.

        cac_additionaldocumentreference = ET.SubElement(
            invoice, "cac:AdditionalDocumentReference"
        )
        cbc_id_1 = ET.SubElement(cac_additionaldocumentreference, CBC_ID)
        cbc_id_1.text = "ICV"
        cbc_uuid_1 = ET.SubElement(cac_additionaldocumentreference, "cbc:UUID")
        cbc_uuid_1.text = str(get_icv_code(invoice_number))
        return invoice
    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Error occurred in reference doc: {e}"))
        return None


def get_pih_for_company(pih_data, company_name):
    """
    Retrieves the PIH for a specific company from the provided data.
    """
    try:
        for entry in pih_data.get("data", []):
            if entry.get("company") == company_name:
                return entry.get("pih")

        frappe.throw(
            _(f"Error while retrieving PIH of company '{company_name}' for production.")
        )
        return None  # Ensures consistent return
    except (KeyError, AttributeError, ValueError) as e:
        frappe.throw(
            _(f"Error in getting PIH of company '{company_name}' for production: {e}")
        )
        return None  # Ensures consistent return


def additional_reference(invoice, company_abbr, sales_invoice_doc):
    """
    Adds additional document references to the XML invoice for PIH, QR, and Signature elements.
    """
    try:
        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)

        # Create the first AdditionalDocumentReference element for PIH
        cac_additionaldocumentreference2 = ET.SubElement(
            invoice, "cac:AdditionalDocumentReference"
        )
        cbc_id_1_1 = ET.SubElement(cac_additionaldocumentreference2, CBC_ID)
        cbc_id_1_1.text = "PIH"
        cac_attachment = ET.SubElement(
            cac_additionaldocumentreference2, "cac:Attachment"
        )
        cbc_embeddeddocumentbinaryobject = ET.SubElement(
            cac_attachment, "cbc:EmbeddedDocumentBinaryObject"
        )
        cbc_embeddeddocumentbinaryobject.set("mimeCode", "text/plain")

        # Directly retrieve the PIH data without JSON parsing
        # pih = company_doc.custom_pih  # Assuming this is already in the correct format
        if sales_invoice_doc.custom_zatca_pos_name:
            zatca_settings = frappe.get_doc(
                "ZATCA Multiple Setting", sales_invoice_doc.custom_zatca_pos_name
            )
            if zatca_settings.custom__use_company_certificate__keys != 1:
                pih = zatca_settings.custom_pih
            else:
                linked_doc = frappe.get_doc("Company", zatca_settings.custom_linked_doctype)
                pih = linked_doc.custom_pih
        else:
            pih = company_doc.custom_pih
        cbc_embeddeddocumentbinaryobject.text = pih

        # Create the second AdditionalDocumentReference element for QR
        cac_additionaldocumentreference22 = ET.SubElement(
            invoice, "cac:AdditionalDocumentReference"
        )
        cbc_id_1_12 = ET.SubElement(cac_additionaldocumentreference22, CBC_ID)
        cbc_id_1_12.text = "QR"
        cac_attachment22 = ET.SubElement(
            cac_additionaldocumentreference22, "cac:Attachment"
        )
        cbc_embeddeddocumentbinaryobject22 = ET.SubElement(
            cac_attachment22, "cbc:EmbeddedDocumentBinaryObject"
        )
        cbc_embeddeddocumentbinaryobject22.set("mimeCode", "text/plain")
        cbc_embeddeddocumentbinaryobject22.text = (
            "GsiuvGjvchjbFhibcDhjv1886G"  # Example QR code
        )
        cac_sign = ET.SubElement(invoice, "cac:Signature")
        cbc_id_sign = ET.SubElement(cac_sign, CBC_ID)
        cbc_method_sign = ET.SubElement(cac_sign, "cbc:SignatureMethod")
        cbc_id_sign.text = "urn:oasis:names:specification:ubl:signature:Invoice"
        cbc_method_sign.text = "urn:oasis:names:specification:ubl:dsig:enveloped:xades"

        return invoice

    except (ET.ParseError, AttributeError, ValueError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error occurred in additional references: {e}"))
        return None


def get_address(sales_invoice_doc, company_doc):
    """
    Fetches the appropriate address for the invoice.
    - If company_doc.custom_costcenter is 1, use the Cost Center's address.
    - If a cost center is selected but has no address, an error is raised.
    - Otherwise, use the first available company address.
    """
    if company_doc.custom_costcenter == 1 and sales_invoice_doc.cost_center:
        cost_center_doc = frappe.get_doc("Cost Center", sales_invoice_doc.cost_center)

        # Ensure the Cost Center has a linked address
        if not cost_center_doc.custom_zatca_branch_address:
            frappe.throw(
                _(
                    f"No address is set for the selected Cost Center: {cost_center_doc.name}. Please add an address."
                )
            )

        address_list = frappe.get_all(
            "Address",
            fields=[
                "address_line1",
                "address_line2",
                "custom_building_number",
                "city",
                "pincode",
                "state",
                "country",
            ],
            filters={"name": cost_center_doc.custom_zatca_branch_address},
        )

        if not address_list:
            frappe.throw(
                f"ZATCA requires a proper address. Please add an address for Cost Center: {cost_center_doc.name}."
            )

        return address_list[0]  # Return the Cost Center's address

    # Fetch Company address only if no cost center is used
    address_list = frappe.get_all(
        "Address",
        fields=[
            "address_line1",
            "address_line2",
            "custom_building_number",
            "city",
            "pincode",
            "state",
            "country",
        ],
        filters={"is_your_company_address": 1},
    )

    if not address_list:
        frappe.throw(_("requires a proper company address. Please add an address"))

    for address in address_list:
        return address


def company_data(invoice, sales_invoice_doc):
    """
    Adds company data elements to the XML invoice, including supplier details, address,
    tax information, and multilingual supplier names when available.
    """
    try:
        company_doc = frappe.get_doc("Company", sales_invoice_doc.company)
        if company_doc.custom_costcenter == 1 and not sales_invoice_doc.cost_center:
            frappe.throw(_("no Cost Center is set in the invoice.Give the feild"))

        # Determine whether to fetch data from Cost Center or Company
        if company_doc.custom_costcenter == 1 and sales_invoice_doc.cost_center:
            cost_center_doc = frappe.get_doc("Cost Center", sales_invoice_doc.cost_center)
            custom_registration_type = cost_center_doc.custom_zatca__registration_type
            custom_company_registration = cost_center_doc.custom_zatca__registration_number
        else:
            custom_registration_type = company_doc.custom_registration_type
            custom_company_registration = company_doc.custom_company_registration

        cac_accountingsupplierparty = ET.SubElement(invoice, "cac:AccountingSupplierParty")
        cac_party_1 = ET.SubElement(cac_accountingsupplierparty, "cac:Party")
        cac_partyidentification = ET.SubElement(cac_party_1, "cac:PartyIdentification")
        cbc_id_2 = ET.SubElement(cac_partyidentification, CBC_ID)
        cbc_id_2.set("schemeID", custom_registration_type)
        cbc_id_2.text = custom_company_registration

        supplier_names = _get_company_display_names(company_doc, sales_invoice_doc)
        if supplier_names:
            _append_party_names(cac_party_1, supplier_names)

        # Get the appropriate address
        address = get_address(sales_invoice_doc, company_doc)

        cac_postaladdress = ET.SubElement(cac_party_1, "cac:PostalAddress")
        cbc_streetname = ET.SubElement(cac_postaladdress, "cbc:StreetName")
        cbc_streetname.text = address.address_line1
        cbc_buildingnumber = ET.SubElement(cac_postaladdress, "cbc:BuildingNumber")
        cbc_buildingnumber.text = address.custom_building_number
        cbc_plotidentification = ET.SubElement(cac_postaladdress, "cbc:PlotIdentification")
        cbc_plotidentification.text = address.address_line1
        cbc_citysubdivisionname = ET.SubElement(cac_postaladdress, "cbc:CitySubdivisionName")
        cbc_citysubdivisionname.text = address.address_line2
        cbc_cityname = ET.SubElement(cac_postaladdress, "cbc:CityName")
        cbc_cityname.text = address.city
        cbc_postalzone = ET.SubElement(cac_postaladdress, "cbc:PostalZone")
        cbc_postalzone.text = address.pincode
        cbc_countrysubentity = ET.SubElement(cac_postaladdress, "cbc:CountrySubentity")
        cbc_countrysubentity.text = address.state

        cac_country = ET.SubElement(cac_postaladdress, "cac:Country")
        cbc_identificationcode = ET.SubElement(cac_country, "cbc:IdentificationCode")
        cbc_identificationcode.text = "SA"

        cac_partytaxscheme = ET.SubElement(cac_party_1, "cac:PartyTaxScheme")
        cbc_companyid = ET.SubElement(cac_partytaxscheme, "cbc:CompanyID")
        cbc_companyid.text = company_doc.tax_id

        cac_taxscheme = ET.SubElement(cac_partytaxscheme, "cac:TaxScheme")
        cbc_id_3 = ET.SubElement(cac_taxscheme, CBC_ID)
        cbc_id_3.text = "VAT"

        cac_partylegalentity = ET.SubElement(cac_party_1, "cac:PartyLegalEntity")
        cbc_registrationname = ET.SubElement(cac_partylegalentity, "cbc:RegistrationName")
        cbc_registrationname.text = supplier_names[0] if supplier_names else sales_invoice_doc.company

        return invoice
    except (ET.ParseError, AttributeError, ValueError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error occurred in company data: {e}"))
        return None


def customer_data(invoice, sales_invoice_doc):
    """
    Add customer data to XML.
    Customer country is resolved from the selected address country.
    If country is blank or unmapped, it defaults to SA.
    Arabic and English buyer names are both included when available and materially different.
    """
    try:
        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        cac_accountingcustomerparty = ET.SubElement(invoice, "cac:AccountingCustomerParty")
        cac_party_2 = ET.SubElement(cac_accountingcustomerparty, "cac:Party")

        if not customer_doc.custom_b2c or (
            customer_doc.custom_b2c and customer_doc.custom_buyer_id
        ):
            cac_partyidentification_1 = ET.SubElement(cac_party_2, "cac:PartyIdentification")
            cbc_id_4 = ET.SubElement(cac_partyidentification_1, CBC_ID)
            cbc_id_4.set("schemeID", str(customer_doc.custom_buyer_id_type))
            cbc_id_4.text = customer_doc.custom_buyer_id

        customer_names = _get_customer_display_names(customer_doc)
        if customer_names:
            _append_party_names(cac_party_2, customer_names)

        address = None
        customer_country_code = "SA"

        if customer_doc.custom_b2c != 1:
            address = _get_customer_address(sales_invoice_doc, customer_doc)

            if not address:
                frappe.throw(_("Customer address is mandatory for non-B2C customers."))

            customer_country_code = _get_customer_country_code(
                sales_invoice_doc, customer_doc, address
            )

            cac_postaladdress_1 = ET.SubElement(cac_party_2, "cac:PostalAddress")
            if getattr(address, "address_line1", None):
                cbc_streetname_1 = ET.SubElement(cac_postaladdress_1, "cbc:StreetName")
                cbc_streetname_1.text = address.address_line1

            if hasattr(address, "custom_building_number") and address.custom_building_number:
                cbc_buildingnumber_1 = ET.SubElement(cac_postaladdress_1, "cbc:BuildingNumber")
                cbc_buildingnumber_1.text = address.custom_building_number

            cbc_plotidentification_1 = ET.SubElement(cac_postaladdress_1, "cbc:PlotIdentification")
            if hasattr(address, "po_box") and address.po_box:
                cbc_plotidentification_1.text = address.po_box
            elif getattr(address, "address_line1", None):
                cbc_plotidentification_1.text = address.address_line1

            if getattr(address, "address_line2", None):
                cbc_citysubdivisionname_1 = ET.SubElement(cac_postaladdress_1, "cbc:CitySubdivisionName")
                cbc_citysubdivisionname_1.text = address.address_line2

            if getattr(address, "city", None):
                cbc_cityname_1 = ET.SubElement(cac_postaladdress_1, "cbc:CityName")
                cbc_cityname_1.text = address.city

            if getattr(address, "pincode", None):
                cbc_postalzone_1 = ET.SubElement(cac_postaladdress_1, "cbc:PostalZone")
                cbc_postalzone_1.text = address.pincode

            if getattr(address, "state", None):
                cbc_countrysubentity_1 = ET.SubElement(cac_postaladdress_1, "cbc:CountrySubentity")
                cbc_countrysubentity_1.text = address.state

            cac_country_1 = ET.SubElement(cac_postaladdress_1, "cac:Country")
            cbc_identificationcode_1 = ET.SubElement(cac_country_1, "cbc:IdentificationCode")
            cbc_identificationcode_1.text = customer_country_code

        cac_partytaxscheme_1 = ET.SubElement(cac_party_2, "cac:PartyTaxScheme")

        if not customer_doc.custom_buyer_id:
            cbc_company_id = ET.SubElement(cac_partytaxscheme_1, "cbc:CompanyID")
            cbc_company_id.text = customer_doc.tax_id

        cac_taxscheme_1 = ET.SubElement(cac_partytaxscheme_1, "cac:TaxScheme")
        cbc_id_5 = ET.SubElement(cac_taxscheme_1, "cbc:ID")
        cbc_id_5.text = "VAT"

        cac_partylegalentity_1 = ET.SubElement(cac_party_2, "cac:PartyLegalEntity")
        cbc_registrationname_1 = ET.SubElement(cac_partylegalentity_1, "cbc:RegistrationName")
        cbc_registrationname_1.text = customer_names[0] if customer_names else customer_doc.customer_name

        return invoice
    except (ET.ParseError, AttributeError, ValueError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error occurred in customer data: {e}"))
        return None


def delivery_and_payment_means(invoice, sales_invoice_doc, is_return):
    """
    Adds delivery and payment means elements to the XML invoice,
    including actual delivery date and payment means.
    """
    try:
        cac_delivery = ET.SubElement(invoice, "cac:Delivery")
        cbc_actual_delivery_date = ET.SubElement(cac_delivery, "cbc:ActualDeliveryDate")
        cbc_actual_delivery_date.text = str(sales_invoice_doc.due_date)

        cac_payment_means = ET.SubElement(invoice, "cac:PaymentMeans")
        cbc_payment_means_code = ET.SubElement(
            cac_payment_means, "cbc:PaymentMeansCode"
        )
        cbc_payment_means_code.text = "30"

        if is_return == 1:
            cbc_instruction_note = ET.SubElement(
                cac_payment_means, "cbc:InstructionNote"
            )
            cbc_instruction_note.text = "Cancellation or Returned"
        
        if sales_invoice_doc.is_debit_note == 1 :
            cbc_instruction_note = ET.SubElement(
                cac_payment_means, "cbc:InstructionNote"
            )
            cbc_instruction_note.text = "Price adjustment or Additional charges"

        return invoice

    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Delivery and payment means failed: {e}"))
        return None  # Ensures all return paths explicitly return a value


def delivery_and_payment_means_for_compliance(
    invoice, sales_invoice_doc, compliance_type
):
    """
    Adds delivery and payment means elements to the XML invoice for compliance,
    including actual delivery date, payment means, and instruction notes for cancellations.
    """
    try:
        cac_delivery = ET.SubElement(invoice, "cac:Delivery")
        cbc_actual_delivery_date = ET.SubElement(cac_delivery, "cbc:ActualDeliveryDate")
        cbc_actual_delivery_date.text = str(sales_invoice_doc.due_date)

        cac_payment_means = ET.SubElement(invoice, "cac:PaymentMeans")
        cbc_payment_means_code = ET.SubElement(
            cac_payment_means, "cbc:PaymentMeansCode"
        )
        cbc_payment_means_code.text = "30"

        if compliance_type in {"3", "4", "5", "6"}:
            cbc_instruction_note = ET.SubElement(
                cac_payment_means, "cbc:InstructionNote"
            )
            cbc_instruction_note.text = "Cancellation or Additional Charge"

        return invoice

    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Delivery and payment means failed: {e}"))
        return None


def add_document_level_discount_with_tax(invoice, sales_invoice_doc):
    """
    Adds document-level discount elements to the XML invoice,
    including allowance charges, reason codes, and tax details.
    When invoice discounts are already reflected in line net amounts,
    the document-level AllowanceCharge is intentionally skipped to avoid
    double-discounting in the XML sent to ZATCA.
    """
    try:
        if _use_line_net_amounts_discount_model(sales_invoice_doc):
            return invoice

        discount_value = (
            _abs_rounded(sales_invoice_doc.get("base_discount_amount", 0.0))
            if sales_invoice_doc.currency == "SAR"
            else _abs_rounded(sales_invoice_doc.get("discount_amount", 0.0))
        )
        if discount_value <= 0:
            return invoice

        cac_allowance_charge = ET.SubElement(invoice, "cac:AllowanceCharge")

        cbc_charge_indicator = ET.SubElement(
            cac_allowance_charge, "cbc:ChargeIndicator"
        )
        cbc_charge_indicator.text = "false"

        cbc_allowance_charge_reason_code = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReasonCode"
        )
        cbc_allowance_charge_reason_code.text = str(
            sales_invoice_doc.custom_zatca_discount_reason_code
        )

        cbc_allowance_charge_reason = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReason"
        )
        cbc_allowance_charge_reason.text = str(
            sales_invoice_doc.custom_zatca_discount_reason
        )

        cbc_amount = ET.SubElement(
            cac_allowance_charge, "cbc:Amount", currencyID=sales_invoice_doc.currency
        )
        cbc_amount.text = f"{discount_value:.2f}"

        cac_tax_category = ET.SubElement(cac_allowance_charge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_tax_category, CBC_ID)
        if sales_invoice_doc.custom_zatca_tax_category == "Standard":
            cbc_id.text = "S"
        elif sales_invoice_doc.custom_zatca_tax_category == "Zero Rated":
            cbc_id.text = "Z"
        elif sales_invoice_doc.custom_zatca_tax_category == "Exempted":
            cbc_id.text = "E"
        elif (
            sales_invoice_doc.custom_zatca_tax_category
            == "Services outside scope of tax / Not subject to VAT"
        ):
            cbc_id.text = "O"

        cbc_percent = ET.SubElement(cac_tax_category, "cbc:Percent")
        cbc_percent.text = f"{float(sales_invoice_doc.taxes[0].rate):.2f}"

        cac_tax_scheme = ET.SubElement(cac_tax_category, "cac:TaxScheme")
        cbc_tax_scheme_id = ET.SubElement(cac_tax_scheme, CBC_ID)
        cbc_tax_scheme_id.text = "VAT"

        return invoice

    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(
            _(
                f"Error occurred while processing allowance charge data without template: {e}"
            )
        )
        return None


def add_document_level_discount_with_tax_template(invoice, sales_invoice_doc):
    """
    Adds document-level discount elements to the XML invoice,
    including allowance charges, reason codes, and tax details.
    When invoice discounts are already reflected in line net amounts,
    the document-level AllowanceCharge is intentionally skipped to avoid
    double-discounting in the XML sent to ZATCA.
    """
    try:
        if _use_line_net_amounts_discount_model(sales_invoice_doc):
            return invoice

        discount_value = (
            _abs_rounded(sales_invoice_doc.get("base_discount_amount", 0.0))
            if sales_invoice_doc.currency == "SAR"
            else _abs_rounded(sales_invoice_doc.get("discount_amount", 0.0))
        )
        if discount_value <= 0:
            return invoice

        # Create the AllowanceCharge element
        cac_allowance_charge = ET.SubElement(invoice, "cac:AllowanceCharge")

        # ChargeIndicator
        cbc_charge_indicator = ET.SubElement(
            cac_allowance_charge, "cbc:ChargeIndicator"
        )
        cbc_charge_indicator.text = "false"  # Indicates a discount

        # AllowanceChargeReason
        cbc_allowance_charge_reason_code = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReasonCode"
        )
        cbc_allowance_charge_reason_code.text = str(
            sales_invoice_doc.custom_zatca_discount_reason_code
        )

        cbc_allowance_charge_reason = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReason"
        )
        cbc_allowance_charge_reason.text = str(
            sales_invoice_doc.custom_zatca_discount_reason
        )

        cbc_amount = ET.SubElement(
            cac_allowance_charge, "cbc:Amount", currencyID=sales_invoice_doc.currency
        )
        cbc_amount.text = f"{discount_value:.2f}"

        # Tax Category Section
        cac_tax_category = ET.SubElement(cac_allowance_charge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_tax_category, CBC_ID)

        vat_category_code = "Standard"
        tax_percentage = 0.0

        for item in sales_invoice_doc.items:
            item_tax_template_doc = frappe.get_doc(
                "Item Tax Template", item.item_tax_template
            )
            vat_category_code = item_tax_template_doc.custom_zatca_tax_category
            tax_percentage = (
                item_tax_template_doc.taxes[0].tax_rate
                if item_tax_template_doc.taxes
                else 15
            )
            break  # Assuming that all items will have the same tax category and percentage

        if vat_category_code == "Standard":
            cbc_id.text = "S"
        elif vat_category_code == "Zero Rated":
            cbc_id.text = "Z"
        elif vat_category_code == "Exempted":
            cbc_id.text = "E"
        elif vat_category_code == "Services outside scope of tax / Not subject to VAT":
            cbc_id.text = "O"
        else:
            frappe.throw(
                "Invalid or missing ZATCA VAT category in the Item Tax Template " 
                "linked to Sales Invoice Item. Ensure each Item Tax Template " 
                "includes one of the following categories: "
                "'Standard', 'Zero Rated', 'Exempted', or 'Services outside scope of tax / Not subject to VAT'."
            )

        cbc_percent = ET.SubElement(cac_tax_category, "cbc:Percent")
        cbc_percent.text = f"{tax_percentage:.2f}"

        cac_tax_scheme = ET.SubElement(cac_tax_category, "cac:TaxScheme")
        cbc_tax_scheme_id = ET.SubElement(cac_tax_scheme, CBC_ID)
        cbc_tax_scheme_id.text = "VAT"

        return invoice

    except (ET.ParseError, AttributeError, ValueError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error occurred while processing allowance charge data: {e}"))
        return None


def add_nominal_discount_tax(invoice, sales_invoice_doc):
    """
    Adds nominal discount and related tax details to the XML structure.
    When invoice discounts are already reflected in line net amounts,
    the document-level AllowanceCharge is skipped to avoid double-discounting.
    """
    try:
        if _use_line_net_amounts_discount_model(sales_invoice_doc):
            return invoice

        cac_allowance_charge = ET.SubElement(invoice, "cac:AllowanceCharge")
        cbc_charge_indicator = ET.SubElement(
            cac_allowance_charge, "cbc:ChargeIndicator"
        )
        cbc_charge_indicator.text = "false"  # Indicates a discount

        cbc_allowance_charge_reason_code = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReasonCode"
        )
        cbc_allowance_charge_reason_code.text = str(
            sales_invoice_doc.custom_zatca_discount_reason_code
        )

        cbc_allowance_charge_reason = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReason"
        )
        cbc_allowance_charge_reason.text = str(
            sales_invoice_doc.custom_zatca_discount_reason
        )

        cbc_amount = ET.SubElement(
            cac_allowance_charge, "cbc:Amount", currencyID=sales_invoice_doc.currency
        )

        total_line_extension = 0

        for single_item in sales_invoice_doc.items:
            line_extension_amount = abs(
                round(
                    single_item.amount / (1 + sales_invoice_doc.taxes[0].rate / 100), 2
                )
            )
            total_line_extension += round(line_extension_amount, 2)
        discount_amount = abs(round(sales_invoice_doc.discount_amount, 2))
        difference = abs(round(discount_amount - total_line_extension, 2))

        if (
            sales_invoice_doc.currency == "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 0
        ):
            base_discount_amount = sales_invoice_doc.base_total
            cbc_amount.text = f"{base_discount_amount:.2f}"

        elif (
            sales_invoice_doc.currency == "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 1
        ):
            base_discount_amount = (
                total_line_extension
                if difference == 0.01
                else sales_invoice_doc.base_discount_amount
            )
            cbc_amount.text = f"{base_discount_amount:.2f}"

        elif (
            sales_invoice_doc.currency != "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 0
        ):
            discount_amount = sales_invoice_doc.total
            cbc_amount.text = f"{discount_amount:.2f}"

        elif (
            sales_invoice_doc.currency != "SAR"
            and sales_invoice_doc.taxes[0].included_in_print_rate == 1
        ):
            discount_amount = (
                total_line_extension
                if difference == 0.01
                else sales_invoice_doc.discount_amount
            )
            cbc_amount.text = f"{discount_amount:.2f}"

        cac_tax_category = ET.SubElement(cac_allowance_charge, "cac:TaxCategory")
        cbc_id = ET.SubElement(cac_tax_category, CBC_ID)
        cbc_id.text = "O"

        cbc_percent = ET.SubElement(cac_tax_category, "cbc:Percent")
        cbc_percent.text = "0.00"

        cbc_tax_exemption_reason_code = ET.SubElement(
            cac_tax_category, "cbc:TaxExemptionReasonCode"
        )
        cbc_tax_exemption_reason_code.text = "VATEX-SA-OOS"

        cbc_tax_exemption_reason = ET.SubElement(
            cac_tax_category, "cbc:TaxExemptionReason"
        )
        cbc_tax_exemption_reason.text = "Special discount offer"

        cac_tax_scheme = ET.SubElement(cac_tax_category, "cac:TaxScheme")
        cbc_tax_scheme_id = ET.SubElement(cac_tax_scheme, CBC_ID)
        cbc_tax_scheme_id.text = "VAT"

        return invoice

    except (ValueError, KeyError, AttributeError) as error:
        frappe.throw(_(f"Error occurred in nominal discount: {str(error)}"))
        return None
