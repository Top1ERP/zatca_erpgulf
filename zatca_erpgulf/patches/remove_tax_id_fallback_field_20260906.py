import frappe


FIELDNAME = "custom_allow_zatca_tax_id_fallback"
CUSTOM_FIELD_NAME = f"Company-{FIELDNAME}"


def execute():
    """Remove the retired Tax ID fallback Company field safely."""
    if frappe.db.exists("Custom Field", CUSTOM_FIELD_NAME):
        frappe.delete_doc(
            "Custom Field",
            CUSTOM_FIELD_NAME,
            force=True,
            ignore_permissions=True,
        )

    frappe.db.commit()
    frappe.clear_cache(doctype="Company")
