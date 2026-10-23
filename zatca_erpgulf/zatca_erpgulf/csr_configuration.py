"""Build CSR configuration drafts without saving settings or generating keys."""

import random
from html import escape
import frappe
from frappe import _
from frappe.permissions import has_permission

from zatca_erpgulf.zatca_erpgulf.operation_messages import mute_operation_messages
from zatca_erpgulf.zatca_erpgulf.permission_compat import saved_row_has_permission
from zatca_erpgulf.zatca_erpgulf.saved_form_source import saved_form_revision, SavedFormSourceError


DRAFT_FAILED = "CSR configuration preparation failed. No configuration was saved or key generated."
DRAFT_DENIED = "You do not have permission to prepare CSR configuration for this Company."
DRAFT_CHANGED = "Saved Company settings changed. Review the Company before preparing CSR configuration again."
DRAFT_INVALID = "CSR configuration requires saved Company identity and revision."
DRAFT_VALUES = "CSR configuration values must be bounded single-line text. Review Company name, Tax ID, location and category."
CONFIG_FIELDS = ("tax_id", "custom_zatca__location_for_csr_configuratoin",
                 "custom_zatca__company_category_for_csr_configuration", "company_name")
REQUIRED_MESSAGES = ("Tax ID (VAT number) is required.", "Location for CSR configuration is required.",
                     "Company category for CSR configuration is required.", "Company name is required.")
ERROR_MESSAGES = frozenset((DRAFT_FAILED, DRAFT_DENIED, DRAFT_CHANGED, DRAFT_INVALID, DRAFT_VALUES,
                            *REQUIRED_MESSAGES))


class CSRConfigurationError(ValueError):
    """Static English message only, never a row value or exception detail."""

    def __init__(self, message):
        self.message = message if type(message) is str and message in ERROR_MESSAGES else DRAFT_FAILED
        super().__init__(self.message)


def _revision(value):
    """Normalize naive saved DATETIME markers, not issuance times or epochs."""
    try:
        return saved_form_revision(value)
    except SavedFormSourceError:
        raise CSRConfigurationError(DRAFT_INVALID) from None


def _build_csr_config(company_doc):
    """Shared legacy text format; no database, popup, key or network operations."""
    tax_id = company_doc.tax_id
    location = company_doc.custom_zatca__location_for_csr_configuratoin
    business_category = company_doc.custom_zatca__company_category_for_csr_configuration
    company_name = company_doc.company_name
    for value, message in zip((tax_id, location, business_category, company_name), REQUIRED_MESSAGES):
        if not value:
            raise CSRConfigurationError(message)

    def hex_segment():
        return f"{random.getrandbits(32):08x}"

    serial_number = (f"1-TST|2-TST|3-{hex_segment()}-{hex_segment()[:4]}-"
                     f"{hex_segment()[:4]}-{hex_segment()[:4]}-{hex_segment()[:12]}")
    return (
        f"csr.common.name=TST-886431145-{tax_id}\n"
        f"csr.serial.number={serial_number}\n"
        f"csr.organization.identifier={tax_id}\n"
        f"csr.organization.unit.name={tax_id}\n"
        f"csr.organization.name={company_name}\n"
        f"csr.country.name=SA\n"
        f"csr.invoice.type=1100\n"
        f"csr.location.address={location.upper()}\n"
        f"csr.industry.business.category={business_category}"
    )


@frappe.whitelist(allow_guest=False)
def prepare_csr_config(company_name, expected_modified):
    """Return an exact saved-Company draft for explicit user review/save.

    ACL/revision checks are observations, not a cross-request source lock. No
    invoice, credential, authority call, save, commit or configuration activation.
    The legacy abbreviation endpoint remains a separate compatibility surface.
    """
    denied = False
    try:
        with mute_operation_messages(frappe):
            if (type(company_name) is not str or not 0 < len(company_name) <= 140
                    or company_name != company_name.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in company_name)):
                raise CSRConfigurationError(DRAFT_INVALID)
            if type(expected_modified) is not str:
                raise CSRConfigurationError(DRAFT_INVALID)
            expected = _revision(expected_modified)
            user = frappe.session.user
            if not user or user == "Guest":
                raise CSRConfigurationError(DRAFT_DENIED)
            company = frappe.get_doc("Company", company_name)
            if company.doctype != "Company" or company.name != company_name:
                raise CSRConfigurationError(DRAFT_INVALID)
            if not all(saved_row_has_permission(has_permission, "Company", operation,
                       doc=company, user=user) for operation in ("read", "write")):
                raise CSRConfigurationError(DRAFT_DENIED)
            if _revision(company.modified) != expected:
                raise CSRConfigurationError(DRAFT_CHANGED)
            for field in CONFIG_FIELDS:
                value = getattr(company, field)
                if (type(value) is not str or len(value) > 1024
                        or any(ord(char) < 32 or ord(char) == 127 or char in "\x85\u2028\u2029" for char in value)):
                    raise CSRConfigurationError(DRAFT_VALUES)
            config = _build_csr_config(company)
            return {"status": "DRAFT", "company_name": company_name,
                    "modified": expected_modified, "config": config}
    except CSRConfigurationError as error:
        message = error.message if type(error) is CSRConfigurationError else DRAFT_FAILED
        denied = message == DRAFT_DENIED
    except Exception:
        message = DRAFT_FAILED
    # Present once outside the child-mute/exception scope; never stringify raw
    # ERP/ACL exceptions or attach their implicit context to the public failure.
    frappe.throw(_(message), exc=frappe.PermissionError if denied else frappe.ValidationError,
                 title=_("CSR Configuration Failed"))


@frappe.whitelist()
def get_csr_config(company_abbr):
    """
    Retrieve and generate CSR configuration data for a company based on its abbreviation.
    """
    try:
        company_name_val = frappe.db.get_value(
            "Company", {"abbr": company_abbr}, "name"
        )
        if not company_name_val:
            frappe.throw(f"Company with abbreviation {company_abbr} not found.")
        company_doc = frappe.get_doc("Company", company_name_val)
        config = _build_csr_config(company_doc)

        frappe.msgprint(
            msg=f"<div style='font-size: 12px; white-space: pre-wrap;'>{escape(config)}</div>",
            title="Thank You! Successfully completed CSR configuration",
        )
        return config
    except Exception as e:
        frappe.throw(_(str(e)))
