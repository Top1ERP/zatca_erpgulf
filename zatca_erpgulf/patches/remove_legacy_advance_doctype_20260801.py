from __future__ import annotations

import frappe
from frappe import _


LEGACY_DOCTYPE = "ZATCA Advance Tax Invoice"

OBSOLETE_CUSTOM_FIELDS = {
    "Company": (
        "custom_zatca_advance_payment_section",
        "custom_zatca_advance_payment_enabled",
        "custom_zatca_advance_payment_submission_mode",
        "custom_zatca_advance_default_tc_name",
        "custom_zatca_advance_signing_enabled",
        "custom_zatca_advance_api_submission_enabled",
    ),
    "Payment Entry": (
        "custom_zatca_advance_section",
        "custom_zatca_is_advance_payment",
        "custom_zatca_advance_tax_invoice",
        "custom_zatca_advance_invoice_status",
        "custom_zatca_advance_invoice_uuid",
        "custom_zatca_advance_qr_code",
        "custom_zatca_advance_xml",
        "custom_zatca_advance_last_debug_at",
        "custom_zatca_advance_full_response",
    ),
    "Sales Invoice": (
        "custom_is_advance_credit_note",
        "custom_advance_invoice_reference",
    ),
}

OBSOLETE_DATABASE_COLUMNS = {
    **OBSOLETE_CUSTOM_FIELDS,
    "ZATCA Sales Invoice Advance Deduction": (
        "zatca_advance_tax_invoice",
    ),
}


def _table_name(doctype: str) -> str:
    return f"tab{doctype}"


def _table_exists(doctype: str) -> bool:
    return bool(frappe.db.table_exists(doctype))


def _column_exists(doctype: str, fieldname: str) -> bool:
    return _table_exists(doctype) and bool(
        frappe.db.has_column(doctype, fieldname)
    )


def _count_rows(doctype: str, where_sql: str = "1=1", values=()) -> int:
    rows = frappe.db.sql(
        f"SELECT COUNT(*) FROM `{_table_name(doctype)}` WHERE {where_sql}",
        values,
    )
    return int(rows[0][0] or 0)


def _assert_no_legacy_data() -> None:
    blockers = []

    if _table_exists(LEGACY_DOCTYPE):
        count = _count_rows(LEGACY_DOCTYPE)
        if count:
            blockers.append(f"{LEGACY_DOCTYPE}: {count} document(s)")

    value_checks = (
        ("Payment Entry", "custom_zatca_advance_tax_invoice"),
        ("Sales Invoice", "custom_advance_invoice_reference"),
        (
            "ZATCA Sales Invoice Advance Deduction",
            "zatca_advance_tax_invoice",
        ),
    )

    for doctype, fieldname in value_checks:
        if not _column_exists(doctype, fieldname):
            continue

        count = _count_rows(
            doctype,
            f"COALESCE(`{fieldname}`, '') != ''",
        )
        if count:
            blockers.append(f"{doctype}.{fieldname}: {count} populated row(s)")

    reference_checks = (
        ("File", "attached_to_doctype"),
        ("Comment", "reference_doctype"),
        ("Version", "ref_doctype"),
        ("Communication", "reference_doctype"),
        ("ToDo", "reference_type"),
    )

    for doctype, fieldname in reference_checks:
        if not _column_exists(doctype, fieldname):
            continue

        count = _count_rows(doctype, f"`{fieldname}` = %s", (LEGACY_DOCTYPE,))
        if count:
            blockers.append(f"{doctype}.{fieldname}: {count} reference(s)")

    if blockers:
        frappe.throw(
            _(
                "Legacy advance invoice retirement stopped because unexpected data "
                "still exists: {0}"
            ).format("; ".join(blockers))
        )


def _delete_custom_field(doctype: str, fieldname: str) -> None:
    names = frappe.get_all(
        "Custom Field",
        filters={"dt": doctype, "fieldname": fieldname},
        pluck="name",
    )
    for name in names:
        frappe.delete_doc(
            "Custom Field",
            name,
            ignore_permissions=True,
            force=True,
        )


def _delete_property_setters(doctype: str, fieldname: str) -> None:
    names = frappe.get_all(
        "Property Setter",
        filters={"doc_type": doctype, "field_name": fieldname},
        pluck="name",
    )
    for name in names:
        frappe.delete_doc(
            "Property Setter",
            name,
            ignore_permissions=True,
            force=True,
        )


def _drop_column(doctype: str, fieldname: str) -> None:
    if not _column_exists(doctype, fieldname):
        return

    frappe.db.sql_ddl(
        f"ALTER TABLE `{_table_name(doctype)}` DROP COLUMN `{fieldname}`"
    )


def execute() -> None:
    _assert_no_legacy_data()

    for doctype, fieldnames in OBSOLETE_CUSTOM_FIELDS.items():
        for fieldname in fieldnames:
            _delete_property_setters(doctype, fieldname)
            _delete_custom_field(doctype, fieldname)

    for doctype, fieldnames in OBSOLETE_DATABASE_COLUMNS.items():
        for fieldname in fieldnames:
            _drop_column(doctype, fieldname)

    if frappe.db.exists("DocType", LEGACY_DOCTYPE):
        frappe.delete_doc(
            "DocType",
            LEGACY_DOCTYPE,
            ignore_permissions=True,
            force=True,
        )

    for doctype in (*OBSOLETE_CUSTOM_FIELDS, "ZATCA Sales Invoice Advance Deduction"):
        frappe.clear_cache(doctype=doctype)
