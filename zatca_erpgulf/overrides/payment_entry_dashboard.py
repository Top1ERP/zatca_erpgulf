from frappe import _, _dict

from zatca_erpgulf.zatca_erpgulf.zatca_runtime import (
    ADVANCE_PAYMENT_ENTRY_LINK_FIELD,
    supports_advance_payment_entry_link,
)


def get_dashboard_data(data=None):
    """Expose advance invoices only when the physical link schema is available."""
    data = _dict(data or {})
    if not supports_advance_payment_entry_link():
        return data

    fieldnames = data.setdefault("non_standard_fieldnames", {})
    existing_fieldname = fieldnames.get("Sales Invoice")
    if existing_fieldname and existing_fieldname != ADVANCE_PAYMENT_ENTRY_LINK_FIELD:
        return data

    fieldnames["Sales Invoice"] = ADVANCE_PAYMENT_ENTRY_LINK_FIELD
    transactions = data.setdefault("transactions", [])
    if not any("Sales Invoice" in (group.get("items") or []) for group in transactions):
        transactions.append({"label": _("Advance Payment"), "items": ["Sales Invoice"]})

    if not data.get("fieldname"):
        data.fieldname = ADVANCE_PAYMENT_ENTRY_LINK_FIELD
    return data
