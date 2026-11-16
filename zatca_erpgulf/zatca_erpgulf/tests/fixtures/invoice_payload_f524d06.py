"""Frozen increment227 API/payload consumers; offline test reference only."""

SOURCES = {
'zatca_erpgulf/zatca_erpgulf/sign_invoice.py': r'''
def _attach_reported_xml(signed_xmlfile_name, sales_invoice_doc):
    """Attach the submitted XML only after Reporting accepted it."""
    xml_base64 = xml_base64_decode(signed_xmlfile_name)
    xml_content = base64.b64decode(xml_base64).decode("utf-8")
    file = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": "Reported xml file " + sales_invoice_doc.name + ".xml",
            "attached_to_doctype": sales_invoice_doc.doctype,
            "is_private": 1,
            "attached_to_name": sales_invoice_doc.name,
            "content": xml_content,
        }
    )
    file.save(ignore_permissions=True)
    sales_invoice_doc.db_set("custom_ksa_einvoicing_xml", file.file_url)

def _extract_qr_payload(signed_xmlfile_name):
    """Read the exact QR TLV payload embedded in the XML submitted to ZATCA."""
    root = etree.parse(signed_xmlfile_name)
    nodes = root.xpath(
        "//*[local-name()='AdditionalDocumentReference'][*[local-name()='ID' and normalize-space(.)='QR']]"
        "//*[local-name()='EmbeddedDocumentBinaryObject']"
    )
    return nodes[0].text.strip() if nodes and nodes[0].text else None

def reporting_api(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, sales_invoice_doc
):
    """reporting api based on the api data and payload"""
    # Reject stored-link/schema problems before HTTP AND legacy error writes.
    require_primary_qr_attachment(sales_invoice_doc, expected_doctype="Sales Invoice")
    processing_response = local_response_failure = False
    try:
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )

        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {sales_invoice_doc.company} not found.")
            )
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        submission = get_submission_context(
            company_abbr, sales_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="Sales Invoice",
        )
        # Reporting accepts the invoice hash and signed invoice payload.
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }
        headers = {
            "accept": "application/json",
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": "application/json",
        }
        if get_b2c_submission_method(company_doc) != "Batches":
            try:
                frappe.publish_realtime(
                    "show_gif",
                    {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                    user=frappe.session.user,
                )
                response = requests.post(
                    url=submission.route.url,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                # Guard selected local processing for EVERY received status,
                # not deliberate rejection throws or the transport call itself.
                response_step = partial(
                    run_received_response_step, validation_error_type=frappe.ValidationError
                )
                render_response = partial(response_step, received_response_message, format_zatca_response)
                # Error boundary only: HTTP status is NOT acceptance evidence.
                processing_response = response.status_code in (200, 202, 409)
                response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
                # Classify and log ZATCA API responses
                if response.status_code in (200, 202, 409):
                    if response.status_code == 200:
                        status_label = "Success"
                        title = f"ZATCA Success - {invoice_number}"
                    elif response.status_code == 202:
                        status_label = "Warning"
                        title = f"ZATCA Invoice with Warnings - {invoice_number}"
                    elif response.status_code == 409:
                        status_label = "Success (Duplicate Invoice)"
                        title = f"ZATCA Duplicate Success - {invoice_number}"

                    msg = (
                        f"{_('Status Code')}: {response.status_code}<br>"
                        f"{_('ZATCA Response')}: {render_response(response)}"
                    )

                    response_step(
                        log_zatca_event,
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )

                else:
                    # All other codes are failures
                    status_label = f"Failed (HTTP {response.status_code})"
                    title = f"ZATCA API Failed - {invoice_number}"
                    msg = (
                        f"{_('Status Code')}: {response.status_code}<br>"
                        f"{_('ZATCA Response')}: {render_response(response)}"
                    )

                    response_step(
                        log_zatca_event,
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )

                if response.status_code in (400, 405, 406):
                    response_step(_persist_reporting_rejection, invoice_number, response)
                    frappe.throw(
                        _(
                            (
                                "Error: The request you are sending to ZATCA is in incorrect format. "
                                "Please report to system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{render_response(response)}"
                            )
                        )
                    )

                if response.status_code in (401, 403, 407, 451):
                    response_step(_persist_reporting_rejection, invoice_number, response)
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA Authentication failed. "
                                "Your access token may be expired or not valid. "
                                "Please contact your system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{render_response(response)}"
                            )
                        )
                    )
                if response.status_code == 409:
                    msg = _("Submission successful:") + "<br><br>"
                    msg += (
                        f"{_('Status Code')}: {response.status_code}<br><br> "
                        f"{_('ZATCA Response')}: {render_response(response)}<br><br>"
                    )

                    # Update PIH
                    record_submission_owner_success(
                        submission, encoded_hash, sales_invoice_doc, msg
                    )

                    _attach_reported_xml(signed_xmlfile_name, sales_invoice_doc)
                    # Persist the exact QR that was submitted after Reporting accepts it.
                    qr_payload = _extract_qr_payload(signed_xmlfile_name)
                    if qr_payload:
                        attach_qr_image(qr_payload, sales_invoice_doc, allow_phase2=True)
                    invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()


                    success_log(response.text, uuid1, invoice_number)

                if response.status_code not in (200, 202, 409):
                    response_step(_persist_reporting_rejection, invoice_number, response)
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA server busy or not responding."
                                " Try after sometime or contact your system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{render_response(response)}"
                            )
                        )
                    )

                if response.status_code in (200, 202):
                    msg = (
                        _("Submission successful:") + "<br><br>"
                        if response.status_code == 200
                        else (
                            "REPORTED WITH WARNINGS: <br><br> "
                            "Please copy the below message and send it to your system administrator "
                            "to fix this warnings before next submission <br><br>"
                        )
                    )
                    msg += (
                        f"{_('Status Code')}: {response.status_code}<br><br> "
                        f"{_('ZATCA Response')}: {render_response(response)}<br><br>"
                    )
                    record_submission_owner_success(
                        submission, encoded_hash, sales_invoice_doc, msg
                    )

                    _attach_reported_xml(signed_xmlfile_name, sales_invoice_doc)
                    # Persist the exact QR that was submitted after Reporting accepts it.
                    qr_payload = _extract_qr_payload(signed_xmlfile_name)
                    if qr_payload:
                        attach_qr_image(qr_payload, sales_invoice_doc, allow_phase2=True)
                    invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     msg,
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_uuid", uuid1, commit=True, update_modified=True
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "REPORTED",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()
                    success_log(response.text, uuid1, invoice_number)
                else:

                    error_log()

            except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
                if processing_response:
                    raise  # Outer boundary suppresses legacy error persistence.
                frappe.throw(_(f"Error in reporting API-2 original reporting: {str(e)}"))

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        if processing_response:
            local_response_failure = True
        else:
            invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
            invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
            invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
            frappe.db.commit()
            frappe.throw(_(f"Error in reporting API-1: {str(e)}"))
    if local_response_failure:
        raise_local_response_review()

def clearance_api(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, sales_invoice_doc
):
    """The clearance api with payload and headeders aand signed xml data"""
    require_primary_qr_attachment(sales_invoice_doc, expected_doctype="Sales Invoice")
    processing_response = local_response_failure = False
    try:
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )
        if not company_abbr:
            frappe.throw(
                _(
                    f" problem with company name in {sales_invoice_doc.company} not found."
                )
            )
        submission = get_submission_context(
            company_abbr, sales_invoice_doc, invoice_number, "invoices/clearance/single",
            expected_doctype="Sales Invoice",
        )
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }

        headers = {
            "accept": "application/json",
            "accept-language": "en",
            "Clearance-Status": "1",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": "application/json",
        }
        frappe.publish_realtime(
            "show_gif",
            {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
            user=frappe.session.user,
        )

        response = requests.post(
            url=submission.route.url,
            headers=headers,
            json=payload,
            timeout=300,
        )
        # Presentation failures cannot replace a received rejection/error with
        # generic local failure writes. Normal rejection handling stays below.
        response_step = partial(
            run_received_response_step, validation_error_type=frappe.ValidationError
        )
        render_response = partial(response_step, received_response_message, format_zatca_response)
        # Preserve the legacy branch set without treating status as proof.
        processing_response = response.status_code in (200, 202, 409)

        if response.status_code in (200, 202, 409):
            if response.status_code == 200:
                status_label = "Success"
                title = f"ZATCA Success - {invoice_number}"
            elif response.status_code == 202:
                status_label = "Warning"
                title = f"ZATCA Invoice with Warnings - {invoice_number}"
            elif response.status_code == 409:
                status_label = "Success (Duplicate Invoice)"
                title = f"ZATCA Duplicate Success - {invoice_number}"

            msg = (
                f"{_('Status Code')}: {response.status_code}<br>"
                f"{_('ZATCA Response')}: {render_response(response)}"
            )

            response_step(
                log_zatca_event,
                invoice_number=invoice_number,
                response_text=msg,
                status=status_label,
                uuid=uuid1,
                title=title
            )

        else:
                    # All other codes are failures
            status_label = f"Failed (HTTP {response.status_code})"
            title = f"ZATCA API Failed - {invoice_number}"
            msg = (
                f"{_('Status Code')}: {response.status_code}<br>"
                f"{_('ZATCA Response')}: {render_response(response)}"
            )

            response_step(
                log_zatca_event,
                invoice_number=invoice_number,
                response_text=msg,
                status=status_label,
                uuid=uuid1,
                title=title
            )
        response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
        if response.status_code == 303:
            invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
            invoice_doc.db_set(
                "custom_zatca_status", "Not Submitted", commit=True, update_modified=True
            )
            invoice_doc.db_set(
                "custom_zatca_full_response",
                "ZATCA Clearance is disabled; submit through the Reporting API.",
                commit=True,
                update_modified=True,
            )
            return "CLEARANCE_DISABLED"
        if response.status_code in (400, 405, 406):
            response_step(_persist_clearance_rejection, invoice_number, response)
            frappe.throw(
                _(
                    (
                        "Error: The request you are sending to ZATCA is in incorrect format. "
                        f"Status code: {response.status_code}<br><br>"
                        f"{render_response(response)}"
                    )
                )
            )
        if response.status_code in (401, 403, 407, 451):
            response_step(_persist_clearance_rejection, invoice_number, response)
            frappe.throw(
                _(
                    (
                        "Error: ZATCA Authentication failed. "
                        f"Status code: {response.status_code}<br><br>"
                        f"{render_response(response)}"
                    )
                )
            )

        if response.status_code == 409:
            msg = _("Submission successful:") + "<br><br>"
            msg += (
                f"{_('Status Code')}: {response.status_code}<br><br> "
                f"{_('ZATCA Response')}: {render_response(response)}<br><br>"
            )

            # Update PIH
            record_submission_owner_success(
                submission, encoded_hash, sales_invoice_doc, msg
            )

            invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
            invoice_doc.custom_zatca_full_response = response.text
            invoice_doc.custom_uuid = uuid1
            invoice_doc.custom_zatca_status = "CLEARED"
            invoice_doc.save(ignore_permissions=True)
            frappe.db.commit()


            success_log(response.text, uuid1, invoice_number)
        # else:

        #     error_log()
        if response.status_code not in (200, 202, 409):
            response_step(_persist_clearance_rejection, invoice_number, response)
            frappe.throw(
                _(
                    f"Error: ZATCA server busy or not responding. Status code: {response.status_code}"
                )
            )

        if response.status_code in (200, 202):
            msg = (
                "CLEARED WITH WARNINGS: <br><br>"
                if response.status_code == 202
                else _("Submission successful:") + "<br><br>"
            )
            msg += (
                f"{_('Status Code')}: {response.status_code}<br><br>"
                f"{_('ZATCA Response')}: {render_response(response)}<br><br>"
            )

            record_submission_owner_success(
                submission, encoded_hash, sales_invoice_doc, msg
            )

            invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
            set_zatca_full_response(
                invoice_doc, response.text, commit=True, update_modified=True
            )
            invoice_doc.db_set("custom_uuid", uuid1, commit=True, update_modified=True)
            invoice_doc.db_set(
                "custom_zatca_status", "CLEARED", commit=True, update_modified=True
            )

            data = response.json()
            base64_xml = data.get("clearedInvoice")
            xml_cleared = base64.b64decode(base64_xml).decode("utf-8")
            file = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": "Cleared xml file " + sales_invoice_doc.name + ".xml",
                    "attached_to_doctype": sales_invoice_doc.doctype,
                    "is_private": 1,
                    "attached_to_name": sales_invoice_doc.name,
                    "content": xml_cleared,
                }
            )
            file.save(ignore_permissions=True)
            sales_invoice_doc.db_set("custom_ksa_einvoicing_xml", file.file_url)

            # ZATCA returns the authoritative QR inside clearedInvoice. The
            # phase-2 on_submit hook runs before this response is stored, and
            # db_set does not fire on_update_after_submit, so create the image
            # here while the response XML is available. This is local only;
            # it never submits the invoice again.
            qr_payload = _extract_qr_payload_from_xml(xml_cleared.encode("utf-8"))
            if qr_payload:
                attach_qr_image(
                    qr_payload,
                    invoice_doc,
                    allow_phase2=True,
                    phase2_status="CLEARED",
                )
            success_log(response.text, uuid1, invoice_number)
            return xml_cleared
        else:
            error_log()

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        if processing_response:
            local_response_failure = True
        else:
            invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
            invoice_doc.db_set(
                "custom_zatca_full_response",
                f"Error: {str(e)}",
                commit=True,
                update_modified=True,
            )
            invoice_doc.db_set(
                "custom_zatca_status",
                "503 Service Unavailable",
                commit=True,
                update_modified=True,
            )
            frappe.throw(_(f"Error in clearance API: {str(e)}"))
    if local_response_failure:
        raise_local_response_review()
''',
'zatca_erpgulf/zatca_erpgulf/pos_sign.py': r'''
def reporting_api(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, pos_invoice_doc
):
    """Function for reporting api"""
    # Before legacy POS XML creation and any HTTP/error-persistence side effects.
    require_primary_qr_attachment(pos_invoice_doc, expected_doctype="POS Invoice")
    processing_response = local_response_failure = False
    try:
        # Retrieve the company abbreviation based on the company in the sales invoice
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )

        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {pos_invoice_doc.company} not found.")
            )

        # Retrieve the company document using the abbreviation
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        submission = get_submission_context(
            company_abbr, pos_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="POS Invoice",
        )

        # Prepare the payload without JSON formatting
        xml_base64 = xml_base64_decode(signed_xmlfile_name)

        xml_cleared_data = base64.b64decode(xml_base64).decode("utf-8")
        file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "Reported xml file " + pos_invoice_doc.name + ".xml",
                "is_private": 1,
                "attached_to_doctype": pos_invoice_doc.doctype,
                "attached_to_name": pos_invoice_doc.name,
                "content": xml_cleared_data,
            }
        )
        file.is_private = 1
        file.save(ignore_permissions=True)
        pos_invoice_doc.db_set("custom_ksa_einvoicing_xml", file.file_url)
        if file.is_private == 0:
            frappe.db.set_value("File", file.name, "is_private", 1)
            frappe.db.commit()
        # file.reload()
        # frappe.throw(file.is_private)
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }

        headers = {
            "accept": CONTENT_TYPE_JSON,
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": CONTENT_TYPE_JSON,
            "Cookie": (
                "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119d"
                "cdd3b817f963ec301682dae864351c67ee3a402866"
            ),
        }
        if company_doc.custom_send_invoice_to_zatca != "Batches":
            try:
                frappe.publish_realtime(
                    "show_gif",
                    {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                    user=frappe.session.user,
                )
                response = requests.post(
                    url=submission.route.url,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                # Local rendering/logging is separate from intentional HTTP
                # rejection handling for both successful and error statuses.
                response_step = partial(
                    run_received_response_step, validation_error_type=frappe.ValidationError
                )
                render_response = partial(response_step, received_response_message, format_zatca_response)
                # Error boundary only, not authority acceptance classification.
                processing_response = response.status_code in (200, 202, 409)
                response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
                if response.status_code in (200, 202, 409):
                    if response.status_code == 200:
                            status_label = "Success"
                            title = f"ZATCA Success - {invoice_number}"
                    elif response.status_code == 202:
                        status_label = "Warning"
                        title = f"ZATCA Invoice with Warnings - {invoice_number}"
                    elif response.status_code == 409:
                        status_label = "Success (Duplicate Invoice)"
                        title = f"ZATCA Duplicate Success - {invoice_number}"

                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {render_response(response)}"
                    )

                    response_step(
                        log_zatca_event,
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )

                else:

                    status_label = f"Failed (HTTP {response.status_code})"
                    title = f"ZATCA API Failed - {invoice_number}"
                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {render_response(response)}"
                    )
                    response_step(
                        log_zatca_event,
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )
                if response.status_code in (400, 405, 406):
                    response_step(_persist_pos_rejection, invoice_number)
                    frappe.throw(
                        _(
                            (
                                "Error: The request you are sending to ZATCA is in incorrect format. "
                                "Please report to system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{render_response(response)}"
                            )
                        )
                    )

                if response.status_code in (401, 403, 407, 451):
                    response_step(_persist_pos_rejection, invoice_number)
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA Authentication failed."
                                "Your access token may be expired or not valid. "
                                "Please contact your system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{render_response(response)}"
                            )
                        )
                    )
                if response.status_code == 409:
                    msg = "SUCCESS: <br><br>"
                    msg += (
                        f"Status Code: {response.status_code}<br><br> "
                        f"ZATCA Response: {render_response(response)}<br><br>"
                    )

                    # Update PIH
                    record_submission_owner_success(
                        submission, encoded_hash, pos_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()


                    success_log(response.text, uuid1, invoice_number)

                if response.status_code not in (200, 202, 409):
                    response_step(_persist_pos_rejection, invoice_number)
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA server busy or not responding."
                                " Try after sometime or contact your system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{render_response(response)}"
                            )
                        )
                    )

                if response.status_code in (200, 202):
                    msg = (
                        "SUCCESS: <br><br>"
                        if response.status_code == 200
                        else (
                            "REPORTED WITH WARNINGS: <br><br> "
                            "Please copy the below message and send it to your system administrator "
                            "to fix this warnings before next submission <br><br>"
                        )
                    )
                    msg += (
                        f"Status Code: {response.status_code}<br><br>"
                        f"ZATCA Response: {render_response(response)}<br><br>"
                    )

                    record_submission_owner_success(
                        submission, encoded_hash, pos_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
                    invoice_doc.db_set(
                        "custom_zatca_full_response",
                        msg,
                        commit=True,
                        update_modified=True,
                    )
                    invoice_doc.db_set(
                        "custom_uuid", uuid1, commit=True, update_modified=True
                    )
                    invoice_doc.db_set(
                        "custom_zatca_status",
                        "REPORTED",
                        commit=True,
                        update_modified=True,
                    )

                    success_log(response.text, uuid1, invoice_number)
                else:
                    error_log()
            except (ValueError, TypeError, KeyError) as e:
                if processing_response:
                    raise
                frappe.throw(_(("Error in reporting API-2 Normal POS invoice" f"error: {str(e)}")))

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        if processing_response:
            local_response_failure = True
        else:
            invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
            invoice_doc.db_set(
                "custom_zatca_full_response",
                f"Error: {str(e)}",
                commit=True,
                update_modified=True,
            )
            frappe.throw(_(("Error in reporting API-1 " f"error: {str(e)}")))
    if local_response_failure:
        raise_local_response_review()

def clearance_api(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, pos_invoice_doc
):
    """Function for clearence api"""
    require_primary_qr_attachment(pos_invoice_doc, expected_doctype="POS Invoice")
    processing_response = local_response_failure = False
    try:
        # Retrieve the company name based on the abbreviation in the POS Invoice
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )
        if not company_abbr:
            frappe.throw(
                _(
                    (
                        "There is a problem with company name in invoice "
                        f"{pos_invoice_doc.company} not found."
                    )
                )
            )

        submission = get_submission_context(
            company_abbr, pos_invoice_doc, invoice_number, "invoices/clearance/single",
            expected_doctype="POS Invoice",
        )
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }

        headers = {
            "accept": CONTENT_TYPE_JSON,
            "accept-language": "en",
            "Clearance-Status": "1",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": CONTENT_TYPE_JSON,
            "Cookie": (
                "TS0106293e=0132a679c03c628e6c49de86c0f6bb76390abb4416868d6368d6d7c05da619c8"
                "326266f5bc262b7c0c65a6863cd3b19081d64eee99"
            ),
        }
        frappe.publish_realtime(
            "show_gif",
            {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
            user=frappe.session.user,
        )
        response = requests.post(
            url=submission.route.url,
            headers=headers,
            json=payload,
            timeout=300,
        )
        # Only local display/log steps use the guard, not the rejection throws.
        response_step = partial(
            run_received_response_step, validation_error_type=frappe.ValidationError
        )
        render_response = partial(response_step, received_response_message, format_zatca_response)
        # POS clearance's legacy 409 rejection remains a separate outcome gate.
        processing_response = response.status_code in (200, 202)
        response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
        if response.status_code in (200, 202, 409):
            if response.status_code == 200:
                    status_label = "Success"
                    title = f"ZATCA Success - {invoice_number}"
            elif response.status_code == 202:
                status_label = "Warning"
                title = f"ZATCA Invoice with Warnings - {invoice_number}"
            elif response.status_code == 409:
                status_label = "Success (Duplicate Invoice)"
                title = f"ZATCA Duplicate Success - {invoice_number}"

            msg = (
                f"Status Code: {response.status_code}<br>"
                f"ZATCA Response: {render_response(response)}"
            )

            response_step(
                log_zatca_event,
                invoice_number=invoice_number,
                response_text=msg,
                status=status_label,
                uuid=uuid1,
                title=title
            )

        else:

            status_label = f"Failed (HTTP {response.status_code})"
            title = f"ZATCA API Failed - {invoice_number}"
            msg = (
                f"Status Code: {response.status_code}<br>"
                f"ZATCA Response: {render_response(response)}"
            )
            response_step(
                log_zatca_event,
                invoice_number=invoice_number,
                response_text=msg,
                status=status_label,
                uuid=uuid1,
                title=title
            )
        if response.status_code in (400, 405, 406, 409):
            response_step(_persist_pos_rejection, invoice_number)
            frappe.throw(
                _(
                    (
                        "Error: The request you are sending to ZATCA is in incorrect format. "
                        f"Status code: {response.status_code}<br><br>"
                        f"{render_response(response)}"
                    )
                )
            )

        if response.status_code in (401, 403, 407, 451):
            response_step(_persist_pos_rejection, invoice_number)
            frappe.throw(
                _(
                    (
                        "Error: ZATCA Authentication failed. "
                        f"Status code: {response.status_code}<br><br>"
                        f"{render_response(response)}"
                    )
                )
            )

        if response.status_code not in (200, 202):
            response_step(_persist_pos_rejection, invoice_number)
            frappe.throw(
                _(
                    f"Error: ZATCA server busy or not responding. Status code: {response.status_code}"
                )
            )

        if response.status_code in (200, 202):
            msg = (
                "CLEARED WITH WARNINGS: <br><br>"
                if response.status_code == 202
                else "SUCCESS: <br><br>"
            )
            msg += (
                f"Status Code: {response.status_code}<br><br>"
                f"ZATCA Response: {render_response(response)}<br><br>"
            )

            record_submission_owner_success(
                submission, encoded_hash, pos_invoice_doc, msg
            )

            invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
            set_zatca_full_response(
                invoice_doc, response.text, commit=True, update_modified=True
            )
            invoice_doc.db_set("custom_uuid", uuid1, commit=True, update_modified=True)
            invoice_doc.db_set(
                "custom_zatca_status", "CLEARED", commit=True, update_modified=True
            )

            data = response.json()
            base64_xml = data.get("clearedInvoice")
            xml_cleared = base64.b64decode(base64_xml).decode("utf-8")
            file = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": "Cleared xml file " + pos_invoice_doc.name + ".xml",
                    "is_private": 1,  # Ensure this is explicitly set
                    "attached_to_doctype": pos_invoice_doc.doctype,
                    "attached_to_name": pos_invoice_doc.name,
                    "content": xml_cleared,
                }
            )

            file.is_private = 1  # Force private before saving
            file.save(ignore_permissions=True)
            if file.is_private == 0:
                frappe.db.set_value("File", file.name, "is_private", 1)
                frappe.db.commit()

            # Build the local QR from ZATCA's authoritative clearedInvoice
            # without submitting the POS invoice again.
            qr_payload = _extract_qr_payload_from_xml(xml_cleared.encode("utf-8"))
            if qr_payload:
                attach_qr_image(
                    qr_payload,
                    invoice_doc,
                    allow_phase2=True,
                    phase2_status="CLEARED",
                )

            success_log(response.text, uuid1, invoice_number)
            return xml_cleared
        else:
            error_log()
            return None

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        if processing_response:
            local_response_failure = True
        else:
            invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
            invoice_doc.db_set(
                "custom_zatca_full_response",
                f"Error: {str(e)}",
                commit=True,
                update_modified=True,
            )
            invoice_doc.db_set(
                "custom_zatca_status",
                "503 Service Unavailable",
                commit=True,
                update_modified=True,
            )
            frappe.throw(_(("Error in clearance API " f"error: {str(e)}")))
            return None
    if local_response_failure:
        raise_local_response_review()
''',
'zatca_erpgulf/zatca_erpgulf/sales_invoice_withoutxml.py': r'''
def reporting_api_sales_withoutxml(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, sales_invoice_doc
):
    """reporting api based on the api data and payload"""
    try:
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )

        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {sales_invoice_doc.company} not found.")
            )
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        submission = get_submission_context(
            company_abbr, sales_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="Sales Invoice", require_issuing_unit=True,
        )
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }
        xml_base64 = xml_base64_decode(signed_xmlfile_name)

        xml_cleared_data = base64.b64decode(xml_base64).decode("utf-8")
        file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "Reported xml file " + sales_invoice_doc.name + ".xml",
                "attached_to_doctype": sales_invoice_doc.doctype,
                "is_private": 1,
                "attached_to_name": sales_invoice_doc.name,
                "content": xml_cleared_data,
            }
        )
        file.save(ignore_permissions=True)
        sales_invoice_doc.db_set("custom_ksa_einvoicing_xml", file.file_url)
        headers = {
            "accept": "application/json",
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": "application/json",
            "Cookie": "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119dcdd3b817f963ec301682dae864351c67ee3a402866",
        }
        if company_doc.custom_send_invoice_to_zatca != "Batches":
            try:
                frappe.publish_realtime(
                    "show_gif",
                    {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                    user=frappe.session.user,
                )
                response = requests.post(
                    url=submission.route.url,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                frappe.publish_realtime("hide_gif", user=frappe.session.user)
                if response.status_code in (200, 202, 409):
                    if response.status_code == 200:
                        status_label = "Success"
                        title = f"ZATCA Success - {invoice_number}"
                    elif response.status_code == 202:
                        status_label = "Warning"
                        title = f"ZATCA Invoice with Warnings - {invoice_number}"
                    elif response.status_code == 409:
                        status_label = "Success (Duplicate Invoice)"
                        title = f"ZATCA Duplicate Success - {invoice_number}"

                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}"
                    )

                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )

                else:

                    status_label = f"Failed (HTTP {response.status_code})"
                    title = f"ZATCA API Failed - {invoice_number}"
                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}"
                    )
                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )
                if response.status_code in (400, 405, 406):
                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()

                    frappe.throw(
                        _(
                            (
                                "Error: The request you are sending to ZATCA is in incorrect format. "
                                "Please report to system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )

                if response.status_code in (401, 403, 407, 451):
                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA Authentication failed. "
                                "Your access token may be expired or not valid. "
                                "Please contact your system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )
                if response.status_code == 409:
                    msg = "SUCCESS: <br><br>"
                    msg += (
                        f"Status Code: {response.status_code}<br><br> "
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}<br><br>"
                    )

                    # Update PIH
                    record_submission_owner_success(
                        submission, encoded_hash, sales_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()


                    success_log(response.text, uuid1, invoice_number)
                # else:

                #     error_log()
                if response.status_code not in (200, 202, 409):
                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA server busy or not responding."
                                " Try after sometime or contact your system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )

                if response.status_code in (200, 202):
                    msg = (
                        "SUCCESS: <br><br>"
                        if response.status_code == 200
                        else (
                            "REPORTED WITH WARNINGS: <br><br> "
                            "Please copy the below message and send it to your system administrator "
                            "to fix this warnings before next submission <br><br>"
                        )
                    )
                    msg += (
                        f"Status Code: {response.status_code}<br><br> "
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}<br><br>"
                    )

                    record_submission_owner_success(
                        submission, encoded_hash, sales_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     msg,
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_uuid", uuid1, commit=True, update_modified=True
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "REPORTED",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()

                    success_log(response.text, uuid1, invoice_number)
                else:

                    error_log()


            except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
                frappe.throw(
                    _(f"Error in reporting API-2 sales invoice without xmldata: {str(e)}")
                )

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
        # invoice_doc.db_set(
        #     "custom_zatca_full_response",
        #     f"Error: {str(e)}",
        #     commit=True,
        #     update_modified=True,
        # )
        invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
        invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
        frappe.db.commit()
        frappe.throw(_(f"Error in reporting API-1 sales invoice with xml: {str(e)}"))
''',
'zatca_erpgulf/zatca_erpgulf/zatca_background_sched.py': r'''
def reporting_api_sales_withoutxml(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, sales_invoice_doc
):
    """reporting api based on the api data and payload"""
    try:
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )

        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {sales_invoice_doc.company} not found.")
            )
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        submission = get_submission_context(
            company_abbr, sales_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="Sales Invoice",
        )
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }
        xml_base64 = xml_base64_decode(signed_xmlfile_name)

        xml_cleared_data = base64.b64decode(xml_base64).decode("utf-8")
        file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "Reported xml file " + sales_invoice_doc.name + ".xml",
                "attached_to_doctype": sales_invoice_doc.doctype,
                "is_private": 1,
                "attached_to_name": sales_invoice_doc.name,
                "content": xml_cleared_data,
            }
        )
        file.save(ignore_permissions=True)
        sales_invoice_doc.db_set("custom_ksa_einvoicing_xml", file.file_url)

        headers = {
            "accept": "application/json",
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": "application/json",
            "Cookie": "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119dcdd3b817f963ec301682dae864351c67ee3a402866",
        }
        if company_doc.custom_send_invoice_to_zatca not in ["Batches", "Background"]:


            try:
                frappe.publish_realtime(
                    "show_gif",
                    {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                    user=frappe.session.user,
                )

                response = requests.post(
                    url=submission.route.url,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )



                if response.status_code in (200, 202, 409):
                    if response.status_code == 200:
                            status_label = "Success"
                            title = f"ZATCA Success - {invoice_number}"
                    elif response.status_code == 202:
                        status_label = "Warning"
                        title = f"ZATCA Invoice with Warnings - {invoice_number}"
                    elif response.status_code == 409:
                        status_label = "Success (Duplicate Invoice)"
                        title = f"ZATCA Duplicate Success - {invoice_number}"

                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {response.text}"
                    )

                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )

                else:

                    status_label = f"Failed (HTTP {response.status_code})"
                    title = f"ZATCA API Failed - {invoice_number}"
                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {response.text}"
                    )
                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )
                frappe.publish_realtime("hide_gif", user=frappe.session.user)

                if response.status_code in (400, 405, 406):
                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()

                    frappe.throw(
                        _(
                            (
                                "Error: The request you are sending to ZATCA is in incorrect format. "
                                "Please report to system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{response.text}"
                            )
                        )
                    )

                if response.status_code in (401, 403, 407, 451):
                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()

                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA Authentication failed. "
                                "Your access token may be expired or not valid. "
                                "Please contact your system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{response.text}"
                            )
                        )
                    )
                if response.status_code == 409:
                    msg = "SUCCESS: <br><br>"
                    msg += (
                        f"Status Code: {response.status_code}<br><br> "
                        f"ZATCA Response: {response.text}<br><br>"
                    )

                    # Update PIH
                    record_submission_owner_success(
                        submission, encoded_hash, sales_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()


                    success_log(response.text, uuid1, invoice_number)
                # else:

                #     error_log()

                if response.status_code not in (200, 202, 409):
                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA server busy or not responding."
                                " Try after sometime or contact your system administrator. "
                                f"Status code: {response.status_code}<br><br>"
                                f"{response.text}"
                            )
                        )
                    )

                if response.status_code in (200, 202):
                    msg = (
                        "SUCCESS: <br><br>"
                        if response.status_code == 200
                        else (
                            "REPORTED WITH WARNINGS: <br><br> "
                            "Please copy the below message and send it to your system administrator "
                            "to fix this warnings before next submission <br><br>"
                        )
                    )
                    msg += (
                        f"Status Code: {response.status_code}<br><br> "
                        f"ZATCA Response: {response.text}<br><br>"
                    )

                    record_submission_owner_success(
                        submission, encoded_hash, sales_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     msg,
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_uuid", uuid1, commit=True, update_modified=True
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "REPORTED",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"

                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()

                    success_log(response.text, uuid1, invoice_number)
                else:

                    error_log()

            except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
                frappe.throw(
                    _(f"Error in reporting API-2 sales invoice without xml in zatca background: {str(e)}")
                )

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)
        # invoice_doc.db_set(
        #     "custom_zatca_full_response",
        #     f"Error: {str(e)}",
        #     commit=True,
        #     update_modified=True,
        # )
        invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
        invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
        frappe.db.commit()
        frappe.throw(_(f"Error in reporting API-1 sales invoice with xml: {str(e)}"))
''',
'zatca_erpgulf/zatca_erpgulf/pos_submit__without_xml.py': r'''
def reporting_api_pos_without_xml(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, pos_invoice_doc
):
    """Function for reporting api"""
    try:
        # Retrieve the company abbreviation based on the company in the sales invoice
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        submission = get_submission_context(
            company_abbr, pos_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="POS Invoice", require_issuing_unit=True,
        )
        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {pos_invoice_doc.company} not found.")
            )

        # Prepare the payload without JSON formatting
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }
        xml_base64 = xml_base64_decode(signed_xmlfile_name)

        xml_cleared_data = base64.b64decode(xml_base64).decode("utf-8")
        file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "Reported xml file " + pos_invoice_doc.name + ".xml",
                "attached_to_doctype": pos_invoice_doc.doctype,
                "is_private": 1,
                "attached_to_name": pos_invoice_doc.name,
                "content": xml_cleared_data,
            }
        )
        file.is_private = 1
        file.save(ignore_permissions=True)
        pos_invoice_doc.db_set("custom_ksa_einvoicing_xml", file.file_url)
        if file.is_private == 0:
            frappe.db.set_value("File", file.name, "is_private", 1)
            frappe.db.commit()
        # Directly retrieve the production CSID from the company's document field
        headers = {
            "accept": CONTENT_TYPE_JSON,
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": CONTENT_TYPE_JSON,
            "Cookie": (
                "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119d"
                "cdd3b817f963ec301682dae864351c67ee3a402866"
            ),
        }
        if company_doc.custom_send_invoice_to_zatca != "Batches":
            try:
                frappe.publish_realtime(
                    "show_gif",
                    {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                    user=frappe.session.user,
                )
                response = requests.post(
                    url=submission.route.url,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                frappe.publish_realtime("hide_gif", user=frappe.session.user)
                if response.status_code in (200, 202, 409):
                    if response.status_code == 200:
                            status_label = "Success"
                            title = f"ZATCA Success - {invoice_number}"
                    elif response.status_code == 202:
                        status_label = "Warning"
                        title = f"ZATCA Invoice with Warnings - {invoice_number}"
                    elif response.status_code == 409:
                        status_label = "Success (Duplicate Invoice)"
                        title = f"ZATCA Duplicate Success - {invoice_number}"

                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}"
                    )

                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )

                else:

                    status_label = f"Failed (HTTP {response.status_code})"
                    title = f"ZATCA API Failed - {invoice_number}"
                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}"
                    )
                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )
                if response.status_code in (400, 405, 406):
                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()
                    frappe.throw(
                        _(
                            (
                                "Error: The request you are sending to ZATCA is in incorrect format. "
                                "Please report to system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )

                if response.status_code in (401, 403, 407, 451):
                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA Authentication failed."
                                "Your access token may be expired or not valid. "
                                "Please contact your system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )
                if response.status_code == 409:
                    msg = "SUCCESS: <br><br>"
                    msg += (
                        f"Status Code: {response.status_code}<br><br> "
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}<br><br>"
                    )

                    # Update PIH
                    record_submission_owner_success(
                        submission, encoded_hash, pos_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()


                    success_log(response.text, uuid1, invoice_number)
                # else:

                #     error_log()

                if response.status_code not in (200, 202, 409):
                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()

                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA server busy or not responding."
                                " Try after sometime or contact your system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )

                if response.status_code in (200, 202):
                    msg = (
                        "SUCCESS: <br><br>"
                        if response.status_code == 200
                        else (
                            "REPORTED WITH WARNINGS: <br><br> "
                            "Please copy the below message and send it to your system administrator "
                            "to fix this warnings before next submission <br><br>"
                        )
                    )
                    msg += (
                        f"Status Code: {response.status_code}<br><br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}<br><br>"
                    )
                    record_submission_owner_success(
                        submission, encoded_hash, pos_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     msg,
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_uuid", uuid1, commit=True, update_modified=True
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "REPORTED",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()

                    success_log(response.text, uuid1, invoice_number)
                else:
                    error_log()

            except (ValueError, TypeError, KeyError) as e:
                frappe.throw(
                    _(("Error in reporting API-2 pos without xml " f"error: {str(e)}"))
                )

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
        invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
        invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
        frappe.db.commit()
        frappe.throw(_(("Error in reporting API-1 pos without xml" f"error: {str(e)}")))
''',
'zatca_erpgulf/zatca_erpgulf/pos_schedule_background.py': r'''
def reporting_api_pos_without_xml(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, pos_invoice_doc
):
    """Function for reporting api"""
    try:
        # Retrieve the company abbreviation based on the company in the sales invoice
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        submission = get_submission_context(
            company_abbr, pos_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="POS Invoice",
        )
        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {pos_invoice_doc.company} not found.")
            )

        # Prepare the payload without JSON formatting
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }

        # Directly retrieve the production CSID from the company's document field

        xml_base64 = xml_base64_decode(signed_xmlfile_name)

        xml_cleared_data = base64.b64decode(xml_base64).decode("utf-8")
        file = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "Reported xml file " + pos_invoice_doc.name + ".xml",
                "is_private": 1,
                "attached_to_doctype": pos_invoice_doc.doctype,
                "attached_to_name": pos_invoice_doc.name,
                "content": xml_cleared_data,
            }
        )

        file.save(ignore_permissions=True)
        pos_invoice_doc.db_set("custom_ksa_einvoicing_xml", file.file_url)
        headers = {
            "accept": CONTENT_TYPE_JSON,
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": CONTENT_TYPE_JSON,
            "Cookie": (
                "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119d"
                "cdd3b817f963ec301682dae864351c67ee3a402866"
            ),
        }
        if company_doc.custom_send_invoice_to_zatca not in ["Batches", "Background"]:
            try:
                frappe.publish_realtime(
                    "show_gif",
                    {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                    user=frappe.session.user,
                )
                response = requests.post(
                    url=submission.route.url,
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                frappe.publish_realtime("hide_gif", user=frappe.session.user)
                if response.status_code in (200, 202, 409):
                    if response.status_code == 200:
                        status_label = "Success"
                        title = f"ZATCA Success - {invoice_number}"
                    elif response.status_code == 202:
                        status_label = "Warning"
                        title = f"ZATCA Invoice with Warnings - {invoice_number}"
                    elif response.status_code == 409:
                        status_label = "Success (Duplicate Invoice)"
                        title = f"ZATCA Duplicate Success - {invoice_number}"

                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}"
                    )

                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )

                else:

                    status_label = f"Failed (HTTP {response.status_code})"
                    title = f"ZATCA API Failed - {invoice_number}"
                    msg = (
                        f"Status Code: {response.status_code}<br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}"
                    )
                    log_zatca_event(
                        invoice_number=invoice_number,
                        response_text=msg,
                        status=status_label,
                        uuid=uuid1,
                        title=title
                    )
                if response.status_code in (400, 405, 406):
                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()

                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    frappe.throw(
                        _(
                            (
                                "Error: The request you are sending to ZATCA is in incorrect format. "
                                "Please report to system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )

                if response.status_code in (401, 403, 407, 451):
                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()

                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA Authentication failed."
                                "Your access token may be expired or not valid. "
                                "Please contact your system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )
                if response.status_code == 409:
                    msg = "SUCCESS: <br><br>"
                    msg += (
                        f"Status Code: {response.status_code}<br><br> "
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}<br><br>"
                    )

                    # Update PIH
                    record_submission_owner_success(
                        submission, encoded_hash, pos_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()


                    success_log(response.text, uuid1, invoice_number)
                # else:

                #     error_log()

                if response.status_code not in (200, 202, 409):
                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    invoice_doc.custom_uuid = "Not Submitted"
                    invoice_doc.custom_zatca_status = "Not Submitted"
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
                    frappe.db.commit()

                    # invoice_doc.db_set(
                    #     "custom_uuid",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     "Not Submitted",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    frappe.throw(
                        _(
                            (
                                "Error: ZATCA server busy or not responding."
                                " Try after sometime or contact your system administrator. "
                                f"Status code: {response.status_code}<br><br> "
                                f"{format_zatca_response(response.text, response.status_code)}"
                            )
                        )
                    )

                if response.status_code in (200, 202):
                    msg = (
                        "SUCCESS: <br><br>"
                        if response.status_code == 200
                        else (
                            "REPORTED WITH WARNINGS: <br><br> "
                            "Please copy the below message and send it to your system administrator "
                            "to fix this warnings before next submission <br><br>"
                        )
                    )
                    msg += (
                        f"Status Code: {response.status_code}<br><br>"
                        f"ZATCA Response: {format_zatca_response(response.text, response.status_code)}<br><br>"
                    )
                    record_submission_owner_success(
                        submission, encoded_hash, pos_invoice_doc, msg
                    )

                    invoice_doc = frappe.get_doc(POS_INVOICE, invoice_number)
                    # invoice_doc.db_set(
                    #     "custom_zatca_full_response",
                    #     msg,
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    # invoice_doc.db_set(
                    #     "custom_uuid", uuid1, commit=True, update_modified=True
                    # )
                    # invoice_doc.db_set(
                    #     "custom_zatca_status",
                    #     "REPORTED",
                    #     commit=True,
                    #     update_modified=True,
                    # )
                    invoice_doc.custom_zatca_full_response = response.text
                    invoice_doc.custom_uuid = uuid1
                    invoice_doc.custom_zatca_status = "REPORTED"
                    invoice_doc.save(ignore_permissions=True)
                    frappe.db.commit()

                    success_log(response.text, uuid1, invoice_number)
                else:
                    error_log()
            except (ValueError, TypeError, KeyError) as e:
                frappe.throw(
                    _(("Error in reporting API-2 pos without xml " f"error: {str(e)}"))
                )

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.throw(_(("Error in reporting API-1 pos without xml" f"error: {str(e)}")))
''',
'zatca_erpgulf/zatca_erpgulf/submit_xml_qr_notmultiple.py': r'''
def reporting_api_xml_sales_invoice_simplified(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, sales_invoice_doc
):
    """Reporting API based on the API data and payload."""
    try:
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )
        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {sales_invoice_doc.company} not found.")
            )

        submission = get_submission_context(
            company_abbr, sales_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="Sales Invoice",
        )

        # Keep the legacy header helper interface (raw Basic token).
        headers = get_headers(submission.authorization.header.removeprefix("Basic "))
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }


        try:
            frappe.publish_realtime(
                "show_gif",
                {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                user=frappe.session.user,
            )
            # frappe.log_error(
            #         f"Submitting to ZATCA with xml and qr...\n"
            #         f"Time: {frappe.utils.now()}\n"+
            #         f"Invoice No: {invoice_number}\n"
            #         f"UUID: {uuid1 or 'Not Generated'}\n"
            #         f"Status: {sales_invoice_doc.custom_zatca_status or 'Not Set'}",
            #         "ZATCA API Submission with xml and QR"
            #     )
            response = requests.post(
                url=submission.route.url,
                headers=headers,
                json=payload,
                timeout=480,
            )
            # Guard local response steps only; preserve deliberate rejection handling.
            response_step = partial(
                run_received_response_step, validation_error_type=frappe.ValidationError
            )
            render_response = partial(response_step, received_response_message, format_zatca_response)
            persist_reported = partial(
                response_step, persist_existing_xml_reported, frappe,
                "Sales Invoice", invoice_number, response, uuid1,
            )
            persist_rejection = partial(
                response_step, persist_existing_xml_rejection, frappe,
                "Sales Invoice", invoice_number, response,
            )
            response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
            if response.status_code in (200, 202, 409):
                if response.status_code == 200:
                        status_label = "Success"
                        title = f"ZATCA Success - {invoice_number}"
                elif response.status_code == 202:
                    status_label = "Warning"
                    title = f"ZATCA Invoice with Warnings - {invoice_number}"
                elif response.status_code == 409:
                    status_label = "Success (Duplicate Invoice)"
                    title = f"ZATCA Duplicate Success - {invoice_number}"

                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )

                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )

            else:

                status_label = f"Failed (HTTP {response.status_code})"
                title = f"ZATCA API Failed - {invoice_number}"
                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )
                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )
            if response.status_code in (400, 405, 406):
                persist_rejection(commit_uuid=True)
                frappe.throw(
                    _(
                        (
                            "Error: The request you are sending to ZATCA is in incorrect format. "
                            "Please report to system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )
            if response.status_code == 404:
                persist_rejection(commit_uuid=False)
                frappe.throw(
                    _(
                        (
                            "Error: Server response not available. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )

            if response.status_code in (401, 403, 407, 451):
                persist_rejection(commit_uuid=True)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA Authentication failed. "
                            "Your access token may be expired or not valid. "
                            "Please contact your system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )
            if response.status_code == 409:
                msg = "SUCCESS: <br><br>"
                msg += (
                    f"Status Code: {response.status_code}<br><br> "
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )

                # Update PIH
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, sales_invoice_doc, msg
                )

                persist_reported()


                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            # else:

            #     error_log()
            if response.status_code not in (200, 202, 409):
                persist_rejection(commit_uuid=True)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA server busy or not responding."
                            " Try after sometime or contact your system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )


            if response.status_code in (200, 202):
                msg = (
                    "SUCCESS: <br><br>"
                    if response.status_code == 200
                    else (
                        "REPORTED WITH WARNINGS: <br><br> "
                        "Please copy the below message and send it to your system administrator "
                        "to fix this warnings before next submission <br><br>"
                    )
                )
                msg += (
                    f"Status Code: {response.status_code}<br><br> "
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, sales_invoice_doc, msg
                )

                persist_reported()
                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            else:

                response_step(error_log)


        except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
            frappe.throw(_(f"Error in reporting API-2 not qr xml : {str(e)}"))

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)

        invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
        invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
        frappe.db.commit()
        frappe.throw(_(f"Error in reporting API-1 sales invoice with xml: {str(e)}"))
''',
'zatca_erpgulf/zatca_erpgulf/submit_poswithqr_notmultiple.py': r'''
def reporting_api_xml_sales_invoice_simplified(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, pos_invoice_doc
):
    """Reporting API based on the API data and payload."""
    try:
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )
        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {pos_invoice_doc.company} not found.")
            )

        submission = get_submission_context(
            company_abbr, pos_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="POS Invoice",
        )

        # Keep the legacy header helper interface (raw Basic token).
        headers = get_headers(submission.authorization.header.removeprefix("Basic "))
        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }
        try:
            frappe.publish_realtime(
                "show_gif",
                {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                user=frappe.session.user,
            )
            response = requests.post(
                url=submission.route.url,
                headers=headers,
                json=payload,
                timeout=300,
            )
            # Guard local response steps only; preserve deliberate rejection handling.
            response_step = partial(
                run_received_response_step, validation_error_type=frappe.ValidationError
            )
            render_response = partial(response_step, received_response_text)
            persist_reported = partial(
                response_step, persist_existing_xml_reported, frappe,
                "POS Invoice", invoice_number, response, uuid1,
            )
            persist_rejection = partial(
                response_step, persist_existing_xml_rejection, frappe,
                "POS Invoice", invoice_number, response,
            )
            response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
            if response.status_code in (200, 202, 409):
                if response.status_code == 200:
                        status_label = "Success"
                        title = f"ZATCA Success - {invoice_number}"
                elif response.status_code == 202:
                    status_label = "Warning"
                    title = f"ZATCA Invoice with Warnings - {invoice_number}"
                elif response.status_code == 409:
                    status_label = "Success (Duplicate Invoice)"
                    title = f"ZATCA Duplicate Success - {invoice_number}"

                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )

                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )

            else:

                status_label = f"Failed (HTTP {response.status_code})"
                title = f"ZATCA API Failed - {invoice_number}"
                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )
                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )
            if response.status_code in (400, 405, 406):
                persist_rejection(commit_uuid=True)
                frappe.throw(
                    _(
                        (
                            "Error: The request you are sending to ZATCA is in incorrect format. "
                            "Please report to system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )
            if response.status_code == 404:
                persist_rejection(commit_uuid=True)
                frappe.throw(
                    _(
                        (
                            "Error: Server response not available. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )

            if response.status_code in (401, 403, 407, 451):
                persist_rejection(commit_uuid=True)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA Authentication failed. "
                            "Your access token may be expired or not valid. "
                            "Please contact your system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )
            if response.status_code == 409:
                msg = "SUCCESS: <br><br>"
                msg += (
                    f"Status Code: {response.status_code}<br><br> "
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )

                # Update PIH
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, pos_invoice_doc, msg
                )

                persist_reported()


                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            # else:

            #     error_log()
            if response.status_code not in (200, 202, 409):
                persist_rejection(commit_uuid=True)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA server busy or not responding."
                            " Try after sometime or contact your system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )

            if response.status_code in (200, 202):
                msg = (
                    "SUCCESS: <br><br>"
                    if response.status_code == 200
                    else (
                        "REPORTED WITH WARNINGS: <br><br> "
                        "Please copy the below message and send it to your system administrator "
                        "to fix this warnings before next submission <br><br>"
                    )
                )
                msg += (
                    f"Status Code: {response.status_code}<br><br> "
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, pos_invoice_doc, msg
                )

                persist_reported()

                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            else:

                response_step(error_log)

        except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
            frappe.throw(_(f"Error in reporting API-2 reporting simplified : {str(e)}"))

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        invoice_doc = frappe.get_doc(SALES_INVOICE, invoice_number)

        invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
        invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
        frappe.db.commit()
        frappe.throw(_(f"Error in reporting API-1 pos invoice with xml: {str(e)}"))
''',
'zatca_erpgulf/zatca_erpgulf/sales_invoice_with_xmlqr.py': r'''
def reporting_api_xml_sales_invoice(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, sales_invoice_doc
):
    """reporting api based on the api data and payload"""
    try:
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )

        submission = get_submission_context(
            company_abbr, sales_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="Sales Invoice", require_issuing_unit=True,
        )

        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }
        headers = {
            "accept": "application/json",
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": "application/json",
            "Cookie": "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119dcdd3b817f963ec301682dae864351c67ee3a402866",
        }

        try:
            frappe.publish_realtime(
                "show_gif",
                {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                user=frappe.session.user,
            )
            response = requests.post(
                url=submission.route.url,
                headers=headers,
                json=payload,
                timeout=300,
            )
            # Guard local response steps only; preserve deliberate rejection handling.
            response_step = partial(
                run_received_response_step, validation_error_type=frappe.ValidationError
            )
            render_response = partial(response_step, received_response_message, format_zatca_response)
            persist_reported = partial(
                response_step, persist_existing_xml_reported, frappe,
                "Sales Invoice", invoice_number, response, uuid1,
            )
            persist_rejection = partial(
                response_step, persist_existing_xml_rejection, frappe,
                "Sales Invoice", invoice_number, response,
            )
            response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
            if response.status_code in (200, 202, 409):
                if response.status_code == 200:
                    status_label = "Success"
                    title = f"ZATCA Success - {invoice_number}"
                elif response.status_code == 202:
                    status_label = "Warning"
                    title = f"ZATCA Invoice with Warnings - {invoice_number}"
                elif response.status_code == 409:
                    status_label = "Success (Duplicate Invoice)"
                    title = f"ZATCA Duplicate Success - {invoice_number}"

                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )

                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )

            else:

                status_label = f"Failed (HTTP {response.status_code})"
                title = f"ZATCA API Failed - {invoice_number}"
                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )
                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )
            if response.status_code in (400, 405, 406):
                persist_rejection(commit_uuid=False)
                frappe.throw(
                    _(
                        (
                            "Error: The request you are sending to ZATCA is in incorrect format. "
                            "Please report to system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )

            if response.status_code in (401, 403, 407, 451):
                persist_rejection(commit_uuid=False)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA Authentication failed. "
                            "Your access token may be expired or not valid. "
                            "Please contact your system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )
            if response.status_code == 409:
                msg = "SUCCESS: <br><br>"
                msg += (
                    f"Status Code: {response.status_code}<br><br> "
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )

                # Update PIH
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, sales_invoice_doc, msg
                )

                persist_reported()


                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            # else:

            #     error_log()
            if response.status_code not in (200, 202, 409):
                persist_rejection(commit_uuid=False)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA server busy or not responding."
                            " Try after sometime or contact your system administrator. "
                            f"Status code: {response.status_code}<br><br>"
                            f"{render_response(response)}"
                        )
                    )
                )

            if response.status_code in (200, 202):
                msg = (
                    "SUCCESS: <br><br>"
                    if response.status_code == 200
                    else (
                        "REPORTED WITH WARNINGS: <br><br> "
                        "Please copy the below message and send it to your system administrator "
                        "to fix this warnings before next submission <br><br>"
                    )
                )
                msg += (
                    f"Status Code: {response.status_code}<br><br> "
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, sales_invoice_doc, msg
                )

                persist_reported()

                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            else:

                response_step(error_log)


        except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
            frappe.throw(_(f"Error in reporting API-2 xml with sales invoice data : {str(e)}"))

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
        # invoice_doc.db_set(
        #     "custom_zatca_full_response",
        #     f"Error: {str(e)}",
        #     commit=True,
        #     update_modified=True,
        # )
        invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
        invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
        frappe.db.commit()
        frappe.throw(_(f"Error in reporting API-1 sales invoice with xml: {str(e)}"))
''',
'zatca_erpgulf/zatca_erpgulf/pos_submit_with_xml_qr.py': r'''
def reporting_api_machine(
    uuid1, encoded_hash, signed_xmlfile_name, invoice_number, pos_invoice_doc
):
    """Function for reporting api"""
    try:
        # Retrieve the company abbreviation based on the company in the sales invoice
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )
        if not company_abbr:
            frappe.throw(
                _(f"Company with abbreviation {pos_invoice_doc.company} not found.")
            )

        submission = get_submission_context(
            company_abbr, pos_invoice_doc, invoice_number, "invoices/reporting/single",
            expected_doctype="POS Invoice", require_issuing_unit=True,
        )

        payload = {
            "invoiceHash": encoded_hash,
            "uuid": uuid1,
            "invoice": xml_base64_decode(signed_xmlfile_name),
        }
        headers = {
            "accept": CONTENT_TYPE_JSON,
            "accept-language": "en",
            "Clearance-Status": "0",
            "Accept-Version": "V2",
            "Authorization": submission.authorization.header,
            "Content-Type": CONTENT_TYPE_JSON,
            "Cookie": (
                "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119d"
                "cdd3b817f963ec301682dae864351c67ee3a402866"
            ),
        }

        try:
            frappe.publish_realtime(
                "show_gif",
                {"gif_url": "/assets/zatca_erpgulf/js/loading.gif"},
                user=frappe.session.user,
            )
            response = requests.post(
                url=submission.route.url,
                headers=headers,
                json=payload,
                timeout=300,
            )
            # Guard local response steps only; preserve deliberate rejection handling.
            response_step = partial(
                run_received_response_step, validation_error_type=frappe.ValidationError
            )
            render_response = partial(response_step, received_response_text)
            persist_reported = partial(
                response_step, persist_existing_xml_reported, frappe,
                "POS Invoice", invoice_number, response, uuid1,
            )
            persist_rejection = partial(
                response_step, persist_existing_xml_rejection, frappe,
                "POS Invoice", invoice_number, response,
            )
            response_step(frappe.publish_realtime, "hide_gif", user=frappe.session.user)
            if response.status_code in (200, 202, 409):
                if response.status_code == 200:
                        status_label = "Success"
                        title = f"ZATCA Success - {invoice_number}"
                elif response.status_code == 202:
                    status_label = "Warning"
                    title = f"ZATCA Invoice with Warnings - {invoice_number}"
                elif response.status_code == 409:
                    status_label = "Success (Duplicate Invoice)"
                    title = f"ZATCA Duplicate Success - {invoice_number}"

                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )

                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )

            else:

                status_label = f"Failed (HTTP {response.status_code})"
                title = f"ZATCA API Failed - {invoice_number}"
                msg = (
                    f"Status Code: {response.status_code}<br>"
                    f"ZATCA Response: {render_response(response)}"
                )
                response_step(
                    log_zatca_event,
                    invoice_number=invoice_number,
                    response_text=msg,
                    status=status_label,
                    uuid=uuid1,
                    title=title
                )
            if response.status_code in (400, 405, 406):
                persist_rejection(commit_uuid=False)
                frappe.throw(
                    _(
                        (
                            "Error: The request you are sending to ZATCA is in incorrect format. "
                            "Please report to system administrator. "
                            f"Status code: {response.status_code}<br><br> "
                            f"{render_response(response)}"
                        )
                    )
                )

            if response.status_code in (401, 403, 407, 451):
                persist_rejection(commit_uuid=False)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA Authentication failed."
                            "Your access token may be expired or not valid. "
                            "Please contact your system administrator. "
                            f"Status code: {response.status_code}<br><br> "
                            f"{render_response(response)}"
                        )
                    )
                )
            if response.status_code == 409:
                msg = "SUCCESS: <br><br>"
                msg += (
                    f"Status Code: {response.status_code}<br><br> "
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )

                # Update PIH
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, pos_invoice_doc, msg
                )

                persist_reported()


                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            # else:

            #     error_log()
            if response.status_code not in (200, 202, 409):
                persist_rejection(commit_uuid=False)
                frappe.throw(
                    _(
                        (
                            "Error: ZATCA server busy or not responding."
                            " Try after sometime or contact your system administrator. "
                            f"Status code: {response.status_code}<br><br> "
                            f"{render_response(response)}"
                        )
                    )
                )

            if response.status_code in (200, 202):
                msg = (
                    "SUCCESS: <br><br>"
                    if response.status_code == 200
                    else (
                        "REPORTED WITH WARNINGS: <br><br> "
                        "Please copy the below message and send it to your system administrator "
                        "to fix this warnings before next submission <br><br>"
                    )
                )
                msg += (
                    f"Status Code: {response.status_code}<br><br>"
                    f"ZATCA Response: {render_response(response)}<br><br>"
                )

                # company_name = pos_invoice_doc.company
                response_step(
                    record_submission_owner_success,
                    submission, encoded_hash, pos_invoice_doc, msg
                )

                persist_reported()
                response_step(received_response_text_step, success_log, response, uuid1, invoice_number)
            else:
                response_step(error_log)


        except (ValueError, TypeError, KeyError) as e:
            frappe.throw(
                _(("Error in reporting API-2 POS with xml " f"error: {str(e)}"))
            )

    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
        # invoice_doc.db_set(
        #     "custom_zatca_full_response",
        #     f"Error: {str(e)}",
        #     commit=True,
        #     update_modified=True,
        # )
        invoice_doc.custom_zatca_full_response = f"Error: {str(e)}"
        invoice_doc.save(ignore_permissions=True)  # or with permissions if needed
        frappe.db.commit()
        frappe.throw(_(("Error in reporting API-1 with xml pos" f"error: {str(e)}")))
''',
'zatca_erpgulf/zatca_erpgulf/sign_invoice_first.py': r'''
def compliance_api_call(
    uuid1, encoded_hash, signed_xmlfile_name, company_abbr, source_doc
):
    """Submit a compliance sample in the company's configured environment.

    This is not a production clearance/reporting call. Return only confirmed
    validation or previous completion; transport and ambiguous outcomes raise.
    """
    try:

        company_name = frappe.db.get_value("Company", {"abbr": company_abbr}, "name")
        if not company_name:
            frappe.throw(_(f"Company with abbreviation {company_abbr} not found."))

        company_doc = frappe.get_doc("Company", company_name)
        payload = json.dumps(
            {
                "invoiceHash": encoded_hash,
                "uuid": uuid1,
                "invoice": xml_base64_decode(signed_xmlfile_name),
            }
        )

        credentials = get_api_authorization(company_abbr, source_doc, purpose="compliance")
        auth_source = credentials.source_kind
        authorization = credentials.header

        api_url = get_compliance_api_url(company_abbr)

        headers = {
            "accept": "application/json",
            "Accept-Language": "en",
            "Accept-Version": "V2",
            "Authorization": authorization,
            "Content-Type": "application/json",
        }
        response = requests.request(
            "POST",
            url=api_url,
            headers=headers,
            data=payload,
            timeout=300,
        )

        try:
            response_data = response.json()
        except ValueError:
            response_data = response.text

        if is_already_completed_response(response.status_code, response_data):
            response_data["_zatca_compliance_status"] = "ALREADY_COMPLETED"
            return response_data

        if response.status_code not in (200, 202):
            response_body = (response.text or "").strip()
            request_id = response.headers.get("x-request-id") or response.headers.get(
                "X-Request-ID"
            )
            details = response_body or response.reason or "No response body"
            if request_id:
                details += f" (request id: {request_id})"
            if response.status_code == 401:
                details += _(
                    " [environment: {0}; endpoint: {1}; auth source: {2}; CSID length: {3}]"
                ).format(
                    company_doc.get("custom_select") or "Production",
                    api_url,
                    auth_source,
                    len(authorization.removeprefix("Basic ").strip()),
                )
            frappe.throw(
                _(
                    f"Error in compliance [HTTP {response.status_code}]: {details}"
                )
            )

        if isinstance(response_data, dict):
            validation_results = response_data.get("validationResults")
            if (
                isinstance(validation_results, dict)
                and validation_results.get("status") == "ERROR"
            ):
                frappe.throw(json.dumps(response_data, ensure_ascii=False))

        if compliance_result_status(response_data) != "PASS":
            frappe.throw(
                _("ZATCA did not confirm compliance. This check cannot be marked as passed.")
            )

        return response_data
    except requests.exceptions.RequestException:
        # A timeout is an unknown remote outcome, not proof of rejection or
        # success. Never return an error tuple that a caller can treat as PASS.
        frappe.throw(
            _(
                "The ZATCA compliance request could not be completed. "
                "Check the connection and try again; compliance has not been confirmed."
            )
        )

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_(f"ERROR in clearance invoice, ZATCA validation: {str(e)}"))
        return None
''',
}
