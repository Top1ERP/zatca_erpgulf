from __future__ import annotations

import frappe


OLD_WORKSPACE = "ZATCA ERPGulf"
NEW_WORKSPACE = "ZATCA"


def _replace_value(value):
    if isinstance(value, str):
        return value.replace(OLD_WORKSPACE, NEW_WORKSPACE)
    return value


def _replace_doc_strings(doc) -> None:
    meta = doc.meta

    for df in meta.fields:
        if df.fieldtype in {"Data", "Small Text", "Text", "Long Text", "Code", "HTML"}:
            current = doc.get(df.fieldname)
            new_value = _replace_value(current)
            if new_value != current:
                doc.set(df.fieldname, new_value)

        elif df.fieldtype == "Table":
            for row in doc.get(df.fieldname) or []:
                for cdf in row.meta.fields:
                    if cdf.fieldtype in {"Data", "Small Text", "Text", "Long Text", "Code", "HTML"}:
                        current = row.get(cdf.fieldname)
                        new_value = _replace_value(current)
                        if new_value != current:
                            row.set(cdf.fieldname, new_value)


@frappe.whitelist()
def rename_zatca_workspace() -> dict:
    """Rename the visible workspace from 'ZATCA ERPGulf' to 'ZATCA'.

    Keeps the technical module name unchanged: Zatca Erpgulf.
    Safe behavior:
    - If old exists and new does not, rename old to new.
    - If new already exists and old does not, normalize new.
    - If both exist, stop to avoid accidental merge/deletion.
    """

    old_exists = frappe.db.exists("Workspace", OLD_WORKSPACE)
    new_exists = frappe.db.exists("Workspace", NEW_WORKSPACE)

    result = {
        "old_workspace": OLD_WORKSPACE,
        "new_workspace": NEW_WORKSPACE,
        "old_exists_before": bool(old_exists),
        "new_exists_before": bool(new_exists),
        "actions": [],
    }

    if old_exists and new_exists:
        frappe.throw(
            f"Both Workspace records exist: '{OLD_WORKSPACE}' and '{NEW_WORKSPACE}'. "
            "Resolve manually before running this tool."
        )

    if old_exists and not new_exists:
        frappe.rename_doc(
            "Workspace",
            OLD_WORKSPACE,
            NEW_WORKSPACE,
            force=True,
        )
        result["actions"].append("renamed_workspace")

    if frappe.db.exists("Workspace", NEW_WORKSPACE):
        ws = frappe.get_doc("Workspace", NEW_WORKSPACE)

        ws.label = NEW_WORKSPACE
        ws.title = NEW_WORKSPACE

        _replace_doc_strings(ws)

        if ws.get("content"):
            ws.content = ws.content.replace(OLD_WORKSPACE, NEW_WORKSPACE)

        ws.save(ignore_permissions=True)
        result["actions"].append("normalized_workspace_fields")

    frappe.db.commit()
    frappe.clear_cache()

    result["old_exists_after"] = bool(frappe.db.exists("Workspace", OLD_WORKSPACE))
    result["new_exists_after"] = bool(frappe.db.exists("Workspace", NEW_WORKSPACE))

    return result
