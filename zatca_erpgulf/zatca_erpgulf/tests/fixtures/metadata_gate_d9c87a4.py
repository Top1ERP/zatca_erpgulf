"""Frozen increment226 metadata/generators; offline source-order oracle only."""

SOURCES = {
'zatca_erpgulf/zatca_erpgulf/createxml.py': r'''
def salesinvoice_data(invoice, invoice_number, *, purpose="production"):
    """
    Populate metadata, persisting issuance identity only for the live workflow.
    """
    try:
        sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)

        # Freeze time from the SAME loaded record, and validate BEFORE any UUID
        # persistence. A second get_doc could observe a different revision.
        issue_timestamp = format_zatca_qr_timestamp(sales_invoice_doc.posting_date, sales_invoice_doc.posting_time)
        uuid1 = (
            _get_or_create_sales_invoice_uuid(sales_invoice_doc)
            if purpose == "production"
            else preview_invoice_uuid(getattr(sales_invoice_doc, "custom_uuid", None), purpose)
        )
        append_invoice_metadata(invoice, sales_invoice_doc.name, uuid1, issue_timestamp)
        return invoice, uuid1, sales_invoice_doc
    except (AttributeError, ValueError, frappe.ValidationError) as e:
        frappe.throw(_(("Error occurred in SalesInvoice data: " f"{str(e)}")))
        return None
''',
'zatca_erpgulf/zatca_erpgulf/posxml.py': r'''
def salesinvoice_data(invoice, invoice_number, *, purpose="production"):
    """Populate POS metadata; non-production UUIDs never mutate the source."""
    try:
        pos_invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
        # Use this loaded revision for time as well as identity/returned data.
        issue_timestamp = format_zatca_qr_timestamp(pos_invoice_doc.posting_date, pos_invoice_doc.posting_time)
        uuid1 = (
            str(uuid.uuid1())
            if purpose == "production"
            else preview_invoice_uuid(getattr(pos_invoice_doc, "custom_uuid", None), purpose)
        )
        append_invoice_metadata(invoice, pos_invoice_doc.name, uuid1, issue_timestamp)
        return invoice, uuid1, pos_invoice_doc
    except (AttributeError, ValueError, frappe.ValidationError) as e:
        frappe.throw(_(("Error occurred in SalesInvoice data: " f"{str(e)}")))
        return None
''',
'zatca_erpgulf/zatca_erpgulf/sign_invoice.py': r'''
def zatca_call(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
):
    """zatca call which includes the function calling and validation reguarding the api and
    based on this the zATCA output and message is getting"""
    compliance_type = normalize_generator_compliance_type(compliance_type)
    if compliance_type != "0":
        return dispatch_generator_compliance(
            "Sales Invoice", invoice_number, compliance_type, company_abbr
        )
    try:
        if not frappe.db.exists("Sales Invoice", invoice_number):
            frappe.throw(_("Invoice Number is NOT Valid: " + str(invoice_number)))
        invoice = xml_tags()
        invoice, uuid1, sales_invoice_doc = salesinvoice_data(invoice, invoice_number)
        any_item_has_tax_template = resolve_invoice_template_mode(
            sales_invoice_doc, runtime=frappe, translate=_)
        # Signing and HTTP must follow the same saved invoice issuer.
        source_doc = sales_invoice_doc
        # Get the company abbreviation
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )

        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)

        # Export validation
        if getattr(sales_invoice_doc, "custom_zatca_export_invoice", 0) == 1:
            customer_country = _get_customer_country_code(sales_invoice_doc, customer_doc)
            if customer_country == "SA":
                frappe.throw(_("Export Invoice cannot be enabled for a customer in Saudi Arabia."))

        invoice = populate_invoice_type(
            invoice, sales_invoice_doc, customer_doc,
            namespace=globals(), doctype="Sales Invoice",
        )
        invoice = populate_invoice_parties(
            invoice, sales_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="Sales Invoice", purpose="invoice",
            ),
        )

        invoice = populate_document_tax(
            invoice, sales_invoice_doc,
            tools=DocumentTaxTools.from_namespace(
                globals(), has_template=any_item_has_tax_template, include_nominal=True,
            ),
            is_nominal=lambda: sales_invoice_doc.custom_zatca_nominal_invoice == 1,
        )
        invoice = populate_sales_items(
            invoice, sales_invoice_doc, namespace=globals(),
            has_template=any_item_has_tax_template,
        )

        file_content=xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        signed_xmlfile_name = structuring_signedxml(invoice_number,updated_xml_string)
        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            attach_qr_image(qrcodeb64, sales_invoice_doc)
            reporting_api(
                uuid1,
                encoded_hash,
                signed_xmlfile_name,
                invoice_number,
                sales_invoice_doc,
            )

        else:
            company_doc = frappe.get_doc("Company", sales_invoice_doc.company)
            if is_clearance_enabled(company_doc):
                clearance_api(
                    uuid1,
                    encoded_hash,
                    signed_xmlfile_name,
                    invoice_number,
                    sales_invoice_doc,
                )
            else:
                reporting_api(
                    uuid1,
                    encoded_hash,
                    signed_xmlfile_name,
                    invoice_number,
                    sales_invoice_doc,
                )
            attach_qr_image(qrcodeb64, sales_invoice_doc)
    except DeclaredVatError:
        raise
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.log_error(
            title="ZATCA invoice call failed",
            message=f"{frappe.get_traceback()}\nError: {str(e)}",
        )
''',
'zatca_erpgulf/zatca_erpgulf/pos_sign.py': r'''
def zatca_call(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
):
    """Function for zatca call"""
    compliance_type = normalize_generator_compliance_type(compliance_type)
    if compliance_type != "0":
        return dispatch_generator_compliance(
            "POS Invoice", invoice_number, compliance_type, company_abbr
        )
    try:

        if not frappe.db.exists("POS Invoice", invoice_number):
            frappe.throw("Invoice Number is NOT Valid: " + str(invoice_number))

        invoice = xml_tags()
        invoice, uuid1, pos_invoice_doc = salesinvoice_data(invoice, invoice_number)
        any_item_has_tax_template = resolve_invoice_template_mode(
            pos_invoice_doc, runtime=frappe, translate=_)
        # Signing and HTTP must follow the same saved invoice issuer.
        source_doc = pos_invoice_doc

        # Get the company abbreviation
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )

        customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)

        invoice = populate_invoice_type(
            invoice, pos_invoice_doc, customer_doc,
            namespace=globals(), doctype="POS Invoice",
        )
        invoice = populate_invoice_parties(
            invoice, pos_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="POS Invoice", purpose="invoice",
            ),
        )
        invoice = populate_pos_financials(
            invoice, pos_invoice_doc, namespace=globals(),
            has_template=any_item_has_tax_template,
        )

        file_content = xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        signed_xmlfile_name = structuring_signedxml(invoice_number,updated_xml_string)

        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            attach_qr_image(qrcodeb64, pos_invoice_doc)
            reporting_api(
                uuid1,
                encoded_hash,
                signed_xmlfile_name,
                invoice_number,
                pos_invoice_doc,
            )

        else:
            clearance_api(
                uuid1,
                encoded_hash,
                signed_xmlfile_name,
                invoice_number,
                pos_invoice_doc,
            )
            attach_qr_image(qrcodeb64, pos_invoice_doc)
    except PosFinancialError:
        raise
    except DeclaredVatError:
        raise
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.log_error(
            title="ZATCA invoice call failed",
            message=f"{frappe.get_traceback()} \n Error: {str(e)}",
        )
''',
'zatca_erpgulf/zatca_erpgulf/sales_invoice_withoutxml.py': r'''
def zatca_call_withoutxml(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
):
    """zatca call which includes the function calling and validation reguarding the api and
    based on this the zATCA output and message is getting"""
    compliance_type = normalize_generator_compliance_type(compliance_type)
    if compliance_type != "0":
        return dispatch_generator_compliance(
            "Sales Invoice", invoice_number, compliance_type, company_abbr
        )
    try:
        if not frappe.db.exists(SALES_INVOICE, invoice_number):
            frappe.throw(_("Invoice Number is NOT Valid: " + str(invoice_number)))
        invoice = xml_tags()
        invoice, uuid1, sales_invoice_doc = salesinvoice_data(invoice, invoice_number)
        any_item_has_tax_template = resolve_invoice_template_mode(
            sales_invoice_doc, runtime=frappe, translate=_)
        # Signing and HTTP must follow the same saved invoice issuer.
        source_doc = sales_invoice_doc
        # Get the company abbreviation
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )

        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)

        if is_advance_payment_invoice(sales_invoice_doc) and not sales_invoice_doc.is_return and not getattr(sales_invoice_doc, "is_debit_note", 0):
            invoice = invoice_typecode_advance_payment(invoice, sales_invoice_doc)
        else:
            if get_alias_value("customer_b2c", customer_doc, 0) == 1:
                invoice = invoice_typecode_simplified(invoice, sales_invoice_doc)
            else:
                frappe.throw(
                    _("customer should be B2C sales invoice with xml during create xml")
                )
        invoice = populate_invoice_parties(
            invoice, sales_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="Sales Invoice", purpose="invoice",
            ),
        )

        invoice = populate_document_tax(
            invoice, sales_invoice_doc,
            tools=DocumentTaxTools.from_namespace(
                globals(), has_template=any_item_has_tax_template, include_nominal=True,
            ),
            is_nominal=lambda: sales_invoice_doc.custom_zatca_nominal_invoice == 1,
        )

        if not any_item_has_tax_template:
            invoice = item_data(invoice, sales_invoice_doc)
        else:
            invoice = item_data_with_template(invoice, sales_invoice_doc)
        file_content = xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        signed_xmlfile_name = structuring_signedxml(invoice_number, updated_xml_string)

        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            attach_qr_image(qrcodeb64, sales_invoice_doc)
            reporting_api_sales_withoutxml(
                uuid1,
                encoded_hash,
                signed_xmlfile_name,
                invoice_number,
                sales_invoice_doc,
            )
        else:
            frappe.throw(
                _("customer should be B2C type required for simplified invoice")
            )
    except DeclaredVatError:
        raise
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.log_error(
            title="ZATCA invoice call failed",
            message=f"{frappe.get_traceback()}\nError: {str(e)}",
        )
''',
'zatca_erpgulf/zatca_erpgulf/zatca_background_sched.py': r'''
def zatca_call_scheduler_background(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
):
    """zatca call which includes the function calling and validation reguarding the api and
    based on this the zATCA output and message is getting"""
    compliance_type = normalize_generator_compliance_type(compliance_type)
    if compliance_type != "0":
        return dispatch_generator_compliance(
            "Sales Invoice", invoice_number, compliance_type, company_abbr
        )
    try:
        if not frappe.db.exists(SALES_INVOICE, invoice_number):
            frappe.throw(_("Invoice Number is NOT Valid: " + str(invoice_number)))
        invoice = xml_tags()
        invoice, uuid1, sales_invoice_doc = salesinvoice_data(invoice, invoice_number)
        any_item_has_tax_template = resolve_invoice_template_mode(
            sales_invoice_doc, runtime=frappe, translate=_)
        # Signing and HTTP must follow the same saved invoice issuer.
        source_doc = sales_invoice_doc
        # Get the company abbreviation
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )

        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)

        if is_advance_payment_invoice(sales_invoice_doc) and not sales_invoice_doc.is_return and not getattr(sales_invoice_doc, "is_debit_note", 0):
            invoice = invoice_typecode_advance_payment(invoice, sales_invoice_doc)
        else:
            if get_alias_value("customer_b2c", customer_doc, 0) == 1:
                invoice = invoice_typecode_simplified(invoice, sales_invoice_doc)
            else:
                frappe.throw(
                    _("customer should be B2C sales invoice with xml during create xml")
                )
        invoice = populate_invoice_parties(
            invoice, sales_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="Sales Invoice", purpose="invoice",
            ),
        )

        invoice = populate_document_tax(
            invoice, sales_invoice_doc,
            tools=DocumentTaxTools.from_namespace(
                globals(), has_template=any_item_has_tax_template, include_nominal=True,
            ),
            is_nominal=lambda: sales_invoice_doc.custom_zatca_nominal_invoice == 1,
        )

        if not any_item_has_tax_template:
            invoice = item_data(invoice, sales_invoice_doc)
        else:
            invoice = item_data_with_template(invoice, sales_invoice_doc)
        file_content= xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        signed_xmlfile_name = structuring_signedxml(invoice_number,updated_xml_string)

        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            attach_qr_image(qrcodeb64, sales_invoice_doc)
            reporting_api_sales_withoutxml(
                uuid1,
                encoded_hash,
                signed_xmlfile_name,
                invoice_number,
                sales_invoice_doc,
            )
        else:
            frappe.throw(
                _("customer should be B2C type required for simplified invoice")
            )
    except DeclaredVatError:
        raise
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.log_error(
            title="ZATCA invoice call failed",
            message=f"{frappe.get_traceback()}\nError: {str(e)}",
        )
''',
'zatca_erpgulf/zatca_erpgulf/pos_submit__without_xml.py': r'''
def zatca_call_pos_without_xml(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
):
    """Function for ZATCA call"""
    compliance_type = normalize_generator_compliance_type(compliance_type)
    if compliance_type != "0":
        return dispatch_generator_compliance(
            "POS Invoice", invoice_number, compliance_type, company_abbr
        )
    try:

        if not frappe.db.exists(POS_INVOICE, invoice_number):
            frappe.throw("Invoice Number is NOT Valid: " + str(invoice_number))

        invoice = xml_tags()
        invoice, uuid1, pos_invoice_doc = salesinvoice_data(invoice, invoice_number)
        any_item_has_tax_template = resolve_invoice_template_mode(
            pos_invoice_doc, runtime=frappe, translate=_)
        # Signing and HTTP must follow the same saved invoice issuer.
        source_doc = pos_invoice_doc

        # Get the company abbreviation
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )

        customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)

        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            invoice = invoice_typecode_simplified(invoice, pos_invoice_doc)
        else:
            frappe.throw(
                "customer should be B2C pos without xml during create xml "
            )
        invoice = populate_invoice_parties(
            invoice, pos_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="POS Invoice", purpose="invoice",
            ),
        )
        invoice = populate_pos_financials(
            invoice, pos_invoice_doc, namespace=globals(),
            has_template=any_item_has_tax_template,
        )

        file_content = xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        signed_xmlfile_name = structuring_signedxml(invoice_number, updated_xml_string)

        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            attach_qr_image(qrcodeb64, pos_invoice_doc)
            reporting_api_pos_without_xml(
                uuid1,
                encoded_hash,
                signed_xmlfile_name,
                invoice_number,
                pos_invoice_doc,
            )

        else:
            frappe.throw(
                _(
                    "B2B is not supported for POS Invoices,customer should be B2C pos without xml "
                )
            )
    except PosFinancialError:
        raise
    except DeclaredVatError:
        raise
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.log_error(
            title="ZATCA invoice call failed",
            message=f"{frappe.get_traceback()} \n Error: {str(e)}",
        )
''',
'zatca_erpgulf/zatca_erpgulf/pos_schedule_background.py': r'''
def zatca_call_pos_without_xml_background(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
):
    """Function for zatca call"""
    compliance_type = normalize_generator_compliance_type(compliance_type)
    if compliance_type != "0":
        return dispatch_generator_compliance(
            "POS Invoice", invoice_number, compliance_type, company_abbr
        )
    try:

        if not frappe.db.exists(POS_INVOICE, invoice_number):
            frappe.throw("Invoice Number is NOT Valid: " + str(invoice_number))

        invoice = xml_tags()
        invoice, uuid1, pos_invoice_doc = salesinvoice_data(invoice, invoice_number)
        any_item_has_tax_template = resolve_invoice_template_mode(
            pos_invoice_doc, runtime=frappe, translate=_)
        # Signing and HTTP must follow the same saved invoice issuer.
        source_doc = pos_invoice_doc

        # Get the company abbreviation
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )

        customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)

        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            invoice = invoice_typecode_simplified(invoice, pos_invoice_doc)
        else:
            frappe.throw(
                "customer should be B2C pos without xml during create xml "
            )
        invoice = populate_invoice_parties(
            invoice, pos_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="POS Invoice", purpose="invoice",
            ),
        )
        invoice = populate_pos_financials(
            invoice, pos_invoice_doc, namespace=globals(),
            has_template=any_item_has_tax_template,
        )

        file_content = xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        signed_xmlfile_name = structuring_signedxml(invoice_number,updated_xml_string)

        if get_alias_value("customer_b2c", customer_doc, 0) == 1:
            attach_qr_image(qrcodeb64, pos_invoice_doc)
            reporting_api_pos_without_xml(
                uuid1,
                encoded_hash,
                signed_xmlfile_name,
                invoice_number,
                pos_invoice_doc,
            )

        else:
            frappe.throw(
                "B2B is not supported for POS Invoices,customer should be B2C pos without xml "
            )
    except PosFinancialError:
        raise
    except DeclaredVatError:
        raise
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.log_error(
            title="ZATCA invoice call failed",
            message=f"{frappe.get_traceback()} \n Error: {str(e)}",
        )
''',
'zatca_erpgulf/zatca_erpgulf/debug_xml.py': r'''
def _debug_call(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
    bypass_background_check=False
):
    """
    Generate ZATCA-compliant debug XML for a Sales Invoice and attach as a private file.
    Handles Phase-2, B2C simplified, GPOS, TLV, QR, signing, and fallback logic.
    """
    notices = []
    try:
        sales_invoice_doc, settings, debug_source = prepare_debug_source(frappe, SALES_INVOICE, invoice_number)
        compliance_type = checked_debug_type(compliance_type)
        source_doc = sales_invoice_doc
        company_abbr = settings.abbr
        company_doc = settings
        # Debug XML is a local simulation and must remain available even when
        # live ZATCA submission is disabled for the Company.  It never submits
        # or sends the generated XML.
        if not is_zatca_invoice_enabled(company_doc):
            notices.append(DEBUG_LOCAL_ONLY)

        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        if company_doc.tax_id and customer_doc.tax_id:
            if company_doc.tax_id.strip() == customer_doc.tax_id.strip():
                return {"status": "skipped", "message": DEBUG_SKIPPED, "notices": notices}
        # Check if GPOS installed & custom fields exist
        is_gpos_installed = "gpos" in frappe.get_installed_apps()
        field_exists = frappe.get_meta(SALES_INVOICE).has_field("custom_unique_id")

        # Validate QR if XML already exists
        if is_gpos_installed and getattr(sales_invoice_doc, "custom_xml", None) and not getattr(sales_invoice_doc, "custom_qr_code", None):
            frappe.throw(_("Please provide the 'qr_code' field data when XML exists for invoice: ") + str(invoice_number))

        # --- Helper function: generate & attach XML ---
        def generate_and_attach_xml(invoice_doc):
            # Step 1: XML creation
            invoice = xml_tags()
            invoice, uuid1, invoice_doc = salesinvoice_data(
                invoice, invoice_doc.name, purpose="debug"
            )
            any_item_has_tax_template = resolve_invoice_template_mode(
                invoice_doc, runtime=frappe, translate=_)
            customer_doc = frappe.get_doc("Customer", invoice_doc.customer)

            # Step 2: Classify from the invoice/customer or explicit sample.
            invoice = populate_invoice_type(
                invoice, invoice_doc, customer_doc, namespace=globals(),
                doctype="Sales Invoice", compliance_type=compliance_type,
            )

            # Step 3: Populate XML
            invoice = populate_invoice_parties(
                invoice, invoice_doc, invoice_doc.name, company_abbr,
                tools=PartyXmlTools.from_namespace(
                    globals(), doctype="Sales Invoice", purpose="debug",
                ),
            )

            # Step 4: Discounts & Taxes
            debug_nominal = getattr(invoice_doc, "custom_zatca_nominal_invoice", 0) == 1
            invoice = populate_document_tax(
                invoice, invoice_doc,
                tools=DocumentTaxTools.from_namespace(
                    globals(), has_template=any_item_has_tax_template, include_nominal=True,
                ),
                is_nominal=lambda: debug_nominal,
            )

            # Step 5: Use the same direct/legacy item selection as ordinary Sales.
            invoice = populate_sales_items(
                invoice, invoice_doc, namespace=globals(),
                has_template=any_item_has_tax_template,
            )

            # Step 6: XML Structuring & reading
            file_content = xml_structuring(invoice)

            signed_xml = sign_invoice_xml(
                file_content, company_abbr, source_doc,
                tools=SigningTools.from_namespace(globals()),
            )
            updated_xml_string = signed_xml.xml
            # Attach the same formatted bytes without writing, replacing, or
            # unlinking an intermediate file that a live worker may be using.
            xml_data = format_zatca_signed_xml(updated_xml_string)
            attachment = save_debug_attachment(frappe, debug_source, xml_data)
            return {"status": "success", "message": DEBUG_CREATED,
                    **attachment, "notices": notices}

        # Existing issued artifacts only add a notice. Scheduling and GPOS
        # identifiers must not change the customer's invoice classification.
        if resolve_zatca_phase(settings) == PHASE_2_VALUE:
            if field_exists and getattr(sales_invoice_doc, "custom_unique_id", None):
                if is_gpos_installed and getattr(sales_invoice_doc, "custom_xml", None):
                    notices.append(DEBUG_EXISTING)
            elif is_qr_and_xml_attached(sales_invoice_doc):
                notices.append(DEBUG_EXISTING)

        return generate_and_attach_xml(sales_invoice_doc)
    except Exception as e:
        if isinstance(e, InvoiceTypeSelectionError):
            notices.append(e.template)
        if isinstance(e, DeclaredVatError):
            notices.append(e.template)
        if isinstance(e, DebugArtifactError):
            notices.append(str(e))
        # Keep the original traceback; only the app-owned label is English.
        if not isinstance(e, DeclaredVatError) or not e.diagnostic_logged:
            frappe.log_error(traceback.format_exc(), f"Debug XML Error for invoice {invoice_number}")
        return {"status": "error", "message": DEBUG_FAILED,
                "technical_details": str(e), "notices": notices}
''',
'zatca_erpgulf/zatca_erpgulf/pos_debug_xml.py': r'''
def _debug_call(
    invoice_number,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_abbr=None,
    source_doc=None,
):

    """Function for ZATCA debug XML generation and attachment"""
    notices = []
    try:
        # --- Fetch POS Invoice ---
        pos_invoice_doc, settings, debug_source = prepare_debug_source(frappe, "POS Invoice", invoice_number)
        compliance_type = checked_debug_type(compliance_type)
        source_doc = pos_invoice_doc
        company_abbr = settings.abbr
        company_doc = settings

        if not is_zatca_invoice_enabled(company_doc):
            return {"status": "skipped", "message": DEBUG_POS_DISABLED, "notices": notices}

        # --- Fetch Customer ---
        customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)

        # Intra-company transfer
        if company_doc.tax_id and customer_doc.tax_id:
            if company_doc.tax_id.strip() == customer_doc.tax_id.strip():
                return {"status": "skipped", "message": DEBUG_SKIPPED, "notices": notices}

        if not get_alias_value("customer_buyer_id_type", customer_doc, "") and get_alias_value("customer_buyer_id", customer_doc, ""):
            frappe.throw(_("Buyer ID must be blank if Buyer ID Type is not set."))

        if not frappe.db.exists("POS Invoice", invoice_number):
            frappe.throw("Invoice Number is NOT valid: " + str(invoice_number))

        # --- Check GPOS and fields ---
        is_gpos_installed = "gpos" in frappe.get_installed_apps()
        field_exists = frappe.get_meta("POS Invoice").has_field("custom_unique_id")

        if is_gpos_installed and pos_invoice_doc.custom_xml and not pos_invoice_doc.custom_qr_code:
            frappe.throw(
                _(
                    "Please provide the 'qr_code' field data when 'custom_xml' is filled for invoice: "
                    + str(invoice_number)
                )
            )

        # --- Function to generate and attach XML ---
        def generate_and_attach_xml(invoice_doc):
            invoice = xml_tags()
            invoice, uuid1, invoice_doc = salesinvoice_data(
                invoice, invoice_number, purpose="debug"
            )
            any_item_has_tax_template = resolve_invoice_template_mode(
                invoice_doc, runtime=frappe, translate=_)

            company_abbr = frappe.db.get_value("Company", {"name": invoice_doc.company}, "abbr")
            customer_doc_inner = frappe.get_doc("Customer", invoice_doc.customer)

            invoice = populate_invoice_type(
                invoice, invoice_doc, customer_doc_inner, namespace=globals(),
                doctype="POS Invoice", compliance_type=compliance_type,
                standard_builder=_reject_standard_debug_type,
            )

            invoice = populate_invoice_parties(
                invoice, invoice_doc, invoice_number, company_abbr,
                tools=PartyXmlTools.from_namespace(
                    globals(), doctype="POS Invoice", purpose="debug",
                ),
            )

            invoice = populate_pos_financials(
                invoice, invoice_doc, namespace=globals(),
                has_template=any_item_has_tax_template,
            )

            file_content = xml_structuring(invoice)

            signed_xml = sign_invoice_xml(
                file_content, company_abbr, source_doc,
                tools=SigningTools.from_namespace(globals()),
            )
            updated_xml_string = signed_xml.xml

            # Never share the live submission artifact's filename with Debug.
            xml_data = format_zatca_signed_xml(updated_xml_string)
            attachment = save_debug_attachment(frappe, debug_source, xml_data)
            return {"status": "success", "message": DEBUG_CREATED,
                    **attachment, "notices": notices}

        # Keep Phase-2 POS/GPOS checks and existing-artifact notices. Debug is
        # local: live submission scheduling does not select its document type.
        # The generator above already selects B2C or an explicit sample type.
        if resolve_zatca_phase(settings) == PHASE_2_VALUE:
            if field_exists and getattr(pos_invoice_doc, "custom_unique_id", None):
                if not getattr(pos_invoice_doc, "custom_zatca_pos_name", None):
                    frappe.throw(_("POS name is required"))

                if is_gpos_installed and getattr(pos_invoice_doc, "custom_xml", None):
                    notices.append(DEBUG_EXISTING)
            else:
                if is_qr_and_xml_attached(pos_invoice_doc):
                    notices.append(DEBUG_EXISTING)

        return generate_and_attach_xml(pos_invoice_doc)

    except Exception as e:
        if isinstance(e, InvoiceTypeSelectionError):
            notices.append(e.template)
        if isinstance(e, (PosFinancialError, DeclaredVatError)):
            notices.append(e.template)
        if isinstance(e, DebugArtifactError):
            notices.append(str(e))
        if not isinstance(e, (PosFinancialError, DeclaredVatError)) or not e.diagnostic_logged:
            frappe.log_error(traceback.format_exc(), f"Debug XML Error for invoice {invoice_number}")
        return {"status": "error", "message": DEBUG_FAILED,
                "technical_details": str(e), "notices": notices}
''',
}
