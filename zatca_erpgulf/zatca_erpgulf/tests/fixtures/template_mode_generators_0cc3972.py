"""Frozen increment225 generator bodies; test-only route/source oracle."""

SOURCES = {
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

def zatca_call_compliance(
    invoice_number,
    company_abbr=None,
    source_doc=None,
    compliance_type="0",
    any_item_has_tax_template=False,
    company_name=None,
    validation_type=None,
):
    """Test an invoice snapshot; an explicit type never changes Company settings."""

    try:
        if source_doc:
            source_doc = frappe.get_doc(json.loads(source_doc))

        if company_name:
            if not frappe.db.exists("Company", company_name):
                frappe.throw(_(f"Company {company_name} not found."))
        elif company_abbr:
            company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
            if not company_name:
                frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))
        else:
            frappe.throw(_("Company is required for ZATCA compliance check."))

        company_doc = frappe.get_doc("Company", company_name)

        try:
            # Existing single-check callers select the Company label (some UI
            # callers also send a hard-coded numeric value). Batch callers pass
            # an explicit label, avoiding shared mutable Company state.
            compliance_type = resolve_compliance_type(
                company_doc.custom_validation_type if validation_type is None else validation_type,
                fallback=compliance_type if validation_type is None else "0",
            )
        except ValueError:
            frappe.throw(_("Select a valid ZATCA compliance document type."))
        if not frappe.db.exists("Sales Invoice", invoice_number):
            frappe.throw(_("Invoice Number is NOT Valid: " + str(invoice_number)))
        invoice = xml_tags()
        invoice, uuid1, sales_invoice_doc = salesinvoice_data(
            invoice, invoice_number, purpose="compliance"
        )
        if source_doc is None:
            source_doc = sales_invoice_doc

        if getattr(sales_invoice_doc, "company", None) and sales_invoice_doc.company != company_doc.name:
            frappe.throw(
                _(
                    "Sample Invoice {0} belongs to Company {1}, not selected Company {2}."
                ).format(invoice_number, sales_invoice_doc.company, company_doc.name)
            )

        any_item_has_tax_template = any(
            item.item_tax_template for item in sales_invoice_doc.items
        )
        if any_item_has_tax_template and not all(
            item.item_tax_template for item in sales_invoice_doc.items
        ):
            frappe.throw(
                _(
                    "If any one item has an Item Tax Template,"
                    " all items must have an Item Tax Template."
                )
            )
        invoice = invoice_typecode_compliance(invoice, compliance_type)
        invoice = populate_invoice_parties(
            invoice, sales_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="Sales Invoice", purpose="compliance",
            ),
            compliance_type=compliance_type,
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
            item_data_with_template(invoice, sales_invoice_doc)
        # Generate and process the XML data
        file_content=xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        # Use the established formatter, but never write the live invoice's
        # submission filename. The sample disappears even when the API raises.
        with temporary_compliance_xml(format_zatca_signed_xml(updated_xml_string)) as sample_path:
            return compliance_api_call(
                uuid1, encoded_hash, sample_path, company_abbr, source_doc
            )

    except DeclaredVatError:
        raise
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.log_error(
            title="ZATCA invoice call failed", message=frappe.get_traceback()
        )
        frappe.throw(_("Error in ZATCA invoice call: " + str(e)))
        return None
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

def zatca_call_compliance(
    invoice_number,
    company_abbr,
    compliance_type="0",
    any_item_has_tax_template=False,
    source_doc=None,
    validation_type=None,
):
    """Function for zatca call compliance"""

    try:

        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")

        if not company_name:
            frappe.throw(f"Company with abbreviation {company_abbr} not found.")

        company_doc = frappe.get_doc("Company", company_name)

        try:
            compliance_type = resolve_compliance_type(
                company_doc.custom_validation_type if validation_type is None else validation_type,
                fallback=compliance_type if validation_type is None else "0",
            )
        except ValueError:
            frappe.throw(_("Select a valid ZATCA compliance document type."))
        # Validate the invoice number
        if not frappe.db.exists("POS Invoice", invoice_number):
            frappe.throw("Invoice Number is NOT Valid1: " + str(invoice_number))

        # Fetch and process the sales invoice data
        invoice = xml_tags()
        invoice, uuid1, pos_invoice_doc = salesinvoice_data(
            invoice, invoice_number, purpose="compliance"
        )
        if source_doc is None:
            source_doc = pos_invoice_doc
        if pos_invoice_doc.company != company_doc.name:
            frappe.throw(
                _("Sample Invoice {0} belongs to Company {1}, not selected Company {2}.").format(
                    invoice_number, pos_invoice_doc.company, company_doc.name
                )
            )
        # Check if any item has a tax template and validate it
        any_item_has_tax_template = any(
            item.item_tax_template for item in pos_invoice_doc.items
        )
        if any_item_has_tax_template and not all(
            item.item_tax_template for item in pos_invoice_doc.items
        ):
            frappe.throw(ITEM_TAX_TEMPLATE_WARNING)

        invoice = invoice_typecode_compliance(invoice, compliance_type)
        invoice = populate_invoice_parties(
            invoice, pos_invoice_doc, invoice_number, company_abbr,
            tools=PartyXmlTools.from_namespace(
                globals(), doctype="POS Invoice", purpose="compliance",
            ),
            compliance_type=compliance_type,
        )
        invoice = populate_pos_financials(
            invoice, pos_invoice_doc, namespace=globals(),
            has_template=any_item_has_tax_template,
            use_item_result=not bool(any_item_has_tax_template),
        )

        # Generate and process the XML data
        file_content = xml_structuring(invoice)

        signed_xml = sign_invoice_xml(
            file_content, company_abbr, source_doc,
            tools=SigningTools.from_namespace(globals()),
        )
        encoded_hash = signed_xml.encoded_hash
        qrcodeb64 = signed_xml.qr_payload
        updated_xml_string = signed_xml.xml
        with temporary_compliance_xml(format_zatca_signed_xml(updated_xml_string)) as sample_path:
            return compliance_api_call(
                uuid1, encoded_hash, sample_path, company_abbr, source_doc
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
        frappe.throw(_("Error in ZATCA invoice call: " + str(e)))
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

        # Resolve the actual invoice rows instead of trusting the optional JS flag.
        any_item_has_tax_template = any(
            bool(getattr(item, "item_tax_template", None))
            for item in (getattr(sales_invoice_doc, "items", None) or [])
        )
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
