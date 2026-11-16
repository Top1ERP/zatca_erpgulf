"""Frozen increment228 existing-XML consumers; offline reference only."""

SOURCES = {
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
        submitted_invoice = read_invoice_payload(
            uuid1, encoded_hash, signed_xmlfile_name, read_xml=xml_base64_decode
        )
        payload = submitted_invoice.as_payload()


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

def submit_sales_invoice_simplifeid(sales_invoice_doc, file_path, invoice_number):
    """submit sales invoice with xml qr"""
    try:
        uuid1, encoded_hash = extract_uuid_and_invoicehash_simplifeid(file_path)

        if "error" in uuid1:
            frappe.throw(uuid1["error"])

        reporting_api_xml_sales_invoice_simplified(
            uuid1,
            encoded_hash,
            frappe.local.site + file_path,
            invoice_number,
            sales_invoice_doc,
        )

    except LocalResponseProcessingError:
        # Keep the original local-review signal; never save a replacement error.
        raise
    except Exception as e:
        try:
            invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
            invoice_doc.custom_zatca_full_response = f"Failed: {str(e)}"
            invoice_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as inner_e:
            frappe.log_error(f"Failed to save ZATCA error response: {str(inner_e)}")

        frappe.throw(_(f"Error in submitting sales in simplifed: {str(e)}"))
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
        submitted_invoice = read_invoice_payload(
            uuid1, encoded_hash, signed_xmlfile_name, read_xml=xml_base64_decode
        )
        payload = submitted_invoice.as_payload()
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

def submit_pos_invoice_simplifeid(pos_invoice_doc, file_path, invoice_number):
    """submit sales invoice with xml qr"""
    try:
        uuid1, encoded_hash = extract_uuid_and_invoicehash_simplifeid(file_path)

        reporting_api_xml_sales_invoice_simplified(
            uuid1,
            encoded_hash,
            frappe.local.site + file_path,
            invoice_number,
            pos_invoice_doc,
        )

    except LocalResponseProcessingError:
        # Preserve local review across this legacy broad exception boundary.
        raise
    except Exception as e:
        frappe.throw(_(f"Error in submitting pos in simplifed: {str(e)}"))
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

        submitted_invoice = read_invoice_payload(
            uuid1, encoded_hash, signed_xmlfile_name, read_xml=xml_base64_decode
        )
        payload = submitted_invoice.as_payload()
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

def submit_sales_invoice_withxmlqr(sales_invoice_doc, file_path, invoice_number):
    """submit sales invoice with xml qr"""
    try:
        uuid1, encoded_hash = extract_uuid_and_invoicehash(file_path)

        if "error" in uuid1:
            frappe.throw(uuid1["error"])

        reporting_api_xml_sales_invoice(
            uuid1,
            encoded_hash,
            frappe.local.site + file_path,
            invoice_number,
            sales_invoice_doc,
        )

    except LocalResponseProcessingError:
        # Do not turn received local review into a generic submission failure.
        raise
    except Exception as e:
        frappe.throw(_(f"Error in submitting sales invoice with XML and  QR: {str(e)}"))
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

        submitted_invoice = read_invoice_payload(
            uuid1, encoded_hash, signed_xmlfile_name, read_xml=xml_base64_decode
        )
        payload = submitted_invoice.as_payload()
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

def submit_pos_withxmlqr(pos_invoice_doc, file_path, invoice_number):
    """Function to submit POS invoice to ZATCA using the API through XML and QR."""
    try:
        # Extract the UUID and DigestValue from the XML file
        uuid1, encoded_hash = extract_invoice_data_from_field(file_path)
        # frappe.throw(f"uuid1: {uuid1} encoded_hash: {encoded_hash}")

        # Call the reporting API
        reporting_api_machine(
            uuid1,
            encoded_hash,
            frappe.local.site + file_path,
            invoice_number,
            pos_invoice_doc,
        )

    except LocalResponseProcessingError:
        # Preserve local review without reclassifying the received response.
        raise
    except Exception as e:
        frappe.throw(_(f"Error in submitting POS invoice with xml and qr: {str(e)}"))
''',
'zatca_erpgulf/zatca_erpgulf/sign_invoice.py': r'''
def zatca_background(invoice_number, source_doc, bypass_background_check=False):
    """defines the zatca bacground"""
    try:
        # frappe.throw("DEBUG: Country found in address: ")
        if source_doc:
            source_doc = frappe.get_doc(json.loads(source_doc))
        sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
        company_name = sales_invoice_doc.company
        settings = frappe.get_doc("Company", company_name)
        company_abbr = settings.abbr
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        # if company_doc.custom_zatca_invoice_enabled != 1 or (
        #     company_doc.custom_zatca_invoice_enabled == 1
        #     and company_doc.custom_phase_1_or_2 == "Phase-1"
        # ):
        #     # frappe.msgprint("Zatca Invoice is not enabled or Phase is not Phase-1. Submitting the document.")
        #     return
        # customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        # if company_doc.tax_id and customer_doc.tax_id:
        #     if company_doc.tax_id.strip() == customer_doc.tax_id.strip():
        #         sales_invoice_doc.custom_zatca_status = "Intra-company transfer"
        #         sales_invoice_doc.custom_zatca_full_response = "Intra-company transfer"
        #         sales_invoice_doc.save(ignore_permissions=True)
        #         frappe.db.commit()
        #         return

        if (
            sales_invoice_doc.taxes
            and sales_invoice_doc.taxes[0].included_in_print_rate == 1
        ):
            if (any(item.item_tax_template for item in sales_invoice_doc.items)
                    and not verified_declared_templates(sales_invoice_doc, runtime=frappe, translate=_, sales=True)):
                frappe.throw(
                    _(
                        "As per ZATCA regulation,Item Tax Template cannot be used when taxes "
                        "are included in the print rate. Please remove Item Tax Templates."
                    )
                )
        any_item_has_tax_template = any(
            item.item_tax_template for item in sales_invoice_doc.items
        )
        if any_item_has_tax_template and not all(
            item.item_tax_template for item in sales_invoice_doc.items
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulation,If any one item has an Item Tax Template,"
                    " all items must have an Item Tax Template."
                )
            )
        tax_categories = set()
        for item in sales_invoice_doc.items:
            if item.item_tax_template:
                item_tax_template = frappe.get_doc(
                    "Item Tax Template", item.item_tax_template
                )
                zatca_tax_category = item_tax_template.custom_zatca_tax_category
                tax_categories.add(zatca_tax_category)
                for tax in item_vat_rows(item_tax_template, runtime=frappe, translate=_):
                    tax_rate = float(tax.tax_rate)

                    if f"{tax_rate:.2f}" not in [
                        "5.00",
                        "15.00",
                    ] and zatca_tax_category not in [
                        "Zero Rated",
                        "Exempted",
                        "Services outside scope of tax / Not subject to VAT",
                    ]:
                        frappe.throw(
                            _(
                                (
                                    "As per ZATCA regulation,ZATCA tax category should be"
                                    " 'Zero Rated','Exempted' or 'Services outside scope of tax / Not subject to VAT' "
                                    "for items with tax rate not equal to 5.00 or 15.00."
                                )
                            )
                        )

                    if (
                        f"{tax_rate:.2f}" == "15.00"
                        and zatca_tax_category != "Standard"
                    ):
                        frappe.throw(
                            _(
                                "Check the ZATCA category code and enable it as standard."
                            )
                        )
        if not company_doc.tax_id:
            frappe.throw(_("As per ZATCA regulations, Company Tax ID is mandatory"))
        if company_doc.tax_id:
            if not (company_doc.tax_id.isdigit() and len(company_doc.tax_id) == 15):
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Company Tax ID must be a 15-digit number"
                    )
                )
            elif not (
                company_doc.tax_id.startswith("3") and company_doc.tax_id.endswith("3")
            ):
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Company Tax ID must start with 3 and end with 3"
                    )
                )
        address = get_address(sales_invoice_doc, company_doc)
        if not address.address_line1:
            frappe.throw(
                _(
                    "As per ZATCA regulations, Address Line 1 is required in the company address."
                )
            )

        if not address.address_line2:
            frappe.throw(
                _(
                    "As per ZATCA regulations, Address Line 2 is required in the company address."
                )
            )

        if (
            not address.custom_building_number
            or not address.custom_building_number.isdigit()
            or len(address.custom_building_number) != 4
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, Building Number must be exactly 4 digitsin company address."
                )
            )

        if (
            not address.pincode
            or not address.pincode.isdigit()
            or len(address.pincode) != 5
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, Pincode must be exactly 5 digits in company address."
                )
            )
        base_discount_amount = sales_invoice_doc.get("base_discount_amount", 0.0)
        if (
            sales_invoice_doc.custom_zatca_nominal_invoice == 1
            and sales_invoice_doc.get("base_discount_amount", 0.0) < 0
        ):
            frappe.throw(
                _(
                    (
                        "As per ZATCA regulations, Only the document level discount is possible for  "
                        "ZATCA nominal invoices.Please ensure the discount is applied correctly."
                    )
                )
            )
        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        if get_alias_value("customer_b2c", customer_doc, 0) == 0:
            if not get_alias_value("customer_buyer_id", customer_doc, ""):
                frappe.throw(
                    "As per ZATCA regulations - For B2B Customers, customer CR number has to be provided"
                )
        if get_alias_value("customer_b2c", customer_doc, 0) != 1:
            address, _source = resolve_customer_address(sales_invoice_doc, customer_doc)
            # frappe.throw(f"DEBUG: Country found in address: '{address.country}'")
            if not address:
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Customer address is mandatory for non-B2C customers."
                    )
                )

            # ZATCA-required field validation
            if not address.address_line1:
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Address Line 1 is required in customer address."
                    )
                )
            if not address.address_line2:
                frappe.throw(
                    _(
                        "As per ZATCA regulations,Address Line 2 is required in customer address."
                    )
                )

            if address and is_saudi_country(address.country):
                if (
                    not address.custom_building_number
                    or not address.custom_building_number.isdigit()
                    or len(address.custom_building_number) != 4
                ):

                    frappe.throw(
                        _(
                            "As per ZATCA regulations,Building Number must be exactly 4 digits in customer address."
                        )
                    )
                if (
                    not address.pincode
                    or not address.pincode.isdigit()
                    or len(address.pincode) != 5
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Pincode must be exactly 5 digits in customer address."
                        )
                    )
            # if get_alias_value("customer_b2c", customer_doc, 0) != 1:
            if address and is_saudi_country(address.country) and not get_alias_value("customer_buyer_id", customer_doc, ""):
            # if address and is_saudi_country(address.country):
                if not customer_doc.tax_id:
                    frappe.throw(
                        _(
                            "As per ZATCA regulations,Tax ID is required for customers in Saudi Arabia."
                        )
                    )
                elif (
                    not customer_doc.tax_id.isdigit() or len(customer_doc.tax_id) != 15
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations,Customer Tax ID must be exactly 15 digits."
                        )
                    )
                elif not (
                    customer_doc.tax_id.startswith("3")
                    and customer_doc.tax_id.endswith("3")
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Customer Tax ID must start with 3 and end with 3."
                        )
                    )
        if not get_alias_value("customer_buyer_id_type", customer_doc, "") and get_alias_value("customer_buyer_id", customer_doc, ""):
            frappe.throw(_("Buyer ID must be blank if Buyer ID Type is not set."))
        if "claudion4saudi" in frappe.get_installed_apps():
            if (
                hasattr(sales_invoice_doc, "custom_advances_copy")
                and sales_invoice_doc.custom_advances_copy
            ):
                if (
                    sales_invoice_doc.custom_advances_copy[0].reference_name
                    and get_alias_value("customer_b2c", customer_doc, 0) == 1
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Advance allocation is supported for "
                            "non B2C customers. Please change the Customer type to B2B."
                        )
                    )
        if (
            sales_invoice_doc.custom_zatca_nominal_invoice == 1
            and sales_invoice_doc.get("additional_discount_percentage", 0.0) != 100
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations,Only a 100% discount is allowed for ZATCA"
                    " nominal invoices.Please ensure the additional discount percentage is set to 100."
                )
            )

        if (
            sales_invoice_doc.custom_zatca_nominal_invoice == 1
            and sales_invoice_doc.get("custom_submit_line_item_discount_to_zatca")
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, For nominal invoices, please disable line item"
                    "discounts by unchecking 'Submit Line Item Discount to ZATCA'."
                )
            )

        if (
            len(tax_categories) > 1
            and base_discount_amount > 0
            and (
                sales_invoice_doc.custom_zatca_nominal_invoice == 1
                or not _has_erp_distributed_discount(sales_invoice_doc)
            )
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, ZATCA does not respond for multiple items with multiple tax categories"
                    " with doc-level discount. Please ensure all items have the same tax category."
                )
            )
        # ERPNext can distribute a Grand Total discount across the item net
        # amounts and the tax after discount.  The XML builder then uses those
        # net line amounts as the source of truth and does not add a second
        # document-level allowance.  Reject only cases where that normalized
        # line-net model is not actually present.
        if (
            base_discount_amount > 0
            and sales_invoice_doc.apply_discount_on != "Net Total"
            and not _use_line_net_amounts_discount_model(sales_invoice_doc)
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations,You cannot put discount on Grand total as the tax is already calculated."
                    " Please make sure your discount is in Net total field."
                )
            )

        if base_discount_amount < 0 and sales_invoice_doc.is_return == 0:
            frappe.throw(
                _(
                    "As per ZATCA regulations,Additional discount cannot be negative. Please enter a positive value."
                )
            )

        if not frappe.db.exists("Sales Invoice", invoice_number):
            frappe.throw(
                _(
                    "Please save and submit the invoice before sending to ZATCA: "
                    + str(invoice_number)
                )
            )

        if sales_invoice_doc.docstatus in [0, 2]:
            frappe.throw(
                _(
                    "Please submit the invoice before sending to ZATCA: "
                    + str(invoice_number)
                )
            )

        if sales_invoice_doc.custom_zatca_status in ["REPORTED", "CLEARED"]:
            frappe.throw(_("Already submitted to Zakat and Tax Authority"))

        if not is_zatca_invoice_enabled(settings):
            frappe.throw(
                _(
                    "ZATCA Invoice is not enabled in Company Settings,"
                    " Please contact your system administrator"
                )
            )
        # if settings.custom_phase_1_or_2 == "Phase-2":
        is_gpos_installed = "gpos" in frappe.get_installed_apps()

        # Check if the field exists
        field_exists = frappe.get_meta("Sales Invoice").has_field("custom_unique_id")
        if is_gpos_installed:
            if sales_invoice_doc.custom_xml and not sales_invoice_doc.custom_qr_code:
                frappe.throw(
                    _(
                        "Please provide the 'qr_code' data when 'xml' is filled for invoice: "
                        + str(invoice_number)
                    )
                )
        if resolve_zatca_phase(settings) == PHASE_2_VALUE:
            if field_exists and sales_invoice_doc.custom_unique_id:

                if is_gpos_installed and sales_invoice_doc.custom_xml:
                    # Set the custom XML field
                    custom_xml_field = sales_invoice_doc.custom_xml
                    submit_sales_invoice_withxmlqr(
                        sales_invoice_doc, custom_xml_field, invoice_number
                    )

                else:
                    zatca_call_withoutxml(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
            else:
                if is_qr_and_xml_attached(sales_invoice_doc):
                    custom_xml_field = frappe.db.get_value(
                        "File",
                        {
                            "attached_to_doctype": sales_invoice_doc.doctype,
                            "attached_to_name": sales_invoice_doc.name,
                            "file_name": ["like", REPORTED_XML],
                        },
                        "file_url",
                    )
                    submit_sales_invoice_simplifeid(
                        sales_invoice_doc, custom_xml_field, invoice_number
                    )
                elif (
                    get_b2c_submission_method(settings) == "Background"
                    and not bypass_background_check and get_alias_value("customer_b2c", customer_doc, 0) == 1
                ):
                    zatca_call_scheduler_background(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
                else:

                    zatca_call(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )

        else:
            create_qr_code(sales_invoice_doc, method=None)
        return "Success"
    except DeclaredVatError:
        raise
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.throw(_("Error in background call : " + str(e)))

def zatca_background_on_submit(doc, _method=None, bypass_background_check=False):
    """referes according to the ZATC based sytem with the submitbutton of the sales invoice"""
    try:
        source_doc = doc
        sales_invoice_doc = doc
        invoice_number = sales_invoice_doc.name
        sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
        company_abbr = frappe.db.get_value(
            "Company", {"name": sales_invoice_doc.company}, "abbr"
        )
        if not company_abbr:
            frappe.throw(
                _(f"Company abbreviation for {sales_invoice_doc.company} not found.")
            )
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        if not is_zatca_invoice_enabled(company_doc):
            # frappe.msgprint("Zatca Invoice is not enabled. Submitting the document.")
            return  # Exit the function without further checks

        # ? Skip ZATCA logic if Company Tax ID = Customer Tax ID
        if company_doc.tax_id and customer_doc.tax_id:
            if company_doc.tax_id.strip() == customer_doc.tax_id.strip():
                sales_invoice_doc.custom_zatca_status = "Intra-company transfer"
                sales_invoice_doc.custom_zatca_full_response = "Intra-company transfer"
                sales_invoice_doc.save(ignore_permissions=True)
                frappe.db.commit()
                return


        is_gpos_installed = "gpos" in frappe.get_installed_apps()
        field_exists = frappe.get_meta("Sales Invoice").has_field("custom_offline_invoice_number")

        # If GPOS is installed and field exists, check its value
        if is_gpos_installed and field_exists:
            offline_invoice_number = sales_invoice_doc.get("custom_offline_invoice_number")

            # If the field has data and Phase-1 is enabled, skip QR creation
            if (
                offline_invoice_number
                and is_zatca_invoice_enabled(company_doc)
                and resolve_zatca_phase(company_doc) == PHASE_1_VALUE
            ):
                return

    # If offline invoice number is blank ? only create QR when Phase-1
            if resolve_zatca_phase(company_doc) == PHASE_1_VALUE:
                create_qr_code(sales_invoice_doc, method=_method)
                return
            if resolve_zatca_phase(company_doc) == PHASE_2_VALUE:

                pass


        # Separate check for ZATCA Phase-1 condition (when GPOS is not applicable)
        if (
            is_zatca_invoice_enabled(company_doc)
            and resolve_zatca_phase(company_doc) == PHASE_1_VALUE
        ):
            create_qr_code(sales_invoice_doc, method=_method)
            return

        # if (
        #     company_doc.custom_zatca_invoice_enabled == 1
        #     and company_doc.custom_phase_1_or_2 == "Phase-1"
        # ):
        #     # frappe.msgprint(
        #     #     "Zatca Invoice is not enabled or Phase is not Phase-1. Submitting the document."
        #     # )
        #     create_qr_code(sales_invoice_doc, method=_method)
        #     return

        if (
            sales_invoice_doc.taxes
            and sales_invoice_doc.taxes[0].included_in_print_rate == 1
        ):
            if (any(item.item_tax_template for item in sales_invoice_doc.items)
                    and not verified_declared_templates(sales_invoice_doc, runtime=frappe, translate=_, sales=True)):
                frappe.throw(
                    "As per ZATCA regulations, Item Tax Template cannot be used when taxes are included"
                    " in the print rate. Please remove Item Tax Templates."
                )
        any_item_has_tax_template = False
        for item in sales_invoice_doc.items:
            if item.item_tax_template:
                any_item_has_tax_template = True
                break
        if any_item_has_tax_template:
            for item in sales_invoice_doc.items:
                if not item.item_tax_template:
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, If any one item has an Item Tax Template,"
                            " all items must have an Item Tax Template."
                        )
                    )
        tax_categories = set()
        for item in sales_invoice_doc.items:
            if item.item_tax_template:
                item_tax_template = frappe.get_doc(
                    "Item Tax Template", item.item_tax_template
                )
                zatca_tax_category = item_tax_template.custom_zatca_tax_category
                tax_categories.add(zatca_tax_category)
                for tax in item_vat_rows(item_tax_template, runtime=frappe, translate=_):
                    tax_rate = float(tax.tax_rate)

                    if f"{tax_rate:.2f}" not in [
                        "5.00",
                        "15.00",
                    ] and zatca_tax_category not in [
                        "Zero Rated",
                        "Exempted",
                        "Services outside scope of tax / Not subject to VAT",
                    ]:
                        frappe.throw(
                            _(
                                "As per ZATCA regulations, ZATCA tax category should be "
                                "'Zero Rated', 'Exempted', or 'Services outside scope of tax / Not subject to VAT' "
                                "for items with tax rate not equal to 5.00 or 15.00."
                            )
                        )

                    if (
                        f"{tax_rate:.2f}" == "15.00"
                        and zatca_tax_category != "Standard"
                    ):
                        frappe.throw(
                            _(
                                "Check the ZATCA category code and enable it as Standard."
                            )
                        )

        base_discount_amount = sales_invoice_doc.get("base_discount_amount", 0.0)
        if (
            sales_invoice_doc.custom_zatca_nominal_invoice == 1
            and sales_invoice_doc.get("base_discount_amount", 0.0) < 0
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulation, only the document level discount is possible for ZATCA nominal invoices."
                    " Please ensure the discount is applied correctly."
                )
            )
        if not company_doc.tax_id:
            frappe.throw(_("As per ZATCA regulations, Company Tax ID is mandatory"))
        if company_doc.tax_id:
            if not (company_doc.tax_id.isdigit() and len(company_doc.tax_id) == 15):
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Company Tax ID must be a 15-digit number"
                    )
                )
            elif not (
                company_doc.tax_id.startswith("3") and company_doc.tax_id.endswith("3")
            ):
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Company Tax ID must start with 3 and end with 3"
                    )
                )
        address = get_address(sales_invoice_doc, company_doc)
        if not address.address_line1:
            frappe.throw(
                _(
                    "As per ZATCA regulations, Address Line 1 is required in the company address."
                )
            )

        if not address.address_line2:
            frappe.throw(
                _(
                    "As per ZATCA regulations, Address Line 2 is required in the company address."
                )
            )

        if (
            not address.custom_building_number
            or not address.custom_building_number.isdigit()
            or len(address.custom_building_number) != 4
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, Building Number must be exactly 4 digitsin company address."
                )
            )

        if (
            not address.pincode
            or not address.pincode.isdigit()
            or len(address.pincode) != 5
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, Pincode must be exactly 5 digits in company address."
                )
            )

        customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
        if get_alias_value("customer_b2c", customer_doc, 0) == 0:
            if not get_alias_value("customer_buyer_id", customer_doc, ""):
                frappe.throw(
                    "As per ZATCA regulations- For B2B Customers, customer CR number has to be provided"
                )
        if get_alias_value("customer_b2c", customer_doc, 0) != 1:
            address, _source = resolve_customer_address(sales_invoice_doc, customer_doc)

            if not address:
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Customer address is mandatory for non-B2C customers."
                    )
                )

            # ZATCA-required field validation
            if not address.address_line1:
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Address Line 1 is required in customer address."
                    )
                )
            if not address.address_line2:
                frappe.throw(
                    _(
                        "As per ZATCA regulations, Address Line 2 is required in customer address."
                    )
                )
            if address and is_saudi_country(address.country):
                if (
                    not address.custom_building_number
                    or not address.custom_building_number.isdigit()
                    or len(address.custom_building_number) != 4
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Building Number must be exactly 4 digits in customer address."
                        )
                    )
                if (
                    not address.pincode
                    or not address.pincode.isdigit()
                    or len(address.pincode) != 5
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Pincode must be exactly 5 digits in customer address."
                        )
                    )
            if address and is_saudi_country(address.country) and not get_alias_value("customer_buyer_id", customer_doc, ""):
            # if address and is_saudi_country(address.country):
                if not customer_doc.tax_id:
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Tax ID is required for customers in Saudi Arabia."
                        )
                    )
                elif (
                    not customer_doc.tax_id.isdigit() or len(customer_doc.tax_id) != 15
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Customer Tax ID must be exactly 15 digits."
                        )
                    )
                elif not (
                    customer_doc.tax_id.startswith("3")
                    and customer_doc.tax_id.endswith("3")
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Customer Tax ID must start with 3 and end with 3."
                        )
                    )
        if not get_alias_value("customer_buyer_id_type", customer_doc, "") and get_alias_value("customer_buyer_id", customer_doc, ""):
            frappe.throw(_("Buyer ID must be blank if Buyer ID Type is not set."))
        if "claudion4saudi" in frappe.get_installed_apps():
            if (
                hasattr(sales_invoice_doc, "custom_advances_copy")
                and sales_invoice_doc.custom_advances_copy
            ):
                if (
                    sales_invoice_doc.custom_advances_copy[0].reference_name
                    and get_alias_value("customer_b2c", customer_doc, 0) == 1
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulations, Advance allocation is supported for non B2C customers. Please change the Customer type to B2B."
                        )
                    )

        if (
            sales_invoice_doc.custom_zatca_nominal_invoice == 1
            and sales_invoice_doc.get("additional_discount_percentage", 0.0) != 100
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations,Only a 100% discount is allowed for ZATCA nominal invoices."
                    " Please ensure the additional discount percentage is set to 100."
                )
            )
        if (
            sales_invoice_doc.custom_zatca_nominal_invoice == 1
            and sales_invoice_doc.get("custom_submit_line_item_discount_to_zatca")
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, For nominal invoices, please disable line item discounts"
                    " by unchecking 'Submit Line Item Discount to ZATCA'."
                )
            )
        if (
            len(tax_categories) > 1
            and base_discount_amount > 0
            and (
                sales_invoice_doc.custom_zatca_nominal_invoice == 1
                or not _has_erp_distributed_discount(sales_invoice_doc)
            )
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations, ZATCA does not respond for multiple items with multiple tax categories "
                    "and a document-level discount. Please ensure all items have the same tax category."
                )
            )
        if (
            base_discount_amount > 0
            and sales_invoice_doc.apply_discount_on != "Net Total"
            and not _use_line_net_amounts_discount_model(sales_invoice_doc)
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulations,You cannot apply a discount on the Grand Total as the tax is already calculated. "
                    "Please apply your discount on the Net Total."
                )
            )
        if not frappe.db.exists("Sales Invoice", invoice_number):
            frappe.throw(
                _(
                    f"Please save and submit the invoice before sending to ZATCA: {invoice_number}"
                )
            )
        if base_discount_amount < 0 and not sales_invoice_doc.is_return:
            frappe.throw(
                _(
                    "Additional discount cannot be negative. Please enter a positive value."
                )
            )
        if sales_invoice_doc.docstatus in [0, 2]:
            frappe.throw(
                _(
                    f"Please submit the invoice before sending to ZATCA: {invoice_number}"
                )
            )
        if sales_invoice_doc.custom_zatca_status in ["REPORTED", "CLEARED"]:
            frappe.throw(
                _("This invoice has already been submitted to Zakat and Tax Authority.")
            )
        company_name = sales_invoice_doc.company
        settings = frappe.get_doc("Company", company_name)
        # if settings.custom_phase_1_or_2 == "Phase-2":
        is_gpos_installed = "gpos" in frappe.get_installed_apps()
        field_exists = frappe.get_meta("Sales Invoice").has_field("custom_unique_id")
        if is_gpos_installed:
            if sales_invoice_doc.custom_xml and not sales_invoice_doc.custom_qr_code:
                frappe.throw(
                    _(
                        "Please provide the 'qr_code' field data when have'xml' for invoice: "
                        + str(invoice_number)
                    )
                )
        if resolve_zatca_phase(settings) == PHASE_2_VALUE:

            if field_exists and sales_invoice_doc.custom_unique_id:
                if (
                    get_b2c_submission_method(settings) == "Background"
                    and get_alias_value("customer_b2c", customer_doc, 0) == 1
                    and not bypass_background_check
                ):
                    return
                if is_gpos_installed and sales_invoice_doc.custom_xml:
                    # Set the custom XML field
                    custom_xml_field = sales_invoice_doc.custom_xml
                    submit_sales_invoice_withxmlqr(
                        sales_invoice_doc, custom_xml_field, invoice_number
                    )
                else:
                    zatca_call_withoutxml(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
            else:
                if is_qr_and_xml_attached(sales_invoice_doc):
                    custom_xml_field = frappe.db.get_value(
                        "File",
                        {
                            "attached_to_doctype": sales_invoice_doc.doctype,
                            "attached_to_name": sales_invoice_doc.name,
                            "file_name": ["like", REPORTED_XML],
                        },
                        "file_url",
                    )
                    submit_sales_invoice_simplifeid(
                        sales_invoice_doc, custom_xml_field, invoice_number
                    )
                elif (
                    get_b2c_submission_method(settings) == "Background"
                    and not bypass_background_check and get_alias_value("customer_b2c", customer_doc, 0) == 1
                ):
                    zatca_call_scheduler_background(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
                else:

                    zatca_call(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )

        else:
            create_qr_code(sales_invoice_doc, method=None)
        doc.reload()
    except DeclaredVatError:
        raise
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.throw(_(f"Error in background call on submit: {str(e)}"))

def resubmit_invoices(invoice_numbers, bypass_background_check=False):
    """
    Resubmit invoices where custom_zatca_full_response contains 'RemoteDisconnected'.
    If the invoice is already submitted, call `zatca_background_on_submit`.
    Otherwise, submit the invoice.
    """
    if isinstance(invoice_numbers, str):
        invoice_numbers = frappe.parse_json(invoice_numbers)

    results = {}
    for invoice_number in invoice_numbers:
        try:
            # Fetch the Sales Invoice document
            sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
            company_doc = frappe.get_doc("Company", sales_invoice_doc.company)
            customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
            if (
                sales_invoice_doc.docstatus == 1
            ):  # Check if the invoice is already submitted
                # Call the zatca_background_on_submit function
                zatca_background_on_submit(
                    sales_invoice_doc, bypass_background_check=True
                )

            # elif company_doc.custom_submit_or_not == 1:
            elif (
                sales_invoice_doc.docstatus == 0
                and company_doc.custom_submit_or_not == 1
                and get_alias_value("customer_b2c", customer_doc, 0) == 1
            ):
                # Submit the invoice
                sales_invoice_doc.submit()
                # zatca_background_on_submit(
                #     sales_invoice_doc, bypass_background_check=True
                # )

        except DeclaredVatError:
            raise
        except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
            frappe.throw(_(f"Error in background call: {str(e)}"))
            # Log errors and add to the results

    return results
''',
'zatca_erpgulf/zatca_erpgulf/pos_sign.py': r'''
def zatca_background_(invoice_number, source_doc, bypass_background_check=False):
    """Function for zatca background"""
    try:
        if source_doc:
            source_doc = frappe.get_doc(
                json.loads(source_doc)
            )  # Deserialize if sent as JSON

        pos_invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
        company_name = pos_invoice_doc.company

        settings = frappe.get_doc("Company", company_name)
        company_abbr = settings.abbr

        any_item_has_tax_template = any(
            item.item_tax_template for item in pos_invoice_doc.items
        )
        if any_item_has_tax_template and not all(
            item.item_tax_template for item in pos_invoice_doc.items
        ):
            frappe.throw(_(ITEM_TAX_TEMPLATE_WARNING))

        pos_profile = pos_invoice_doc.pos_profile
        if not pos_profile:
            frappe.throw(_("POS Profile is not set in the POS Invoice."))
        pos_profile_doc = frappe.get_doc("POS Profile", pos_profile)
        taxes_and_charges = pos_profile_doc.taxes_and_charges
        taxes_template_doc = frappe.get_doc(
            "Sales Taxes and Charges Template", taxes_and_charges
        )

        tax_rate = taxes_template_doc.taxes[0]
        if tax_rate and tax_rate.included_in_print_rate == 1:
            if (any(item.item_tax_template for item in pos_invoice_doc.items)
                    and not verified_declared_templates(pos_invoice_doc, runtime=frappe, translate=_, sales=False)):
                frappe.throw(
                    _(
                        "As per ZATCA regulation,Item Tax Template cannot be used when taxes are included in "
                        "the print rate. Please remove Item Tax Templates."
                    )
                )
        tax_categories = set()
        for item in pos_invoice_doc.items:
            if item.item_tax_template:
                item_tax_template = frappe.get_doc(
                    "Item Tax Template", item.item_tax_template
                )
                zatca_tax_category = item_tax_template.custom_zatca_tax_category
                tax_categories.add(zatca_tax_category)
                for tax in item_vat_rows(item_tax_template, runtime=frappe, translate=_):
                    tax_rate = float(tax.tax_rate)

                    if f"{tax_rate:.2f}" not in [
                        "5.00",
                        "15.00",
                    ] and zatca_tax_category not in [
                        "Zero Rated",
                        "Exempted",
                        "Services outside scope of tax / Not subject to VAT",
                    ]:
                        frappe.throw(
                            _(
                                "As per ZATCA regulation, ZATCA tax category should be 'Zero Rated', 'Exempted' or "
                                "'Services outside scope of tax / Not subject to VAT' for items with "
                                "tax rate not equal to 5.00 or 15.00."
                            )
                        )

                    if (
                        f"{tax_rate:.2f}" == "15.00"
                        and zatca_tax_category != "Standard"
                    ):
                        frappe.throw(
                            _(
                                "As per ZATCA regulation, Check the ZATCA category code and enable it as standard."
                            )
                        )
        customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)
        if get_alias_value("customer_b2c", customer_doc, 0) == 0:
            if not get_alias_value("customer_buyer_id", customer_doc, ""):
                frappe.throw(
                    "As per ZATCA regulation- For B2B Customers, customer CR number has to be provided"
                )
        if get_alias_value("customer_b2c", customer_doc, 0) != 1:
            address, _source = resolve_customer_address(pos_invoice_doc, customer_doc)

            if not address:
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Customer address is mandatory for non-B2C customers."
                    )
                )

            # ZATCA-required field validation
            if not address.address_line1:
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Address Line 1 is required in customer address."
                    )
                )
            if not address.address_line2:
                frappe.throw(
                    _(
                        "As per ZATCA regulation,Address Line 2 is required in customer address."
                    )
                )
            if (
                not address.custom_building_number
                or not address.custom_building_number.isdigit()
                or len(address.custom_building_number) != 4
            ):
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Building Number must be exactly 4 digits in customer address."
                    )
                )
            if (
                not address.pincode
                or not address.pincode.isdigit()
                or len(address.pincode) != 5
            ):
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Pincode must be exactly 5 digits in customer address."
                    )
                )
            if address and is_saudi_country(address.country):
                if not customer_doc.tax_id:
                    frappe.throw(
                        _(
                            "As per ZATCA regulation, Tax ID is required for customers in Saudi Arabia."
                        )
                    )
                elif (
                    not customer_doc.tax_id.isdigit() or len(customer_doc.tax_id) != 15
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulation, Customer Tax ID must be exactly 15 digits."
                        )
                    )

        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        if not company_doc.tax_id:
            frappe.throw(_("As per ZATCA regulation, Company Tax ID is mandatory"))
        if company_doc.tax_id and not (
            company_doc.tax_id.isdigit() and len(company_doc.tax_id) == 15
        ):
            frappe.throw(
                _("As per ZATCA regulation, Company Tax ID must be a 15-digit number")
            )
        address = get_address(pos_invoice_doc, company_doc)
        if not address.address_line1:
            frappe.throw(
                _(
                    "As per ZATCA regulation, Address Line 1 is required in the company address."
                )
            )

        if not address.address_line2:
            frappe.throw(
                _(
                    "As per ZATCA regulation, Address Line 2 is required in the company address."
                )
            )

        if (
            not address.custom_building_number
            or not address.custom_building_number.isdigit()
            or len(address.custom_building_number) != 4
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulation, Building Number must be exactly 4 digitsin company address."
                )
            )

        if (
            not address.pincode
            or not address.pincode.isdigit()
            or len(address.pincode) != 5
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulation,Pincode must be exactly 5 digits in company address."
                )
            )
        base_discount_amount = pos_invoice_doc.get("base_discount_amount", 0.0)
        if (len(tax_categories) > 1 and base_discount_amount > 0
                and (pos_invoice_doc.get("custom_zatca_nominal_invoice") == 1
                     or not _has_erp_distributed_discount(pos_invoice_doc))):
            frappe.throw(
                _(
                    "As per ZATCA regulation, ZATCA does not respond for multiple items with multiple tax categories"
                    " with doc-level discount. Please ensure all items have the same tax category."
                )
            )
        if not frappe.db.exists("POS Invoice", invoice_number):
            frappe.throw(
                _(
                    "Please save and submit the invoice before sending to ZATCA: "
                    + str(invoice_number)
                )
            )
        if base_discount_amount < 0:
            frappe.throw(
                _(
                    "Additional discount cannot be negative. Please enter a positive value."
                )
            )

        if pos_invoice_doc.docstatus in [0, 2]:
            frappe.throw(
                _(
                    "Please submit the invoice before sending to ZATCA: "
                    + str(invoice_number)
                )
            )

        if pos_invoice_doc.custom_zatca_status in ["REPORTED", "CLEARED"]:
            frappe.throw(_("Already submitted to Zakat and Tax Authority"))

        if not is_zatca_invoice_enabled(settings):
            frappe.throw(
                _(
                    "ZATCA Invoice is not enabled in Company Settings, "
                    "Please contact your system administrator"
                )
            )

        # if resolve_zatca_phase(settings) == PHASE_2_VALUE:
        is_gpos_installed = "gpos" in frappe.get_installed_apps()
        field_exists = frappe.get_meta("POS Invoice").has_field("custom_unique_id")
        if is_gpos_installed:
            if pos_invoice_doc.custom_xml and not pos_invoice_doc.custom_qr_code:
                frappe.throw(
                    _(
                        "Please provide the 'qr_code' field data when 'custom_xml' is filled for invoice: "
                        + str(invoice_number)
                    )
                )
        if resolve_zatca_phase(settings) == PHASE_2_VALUE:
            if field_exists and pos_invoice_doc.custom_unique_id:
                if not pos_invoice_doc.custom_zatca_pos_name:
                    frappe.throw(_("pos name required"))
                if is_gpos_installed and pos_invoice_doc.custom_xml:
                    # Set the custom XML field
                    custom_xml_field = pos_invoice_doc.custom_xml
                    submit_pos_withxmlqr(
                        pos_invoice_doc, custom_xml_field, invoice_number
                    )
                else:
                    zatca_call_pos_without_xml(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
            else:
                if is_qr_and_xml_attached(pos_invoice_doc):
                    custom_xml_field = frappe.db.get_value(
                        "File",
                        {
                            "attached_to_doctype": pos_invoice_doc.doctype,
                            "attached_to_name": pos_invoice_doc.name,
                            "file_name": ["like", "%Reported xml file%"],
                        },
                        "file_url",
                    )
                    submit_pos_invoice_simplifeid(
                        pos_invoice_doc, custom_xml_field, invoice_number
                    )
                elif (
                    settings.custom_send_invoice_to_zatca == "Background"
                    and not bypass_background_check and get_alias_value("customer_b2c", customer_doc, 0) == 1
                ):
                    zatca_call_pos_without_xml_background(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
                else:
                    zatca_call(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
        else:
            create_qr_code(pos_invoice_doc, method=None)

    except PosFinancialError:
        raise
    except DeclaredVatError:
        raise
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in background call: " + str(e)))

def zatca_background_on_submit(doc, _method=None, bypass_background_check=False):
    """Function for zatca background on submit"""

    try:
        source_doc = doc
        pos_invoice_doc = doc
        invoice_number = pos_invoice_doc.name
        pos_invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
        company_abbr = frappe.db.get_value(
            "Company", {"name": pos_invoice_doc.company}, "abbr"
        )

        customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)
        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        if not company_abbr:
            frappe.throw(
                _(f"Company abbreviation for {pos_invoice_doc.company} not found.")
            )
        if not is_zatca_invoice_enabled(company_doc):
            # frappe.msgprint("Zatca Invoice is not enabled. Submitting the document.")
            return

        if company_doc.tax_id and customer_doc.tax_id:
            if company_doc.tax_id.strip() == customer_doc.tax_id.strip():
                pos_invoice_doc.custom_zatca_status = "Intra-company transfer"
                pos_invoice_doc.custom_zatca_full_response = "Intra-company transfer"
                pos_invoice_doc.save(ignore_permissions=True)
                frappe.db.commit()
                return

        if not get_alias_value("customer_buyer_id_type", customer_doc, "") and get_alias_value("customer_buyer_id", customer_doc, ""):
            frappe.throw(_("Buyer ID must be blank if Buyer ID Type is not set."))
        any_item_has_tax_template = False

        for item in pos_invoice_doc.items:
            if item.item_tax_template:
                any_item_has_tax_template = True
                break

        if any_item_has_tax_template:
            for item in pos_invoice_doc.items:
                if not item.item_tax_template:
                    frappe.throw(_(ITEM_TAX_TEMPLATE_WARNING))

        pos_profile = pos_invoice_doc.pos_profile
        if not pos_profile:
            frappe.throw(_("POS Profile is not set in the POS Invoice."))
        pos_profile_doc = frappe.get_doc("POS Profile", pos_profile)
        taxes_and_charges = pos_profile_doc.taxes_and_charges
        taxes_template_doc = frappe.get_doc(
            "Sales Taxes and Charges Template", taxes_and_charges
        )

        tax_rate = taxes_template_doc.taxes[0]
        if tax_rate and tax_rate.included_in_print_rate == 1:
            if (any(item.item_tax_template for item in pos_invoice_doc.items)
                    and not verified_declared_templates(pos_invoice_doc, runtime=frappe, translate=_, sales=False)):
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Item Tax Template cannot be used when taxes are included in "
                        "the print rate. Please remove Item Tax Templates."
                    )
                )
        tax_categories = set()
        for item in pos_invoice_doc.items:
            if item.item_tax_template:
                item_tax_template = frappe.get_doc(
                    "Item Tax Template", item.item_tax_template
                )
                zatca_tax_category = item_tax_template.custom_zatca_tax_category
                tax_categories.add(zatca_tax_category)
                for tax in item_vat_rows(item_tax_template, runtime=frappe, translate=_):
                    tax_rate = float(tax.tax_rate)

                    if f"{tax_rate:.2f}" not in [
                        "5.00",
                        "15.00",
                    ] and zatca_tax_category not in [
                        "Zero Rated",
                        "Exempted",
                        "Services outside scope of tax / Not subject to VAT",
                    ]:
                        frappe.throw(
                            _(
                                "As per ZATCA regulation, ZATCA tax category should be 'Zero Rated', 'Exempted' or "
                                "'Services outside scope of tax / Not subject to VAT' for items with "
                                "tax rate not equal to 5.00 or 15.00."
                            )
                        )

                    if (
                        f"{tax_rate:.2f}" == "15.00"
                        and zatca_tax_category != "Standard"
                    ):
                        frappe.throw(
                            _(
                                "As per ZATCA regulation,Check the ZATCA category code and enable it as standard."
                            )
                        )

        customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)
        if get_alias_value("customer_b2c", customer_doc, 0) == 0:
            if not get_alias_value("customer_buyer_id", customer_doc, ""):
                frappe.throw(
                    "As per ZATCA regulation- For B2B Customers, customer CR number has to be provided"
                )
        if get_alias_value("customer_b2c", customer_doc, 0) != 1:
            address, _source = resolve_customer_address(pos_invoice_doc, customer_doc)

            if not address:
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Customer address is mandatory for non-B2C customers."
                    )
                )

            # ZATCA-required field validation
            if not address.address_line1:
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Address Line 1 is required in customer address."
                    )
                )
            if not address.address_line2:
                frappe.throw(
                    _(
                        "As per ZATCA regulation,Address Line 2 is required in customer address."
                    )
                )
            if (
                not address.custom_building_number
                or not address.custom_building_number.isdigit()
                or len(address.custom_building_number) != 4
            ):
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Building Number must be exactly 4 digits in customer address."
                    )
                )
            if (
                not address.pincode
                or not address.pincode.isdigit()
                or len(address.pincode) != 5
            ):
                frappe.throw(
                    _(
                        "As per ZATCA regulation, Pincode must be exactly 5 digits in customer address."
                    )
                )
            if address and is_saudi_country(address.country):
                if not customer_doc.tax_id:
                    frappe.throw(
                        _(
                            "As per ZATCA regulation, Tax ID is required for customers in Saudi Arabia."
                        )
                    )
                elif (
                    not customer_doc.tax_id.isdigit() or len(customer_doc.tax_id) != 15
                ):
                    frappe.throw(
                        _(
                            "As per ZATCA regulation, Customer Tax ID must be exactly 15 digits."
                        )
                    )

        company_doc = frappe.get_doc("Company", {"abbr": company_abbr})
        if not company_doc.tax_id:
            frappe.throw(_("As per ZATCA regulation, Company Tax ID is mandatory"))
        if company_doc.tax_id and not (
            company_doc.tax_id.isdigit() and len(company_doc.tax_id) == 15
        ):
            frappe.throw(
                _("As per ZATCA regulation, Company Tax ID must be a 15-digit number")
            )
        address = get_address(pos_invoice_doc, company_doc)
        if not address.address_line1:
            frappe.throw(
                _(
                    "As per ZATCA regulation, Address Line 1 is required in the company address."
                )
            )

        if not address.address_line2:
            frappe.throw(
                _(
                    "As per ZATCA regulation, Address Line 2 is required in the company address."
                )
            )

        if (
            not address.custom_building_number
            or not address.custom_building_number.isdigit()
            or len(address.custom_building_number) != 4
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulation, Building Number must be exactly 4 digitsin company address."
                )
            )

        if (
            not address.pincode
            or not address.pincode.isdigit()
            or len(address.pincode) != 5
        ):
            frappe.throw(
                _(
                    "As per ZATCA regulation,Pincode must be exactly 5 digits in company address."
                )
            )
        base_discount_amount = pos_invoice_doc.get("base_discount_amount", 0.0)
        if (len(tax_categories) > 1 and base_discount_amount > 0
                and (pos_invoice_doc.get("custom_zatca_nominal_invoice") == 1
                     or not _has_erp_distributed_discount(pos_invoice_doc))):
            frappe.throw(
                _(
                    "As per ZATCA regulation, ZATCA does not respond for multiple items with multiple tax categories "
                    "with doc-level discount. Please ensure all items have the same tax category."
                )
            )
        # Check if Zatca Invoice is enabled in the Company document

        if not is_zatca_invoice_enabled(company_doc):
            frappe.throw(
                _(
                    "ZATCA Invoice is not enabled in the Company settings,"
                    " Please contact your system administrator"
                )
            )

        if not frappe.db.exists("POS Invoice", invoice_number):
            frappe.throw(
                _(
                    "Please save and submit the invoice before sending to ZATCA:  "
                    + str(invoice_number)
                )
            )
        if base_discount_amount < 0:
            frappe.throw(
                _(
                    "Additional discount cannot be negative. Please enter a positive value."
                )
            )

        if pos_invoice_doc.docstatus in [0, 2]:
            frappe.throw(
                _(
                    "Please submit the invoice before sending to ZATCA:  "
                    + str(invoice_number)
                )
            )

        if pos_invoice_doc.custom_zatca_status in ["REPORTED", "CLEARED"]:
            frappe.throw(_("Already submitted to Zakat and Tax Authority"))
        company_name = pos_invoice_doc.company

        # Retrieve the company document to access settings
        settings = frappe.get_doc("Company", company_name)
        # if resolve_zatca_phase(settings) == PHASE_2_VALUE:
        #     zatca_call(
        #         invoice_number, "0", any_item_has_tax_template, company_abbr, source_doc
        #     )
        # else:
        #     create_qr_code(pos_invoice_doc, method=None)
        settings = frappe.get_doc("Company", company_name)

        is_gpos_installed = "gpos" in frappe.get_installed_apps()
        field_exists = frappe.get_meta("POS Invoice").has_field("custom_unique_id")
        if is_gpos_installed:
            if pos_invoice_doc.custom_xml and not pos_invoice_doc.custom_qr_code:
                frappe.throw(
                    _(
                        "Please provide the 'qr_code' field data when 'custom_xml' is filled for invoice: "
                        + str(invoice_number)
                    )
                )
        if resolve_zatca_phase(settings) == PHASE_2_VALUE:
            if field_exists and pos_invoice_doc.custom_unique_id:
                if not pos_invoice_doc.custom_zatca_pos_name:
                    frappe.throw(_("pos name required"))
                if is_gpos_installed and pos_invoice_doc.custom_xml:
                    # Set the custom XML field
                    custom_xml_field = pos_invoice_doc.custom_xml
                    submit_pos_withxmlqr(
                        pos_invoice_doc, custom_xml_field, invoice_number
                    )
                else:
                    zatca_call_pos_without_xml(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
            else:
                if is_qr_and_xml_attached(pos_invoice_doc):
                    custom_xml_field = frappe.db.get_value(
                        "File",
                        {
                            "attached_to_doctype": pos_invoice_doc.doctype,
                            "attached_to_name": pos_invoice_doc.name,
                            "file_name": ["like", "%Reported xml file%"],
                        },
                        "file_url",
                    )
                    # frappe.throw("custom_xml_field: " + str(custom_xml_field))
                    submit_pos_invoice_simplifeid(
                        pos_invoice_doc, custom_xml_field, invoice_number
                    )
                elif (
                    settings.custom_send_invoice_to_zatca == "Background"
                    and not bypass_background_check and get_alias_value("customer_b2c", customer_doc, 0) == 1
                ):
                    zatca_call_pos_without_xml_background(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
                else:
                    # Handle the case where custom_unique_id is missing
                    zatca_call(
                        invoice_number,
                        "0",
                        any_item_has_tax_template,
                        company_abbr,
                        source_doc,
                    )
        else:
            # If not Phase-2, create a QR code
            create_qr_code(pos_invoice_doc, method=None)

    except PosFinancialError:
        raise
    except DeclaredVatError:
        raise
    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error in background call submit: " + str(e)))

def resubmit_invoices_pos(invoice_numbers, bypass_background_check=False):
    """
    Resubmit invoices where custom_zatca_full_response contains 'RemoteDisconnected'.
    If the invoice is already submitted, call `zatca_background_on_submit`.
    Otherwise, submit the invoice.
    """
    if isinstance(invoice_numbers, str):
        invoice_numbers = frappe.parse_json(invoice_numbers)

    results = {}
    for invoice_number in invoice_numbers:
        try:
            # Fetch the Sales Invoice document
            pos_invoice_doc = frappe.get_doc("POS Invoice", invoice_number)
            company_doc = frappe.get_doc("Company", pos_invoice_doc.company)
            customer_doc = frappe.get_doc("Customer", pos_invoice_doc.customer)


            if (
                pos_invoice_doc.docstatus == 1
            ):  # Check if the invoice is already submitted
                # Call the zatca_background_on_submit function
                zatca_background_on_submit(
                    pos_invoice_doc, bypass_background_check=True
                )

            # elif company_doc.custom_submit_or_not == 1:
            elif (
                sales_invoice_doc.docstatus == 0
                and company_doc.custom_submit_or_not == 1
                and get_alias_value("customer_b2c", customer_doc, 0) == 1
            ):
                pos_invoice_doc.submit()
                # zatca_background_on_submit(
                #     pos_invoice_doc, bypass_background_check=True
                # )

        except DeclaredVatError:
            raise
        except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
            frappe.throw(_(f"Error in background call: {str(e)}"))
            # Log errors and add to the results

    return results
''',
'zatca_erpgulf/zatca_erpgulf/background_worker.py': r'''
def run_pending_background_invoices(doctype, submit_callback, *, commit_per_invoice=False):
    """Process pending invoices with one Company policy snapshot per worker run.

Retain the existing 24-hour discovery horizon and Sales/POS commit distinction.
An invalid Company configuration or one invoice failure cannot stop the other
Companies in this run. Status rechecks reduce stale-query duplicates; they do
not provide a cross-worker lock or make remote submissions transactional.
"""
    if doctype not in ("Sales Invoice", "POS Invoice"):
        raise ValueError("Unsupported background invoice DocType.")
    try:
        clock = now_datetime()
        pending = frappe.get_all(
            doctype,
            filters=[
                ["creation", ">=", add_to_date(clock, hours=-24)],
                ["docstatus", "in", [0, 1]],
                ["custom_zatca_status", "in", list(PENDING_STATUSES)],
            ],
            fields=["name"],
        )
        policies = {}
        for row in pending:
            try:
                invoice = frappe.get_doc(doctype, row["name"])
                if not is_pending_invoice(invoice):
                    continue
                company_name = invoice.company
                if company_name not in policies:
                    # Fail closed for this Company, even if loading/parsing fails.
                    policies[company_name] = (None, False)
                    company = frappe.get_doc("Company", company_name)
                    eligible = is_company_background_eligible(company, clock.time())
                    policies[company_name] = (company, eligible)
                company, eligible = policies[company_name]
                if not eligible:
                    continue
                if invoice.docstatus == 0:
                    if not cint(company.get("custom_submit_or_not", 0)):
                        continue
                    customer = frappe.get_doc("Customer", invoice.customer)
                    if not cint(get_alias_value("customer_b2c", customer, 0)):
                        continue
                    invoice.submit()
                    invoice.reload()
                    # on_submit may have accepted it already; do not send twice.
                    if not is_pending_invoice(invoice):
                        if commit_per_invoice:
                            frappe.db.commit()
                        continue
                submit_callback(invoice, bypass_background_check=True)
                if commit_per_invoice:
                    frappe.db.commit()
            except Exception:
                frappe.log_error(
                    title=f"ZATCA background: {doctype} {row['name']}",
                    message=frappe.get_traceback(),
                )
    except Exception:
        frappe.log_error(
            title="ZATCA Background Job Error", message=frappe.get_traceback()
        )
''',
}
