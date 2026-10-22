"""This module is used to submit the POS invoice to ZATCA using the API through xml and qr."""

import base64
from functools import partial
from frappe import _
import frappe
import requests
from lxml import etree
from zatca_erpgulf.zatca_erpgulf.event_log import log_zatca_event
from zatca_erpgulf.zatca_erpgulf.legacy_xml_persistence import (
    persist_existing_xml_rejection, persist_existing_xml_reported,
)
from zatca_erpgulf.zatca_erpgulf.response_processing import (
    LocalResponseProcessingError, run_received_response_step, received_response_message,
    received_response_text_step,
)
from zatca_erpgulf.zatca_erpgulf.zatca_response import format_zatca_response
from zatca_erpgulf.zatca_erpgulf.submission_context import (
    get_submission_context, record_submission_owner_success,
)
from zatca_erpgulf.zatca_erpgulf.api_settings import get_company_api_route
CONTENT_TYPE_JSON = "application/json"
NOT_SUBMITTED = "Not Submitted"
SALES_INVOICE = "Sales Invoice"


def xml_base64_decode(signed_xmlfile_name):
    """xml base64 decode"""
    try:
        with open(signed_xmlfile_name, "r", encoding="utf-8") as file:
            xml = file.read().lstrip()
            base64_encoded = base64.b64encode(xml.encode("utf-8"))
            base64_decoded = base64_encoded.decode("utf-8")
            return base64_decoded
    except (ValueError, TypeError, KeyError) as e:
        frappe.throw(_(("xml decode base64in simplifed" f"error: {str(e)}")))
        return None


def get_api_url(company_abbr, base_url):
    """Compatibility entry point; all URL decisions use the shared resolver."""
    return get_company_api_route(company_abbr, base_url).url


def success_log(response, uuid1, invoice_number):
    """defining the success log"""
    try:
        current_time = frappe.utils.now()
        frappe.get_doc(
            {
                "doctype": "ZATCA ERPGulf Success Log",
                "title": "ZATCA invoice call done successfully",
                "message": "This message by ZATCA Compliance",
                "uuid": uuid1,
                "invoice_number": invoice_number,
                "time": current_time,
                "zatca_response": response,
            }
        ).insert(ignore_permissions=True)
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.throw(_(("error in success log in simplifed" f"error: {str(e)}")))
        return None


def error_log():
    """defining the error log"""
    try:
        frappe.log_error(
            title="ZATCA invoice call failed in clearance status",
            message=frappe.get_traceback(),
        )
    except (ValueError, TypeError, KeyError, frappe.ValidationError) as e:
        frappe.throw(_(("error in error login simplifed" f"error: {str(e)}")))
        return None


def extract_uuid_and_invoicehash_simplifeid(file_path):
    """
    Extracts the UUID and DigestValue from an XML file.

    Args:
        file_path (str): Path to the XML file.

    Returns:
        dict: A dictionary containing UUID and DigestValue.
    """
    try:
        # Read the file content as bytes
        with open(frappe.local.site + file_path, "rb") as file:
            custom_xml = file.read()

        # Parse the XML string as bytes
        tree = etree.fromstring(custom_xml)

        # Define the namespaces
        namespaces = {
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }

        # Extract the UUID
        uuid = tree.find("cbc:UUID", namespaces).text

        # Extract the DigestValue
        digest_value_element = tree.find(
            ".//ds:Reference[@Id='invoiceSignedData']/ds:DigestValue", namespaces
        )
        digest_value = (
            digest_value_element.text
            if digest_value_element is not None
            else "Not Found"
        )

        return uuid, digest_value

    except Exception as e:
        return {"error": f"Error extracting data in simplifed: {e}"}


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


def get_headers(production_csid):
    """ "get headers"""
    if not production_csid:
        frappe.throw(_("Production CSID is missing in ZATCA XML."))
    return {
        "accept": CONTENT_TYPE_JSON,
        "accept-language": "en",
        "Clearance-Status": "0",
        "Accept-Version": "V2",
        "Authorization": "Basic " + production_csid,
        "Content-Type": CONTENT_TYPE_JSON,
        "Cookie": "TS0106293e=0132a679c0639d13d069bcba831384623a2ca6da47fac8d91bef610c47c7119dcdd3b817f963ec301682dae864351c67ee3a402866",
    }

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
