"""Redirect legacy generator checks to disposable Sales/POS Compliance adapters.

Imports of the dedicated adapters are lazy because live adapters also import
the legacy generator modules. No customer/invoice creation or identity writes
occur here; the dedicated adapter owns its separate sample counter and file.
"""

import json

import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.compliance_result import compliance_result_status
from zatca_erpgulf.zatca_erpgulf.compliance_types import (
    COMPLIANCE_TYPES, normalize_submission_compliance_type,
)


def normalize_generator_compliance_type(value):
    try:
        return normalize_submission_compliance_type(value)
    except ValueError:
        frappe.throw(_("Select a valid ZATCA compliance document type."))


def dispatch_generator_compliance(doctype, invoice_number, compliance_type, company_abbr=None):
    """Honor the explicit sample code and saved invoice's issuer configuration.

    Call before live metadata/file generation and outside legacy catch-and-log
    blocks, so an unconfirmed remote outcome reaches the caller as a failure.
    Caller-provided secret-bearing source objects never choose a different owner.
    """
    code = normalize_generator_compliance_type(compliance_type)
    if doctype not in ("Sales Invoice", "POS Invoice") or code == "0":
        frappe.throw(_("Select a valid ZATCA compliance document type."))
    source = frappe.get_doc(doctype, invoice_number)
    company = frappe.get_doc("Company", source.company)
    if company_abbr is not None and company_abbr != company.abbr:
        frappe.throw(_("The ZATCA credential source does not belong to the selected company."))
    label = next(label for label, value in COMPLIANCE_TYPES.items() if value == code)
    kwargs = dict(invoice_number=invoice_number, company_abbr=company.abbr,
                  compliance_type=code, validation_type=label)
    if doctype == "Sales Invoice":
        from zatca_erpgulf.zatca_erpgulf.sign_invoice import zatca_call_compliance

        # The Sales compatibility API accepts JSON source identity. Its reader
        # reloads the saved document; no credential values are serialized here.
        kwargs["source_doc"] = json.dumps({"doctype": source.doctype, "name": source.name})
        kwargs["company_name"] = company.name
    else:
        from zatca_erpgulf.zatca_erpgulf.pos_sign import zatca_call_compliance

        kwargs["source_doc"] = source
    result = zatca_call_compliance(**kwargs)
    if compliance_result_status(result) != "PASS":
        frappe.throw(_("ZATCA did not confirm compliance. This check cannot be marked as passed."))
    return result
