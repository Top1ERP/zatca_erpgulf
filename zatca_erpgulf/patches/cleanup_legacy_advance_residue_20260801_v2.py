from __future__ import annotations

import frappe

from zatca_erpgulf.patches.remove_legacy_advance_doctype_20260801 import (
    LEGACY_DOCTYPE,
    OBSOLETE_CUSTOM_FIELDS,
    OBSOLETE_DATABASE_COLUMNS,
    _drop_column,
)


# Only translations uniquely identifying the retired DocType or its obsolete
# custom fields may be removed. Generic UI, validation, ZATCA, Payment Entry,
# and advance-reversal translations are intentionally preserved because
# Translation records are global per language and may serve other workflows.
LEGACY_TRANSLATION_SOURCE_TEXTS = {
    "ZATCA Advance Tax Invoice behavior",
    "ZATCA Advance Payment Enabled",
    "ZATCA Advance Payment Submission Mode",
    "ZATCA Advance Default Terms and Conditions",
    "ZATCA Advance Signing Enabled",
    "ZATCA Advance API Submission Enabled",
    "ZATCA Advance Payment",
    "Is ZATCA Advance Payment",
    "ZATCA Advance Invoice Status",
    "ZATCA Advance Invoice UUID",
    "ZATCA Advance QR Code",
    "ZATCA Advance XML",
    "ZATCA Advance Last Debug At",
    "ZATCA Advance Full Response",
    "Open Advance Tax Invoice",
    "Finalize this advance tax invoice and generate the Phase 1 QR Code?",
}

LEGACY_TRANSLATION_EXACT_TRANSLATED_TEXTS = {
    "فاتورة الدفعة المقدمة - زاتكا",
}


def _delete_docs(doctype: str, filters: dict) -> None:
    for name in frappe.get_all(doctype, filters=filters, pluck="name"):
        frappe.delete_doc(
            doctype,
            name,
            ignore_permissions=True,
            force=True,
        )


def _is_legacy_translation(source_text: str, translated_text: str) -> bool:
    source_text = str(source_text or "")
    translated_text = str(translated_text or "")

    return (
        source_text in LEGACY_TRANSLATION_SOURCE_TEXTS
        or LEGACY_DOCTYPE in source_text
        or translated_text in LEGACY_TRANSLATION_EXACT_TRANSLATED_TEXTS
    )


def get_legacy_translation_candidates() -> list[dict]:
    rows = frappe.get_all(
        "Translation",
        filters={"language": "ar"},
        fields=["name", "source_text", "translated_text"],
        limit_page_length=0,
    )

    return [
        {
            "name": row.name,
            "source_text": row.source_text,
            "translated_text": row.translated_text,
        }
        for row in rows
        if _is_legacy_translation(row.source_text, row.translated_text)
    ]


def _delete_legacy_translations() -> None:
    for row in get_legacy_translation_candidates():
        frappe.delete_doc(
            "Translation",
            row["name"],
            ignore_permissions=True,
            force=True,
        )


def execute() -> None:
    for doctype, fieldnames in OBSOLETE_CUSTOM_FIELDS.items():
        for fieldname in fieldnames:
            _delete_docs(
                "Property Setter",
                {"doc_type": doctype, "field_name": fieldname},
            )
            _delete_docs(
                "Custom Field",
                {"dt": doctype, "fieldname": fieldname},
            )

    _delete_docs("Property Setter", {"doc_type": LEGACY_DOCTYPE})
    _delete_docs("Custom Field", {"dt": LEGACY_DOCTYPE})

    for doctype, fieldnames in OBSOLETE_DATABASE_COLUMNS.items():
        for fieldname in fieldnames:
            _drop_column(doctype, fieldname)

    _delete_legacy_translations()

    for doctype in (
        *OBSOLETE_CUSTOM_FIELDS,
        "ZATCA Sales Invoice Advance Deduction",
        LEGACY_DOCTYPE,
        "Translation",
    ):
        frappe.clear_cache(doctype=doctype)
