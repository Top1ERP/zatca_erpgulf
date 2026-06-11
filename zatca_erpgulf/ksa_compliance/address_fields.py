from __future__ import annotations

import frappe


APP_MODULE = "Zatca Erpgulf"
ADDRESS_DOCTYPE = "Address"
CANONICAL_FIELDNAME = "address_in_arabic"

ADDRESS_ARABIC_ALIASES = [
    "address_in_arabic",
    "custom_address_in_arabic",
    "zatca_address_in_arabic",
    "address_line1_in_arabic",
    "custom_address_line1_in_arabic",
    "custom__address_in_arabic__",
]


def field_exists(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.get_meta(doctype, cached=False).has_field(fieldname))
    except Exception:
        return False


def existing_address_arabic_fields() -> list[str]:
    return [
        fieldname
        for fieldname in ADDRESS_ARABIC_ALIASES
        if field_exists(ADDRESS_DOCTYPE, fieldname)
    ]


def get_effective_address_arabic_fieldname() -> str | None:
    """Prefer canonical address_in_arabic, otherwise return the first existing alias."""

    if field_exists(ADDRESS_DOCTYPE, CANONICAL_FIELDNAME):
        return CANONICAL_FIELDNAME

    for fieldname in ADDRESS_ARABIC_ALIASES:
        if fieldname != CANONICAL_FIELDNAME and field_exists(ADDRESS_DOCTYPE, fieldname):
            return fieldname

    return None


def get_address_arabic_value(address_doc) -> str:
    """Read Arabic address value from any supported field shape."""

    for fieldname in ADDRESS_ARABIC_ALIASES:
        if hasattr(address_doc, "get") and address_doc.get(fieldname):
            return str(address_doc.get(fieldname)).strip()

    return ""


def get_insert_after_field() -> str:
    meta = frappe.get_meta(ADDRESS_DOCTYPE, cached=False)

    for candidate in [
        "address_line1",
        "address_line2",
        "city",
        "county",
        "state",
        "pincode",
        "country",
    ]:
        if meta.has_field(candidate):
            return candidate

    return ""


@frappe.whitelist()
def ensure_address_in_arabic_field() -> dict:
    """Ensure canonical Address.address_in_arabic exists.

    This intentionally creates the canonical field if it is missing,
    while still supporting older/alternate field names for compatibility.
    Existing alias fields are not removed to avoid data loss.
    """

    result = {
        "doctype": ADDRESS_DOCTYPE,
        "canonical": CANONICAL_FIELDNAME,
        "aliases": ADDRESS_ARABIC_ALIASES,
        "existing_before": existing_address_arabic_fields(),
        "created": False,
    }

    if field_exists(ADDRESS_DOCTYPE, CANONICAL_FIELDNAME):
        result["existing_after"] = existing_address_arabic_fields()
        result["effective_fieldname"] = get_effective_address_arabic_fieldname()
        return result

    custom_field_name = f"{ADDRESS_DOCTYPE}-{CANONICAL_FIELDNAME}"

    if not frappe.db.exists("Custom Field", custom_field_name):
        insert_after = get_insert_after_field()

        custom_field = frappe.get_doc({
            "doctype": "Custom Field",
            "dt": ADDRESS_DOCTYPE,
            "fieldname": CANONICAL_FIELDNAME,
            "label": "Address in Arabic",
            "fieldtype": "Small Text",
            "insert_after": insert_after,
            "module": APP_MODULE,
            "allow_on_submit": 1,
            "description": (
                "Arabic address field used by ZATCA. "
                "The app also supports older aliases such as custom_address_in_arabic "
                "and address_line1_in_arabic."
            ),
        })

        # Compatible with Frappe versions where Custom Field has translatable.
        if frappe.get_meta("Custom Field").has_field("translatable"):
            custom_field.translatable = 1

        custom_field.flags.ignore_validate = True
        custom_field.flags.ignore_mandatory = True
        custom_field.insert(ignore_permissions=True)

        result["created"] = True

    frappe.clear_cache(doctype=ADDRESS_DOCTYPE)

    result["existing_after"] = existing_address_arabic_fields()
    result["effective_fieldname"] = get_effective_address_arabic_fieldname()

    return result


@frappe.whitelist()
def report_address_arabic_field_status() -> dict:
    return {
        "doctype": ADDRESS_DOCTYPE,
        "canonical": CANONICAL_FIELDNAME,
        "aliases": ADDRESS_ARABIC_ALIASES,
        "existing": existing_address_arabic_fields(),
        "effective_fieldname": get_effective_address_arabic_fieldname(),
        "canonical_exists": field_exists(ADDRESS_DOCTYPE, CANONICAL_FIELDNAME),
    }
