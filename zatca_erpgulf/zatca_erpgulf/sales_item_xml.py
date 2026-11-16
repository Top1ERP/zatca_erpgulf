"""Select existing Sales item builders for ordinary and local Debug generation.

Keep the primary generator's schema/direct-allocation/legacy-copy decision and
lazy read order. The chosen builder owns reference checks and money; this helper
does not search advances, allocate, calculate, mutate, sign, persist or submit.
"""


def populate_sales_items(invoice, doc, *, namespace, has_template):
    """Bind the caller's current functions, preserving replacement-root results."""
    installed = namespace["frappe"].get_installed_apps()
    legacy_installed = "claudion4saudi" in installed
    has_legacy_copy = hasattr(doc, "custom_advances_copy") and doc.custom_advances_copy
    has_direct = namespace["supports_advance_deduction_schema"](doc) and any(
        row.get("advance_invoice") and row.get("allocated_total_amount")
        for row in doc.get("custom_zatca_advance_deduction_details", []) or []
    )
    if has_direct or (legacy_installed and has_legacy_copy):
        name = "item_data_with_template_advance_invoice" if has_template else "item_data_advance_invoice"
    else:
        name = "item_data_with_template" if has_template else "item_data"
    return namespace[name](invoice, doc)
