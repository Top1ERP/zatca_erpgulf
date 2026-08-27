# tax_error.py

"""this module contains functions that are used to validate tax information
in sales invoices."""

import frappe
from frappe import _
from frappe.utils import cint, flt
from zatca_erpgulf.zatca_erpgulf.createxml import get_zatca_discount_reason_code
from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    PHASE_2_VALUE,
    is_zatca_invoice_enabled,
    resolve_zatca_phase,
    supports_advance_deduction_schema,
)


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

_ZATCA_CATEGORY_RATE_VALIDATION_FIELD = "custom_enforce_zatca_tax_category_rate_validation"
_ZATCA_NON_STANDARD_CATEGORIES = {
    "Zero Rated",
    "Exempted",
    "Services outside scope of tax / Not subject to VAT",
}


def _is_phase2_category_rate_validation_enabled(company_doc) -> bool:
    """Gate zero-rate enforcement by company, phase, and explicit setting."""
    if not company_doc:
        return False
    meta = getattr(company_doc, "meta", None)
    if meta and not meta.has_field(_ZATCA_CATEGORY_RATE_VALIDATION_FIELD):
        return False
    return bool(
        is_zatca_invoice_enabled(company_doc)
        and resolve_zatca_phase(company_doc) == PHASE_2_VALUE
        and cint(getattr(company_doc, _ZATCA_CATEGORY_RATE_VALIDATION_FIELD, 0) or 0)
    )


def _is_advance_invoice(invoice) -> bool:
    meta = getattr(invoice, "meta", None)
    if meta and meta.has_field("is_advance_payment"):
        return bool(cint(getattr(invoice, "is_advance_payment", 0) or 0))
    if meta and meta.has_field("custom_is_advance_payment"):
        return bool(cint(getattr(invoice, "custom_is_advance_payment", 0) or 0))
    return False


def _advance_tax_template_signature(item_tax_template):
    """Return the one category/rate pair represented by an item template."""
    category = _safe_str(getattr(item_tax_template, "custom_zatca_tax_category", None))
    rates = {
        round(flt(getattr(row, "tax_rate", 0) or 0), 6)
        for row in (getattr(item_tax_template, "taxes", []) or [])
    }
    if not category or len(rates) != 1:
        return None
    return category, next(iter(rates))


def validate_advance_payment_invoice_tax_structure(invoice) -> None:
    """Require exactly one VAT category/rate combination on advance invoices."""
    if cint(getattr(invoice, "is_return", 0)) or not _is_advance_invoice(invoice):
        return

    items = list(invoice.get("items") or [])
    template_names = [_safe_str(getattr(item, "item_tax_template", None)) for item in items]
    has_templates = any(template_names)
    if has_templates and not all(template_names):
        frappe.throw(
            _(
                "Advance Payment Invoice cannot mix items with and without Item Tax Template. "
                "Use one Item Tax Template on every item, or use invoice-level taxes only."
            )
        )
    if not has_templates:
        if not _safe_str(getattr(invoice, "taxes_and_charges", None)):
            frappe.throw(
                _(
                    "Advance Payment Invoice without Item Tax Templates must use "
                    "invoice-level taxes_and_charges as its single tax source."
                )
            )

        source = _get_invoice_level_zatca_source(invoice)
        if not _safe_str(source.get("category")):
            frappe.throw(
                _(
                    "Advance Payment Invoice must resolve to exactly one ZATCA VAT category. "
                    "Configure the invoice-level tax source before saving."
                )
            )

        rates = _get_invoice_level_tax_rates(invoice)
        if len(rates) != 1:
            frappe.throw(
                _(
                    "An Advance Payment Invoice may contain only one VAT rate. "
                    "Split invoices when different VAT rates are required."
                )
            )
        return

    signatures = set()
    for item in items:
        template = frappe.get_doc("Item Tax Template", _safe_str(item.item_tax_template))
        signature = _advance_tax_template_signature(template)
        if signature is None:
            frappe.throw(
                _(
                    "Advance Payment Invoice requires every Item Tax Template to resolve "
                    "to exactly one VAT category and VAT rate."
                )
            )
        signatures.add(signature)

    if len(signatures) > 1:
        frappe.throw(
            _(
                "An Advance Payment Invoice may contain only one VAT category and VAT rate. "
                "Split invoices when different VAT rates or categories are required."
            )
        )


def validate_zatca_zero_rate_categories(doc, company_doc=None) -> None:
    """Reject non-zero rates/tax for Z/E/O in enabled Phase-2 companies."""
    if doc.doctype not in {"Sales Invoice", "POS Invoice"}:
        return
    if company_doc is None and getattr(doc, "company", None):
        company_doc = frappe.get_doc("Company", doc.company)
    if not _is_phase2_category_rate_validation_enabled(company_doc):
        return

    items = list(getattr(doc, "items", []) or [])
    if any(_safe_str(getattr(item, "item_tax_template", None)) for item in items):
        for item in items:
            template_name = _safe_str(getattr(item, "item_tax_template", None))
            if not template_name:
                continue
            template = _get_item_tax_template_doc(item)
            category = _safe_str(getattr(template, "custom_zatca_tax_category", None))
            if category not in _ZATCA_NON_STANDARD_CATEGORIES:
                continue
            for tax in getattr(template, "taxes", []) or []:
                if abs(flt(getattr(tax, "tax_rate", 0) or 0)) > 0.000001:
                    frappe.throw(
                        _(
                            "ZATCA categories Zero Rated, Exempted, and Outside Scope "
                            "must use a zero VAT rate."
                        )
                    )
        return

    source = _get_invoice_level_zatca_source(doc)
    category = _safe_str(source.get("category"))
    if category not in _ZATCA_NON_STANDARD_CATEGORIES:
        return
    if any(abs(flt(getattr(tax, "rate", 0) or 0)) > 0.000001 for tax in doc.taxes):
        frappe.throw(
            _(
                "ZATCA categories Zero Rated, Exempted, and Outside Scope "
                "must use a zero VAT rate."
            )
        )
    if any(
        abs(flt(getattr(tax, "tax_amount", 0) or 0)) > 0.000001
        or abs(flt(getattr(tax, "base_tax_amount", 0) or 0)) > 0.000001
        for tax in doc.taxes
    ):
        frappe.throw(
            _(
                "ZATCA categories Zero Rated, Exempted, and Outside Scope "
                "must not produce a VAT amount."
            )
        )


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


def _get_zatca_user_language() -> str:
    """Return the user's configured language for ZATCA validation messages."""
    try:
        user = getattr(frappe.session, "user", None)
        if user and user != "Guest":
            user_language = frappe.db.get_value("User", user, "language")
            if user_language:
                return _safe_str(user_language)
    except Exception:
        pass

    return _safe_str(getattr(frappe.local, "lang", None) or "en")


def _zt(source_text: str) -> str:
    """Translate ZATCA validation text only when the user selected Arabic."""
    source_text = _safe_str(source_text)
    if not source_text:
        return ""

    user_language = _get_zatca_user_language().lower()

    if user_language.startswith("ar"):
        try:
            return _(source_text, lang="ar")
        except TypeError:
            old_lang = getattr(frappe.local, "lang", None)
            try:
                frappe.local.lang = "ar"
                return _(source_text)
            finally:
                frappe.local.lang = old_lang

    return source_text


def _build_negative_line_issue_line(doc, issue) -> str:
    field_label = _zt(issue.get("field_label") or "")
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

    reason = _zt(reason)

    if issue.get("item_code"):
        return _zt("- Row {0}, Item {1}, {2}: {3}. {4}").format(
            issue.get("idx") or "",
            issue.get("item_code"),
            field_label,
            value,
            reason,
        )

    return _zt("- Row {0}, {1}: {2}. {3}").format(
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
            _zt("- ... and {0} more invalid values.").format(
                len(issues) - len(shown_issues)
            )
        )

    document_name = getattr(doc, "name", "") or _zt("new document")

    return "\n".join(
        [
            _zt("ZATCA item line validation failed."),
            "",
            _zt("For standard invoices and debit notes:"),
            "- " + _zt("Item quantity must not be negative."),
            "- " + _zt("Item rates, prices, and amounts must not be negative."),
            "- " + _zt("Zero quantity and zero monetary values are allowed by this ZATCA validation layer."),
            "",
            _zt("For returns / credit notes:"),
            "- " + _zt("Item quantity must not be positive."),
            "- " + _zt("Item rates must not be negative."),
            "- " + _zt("Zero quantity is allowed by this ZATCA validation layer."),
            "",
            _zt("Document {0} {1} contains invalid item values:").format(
                doc.doctype,
                document_name,
            ),
            "\n".join(issue_lines),
            "",
            _zt("If a row represents a discount, use the discount fields."),
            _zt("If it represents retention or deduction, use the taxes and deductions table."),
            _zt("If it represents an advance payment, create a Payment Entry and issue an Advance Tax Invoice (386)."),
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


_ZATCA_STANDARD_CATEGORY = "Standard"

_ZATCA_EXEMPTION_REASON_REQUIRED_CATEGORIES = {
    "Zero Rated",
    "Exempted",
    "Services outside scope of tax / Not subject to VAT",
}

_ZATCA_NON_STANDARD_CATEGORIES = _ZATCA_EXEMPTION_REASON_REQUIRED_CATEGORIES


def _zatca_category_requires_exemption_reason(zatca_tax_category) -> bool:
    return _safe_str(zatca_tax_category) in _ZATCA_EXEMPTION_REASON_REQUIRED_CATEGORIES


def _get_item_tax_template_doc(item):
    template_name = _safe_str(getattr(item, "item_tax_template", None))
    if not template_name:
        return None

    return frappe.get_doc("Item Tax Template", template_name)


def _is_zatca_tax_category_source_validation_enabled(company_doc) -> bool:
    """Return true unless the company explicitly disables the source consistency rule."""
    if not company_doc:
        return True

    try:
        company_meta = frappe.get_meta("Company")
        fieldname = "custom_enforce_zatca_tax_category_source_validation"

        if not company_meta.has_field(fieldname):
            return True

        return cint(getattr(company_doc, fieldname, 1)) == 1
    except Exception:
        return True


def _get_template_rate(template_doc, child_field="taxes") -> float:
    rows = list(getattr(template_doc, child_field, []) or [])

    if not rows:
        return 0.0

    first_row = rows[0]

    for fieldname in ("tax_rate", "rate"):
        value = getattr(first_row, fieldname, None)
        if value not in (None, ""):
            return flt(value)

    return 0.0


def _invoice_has_tax_amount(doc) -> bool:
    for fieldname in ("base_total_taxes_and_charges", "total_taxes_and_charges"):
        if abs(flt(getattr(doc, fieldname, 0))) > 0.000001:
            return True

    for tax_row in getattr(doc, "taxes", []) or []:
        for fieldname in ("base_tax_amount", "tax_amount"):
            if abs(flt(getattr(tax_row, fieldname, 0))) > 0.000001:
                return True

    return False


def _has_allowed_zero_tax_standard_exception(doc) -> bool:
    if cint(getattr(doc, "custom_zatca_nominal_invoice", 0)) == 1:
        return True

    if cint(getattr(doc, "custom_zatca_export_invoice", 0)) == 1:
        return True

    if supports_advance_deduction_schema(doc):
        if abs(flt(getattr(doc, "custom_zatca_prepaid_amount", 0))) > 0.000001:
            return True

        if cint(getattr(doc, "custom_zatca_advance_deduction_count", 0)) > 0:
            return True

    return False


def _has_invoice_discount(doc) -> bool:
    for fieldname in (
        "discount_amount",
        "base_discount_amount",
        "additional_discount_percentage",
        "discount_percentage",
    ):
        if abs(flt(getattr(doc, fieldname, 0))) > 0.000001:
            return True

    for item in getattr(doc, "items", []) or []:
        for fieldname in ("discount_amount", "discount_percentage"):
            if abs(flt(getattr(item, fieldname, 0))) > 0.000001:
                return True

    return False


def _validate_discount_reason_if_required(doc) -> None:
    if not _has_invoice_discount(doc):
        return

    discount_reason = _safe_str(
        getattr(doc, "custom_zatca_discount_reason", None)
    )
    discount_reason_code = get_zatca_discount_reason_code(discount_reason)

    if not discount_reason or not discount_reason_code:
        frappe.throw(
            _zt(
                "A ZATCA discount reason code and reason are required when the invoice contains a discount."
            )
        )


def _validate_category_rate_consistency(
    zatca_tax_category,
    tax_rate,
    source_name,
    exemption_reason_code=None,
    doc=None,
) -> None:
    category = _safe_str(zatca_tax_category)
    rate = abs(flt(tax_rate))

    if not category:
        frappe.throw(
            _zt(
                "ZATCA Tax Category is required in {0}. Please configure the tax template before submitting the invoice."
            ).format(source_name)
        )

    if category == _ZATCA_STANDARD_CATEGORY:
        if rate <= 0.000001:
            frappe.throw(
                _zt(
                    "Standard ZATCA tax category requires a tax rate greater than zero in {0}."
                ).format(source_name)
            )

        if doc and not _invoice_has_tax_amount(doc) and not _has_allowed_zero_tax_standard_exception(doc):
            frappe.throw(
                _zt(
                    "Standard ZATCA tax category requires a tax amount on the invoice. Add VAT, or use a supported exception such as Nominal Invoice, Export Invoice, or accepted Advance Deductions."
                )
            )

        return

    if category in _ZATCA_NON_STANDARD_CATEGORIES:
        if rate > 0.000001:
            frappe.throw(
                _zt(
                    "Zero-rated, exempt, or out-of-scope ZATCA categories must have a zero tax rate in {0}."
                ).format(source_name)
            )

        if doc and _invoice_has_tax_amount(doc):
            frappe.throw(
                _zt(
                    "Zero-rated, exempt, or out-of-scope ZATCA categories must not produce a tax amount on the invoice."
                )
            )

        if not _safe_str(exemption_reason_code):
            frappe.throw(
                _zt(
                    "ZATCA exemption or exception reason code is required in {0} when the category is {1}."
                ).format(source_name, _zt(category))
            )

        return


def _get_sales_taxes_template_doc(doc):
    template_name = _safe_str(getattr(doc, "taxes_and_charges", None))
    if not template_name:
        return None

    if not frappe.db.exists("Sales Taxes and Charges Template", template_name):
        return None

    return frappe.get_doc("Sales Taxes and Charges Template", template_name)


def _get_invoice_level_tax_rate(doc) -> float:
    for tax_row in getattr(doc, "taxes", []) or []:
        value = getattr(tax_row, "rate", None)

        if value not in (None, ""):
            return flt(value)

    return 0.0


def _get_invoice_level_tax_rates(doc) -> set[float]:
    """Return every effective invoice-level tax rate, preserving zero rates."""
    rates = set()
    for tax_row in getattr(doc, "taxes", []) or []:
        value = getattr(tax_row, "rate", None)
        if value not in (None, ""):
            rates.add(round(flt(value), 6))
    return rates


def _get_invoice_level_zatca_source(doc):
    """Resolve invoice-level ZATCA fields, preferring Sales Invoice values."""
    sales_template = _get_sales_taxes_template_doc(doc)
    invoice_category = _safe_str(getattr(doc, "custom_zatca_tax_category", None))
    invoice_exemption_reason = _safe_str(getattr(doc, "custom_exemption_reason_code", None))
    invoice_rate = _get_invoice_level_tax_rate(doc)

    template_category = ""
    template_exemption_reason = ""
    template_rate = None
    if sales_template:
        template_category = _safe_str(getattr(sales_template, "custom_zatca_tax_category", None))
        template_exemption_reason = _safe_str(
            getattr(sales_template, "custom_exemption_reason_code", None)
        )
        template_rate = _get_template_rate(sales_template)

    if invoice_category:
        return {
            "source_type": "invoice",
            "source_name": _zt("Sales Invoice ZATCA fields"),
            "category": invoice_category,
            "exemption_reason": invoice_exemption_reason or template_exemption_reason,
            "rate": invoice_rate if invoice_rate else template_rate,
        }

    if template_category:
        return {
            "source_type": "sales_taxes_template",
            "source_name": _zt("Sales Taxes and Charges Template {0}").format(
                sales_template.name
            ),
            "category": template_category,
            "exemption_reason": template_exemption_reason,
            "rate": template_rate,
        }

    location = (
        _zt("Sales Invoice ZATCA fields and Sales Taxes and Charges Template")
        if sales_template
        else _zt("Sales Invoice ZATCA fields")
    )
    return {
        "source_type": "missing",
        "source_name": location,
        "category": "",
        "exemption_reason": "",
        "rate": template_rate,
    }


def validate_zatca_tax_category_and_exemption_reason(
    doc,
    company_doc=None,
    enforce_source_consistency=False,
) -> None:
    """Validate ZATCA tax category source, exemption reason, and tax rate consistency."""
    if doc.doctype not in {"Sales Invoice", "POS Invoice"}:
        return

    if company_doc is None and getattr(doc, "company", None):
        company_doc = frappe.get_doc("Company", doc.company)

    enforce_source_consistency = (
        enforce_source_consistency
        and _is_zatca_tax_category_source_validation_enabled(company_doc)
    )

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
                _zt(
                    "All item rows must either have an Item Tax Template or none of them should have one. Missing Item Tax Template in rows: {0}."
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
                    _zt(
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
                    _zt(
                        "ZATCA exemption reason is required in Item Tax Template {0} for row {1} because the ZATCA tax category is {2}."
                    ).format(
                        item_tax_template.name,
                        getattr(item, "idx", "") or "",
                        _zt(zatca_tax_category),
                    )
                )

            if enforce_source_consistency:
                _validate_category_rate_consistency(
                    zatca_tax_category,
                    _get_template_rate(item_tax_template),
                    _zt("Item Tax Template {0}").format(item_tax_template.name),
                    exemption_reason_code=exemption_reason_code,
                    doc=None,
                )

        return

    invoice_source = _get_invoice_level_zatca_source(doc)
    invoice_zatca_tax_category = invoice_source["category"]
    invoice_exemption_reason_code = invoice_source["exemption_reason"]

    if cint(getattr(doc, "custom_zatca_export_invoice", 0)) == 1:
        if not invoice_zatca_tax_category:
            frappe.throw(
                _zt("ZATCA Tax Category is required when ZATCA Export Invoice is enabled.")
            )

        if not invoice_exemption_reason_code:
            frappe.throw(
                _zt("ZATCA exemption reason is required when ZATCA Export Invoice is enabled.")
            )

    if (
        _zatca_category_requires_exemption_reason(invoice_zatca_tax_category)
        and not invoice_exemption_reason_code
    ):
        frappe.throw(
            _zt(
                "ZATCA exemption reason is required when the ZATCA tax category is {0}. "
                "The field custom_exemption_reason_code is empty in {1}."
            ).format(_zt(invoice_zatca_tax_category), invoice_source["source_name"])
        )

    if enforce_source_consistency:
        _validate_category_rate_consistency(
            invoice_zatca_tax_category,
            invoice_source["rate"],
            invoice_source["source_name"],
            exemption_reason_code=invoice_exemption_reason_code,
            doc=doc,
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

def _tax_template_uses_only_non_tax_accounts(doc) -> bool:
    """Allow a blank category only for templates with exclusively non-tax accounts."""
    rows = list(getattr(doc, "taxes", []) or [])
    if not rows:
        return False

    account_field = "tax_type" if doc.doctype == "Item Tax Template" else "account_head"
    for row in rows:
        account_name = _safe_str(getattr(row, account_field, None))
        if not account_name:
            return False
        account_type = _safe_str(
            frappe.db.get_value("Account", account_name, "account_type")
        )
        if account_type == "Tax":
            return False

    return True


def validate_tax_template_category_constraints(doc, event=None) -> None:
    """Validate ZATCA category/rate/reason fields on tax templates."""
    if doc.doctype not in {"Sales Taxes and Charges Template", "Item Tax Template"}:
        return
    company = getattr(doc, "company", None)
    if not company:
        return
    company_doc = frappe.get_doc("Company", company)
    if not _is_phase2_category_rate_validation_enabled(company_doc):
        return

    category = _safe_str(getattr(doc, "custom_zatca_tax_category", None))
    if not category and not _tax_template_uses_only_non_tax_accounts(doc):
        frappe.throw(
            _(
                "ZATCA Tax Category is required when any Tax Rates row uses a Tax Account."
            )
        )

    if category == "Standard":
        if getattr(doc, "custom_exemption_reason_code", None):
            doc.custom_exemption_reason_code = ""
        rate_field = "tax_rate" if doc.doctype == "Item Tax Template" else "rate"
        has_positive_rate = any(
            abs(flt(getattr(row, rate_field, 0) or 0)) > 0.000001
            for row in getattr(doc, "taxes", []) or []
        )
        if not has_positive_rate:
            frappe.throw(
                _(
                    "Standard ZATCA tax category requires at least one tax row with a rate greater than zero in {0}."
                ).format(doc.name)
            )
        return

    if category in _ZATCA_NON_STANDARD_CATEGORIES:
        if not _safe_str(getattr(doc, "custom_exemption_reason_code", None)):
            frappe.throw(
                _(
                    "Exemption Reason Code is required for Zero Rated, Exempted, "
                    "and Outside Scope ZATCA categories."
                )
            )
        rate_field = "tax_rate" if doc.doctype == "Item Tax Template" else "rate"
        for row in getattr(doc, "taxes", []) or []:
            if abs(flt(getattr(row, rate_field, 0) or 0)) > 0.000001:
                frappe.throw(
                    _(
                        "ZATCA categories Zero Rated, Exempted, and Outside Scope "
                        "must use a zero VAT rate."
                    )
                )


def validate_zatca_tax_source_presence(doc, company_doc=None) -> None:
    """Require an explicit tax source when ZATCA is enabled."""
    if doc.doctype not in {"Sales Invoice", "POS Invoice"}:
        return
    if company_doc is None and getattr(doc, "company", None):
        company_doc = frappe.get_doc("Company", doc.company)
    if not company_doc or not is_zatca_invoice_enabled(company_doc):
        return

    items = list(getattr(doc, "items", []) or [])
    has_item_templates = any(
        _safe_str(getattr(item, "item_tax_template", None)) for item in items
    )
    if has_item_templates:
        return

    if not _safe_str(getattr(doc, "taxes_and_charges", None)):
        frappe.throw(
            _(
                "ZATCA-enabled Sales Invoices must use either Item Tax Template on every item "
                "or one Sales Taxes and Charges Template at invoice level. All tax sources cannot be blank."
            )
        )
    if not list(getattr(doc, "taxes", []) or []):
        frappe.throw(
            _(
                "ZATCA-enabled Sales Invoices must contain at least one Sales Taxes and Charges row."
            )
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
    validate_advance_payment_invoice_tax_structure(doc)
    validate_zatca_tax_source_presence(doc, company_doc)
    validate_zatca_tax_category_and_exemption_reason(doc, company_doc)
    validate_zatca_zero_rate_categories(doc, company_doc)

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
    validate_advance_payment_invoice_tax_structure(doc)
    validate_zatca_tax_source_presence(doc, company_doc)
    validate_zatca_tax_category_and_exemption_reason(doc, company_doc, enforce_source_consistency=True)
    validate_zatca_zero_rate_categories(doc, company_doc)

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
