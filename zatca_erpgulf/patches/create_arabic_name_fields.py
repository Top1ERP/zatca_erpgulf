import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def field_exists(doctype: str, fieldname: str) -> bool:
    meta = frappe.get_meta(doctype)
    return bool(meta.get_field(fieldname))


def execute():
    custom_fields = {}

    # ------------------------------------------------------------------
    # Company
    # If standard field exists, do nothing.
    # Otherwise create only custom_company_name_in_arabic if missing.
    # ------------------------------------------------------------------
    if not field_exists("Company", "company_name_in_arabic"):
        if not field_exists("Company", "custom_company_name_in_arabic"):
            custom_fields.setdefault("Company", []).append({
                "fieldname": "custom_company_name_in_arabic",
                "label": "Company Name In Arabic",
                "fieldtype": "Data",
                "insert_after": "company_name",
                "translatable": 0,
                "read_only": 0,
                "reqd": 0,
            })

    # ------------------------------------------------------------------
    # Customer
    # If standard field exists, do nothing.
    # Otherwise create only custom_customer_name_in_arabic if missing.
    # ------------------------------------------------------------------
    if not field_exists("Customer", "customer_name_in_arabic"):
        if not field_exists("Customer", "custom_customer_name_in_arabic"):
            custom_fields.setdefault("Customer", []).append({
                "fieldname": "custom_customer_name_in_arabic",
                "label": "Customer Name Arabic",
                "fieldtype": "Data",
                "insert_after": "customer_name",
                "translatable": 0,
                "read_only": 0,
                "reqd": 0,
            })

    if custom_fields:
        create_custom_fields(custom_fields, update=True)