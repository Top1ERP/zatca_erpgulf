# tax_error.py

"""this module contains functions that are used to validate tax information
in sales invoices."""

import frappe
from frappe import _
from frappe.utils import cint, flt


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



_ZATCA_NEGATIVE_LINE_VALIDATION_FIELD = "custom_zatca_negative_line_validation_mode"
_ZATCA_NEGATIVE_LINE_VALIDATION_MODES = {"Strict", "Warn Only", "Disabled"}

_ZATCA_ITEM_POSITIVE_FIELDS = (
    ("qty", "Quantity"),
    ("rate", "Rate"),
    ("amount", "Amount"),
    ("net_rate", "Net Rate"),
    ("net_amount", "Net Amount"),
    ("base_rate", "Base Rate"),
    ("base_amount", "Base Amount"),
    ("base_net_rate", "Base Net Rate"),
    ("base_net_amount", "Base Net Amount"),
)


_ZATCA_ITEM_RATE_FIELDS = (
    ("rate", "Rate"),
    ("net_rate", "Net Rate"),
    ("base_rate", "Base Rate"),
    ("base_net_rate", "Base Net Rate"),
)


def _company_has_negative_line_validation_field() -> bool:
    """
    Return True only if the site has the Company custom field installed.

    This keeps shared benches safe while migrating/testing one site first.
    Sites that were not migrated yet will not suddenly enforce the new rule.
    """
    try:
        return bool(frappe.get_meta("Company").has_field(_ZATCA_NEGATIVE_LINE_VALIDATION_FIELD))
    except Exception:
        return False


def _get_negative_line_validation_mode(company_doc) -> str:
    """
    Return company-level validation mode.

    If the field does not exist on this site yet, validation is skipped for
    backward compatibility during staged rollout.
    """
    if not _company_has_negative_line_validation_field():
        return "Disabled"

    mode = _safe_str(getattr(company_doc, _ZATCA_NEGATIVE_LINE_VALIDATION_FIELD, None))

    if not mode:
        return "Strict"

    if mode not in _ZATCA_NEGATIVE_LINE_VALIDATION_MODES:
        return "Strict"

    return mode


def _build_negative_line_issue_line(doc, issue) -> str:
    field_label = _(issue.get("field_label") or "")
    value = issue.get("value")

    reason = issue.get("reason")
    if not reason:
        if issue.get("fieldname") == "qty":
            reason = (
                "Return / credit note item quantity must be zero or negative."
                if cint(getattr(doc, "is_return", 0)) == 1
                else "Standard invoice and debit note item quantity must be zero or greater."
            )
        elif cint(getattr(doc, "is_return", 0)) == 1:
            reason = "Item rates must not be negative."
        else:
            reason = "Item rates, prices, and amounts must not be negative."

    reason = _(reason)

    if issue.get("item_code"):
        return _("- Row {0}, Item {1}, {2}: {3}. {4}").format(
            issue.get("idx") or "",
            issue.get("item_code"),
            field_label,
            value,
            reason,
        )

    return _("- Row {0}, {1}: {2}. {3}").format(
        issue.get("idx") or "",
        field_label,
        value,
        reason,
    )


def _build_negative_line_validation_message(doc, issues) -> str:
    shown_issues = issues[:10]

    issue_lines = []
    for issue in shown_issues:
        if issue.get("custom_message"):
            issue_lines.append(issue["custom_message"])
            continue

        issue_lines.append(_build_negative_line_issue_line(doc, issue))

    if len(issues) > len(shown_issues):
        issue_lines.append(
            _("- ... and {0} more invalid values.").format(
                len(issues) - len(shown_issues)
            )
        )

    document_name = getattr(doc, "name", "") or _("new document")

    return "\n".join(
        [
            _("ZATCA item line validation failed."),
            "",
            _("For standard invoices and debit notes:"),
            "- " + _("Item quantity must not be negative."),
            "- " + _("Item rates, prices, and amounts must not be negative."),
            "- " + _("Zero quantity and zero monetary values are allowed by this ZATCA validation layer."),
            "",
            _("For returns / credit notes:"),
            "- " + _("Item quantity must not be positive."),
            "- " + _("Item rates must not be negative."),
            "- " + _("Zero quantity is allowed by this ZATCA validation layer."),
            "",
            _("Document {0} {1} contains invalid item values:").format(
                doc.doctype,
                document_name,
            ),
            "\n".join(issue_lines),
            "",
            _("If a row represents a discount, use the discount fields."),
            _("If it represents retention or deduction, use the taxes and deductions table."),
            _("If it represents an advance payment, create a Payment Entry and issue an Advance Tax Invoice (386)."),
        ]
    )


def _build_quantity_sign_issue(item, expected, actual_value):
    return {
        "idx": getattr(item, "idx", None) or "",
        "item_code": getattr(item, "item_code", None),
        "fieldname": "qty",
        "field_label": "Quantity",
        "value": actual_value,
        "reason": expected,
    }


_ZATCA_EXEMPTION_REASON_REQUIRED_CATEGORIES = {
    "Zero Rated",
    "Exempted",
    "Services outside scope of tax / Not subject to VAT",
}


def _zatca_category_requires_exemption_reason(zatca_tax_category) -> bool:
    return _safe_str(zatca_tax_category) in _ZATCA_EXEMPTION_REASON_REQUIRED_CATEGORIES


def _get_item_tax_template_doc(item):
    template_name = _safe_str(getattr(item, "item_tax_template", None))
    if not template_name:
        return None

    return frappe.get_doc("Item Tax Template", template_name)


def validate_zatca_tax_category_and_exemption_reason(doc) -> None:
    """Validate that ZATCA tax category and exemption reason are complete.

    Rules:
    - If one item uses Item Tax Template, all items must use Item Tax Template.
    - Item Tax Template must define ZATCA Tax Category.
    - ZATCA exemption reason is mandatory for Zero Rated, Exempted, and Out of Scope categories.
    - Export invoices must explicitly carry a ZATCA tax category and exemption/zero-rating reason.
    """
    if doc.doctype not in {"Sales Invoice", "POS Invoice"}:
        return

    items = list(getattr(doc, "items", []) or [])
    any_item_has_tax_template = any(
        _safe_str(getattr(item, "item_tax_template", None)) for item in items
    )

    if any_item_has_tax_template:
        missing_template_rows = [
            str(getattr(item, "idx", "") or "")
            for item in items
            if not _safe_str(getattr(item, "item_tax_template", None))
        ]

        if missing_template_rows:
            frappe.throw(
                _(
                    "All item rows must have an Item Tax Template when any row uses an Item Tax Template. Missing rows: {0}."
                ).format(", ".join(missing_template_rows))
            )

        for item in items:
            item_tax_template = _get_item_tax_template_doc(item)
            if not item_tax_template:
                continue

            zatca_tax_category = _safe_str(
                getattr(item_tax_template, "custom_zatca_tax_category", None)
            )
            exemption_reason_code = _safe_str(
                getattr(item_tax_template, "custom_exemption_reason_code", None)
            )

            if not zatca_tax_category:
                frappe.throw(
                    _(
                        "ZATCA Tax Category is required in Item Tax Template {0} used by row {1}."
                    ).format(
                        item_tax_template.name,
                        getattr(item, "idx", "") or "",
                    )
                )

            if (
                _zatca_category_requires_exemption_reason(zatca_tax_category)
                and not exemption_reason_code
            ):
                frappe.throw(
                    _(
                        "ZATCA exemption reason is required in Item Tax Template {0} for row {1} because the ZATCA tax category is {2}."
                    ).format(
                        item_tax_template.name,
                        getattr(item, "idx", "") or "",
                        _(zatca_tax_category),
                    )
                )

        return

    invoice_zatca_tax_category = _safe_str(
        getattr(doc, "custom_zatca_tax_category", None)
    )
    invoice_exemption_reason_code = _safe_str(
        getattr(doc, "custom_exemption_reason_code", None)
    )

    if cint(getattr(doc, "custom_zatca_export_invoice", 0)) == 1:
        if not invoice_zatca_tax_category:
            frappe.throw(
                _("ZATCA Tax Category is required when ZATCA Export Invoice is enabled.")
            )

        if not invoice_exemption_reason_code:
            frappe.throw(
                _("ZATCA exemption reason is required when ZATCA Export Invoice is enabled.")
            )

    if (
        _zatca_category_requires_exemption_reason(invoice_zatca_tax_category)
        and not invoice_exemption_reason_code
    ):
        frappe.throw(
            _(
                "ZATCA exemption reason is required when the ZATCA tax category is {0}."
            ).format(_(invoice_zatca_tax_category))
        )


def validate_positive_item_values_for_zatca(doc, company_doc) -> None:
    """
    Validate ZATCA item line values.

    Rules:
    - Standard invoices and debit notes:
      * item quantity must not be negative
      * item rates and amounts must not be negative
    - Returns / credit notes:
      * item quantity must not be positive
      * item rates must not be negative
      * line amounts are not blocked here because ERPNext return rows may carry
        negative amounts and XML builders convert return values to absolute
        positive values.
    - Zero quantity is allowed by this validation layer.
    - Zero monetary values are allowed, for example free samples.
    - Taxes table rows are intentionally not validated here because retention
      and deductions may be represented there depending on ERPNext configuration.
    """
    if doc.doctype not in {"Sales Invoice", "POS Invoice"}:
        return

    mode = _get_negative_line_validation_mode(company_doc)

    if mode == "Disabled":
        return

    is_return = cint(getattr(doc, "is_return", 0)) == 1
    issues = []

    for item in getattr(doc, "items", []) or []:
        qty = flt(getattr(item, "qty", 0))

        if is_return:
            if qty > 0:
                issues.append(
                    _build_quantity_sign_issue(
                        item,
                        "Return / credit note item quantity must be zero or negative.",
                        getattr(item, "qty", None),
                    )
                )

            # Return / credit note quantities may be negative, but item rates
            # must still be zero or positive. Do not validate line amounts here,
            # because ERPNext may calculate return amounts as negative values.
            for fieldname, field_label in _ZATCA_ITEM_RATE_FIELDS:
                value = getattr(item, fieldname, None)

                if flt(value) < 0:
                    issues.append(
                        {
                            "idx": getattr(item, "idx", None) or "",
                            "item_code": getattr(item, "item_code", None),
                            "fieldname": fieldname,
                            "field_label": field_label,
                            "value": value,
                        }
                    )

            continue

        # Standard invoices and debit notes must not have negative quantity.
        if qty < 0:
            issues.append(
                _build_quantity_sign_issue(
                    item,
                    "Standard invoice and debit note item quantity must be zero or greater.",
                    getattr(item, "qty", None),
                )
            )

        # Monetary zero values are allowed. Negative monetary values are blocked.
        for fieldname, field_label in _ZATCA_ITEM_POSITIVE_FIELDS:
            if fieldname == "qty":
                continue

            value = getattr(item, fieldname, None)

            if flt(value) < 0:
                issues.append(
                    {
                        "idx": getattr(item, "idx", None) or "",
                        "item_code": getattr(item, "item_code", None),
                        "fieldname": fieldname,
                        "field_label": field_label,
                        "value": value,
                    }
                )

    if not issues:
        return

    message = _build_negative_line_validation_message(doc, issues)

    if mode == "Warn Only":
        frappe.msgprint(
            message,
            title="ZATCA Negative Line Validation",
            indicator="orange",
        )
        frappe.log_error(
            title="ZATCA Negative Line Validation Warning",
            message=message,
        )
        return

    frappe.throw(
        message,
        title="ZATCA Negative Line Validation",
    )

def validate_negative_item_values_on_save(doc, event=None):
    """
    Validate item quantities and negative values on document save.

    This is intentionally limited to item value validation only.
    Do not run the full ZATCA submit validation here because drafts may still
    be incomplete while users are entering invoice data.
    """
    if doc.doctype not in {"Sales Invoice", "POS Invoice"}:
        return

    company = getattr(doc, "company", None)
    if not company:
        return

    company_doc = frappe.get_doc("Company", company)

    if not cint(getattr(company_doc, "custom_zatca_invoice_enabled", 0)):
        return

    validate_positive_item_values_for_zatca(doc, company_doc)
    validate_zatca_tax_category_and_exemption_reason(doc)

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

    validate_positive_item_values_for_zatca(doc, company_doc)
    validate_zatca_tax_category_and_exemption_reason(doc)

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
        is_advance_credit_note = (
            doc.doctype == "Sales Invoice"
            and cint(getattr(doc, "custom_is_advance_credit_note", 0)) == 1
        )

        if is_advance_credit_note:
            advance_reference = str(
                getattr(doc, "custom_advance_invoice_reference", "") or ""
            ).strip()

            if not advance_reference:
                frappe.throw(
                    _(
                        "Advance Invoice Reference is required when this credit note "
                        "cancels or reverses a ZATCA advance payment invoice."
                    )
                )

            if not frappe.db.exists("ZATCA Advance Tax Invoice", advance_reference):
                frappe.throw(
                    _("ZATCA Advance Tax Invoice not found: {0}").format(
                        advance_reference
                    )
                )

            advance_doc = frappe.get_doc("ZATCA Advance Tax Invoice", advance_reference)
            advance_status_values = [
                getattr(advance_doc, "zatca_status", None),
                getattr(advance_doc, "zatca_clearance_status", None),
                getattr(advance_doc, "zatca_reporting_status", None),
            ]

            if not any(
                str(status or "").strip().lower() in {"cleared", "reported"}
                for status in advance_status_values
            ):
                frappe.throw(
                    _(
                        "Original ZATCA advance payment invoice must be Cleared or "
                        "Reported before creating a credit note."
                    )
                )

        elif not getattr(doc, "return_against", None):
            frappe.throw(
                _(
                    "As per ZATCA regulation, the Billing Reference ID "
                    "(Original Invoice Number) is mandatory for "
                    "Credit Notes and Return Invoices.\n"
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
