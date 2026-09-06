import frappe


FIELDNAMES = (
    "custom_zatca_output_attachments_section",
    "custom_attach_xml_with_invoice",
    "custom_zatca_output_attach_column_break_1",
    "custom_attach_xml_with_qr_code",
    "custom_zatca_output_attach_column_break_2",
    "custom_attach_qr_code_doctype",
    "custom_attach_e_invoice_send_status_with_invoice",
)


def execute():
    """Remove retired/legacy Company output-attachment fields safely."""
    for fieldname in FIELDNAMES:
        custom_field_name = f"Company-{fieldname}"
        if frappe.db.exists("Custom Field", custom_field_name):
            frappe.delete_doc(
                "Custom Field",
                custom_field_name,
                force=True,
                ignore_permissions=True,
            )

    frappe.db.commit()
    frappe.clear_cache(doctype="Company")
