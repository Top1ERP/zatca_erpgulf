"""Saved-Company facade for the three existing Compliance workflows.

Development adoption only: delegates existing generators/transport without a
new retry, transaction, credential writer, activation or authority invocation.
"""

import frappe
from frappe import _
from frappe.permissions import has_permission

from zatca_erpgulf.zatca_erpgulf.operation_messages import mute_operation_messages
from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission
from zatca_erpgulf.zatca_erpgulf.saved_form_source import saved_form_name, saved_form_revision
from zatca_erpgulf.zatca_erpgulf.sign_invoice import (
    run_single_compliance_summary, run_all_compliance_summary, run_automatic_zatca_onboarding_checks,
)


DENIED = "You do not have permission to run the saved Company Compliance check."
CHANGED = "Saved Company settings changed. Review the Company before running Compliance again."
MISMATCH = "The sample invoice must belong to the selected Company. No Compliance call was started."
PREPARATION_FAILED = "Company Compliance preparation failed. Review saved Company and sample invoice settings. No Compliance call was started."
UNCONFIRMED = "The Company Compliance outcome could not be confirmed. Review the outcome before another request; no automatic retry was performed."
MODES = ("single", "all", "automatic")


class CompanyComplianceError(ValueError):
    """Only static application-owned messages, never supplied row/error text."""

    def __init__(self, message):
        self.message = message if type(message) is str and message in (DENIED, CHANGED, MISMATCH) else PREPARATION_FAILED
        super().__init__(self.message)


@frappe.whitelist(allow_guest=False)
def run_company_compliance_summary(company_name, expected_modified, mode):
    """Read one saved Company and dispatch one explicitly selected workflow.

    Only Company revision is compared; no source/credential epoch or related
    address revision is locked across generation/HTTP. Legacy direct APIs remain
    compatibility surfaces, not newly permissioned by this facade.
    """
    attempted = False
    denied = False
    try:
        with mute_operation_messages(frappe):
            saved_form_name(company_name)
            if type(expected_modified) is not str or type(mode) is not str or mode not in MODES:
                raise CompanyComplianceError(PREPARATION_FAILED)
            revision = saved_form_revision(expected_modified)
            user = frappe.session.user
            if not user or user == "Guest":
                raise CompanyComplianceError(DENIED)

            def load(doctype, name):
                saved_form_name(name)
                doc = frappe.get_doc(doctype, name)
                if doc.doctype != doctype or doc.name != name:
                    raise CompanyComplianceError(PREPARATION_FAILED)
                if not saved_row_has_permission(has_permission, doctype, "read", doc=doc, user=user):
                    raise CompanyComplianceError(DENIED)
                return doc

            company = load("Company", company_name)
            if saved_form_revision(company.modified) != revision:
                raise CompanyComplianceError(CHANGED)
            saved_form_name(company.abbr)
            if mode != "automatic":
                invoice = load("Sales Invoice", company.custom_sample_invoice_number_to_test)
                if invoice.company != company.name:
                    raise CompanyComplianceError(MISMATCH)
            # Entering a legacy workflow is not proof of HTTP delivery or
            # completion. Keep errors after this boundary conservatively unknown.
            attempted = True
            if mode == "automatic":
                return run_automatic_zatca_onboarding_checks(company.name)
            if mode == "single":
                return run_single_compliance_summary(company.name, invoice.name)
            return run_all_compliance_summary(company.name, invoice.name)
    except CompanyComplianceError as error:
        message = error.message if type(error) is CompanyComplianceError else PREPARATION_FAILED
        denied = message == DENIED
    except Exception:
        message = UNCONFIRMED if attempted else PREPARATION_FAILED
    # Translate only final display. No raw exception/log/result translation,
    # parent-message clearing or implicit private exception chain is added here.
    frappe.throw(_(message), exc=frappe.PermissionError if denied else frappe.ValidationError,
                 title=_("Compliance Check Failed"))
