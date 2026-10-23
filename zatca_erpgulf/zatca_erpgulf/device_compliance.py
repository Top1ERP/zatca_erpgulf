"""Saved-device single Compliance facade; development adoption only.

No client credential fields, Company selector or validation type is accepted.
The delegated legacy generator still owns signing/temporary XML/transport. This
facade adds no live invocation, transaction, retry, key rotation or activation.
"""

import json

import frappe
from frappe import _
from frappe.permissions import has_permission

from zatca_erpgulf.zatca_erpgulf.compliance_messages import collect_compliance_results
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES, resolve_compliance_type
from zatca_erpgulf.zatca_erpgulf.operation_messages import mute_operation_messages
from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission
from zatca_erpgulf.zatca_erpgulf.saved_form_source import saved_form_name, saved_form_revision
from zatca_erpgulf.zatca_erpgulf.sign_invoice import zatca_call_compliance


DENIED = "You do not have permission to run the saved device Compliance check."
CHANGED = "Saved device settings changed. Review the device before running Compliance again."
MISMATCH = "The sample invoice must belong to the device's linked Company. No Compliance call was started."
PREPARATION_FAILED = "Device Compliance preparation failed. Review saved device, Company and sample invoice settings. No Compliance call was started."
UNCONFIRMED = "The device Compliance outcome could not be confirmed. Review the outcome before another request; no automatic retry was performed."


class DeviceComplianceError(ValueError):
    """Only allowlisted app-owned text, never a private ERP exception."""

    def __init__(self, message):
        self.message = message if type(message) is str and message in (DENIED, CHANGED, MISMATCH) else PREPARATION_FAILED
        super().__init__(self.message)


@frappe.whitelist(allow_guest=False)
def run_device_compliance_summary(device_name, expected_modified):
    """Read one saved device/Company/invoice and collect one selected check.

    Only the observed device revision is compared; no row/credential epoch is
    pinned across generation or HTTP. Full invoice mutation isolation, legacy
    diagnostic custody and concurrent source/key rotation remain separate gates.
    """
    attempted = False
    denied = False
    try:
        with mute_operation_messages(frappe):
            saved_form_name(device_name)
            if type(expected_modified) is not str:
                raise DeviceComplianceError(PREPARATION_FAILED)
            revision = saved_form_revision(expected_modified)
            user = frappe.session.user
            if not user or user == "Guest":
                raise DeviceComplianceError(DENIED)

            def load(doctype, name):
                saved_form_name(name)
                doc = frappe.get_doc(doctype, name)
                if doc.doctype != doctype or doc.name != name:
                    raise DeviceComplianceError(PREPARATION_FAILED)
                if not saved_row_has_permission(has_permission, doctype, "read", doc=doc, user=user):
                    raise DeviceComplianceError(DENIED)
                return doc

            device = load("ZATCA Multiple Setting", device_name)
            if saved_form_revision(device.modified) != revision:
                raise DeviceComplianceError(CHANGED)
            company = load("Company", device.custom_linked_doctype)
            invoice = load("Sales Invoice", device.custom_sample_invoice_number_to_test)
            if invoice.company != company.name:
                raise DeviceComplianceError(MISMATCH)
            saved_form_name(company.abbr)
            # Match the existing single-check policy: Company label wins; the
            # historical numeric fallback is Simplified Invoice, not live mode.
            code = resolve_compliance_type(company.custom_validation_type, fallback="1")
            selected = next(label for label, value in COMPLIANCE_TYPES.items() if value == code)
            attempted = True
            results = collect_compliance_results(frappe, (selected,), lambda validation_type: zatca_call_compliance(
                invoice_number=invoice.name, company_name=company.name, company_abbr=company.abbr,
                source_doc=json.dumps({"doctype": device.doctype, "name": device.name}),
                validation_type=validation_type, compliance_type="1"))
            return {"results": results, "single_check": True}
    except DeviceComplianceError as error:
        message = error.message if type(error) is DeviceComplianceError else PREPARATION_FAILED
        denied = message == DENIED
    except Exception:
        message = UNCONFIRMED if attempted else PREPARATION_FAILED
    # No caught raw preparation exception is attached to the public failure.
    # Technical details already collected by the legacy summary retain their
    # established original diagnostic semantics, not a new redaction guarantee.
    frappe.throw(_(message), exc=frappe.PermissionError if denied else frappe.ValidationError,
                 title=_("Compliance Check Failed"))
