from __future__ import annotations

from frappe.utils import cint


PHASE_1_VALUE = "Phase-1"
PHASE_2_VALUE = "Phase-2"


def _get_value(doc, fieldname, default=None):
    if not doc:
        return default

    getter = getattr(doc, "get", None)
    if callable(getter):
        return getter(fieldname, default)

    return getattr(doc, fieldname, default)


def _has_field(doc, fieldname: str) -> bool:
    if not doc:
        return False

    meta = getattr(doc, "meta", None)
    has_field = getattr(meta, "has_field", None)

    if callable(has_field):
        return bool(has_field(fieldname))

    return hasattr(doc, fieldname)


def is_advance_payment_invoice(sales_invoice_doc) -> bool:
    """Resolve the Sales Invoice advance marker without OR-merging two fields.

    The exact standard-style field has priority whenever it exists in metadata,
    including when its value is 0. The legacy custom marker is consulted only
    when the exact field is absent.
    """
    if _has_field(sales_invoice_doc, "is_advance_payment"):
        return bool(cint(_get_value(sales_invoice_doc, "is_advance_payment", 0)))

    if _has_field(sales_invoice_doc, "custom_is_advance_payment"):
        return bool(cint(_get_value(sales_invoice_doc, "custom_is_advance_payment", 0)))

    return False


def is_zatca_invoice_enabled(company_doc) -> bool:
    """Use the single general ZATCA enablement switch."""
    return bool(cint(_get_value(company_doc, "custom_zatca_invoice_enabled", 0)))


def resolve_zatca_phase(company_doc) -> str:
    """Prefer custom_phase_1_or_2, with phase_1_or_2 as compatibility fallback."""
    primary = str(_get_value(company_doc, "custom_phase_1_or_2", "") or "").strip()
    if primary:
        return primary

    return str(_get_value(company_doc, "phase_1_or_2", "") or "").strip()


def get_zatca_environment(company_doc) -> str:
    """Return the existing general ZATCA environment selection."""
    return str(_get_value(company_doc, "custom_select", "") or "").strip()


def get_b2c_submission_method(company_doc) -> str:
    """Return the existing general B2C submission method."""
    return str(
        _get_value(company_doc, "custom_send_invoice_to_zatca", "") or ""
    ).strip()
