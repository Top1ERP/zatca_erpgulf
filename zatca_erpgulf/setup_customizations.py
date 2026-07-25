from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import cint
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


APP_NAME = "zatca_erpgulf"
MODULE_NAME = "Zatca Erpgulf"


PYTHON_MANAGED_COMPANY_ZATCA_FIELDS = {
    ("Company", "custom_zatca_invoice_enabled"),
    ("Company", "custom_select"),
    ("Company", "custom_phase_1_or_2"),
    ("Company", "custom_costcenter"),
    ("Company", "custom_send_einvoice_background"),
    ("Company", "custom_send_invoice_to_zatca"),
    ("Company", "custom_submit_or_not"),
    ("Company", "custom_zatca_background_schedule_section"),
    ("Company", "custom_start_time"),
    ("Company", "custom_start_time_session"),
    ("Company", "custom_zatca_background_schedule_column_break"),
    ("Company", "custom_end_time"),
    ("Company", "custom_end_time_session"),
    ("Company", "custom_zatca_csr_section"),
    ("Company", "custom_create_csr_configuration"),
    ("Company", "custom_csr_config"),
    ("Company", "custom_create_csr"),
    ("Company", "custom_csr_data"),
    ("Company", "custom_zatca_output_attachments_section"),
    ("Company", "custom_attach_xml_with_invoice"),
    ("Company", "custom_zatca_output_attach_column_break_1"),
    ("Company", "custom_attach_xml_with_qr_code"),
    ("Company", "custom_zatca_output_attach_column_break_2"),
    ("Company", "custom_attach_qr_code_doctype"),
    ("Company", "custom_attach_e_invoice_send_status_with_invoice"),
    ("Company", "custom_zatca_pih_section"),
    ("Company", "custom_pih"),
    ("Company", "custom_keys__certificate_for_zatca"),
    ("Company", "custom_private_key"),
    ("Company", "custom_public_key"),
    ("Company", "custom_certificate"),
    ("Company", "custom_urls__api_endpoints"),
    ("Company", "custom_sandbox_url"),
    ("Company", "custom_simulation_url"),
    ("Company", "custom_production_url"),
    ("Company", "custom_compliance_csid_generation"),
    ("Company", "custom_otp"),
    ("Company", "custom_generate_compliance_csid"),
    ("Company", "custom_basic_auth_from_csid"),
    ("Company", "custom_compliance_request_id_"),
    ("Company", "custom_zatca_compliance_check_check_all_options_below"),
    ("Company", "custom_validation_type"),
    ("Company", "custom_sample_invoice_number_to_test"),
    ("Company", "custom_check_compliance"),
    ("Company", "custom_run_all_compliance"),
    ("Company", "custom_production__csid__generation"),
    ("Company", "custom_generate_production_csids"),
    ("Company", "custom_basic_auth_from_production"),
    ("Company", "custom_zatca_advance_payment_section"),
    ("Company", "custom_zatca_advance_payment_enabled"),
    ("Company", "custom_zatca_advance_payment_submission_mode"),
    ("Company", "custom_zatca_advance_default_tc_name"),
    ("Company", "custom_zatca_advance_signing_enabled"),
    ("Company", "custom_zatca_advance_api_submission_enabled"),
    ("Company", "custom_zatca_validation_section"),
    ("Company", "custom_zatca_negative_line_validation_mode"),
    ("Company", "custom_section_break_hwvcd"),
    ("Company", "custom_zatca_offline_machines"),
    ("Company", "custom_submit_line_item_discount_to_zatca"),

    # Customer ZATCA fields are intentionally controlled by Python layout
    # normalizers to avoid fixture/layout churn during after_migrate.
    ("Customer", "customer_name_in_arabic"),
    ("Customer", "custom_customer_name_in_arabic"),
    ("Customer", "zatca_customer_name_in_arabic"),
    ("Customer", "custom_b2c"),
    ("Customer", "custom_buyer_id_type"),
    ("Customer", "custom_buyer_id"),
}


# Do not delete user/manual customizations.
# Only create missing records and update records owned by this app.
UPDATE_EXISTING_APP_CUSTOM_FIELDS = True


# Fields that must exist even if they were not exported to custom_field.json.
# For v16 or future ERPNext versions, if a standard equivalent exists, we do not duplicate it.
CRITICAL_CUSTOM_FIELDS: dict[str, list[dict[str, Any]]] = {
    "Company": [
        {
            "fieldname": "custom_company_name_in_arabic",
            "label": "Company Name In Arabic",
            "fieldtype": "Data",
            "insert_after": "company_name",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "_alternatives": [
                "company_name_in_arabic",
                "custom_company_name_in_arabic",
                "custom__company_name_in_arabic__",
            ],
            "_fallback_insert_after": [
                "company_name",
                "abbr",
                "default_currency",
            ],
        },
        {
            "fieldname": "custom_zatca_validation_section",
            "label": "ZATCA Validation Settings",
            "fieldtype": "Section Break",
            "insert_after": "custom_zatca_advance_api_submission_enabled",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "collapsible": 0,
            "description": "Controls ZATCA validation behavior for this company.",
            "_alternatives": [
                "custom_zatca_validation_section",
            ],
            "_fallback_insert_after": [
                "custom_zatca_advance_api_submission_enabled",
                "custom_zatca_advance_signing_enabled",
                "custom_zatca_advance_payment_section",
                "custom_basic_auth_from_production",
                "custom_zatca_invoice_enabled",
                "company_name",
            ],
        },
        {
            "fieldname": "custom_zatca_negative_line_validation_mode",
            "label": "ZATCA Negative Line Validation Mode",
            "fieldtype": "Select",
            "options": "Strict\nWarn Only\nDisabled",
            "default": "Strict",
            "insert_after": "custom_zatca_validation_section",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "description": (
                "Controls whether ZATCA validation blocks negative item quantities, "
                "prices, and amounts in standard invoices and debit notes. "
                "Returns/credit notes are excluded."
            ),
            "_fallback_insert_after": [
                "custom_zatca_validation_section",
                "custom_zatca_invoice_enabled",
                "custom_costcenter",
                "custom_company_name_in_arabic",
                "company_name",
                "abbr",
                "default_currency",
            ],
        },
        {
            "fieldname": "custom_zatca_advance_payment_section",
            "label": "ZATCA Advance Payment Settings",
            "fieldtype": "Section Break",
            "insert_after": "custom_basic_auth_from_production",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "collapsible": 0,
            "description": "Controls ZATCA advance tax invoice behavior for this company.",
            "_fallback_insert_after": [
                "custom_basic_auth_from_production",
                "custom_generate_production_csids",
                "custom_send_einvoice_background",
                "custom_zatca_invoice_enabled",
                "company_name",
            ],
        },
        {
            "fieldname": "custom_zatca_advance_payment_enabled",
            "label": "ZATCA Advance Payment Enabled",
            "fieldtype": "Check",
            "default": "0",
            "insert_after": "custom_zatca_advance_payment_section",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "description": "Enable ZATCA advance payment tax invoice foundation for this company.",
            "_fallback_insert_after": [
                "custom_zatca_advance_payment_section",
                "custom_zatca_negative_line_validation_mode",
                "custom_zatca_invoice_enabled",
                "company_name",
            ],
        },
        {
            "fieldname": "custom_zatca_advance_payment_submission_mode",
            "label": "ZATCA Advance Payment Submission Mode",
            "fieldtype": "Select",
            "options": "Local Only\nSubmit to ZATCA\nDisabled",
            "default": "Local Only",
            "insert_after": "custom_zatca_advance_payment_enabled",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "depends_on": "eval:doc.custom_zatca_advance_payment_enabled",
            "description": "Controls whether advance payment tax invoices are kept local only, submitted to ZATCA, or disabled for this company.",
            "_fallback_insert_after": [
                "custom_zatca_advance_payment_enabled",
                "custom_zatca_advance_payment_section",
                "custom_zatca_negative_line_validation_mode",
                "custom_zatca_invoice_enabled",
                "company_name",
            ],
        },
        {
            "fieldname": "custom_zatca_advance_default_tc_name",
            "label": "ZATCA Advance Default Terms Template",
            "fieldtype": "Link",
            "options": "Terms and Conditions",
            "insert_after": "custom_zatca_advance_payment_submission_mode",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "depends_on": "eval:doc.custom_zatca_advance_payment_enabled",
            "description": "Default Terms and Conditions template for ZATCA Advance Tax Invoice.",
            "_fallback_insert_after": [
                "custom_zatca_advance_payment_submission_mode",
                "custom_zatca_advance_payment_enabled",
                "custom_zatca_advance_payment_section",
                "custom_zatca_negative_line_validation_mode",
                "custom_zatca_invoice_enabled",
                "company_name",
            ],
        },
        {
            "fieldname": "custom_zatca_advance_signing_enabled",
            "label": "ZATCA Advance Signing Enabled",
            "fieldtype": "Check",
            "default": "0",
            "insert_after": "custom_zatca_advance_default_tc_name",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "depends_on": "eval:doc.custom_zatca_advance_payment_enabled",
            "description": "Advanced technical control. Enable only after advance tax invoice signing is fully tested.",
            "_fallback_insert_after": [
                "custom_zatca_advance_default_tc_name",
                "custom_zatca_advance_payment_submission_mode",
                "custom_zatca_advance_payment_enabled",
                "custom_zatca_advance_payment_section",
                "custom_zatca_negative_line_validation_mode",
                "custom_zatca_invoice_enabled",
                "company_name",
            ],
        },
        {
            "fieldname": "custom_zatca_advance_api_submission_enabled",
            "label": "ZATCA Advance API Submission Enabled",
            "fieldtype": "Check",
            "default": "0",
            "insert_after": "custom_zatca_advance_signing_enabled",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "depends_on": "eval:doc.custom_zatca_advance_payment_enabled",
            "description": "Advanced technical control. Enable only after advance tax invoice API submission is fully tested.",
            "_fallback_insert_after": [
                "custom_zatca_advance_signing_enabled",
                "custom_zatca_advance_default_tc_name",
                "custom_zatca_advance_payment_submission_mode",
                "custom_zatca_advance_payment_enabled",
                "custom_zatca_advance_payment_section",
                "custom_zatca_negative_line_validation_mode",
                "custom_zatca_invoice_enabled",
                "company_name",
            ],
        },
    ],
    "Sales Invoice": [
        {
            "fieldname": "custom_is_advance_credit_note",
            "label": "Is Advance Credit Note",
            "fieldtype": "Check",
            "insert_after": "return_against",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "depends_on": "eval:doc.is_return",
            "description": (
                "Enable this when the credit note cancels or reverses a ZATCA "
                "advance payment invoice."
            ),
            "_alternatives": [
                "custom_is_advance_credit_note",
            ],
            "_fallback_insert_after": [
                "return_against",
                "is_return",
                "remarks",
            ],
        },
        {
            "fieldname": "custom_advance_invoice_reference",
            "label": "Advance Invoice Reference",
            "fieldtype": "Link",
            "options": "ZATCA Advance Tax Invoice",
            "insert_after": "custom_is_advance_credit_note",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "depends_on": "eval:doc.is_return && doc.custom_is_advance_credit_note",
            "mandatory_depends_on": "eval:doc.is_return && doc.custom_is_advance_credit_note",
            "description": (
                "Reference to the original ZATCA advance payment invoice when this "
                "credit note cancels or reverses an advance payment invoice."
            ),
            "_alternatives": [
                "custom_advance_invoice_reference",
            ],
            "_fallback_insert_after": [
                "custom_is_advance_credit_note",
                "return_against",
                "is_return",
                "remarks",
            ],
        },



        {
            "fieldname": "custom_zatca_advance_deduction_section",
            "label": "ZATCA Advance Deductions",
            "fieldtype": "Section Break",
            "insert_after": "advances",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "description": "Automatically summarizes accepted ZATCA advance deductions from ERPNext standard Advance Payments.",
            "_fallback_insert_after": [
                "custom_zatca_full_response",
                "custom_integrations",
                "taxes_and_charges",
                "taxes",
                "items"
            ],
        },
                {
            "fieldname": "custom_zatca_prepaid_amount",
            "label": "ZATCA Prepaid Amount",
            "fieldtype": "Currency",
            "insert_after": "custom_zatca_advance_deduction_section",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "no_copy": 1,
            "description": "Tax-inclusive prepaid amount used for cbc:PrepaidAmount.",
            "_fallback_insert_after": [
                "custom_zatca_advance_deductions",
                "custom_zatca_full_response",
                "taxes_and_charges",
                "taxes"
            ],
        },
        {
            "fieldname": "custom_zatca_advance_deduction_count",
            "label": "ZATCA Advance Deduction Count",
            "fieldtype": "Int",
            "insert_after": "custom_zatca_prepaid_amount",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "no_copy": 1,
            "description": "Number of linked advance tax invoices.",
            "_fallback_insert_after": [
                "custom_zatca_prepaid_amount",
                "custom_zatca_advance_deductions",
                "taxes"
            ],
        },
    ],
    "ZATCA Advance Tax Invoice": [
        {
            "fieldname": "advance_reversal_section",
            "label": "Advance Reversal",
            "fieldtype": "Section Break",
            "insert_after": "total_amount",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "_alternatives": ["advance_reversal_section"],
            "_fallback_insert_after": ["total_amount", "zatca_status", "status"],
        },
        {
            "fieldname": "advance_reversal_status",
            "label": "Advance Reversal Status",
            "fieldtype": "Select",
            "options": "Not Cancelled\nPartially Cancelled\nCancelled",
            "insert_after": "advance_reversal_section",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "default": "Not Cancelled",
            "_alternatives": ["advance_reversal_status"],
            "_fallback_insert_after": ["advance_reversal_section", "total_amount"],
        },
        {
            "fieldname": "credited_amount",
            "label": "Credited Amount",
            "fieldtype": "Currency",
            "insert_after": "advance_reversal_status",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "_alternatives": ["credited_amount"],
            "_fallback_insert_after": ["advance_reversal_status", "total_amount"],
        },
        {
            "fieldname": "remaining_amount",
            "label": "Remaining Amount",
            "fieldtype": "Currency",
            "insert_after": "credited_amount",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "_alternatives": ["remaining_amount"],
            "_fallback_insert_after": ["credited_amount", "total_amount"],
        },
        {
            "fieldname": "advance_credit_note_count",
            "label": "Advance Credit Note Count",
            "fieldtype": "Int",
            "insert_after": "remaining_amount",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "_alternatives": ["advance_credit_note_count"],
            "_fallback_insert_after": ["remaining_amount", "total_amount"],
        },
        {
            "fieldname": "last_advance_credit_note",
            "label": "Last Advance Credit Note",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "insert_after": "advance_credit_note_count",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "_alternatives": ["last_advance_credit_note"],
            "_fallback_insert_after": ["advance_credit_note_count", "total_amount"],
        },
        {
            "fieldname": "last_reversal_update_at",
            "label": "Last Reversal Update At",
            "fieldtype": "Datetime",
            "insert_after": "last_advance_credit_note",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 1,
            "reqd": 0,
            "_alternatives": ["last_reversal_update_at"],
            "_fallback_insert_after": ["last_advance_credit_note", "total_amount"],
        },
    ],

    "Customer": [
        {
            "fieldname": "custom_customer_name_in_arabic",
            "label": "Customer Name Arabic",
            "fieldtype": "Data",
            "insert_after": "customer_name",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "_alternatives": [
                "customer_name_in_arabic",
                "custom_customer_name_in_arabic",
                "zatca_customer_name_in_arabic",
            ],
            "_fallback_insert_after": [
                "customer_name",
                "customer_type",
                "customer_group",
                "territory",
            ],
        }
    ],
}


# If you later add a property_setter.json, this code will sync it.
# You can also define essential property setters here.
CRITICAL_PROPERTY_SETTERS: list[dict[str, Any]] = [
    # Example, only applied if the relevant field exists:
    # {
    #     "doctype": "Property Setter",
    #     "doc_type": "Company",
    #     "field_name": "company_name_in_arabic",
    #     "property": "hidden",
    #     "property_type": "Check",
    #     "value": "0",
    #     "name": "Company-company_name_in_arabic-hidden-zatca_erpgulf",
    # }
]


SAFE_CUSTOM_FIELD_UPDATE_KEYS = {
    "label",
    "description",
    "options",
    "insert_after",
    "depends_on",
    "mandatory_depends_on",
    "read_only_depends_on",
    "collapsible_depends_on",
    "hidden",
    "read_only",
    "reqd",
    "print_hide",
    "report_hide",
    "in_list_view",
    "in_standard_filter",
    "in_preview",
    "bold",
    "no_copy",
    "allow_on_submit",
    "translatable",
    "module",
    "default",
    "precision",
    "width",
    "columns",
}


def _log(message: str) -> None:
    print(f"[zatca_erpgulf.setup_customizations] {message}")


def _get_frappe_major_version() -> int | None:
    version = getattr(frappe, "__version__", "") or ""
    try:
        return int(str(version).split(".")[0])
    except Exception:
        return None


def _get_fixture_path(filename: str) -> Path:
    return Path(frappe.get_app_path(APP_NAME, "fixtures", filename))


def _load_json_fixture(filename: str) -> list[dict[str, Any]]:
    path = _get_fixture_path(filename)

    if not path.exists():
        _log(f"Fixture not found, skipped: {path}")
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        frappe.log_error(
            title=f"ZATCA fixture read failed: {filename}",
            message=frappe.get_traceback(),
        )
        raise

    if not isinstance(data, list):
        raise ValueError(f"Fixture must be a JSON list: {filename}")

    return data


def _doctype_exists(doctype: str) -> bool:
    if not doctype:
        return False

    try:
        return bool(frappe.db.exists("DocType", doctype))
    except Exception:
        return False


def _table_exists(doctype: str) -> bool:
    try:
        return bool(frappe.db.table_exists(doctype))
    except Exception:
        try:
            return bool(frappe.db.sql("show tables like %s", (f"tab{doctype}",)))
        except Exception:
            return False


def _get_meta_fieldnames(doctype: str) -> set[str]:
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return set()

    names = {"doctype", "name"}

    for df in meta.fields:
        if df.fieldname:
            names.add(df.fieldname)

    return names


def _clean_record_for_doctype(doctype: str, row: dict[str, Any]) -> dict[str, Any]:
    """
    Keep only fields supported by the current Frappe version.
    This is important for v15/v16 compatibility.
    """
    allowed = _get_meta_fieldnames(doctype)
    cleaned: dict[str, Any] = {}

    for key, value in row.items():
        if key in allowed:
            cleaned[key] = value

    cleaned["doctype"] = doctype
    return cleaned


def _get_doctype_meta(dt: str):
    try:
        return frappe.get_meta(dt)
    except Exception:
        return None


def _field_exists_in_meta(dt: str, fieldname: str) -> bool:
    if not dt or not fieldname:
        return False

    meta = _get_doctype_meta(dt)

    if not meta:
        return False

    try:
        return bool(meta.get_field(fieldname))
    except Exception:
        return False


def _custom_field_exists(dt: str, fieldname: str, name: str | None = None) -> bool:
    if not dt or not fieldname:
        return False

    try:
        if name and frappe.db.exists("Custom Field", name):
            return True

        return bool(
            frappe.db.exists(
                "Custom Field",
                {
                    "dt": dt,
                    "fieldname": fieldname,
                },
            )
        )
    except Exception:
        return False


def _any_field_exists(dt: str, fieldnames: list[str]) -> bool:
    for fieldname in fieldnames:
        if _field_exists_in_meta(dt, fieldname):
            return True

        if _custom_field_exists(dt, fieldname):
            return True

    return False


def _get_custom_field_name(dt: str, fieldname: str, fixture_name: str | None = None) -> str | None:
    if fixture_name and frappe.db.exists("Custom Field", fixture_name):
        return fixture_name

    return frappe.db.get_value(
        "Custom Field",
        {
            "dt": dt,
            "fieldname": fieldname,
        },
        "name",
    )


def _is_app_owned_custom_field(doc) -> bool:
    module = getattr(doc, "module", None)
    name = getattr(doc, "name", "") or ""

    if module == MODULE_NAME:
        return True

    # Some old records may have empty module but were created with the app naming convention.
    if name and name.startswith(("Company-custom_", "Customer-custom_", "Address-custom_", "Sales Invoice-custom_", "POS Invoice-custom_")):
        return False

    return False


def _field_has_rows(dt: str, fieldname: str) -> bool:
    """
    Detect whether changing fieldtype would be risky.
    This is conservative. We avoid fieldtype change by default anyway.
    """
    if not dt or not fieldname:
        return False

    if not _table_exists(dt):
        return False

    try:
        result = frappe.db.sql(
            f"select count(*) from `tab{dt}` where `{fieldname}` is not null and `{fieldname}` != ''",
            as_list=True,
        )
        return bool(result and result[0] and result[0][0])
    except Exception:
        return False


def _resolve_insert_after(dt: str, requested: str | None, fallback_candidates: list[str] | None = None) -> str | None:
    meta = _get_doctype_meta(dt)

    if not meta:
        return requested

    if requested and meta.get_field(requested):
        return requested

    for candidate in fallback_candidates or []:
        if candidate and meta.get_field(candidate):
            return candidate

    fields = [df.fieldname for df in meta.fields if df.fieldname]

    if fields:
        return fields[-1]

    return requested


def _prepare_custom_field_row(row: dict[str, Any]) -> dict[str, Any]:
    prepared = copy.deepcopy(row)

    dt = prepared.get("dt")
    fieldname = prepared.get("fieldname")

    if not prepared.get("name") and dt and fieldname:
        prepared["name"] = f"{dt}-{fieldname}"

    prepared.setdefault("module", MODULE_NAME)

    fallback_candidates = prepared.pop("_fallback_insert_after", None)

    if dt:
        prepared["insert_after"] = _resolve_insert_after(
            dt,
            prepared.get("insert_after"),
            fallback_candidates,
        )

    prepared.pop("_alternatives", None)

    return _clean_record_for_doctype("Custom Field", prepared)


def _insert_custom_field_from_row(row: dict[str, Any]) -> bool:
    dt = row.get("dt")
    fieldname = row.get("fieldname")
    name = row.get("name") or (f"{dt}-{fieldname}" if dt and fieldname else None)

    if not dt or not fieldname:
        return False

    if not _doctype_exists(dt):
        _log(f"Skipped Custom Field for missing DocType: {dt}.{fieldname}")
        return False

    if _should_skip_duplicate_arabic_name_field_creation(dt, fieldname):
        _log(
            f"Skipped duplicate Arabic-name Custom Field creation because an "
            f"alternative already exists: {dt}.{fieldname}"
        )
        return False

    if _custom_field_exists(dt, fieldname, name):
        return False

    cleaned = _prepare_custom_field_row(row)
    cleaned["dt"] = dt
    cleaned["fieldname"] = fieldname

    if name:
        cleaned["name"] = name

    try:
        doc = frappe.get_doc(cleaned)
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
        frappe.clear_cache(doctype=dt)
        return True
    except Exception:
        frappe.log_error(
            title=f"ZATCA Custom Field insert failed: {dt}.{fieldname}",
            message=frappe.get_traceback(),
        )
        raise


def _update_app_owned_custom_field_from_row(row: dict[str, Any]) -> bool:

    managed_dt = row.get("dt")
    managed_fieldname = row.get("fieldname")

    if (
        (managed_dt, managed_fieldname) in PYTHON_MANAGED_COMPANY_ZATCA_FIELDS
        and frappe.db.exists("Custom Field", {"dt": managed_dt, "fieldname": managed_fieldname})
    ):
        return False
    if not UPDATE_EXISTING_APP_CUSTOM_FIELDS:
        return False

    dt = row.get("dt")
    fieldname = row.get("fieldname")
    name = row.get("name")

    if not dt or not fieldname:
        return False

    existing_name = _get_custom_field_name(dt, fieldname, name)

    if not existing_name:
        return False

    doc = frappe.get_doc("Custom Field", existing_name)

    if not _is_app_owned_custom_field(doc):
        return False

    cleaned = _prepare_custom_field_row(row)

    changed = False

    for key, value in cleaned.items():
        if key in {"doctype", "name", "dt", "fieldname"}:
            continue

        if key == "fieldtype":
            # Fieldtype changes can break existing database data.
            # We do not auto-change it.
            old_fieldtype = getattr(doc, "fieldtype", None)
            if old_fieldtype and value and old_fieldtype != value:
                _log(
                    f"Skipped risky fieldtype change for {dt}.{fieldname}: "
                    f"{old_fieldtype} -> {value}"
                )
            continue

        if key not in SAFE_CUSTOM_FIELD_UPDATE_KEYS:
            continue

        if not doc.meta.has_field(key):
            continue

        if getattr(doc, key, None) != value:
            doc.set(key, value)
            changed = True

    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        frappe.clear_cache(doctype=dt)

    return changed


def sync_custom_fields_from_fixture() -> dict[str, list[str]]:
    """
    Sync custom_field.json in a non-destructive way.
    - Create missing fields.
    - Update app-owned fields only.
    - Never delete user fields.
    - Never overwrite fields owned by another module.
    """
    result = {
        "created": [],
        "updated": [],
        "conflicts": [],
        "skipped": [],
    }

    if not _doctype_exists("Custom Field") or not _table_exists("Custom Field"):
        _log("Custom Field is not available. Skipping custom_field.json.")
        return result

    rows = _load_json_fixture("custom_field.json")

    for row in rows:
        dt = row.get("dt")
        fieldname = row.get("fieldname")
        name = row.get("name") or (f"{dt}-{fieldname}" if dt and fieldname else None)

        if not dt or not fieldname:
            result["skipped"].append(str(row.get("name") or row))
            continue

        if not _doctype_exists(dt):
            result["skipped"].append(f"{dt}.{fieldname} - missing DocType")
            continue

        existing_name = _get_custom_field_name(dt, fieldname, name)

        if existing_name:
            doc = frappe.get_doc("Custom Field", existing_name)

            if _is_app_owned_custom_field(doc):
                if _update_app_owned_custom_field_from_row(row):
                    result["updated"].append(f"{dt}.{fieldname}")
            else:
                result["conflicts"].append(
                    f"{dt}.{fieldname} exists but is not app-owned: {existing_name}"
                )

            continue

        if _insert_custom_field_from_row(row):
            result["created"].append(f"{dt}.{fieldname}")

    return result


def ensure_critical_custom_fields() -> dict[str, list[str]]:
    """
    Ensure fields required by ZATCA logic exist even if omitted from fixtures.
    If a standard/new ERPNext field exists in v16, do not create duplicate custom field.
    """
    result = {
        "created": [],
        "already_available": [],
        "skipped": [],
    }

    fields_to_create: dict[str, list[dict[str, Any]]] = {}

    for dt, field_defs in CRITICAL_CUSTOM_FIELDS.items():
        if not _doctype_exists(dt):
            result["skipped"].append(f"{dt} - missing DocType")
            continue

        for field_def in field_defs:
            field_def_copy = copy.deepcopy(field_def)

            target_fieldname = field_def_copy.get("fieldname")
            alternatives = field_def_copy.pop("_alternatives", [])
            fallback_candidates = field_def_copy.pop("_fallback_insert_after", [])

            if target_fieldname and target_fieldname not in alternatives:
                alternatives = list(alternatives) + [target_fieldname]

            if alternatives and _any_field_exists(dt, alternatives):
                result["already_available"].append(f"{dt}.{target_fieldname}")
                _ensure_alternative_field_visible(dt, alternatives)
                continue

            field_def_copy["insert_after"] = _resolve_insert_after(
                dt,
                field_def_copy.get("insert_after"),
                fallback_candidates,
            )

            fields_to_create.setdefault(dt, []).append(field_def_copy)

    if fields_to_create:
        create_custom_fields(fields_to_create, update=True)

        for dt, defs in fields_to_create.items():
            frappe.clear_cache(doctype=dt)
            for field_def in defs:
                result["created"].append(f"{dt}.{field_def.get('fieldname')}")

    return result


def _ensure_alternative_field_visible(dt: str, alternatives: list[str]) -> None:
    """
    If v16 or a customization already provides a standard/custom Arabic field,
    make sure it is not hidden when safely possible.
    """
    for fieldname in alternatives:
        custom_field_name = _get_custom_field_name(dt, fieldname)

        if custom_field_name:
            doc = frappe.get_doc("Custom Field", custom_field_name)

            if getattr(doc, "hidden", 0):
                doc.hidden = 0
                doc.flags.ignore_permissions = True
                doc.save(ignore_permissions=True)
                frappe.clear_cache(doctype=dt)

            return

        if _field_exists_in_meta(dt, fieldname):
            # Standard field. Use Property Setter only if available.
            if _property_setter_available():
                _upsert_property_setter(
                    {
                        "doctype": "Property Setter",
                        "doc_type": dt,
                        "field_name": fieldname,
                        "property": "hidden",
                        "property_type": "Check",
                        "value": "0",
                        "name": f"{dt}-{fieldname}-hidden-zatca_erpgulf",
                    }
                )
            return


def _property_setter_available() -> bool:
    return _doctype_exists("Property Setter") and _table_exists("Property Setter")


def _property_setter_exists(name: str | None, doc_type: str, field_name: str | None, property_name: str) -> str | None:
    if name and frappe.db.exists("Property Setter", name):
        return name

    filters = {
        "doc_type": doc_type,
        "property": property_name,
    }

    if field_name:
        filters["field_name"] = field_name

    return frappe.db.get_value("Property Setter", filters, "name")


def _apply_property_setter_fallback(row: dict[str, Any]) -> bool:
    """
    Limited fallback for old/changed versions:
    If Property Setter is not available, apply simple properties directly
    only on Custom Field records. Never mutate standard DocField directly.
    """
    doc_type = row.get("doc_type")
    field_name = row.get("field_name")
    property_name = row.get("property")
    value = row.get("value")

    if not doc_type or not field_name or not property_name:
        return False

    allowed_direct_properties = {
        "hidden",
        "read_only",
        "reqd",
        "default",
        "description",
        "depends_on",
        "mandatory_depends_on",
        "read_only_depends_on",
    }

    if property_name not in allowed_direct_properties:
        return False

    custom_field_name = _get_custom_field_name(doc_type, field_name)

    if not custom_field_name:
        return False

    custom_field = frappe.get_doc("Custom Field", custom_field_name)

    if not custom_field.meta.has_field(property_name):
        return False

    if getattr(custom_field, property_name, None) == value:
        return False

    custom_field.set(property_name, value)
    custom_field.flags.ignore_permissions = True
    custom_field.save(ignore_permissions=True)
    frappe.clear_cache(doctype=doc_type)

    return True


def _upsert_property_setter(row: dict[str, Any]) -> bool:
    doc_type = row.get("doc_type")
    field_name = row.get("field_name")
    property_name = row.get("property")
    name = row.get("name")

    if not doc_type or not property_name:
        return False

    if not _doctype_exists(doc_type):
        _log(f"Skipped Property Setter for missing DocType: {doc_type}")
        return False

    if field_name and not _field_exists_in_meta(doc_type, field_name) and not _custom_field_exists(doc_type, field_name):
        _log(f"Skipped Property Setter for missing field: {doc_type}.{field_name}")
        return False

    if not _property_setter_available():
        return _apply_property_setter_fallback(row)

    existing_name = _property_setter_exists(name, doc_type, field_name, property_name)
    cleaned = _clean_record_for_doctype("Property Setter", row)

    cleaned["doctype"] = "Property Setter"
    cleaned["doc_type"] = doc_type
    cleaned["property"] = property_name
    cleaned["doctype_or_field"] = "DocField" if field_name else "DocType"

    if field_name:
        cleaned["field_name"] = field_name

    if name:
        cleaned["name"] = name

    if existing_name:
        doc = frappe.get_doc("Property Setter", existing_name)
        changed = False

        for key, value in cleaned.items():
            if key in {"doctype", "name"}:
                continue

            if doc.meta.has_field(key) and getattr(doc, key, None) != value:
                doc.set(key, value)
                changed = True

        if changed:
            doc.flags.ignore_permissions = True
            doc.save(ignore_permissions=True)
            frappe.clear_cache(doctype=doc_type)

        return changed

    doc = frappe.get_doc(cleaned)
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
    frappe.clear_cache(doctype=doc_type)

    return True


def sync_property_setters_from_fixture() -> dict[str, list[str]]:
    """
    Sync property_setter.json only if it exists.
    This allows new versions of the app to add Property Setters without breaking older sites.
    """
    result = {
        "created_or_updated": [],
        "skipped": [],
    }

    rows = _load_json_fixture("property_setter.json")

    if not rows:
        return result

    for row in rows:
        doc_type = row.get("doc_type")
        field_name = row.get("field_name")
        property_name = row.get("property")

        label = f"{doc_type}.{field_name or ''}.{property_name}"

        try:
            if _upsert_property_setter(row):
                result["created_or_updated"].append(label)
            else:
                result["skipped"].append(label)
        except Exception:
            frappe.log_error(
                title=f"ZATCA Property Setter sync failed: {label}",
                message=frappe.get_traceback(),
            )
            raise

    return result


def ensure_critical_property_setters() -> dict[str, list[str]]:
    result = {
        "created_or_updated": [],
        "skipped": [],
    }

    for row in CRITICAL_PROPERTY_SETTERS:
        doc_type = row.get("doc_type")
        field_name = row.get("field_name")
        property_name = row.get("property")
        label = f"{doc_type}.{field_name or ''}.{property_name}"

        try:
            if _upsert_property_setter(row):
                result["created_or_updated"].append(label)
            else:
                result["skipped"].append(label)
        except Exception:
            frappe.log_error(
                title=f"ZATCA critical Property Setter sync failed: {label}",
                message=frappe.get_traceback(),
            )
            raise

    return result



ARABIC_NAME_FIELD_GROUPS: dict[str, list[str]] = {
    "Company": [
        "company_name_in_arabic",
        "custom_company_name_in_arabic",
        "custom__company_name_in_arabic__",
    ],
    "Customer": [
        "customer_name_in_arabic",
        "custom_customer_name_in_arabic",
        "zatca_customer_name_in_arabic",
    ],
}


ARABIC_NAME_FIELD_LAYOUT: dict[str, dict[str, str]] = {
    "Company": {
        "insert_after": "company_name",
        "label": "Company Name In Arabic",
    },
    "Customer": {
        "insert_after": "customer_name",
        "label": "Customer Name in Arabic",
    },
}


def _get_arabic_name_group_candidates(dt: str, fieldname: str) -> list[str]:
    candidates = ARABIC_NAME_FIELD_GROUPS.get(dt, [])
    return candidates if fieldname in candidates else []


def _should_skip_duplicate_arabic_name_field_creation(dt: str, fieldname: str) -> bool:
    """
    Prevent fixture/critical sync from creating a new Arabic-name field when
    any known alternative already exists on the DocType.
    """
    candidates = _get_arabic_name_group_candidates(dt, fieldname)

    if not candidates:
        return False

    if _field_exists_in_meta(dt, fieldname) or _custom_field_exists(dt, fieldname):
        return False

    return _any_field_exists(dt, candidates)


def _normalize_text_value(value: Any) -> str:
    return str(value or "").strip()


def _existing_fields_from_group(dt: str, candidates: list[str]) -> list[str]:
    return [fieldname for fieldname in candidates if _field_exists_in_meta(dt, fieldname)]


def _get_canonical_arabic_field(dt: str, existing_fields: list[str]) -> str | None:
    """
    Choose the single Arabic-name field that should remain visible.

    Priority:
    - existing non-custom/simple legacy field if present
    - app critical field
    - any existing alternative
    """
    for fieldname in ARABIC_NAME_FIELD_GROUPS.get(dt, []):
        if fieldname in existing_fields:
            return fieldname
    return existing_fields[0] if existing_fields else None


def _get_rows_for_arabic_field_cleanup(dt: str, fields: list[str]) -> list[dict[str, Any]]:
    if not fields:
        return []

    columns = ["name"] + fields
    quoted = ", ".join(f"`{column}`" for column in columns)

    try:
        return frappe.db.sql(f"select {quoted} from `tab{dt}`", as_dict=True)
    except Exception as exc:
        _log(f"Skipped Arabic field data scan for {dt}: {exc}")
        return []


def _set_field_layout(
    dt: str,
    fieldname: str,
    *,
    visible: bool,
    insert_after: str | None = None,
    label: str | None = None,
) -> bool:
    """
    Normalize visibility and placement for both Custom Fields and effective Meta.

    For Custom Field records, update the record directly.
    Also upsert Property Setters to counter old hidden/insert_after overrides.
    """
    changed = False
    hidden_value = 0 if visible else 1
    custom_field_name = _get_custom_field_name(dt, fieldname)

    if custom_field_name:
        doc = frappe.get_doc("Custom Field", custom_field_name)

        if cint(getattr(doc, "hidden", 0)) != hidden_value:
            doc.hidden = hidden_value
            changed = True

        if insert_after and getattr(doc, "insert_after", None) != insert_after:
            doc.insert_after = insert_after
            changed = True

        if label and getattr(doc, "label", None) != label:
            doc.label = label
            changed = True

        if changed:
            doc.flags.ignore_permissions = True
            doc.save(ignore_permissions=True)

    field_available = _field_exists_in_meta(dt, fieldname) or _custom_field_exists(dt, fieldname)

    if field_available and _property_setter_available():
        if _upsert_property_setter(
            {
                "doctype": "Property Setter",
                "doc_type": dt,
                "field_name": fieldname,
                "property": "hidden",
                "property_type": "Check",
                "value": str(hidden_value),
                "name": f"{dt}-{fieldname}-hidden-zatca_erpgulf",
            }
        ):
            changed = True

        if insert_after and _upsert_property_setter(
            {
                "doctype": "Property Setter",
                "doc_type": dt,
                "field_name": fieldname,
                "property": "insert_after",
                "property_type": "Data",
                "value": insert_after,
                "name": f"{dt}-{fieldname}-insert_after-zatca_erpgulf",
            }
        ):
            changed = True

    if changed:
        frappe.clear_cache(doctype=dt)

    return changed


def _set_field_visibility(dt: str, fieldname: str, visible: bool) -> bool:
    return _set_field_layout(dt, fieldname, visible=visible)

def _delete_duplicate_custom_field_if_safe(dt: str, fieldname: str) -> bool:
    """
    Delete duplicate Custom Field only after all values were copied to the canonical field.

    This is intentionally limited to Custom Field records. Standard DocFields are hidden,
    not deleted.
    """
    custom_field_name = _get_custom_field_name(dt, fieldname)

    if not custom_field_name:
        return False

    try:
        frappe.delete_doc(
            "Custom Field",
            custom_field_name,
            ignore_permissions=True,
            force=True,
        )
        frappe.clear_cache(doctype=dt)
        return True
    except Exception as exc:
        _log(f"Could not delete duplicate Arabic field {dt}.{fieldname}: {exc}")
        _set_field_visibility(dt, fieldname, visible=False)
        return False


def cleanup_arabic_name_fields() -> dict[str, Any]:
    """
    Normalize duplicated Arabic-name fields across Company and Customer.

    Policy:
    - Do not create a new Arabic-name field if any known alternative already exists.
    - Copy a non-empty Arabic value to empty duplicate fields.
    - Keep one canonical field visible and immediately after the base name field.
    - If all non-empty duplicate values are identical, delete duplicate Custom Fields.
    - If values conflict, hide duplicate fields and keep the canonical field visible.
    """
    result: dict[str, Any] = {
        "copied_values": [],
        "visible": [],
        "hidden": [],
        "deleted": [],
        "conflicts": [],
        "skipped": [],
    }

    for dt, candidates in ARABIC_NAME_FIELD_GROUPS.items():
        if not _doctype_exists(dt):
            result["skipped"].append(f"{dt} - missing DocType")
            continue

        existing_fields = _existing_fields_from_group(dt, candidates)
        layout = ARABIC_NAME_FIELD_LAYOUT.get(dt, {})

        if len(existing_fields) <= 1:
            if existing_fields:
                if _set_field_layout(
                    dt,
                    existing_fields[0],
                    visible=True,
                    insert_after=layout.get("insert_after"),
                    label=layout.get("label"),
                ):
                    result["visible"].append(f"{dt}.{existing_fields[0]}")
            continue

        canonical = _get_canonical_arabic_field(dt, existing_fields)

        if not canonical:
            result["skipped"].append(f"{dt} - no canonical Arabic field")
            continue

        rows = _get_rows_for_arabic_field_cleanup(dt, existing_fields)
        conflict_found = False

        for row in rows:
            values = {
                fieldname: _normalize_text_value(row.get(fieldname))
                for fieldname in existing_fields
            }
            non_empty_values = [value for value in values.values() if value]
            unique_values = set(non_empty_values)

            if len(unique_values) > 1:
                conflict_found = True
                result["conflicts"].append(f"{dt}.{row.get('name')}")
                chosen_value = values.get(canonical) or non_empty_values[0]
            else:
                chosen_value = non_empty_values[0] if non_empty_values else ""

            if not chosen_value:
                continue

            updates = {}

            for fieldname in existing_fields:
                if not values.get(fieldname):
                    updates[fieldname] = chosen_value

            if updates:
                frappe.db.set_value(dt, row.get("name"), updates, update_modified=False)
                result["copied_values"].append(
                    f"{dt}.{row.get('name')} -> {', '.join(sorted(updates))}"
                )

        if _set_field_layout(
            dt,
            canonical,
            visible=True,
            insert_after=layout.get("insert_after"),
            label=layout.get("label"),
        ):
            result["visible"].append(f"{dt}.{canonical}")

        for fieldname in existing_fields:
            if fieldname == canonical:
                continue

            if conflict_found:
                if _set_field_layout(dt, fieldname, visible=False):
                    result["hidden"].append(f"{dt}.{fieldname}")
            else:
                if _delete_duplicate_custom_field_if_safe(dt, fieldname):
                    result["deleted"].append(f"{dt}.{fieldname}")
                else:
                    if _set_field_layout(dt, fieldname, visible=False):
                        result["hidden"].append(f"{dt}.{fieldname}")

        frappe.clear_cache(doctype=dt)

    return result

def normalize_company_zatca_settings_layout() -> dict[str, list[str]]:
    """
    Normalize Company ZATCA Setting tab layout for old and inconsistent sites.

    This fixes sites where Custom Field idx/insert_after drift caused the
    Advance Payment fields to visually mix with other ZATCA settings.
    """
    result = {
        "updated": [],
        "skipped": [],
    }

    if not _doctype_exists("Company"):
        result["skipped"].append("Company - missing DocType")
        return result

    details_anchor = (
        "custom_details_and_otp"
        if _field_exists_in_meta("Company", "custom_details_and_otp")
        or _custom_field_exists("Company", "custom_details_and_otp")
        else "custom_zatca_setting"
    )

    layout = [
        ("custom_zatca_setting", "dashboard_tab"),
        ("custom_details_and_otp", "custom_zatca_setting"),
        ("custom_zatca_invoice_enabled", details_anchor),
        ("custom_select", "custom_zatca_invoice_enabled"),
        ("custom_phase_1_or_2", "custom_select"),
        ("custom_costcenter", "custom_phase_1_or_2"),
        ("custom_send_einvoice_background", "custom_costcenter"),
        ("custom_send_invoice_to_zatca", "custom_send_einvoice_background"),
        ("custom_submit_or_not", "custom_send_invoice_to_zatca"),
        ("custom_zatca_advance_payment_section", "custom_basic_auth_from_production"),
        ("custom_zatca_advance_payment_enabled", "custom_zatca_advance_payment_section"),
        ("custom_zatca_advance_payment_submission_mode", "custom_zatca_advance_payment_enabled"),
        ("custom_zatca_advance_default_tc_name", "custom_zatca_advance_payment_submission_mode"),
        ("custom_zatca_advance_signing_enabled", "custom_zatca_advance_default_tc_name"),
        ("custom_zatca_advance_api_submission_enabled", "custom_zatca_advance_signing_enabled"),
        ("custom_zatca_validation_section", "custom_zatca_advance_api_submission_enabled"),
        ("custom_zatca_negative_line_validation_mode", "custom_zatca_validation_section"),
    ]

    for fieldname, insert_after in layout:
        if not (_field_exists_in_meta("Company", fieldname) or _custom_field_exists("Company", fieldname)):
            result["skipped"].append(f"Company.{fieldname} - missing field")
            continue

        if _set_field_layout(
            "Company",
            fieldname,
            visible=True,
            insert_after=insert_after,
        ):
            result["updated"].append(f"Company.{fieldname}")

    frappe.clear_cache(doctype="Company")
    return result


def _custom_field_record_name(dt: str, fieldname: str) -> str | None:
    return _get_custom_field_name(dt, fieldname)


def _set_custom_field_idx(dt: str, fieldname: str, idx: int) -> bool:
    custom_field_name = _custom_field_record_name(dt, fieldname)

    if not custom_field_name:
        return False

    current_idx = cint(frappe.db.get_value("Custom Field", custom_field_name, "idx") or 0)

    if current_idx == idx:
        return False

    frappe.db.set_value("Custom Field", custom_field_name, "idx", idx, update_modified=False)
    frappe.clear_cache(doctype=dt)
    return True


def _get_effective_field_idx(dt: str, fieldname: str) -> int:
    meta = _get_doctype_meta(dt)

    if meta:
        df = meta.get_field(fieldname)
        if df:
            return cint(getattr(df, "idx", 0) or 0)

    custom_field_name = _custom_field_record_name(dt, fieldname)

    if custom_field_name:
        return cint(frappe.db.get_value("Custom Field", custom_field_name, "idx") or 0)

    return 0


def _normalize_label(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _find_field_by_label_or_candidates(
    dt: str,
    labels: list[str],
    candidates: list[str] | None = None,
) -> str | None:
    for fieldname in candidates or []:
        if _field_exists_in_meta(dt, fieldname) or _custom_field_exists(dt, fieldname):
            return fieldname

    normalized_labels = {_normalize_label(label) for label in labels}
    meta = _get_doctype_meta(dt)

    if not meta:
        return None

    for df in meta.fields:
        if not getattr(df, "fieldname", None):
            continue

        if _normalize_label(getattr(df, "label", "")) in normalized_labels:
            return df.fieldname

    return None


def _find_tab_break_by_label(dt: str, label: str) -> str | None:
    meta = _get_doctype_meta(dt)

    if not meta:
        return None

    wanted = _normalize_label(label)

    for df in meta.fields:
        if getattr(df, "fieldtype", None) == "Tab Break" and _normalize_label(getattr(df, "label", "")) == wanted:
            return df.fieldname

    return None


def normalize_arabic_name_field_layout() -> dict[str, list[str]]:
    """
    Force the single visible Arabic-name field to stay immediately after
    the base name field on Company and Customer.
    """
    result = {
        "updated": [],
        "skipped": [],
    }

    layout = {
        "Company": {
            "base_field": "company_name",
            "insert_after": "company_name",
            "label": "Company Name In Arabic",
        },
        "Customer": {
            "base_field": "customer_name",
            "insert_after": "customer_name",
            "label": "Customer Name in Arabic",
        },
    }

    for dt, config in layout.items():
        if not _doctype_exists(dt):
            result["skipped"].append(f"{dt} - missing DocType")
            continue

        candidates = ARABIC_NAME_FIELD_GROUPS.get(dt, [])
        existing_fields = _existing_fields_from_group(dt, candidates)

        if not existing_fields:
            result["skipped"].append(f"{dt} - no Arabic name field")
            continue

        canonical = _get_canonical_arabic_field(dt, existing_fields)

        if not canonical:
            result["skipped"].append(f"{dt} - no canonical Arabic field")
            continue

        if _set_field_layout(
            dt,
            canonical,
            visible=True,
            insert_after=config["insert_after"],
            label=config["label"],
        ):
            result["updated"].append(f"{dt}.{canonical}")

        base_idx = _get_effective_field_idx(dt, config["base_field"])

        if base_idx and _set_custom_field_idx(dt, canonical, base_idx + 1):
            result["updated"].append(f"{dt}.{canonical}.idx")

        for fieldname in existing_fields:
            if fieldname == canonical:
                continue

            if _set_field_layout(dt, fieldname, visible=False):
                result["updated"].append(f"{dt}.{fieldname}.hidden")

        frappe.clear_cache(doctype=dt)

    return result


def normalize_customer_zatca_tax_layout() -> dict[str, list[str]]:
    """
    Move Customer ZATCA identification fields to the Tax tab and enforce order.

    Expected order:
    - B2C, if present
    - Customer ID Type for ZATCA
    - Customer ID Number for ZATCA
    """
    result = {
        "updated": [],
        "skipped": [],
    }

    if not _doctype_exists("Customer"):
        result["skipped"].append("Customer - missing DocType")
        return result

    layout_fields = [
        "customer_name_in_arabic",
        "custom_customer_name_in_arabic",
        "zatca_customer_name_in_arabic",
        "custom_b2c",
        "custom_buyer_id_type",
        "custom_buyer_id",
    ]

    # Old idx/insert_after Property Setters can override or confuse effective Meta.
    # For Custom Fields, the Custom Field row itself is the source of truth.
    frappe.db.delete(
        "Property Setter",
        {
            "doc_type": "Customer",
            "field_name": ["in", layout_fields],
            "property": ["in", ["idx", "insert_after"]],
        },
    )

    tax_anchor = (
        _find_tab_break_by_label("Customer", "Tax")
        or _find_field_by_label_or_candidates("Customer", ["Tax"], ["tax_tab"])
        or "tax_id"
    )

    fields_in_order: list[str] = []

    b2c_field = _find_field_by_label_or_candidates(
        "Customer",
        ["B2C"],
        [
            "custom_b2c",
            "b2c",
            "custom_is_b2c",
            "is_b2c",
            "custom_zatca_b2c",
        ],
    )

    id_type_field = _find_field_by_label_or_candidates(
        "Customer",
        ["Customer ID Type for ZATCA"],
        [
            "custom_customer_id_type_for_zatca",
            "customer_id_type_for_zatca",
            "custom_zatca_customer_id_type",
            "zatca_customer_id_type",
        ],
    )

    id_number_field = _find_field_by_label_or_candidates(
        "Customer",
        ["Customer ID Number for ZATCA"],
        [
            "custom_customer_id_number_for_zatca",
            "customer_id_number_for_zatca",
            "custom_zatca_customer_id_number",
            "zatca_customer_id_number",
        ],
    )

    for fieldname in [b2c_field, id_type_field, id_number_field]:
        if fieldname and fieldname not in fields_in_order:
            fields_in_order.append(fieldname)

    if not fields_in_order:
        result["skipped"].append("Customer - no ZATCA tax fields found")
        return result

    previous = tax_anchor
    base_idx = _get_effective_field_idx("Customer", tax_anchor) or 0

    for offset, fieldname in enumerate(fields_in_order, start=1):
        if _set_field_layout(
            "Customer",
            fieldname,
            visible=True,
            insert_after=previous,
        ):
            result["updated"].append(f"Customer.{fieldname}")

        if base_idx and _set_custom_field_idx("Customer", fieldname, base_idx + offset):
            result["updated"].append(f"Customer.{fieldname}.idx")

        previous = fieldname

    frappe.clear_cache(doctype="Customer")
    return result


def normalize_company_zatca_settings_layout_idx() -> dict[str, list[str]]:
    """
    Re-index important Company ZATCA fields so visual order is stable even
    on old sites where many Custom Fields share the same idx.
    """
    result = {
        "updated": [],
        "skipped": [],
    }

    if not _doctype_exists("Company"):
        result["skipped"].append("Company - missing DocType")
        return result

    chain = [
        "custom_zatca_setting",
        "custom_details_and_otp",
        "custom_zatca_invoice_enabled",
        "custom_select",
        "custom_phase_1_or_2",
        "custom_costcenter",
        "custom_send_einvoice_background",
        "custom_send_invoice_to_zatca",
        "custom_submit_or_not",
        "custom_zatca_background_schedule_section",
        "custom_start_time",
        "custom_start_time_session",
        "custom_zatca_background_schedule_column_break",
        "custom_end_time",
        "custom_end_time_session",
        "custom_create_csr_configuration",
        "custom_csr_config",
        "custom_create_csr",
        "custom_csr_data",
        "custom_zatca_output_attachments_section",
        "custom_attach_xml_with_invoice",
        "custom_zatca_output_attach_column_break_1",
        "custom_attach_xml_with_qr_code",
        "custom_zatca_output_attach_column_break_2",
        "custom_attach_qr_code_doctype",
        "custom_attach_e_invoice_send_status_with_invoice",
        "custom_pih",
        "custom_keys__certificate_for_zatca",
        "custom_private_key",
        "custom_public_key",
        "custom_certificate",
        "custom_urls__api_endpoints",
        "custom_sandbox_url",
        "custom_simulation_url",
        "custom_production_url",
        "custom_compliance_csid_generation",
        "custom_otp",
        "custom_generate_compliance_csid",
        "custom_basic_auth_from_csid",
        "custom_compliance_request_id_",
        "custom_zatca_compliance_check_check_all_options_below",
        "custom_validation_type",
        "custom_sample_invoice_number_to_test",
        "custom_check_compliance",
        "custom_run_all_compliance",
        "custom_production__csid__generation",
        "custom_generate_production_csids",
        "custom_basic_auth_from_production",
        "custom_zatca_advance_payment_section",
        "custom_zatca_advance_payment_enabled",
        "custom_zatca_advance_payment_submission_mode",
        "custom_zatca_advance_default_tc_name",
        "custom_zatca_advance_signing_enabled",
        "custom_zatca_advance_api_submission_enabled",
        "custom_zatca_validation_section",
        "custom_zatca_negative_line_validation_mode",
        "custom_section_break_hwvcd",
        "custom_zatca_offline_machines",
        "custom_submit_line_item_discount_to_zatca",
    ]

    existing_chain = [
        fieldname for fieldname in chain
        if _field_exists_in_meta("Company", fieldname) or _custom_field_exists("Company", fieldname)
    ]

    if not existing_chain:
        result["skipped"].append("Company - no ZATCA layout fields found")
        return result

    start_idx = _get_effective_field_idx("Company", existing_chain[0]) or 117

    for offset, fieldname in enumerate(existing_chain):
        if _set_custom_field_idx("Company", fieldname, start_idx + offset):
            result["updated"].append(f"Company.{fieldname}.idx")

    frappe.clear_cache(doctype="Company")
    return result



def _strict_normalize_label(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _strict_customer_meta():
    return _get_doctype_meta("Customer")


def _strict_find_customer_tab(label: str) -> str | None:
    meta = _strict_customer_meta()
    if not meta:
        return None

    wanted = _strict_normalize_label(label)

    for df in meta.fields:
        if (
            getattr(df, "fieldtype", None) == "Tab Break"
            and _strict_normalize_label(getattr(df, "label", "")) == wanted
        ):
            return df.fieldname

    return None


def _strict_find_customer_field_by_label(labels: list[str]) -> str | None:
    meta = _strict_customer_meta()
    if not meta:
        return None

    wanted = {_strict_normalize_label(label) for label in labels}

    for df in meta.fields:
        if not getattr(df, "fieldname", None):
            continue

        if _strict_normalize_label(getattr(df, "label", "")) in wanted:
            return df.fieldname

    return None


def _strict_get_customer_field_idx(fieldname: str) -> int:
    meta = _strict_customer_meta()

    if meta:
        df = meta.get_field(fieldname)
        if df:
            return cint(getattr(df, "idx", 0) or 0)

    custom_field_name = _get_custom_field_name("Customer", fieldname)

    if custom_field_name:
        return cint(frappe.db.get_value("Custom Field", custom_field_name, "idx") or 0)

    return 0


def _strict_set_customer_layout(
    fieldname: str,
    *,
    insert_after: str,
    visible: bool = True,
    label: str | None = None,
    idx: int | None = None,
) -> bool:
    changed = False
    hidden_value = 0 if visible else 1
    custom_field_name = _get_custom_field_name("Customer", fieldname)

    if custom_field_name:
        doc = frappe.get_doc("Custom Field", custom_field_name)

        if cint(getattr(doc, "hidden", 0)) != hidden_value:
            doc.hidden = hidden_value
            changed = True

        if getattr(doc, "insert_after", None) != insert_after:
            doc.insert_after = insert_after
            changed = True

        if label and getattr(doc, "label", None) != label:
            doc.label = label
            changed = True

        if changed:
            doc.flags.ignore_permissions = True
            doc.save(ignore_permissions=True)

        if idx is not None:
            current_idx = cint(frappe.db.get_value("Custom Field", custom_field_name, "idx") or 0)
            if current_idx != idx:
                frappe.db.set_value("Custom Field", custom_field_name, "idx", idx, update_modified=False)
                changed = True

    field_available = _field_exists_in_meta("Customer", fieldname) or _custom_field_exists("Customer", fieldname)

    if field_available and _property_setter_available():
        if _upsert_property_setter(
            {
                "doctype": "Property Setter",
                "doc_type": "Customer",
                "field_name": fieldname,
                "property": "hidden",
                "property_type": "Check",
                "value": str(hidden_value),
                "name": f"Customer-{fieldname}-hidden-zatca_erpgulf",
            }
        ):
            changed = True

        if _upsert_property_setter(
            {
                "doctype": "Property Setter",
                "doc_type": "Customer",
                "field_name": fieldname,
                "property": "insert_after",
                "property_type": "Data",
                "value": insert_after,
                "name": f"Customer-{fieldname}-insert_after-zatca_erpgulf",
            }
        ):
            changed = True

    if changed:
        frappe.clear_cache(doctype="Customer")

    return changed


def normalize_customer_details_and_tax_layout_strict() -> dict[str, list[str]]:
    """
    Strictly enforce Customer layout:

    Details tab:
    - Customer Name
    - Customer Name in Arabic

    Tax tab:
    - B2C
    - Customer ID Type for ZATCA
    - Customer ID Number for ZATCA
    """
    result = {
        "updated": [],
        "skipped": [],
        "found": [],
    }

    if not _doctype_exists("Customer"):
        result["skipped"].append("Customer - missing DocType")
        return result

    # 1) Arabic customer name must be visible directly after customer_name.
    arabic_candidates = ARABIC_NAME_FIELD_GROUPS.get("Customer", [])
    existing_arabic_fields = _existing_fields_from_group("Customer", arabic_candidates)

    if existing_arabic_fields:
        canonical_arabic = _get_canonical_arabic_field("Customer", existing_arabic_fields)
        customer_name_idx = _strict_get_customer_field_idx("customer_name") or 1

        if canonical_arabic:
            result["found"].append(f"Customer Arabic canonical: {canonical_arabic}")

            if _strict_set_customer_layout(
                canonical_arabic,
                insert_after="customer_name",
                visible=True,
                label="Customer Name in Arabic",
                idx=customer_name_idx + 1,
            ):
                result["updated"].append(f"Customer.{canonical_arabic}")

            for fieldname in existing_arabic_fields:
                if fieldname == canonical_arabic:
                    continue

                if _strict_set_customer_layout(
                    fieldname,
                    insert_after=canonical_arabic,
                    visible=False,
                ):
                    result["updated"].append(f"Customer.{fieldname}.hidden")
    else:
        result["skipped"].append("Customer - no Arabic name field")

    # 2) ZATCA identification fields must be under Tax tab.
    tax_tab = _strict_find_customer_tab("Tax")

    if not tax_tab:
        result["skipped"].append("Customer - Tax Tab Break not found")
        return result

    result["found"].append(f"Customer Tax tab: {tax_tab}")

    b2c_field = _strict_find_customer_field_by_label(["B2C"])
    id_type_field = _strict_find_customer_field_by_label(["Customer ID Type for ZATCA"])
    id_number_field = _strict_find_customer_field_by_label(["Customer ID Number for ZATCA"])

    ordered_fields = []
    for fieldname in [b2c_field, id_type_field, id_number_field]:
        if fieldname and fieldname not in ordered_fields:
            ordered_fields.append(fieldname)

    if not ordered_fields:
        result["skipped"].append("Customer - no B2C/ZATCA identification fields found")
        return result

    tax_idx = _strict_get_customer_field_idx(tax_tab) or 1
    previous = tax_tab

    for offset, fieldname in enumerate(ordered_fields, start=1):
        result["found"].append(f"Customer Tax field: {fieldname}")

        if _strict_set_customer_layout(
            fieldname,
            insert_after=previous,
            visible=True,
            idx=tax_idx + offset,
        ):
            result["updated"].append(f"Customer.{fieldname}")

        previous = fieldname

    frappe.clear_cache(doctype="Customer")
    return result



def _force_customer_custom_field_db_values(
    fieldname: str,
    *,
    insert_after: str,
    hidden: int,
    idx: int | None = None,
    label: str | None = None,
) -> bool:
    """
    Update Customer Custom Field through Document.save() so Frappe rebuilds
    the effective DocType meta in the same way Customize Form expects.
    """
    changed = False
    custom_field_name = _get_custom_field_name("Customer", fieldname)

    if not custom_field_name:
        return False

    doc = frappe.get_doc("Custom Field", custom_field_name)

    if getattr(doc, "insert_after", None) != insert_after:
        doc.insert_after = insert_after
        changed = True

    if cint(getattr(doc, "hidden", 0) or 0) != cint(hidden):
        doc.hidden = hidden
        changed = True

    if label and getattr(doc, "label", None) != label:
        doc.label = label
        changed = True

    if idx is not None and cint(getattr(doc, "idx", 0) or 0) != cint(idx):
        doc.idx = idx
        changed = True

    if changed:
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        frappe.clear_cache(doctype="Customer")

    return changed

def _force_customer_property_setters(
    fieldname: str,
    *,
    insert_after: str,
    hidden: int,
    idx: int | None = None,
) -> bool:
    changed = False

    for row in [
        {
            "doctype": "Property Setter",
            "doc_type": "Customer",
            "field_name": fieldname,
            "property": "hidden",
            "property_type": "Check",
            "value": str(hidden),
            "name": f"Customer-{fieldname}-hidden-zatca_erpgulf",
        },
        {
            "doctype": "Property Setter",
            "doc_type": "Customer",
            "field_name": fieldname,
            "property": "insert_after",
            "property_type": "Data",
            "value": insert_after,
            "name": f"Customer-{fieldname}-insert_after-zatca_erpgulf",
        },
    ]:
        if _upsert_property_setter(row):
            changed = True


    if changed:
        frappe.clear_cache(doctype="Customer")

    return changed


def _force_customer_field(
    fieldname: str,
    *,
    insert_after: str,
    hidden: int,
    idx: int | None = None,
    label: str | None = None,
) -> bool:
    changed = False

    if _force_customer_custom_field_db_values(
        fieldname,
        insert_after=insert_after,
        hidden=hidden,
        idx=idx,
        label=label,
    ):
        changed = True

    if _force_customer_property_setters(
        fieldname,
        insert_after=insert_after,
        hidden=hidden,
        idx=idx,
    ):
        changed = True

    return changed


def _customer_meta_idx(fieldname: str) -> int:
    meta = frappe.get_meta("Customer", cached=False)
    df = meta.get_field(fieldname)
    return cint(getattr(df, "idx", 0) or 0) if df else 0


def force_customer_arabic_and_tax_layout() -> dict[str, Any]:
    """
    Force Customer visible layout for old sites where Customize Form still shows
    ZATCA fields inside Details despite insert_after corrections.

    Final order:
    - customer_name
    - Arabic customer name field
    - Tax tab
    - B2C
    - Customer ID Type for ZATCA
    - Customer ID Number for ZATCA
    """
    result: dict[str, Any] = {
        "updated": [],
        "skipped": [],
        "final_meta": [],
        "custom_field_rows": [],
        "property_setters": [],
    }

    if not _doctype_exists("Customer"):
        result["skipped"].append("Customer - missing DocType")
        return result

    arabic_fields = _existing_fields_from_group(
        "Customer",
        ARABIC_NAME_FIELD_GROUPS.get("Customer", []),
    )

    arabic_field = _get_canonical_arabic_field("Customer", arabic_fields) if arabic_fields else None

    if not arabic_field:
        result["skipped"].append("Customer Arabic name field not found")
    else:
        customer_name_idx = _customer_meta_idx("customer_name") or 3

        if _force_customer_field(
            arabic_field,
            insert_after="customer_name",
            hidden=0,
            idx=customer_name_idx + 1,
            label="Customer Name in Arabic",
        ):
            result["updated"].append(f"Customer.{arabic_field}")

        for duplicate_field in arabic_fields:
            if duplicate_field == arabic_field:
                continue

            if _force_customer_field(
                duplicate_field,
                insert_after=arabic_field,
                hidden=1,
            ):
                result["updated"].append(f"Customer.{duplicate_field}.hidden")

    tax_tab = "tax_tab" if _field_exists_in_meta("Customer", "tax_tab") else None

    if not tax_tab:
        meta = frappe.get_meta("Customer", cached=False)
        for df in meta.fields:
            if getattr(df, "fieldtype", None) == "Tab Break" and (df.label or "").strip().lower() == "tax":
                tax_tab = df.fieldname
                break

    if not tax_tab:
        result["skipped"].append("Customer tax_tab not found")
    else:
        tax_idx = _customer_meta_idx(tax_tab) or 50

        ordered_tax_fields = [
            ("custom_b2c", tax_tab, tax_idx + 1),
            ("custom_buyer_id_type", "custom_b2c", tax_idx + 2),
            ("custom_buyer_id", "custom_buyer_id_type", tax_idx + 3),
        ]

        for fieldname, insert_after, idx in ordered_tax_fields:
            if not (_field_exists_in_meta("Customer", fieldname) or _custom_field_exists("Customer", fieldname)):
                result["skipped"].append(f"Customer.{fieldname} not found")
                continue

            if _force_customer_field(
                fieldname,
                insert_after=insert_after,
                hidden=0,
                idx=idx,
            ):
                result["updated"].append(f"Customer.{fieldname}")

    frappe.clear_cache(doctype="Customer")

    meta = frappe.get_meta("Customer", cached=False)

    relevant = {
        "customer_name",
        "customer_name_in_arabic",
        "custom_customer_name_in_arabic",
        "zatca_customer_name_in_arabic",
        "tax_tab",
        "custom_b2c",
        "custom_buyer_id_type",
        "custom_buyer_id",
    }

    for df in meta.fields:
        if df.fieldname in relevant:
            result["final_meta"].append(
                {
                    "idx": cint(getattr(df, "idx", 0) or 0),
                    "fieldtype": df.fieldtype,
                    "fieldname": df.fieldname,
                    "label": df.label,
                    "hidden": cint(getattr(df, "hidden", 0) or 0),
                }
            )

    rows = frappe.db.sql(
        """
        select name, fieldname, label, insert_after, hidden, idx, module
        from `tabCustom Field`
        where dt = 'Customer'
          and fieldname in (
            'customer_name_in_arabic',
            'custom_customer_name_in_arabic',
            'zatca_customer_name_in_arabic',
            'custom_b2c',
            'custom_buyer_id_type',
            'custom_buyer_id'
          )
        order by idx
        """,
        as_dict=True,
    )
    result["custom_field_rows"] = rows

    setters = frappe.db.sql(
        """
        select name, field_name, property, value, doctype_or_field
        from `tabProperty Setter`
        where doc_type = 'Customer'
          and field_name in (
            'customer_name_in_arabic',
            'custom_customer_name_in_arabic',
            'zatca_customer_name_in_arabic',
            'custom_b2c',
            'custom_buyer_id_type',
            'custom_buyer_id'
          )
          and property in ('hidden', 'insert_after', 'idx')
        order by field_name, property
        """,
        as_dict=True,
    )
    result["property_setters"] = setters

    return result



def force_customer_layout_using_customize_form() -> dict[str, Any]:
    """
    Force Customer layout through Frappe Customize Form API.

    This is stronger than updating tabCustom Field directly because the visible
    Customize Form screen may still use the effective customized DocType order.
    """
    result: dict[str, Any] = {
        "updated": [],
        "skipped": [],
        "before": [],
        "after": [],
        "methods": [],
    }

    if not _doctype_exists("Customer"):
        result["skipped"].append("Customer - missing DocType")
        return result

    cf = frappe.get_doc("Customize Form")
    cf.doc_type = "Customer"

    for method_name in ["fetch_to_customize", "load_customization", "get_fields"]:
        if hasattr(cf, method_name):
            result["methods"].append(method_name)

    if hasattr(cf, "fetch_to_customize"):
        cf.fetch_to_customize()
    else:
        result["skipped"].append("Customize Form.fetch_to_customize not available")
        return result

    rows = list(cf.get("fields") or [])

    def snapshot(rows_list):
        output = []
        wanted = {
            "customer_name",
            "customer_name_in_arabic",
            "custom_customer_name_in_arabic",
            "zatca_customer_name_in_arabic",
            "tax_tab",
            "custom_b2c",
            "custom_buyer_id_type",
            "custom_buyer_id",
        }

        for row in rows_list:
            if row.fieldname in wanted:
                output.append(
                    {
                        "idx": row.idx,
                        "fieldtype": row.fieldtype,
                        "fieldname": row.fieldname,
                        "label": row.label,
                        "hidden": cint(row.hidden or 0),
                        "insert_after": getattr(row, "insert_after", None),
                    }
                )

        return output

    result["before"] = snapshot(rows)

    by_field = {row.fieldname: row for row in rows if row.fieldname}

    arabic_candidates = [
        "customer_name_in_arabic",
        "custom_customer_name_in_arabic",
        "zatca_customer_name_in_arabic",
    ]

    arabic_field = next((fieldname for fieldname in arabic_candidates if fieldname in by_field), None)

    required_fields = [
        fieldname
        for fieldname in [
            "customer_name",
            arabic_field,
            "tax_tab",
            "custom_b2c",
            "custom_buyer_id_type",
            "custom_buyer_id",
        ]
        if fieldname
    ]

    missing = [fieldname for fieldname in required_fields if fieldname not in by_field]

    if missing:
        result["skipped"].append(f"Missing fields: {missing}")
        return result

    def move_after(fieldname: str, anchor: str) -> None:
        nonlocal rows

        row = by_field.get(fieldname)
        anchor_row = by_field.get(anchor)

        if not row or not anchor_row:
            result["skipped"].append(f"Cannot move {fieldname} after {anchor}")
            return

        rows = [item for item in rows if item.fieldname != fieldname]

        anchor_index = next(
            index for index, item in enumerate(rows)
            if item.fieldname == anchor
        )

        rows.insert(anchor_index + 1, row)
        result["updated"].append(f"{fieldname} after {anchor}")

    # Details tab order
    if arabic_field:
        by_field[arabic_field].hidden = 0
        by_field[arabic_field].label = "Customer Name in Arabic"
        move_after(arabic_field, "customer_name")

    # Tax tab order
    by_field["custom_b2c"].hidden = 0
    by_field["custom_buyer_id_type"].hidden = 0
    by_field["custom_buyer_id"].hidden = 0

    move_after("custom_b2c", "tax_tab")
    move_after("custom_buyer_id_type", "custom_b2c")
    move_after("custom_buyer_id", "custom_buyer_id_type")

    # Rebuild child table order for Customize Form.
    clean_rows = []

    for index, row in enumerate(rows, start=1):
        row.idx = index
        d = row.as_dict()

        for key in [
            "name",
            "owner",
            "creation",
            "modified",
            "modified_by",
            "parent",
            "parenttype",
            "parentfield",
            "doctype",
        ]:
            d.pop(key, None)

        d["idx"] = index
        clean_rows.append(d)

    cf.set("fields", [])

    for d in clean_rows:
        cf.append("fields", d)

    if hasattr(cf, "save_customization"):
        cf.save_customization()
    else:
        result["skipped"].append("Customize Form.save_customization not available")
        return result


    frappe.db.commit()
    frappe.clear_cache(doctype="Customer")

    cf2 = frappe.get_doc("Customize Form")
    cf2.doc_type = "Customer"
    cf2.fetch_to_customize()

    result["after"] = snapshot(list(cf2.get("fields") or []))

    return result






def sync_company_zatca_fields_and_layout() -> dict[str, list[str]]:
    """
    Canonical sync for Company > ZATCA Setting fields and layout. This is the single source of truth for Company ZATCA UI.
    """
    result = {
        "created": [],
        "updated": [],
        "property_setters": [],
        "skipped": [],
    }

    if not _doctype_exists("Company"):
        result["skipped"].append("Company - missing DocType")
        return result

    def _normalized(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def upsert_property_setter(fieldname: str, property_name: str, value: Any, property_type: str = "Data") -> None:
        ps_name = f"Company-{fieldname}-{property_name}"
        desired_value = _normalized(value)

        if frappe.db.exists("Property Setter", ps_name):
            ps = frappe.get_doc("Property Setter", ps_name)
            created = False
        else:
            ps = frappe.new_doc("Property Setter")
            ps.name = ps_name
            created = True

        desired = {
            "doc_type": "Company",
            "doctype_or_field": "DocField",
            "field_name": fieldname,
            "property": property_name,
            "property_type": property_type,
            "value": desired_value,
        }

        changed = created

        for key, expected in desired.items():
            if _normalized(getattr(ps, key, None)) != _normalized(expected):
                setattr(ps, key, expected)
                changed = True

        if changed:
            ps.flags.ignore_permissions = True
            ps.save(ignore_permissions=True)
            result["property_setters"].append(ps_name)

    def ensure_or_update_custom_field(field: dict[str, Any]) -> None:
        fieldname = field["fieldname"]
        existing = _get_custom_field_name("Company", fieldname)

        if existing:
            doc = frappe.get_doc("Custom Field", existing)
            created = False
        else:
            doc = frappe.new_doc("Custom Field")
            doc.dt = "Company"
            doc.fieldname = fieldname
            doc.module = MODULE_NAME
            created = True

        changed = False

        for key, value in field.items():
            if key in {"fieldname", "create_if_missing"}:
                continue

            if getattr(doc, key, None) != value:
                setattr(doc, key, value)
                changed = True

        if created or changed:
            doc.flags.ignore_permissions = True
            doc.save(ignore_permissions=True)

            if created:
                result["created"].append(f"Company.{fieldname}")
            else:
                result["updated"].append(f"Company.{fieldname}")

        for key in [
            "label",
            "description",
            "insert_after",
            "depends_on",
            "collapsible",
            "hidden",
            "default",
            "fieldtype",
        ]:
            if key in field:
                property_type = "Check" if key in {"collapsible", "hidden"} else "Data"
                upsert_property_setter(fieldname, key, field.get(key), property_type)

    fields = [
        # Background section: visible only when Background mode is selected.
        {
            "fieldname": "custom_zatca_background_schedule_section",
            "label": "Background Submission Schedule",
            "fieldtype": "Section Break",
            "insert_after": "custom_submit_or_not",
            "module": MODULE_NAME,
            "hidden": 0,
            "collapsible": 1,
            "depends_on": "eval:doc.custom_send_invoice_to_zatca == 'Background'",
            "description": "Used only when B2C/POS Submission Method is set to Background.",
        },
        {
            "fieldname": "custom_start_time",
            "label": "Background Start Time",
            "insert_after": "custom_zatca_background_schedule_section",
            "depends_on": "eval:doc.custom_send_invoice_to_zatca == 'Background'",
            "description": "Start of the first allowed background-submission window.",
        },
        {
            "fieldname": "custom_start_time_session",
            "label": "Background Start Time - Session 2",
            "insert_after": "custom_start_time",
            "depends_on": "eval:doc.custom_send_invoice_to_zatca == 'Background'",
            "description": "Start of the second allowed background-submission window.",
        },
        {
            "fieldname": "custom_zatca_background_schedule_column_break",
            "label": "",
            "fieldtype": "Column Break",
            "insert_after": "custom_start_time_session",
            "module": MODULE_NAME,
            "hidden": 0,
            "depends_on": "eval:doc.custom_send_invoice_to_zatca == 'Background'",
            "description": "",
        },
        {
            "fieldname": "custom_end_time",
            "label": "Background End Time",
            "insert_after": "custom_zatca_background_schedule_column_break",
            "depends_on": "eval:doc.custom_send_invoice_to_zatca == 'Background'",
            "description": "End of the first allowed background-submission window.",
        },
        {
            "fieldname": "custom_end_time_session",
            "label": "Background End Time - Session 2",
            "insert_after": "custom_end_time",
            "depends_on": "eval:doc.custom_send_invoice_to_zatca == 'Background'",
            "description": "End of the second allowed background-submission window.",
        },

        # CSR section: always visible and not inside Background.
        {
            "fieldname": "custom_zatca_csr_section",
            "label": "CSR Configuration and Data",
            "fieldtype": "Section Break",
            "insert_after": "custom_end_time_session",
            "module": MODULE_NAME,
            "hidden": 0,
            "collapsible": 0,
            "depends_on": "",
            "description": "",
        },
        {
            "fieldname": "custom_create_csr_configuration",
            "insert_after": "custom_zatca_csr_section",
            "depends_on": "",
        },
        {
            "fieldname": "custom_csr_config",
            "insert_after": "custom_create_csr_configuration",
            "depends_on": "",
        },
        {
            "fieldname": "custom_create_csr",
            "insert_after": "custom_csr_config",
            "depends_on": "",
        },
        {
            "fieldname": "custom_csr_data",
            "insert_after": "custom_create_csr",
            "depends_on": "",
        },

        # Attachments: no descriptions.
        {
            "fieldname": "custom_zatca_output_attachments_section",
            "label": "Optional / Legacy Output Attachments",
            "fieldtype": "Section Break",
            "insert_after": "custom_csr_data",
            "module": MODULE_NAME,
            "hidden": 0,
            "collapsible": 1,
            "description": "",
        },
        {
            "fieldname": "custom_attach_xml_with_invoice",
            "insert_after": "custom_zatca_output_attachments_section",
            "description": "",
        },
        {
            "fieldname": "custom_zatca_output_attach_column_break_1",
            "label": "",
            "fieldtype": "Column Break",
            "insert_after": "custom_attach_xml_with_invoice",
            "module": MODULE_NAME,
            "hidden": 0,
            "description": "",
        },
        {
            "fieldname": "custom_attach_xml_with_qr_code",
            "insert_after": "custom_zatca_output_attach_column_break_1",
            "description": "",
        },
        {
            "fieldname": "custom_zatca_output_attach_column_break_2",
            "label": "",
            "fieldtype": "Column Break",
            "insert_after": "custom_attach_xml_with_qr_code",
            "module": MODULE_NAME,
            "hidden": 0,
            "description": "",
        },
        {
            "fieldname": "custom_attach_qr_code_doctype",
            "insert_after": "custom_zatca_output_attach_column_break_2",
            "description": "",
        },
        {
            "fieldname": "custom_attach_e_invoice_send_status_with_invoice",
            "insert_after": "custom_attach_qr_code_doctype",
            "description": "",
        },

        # PIH: full-width own section.
        {
            "fieldname": "custom_zatca_pih_section",
            "label": "ZATCA Chain State",
            "fieldtype": "Section Break",
            "insert_after": "custom_attach_e_invoice_send_status_with_invoice",
            "module": MODULE_NAME,
            "hidden": 0,
            "collapsible": 0,
            "description": "",
        },
        {
            "fieldname": "custom_pih",
            "label": "Previous Invoice Hash (PIH)",
            "insert_after": "custom_zatca_pih_section",
        },

        # Create if missing because runtime code reads it on some flows.
        {
            "fieldname": "custom_submit_line_item_discount_to_zatca",
            "label": "Submit POS Line Item Discount to ZATCA",
            "fieldtype": "Check",
            "insert_after": "custom_zatca_offline_machines",
            "module": MODULE_NAME,
            "hidden": 0,
            "default": "0",
            "description": "Controls whether POS line item discount details are submitted in the ZATCA XML.",
            "create_if_missing": True,
        },
    ]

    for field in fields:
        fieldname = field["fieldname"]

        if field.get("fieldtype") in {"Section Break", "Column Break"} or field.get("create_if_missing"):
            ensure_or_update_custom_field(field)
            continue

        if not _get_custom_field_name("Company", fieldname):
            result["skipped"].append(f"Company.{fieldname} - missing field")
            continue

        ensure_or_update_custom_field(field)

    # Force final visual order through Customize Form.
    final_order = [
        "custom_zatca_setting",
        "custom_details_and_otp",
        "custom_zatca_invoice_enabled",
        "custom_select",
        "custom_phase_1_or_2",
        "custom_costcenter",
        "custom_send_einvoice_background",
        "custom_send_invoice_to_zatca",
        "custom_submit_or_not",

        "custom_zatca_background_schedule_section",
        "custom_start_time",
        "custom_start_time_session",
        "custom_zatca_background_schedule_column_break",
        "custom_end_time",
        "custom_end_time_session",

        "custom_zatca_csr_section",
        "custom_create_csr_configuration",
        "custom_csr_config",
        "custom_create_csr",
        "custom_csr_data",

        "custom_zatca_output_attachments_section",
        "custom_attach_xml_with_invoice",
        "custom_zatca_output_attach_column_break_1",
        "custom_attach_xml_with_qr_code",
        "custom_zatca_output_attach_column_break_2",
        "custom_attach_qr_code_doctype",
        "custom_attach_e_invoice_send_status_with_invoice",

        "custom_zatca_pih_section",
        "custom_pih",

        "custom_keys__certificate_for_zatca",
        "custom_private_key",
        "custom_public_key",
        "custom_certificate",
        "custom_urls__api_endpoints",
        "custom_sandbox_url",
        "custom_simulation_url",
        "custom_production_url",
        "custom_compliance_csid_generation",
        "custom_otp",
        "custom_generate_compliance_csid",
        "custom_basic_auth_from_csid",
        "custom_compliance_request_id_",
        "custom_zatca_compliance_check_check_all_options_below",
        "custom_validation_type",
        "custom_sample_invoice_number_to_test",
        "custom_check_compliance",
        "custom_run_all_compliance",
        "custom_production__csid__generation",
        "custom_generate_production_csids",
        "custom_basic_auth_from_production",
        "custom_zatca_advance_payment_section",
        "custom_zatca_advance_payment_enabled",
        "custom_zatca_advance_payment_submission_mode",
        "custom_zatca_advance_default_tc_name",
        "custom_zatca_advance_signing_enabled",
        "custom_zatca_advance_api_submission_enabled",
        "custom_zatca_validation_section",
        "custom_zatca_negative_line_validation_mode",
        "custom_section_break_hwvcd",
        "custom_zatca_offline_machines",
        "custom_submit_line_item_discount_to_zatca",
    ]

    cf = frappe.get_doc("Customize Form")
    cf.doc_type = "Company"
    cf.fetch_to_customize()

    rows = list(cf.get("fields") or [])
    by_fieldname = {
        row.fieldname: row
        for row in rows
        if getattr(row, "fieldname", None)
    }

    expected_order = [fieldname for fieldname in final_order if fieldname in by_fieldname]
    current_order = [
        row.fieldname
        for row in rows
        if getattr(row, "fieldname", None) in set(expected_order)
    ]

    def move_after(fieldname: str, anchor: str) -> None:
        if fieldname not in by_fieldname or anchor not in by_fieldname:
            return

        row = by_fieldname[fieldname]
        anchor_row = by_fieldname[anchor]

        if row in rows:
            rows.remove(row)

        anchor_index = rows.index(anchor_row)
        rows.insert(anchor_index + 1, row)
        row.insert_after = anchor

    previous = None

    for fieldname in final_order:
        if fieldname not in by_fieldname:
            continue

        if previous:
            move_after(fieldname, previous)

        previous = fieldname

    final_current_order = [
        row.fieldname
        for row in rows
        if getattr(row, "fieldname", None) in set(expected_order)
    ]

    needs_customize_save = current_order != expected_order or final_current_order != expected_order

    if needs_customize_save:
        clean_rows = []

        for index, row in enumerate(rows, start=1):
            row.idx = index
            d = row.as_dict()

            for key in [
                "name",
                "owner",
                "creation",
                "modified",
                "modified_by",
                "parent",
                "parenttype",
                "parentfield",
                "doctype",
            ]:
                d.pop(key, None)

            d["idx"] = index
            clean_rows.append(d)

        cf.set("fields", [])

        for d in clean_rows:
            cf.append("fields", d)

        if hasattr(cf, "save_customization"):
            cf.save_customization()
            result["updated"].append("Company.effective_customize_form_order")
        else:
            result["skipped"].append("Company Customize Form.save_customization not available")

    frappe.db.commit()
    frappe.clear_cache(doctype="Company")
    return result



def run_zatca_customization_sync_after_migrate() -> None:
    """
    Run ZATCA customization sync after app/site migration.

    This keeps existing customer sites aligned after app updates without requiring
    a manual bench execute command.
    """
    try:
        _log("Running ZATCA customization sync from after_migrate hook.")
        sync_all_zatca_customizations()
        _log("ZATCA customization sync from after_migrate hook completed.")
    except Exception:
        # Do not block the entire site migration because of a UI/customization sync issue.
        # The exception is logged for administrator review.
        frappe.log_error(
            title="ZATCA after_migrate customization sync failed",
            message=frappe.get_traceback(),
        )
        _log("ZATCA customization sync from after_migrate hook failed. See Error Log.")

def sync_all_zatca_customizations() -> dict[str, Any]:
    """
    Main idempotent sync function.

    Safe to run:
    - after install
    - after fixture sync
    - after migrate
    - manually via bench execute

    It never deletes customizations.
    It does not overwrite non-app-owned custom fields.
    """
    frappe_major = _get_frappe_major_version()

    _log("Starting ZATCA customization sync.")
    _log(f"Frappe major version detected: {frappe_major}")

    custom_fields_result = sync_custom_fields_from_fixture()
    critical_fields_result = ensure_critical_custom_fields()
    arabic_name_cleanup_result = cleanup_arabic_name_fields()
    arabic_name_layout_result = normalize_arabic_name_field_layout()
    force_customer_layout_result = force_customer_arabic_and_tax_layout()
    customer_zatca_tax_layout_result = {
        "updated": [],
        "skipped": ["superseded by force_customer_arabic_and_tax_layout"],
    }
    customer_details_tax_strict_layout_result = {
        "updated": [],
        "skipped": ["superseded by force_customer_arabic_and_tax_layout"],
        "found": [],
    }
    property_setters_result = sync_property_setters_from_fixture()
    critical_property_setters_result = ensure_critical_property_setters()
    company_zatca_ui_result = sync_company_zatca_fields_and_layout()
    customer_customize_form_layout_result = {
        "updated": [],
        "skipped": ["superseded by force_customer_arabic_and_tax_layout"],
        "before": [],
        "after": [],
        "methods": [],
    }

    frappe.db.commit()

    result = {
        "frappe_major": frappe_major,
        "custom_fields": custom_fields_result,
        "critical_custom_fields": critical_fields_result,
        "arabic_name_cleanup": arabic_name_cleanup_result,
        "arabic_name_layout": arabic_name_layout_result,
        "customer_zatca_tax_layout": customer_zatca_tax_layout_result,
        "customer_details_tax_strict_layout": customer_details_tax_strict_layout_result,
        "force_customer_layout": force_customer_layout_result,
        "property_setters": property_setters_result,
        "critical_property_setters": critical_property_setters_result,
        "company_zatca_ui": company_zatca_ui_result,
        "customer_customize_form_layout": customer_customize_form_layout_result,
    }

    _print_result_summary(result)
    _log("ZATCA customization sync completed.")

    return result


def _print_result_summary(result: dict[str, Any]) -> None:
    print("=" * 120)
    print("ZATCA Customization Sync Summary")
    print("=" * 120)

    for section, data in result.items():
        if not isinstance(data, dict):
            print(f"{section}: {data}")
            continue

        print(f"\n[{section}]")

        for key, values in data.items():
            if isinstance(values, list):
                print(f"{key}: {len(values)}")
                for value in values:
                    print(f"  - {value}")
            else:
                print(f"{key}: {values}")

    print("=" * 120)


def report_zatca_customization_status() -> dict[str, Any]:
    """
    Diagnostic only. Does not change data.
    """
    result: dict[str, Any] = {
        "frappe_major": _get_frappe_major_version(),
        "custom_field_fixture": {
            "present": [],
            "missing": [],
            "conflicts": [],
            "skipped": [],
        },
        "critical_custom_fields": {
            "available": [],
            "missing": [],
        },
        "property_setter_fixture_found": False,
    }

    rows = _load_json_fixture("custom_field.json")

    for row in rows:
        dt = row.get("dt")
        fieldname = row.get("fieldname")
        name = row.get("name") or (f"{dt}-{fieldname}" if dt and fieldname else None)

        if not dt or not fieldname:
            result["custom_field_fixture"]["skipped"].append(str(row.get("name") or row))
            continue

        existing_name = _get_custom_field_name(dt, fieldname, name)

        if existing_name:
            doc = frappe.get_doc("Custom Field", existing_name)

            if _is_app_owned_custom_field(doc):
                result["custom_field_fixture"]["present"].append(f"{dt}.{fieldname}")
            else:
                result["custom_field_fixture"]["conflicts"].append(
                    f"{dt}.{fieldname} exists but is not app-owned: {existing_name}"
                )
        else:
            result["custom_field_fixture"]["missing"].append(f"{dt}.{fieldname}")

    for dt, field_defs in CRITICAL_CUSTOM_FIELDS.items():
        for field_def in field_defs:
            fieldname = field_def.get("fieldname")
            alternatives = field_def.get("_alternatives", [fieldname])

            if _any_field_exists(dt, alternatives):
                result["critical_custom_fields"]["available"].append(
                    f"{dt}.{fieldname} via alternatives={alternatives}"
                )
            else:
                result["critical_custom_fields"]["missing"].append(
                    f"{dt}.{fieldname} via alternatives={alternatives}"
                )

    property_setter_path = _get_fixture_path("property_setter.json")
    result["property_setter_fixture_found"] = property_setter_path.exists()

    _print_result_summary(
        {
            "frappe_major": result["frappe_major"],
            "custom_field_fixture": result["custom_field_fixture"],
            "critical_custom_fields": result["critical_custom_fields"],
            "property_setter_fixture_found": {
                "exists": result["property_setter_fixture_found"],
            },
        }
    )

    return result


def after_install() -> None:
    sync_all_zatca_customizations()


def after_sync() -> None:
    sync_all_zatca_customizations()


def after_migrate() -> None:
    sync_all_zatca_customizations()
