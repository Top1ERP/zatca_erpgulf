from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import frappe
from frappe import _


LEGACY_DOCTYPE = "ZATCA Advance Tax Invoice"
LEGACY_TABLE = f"tab{LEGACY_DOCTYPE}"
LEGACY_SERIES_PREFIX = "ZADV-"
LEGACY_SERIES_PATTERN = f"{LEGACY_SERIES_PREFIX}%"

OBSOLETE_CUSTOM_FIELDS = {
    "Company": {
        "custom_zatca_advance_payment_section",
        "custom_zatca_advance_payment_enabled",
        "custom_zatca_advance_payment_submission_mode",
        "custom_zatca_advance_default_tc_name",
        "custom_zatca_advance_signing_enabled",
        "custom_zatca_advance_api_submission_enabled",
    },
    "Payment Entry": {
        "custom_zatca_advance_section",
        "custom_zatca_is_advance_payment",
        "custom_zatca_advance_tax_invoice",
        "custom_zatca_advance_invoice_status",
        "custom_zatca_advance_invoice_uuid",
        "custom_zatca_advance_qr_code",
        "custom_zatca_advance_xml",
        "custom_zatca_advance_last_debug_at",
        "custom_zatca_advance_full_response",
    },
    "Sales Invoice": {
        "custom_is_advance_credit_note",
        "custom_advance_invoice_reference",
    },
}


def _table_exists(doctype: str) -> bool:
    return bool(frappe.db.table_exists(doctype))


def _count_rows(
    doctype: str,
    where_sql: str = "1=1",
    values: tuple[Any, ...] = (),
) -> int:
    if not _table_exists(doctype):
        return 0

    rows = frappe.db.sql(
        f"SELECT COUNT(*) FROM `tab{doctype}` WHERE {where_sql}",
        values,
    )
    return int(rows[0][0] or 0)


def _safe_payload(data: str | None) -> Mapping[str, Any] | None:
    if not data:
        return {}

    try:
        payload = frappe.parse_json(data)
    except Exception:
        return None

    if isinstance(payload, Mapping):
        return payload

    return None


def _is_obsolete_custom_field(payload: Mapping[str, Any]) -> bool:
    doctype = str(payload.get("dt") or "")
    fieldname = str(payload.get("fieldname") or "")

    return fieldname in OBSOLETE_CUSTOM_FIELDS.get(doctype, set())


def _is_obsolete_property_setter(payload: Mapping[str, Any]) -> bool:
    doctype = str(payload.get("doc_type") or "")
    fieldname = str(payload.get("field_name") or "")

    return fieldname in OBSOLETE_CUSTOM_FIELDS.get(doctype, set())


def _is_legacy_file(payload: Mapping[str, Any]) -> bool:
    attached_doctype = str(payload.get("attached_to_doctype") or "")
    attached_name = str(payload.get("attached_to_name") or "")

    return (
        attached_doctype == LEGACY_DOCTYPE
        or attached_name.startswith(LEGACY_SERIES_PREFIX)
    )


def _deleted_document_rows() -> list[frappe._dict]:
    return frappe.db.sql(
        """
        SELECT
            name,
            deleted_doctype,
            deleted_name,
            data
        FROM `tabDeleted Document`
        WHERE restored = 0
          AND (
                deleted_doctype = %s
             OR (
                    deleted_doctype = 'DocType'
                AND deleted_name = %s
             )
             OR deleted_doctype IN ('Custom Field', 'Property Setter')
             OR (
                    deleted_doctype = 'File'
                AND (
                       data LIKE %s
                    OR data LIKE %s
                )
             )
          )
        ORDER BY creation, name
        """,
        (
            LEGACY_DOCTYPE,
            LEGACY_DOCTYPE,
            f"%{LEGACY_DOCTYPE}%",
            f"%{LEGACY_SERIES_PREFIX}%",
        ),
        as_dict=True,
    )


def _classify_deleted_document(
    row: frappe._dict,
) -> tuple[str | None, str | None]:
    deleted_doctype = str(row.deleted_doctype or "")
    deleted_name = str(row.deleted_name or "")

    if deleted_doctype == LEGACY_DOCTYPE:
        return "legacy_document", None

    if deleted_doctype == "DocType" and deleted_name == LEGACY_DOCTYPE:
        return "legacy_doctype", None

    payload = _safe_payload(row.data)

    if payload is None:
        if deleted_doctype == "File":
            return None, (
                f"Deleted Document {row.name} contains an unreadable File payload"
            )
        return None, None

    if deleted_doctype == "Custom Field" and _is_obsolete_custom_field(payload):
        return "obsolete_custom_field", None

    if (
        deleted_doctype == "Property Setter"
        and _is_obsolete_property_setter(payload)
    ):
        return "obsolete_property_setter", None

    if deleted_doctype == "File" and _is_legacy_file(payload):
        return "legacy_file", None

    return None, None


def _deleted_document_plan() -> tuple[list[dict[str, str]], list[str]]:
    records = []
    errors = []

    for row in _deleted_document_rows():
        reason, error = _classify_deleted_document(row)

        if error:
            errors.append(error)
            continue

        if reason:
            records.append(
                {
                    "name": str(row.name),
                    "deleted_doctype": str(row.deleted_doctype or ""),
                    "deleted_name": str(row.deleted_name or ""),
                    "reason": reason,
                }
            )

    return records, errors


def _legacy_deleted_comment_rows() -> list[dict[str, str]]:
    if not _table_exists("Comment"):
        return []

    rows = frappe.db.sql(
        """
        SELECT
            name,
            comment_type,
            COALESCE(reference_doctype, '') AS reference_doctype,
            COALESCE(reference_name, '') AS reference_name
        FROM `tabComment`
        WHERE COALESCE(comment_type, '') = 'Deleted'
          AND reference_doctype = %s
          AND COALESCE(reference_name, '') = ''
        ORDER BY creation, name
        """,
        (LEGACY_DOCTYPE,),
        as_dict=True,
    )

    return [
        {
            "name": str(row.name),
            "comment_type": str(row.comment_type or ""),
            "reference_doctype": str(row.reference_doctype or ""),
            "reference_name": str(row.reference_name or ""),
        }
        for row in rows
    ]


def _collect_live_blockers() -> list[str]:
    blockers = []

    if frappe.db.exists("DocType", LEGACY_DOCTYPE):
        blockers.append(f"DocType {LEGACY_DOCTYPE} still exists")

    if _table_exists(LEGACY_DOCTYPE):
        row_count = _count_rows(LEGACY_DOCTYPE)
        if row_count:
            blockers.append(
                f"{LEGACY_TABLE} contains {row_count} live row(s)"
            )

    reference_checks = (
        (
            "Payment Entry Reference",
            (
                "`reference_doctype` = %s "
                "OR `reference_name` LIKE %s"
            ),
            (LEGACY_DOCTYPE, LEGACY_SERIES_PATTERN),
        ),
        (
            "File",
            (
                "`attached_to_doctype` = %s "
                "OR `attached_to_name` LIKE %s"
            ),
            (LEGACY_DOCTYPE, LEGACY_SERIES_PATTERN),
        ),
        (
            "Communication",
            (
                "`reference_doctype` = %s "
                "OR `reference_name` LIKE %s"
            ),
            (LEGACY_DOCTYPE, LEGACY_SERIES_PATTERN),
        ),
        (
            "Dynamic Link",
            (
                "`link_doctype` = %s "
                "OR `link_name` LIKE %s"
            ),
            (LEGACY_DOCTYPE, LEGACY_SERIES_PATTERN),
        ),
        (
            "ToDo",
            (
                "`reference_type` = %s "
                "OR `reference_name` LIKE %s"
            ),
            (LEGACY_DOCTYPE, LEGACY_SERIES_PATTERN),
        ),
        (
            "Version",
            (
                "`ref_doctype` = %s "
                "OR ("
                "    `docname` LIKE %s "
                "    AND `ref_doctype` != 'Series'"
                ")"
            ),
            (LEGACY_DOCTYPE, LEGACY_SERIES_PATTERN),
        ),
    )

    for doctype, where_sql, values in reference_checks:
        count = _count_rows(doctype, where_sql, values)
        if count:
            blockers.append(f"{doctype}: {count} live reference(s)")

    if _table_exists("Comment"):
        comment_count = _count_rows(
            "Comment",
            """
            (
                `reference_doctype` = %s
                OR `reference_name` LIKE %s
            )
            AND NOT (
                COALESCE(`comment_type`, '') = 'Deleted'
                AND `reference_doctype` = %s
                AND COALESCE(`reference_name`, '') = ''
            )
            """,
            (
                LEGACY_DOCTYPE,
                LEGACY_SERIES_PATTERN,
                LEGACY_DOCTYPE,
            ),
        )

        if comment_count:
            blockers.append(
                f"Comment: {comment_count} live reference(s)"
            )

    return blockers


def diagnose() -> dict[str, Any]:
    deleted_records, deleted_errors = _deleted_document_plan()
    deleted_comments = _legacy_deleted_comment_rows()
    table_exists = _table_exists(LEGACY_DOCTYPE)

    return {
        "legacy_doctype_count": int(
            frappe.db.count(
                "DocType",
                filters={"name": LEGACY_DOCTYPE},
            )
        ),
        "legacy_table_exists": int(table_exists),
        "legacy_table_rows": (
            _count_rows(LEGACY_DOCTYPE) if table_exists else 0
        ),
        "legacy_series_rows": _count_rows(
            "Series",
            "`name` LIKE %s",
            (LEGACY_SERIES_PATTERN,),
        ),
        "legacy_series_version_rows": _count_rows(
            "Version",
            "`ref_doctype` = 'Series' AND `docname` LIKE %s",
            (LEGACY_SERIES_PATTERN,),
        ),
        "deleted_document_candidates": deleted_records,
        "deleted_document_candidate_count": len(deleted_records),
        "legacy_deleted_comment_candidates": deleted_comments,
        "legacy_deleted_comment_candidate_count": len(deleted_comments),
        "deleted_document_errors": deleted_errors,
        "live_blockers": _collect_live_blockers(),
    }


def _assert_safe_to_cleanup() -> list[dict[str, str]]:
    blockers = _collect_live_blockers()
    deleted_records, deleted_errors = _deleted_document_plan()

    blockers.extend(deleted_errors)

    if blockers:
        frappe.throw(
            _(
                "Legacy advance artifact cleanup stopped because unsafe "
                "or unexpected data still exists: {0}"
            ).format("; ".join(blockers))
        )

    return deleted_records


def _delete_deleted_document_records(
    records: list[dict[str, str]],
) -> None:
    for record in records:
        frappe.db.sql(
            "DELETE FROM `tabDeleted Document` WHERE `name` = %s",
            (record["name"],),
        )


def _delete_legacy_deleted_comments() -> None:
    if not _table_exists("Comment"):
        return

    frappe.db.sql(
        """
        DELETE FROM `tabComment`
        WHERE COALESCE(`comment_type`, '') = 'Deleted'
          AND `reference_doctype` = %s
          AND COALESCE(`reference_name`, '') = ''
        """,
        (LEGACY_DOCTYPE,),
    )


def _delete_legacy_series_history() -> None:
    frappe.db.sql(
        """
        DELETE FROM `tabVersion`
        WHERE `ref_doctype` = 'Series'
          AND `docname` LIKE %s
        """,
        (LEGACY_SERIES_PATTERN,),
    )

    frappe.db.sql(
        "DELETE FROM `tabSeries` WHERE `name` LIKE %s",
        (LEGACY_SERIES_PATTERN,),
    )


def _drop_empty_legacy_table() -> None:
    if not _table_exists(LEGACY_DOCTYPE):
        return

    row_count = _count_rows(LEGACY_DOCTYPE)

    if row_count:
        frappe.throw(
            _(
                "Cannot drop {0} because it contains {1} row(s)."
            ).format(LEGACY_TABLE, row_count)
        )

    frappe.db.sql_ddl(f"DROP TABLE `{LEGACY_TABLE}`")


def execute() -> None:
    deleted_records = _assert_safe_to_cleanup()

    _delete_deleted_document_records(deleted_records)
    _delete_legacy_deleted_comments()
    _delete_legacy_series_history()
    _drop_empty_legacy_table()

    frappe.clear_cache()
