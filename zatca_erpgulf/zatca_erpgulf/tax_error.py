# tax_error.py

"""this module contains functions that are used to validate tax information
in sales invoices."""

import frappe
from frappe import _
from frappe.utils import cint


def _safe_str(value):
    """Return stripped string or empty string."""
    if value is None:
        return ""
    return str(value).strip()


def _is_meaningful_value(value):
    """
    Check whether a value is actually usable and not just a placeholder.
    """
    value = _safe_str(value)
    if not value:
        return False

    invalid_values = {
        "not submitted",
        "none",
        "null",
        "n/a",
        "na",
    }
    return value.lower() not in invalid_values


def _get_machine_unique_id(doc):
    """
    Return machine unique id while supporting both possible field names.

    Priority:
    1. custom_unique_id -> real machine ID field in many sites
    2. custom_uuid -> fallback only if it contains a real meaningful value
    """
    custom_unique_id = getattr(doc, "custom_unique_id", None)
    custom_uuid = getattr(doc, "custom_uuid", None)

    if _is_meaningful_value(custom_unique_id):
        return _safe_str(custom_unique_id)

    if _is_meaningful_value(custom_uuid):
        return _safe_str(custom_uuid)

    return ""


def _get_pos_name(doc):
    """Safely get POS machine name."""
    return _safe_str(getattr(doc, "custom_zatca_pos_name", None))


def validate_sales_invoice_taxes(doc, event=None):
    """
    Validate tax information and required ZATCA-related fields
    before Sales Invoice submit.
    """
    company_doc = frappe.get_doc("Company", doc.company)

    # ----------------------------------------
    # Exit early if ZATCA is not enabled
    # ----------------------------------------
    if not cint(getattr(company_doc, "custom_zatca_invoice_enabled", 0)):
        return

    is_gpos_installed = "gpos" in frappe.get_installed_apps()
    meta = frappe.get_meta(doc.doctype)

    has_custom_unique_id = meta.has_field("custom_unique_id")
    has_custom_uuid = meta.has_field("custom_uuid")
    has_pos_name_field = meta.has_field("custom_zatca_pos_name")

    machine_unique_id = ""
    pos_name = ""

    if has_custom_unique_id or has_custom_uuid:
        machine_unique_id = _get_machine_unique_id(doc)

    if has_pos_name_field:
        pos_name = _get_pos_name(doc)

    # ----------------------------------------
    # POS Validation
    # ----------------------------------------
    # Preserve original behavior as much as possible:
    # Only validate machine settings if user/site is actually using them.
    if cint(getattr(doc, "is_pos", 0)) == 1 and is_gpos_installed:
        if machine_unique_id or pos_name:
            if not (machine_unique_id and pos_name):
                frappe.throw(
                    _("POS Invoice requires both ZATCA Machine unique ID and POS Name.")
                )

    customer_doc = frappe.get_doc("Customer", doc.customer)

    # ----------------------------------------
    # Export Invoice Validation
    # ----------------------------------------
    if cint(getattr(doc, "custom_zatca_export_invoice", 0)) == 1:
        address_name = getattr(customer_doc, "customer_primary_address", None)
        if not address_name:
            frappe.throw(
                _("Customer address is required to validate Export Invoice.")
            )

        address = frappe.get_doc("Address", address_name)
        country = (getattr(address, "country", "") or "").strip()

        if country.lower() == "saudi arabia":
            frappe.throw(
                _(
                    "ZATCA Export Invoice cannot be enabled when the customer country is Saudi Arabia."
                )
            )

    # ----------------------------------------
    # Validate linked POS machine setting company
    # ----------------------------------------
    if pos_name:
        zatca_settings = frappe.get_doc("ZATCA Multiple Setting", pos_name)
        linked_company_name = getattr(zatca_settings, "custom_linked_doctype", None)

        if linked_company_name:
            linked_company_doc = frappe.get_doc("Company", linked_company_name)

            if linked_company_doc.name != doc.company:
                frappe.throw(
                    _(
                        f"Company mismatch: Document company '{doc.company}' "
                        f"does not match linked ZATCA company "
                        f"'{linked_company_doc.name}' of machine setting."
                    )
                )

    # ----------------------------------------
    # Cost Center / Branch Validation
    # ----------------------------------------
    if cint(getattr(company_doc, "custom_costcenter", 0)) == 1:
        if not getattr(doc, "cost_center", None):
            frappe.throw(_("This company requires a Cost Center"))

        cost_center_doc = frappe.get_doc("Cost Center", doc.cost_center)

        if not getattr(cost_center_doc, "custom_zatca_branch_address", None):
            frappe.throw(
                _(
                    f"As per ZATCA regulation, the Cost Center '{doc.cost_center}' is missing a valid branch address. "
                    "Please update the Cost Center with a valid `custom_zatca_branch_address`."
                )
            )

        registration_type = (
            getattr(cost_center_doc, "custom_registration_type", None)
            or getattr(cost_center_doc, "custom_zatca__registration_type", None)
        )
        registration_number = (
            getattr(cost_center_doc, "custom_registration_number", None)
            or getattr(cost_center_doc, "custom_zatca__registration_number", None)
        )

        if not registration_type:
            frappe.throw(
                _(
                    f"As per ZATCA regulation, the Cost Center '{doc.cost_center}' is missing a valid registration type. "
                    "Please update the Cost Center with a valid registration type field."
                )
            )

        if not registration_number:
            frappe.throw(
                _(
                    f"As per ZATCA regulation, the Cost Center '{doc.cost_center}' is missing a valid registration number. "
                    "Please update the Cost Center with a valid registration number field."
                )
            )

    # ----------------------------------------
    # Validate item tax template existence
    # ----------------------------------------
    if not getattr(doc, "items", None):
        frappe.throw(_("Sales Invoice must contain at least one item."))

    for item in doc.items:
        item_tax_template = getattr(item, "item_tax_template", None)
        if item_tax_template:
            try:
                frappe.get_doc("Item Tax Template", item_tax_template)
            except frappe.DoesNotExistError:
                frappe.throw(
                    _(
                        f"As per ZATCA regulation, the Item Tax Template '{item_tax_template}' "
                        f"for item '{item.item_code}' does not exist."
                    )
                )

    # ----------------------------------------
    # Taxes validation
    # ----------------------------------------
    if not getattr(doc, "taxes", None):
        all_items_have_template = all(
            getattr(item, "item_tax_template", None) for item in doc.items
        )
        if not all_items_have_template:
            frappe.throw(
                _(
                    "As per ZATCA regulation, tax information is missing from the Sales Invoice. "
                    "Either add an Item Tax Template for all items or include taxes in the invoice."
                )
            )

    # Prevent mixing item tax template and no template
    has_template = any(getattr(item, "item_tax_template", None) for item in doc.items)
    has_no_template = any(not getattr(item, "item_tax_template", None) for item in doc.items)

    if has_template and has_no_template:
        frappe.throw(
            _(
                "All items must either use Item Tax Template or none should use it. Mixing is not allowed."
            )
        )

    # ----------------------------------------
    # Return / Credit Note validation
    # ----------------------------------------
    if cint(getattr(doc, "is_return", 0)) == 1 and doc.doctype in ["Sales Invoice", "POS Invoice"]:
        if not getattr(doc, "return_against", None):
            frappe.throw(
                _(
                    "As per ZATCA regulation, the Billing Reference ID "
                    "(Original Invoice Number) is mandatory for "
                    "Credit Notes and Return Invoices. "
                    "Please select the original invoice in the 'Return Against' field."
                )
            )

    # ----------------------------------------
    # Debit Note validation
    # ----------------------------------------
    if doc.doctype == "Sales Invoice":
        if cint(getattr(doc, "is_debit_note", 0)) == 1 and not getattr(doc, "return_against", None):
            frappe.throw(
                _("Debit Note must reference a Sales Invoice in 'Return Against'.")
            )

    # ----------------------------------------
    # Advance Rows Validation
    # ----------------------------------------
    if doc.doctype == "Sales Invoice":
        if "claudion4saudi" in frappe.get_installed_apps():
            if hasattr(doc, "custom_advances_copy") and doc.custom_advances_copy:
                for advance_row in doc.custom_advances_copy:
                    if (
                        getattr(advance_row, "difference_posting_date", None)
                        and not getattr(advance_row, "reference_name", None)
                    ):
                        frappe.throw(
                            _(
                                "⚠️ As per ZATCA regulation, missing Advance Sales Invoice reference name in fetched details. "
                                "If there is no advance sales invoice, then remove the row from the table."
                            )
                        )