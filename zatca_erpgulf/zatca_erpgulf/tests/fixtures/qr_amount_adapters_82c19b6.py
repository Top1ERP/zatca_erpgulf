# Frozen increment222 QR adapters; test data, not runtime code.

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

        # VAT Number
        tax_id = frappe.db.get_value("Company", doc.company, "tax_id")
        if not tax_id:
            frappe.throw(
                _("Tax ID missing for {} in the company document").format(doc.company)
            )

        # Time Stamp
        time_stamp = format_zatca_qr_timestamp(doc.posting_date, doc.posting_time)

        # Invoice Amount
        invoice_amount = str(doc.base_grand_total)
        # VAT Amount
        vat_amount = str(doc.total_taxes_and_charges)
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


def ensure_final_sales_invoice_qr_for_print(doc, event=None, force=False):
    """Stage a first advance-aware QR, never repair or replace stored artifacts.

    This keeps existing print formats stable because they continue using doc.ksa_einv_qr.
    ``force`` is retained for call compatibility, not as a preservation bypass.
    A print hook is not an artifact-repair or historical-data migration boundary.

    Applies only when:
    - DocType is Sales Invoice.
    - Document is submitted.
    - Sales Invoice has custom_zatca_advance_deducted_taxable_amount > 0.
    - ksa_einv_qr field exists.

    The QR total is aligned with the final printed amount due after deducting
    the advance taxable amount and adding the remaining VAT.
    """
    from frappe.utils import flt

    if getattr(doc, "doctype", None) != "Sales Invoice":
        return

    company_doc = frappe.get_cached_doc("Company", doc.company)
    if is_zatca_invoice_enabled(company_doc) and resolve_zatca_phase(company_doc) == PHASE_2_VALUE:
        # Phase-2 QR must come from the returned ZATCA XML artifact.
        return

    if not supports_advance_deduction_schema(doc):
        return

    if int(getattr(doc, "docstatus", 0) or 0) != 1:
        return

    if not doc.meta.has_field("ksa_einv_qr"):
        return

    # This hook owns initial advances only. Never delete/relink a final invoice's
    # historical attachments based on filename hints, even if force was supplied.
    if not is_advance_payment_invoice(doc):
        return

    advance_taxable = flt(doc.get("custom_zatca_advance_deducted_taxable_amount") or 0)
    if advance_taxable <= 0:
        return

    # Reuse the bounded same-invoice policy, including missing/orphan review.
    # Preserving a link is not proof of valid contents or remote acceptance.
    if _existing_qr_reference(doc):
        return

    import io

    import pyqrcode
    from frappe.utils.file_manager import save_file

    company = frappe.get_doc("Company", doc.company)

    seller_name = (
        company.get("company_name_in_arabic")
        or company.get("custom_company_name_in_arabic")
        or company.company_name
    )

    vat_number = company.get("tax_id")
    if not vat_number:
        frappe.throw("Company Tax ID is required to generate ZATCA QR.")

    # Same explicit conversion as ordinary Phase-1 and XML-derived Phase-2.
    # Do not invent midnight for a missing field. The Phase-2 guard above still
    # preserves the authoritative stored QR and all amount calculations below.
    timestamp = format_zatca_qr_timestamp(doc.posting_date, doc.get("posting_time"))

    conversion_rate = flt(doc.get("conversion_rate") or 1)

    taxable_source = flt(doc.get("net_total") if doc.get("discount_amount") else doc.get("total"))
    base_taxable_source = flt(doc.get("base_net_total") if doc.get("discount_amount") else doc.get("base_total"))

    base_advance_taxable = advance_taxable * conversion_rate

    final_amount_due = taxable_source - advance_taxable + flt(doc.get("total_taxes_and_charges") or 0)
    base_final_amount_due = base_taxable_source - base_advance_taxable + flt(doc.get("base_total_taxes_and_charges") or 0)

    if doc.currency == "SAR":
        qr_invoice_total = final_amount_due
        qr_vat_total = flt(doc.get("total_taxes_and_charges") or 0)
    else:
        qr_invoice_total = base_final_amount_due
        qr_vat_total = flt(doc.get("base_total_taxes_and_charges") or 0)

    try:
        payload = encode_phase1_qr(
            seller_name=str(seller_name or ""), vat_number=str(vat_number or ""),
            timestamp=timestamp, invoice_total=f"{qr_invoice_total:.2f}",
            vat_total=f"{qr_vat_total:.2f}",
        )
    except Phase1QREncodingError as error:
        invalid_tag = error.tag
    else:
        invalid_tag = None
    if invalid_tag is not None:
        frappe.throw(_(PHASE1_QR_VALUE_ERROR).format(invalid_tag))

    png = io.BytesIO()
    pyqrcode.create(payload, error="L").png(png, scale=4, quiet_zone=4)

    file_name = f"QR-ZATCA-Advance-Aware-{doc.name}.png"

    file_doc = save_file(
        file_name,
        png.getvalue(),
        "Sales Invoice",
        doc.name,
        is_private=0,
    )

    file_doc.attached_to_field = "ksa_einv_qr"
    file_doc.save(ignore_permissions=True)

    frappe.db.set_value(
        "Sales Invoice",
        doc.name,
        "ksa_einv_qr",
        file_doc.file_url,
        update_modified=False,
    )

    doc.ksa_einv_qr = file_doc.file_url


def generate_tlv_xml(final_xml_string,company_abbr,source_doc):
    """generate xml by adding the tlv data"""
    try:

        # with open(
        #     f"{frappe.local.site}/private/files/final_xml_after_sign_{invoice_number}.xml", "rb"
        # ) as file:
        #     xml_data = file.read()
        # root = etree.fromstring(xml_data)
        root = etree.fromstring(final_xml_string.encode("utf-8"))
        namespaces = {
            "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
            "sig": "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
            "sac": "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }
        issue_date_xpath = "/ubl:Invoice/cbc:IssueDate"
        issue_time_xpath = "/ubl:Invoice/cbc:IssueTime"
        issue_date_results = root.xpath(issue_date_xpath, namespaces=namespaces)
        issue_time_results = root.xpath(issue_time_xpath, namespaces=namespaces)
        if (len(issue_date_results) != 1 or len(issue_time_results) != 1
                or any(len(element) or not str(element.text or "").strip()
                       for element in (*issue_date_results, *issue_time_results))):
            # Never silently select the first duplicate or invent a timestamp.
            frappe.throw(_("The invoice XML must contain exactly one nonempty IssueDate and IssueTime."))
        issue_date = (
            issue_date_results[0].text.strip() if issue_date_results else "Missing Data"
        )
        issue_time = (
            issue_time_results[0].text.strip() if issue_time_results else "Missing Data"
        )
        # ZATCA requires QR Tag 3 to be an ISO-8601 UTC timestamp.
        issue_date_time = format_zatca_qr_timestamp(issue_date, issue_time)
        tags_xpaths = [
            (
                1,
                "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName",
            ),
            (
                2,
                "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
            ),
            (3, None),
            # QR Tag 4 follows BT-115 (PayableAmount). For ordinary invoices
            # it normally equals TaxInclusiveAmount; with prepayments or
            # rounding it is the final amount due.
            (4, "/ubl:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount"),
            (5, "/ubl:Invoice/cac:TaxTotal/cbc:TaxAmount"),
            (
                6,
                "/ubl:Invoice/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:SignedInfo/ds:Reference/ds:DigestValue",
            ),
            (
                7,
                "/ubl:Invoice/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sig:UBLDocumentSignatures/sac:SignatureInformation/ds:Signature/ds:SignatureValue",
            ),
            (8, None),
            (9, None),
        ]
        result_dict = {}
        for tag, xpath in tags_xpaths:
            if isinstance(xpath, str):
                elements = root.xpath(xpath, namespaces=namespaces)
                if elements:
                    value = (
                        elements[0].text
                        if isinstance(elements[0], etree._Element)
                        else elements[0]
                    )
                    if tag == 4 and not str(value or "").strip():
                        frappe.throw(
                            _(
                                "Cannot generate QR Tag 4: "
                                "cbc:PayableAmount is empty."
                            )
                        )
                    result_dict[tag] = value
                else:
                    if tag == 4:
                        frappe.throw(
                            _(
                                "Cannot generate QR Tag 4: "
                                "cbc:PayableAmount is missing from the XML."
                            )
                        )
                    result_dict[tag] = "Not found"
            else:
                result_dict[tag] = xpath
        result_dict[3] = issue_date_time
        result_dict[8] = tag8_publickey(company_abbr, source_doc)
        # Tag 9 is defined only for Simplified Tax Invoices and their notes.
        invoice_typecode = root.xpath(
            "/ubl:Invoice/cbc:InvoiceTypeCode", namespaces=namespaces
        )
        invoice_type_name = (
            (invoice_typecode[0].get("name") or "").strip()
            if invoice_typecode
            else ""
        )
        is_simplified_xml = invoice_type_name.startswith("02")
        if is_simplified_xml or _is_simplified_document(source_doc):
            result_dict[9] = tag9_signature_ecdsa(company_abbr, source_doc)
        else:
            result_dict.pop(9, None)
        result_dict[1] = result_dict[1].encode(
            "utf-8"
        )  # Handling Arabic company name in QR Code
        return result_dict
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in getting the entire TLV data: " + str(e)))
        return None
