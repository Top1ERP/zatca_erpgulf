"""Company-scoped background selection, independent of invoice XML generation.

The callback still uses the existing submission pipeline. Its bypass flag means
the worker may send an eligible invoice, not that Company policy is optional.
No schedule restrictions are added to explicit manual or batch submissions.
"""

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_value
from zatca_erpgulf.zatca_erpgulf.scheduling import (
    PENDING_STATUSES,
    is_pending_invoice,
    is_within_company_windows,
)
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    PHASE_2_VALUE,
    get_b2c_submission_method,
    is_zatca_invoice_enabled,
    resolve_zatca_phase,
)


def is_company_background_eligible(company, current):
    """Only this enabled Phase-2 Company's own Background windows authorize it."""
    return (
        is_zatca_invoice_enabled(company)
        and resolve_zatca_phase(company) == PHASE_2_VALUE
        and get_b2c_submission_method(company) == "Background"
        and is_within_company_windows(company, current)
    )


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
