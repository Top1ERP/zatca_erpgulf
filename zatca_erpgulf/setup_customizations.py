from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import cint, flt
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


APP_NAME = "zatca_erpgulf"
MODULE_NAME = "Zatca Erpgulf"
ADVANCE_PAYMENT_ITEM_CODE = "Advance Payment"


SALES_INVOICE_PRINT_HEADING_TEMPLATE = r"""<h1 style="text-align: center !important">
    {% set b2c = frappe.db.get_value("Customer", doc.customer, "custom_b2c") or 0 %}
    {% set is_return = doc.is_return|int %}
    {% set is_debit_note = doc.is_debit_note|int %}
    {% set is_advance_payment = doc.is_advance_payment|int %}
    {% if is_return == 1 %}
        <div>فاتورة ضريبية - إشعار دائن</div>
        <small class="sub-heading">Credit Note</small>
    {% elif is_debit_note == 1 %}
        <div>فاتورة ضريبية - إشعار مدين</div>
        <small class="sub-heading">Debit Note</small>
    {% elif is_advance_payment == 1 and b2c|int == 1 %}
        <div>فاتورة ضريبية مبسطة للدفعة المقدمة</div>
        <small class="sub-heading">Simplified Advance Payment Tax Invoice</small>
    {% elif is_advance_payment == 1 %}
        <div>فاتورة ضريبية للدفعة المقدمة</div>
        <small class="sub-heading">Advance Payment Tax Invoice</small>
    {% elif b2c|int == 1 %}
        <div>فاتورة ضريبية مبسطة</div>
        <small class="sub-heading">Simplified Tax Invoice</small>
    {% else %}
        <div>فاتورة ضريبية</div>
        <small class="sub-heading">Tax Invoice</small>
    {% endif %}
</h1>"""


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
    ("Company", "custom_zatca_validation_section"),
    ("Company", "custom_zatca_negative_line_validation_mode"),
    ("Company", "custom_section_break_hwvcd"),
    ("Company", "custom_zatca_offline_machines"),
    ("Company", "custom_submit_line_item_discount_to_zatca"),
    ("Company", "custom_enforce_zatca_tax_category_rate_validation"),
    ("Company", "custom_enforce_zatca_payment_entry_amount_limit"),

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
            "insert_after": "custom_basic_auth_from_production",
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
    ],
    "Sales Invoice": [
        {
            "fieldname": "abbr",
            "label": "Company Abbreviation",
            "fieldtype": "Data",
            "insert_after": "company",
            "fetch_from": "company.abbr",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 1,
            "reqd": 0,
            "no_copy": 1,
            # Preserve an exact existing field's customer-owned configuration.
            "_alternatives": ["abbr"],
            "_preserve_existing": True,
        },
        {
            "fieldname": "is_advance_payment",
            "label": "Is Advance Payment Invoice",
            "fieldtype": "Check",
            "insert_after": "is_debit_note",
            "default": "0",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "description": (
                "Use this only for the initial advance payment invoice, "
                "not for the final invoice."
            ),
            "_alternatives": [
                "is_advance_payment",
                "custom_is_advance_payment",
            ],
            "_fallback_insert_after": [
                "is_debit_note",
                "is_return",
                "customer",
            ],
        },
        {
            "fieldname": "custom_zatca_payment_entry",
            "label": "ZATCA Payment Entry",
            "fieldtype": "Link",
            "options": "Payment Entry",
            "insert_after": "is_advance_payment",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "allow_on_submit": 1,
            "no_copy": 1,
            "depends_on": (
                "eval:doc.is_advance_payment || doc.custom_is_advance_payment"
            ),
            "description": (
                "Optional submitted Receive Payment Entry used to create or link "
                "this advance payment Sales Invoice."
            ),
            "_alternatives": [
                "custom_zatca_payment_entry",
            ],
            "_fallback_insert_after": [
                "is_advance_payment",
                "custom_is_advance_payment",
                "customer",
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
            "description": "Allocate submitted advance payment Sales Invoices directly in the final invoice.",
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
            "fieldname": "custom_zatca_advance_deduction_summary_column_break",
            "label": "",
            "fieldtype": "Column Break",
            "insert_after": "custom_zatca_prepaid_amount",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_zatca_advance_deduction_totals_column_break",
            "label": "",
            "fieldtype": "Column Break",
            "insert_after": "custom_zatca_advance_deducted_taxable_amount",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 1,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_section_break_qhp4f",
            "label": "ZATCA Advance Deduction Table",
            "fieldtype": "Section Break",
            "insert_after": "custom_zatca_advance_deduction_count",
            "module": MODULE_NAME,
            "translatable": 0,
            "hidden": 0,
            "read_only": 0,
            "reqd": 0,
            "no_copy": 1,
            "collapsible": 1,
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
            "description": "Number of linked advance-payment Sales Invoices.",
            "_fallback_insert_after": [
                "custom_zatca_prepaid_amount",
                "custom_zatca_advance_deductions",
                "taxes"
            ],
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
            preserve_existing = field_def_copy.pop("_preserve_existing", False)
            fallback_candidates = field_def_copy.pop("_fallback_insert_after", [])

            if target_fieldname and target_fieldname not in alternatives:
                alternatives = list(alternatives) + [target_fieldname]

            if alternatives and _any_field_exists(dt, alternatives):
                result["already_available"].append(f"{dt}.{target_fieldname}")
                if not preserve_existing:
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
        ("custom_zatca_validation_section", "custom_basic_auth_from_production"),
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




def sync_zatca_arabic_translations() -> dict[str, list[str]]:
    """Sync Arabic ZATCA translations to Translation DocType for existing sites."""
    result = {
        "created": [],
        "updated": [],
        "skipped": [],
    }

    if not _doctype_exists("Translation"):
        result["skipped"].append("Translation DocType not available")
        return result

    try:
        from pathlib import Path
        import csv

        translations_file = Path(
            frappe.get_app_path("zatca_erpgulf", "translations", "ar.csv")
        )
    except Exception as exc:
        result["skipped"].append(f"translation path resolution failed: {exc}")
        return result

    if not translations_file.exists():
        result["skipped"].append(f"missing file: {translations_file}")
        return result

    meta = frappe.get_meta("Translation")
    fieldnames = {df.fieldname for df in meta.fields}

    required_fields = {"language", "source_text", "translated_text"}
    if not required_fields.issubset(fieldnames):
        result["skipped"].append("Translation DocType schema is not compatible")
        return result

    with translations_file.open("r", encoding="utf-8", newline="") as f:
        rows = [row for row in csv.reader(f) if len(row) >= 2 and row[0] and row[1]]

    for source_text, translated_text, *_ in rows:
        filters = {
            "language": "ar",
            "source_text": source_text,
        }

        existing_name = frappe.db.get_value("Translation", filters, "name")

        if existing_name:
            doc = frappe.get_doc("Translation", existing_name)
            if getattr(doc, "translated_text", None) != translated_text:
                doc.translated_text = translated_text
                doc.flags.ignore_permissions = True
                doc.save(ignore_permissions=True)
                result["updated"].append(source_text)
            continue

        doc = frappe.new_doc("Translation")
        doc.language = "ar"
        doc.source_text = source_text
        doc.translated_text = translated_text
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
        result["created"].append(source_text)

    frappe.db.commit()
    return result


def remove_unused_sales_invoice_user_invoice_number_field() -> dict[str, list[str]]:
    """Remove unused Sales Invoice.custom_user_invoice_number if it has no data."""
    result = {
        "deleted": [],
        "skipped": [],
        "property_setters_deleted": [],
        "field_order_updated": [],
    }

    fieldname = "custom_user_invoice_number"

    if not _doctype_exists("Sales Invoice"):
        result["skipped"].append("Sales Invoice - missing DocType")
        return result

    has_column = bool(
        frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'tabSales Invoice'
              AND column_name = %s
            """,
            fieldname,
        )[0][0]
    )

    if has_column:
        non_empty = frappe.db.sql(
            f"""
            SELECT COUNT(*)
            FROM `tabSales Invoice`
            WHERE COALESCE(`{fieldname}`, '') != ''
            """
        )[0][0]

        if non_empty:
            result["skipped"].append(
                f"Sales Invoice.{fieldname} has {non_empty} non-empty values"
            )
            return result

    custom_field_name = _get_custom_field_name("Sales Invoice", fieldname)
    if custom_field_name:
        frappe.delete_doc(
            "Custom Field",
            custom_field_name,
            force=True,
            ignore_permissions=True,
        )
        result["deleted"].append(custom_field_name)

    property_setters = frappe.get_all(
        "Property Setter",
        filters={
            "doc_type": "Sales Invoice",
            "field_name": fieldname,
        },
        pluck="name",
    )

    for ps_name in property_setters:
        frappe.delete_doc(
            "Property Setter",
            ps_name,
            force=True,
            ignore_permissions=True,
        )
        result["property_setters_deleted"].append(ps_name)

    field_order_setters = frappe.get_all(
        "Property Setter",
        filters={
            "doc_type": "Sales Invoice",
            "property": "field_order",
        },
        fields=["name", "value"],
    )

    import json

    for row in field_order_setters:
        value = row.get("value") or ""
        if fieldname not in value:
            continue

        new_value = value

        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                parsed = [x for x in parsed if x != fieldname]
                new_value = json.dumps(parsed)
        except Exception:
            new_value = value.replace(f'"{fieldname}", ', "")
            new_value = new_value.replace(f', "{fieldname}"', "")
            new_value = new_value.replace(fieldname, "")

        if new_value != value:
            ps = frappe.get_doc("Property Setter", row["name"])
            ps.value = new_value
            ps.flags.ignore_permissions = True
            ps.save(ignore_permissions=True)
            result["field_order_updated"].append(row["name"])

    frappe.db.commit()
    frappe.clear_cache(doctype="Sales Invoice")
    return result


def sync_sales_invoice_zatca_integration_layout() -> dict[str, list[str]]:
    """Canonical Sales Invoice ZATCA Integration Fields layout."""
    result = {
        "created": [],
        "updated": [],
        "property_setters": [],
        "skipped": [],
    }

    if not _doctype_exists("Sales Invoice"):
        result["skipped"].append("Sales Invoice - missing DocType")
        return result

    def _normalized(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def property_type_for(property_name: str, value: Any) -> str:
        if property_name in {"hidden", "read_only", "collapsible"}:
            return "Check"
        if property_name == "idx":
            return "Int"
        if property_name in {"description", "options"}:
            return "Text"
        return "Data"

    def upsert_property_setter(fieldname: str, property_name: str, value: Any) -> None:
        ps_name = f"Sales Invoice-{fieldname}-{property_name}"
        desired_value = _normalized(value)

        if frappe.db.exists("Property Setter", ps_name):
            ps = frappe.get_doc("Property Setter", ps_name)
            created = False
        else:
            ps = frappe.new_doc("Property Setter")
            ps.name = ps_name
            created = True

        desired = {
            "doc_type": "Sales Invoice",
            "doctype_or_field": "DocField",
            "field_name": fieldname,
            "property": property_name,
            "property_type": property_type_for(property_name, value),
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
        existing = _get_custom_field_name("Sales Invoice", fieldname)

        if existing:
            doc = frappe.get_doc("Custom Field", existing)
            created = False
        else:
            doc = frappe.new_doc("Custom Field")
            doc.dt = "Sales Invoice"
            doc.fieldname = fieldname
            doc.module = MODULE_NAME
            created = True

        changed = False

        for key, value in field.items():
            if key in {"fieldname"}:
                continue

            if getattr(doc, key, None) != value:
                setattr(doc, key, value)
                changed = True

        if created or changed:
            doc.flags.ignore_permissions = True
            doc.save(ignore_permissions=True)

            if created:
                result["created"].append(f"Sales Invoice.{fieldname}")
            else:
                result["updated"].append(f"Sales Invoice.{fieldname}")

        for property_name in [
            "label",
            "insert_after",
            "description",
            "options",
            "hidden",
            "read_only",
            "collapsible",
        ]:
            if property_name in field:
                upsert_property_setter(fieldname, property_name, field[property_name])

    fields = [
        {
            "fieldname": "custom_section_break_gqwpx",
            "idx": 33,
            "fieldtype": "Section Break",
            "label": "ZATCA Integration Fields",
            "insert_after": "amended_from",
            "collapsible": 1,
        },
        {
            "fieldname": "custom_zatca_tax_category",
            "idx": 34,
            "fieldtype": "Select",
            "label": "ZATCA Tax Category",
            "insert_after": "custom_section_break_gqwpx",
            "options": "Standard\nZero Rated\nExempted\nServices outside scope of tax / Not subject to VAT",
            "description": "",
            "read_only": 1,
        },
        {
            "fieldname": "custom_exemption_reason_code",
            "idx": 35,
            "fieldtype": "Select",
            "label": "Exemption Reason Code",
            "insert_after": "custom_zatca_tax_category",
            "options": "\nVATEX-SA-29\nVATEX-SA-29-7\nVATEX-SA-30\nVATEX-SA-32\nVATEX-SA-33\nVATEX-SA-34-1\nVATEX-SA-34-2\nVATEX-SA-34-3\nVATEX-SA-34-4\nVATEX-SA-34-5\nVATEX-SA-35\nVATEX-SA-36\nVATEX-SA-EDU\nVATEX-SA-HEA\nVATEX-SA-MLTRY\nVATEX-SA-OOS",
            "description": "",
        },
        {
            "fieldname": "custom_zatca_discount_reason",
            "idx": 37,
            "fieldtype": "Select",
            "options": "\nBonus for works ahead of schedule\nOther bonus\nManufacturer's consumer discount\nDue to military status\nDue to work accident\nSpecial agreement\nProduction error discount\nNew outlet discount\nSample discount\nEnd of range discount\nIncoterm discount\nPoint of sales threshold allowance\nMaterial surcharge/deduction\nDiscount\nSpecial rebate\nFixed long term\nTemporary\nStandard\nYearly turnover",
            "label": "ZATCA Discount reason",
            "insert_after": "custom_zatca_discount_reason_code",
            "description": "",
        },
        {
            "fieldname": "custom_submit_line_item_discount_to_zatca",
            "idx": 38,
            "fieldtype": "Check",
            "label": "Submit line item discount to ZATCA.",
            "insert_after": "custom_zatca_discount_reason",
            "description": "",
        },
        {
            "fieldname": "custom_column_break_hb6s7",
            "idx": 42,
            "fieldtype": "Column Break",
            "label": "",
            "insert_after": "custom_zatca_status",
        },
        {
            "fieldname": "custom_zatca_third_party_invoice",
            "idx": 43,
            "fieldtype": "Check",
            "label": "ZATCA 3rd party invoice",
            "insert_after": "custom_column_break_hb6s7",
            "description": "",
        },
        {
            "fieldname": "custom_zatca_nominal_invoice",
            "idx": 44,
            "fieldtype": "Check",
            "label": "ZATCA NOMINAL Invoice",
            "insert_after": "custom_zatca_third_party_invoice",
            "description": "",
        },
        {
            "fieldname": "custom_zatca_export_invoice",
            "idx": 45,
            "fieldtype": "Check",
            "label": "ZATCA Export Invoice",
            "insert_after": "custom_zatca_nominal_invoice",
            "description": "",
        },
        {
            "fieldname": "custom_summary_invoice",
            "idx": 46,
            "fieldtype": "Check",
            "label": "ZATCA Summary Invoice",
            "insert_after": "custom_zatca_export_invoice",
            "description": "",
        },
        {
            "fieldname": "custom_self_billed_invoice",
            "idx": 47,
            "fieldtype": "Check",
            "label": "ZATCA Self billed Invoice",
            "insert_after": "custom_summary_invoice",
            "hidden": 1,
            "description": "",
        },
        {
            "fieldname": "custom_column_break_h3ntp",
            "idx": 39,
            "fieldtype": "Column Break",
            "label": "",
            "insert_after": "custom_submit_line_item_discount_to_zatca",
        },
        {
            "fieldname": "custom_uuid",
            "idx": 40,
            "fieldtype": "Small Text",
            "label": "UUID",
            "insert_after": "custom_column_break_h3ntp",
            "read_only": 1,
            "description": "",
        },
        {
            "fieldname": "custom_zatca_status",
            "idx": 41,
            "fieldtype": "Data",
            "label": "ZATCA Status",
            "insert_after": "custom_uuid",
            "read_only": 1,
            "description": "",
        },
        {
            "fieldname": "custom_zatca_status_notification",
            "idx": 19,
            "fieldtype": "HTML",
            "label": "ZATCA Status Notification",
            "insert_after": "column_break_14",
            "description": "",
        },
    ]

    for field in fields:
        ensure_or_update_custom_field(field)

    frappe.db.commit()
    frappe.clear_cache(doctype="Sales Invoice")
    return result



def finalize_sales_invoice_zatca_field_order_and_cleanup() -> dict[str, list[str]]:
    """Finalize Sales Invoice ZATCA field order and safely drop removed columns."""
    result = {
        "field_order_updated": [],
        "db_columns_dropped": [],
        "skipped": [],
    }

    if not _doctype_exists("Sales Invoice"):
        result["skipped"].append("Sales Invoice - missing DocType")
        return result

    user_invoice_field = "custom_user_invoice_number"
    user_invoice_has_data = False

    try:
        user_invoice_column_exists = bool(
            frappe.db.sql(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'tabSales Invoice'
                  AND column_name = %s
                """,
                user_invoice_field,
            )[0][0]
        )

        if user_invoice_column_exists:
            non_empty = frappe.db.sql(
                f"""
                SELECT COUNT(*)
                FROM `tabSales Invoice`
                WHERE COALESCE(`{user_invoice_field}`, '') != ''
                """
            )[0][0]

            if non_empty:
                user_invoice_has_data = True
                result["skipped"].append(
                    f"Sales Invoice.{user_invoice_field} physical column has {non_empty} non-empty values"
                )
            else:
                frappe.db.sql(
                    f"ALTER TABLE `tabSales Invoice` DROP COLUMN `{user_invoice_field}`"
                )
                result["db_columns_dropped"].append(
                    f"tabSales Invoice.{user_invoice_field}"
                )
    except Exception as exc:
        result["skipped"].append(
            f"Could not drop Sales Invoice.{user_invoice_field}: {exc}"
        )

    canonical_order = [
        "custom_section_break_gqwpx",
        "custom_zatca_tax_category",
        "custom_exemption_reason_code",
        "custom_zatca_discount_reason_code",
        "custom_zatca_discount_reason",
        "custom_submit_line_item_discount_to_zatca",
        "custom_column_break_hb6s7",
        "custom_zatca_third_party_invoice",
        "custom_zatca_nominal_invoice",
        "custom_zatca_export_invoice",
        "custom_summary_invoice",
        "custom_self_billed_invoice",
        "custom_column_break_h3ntp",
        "custom_uuid",
        "custom_zatca_status",
        "custom_zatca_status_notification",
    ]

    managed_fields = set(canonical_order)

    # Remove the deleted field from field_order only when it has no data.
    if not user_invoice_has_data:
        managed_fields.add(user_invoice_field)

    import json

    field_order_setters = frappe.get_all(
        "Property Setter",
        filters={
            "doc_type": "Sales Invoice",
            "property": "field_order",
        },
        fields=["name", "value"],
    )

    for row in field_order_setters:
        old_value = row.get("value") or ""

        try:
            current_order = json.loads(old_value)
        except Exception as exc:
            result["skipped"].append(
                f"{row['name']} field_order is not valid JSON: {exc}"
            )
            continue

        if not isinstance(current_order, list):
            result["skipped"].append(f"{row['name']} field_order is not a list")
            continue

        cleaned_order = [
            fieldname
            for fieldname in current_order
            if fieldname not in managed_fields
        ]

        anchor = "amended_from"
        if anchor in cleaned_order:
            insert_at = cleaned_order.index(anchor) + 1
        else:
            insert_at = len(cleaned_order)

        new_order = (
            cleaned_order[:insert_at]
            + canonical_order
            + cleaned_order[insert_at:]
        )

        new_value = json.dumps(new_order)

        if new_value != old_value:
            ps = frappe.get_doc("Property Setter", row["name"])
            ps.value = new_value
            ps.flags.ignore_permissions = True
            ps.save(ignore_permissions=True)
            result["field_order_updated"].append(row["name"])

    frappe.db.commit()
    frappe.clear_cache(doctype="Sales Invoice")
    return result



def sync_tax_template_zatca_source_fields() -> dict[str, list[str]]:
    """Ensure ZATCA source fields exist on tax templates and validation setting exists on Company."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    result = {
        "ensured": [],
        "company_defaults_set": [],
        "skipped": [],
    }

    category_options = (
        "\n"
        "Standard\n"
        "Zero Rated\n"
        "Exempted\n"
        "Services outside scope of tax / Not subject to VAT"
    )

    exemption_options = (
        "\n"
        "VATEX-SA-29\n"
        "VATEX-SA-29-7\n"
        "VATEX-SA-30\n"
        "VATEX-SA-32\n"
        "VATEX-SA-33\n"
        "VATEX-SA-34-1\n"
        "VATEX-SA-34-2\n"
        "VATEX-SA-34-3\n"
        "VATEX-SA-34-4\n"
        "VATEX-SA-34-5\n"
        "VATEX-SA-35\n"
        "VATEX-SA-36\n"
        "VATEX-SA-EDU\n"
        "VATEX-SA-HEA\n"
        "VATEX-SA-MLTRY\n"
        "VATEX-SA-OOS"
    )

    custom_fields = {}

    if _doctype_exists("Sales Taxes and Charges Template"):
        custom_fields["Sales Taxes and Charges Template"] = [
            {
                "fieldname": "custom_zatca_tax_category",
                "fieldtype": "Select",
                "label": "ZATCA Tax Category",
                "insert_after": "taxes",
                "options": category_options,
                "description": "",
            },
            {
                "fieldname": "custom_exemption_reason_code",
                "fieldtype": "Select",
                "label": "Default Exemption Reason Code",
                "insert_after": "custom_zatca_tax_category",
                "options": exemption_options,
                "description": "",
            },
        ]
        result["ensured"].append("Sales Taxes and Charges Template ZATCA fields")
    else:
        result["skipped"].append("Sales Taxes and Charges Template missing")

    if _doctype_exists("Item Tax Template"):
        custom_fields["Item Tax Template"] = [
            {
                "fieldname": "custom_zatca_tax_category",
                "fieldtype": "Select",
                "label": "ZATCA Tax Category",
                "insert_after": "taxes",
                "options": category_options,
                "description": "",
            },
            {
                "fieldname": "custom_exemption_reason_code",
                "fieldtype": "Select",
                "label": "Default Exemption Reason Code",
                "insert_after": "custom_zatca_tax_category",
                "options": exemption_options,
                "description": "",
            },
        ]
        result["ensured"].append("Item Tax Template ZATCA fields")
    else:
        result["skipped"].append("Item Tax Template missing")

    company_fieldname = "custom_enforce_zatca_tax_category_source_validation"
    company_field_existed = bool(
        frappe.db.exists("Custom Field", f"Company-{company_fieldname}")
    )
    category_rate_fieldname = "custom_enforce_zatca_tax_category_rate_validation"
    category_rate_field_existed = bool(
        frappe.db.exists("Custom Field", f"Company-{category_rate_fieldname}")
    )
    payment_entry_limit_fieldname = "custom_enforce_zatca_payment_entry_amount_limit"
    payment_entry_limit_field_existed = bool(
        frappe.db.exists("Custom Field", f"Company-{payment_entry_limit_fieldname}")
    )

    if _doctype_exists("Company"):
        custom_fields.setdefault("Company", []).extend(
            [
                {
                    "fieldname": company_fieldname,
                    "fieldtype": "Check",
                    "label": "Enforce ZATCA tax category source validation",
                    "insert_after": "custom_zatca_negative_line_validation_mode",
                    "default": "1",
                    "description": (
                        "When enabled, the system validates ZATCA tax category source "
                        "and consistency using Item Tax Template or Sales Taxes and Charges Template."
                    ),
                },
                {
                    "fieldname": category_rate_fieldname,
                    "fieldtype": "Check",
                    "label": "Enforce ZATCA zero-rate category validation",
                    "insert_after": company_fieldname,
                    "default": "1",
                    "description": (
                        "When enabled in Phase-2 with ZATCA E-Invoicing enabled, Zero Rated, "
                        "Exempted, and Outside Scope categories must use zero VAT rate and zero tax."
                    ),
                },
                {
                    "fieldname": payment_entry_limit_fieldname,
                    "fieldtype": "Check",
                    "label": "Enforce ZATCA Payment Entry amount limit",
                    "insert_after": category_rate_fieldname,
                    "default": "1",
                    "description": (
                        "When enabled, a linked ZATCA Payment Entry cannot exceed the Sales Invoice total including VAT."
                    ),
                },
            ]
        )
        result["ensured"].append("Company ZATCA source and zero-rate validation settings")

    if custom_fields:
        create_custom_fields(custom_fields, update=True)

    # Keep the user-facing label stable on existing sites as well as new installs.
    for doctype in ("Sales Taxes and Charges Template", "Item Tax Template"):
        custom_field_name = f"{doctype}-custom_exemption_reason_code"
        if frappe.db.exists("Custom Field", custom_field_name):
            frappe.db.set_value(
                "Custom Field",
                custom_field_name,
                "label",
                "Default Exemption Reason Code",
                update_modified=False,
            )

    if (
        _doctype_exists("Company")
        and not company_field_existed
        and frappe.db.has_column("Company", company_fieldname)
    ):
        frappe.db.sql(
            f"""
            UPDATE `tabCompany`
            SET `{company_fieldname}` = 1
            WHERE COALESCE(`{company_fieldname}`, 0) = 0
            """
        )
        result["company_defaults_set"].append(company_fieldname)

    if (
        _doctype_exists("Company")
        and not category_rate_field_existed
        and frappe.db.has_column("Company", category_rate_fieldname)
    ):
        frappe.db.sql(
            f"""
            UPDATE `tabCompany`
            SET `{category_rate_fieldname}` = 1
            WHERE COALESCE(`{category_rate_fieldname}`, 0) = 0
            """
        )
        result["company_defaults_set"].append(category_rate_fieldname)

    if (
        _doctype_exists("Company")
        and not payment_entry_limit_field_existed
        and frappe.db.has_column("Company", payment_entry_limit_fieldname)
    ):
        frappe.db.sql(
            f"""
            UPDATE `tabCompany`
            SET `{payment_entry_limit_fieldname}` = 1
            WHERE COALESCE(`{payment_entry_limit_fieldname}`, 0) = 0
            """
        )
        result["company_defaults_set"].append(payment_entry_limit_fieldname)

    frappe.db.commit()

    for doctype in custom_fields:
        frappe.clear_cache(doctype=doctype)

    return result



def _safe_str(value: Any) -> str:
    """Return a stripped string for customization sync helpers."""
    return str(value or "").strip()


def infer_zatca_source_values_from_tax_template(title: str, rate: Any, description: str = "") -> tuple[str, str]:
    """Infer ZATCA source fields for existing KSA tax templates.

    Reason codes are only auto-filled when the reason is unambiguous.
    Generic zero-rated and exempt templates require manual reason selection.
    """
    title_norm = _strict_normalize_label(title)
    description_norm = _strict_normalize_label(description)
    combined = f"{title_norm} {description_norm}".strip()
    rate_value = flt(rate)

    if "excise" in combined:
        return "", ""

    if "out of scope" in combined or "outside scope" in combined or "not subject" in combined:
        return "Services outside scope of tax / Not subject to VAT", "VATEX-SA-OOS"

    if "exempt" in combined:
        return "Exempted", ""

    if "zero" in combined or "0%" in combined:
        return "Zero Rated", ""

    if "vat" in combined and rate_value > 0:
        return "Standard", ""

    return "", ""


def ensure_ksa_tax_templates_for_companies() -> dict[str, list[str]]:
    """Ensure canonical KSA sales/item tax templates exist for Saudi companies.

    This is intentionally limited to Sales Taxes and Charges Template and Item Tax
    Template. It does not create purchase templates or alter non-Saudi companies.
    """
    from zatca_erpgulf.ksa_compliance.tax_templates import (
        KSA_TAX_DEFINITIONS,
        ensure_item_tax_template,
        ensure_sales_tax_template,
        ensure_tax_account,
        reset_sales_default_for_company,
    )

    result = {"companies": [], "skipped": [], "templates": []}
    if not _doctype_exists("Company"):
        result["skipped"].append("Company missing")
        return result

    for company in frappe.get_all("Company", filters={"country": "Saudi Arabia"}, fields=["name"]):
        company_doc = frappe.get_doc("Company", company.name)
        result["companies"].append(company_doc.name)
        reset_sales_default_for_company(company_doc.name)
        for tax_def in KSA_TAX_DEFINITIONS:
            account = ensure_tax_account(company_doc, tax_def["account_name"])["name"]
            sales = ensure_sales_tax_template(company_doc, tax_def, account)
            item = ensure_item_tax_template(company_doc, tax_def, account)
            result["templates"].extend([sales["name"], item["name"]])

    if result["companies"]:
        frappe.db.commit()
        frappe.clear_cache()
    return result


def sync_existing_tax_template_zatca_values() -> dict[str, list[str]]:
    """Backfill ZATCA tax fields on existing Sales Taxes and Item Tax Templates."""
    result = {
        "updated": [],
        "skipped": [],
    }

    template_specs = [
        {
            "doctype": "Sales Taxes and Charges Template",
            "child_doctype": "Sales Taxes and Charges",
            "rate_field": "rate",
        },
        {
            "doctype": "Item Tax Template",
            "child_doctype": "Item Tax Template Detail",
            "rate_field": "tax_rate",
        },
    ]

    for spec in template_specs:
        doctype = spec["doctype"]

        if not _doctype_exists(doctype):
            result["skipped"].append(f"{doctype} missing")
            continue

        meta = frappe.get_meta(doctype)

        if not (
            meta.has_field("custom_zatca_tax_category")
            and meta.has_field("custom_exemption_reason_code")
        ):
            result["skipped"].append(f"{doctype} ZATCA fields missing")
            continue

        templates = frappe.get_all(
            doctype,
            fields=[
                "name",
                "title",
                "custom_zatca_tax_category",
                "custom_exemption_reason_code",
            ],
            filters={"title": ["like", "KSA %"]},
        )

        for row in templates:
            doc = frappe.get_doc(doctype, row.name)
            tax_rows = list(getattr(doc, "taxes", []) or [])
            first_rate = 0

            if tax_rows:
                first_rate = flt(getattr(tax_rows[0], spec["rate_field"], 0))

            first_description = ""
            if tax_rows:
                first_description = (
                    getattr(tax_rows[0], "description", None)
                    or getattr(tax_rows[0], "tax_type", None)
                    or getattr(tax_rows[0], "account_head", None)
                    or ""
                )

            inferred_category, inferred_reason = infer_zatca_source_values_from_tax_template(
                doc.title or doc.name,
                first_rate,
                first_description,
            )

            if not inferred_category:
                result["skipped"].append(f"{doctype} {doc.name} - no safe inference")
                continue

            changed = False

            if not _safe_str(getattr(doc, "custom_zatca_tax_category", None)):
                doc.custom_zatca_tax_category = inferred_category
                changed = True

            # Only auto-fill reason when unambiguous, such as out of scope.
            if (
                inferred_reason
                and not _safe_str(getattr(doc, "custom_exemption_reason_code", None))
            ):
                doc.custom_exemption_reason_code = inferred_reason
                changed = True

            if changed:
                doc.flags.ignore_permissions = True
                doc.save(ignore_permissions=True)
                result["updated"].append(
                    f"{doctype} {doc.name} -> {inferred_category}"
                    + (f" / {inferred_reason}" if inferred_reason else "")
                )

    frappe.db.commit()

    for spec in template_specs:
        frappe.clear_cache(doctype=spec["doctype"])

    return result



def remove_extra_sales_invoice_zatca_column_breaks() -> dict[str, list[str]]:
    """Remove orphan column breaks inside Sales Invoice ZATCA Integration Fields.

    The intended layout is exactly 3 columns:
    1. category / reasons / discount controls
    2. invoice flags
    3. UUID / status fields
    """
    import json

    result = {
        "deleted": [],
        "field_order_updated": [],
        "skipped": [],
    }

    doctype = "Sales Invoice"
    section_fieldname = "custom_section_break_gqwpx"
    allowed_column_breaks = {
        "custom_column_break_hb6s7",
        "custom_column_break_h3ntp",
    }

    canonical_order = [
        "custom_section_break_gqwpx",
        "custom_zatca_tax_category",
        "custom_exemption_reason_code",
        "custom_zatca_discount_reason_code",
        "custom_zatca_discount_reason",
        "custom_submit_line_item_discount_to_zatca",
        "custom_column_break_hb6s7",
        "custom_zatca_third_party_invoice",
        "custom_zatca_nominal_invoice",
        "custom_zatca_export_invoice",
        "custom_summary_invoice",
        "custom_self_billed_invoice",
        "custom_column_break_h3ntp",
        "custom_uuid",
        "custom_zatca_status",
        "custom_zatca_status_notification",
    ]

    if not _doctype_exists(doctype):
        result["skipped"].append(f"{doctype} missing")
        return result

    meta = frappe.get_meta(doctype)
    fields = list(meta.fields or [])

    try:
        section_idx = next(
            idx for idx, df in enumerate(fields)
            if df.fieldname == section_fieldname
        )
    except StopIteration:
        result["skipped"].append("ZATCA section missing")
        return result

    next_section_idx = len(fields)
    for idx in range(section_idx + 1, len(fields)):
        if fields[idx].fieldtype == "Section Break":
            next_section_idx = idx
            break

    section_fields = fields[section_idx:next_section_idx]

    extra_column_breaks = [
        df.fieldname
        for df in section_fields
        if df.fieldtype == "Column Break"
        and df.fieldname
        and df.fieldname.startswith("custom_")
        and df.fieldname not in allowed_column_breaks
    ]

    for fieldname in extra_column_breaks:
        custom_field_name = f"{doctype}-{fieldname}"

        try:
            if frappe.db.exists("Custom Field", custom_field_name):
                frappe.delete_doc(
                    "Custom Field",
                    custom_field_name,
                    ignore_permissions=True,
                    force=True,
                )
                result["deleted"].append(custom_field_name)

            property_setters = frappe.get_all(
                "Property Setter",
                filters={
                    "doc_type": doctype,
                    "field_name": fieldname,
                },
                pluck="name",
            )

            for property_setter in property_setters:
                frappe.delete_doc(
                    "Property Setter",
                    property_setter,
                    ignore_permissions=True,
                    force=True,
                )
                result["deleted"].append(f"Property Setter {property_setter}")
        except Exception as exc:
            result["skipped"].append(f"{fieldname}: {exc}")

    managed_fields = set(canonical_order) | set(extra_column_breaks)

    field_order_setters = frappe.get_all(
        "Property Setter",
        filters={
            "doc_type": doctype,
            "property": "field_order",
        },
        fields=["name", "value"],
    )

    for row in field_order_setters:
        old_value = row.get("value") or ""

        try:
            current_order = json.loads(old_value)
        except Exception as exc:
            result["skipped"].append(f"{row['name']} invalid field_order JSON: {exc}")
            continue

        if not isinstance(current_order, list):
            result["skipped"].append(f"{row['name']} field_order is not a list")
            continue

        cleaned_order = [
            fieldname for fieldname in current_order
            if fieldname not in managed_fields
        ]

        anchor = "amended_from"
        if anchor in cleaned_order:
            insert_at = cleaned_order.index(anchor) + 1
        else:
            insert_at = len(cleaned_order)

        new_order = (
            cleaned_order[:insert_at]
            + canonical_order
            + cleaned_order[insert_at:]
        )

        new_value = json.dumps(new_order)

        if new_value != old_value:
            ps = frappe.get_doc("Property Setter", row["name"])
            ps.value = new_value
            ps.flags.ignore_permissions = True
            ps.save(ignore_permissions=True)
            result["field_order_updated"].append(row["name"])

    frappe.db.commit()
    frappe.clear_cache(doctype=doctype)
    return result



def sync_sales_invoice_advance_deduction_detail_table_field() -> dict[str, list[str]]:
    result = {
        "ensured": [],
        "updated": [],
        "skipped": [],
    }

    if not _doctype_exists("Sales Invoice"):
        result["skipped"].append("Sales Invoice missing")
        return result

    if not _doctype_exists("ZATCA Sales Invoice Advance Deduction"):
        result["skipped"].append("ZATCA Sales Invoice Advance Deduction missing")
        return result

    spec = {
        "dt": "Sales Invoice",
        "fieldname": "custom_zatca_advance_deduction_details",
        "label": "ZATCA Advance Deduction Details",
        "fieldtype": "Table",
        "options": "ZATCA Sales Invoice Advance Deduction",
        "insert_after": "custom_zatca_advance_deduction_count",
        "description": "",
        "read_only": 0,
        "no_copy": 1,
        "allow_on_submit": 0,
        "module": MODULE_NAME,
    }

    name = frappe.db.get_value(
        "Custom Field",
        {
            "dt": spec["dt"],
            "fieldname": spec["fieldname"],
        },
        "name",
    )

    if name:
        doc = frappe.get_doc("Custom Field", name)
        changed = False

        for fieldname, value in spec.items():
            if hasattr(doc, fieldname) and getattr(doc, fieldname) != value:
                setattr(doc, fieldname, value)
                changed = True

        if changed:
            doc.save(ignore_permissions=True)
            result["updated"].append(spec["fieldname"])
        else:
            result["ensured"].append(spec["fieldname"])
    else:
        doc = frappe.get_doc({
            "doctype": "Custom Field",
            **spec,
        })
        doc.insert(ignore_permissions=True)
        result["ensured"].append(spec["fieldname"])

    frappe.clear_cache(doctype="Sales Invoice")
    frappe.db.commit()
    return result



def sync_sales_invoice_advance_deduction_total_fields() -> dict[str, list[str]]:
    """Ensure Sales Invoice totals for ZATCA advance deductions.

    These fields are calculated from the independent direct-allocation child table.
    """
    result = {
        "ensured": [],
        "updated": [],
        "skipped": [],
    }

    if not _doctype_exists("Sales Invoice"):
        result["skipped"].append("Sales Invoice missing")
        return result

    specs = [
        {
            "dt": "Sales Invoice",
            "fieldname": "custom_zatca_advance_deduction_totals_section",
            "label": "ZATCA Advance Deduction",
            "fieldtype": "Section Break",
            "insert_after": "advances",
            "description": "Automatically summarizes accepted ZATCA advance deductions from System standard Advance Payments.",
            "hidden": 0,
            "collapsible": 1,
            "no_copy": 1,
            "module": MODULE_NAME,
        },
        {
            "dt": "Sales Invoice",
            "fieldname": "custom_zatca_advance_deducted_taxable_amount",
            "label": "ZATCA Advance Applied Amount Before VAT",
            "fieldtype": "Currency",
            "options": "currency",
            "insert_after": "custom_zatca_advance_deduction_totals_section",
            "read_only": 1,
            "no_copy": 1,
            "module": MODULE_NAME,
            "description": "Total taxable amount applied from linked advance-payment Sales Invoices.",
        },
        {
            "dt": "Sales Invoice",
            "fieldname": "custom_zatca_advance_deducted_vat_amount",
            "label": "ZATCA Advance Applied VAT Amount",
            "fieldtype": "Currency",
            "options": "currency",
            "insert_after": "custom_zatca_advance_deducted_taxable_amount",
            "read_only": 1,
            "no_copy": 1,
            "module": MODULE_NAME,
            "description": "Total VAT amount already invoiced through linked advance-payment Sales Invoices.",
        },
    ]

    for spec in specs:
        name = frappe.db.get_value(
            "Custom Field",
            {
                "dt": spec["dt"],
                "fieldname": spec["fieldname"],
            },
            "name",
        )

        if name:
            doc = frappe.get_doc("Custom Field", name)
            changed = False

            for fieldname, value in spec.items():
                if hasattr(doc, fieldname) and getattr(doc, fieldname) != value:
                    setattr(doc, fieldname, value)
                    changed = True

            if changed:
                doc.save(ignore_permissions=True)
                result["updated"].append(spec["fieldname"])
            else:
                result["ensured"].append(spec["fieldname"])
        else:
            doc = frappe.get_doc({
                "doctype": "Custom Field",
                **spec,
            })
            doc.insert(ignore_permissions=True)
            result["ensured"].append(spec["fieldname"])

    frappe.clear_cache(doctype="Sales Invoice")
    frappe.db.commit()
    return result



def sync_zatca_advance_final_invoice_layout() -> dict[str, list[str]]:
    """Sync final-invoice deduction fields for standard advance Sales Invoices."""
    result = {
        "ensured": [],
        "updated": [],
        "skipped": [],
    }

    def upsert_custom_field(spec):
        name = frappe.db.get_value(
            "Custom Field",
            {
                "dt": spec["dt"],
                "fieldname": spec["fieldname"],
            },
            "name",
        )

        if name:
            doc = frappe.get_doc("Custom Field", name)
            changed = False

            for fieldname, value in spec.items():
                if hasattr(doc, fieldname) and getattr(doc, fieldname) != value:
                    setattr(doc, fieldname, value)
                    changed = True

            if changed:
                doc.save(ignore_permissions=True)
                result["updated"].append(f'{spec["dt"]}.{spec["fieldname"]}')
            else:
                result["ensured"].append(f'{spec["dt"]}.{spec["fieldname"]}')
            return

        doc = frappe.get_doc({
            "doctype": "Custom Field",
            **spec,
        })
        doc.insert(ignore_permissions=True)
        result["ensured"].append(f'{spec["dt"]}.{spec["fieldname"]}')

    if _doctype_exists("Sales Invoice") and _doctype_exists("ZATCA Sales Invoice Advance Deduction"):
        sales_invoice_specs = [
            {
                "dt": "Sales Invoice",
                "fieldname": "custom_zatca_advance_deduction_section",
                "label": "ZATCA Advance Deductions",
                "fieldtype": "Section Break",
                "insert_after": "advances",
                "hidden": 0,
                "module": MODULE_NAME,
            },
            {
                "dt": "Sales Invoice",
                "fieldname": "custom_section_break_qhp4f",
                "label": "ZATCA Advance Deduction Table",
                "fieldtype": "Section Break",
                "insert_after": "custom_zatca_advance_deduction_count",
                "collapsible": 1,
                "hidden": 0,
                "module": MODULE_NAME,
            },
            {
                "dt": "Sales Invoice",
                "fieldname": "custom_zatca_advance_deduction_details",
                "label": "ZATCA Advance Deduction Details",
                "fieldtype": "Table",
                "options": "ZATCA Sales Invoice Advance Deduction",
                "insert_after": "custom_zatca_advance_deduction_count",
                "description": "",
                "read_only": 0,
                "editable_grid": 1,
                "no_copy": 1,
                "allow_on_submit": 0,
                "module": MODULE_NAME,
            },
            {
                "dt": "Sales Invoice",
                "fieldname": "custom_zatca_advance_deduction_totals_section",
                "label": "ZATCA Advance Deduction",
                "fieldtype": "Section Break",
                "insert_after": "advances",
                "description": "Automatically summarizes accepted ZATCA advance deductions from System standard Advance Payments.",
                "hidden": 0,
                "collapsible": 1,
                "no_copy": 1,
                "module": MODULE_NAME,
            },
            {
                "dt": "Sales Invoice",
                "fieldname": "custom_zatca_advance_deducted_taxable_amount",
                "label": "ZATCA Advance Applied Amount Before VAT",
                "fieldtype": "Currency",
                "options": "currency",
                "insert_after": "custom_zatca_advance_deduction_totals_section",
                "read_only": 1,
                "no_copy": 1,
                "module": MODULE_NAME,
                "description": "Total taxable amount applied from linked advance-payment Sales Invoices.",
            },
            {
                "dt": "Sales Invoice",
                "fieldname": "custom_zatca_advance_deduction_totals_column_break",
                "label": "",
                "fieldtype": "Column Break",
                "insert_after": "custom_zatca_advance_deducted_taxable_amount",
                "hidden": 1,
                "no_copy": 1,
                "module": MODULE_NAME,
            },
            {
                "dt": "Sales Invoice",
                "fieldname": "custom_zatca_advance_deducted_vat_amount",
                "label": "ZATCA Advance Applied VAT Amount",
                "fieldtype": "Currency",
                "options": "currency",
                "insert_after": "custom_zatca_advance_deduction_totals_column_break",
                "read_only": 1,
                "no_copy": 1,
                "module": MODULE_NAME,
                "description": "Total VAT amount already invoiced through linked advance-payment Sales Invoices.",
            },
        ]

        for spec in sales_invoice_specs:
            upsert_custom_field(spec)

        frappe.clear_cache(doctype="Sales Invoice")
    else:
        result["skipped"].append("Sales Invoice or ZATCA Sales Invoice Advance Deduction missing")

    frappe.db.commit()
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


ADVANCE_PAYMENT_NAMING_SERIES = "ADV-.abbr.-.YYYY.-"


def ensure_sales_invoice_advance_naming_series() -> dict[str, Any]:
    """Append the advance-payment series without replacing site-defined series."""
    result = {"updated": False, "skipped": []}

    if not _doctype_exists("Sales Invoice") or not _property_setter_available():
        result["skipped"].append("Sales Invoice or Property Setter is unavailable")
        return result

    field = frappe.get_meta("Sales Invoice").get_field("naming_series")
    if not field:
        result["skipped"].append("Sales Invoice.naming_series is unavailable")
        return result

    options = [line.strip() for line in (field.options or "").splitlines() if line.strip()]
    if ADVANCE_PAYMENT_NAMING_SERIES in options:
        return result

    options.append(ADVANCE_PAYMENT_NAMING_SERIES)
    changed = _upsert_property_setter({
        "doctype": "Property Setter",
        "doc_type": "Sales Invoice",
        "doctype_or_field": "DocField",
        "field_name": "naming_series",
        "property": "options",
        "property_type": "Text",
        "value": "\n".join(options),
        "name": "Sales Invoice-naming_series-options-zatca_erpgulf",
    })
    if changed:
        frappe.clear_cache(doctype="Sales Invoice")
        result["updated"] = True
    return result


def force_sales_invoice_zatca_field_order_property_setter() -> dict[str, Any]:
    """Force the approved Sales Invoice field_order Property Setter.

    Sales Invoice can have a DocType-level field_order Property Setter. When it
    exists, it controls the visual field order even if Custom Field insert_after
    and idx are correct.
    """

    import json

    badge_field = "custom_zatca_status_notification"

    zatca_order = [
        "custom_section_break_gqwpx",
        "custom_zatca_tax_category",
        "custom_exemption_reason_code",
        "custom_zatca_discount_reason_code",
        "custom_zatca_discount_reason",
        "custom_submit_line_item_discount_to_zatca",
        "custom_column_break_h3ntp",
        "company_tax_id",
        "custom_uuid",
        "custom_zatca_status",
        "custom_column_break_hb6s7",
        "custom_zatca_third_party_invoice",
        "custom_zatca_nominal_invoice",
        "custom_zatca_export_invoice",
        "custom_summary_invoice",
        "custom_self_billed_invoice",
        "custom_section_break_qhp4f",
        "custom_zatca_advance_deduction_details",
        "custom_zatca_advance_deduction_totals_section",
        "custom_zatca_prepaid_amount",
        "custom_zatca_advance_deducted_taxable_amount",
        "custom_zatca_advance_deduction_summary_column_break",
        "custom_zatca_advance_deduction_count",
        "custom_zatca_advance_deducted_vat_amount",
    ]

    result = {
        "updated": 0,
        "created": 0,
        "skipped": [],
        "missing_fields": [],
        "before": {},
        "after": {},
    }

    property_setter_name = frappe.db.get_value(
        "Property Setter",
        {
            "doc_type": "Sales Invoice",
            "doctype_or_field": "DocType",
            "property": "field_order",
        },
        "name",
    )

    if property_setter_name:
        property_setter = frappe.get_doc("Property Setter", property_setter_name)
        try:
            order = json.loads(property_setter.value or "[]")
        except Exception:
            result["skipped"].append("Could not parse Sales Invoice field_order JSON.")
            return result
    else:
        meta = frappe.get_meta("Sales Invoice")
        order = [df.fieldname for df in meta.fields if df.fieldname]
        property_setter = frappe.get_doc(
            {
                "doctype": "Property Setter",
                "doc_type": "Sales Invoice",
                "doctype_or_field": "DocType",
                "field_name": None,
                "property": "field_order",
                "property_type": "Data",
            }
        )

    unique_order = []
    seen = set()
    for fieldname in order:
        if fieldname and fieldname not in seen:
            unique_order.append(fieldname)
            seen.add(fieldname)

    order = unique_order

    required_anchors = [
        "company",
        "column_break_14",
        "is_pos",
        "amended_from",
        "advances",
        "loyalty_points_redemption",
        "accounting_dimensions_section",
    ]
    for fieldname in required_anchors:
        if fieldname not in order:
            result["skipped"].append(f"Missing required anchor: {fieldname}")

    if result["skipped"]:
        return result

    marker_anchor = (
        "is_advance_payment"
        if frappe.get_meta("Sales Invoice").has_field("is_advance_payment")
        else "custom_is_advance_payment"
        if frappe.get_meta("Sales Invoice").has_field("custom_is_advance_payment")
        else ""
    )
    controlled = {
        "abbr",
        "custom_zatca_payment_entry",
        "custom_zatca_advance_deduction_section",
        "custom_zatca_advance_deduction_totals_column_break",
    }
    if marker_anchor:
        controlled.add(marker_anchor)
    available_zatca_order = []

    if frappe.db.exists("Custom Field", {"dt": "Sales Invoice", "fieldname": "abbr"}) or "abbr" in order:
        controlled.add("abbr")
    else:
        result["missing_fields"].append("abbr")

    payment_entry_field = "custom_zatca_payment_entry"
    if frappe.db.exists("Custom Field", {"dt": "Sales Invoice", "fieldname": payment_entry_field}) or payment_entry_field in order:
        controlled.add(payment_entry_field)
    else:
        result["missing_fields"].append(payment_entry_field)

    if frappe.db.exists("Custom Field", {"dt": "Sales Invoice", "fieldname": badge_field}) or badge_field in order:
        controlled.add(badge_field)
    else:
        result["missing_fields"].append(badge_field)

    for fieldname in zatca_order:
        if frappe.db.exists("Custom Field", {"dt": "Sales Invoice", "fieldname": fieldname}) or fieldname in order:
            controlled.add(fieldname)
            available_zatca_order.append(fieldname)
        else:
            result["missing_fields"].append(fieldname)

    targets = [
        "company",
        "abbr",
        payment_entry_field,
        "column_break_14",
        badge_field,
        "is_pos",
        "amended_from",
        *zatca_order,
    ]

    for fieldname in targets:
        result["before"][fieldname] = order.index(fieldname) if fieldname in order else None

    new_order = []
    for fieldname in order:
        if fieldname not in controlled:
            new_order.append(fieldname)

    if "abbr" in controlled:
        new_order.insert(new_order.index("company") + 1, "abbr")

    if marker_anchor in controlled:
        marker_insert_after = (
            "is_debit_note"
            if "is_debit_note" in new_order
            else "is_return"
            if "is_return" in new_order
            else "customer"
        )
        new_order.insert(new_order.index(marker_insert_after) + 1, marker_anchor)

    if payment_entry_field in controlled and marker_anchor in new_order:
        new_order.insert(new_order.index(marker_anchor) + 1, payment_entry_field)
    pos = new_order.index("column_break_14")
    if badge_field in controlled:
        new_order.insert(pos + 1, badge_field)

    advance_fieldnames = {
        "custom_zatca_advance_deduction_section",
        "custom_zatca_advance_deduction_totals_section",
        "custom_zatca_prepaid_amount",
        "custom_zatca_advance_deduction_summary_column_break",
        "custom_zatca_advance_deduction_count",
        "custom_section_break_qhp4f",
        "custom_zatca_advance_deduction_details",
        "custom_zatca_advance_deduction_totals_section",
        "custom_zatca_advance_deducted_taxable_amount",
        "custom_zatca_advance_deduction_totals_column_break",
        "custom_zatca_advance_deducted_vat_amount",
    }
    integration_order = [
        fieldname
        for fieldname in available_zatca_order
        if fieldname not in advance_fieldnames
    ]
    advance_order = [
        fieldname
        for fieldname in available_zatca_order
        if fieldname in advance_fieldnames
    ]

    # Keep ZATCA Integration Fields before the standard Accounting Dimensions.
    pos = new_order.index("accounting_dimensions_section")
    for offset, fieldname in enumerate(integration_order, start=0):
        new_order.insert(pos + offset, fieldname)

    # Keep the advance-deduction block with ERPNext Advance Payments, before
    # the standard Loyalty Points Redemption section.
    pos = new_order.index("advances")
    for offset, fieldname in enumerate(advance_order, start=1):
        new_order.insert(pos + offset, fieldname)

    for fieldname in targets:
        result["after"][fieldname] = new_order.index(fieldname) if fieldname in new_order else None

    new_value = json.dumps(new_order, ensure_ascii=False)

    if property_setter.value != new_value:
        property_setter.value = new_value

        if property_setter.is_new():
            property_setter.insert(ignore_permissions=True)
            result["created"] = 1
        else:
            property_setter.save(ignore_permissions=True)
            result["updated"] = 1

        frappe.db.commit()

    frappe.clear_cache(doctype="Sales Invoice")
    frappe.clear_document_cache("DocType", "Sales Invoice")

    return result


def sync_sales_invoice_print_heading() -> dict[str, Any]:
    """Ensure the dynamic ZATCA heading exists only on active non-standard formats."""
    result = {"updated": [], "skipped": []}
    formats = frappe.get_all(
        "Print Format",
        filters={
            "doc_type": "Sales Invoice",
            "standard": "No",
            "custom_format": 0,
            "disabled": 0,
        },
        pluck="name",
    )
    for name in formats:
        print_format = frappe.get_doc("Print Format", name)
        try:
            format_data = json.loads(print_format.format_data or "[]")
        except (TypeError, ValueError):
            result["skipped"].append(f"{name}: invalid format_data")
            continue
        if not isinstance(format_data, list):
            result["skipped"].append(f"{name}: format_data is not a list")
            continue

        heading = {
            "fieldname": "print_heading_template",
            "fieldtype": "Custom HTML",
            "options": SALES_INVOICE_PRINT_HEADING_TEMPLATE,
        }
        if format_data and format_data[0].get("fieldname") == "print_heading_template":
            if format_data[0].get("options") == SALES_INVOICE_PRINT_HEADING_TEMPLATE:
                continue
            format_data[0] = {**format_data[0], **heading}
        else:
            format_data.insert(0, heading)

        print_format.db_set(
            "format_data", json.dumps(format_data, ensure_ascii=False), update_modified=False
        )
        result["updated"].append(name)

    if result["updated"]:
        frappe.clear_cache(doctype="Print Format")
    return result


def ensure_advance_payment_item() -> dict[str, Any]:
    """Create the standard non-stock advance item once, without overwriting user data."""
    result = {"created": [], "present": [], "skipped": []}

    if not _doctype_exists("Item"):
        result["skipped"].append("Item DocType missing")
        return result

    if frappe.db.exists("Item", ADVANCE_PAYMENT_ITEM_CODE):
        result["present"].append(ADVANCE_PAYMENT_ITEM_CODE)
        return result

    if not frappe.db.exists("UOM", "Nos"):
        result["skipped"].append("Standard UOM Nos missing")
        return result

    # Item Group names are site-local and may be translated (for example, the
    # standard English groups are often renamed to Arabic). Prefer the
    # canonical service groups, then use any existing leaf group rather than
    # refusing to create the non-stock advance item.
    item_group = frappe.db.get_value(
        "Item Group",
        {"name": ["in", ["Services", "الخدمات"]], "is_group": 0},
        "name",
    )
    if not item_group:
        item_group = frappe.db.get_value(
            "Item Group", {"is_group": 0}, "name", order_by="lft asc"
        )
    if not item_group:
        result["skipped"].append("No leaf Item Group is available")
        return result

    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": ADVANCE_PAYMENT_ITEM_CODE,
            "item_name": ADVANCE_PAYMENT_ITEM_CODE,
            "description": ADVANCE_PAYMENT_ITEM_CODE,
            "item_group": item_group,
            "stock_uom": "Nos",
            "is_stock_item": 0,
            "is_sales_item": 1,
            "is_purchase_item": 0,
            "disabled": 0,
        }
    )
    item.flags.ignore_permissions = True
    item.insert(ignore_permissions=True)
    result["created"].append(ADVANCE_PAYMENT_ITEM_CODE)
    return result


def hide_legacy_discount_reason_code() -> None:
    """Hide the retired code field while preserving old stored values."""
    fieldname = "Sales Invoice-custom_zatca_discount_reason_code"
    if frappe.db.exists("Custom Field", fieldname):
        frappe.db.set_value("Custom Field", fieldname, "hidden", 1, update_modified=False)
        frappe.clear_cache(doctype="Sales Invoice")



def enforce_tax_template_permissions() -> dict[str, list[str]]:
    """Restrict tax-template write/create rights to the exact System Manager role.

    This is intentionally called only from ``after_install``. Updating the app or
    running ``after_migrate`` must not overwrite administrator permission choices.
    """
    result = {"updated": [], "skipped": []}
    role = "System Manager"
    if not frappe.db.exists("Role", role):
        result["skipped"].append(f"Role missing: {role}")
        return result

    for doctype in ("Item Tax Template", "Sales Taxes and Charges Template"):
        if not _doctype_exists(doctype) or not _doctype_exists("DocPerm"):
            result["skipped"].append(f"{doctype} or DocPerm missing")
            continue

        rows = frappe.get_all(
            "DocPerm",
            filters={"parent": doctype, "permlevel": 0},
            fields=["name", "role", "read", "write", "create"],
        )
        for row in rows:
            docperm = frappe.get_doc("DocPerm", row.name)
            allowed = str(row.role or "") == role
            changed = False
            for fieldname, value in (("read", 1), ("write", int(allowed)), ("create", int(allowed))):
                if getattr(docperm, fieldname, None) != value:
                    setattr(docperm, fieldname, value)
                    changed = True
            if changed:
                docperm.flags.ignore_permissions = True
                docperm.save(ignore_permissions=True)
                result["updated"].append(f"{doctype}:{row.role}")

        if not any(str(row.role or "") == role for row in rows):
            docperm = frappe.get_doc(
                {
                    "doctype": "DocPerm",
                    "parent": doctype,
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    "role": role,
                    "permlevel": 0,
                    "read": 1,
                    "write": 1,
                    "create": 1,
                    "print": 1,
                    "email": 1,
                    "export": 1,
                    "share": 1,
                }
            )
            docperm.flags.ignore_permissions = True
            docperm.insert(ignore_permissions=True)
            result["updated"].append(f"{doctype}:{role}")

    frappe.db.commit()
    return result


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
    sales_invoice_advance_detail_table_result = sync_sales_invoice_advance_deduction_detail_table_field()
    sales_invoice_advance_total_fields_result = sync_sales_invoice_advance_deduction_total_fields()
    zatca_advance_final_invoice_layout_result = sync_zatca_advance_final_invoice_layout()
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
    user_invoice_number_removal_result = remove_unused_sales_invoice_user_invoice_number_field()
    sales_invoice_zatca_ui_result = sync_sales_invoice_zatca_integration_layout()
    sales_invoice_zatca_column_cleanup_result = remove_extra_sales_invoice_zatca_column_breaks()
    sales_invoice_zatca_finalize_result = finalize_sales_invoice_zatca_field_order_and_cleanup()
    sales_invoice_advance_naming_series_result = ensure_sales_invoice_advance_naming_series()
    sales_invoice_zatca_field_order_property_setter_result = force_sales_invoice_zatca_field_order_property_setter()
    tax_template_zatca_source_fields_result = sync_tax_template_zatca_source_fields()
    existing_tax_template_zatca_values_result = sync_existing_tax_template_zatca_values()
    ksa_tax_templates_result = ensure_ksa_tax_templates_for_companies()
    advance_payment_item_result = ensure_advance_payment_item()
    sales_invoice_print_heading_result = sync_sales_invoice_print_heading()
    zatca_arabic_translations_result = sync_zatca_arabic_translations()
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
        "sales_invoice_advance_detail_table": sales_invoice_advance_detail_table_result,
        "sales_invoice_advance_total_fields": sales_invoice_advance_total_fields_result,
        "zatca_advance_final_invoice_layout": zatca_advance_final_invoice_layout_result,
        "arabic_name_cleanup": arabic_name_cleanup_result,
        "arabic_name_layout": arabic_name_layout_result,
        "customer_zatca_tax_layout": customer_zatca_tax_layout_result,
        "customer_details_tax_strict_layout": customer_details_tax_strict_layout_result,
        "force_customer_layout": force_customer_layout_result,
        "property_setters": property_setters_result,
        "critical_property_setters": critical_property_setters_result,
        "company_zatca_ui": company_zatca_ui_result,
        "sales_invoice_user_invoice_number_removal": user_invoice_number_removal_result,
        "sales_invoice_zatca_ui": sales_invoice_zatca_ui_result,
        "sales_invoice_zatca_column_cleanup": sales_invoice_zatca_column_cleanup_result,
        "sales_invoice_advance_naming_series": sales_invoice_advance_naming_series_result,
        "sales_invoice_zatca_finalize": sales_invoice_zatca_finalize_result,
        "tax_template_zatca_source_fields": tax_template_zatca_source_fields_result,
        "existing_tax_template_zatca_values": existing_tax_template_zatca_values_result,
        "ksa_tax_templates": ksa_tax_templates_result,
        "advance_payment_item": advance_payment_item_result,
        "sales_invoice_print_heading": sales_invoice_print_heading_result,
        "zatca_arabic_translations": zatca_arabic_translations_result,
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
    hide_legacy_discount_reason_code()
    enforce_tax_template_permissions()


def after_sync() -> None:
    sync_all_zatca_customizations()


def after_migrate() -> None:
    run_zatca_customization_sync_after_migrate()
    hide_legacy_discount_reason_code()
