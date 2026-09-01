from __future__ import annotations

import frappe

from frappe.utils import cint
from zatca_erpgulf.ksa_compliance.field_compat import get_compat_value


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
    return str(
        get_compat_value(
            company_doc,
            ("custom_phase_1_or_2", "phase_1_or_2"),
            "",
        )
        or ""
    ).strip()


def get_zatca_environment(company_doc) -> str:
    """Return the existing general ZATCA environment selection."""
    return str(_get_value(company_doc, "custom_select", "") or "").strip()


def get_b2c_submission_method(company_doc) -> str:
    """Return the existing general B2C submission method."""
    return str(
        _get_value(company_doc, "custom_send_invoice_to_zatca", "") or ""
    ).strip()


def is_clearance_enabled(company_doc) -> bool:
    """Resolve the optional Clearance switch, preserving the current default.

    Older Sites do not have a dedicated switch; those Sites retain the existing
    Clearance behavior. Newer installations may expose either app-owned field
    spelling and can explicitly disable Clearance for Standard documents.
    """
    for fieldname in (
        "custom_zatca_clearance_enabled",
        "custom_clearance_enabled",
        "clearance_enabled",
    ):
        if _has_field(company_doc, fieldname):
            return bool(cint(_get_value(company_doc, fieldname, 1)))
    return True


# ---------------------------------------------------------------------------
# Runtime schema compatibility
# ---------------------------------------------------------------------------
#
# A Frappe Bench can run one shared application codebase against multiple
# Sites whose database migrations are at different stages.
#
# These helpers intentionally detect actual capabilities instead of relying
# on the application version or assuming that `bench migrate` has already
# been executed for every Site.
#
# IMPORTANT:
# Missing optional/new ZATCA schema means that the corresponding feature is
# unavailable on that Site. It must not break standard ERPNext transactions.
# Business validation remains strict once the complete feature schema exists.


ADVANCE_PAYMENT_ENTRY_LINK_FIELD = "custom_zatca_payment_entry"

ADVANCE_DEDUCTION_CHILD_DOCTYPE = "ZATCA Sales Invoice Advance Deduction"
ADVANCE_DEDUCTION_TABLE_FIELD = "custom_zatca_advance_deduction_details"

ADVANCE_DEDUCTION_PARENT_FIELDS = (
    "custom_zatca_status",
    "custom_zatca_advance_deduction_section",
    "custom_zatca_prepaid_amount",
    "custom_zatca_advance_deduction_count",
    "custom_zatca_advance_deduction_details",
    "custom_zatca_advance_deduction_totals_section",
    "custom_zatca_advance_deducted_taxable_amount",
    "custom_zatca_advance_deduction_totals_column_break",
    "custom_zatca_advance_deducted_vat_amount",
)

ADVANCE_DEDUCTION_PARENT_DB_FIELDS = (
    "custom_zatca_status",
    "custom_zatca_prepaid_amount",
    "custom_zatca_advance_deduction_count",
    "custom_zatca_advance_deducted_taxable_amount",
    "custom_zatca_advance_deducted_vat_amount",
)

ADVANCE_DEDUCTION_CHILD_FIELDS = (
    "payment_entry",
    "advance_invoice",
    "advance_invoice_date",
    "advance_status",
    "currency",
    "advance_total_amount",
    "advance_taxable_amount",
    "advance_tax_amount",
    "allocated_total_amount",
    "allocated_taxable_amount",
    "allocated_tax_amount",
    "remarks",
)

ADVANCE_DEDUCTION_CHILD_DB_FIELDS = (
    "name",
    "parent",
    "parenttype",
    "parentfield",
    "idx",
    *ADVANCE_DEDUCTION_CHILD_FIELDS,
)


def _doctype_meta_available(doctype: str):
    """Return DocType metadata when safely available, otherwise None."""
    if not doctype:
        return None

    if not frappe.db.exists("DocType", doctype):
        return None

    try:
        return frappe.get_meta(doctype)
    except frappe.DoesNotExistError:
        return None


def _doctype_table_available(doctype: str) -> bool:
    """Return whether the physical SQL table for a DocType exists."""
    if not doctype:
        return False

    return bool(frappe.db.table_exists(doctype))


def _doctype_has_columns(doctype: str, fieldnames) -> bool:
    """Require physical SQL columns after first proving the table exists."""
    if not doctype or not _doctype_table_available(doctype):
        return False

    columns = set(frappe.db.get_table_columns(doctype))
    return all(fieldname in columns for fieldname in fieldnames)


def _meta_has_fields(meta, fieldnames) -> bool:
    """Require every supplied field to exist in the provided metadata."""
    if not meta:
        return False

    return all(meta.has_field(fieldname) for fieldname in fieldnames)


def supports_advance_payment_marker(doc=None) -> bool:
    """Return whether this Site/document supports an advance-payment marker."""
    if doc is not None:
        meta = getattr(doc, "meta", None)
    else:
        meta = _doctype_meta_available("Sales Invoice")

    if not meta:
        return False

    for fieldname in ("is_advance_payment", "custom_is_advance_payment"):
        if meta.has_field(fieldname):
            return _doctype_has_columns("Sales Invoice", (fieldname,))

    return False


def supports_advance_payment_entry_link(doc=None) -> bool:
    """Return whether the Sales Invoice ↔ Payment Entry link schema exists."""
    if doc is not None:
        meta = getattr(doc, "meta", None)
    else:
        meta = _doctype_meta_available("Sales Invoice")

    if not meta:
        return False

    return bool(
        supports_advance_payment_marker(doc)
        and meta.has_field(ADVANCE_PAYMENT_ENTRY_LINK_FIELD)
        and _doctype_has_columns(
            "Sales Invoice",
            (ADVANCE_PAYMENT_ENTRY_LINK_FIELD,),
        )
    )


def supports_advance_deduction_schema(doc=None) -> bool:
    """Return whether the complete direct advance-deduction schema exists.

    This is intentionally stricter than checking only the Sales Invoice Table
    field. A partially migrated Site can contain Custom Field metadata while
    the physical child table is still missing.

    The feature is considered available only when:
    - all required Sales Invoice parent fields exist;
    - all stored parent fields have physical SQL columns;
    - the child DocType metadata exists;
    - its physical SQL table exists;
    - all child fields required by the current runtime exist in metadata and SQL.
    """
    if doc is not None:
        meta = getattr(doc, "meta", None)
    else:
        meta = _doctype_meta_available("Sales Invoice")

    if not supports_advance_payment_marker(doc):
        return False

    if not _meta_has_fields(meta, ADVANCE_DEDUCTION_PARENT_FIELDS):
        return False

    if not _doctype_has_columns(
        "Sales Invoice",
        ADVANCE_DEDUCTION_PARENT_DB_FIELDS,
    ):
        return False

    child_meta = _doctype_meta_available(ADVANCE_DEDUCTION_CHILD_DOCTYPE)
    if not child_meta:
        return False

    if not _doctype_table_available(ADVANCE_DEDUCTION_CHILD_DOCTYPE):
        return False

    if not _meta_has_fields(child_meta, ADVANCE_DEDUCTION_CHILD_FIELDS):
        return False

    if not _doctype_has_columns(
        ADVANCE_DEDUCTION_CHILD_DOCTYPE,
        ADVANCE_DEDUCTION_CHILD_DB_FIELDS,
    ):
        return False

    return True


@frappe.whitelist()
def get_zatca_runtime_capabilities(doc=None) -> dict[str, bool]:
    """Return the optional ZATCA runtime features available on this Site."""
    return {
        "advance_payment_marker": supports_advance_payment_marker(doc),
        "advance_payment_entry_link": supports_advance_payment_entry_link(doc),
        "advance_deduction": supports_advance_deduction_schema(doc),
    }
