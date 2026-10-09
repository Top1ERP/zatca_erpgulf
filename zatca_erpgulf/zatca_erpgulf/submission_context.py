"""Shared request selection for live Sales/POS reporting and clearance adapters.

This pins the route, authorization header, and owner identity for one request.
It is not yet a signing/certificate-version snapshot or an ICV allocator.
"""

from dataclasses import dataclass

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.api_routing import ApiRoute
from zatca_erpgulf.zatca_erpgulf.api_settings import get_company_api_route
from zatca_erpgulf.zatca_erpgulf.credential_material import ApiAuthorization
from zatca_erpgulf.zatca_erpgulf.credential_settings import get_api_authorization
from zatca_erpgulf.zatca_erpgulf.pih import update_pih_after_phase2_success


@dataclass(frozen=True)
class SubmissionContext:
    route: ApiRoute
    authorization: ApiAuthorization


def get_submission_context(company_abbr, source_doc, invoice_number, endpoint, *, expected_doctype=None):
    """Validate the target and select Production-purpose auth before sending.

    Production-purpose credentials are also used for simulated reporting and
    clearance; the configured environment is preserved, never forced to Core.
    No credential is loaded for an operation outside these two adapters.
    """
    if endpoint not in ("invoices/reporting/single", "invoices/clearance/single"):
        frappe.throw(_("This submission path supports reporting or clearance only."))
    if (
        source_doc.doctype not in ("Sales Invoice", "POS Invoice")
        or (expected_doctype is not None and source_doc.doctype != expected_doctype)
        or not invoice_number or source_doc.name != invoice_number
    ):
        frappe.throw(_("The ZATCA submission target must match the source invoice."))
    route = get_company_api_route(company_abbr, endpoint)
    authorization = get_api_authorization(
        company_abbr, source_doc, purpose=route.required_credential
    )
    return SubmissionContext(route, authorization)


def record_submission_owner_success(context, encoded_hash, source_doc, message):
    """Use the request's selected owner for existing post-success PIH handling.

    Call only from an adapter's accepted-response branch. This function does not
    classify remote responses or allocate counters. Reload the owner by pinned
    identity instead of reevaluating a potentially changed invoice/device link.
    The existing Phase-2 and unchanged-hash guards remain in the PIH helper.
    """
    auth = context.authorization
    owner = frappe.get_doc(auth.owner_doctype, auth.owner_name)
    notification_field = (
        "custom_send_pos_invoices_to_zatca_on_background"
        if auth.owner_doctype == "ZATCA Multiple Setting"
        else "custom_send_einvoice_background"
    )
    if owner.get(notification_field):
        frappe.msgprint(message)
    return update_pih_after_phase2_success(owner, encoded_hash, source_doc=source_doc)
