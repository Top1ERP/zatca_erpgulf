from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


APP_NAME = "zatca_erpgulf"
MODULE_NAME = "Zatca Erpgulf"


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
            "fieldname": "custom_zatca_negative_line_validation_mode",
            "label": "ZATCA Negative Line Validation Mode",
            "fieldtype": "Select",
            "options": "Strict\nWarn Only\nDisabled",
            "default": "Strict",
            "insert_after": "custom_zatca_invoice_enabled",
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
                "custom_zatca_invoice_enabled",
                "custom_costcenter",
                "custom_company_name_in_arabic",
                "company_name",
                "abbr",
                "default_currency",
            ],
        }
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

            alternatives = field_def_copy.pop("_alternatives", [])
            target_fieldname = field_def_copy.get("fieldname")
            fallback_candidates = field_def_copy.pop("_fallback_insert_after", [])

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
    property_setters_result = sync_property_setters_from_fixture()
    critical_property_setters_result = ensure_critical_property_setters()

    frappe.db.commit()

    result = {
        "frappe_major": frappe_major,
        "custom_fields": custom_fields_result,
        "critical_custom_fields": critical_fields_result,
        "property_setters": property_setters_result,
        "critical_property_setters": critical_property_setters_result,
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
