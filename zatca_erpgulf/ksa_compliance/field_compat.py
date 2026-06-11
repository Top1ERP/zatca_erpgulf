from __future__ import annotations

from typing import Iterable

import frappe


APP_MODULE = "Zatca Erpgulf"


FIELD_ALIAS_GROUPS = {
    "company_arabic_name": {
        "doctype": "Company",
        "canonical": "custom_company_name_in_arabic",
        "aliases": [
            "custom_company_name_in_arabic",
            "company_name_in_arabic",
            "custom__company_name_in_arabic__",
        ],
    },
    "customer_arabic_name": {
        "doctype": "Customer",
        "canonical": "custom_customer_name_in_arabic",
        "aliases": [
            "custom_customer_name_in_arabic",
            "customer_name_in_arabic",
            "zatca_customer_name_in_arabic",
        ],
    },
    "supplier_arabic_name": {
        "doctype": "Supplier",
        "canonical": "supplier_name_in_arabic",
        "aliases": [
            "supplier_name_in_arabic",
            "custom_supplier_name_in_arabic",
            "zatca_supplier_name_in_arabic",
        ],
    },
    "address_arabic": {
        "doctype": "Address",
        "canonical": "address_in_arabic",
        "aliases": [
            "address_in_arabic",
            "custom_address_in_arabic",
            "zatca_address_in_arabic",
            "address_line1_in_arabic",
            "custom_address_line1_in_arabic",
            "custom__address_in_arabic__",
        ],
    },
    "sales_invoice_qr": {
        "doctype": "Sales Invoice",
        "canonical": "ksa_einv_qr",
        "aliases": [
            "ksa_einv_qr",
            "custom_ksa_einv_qr",
        ],
    },
    "pos_invoice_qr": {
        "doctype": "POS Invoice",
        "canonical": "ksa_einv_qr",
        "aliases": [
            "ksa_einv_qr",
            "custom_ksa_einv_qr",
        ],
    },
    "customer_b2c": {
        "doctype": "Customer",
        "canonical": "custom_b2c",
        "aliases": [
            "custom_b2c",
            "b2c",
            "is_b2c",
            "zatca_b2c",
        ],
    },
    "customer_buyer_id_type": {
        "doctype": "Customer",
        "canonical": "custom_buyer_id_type",
        "aliases": [
            "custom_buyer_id_type",
            "buyer_id_type",
            "zatca_buyer_id_type",
        ],
    },
    "customer_buyer_id": {
        "doctype": "Customer",
        "canonical": "custom_buyer_id",
        "aliases": [
            "custom_buyer_id",
            "buyer_id",
            "zatca_buyer_id",
        ],
    },
    "item_is_zero_rated": {
        "doctype": "Item",
        "canonical": "is_zero_rated",
        "aliases": [
            "is_zero_rated",
            "custom_is_zero_rated",
            "zatca_is_zero_rated",
        ],
    },
    "item_is_exempt": {
        "doctype": "Item",
        "canonical": "is_exempt",
        "aliases": [
            "is_exempt",
            "custom_is_exempt",
            "zatca_is_exempt",
        ],
    },
}


def field_exists(doctype: str, fieldname: str) -> bool:
    if not doctype or not fieldname:
        return False

    try:
        meta = frappe.get_meta(doctype)
        if meta and meta.get_field(fieldname):
            return True
    except Exception:
        pass

    if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}):
        return True

    if frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname}):
        return True

    return False


def first_existing_fieldname(doctype: str, fieldnames: Iterable[str]) -> str | None:
    for fieldname in fieldnames:
        if field_exists(doctype, fieldname):
            return fieldname
    return None


def get_alias_group(key: str) -> dict:
    if key not in FIELD_ALIAS_GROUPS:
        frappe.throw(f"Unknown ZATCA/KSA field alias group: {key}")
    return FIELD_ALIAS_GROUPS[key]


def get_existing_alias(key: str) -> str | None:
    group = get_alias_group(key)
    return first_existing_fieldname(group["doctype"], group["aliases"])


def get_effective_fieldname(key: str) -> str:
    group = get_alias_group(key)
    return get_existing_alias(key) or group["canonical"]


def should_create_canonical_field(key: str) -> bool:
    return get_existing_alias(key) is None


def create_custom_field_if_no_alias(
    doctype: str,
    field_spec: dict,
    aliases: list[str] | None = None,
    module: str = APP_MODULE,
) -> dict:
    fieldname = field_spec.get("fieldname")
    if not fieldname:
        frappe.throw("field_spec.fieldname is required")

    aliases = aliases or [fieldname]
    existing = first_existing_fieldname(doctype, aliases)

    if existing:
        return {
            "doctype": doctype,
            "fieldname": fieldname,
            "created": False,
            "skipped": True,
            "existing_fieldname": existing,
            "reason": "alias_already_exists",
        }

    custom_field = frappe.new_doc("Custom Field")
    custom_field.dt = doctype
    custom_field.module = module

    for key, value in field_spec.items():
        setattr(custom_field, key, value)

    custom_field.insert(ignore_permissions=True, ignore_if_duplicate=True)
    frappe.clear_cache(doctype=doctype)

    return {
        "doctype": doctype,
        "fieldname": fieldname,
        "created": True,
        "skipped": False,
        "existing_fieldname": None,
        "reason": "created",
    }


def report_field_alias_status() -> dict:
    result = {}

    for key, group in FIELD_ALIAS_GROUPS.items():
        existing = first_existing_fieldname(group["doctype"], group["aliases"])
        result[key] = {
            "doctype": group["doctype"],
            "canonical": group["canonical"],
            "aliases": group["aliases"],
            "existing": existing,
            "should_create_canonical": existing is None,
            "effective_fieldname": existing or group["canonical"],
        }

    return result
