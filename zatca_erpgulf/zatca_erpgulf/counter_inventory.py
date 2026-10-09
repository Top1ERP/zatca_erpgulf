"""Read historical counter evidence without allocation, seeding, or credentials."""

import frappe

from zatca_erpgulf.zatca_erpgulf.history_evidence import compare_counter_evidence
from zatca_erpgulf.zatca_erpgulf.icv import _counter_key as legacy_counter_key


def read_invoice_counter_evidence(saved):
    """Inspect the saved unit's Production-purpose tuple and possible key collision.

    Do not derive an owner from current auth or silently choose the current
    Company/device pointer. Credential rotation may have changed those pointers.
    Two tuple matches suffice to flag ambiguity; this is not a full counter dump.
    """
    result = {
        "purpose": "Production", "api_environment": saved.environment,
        "expected_key": None, "issues": [], "candidates": [],
    }
    if not saved.issuing_unit.strip():
        result["issues"].append("saved_unit_missing")
        return result
    if not frappe.db.exists("DocType", "ZATCA ICV Counter"):
        result["issues"].append("counter_schema_missing")
        return result
    expected = legacy_counter_key(saved.company_name, saved.issuing_unit, "Production")
    result["expected_key"] = expected
    rows = frappe.get_all(
        "ZATCA ICV Counter",
        filters={"company": saved.company_name, "issuing_unit": saved.issuing_unit,
                 "environment": "Production"},
        fields=["name"], order_by="name asc", limit_page_length=2,
    )
    names = list(dict.fromkeys(row["name"] for row in rows))
    if len(names) > 1:
        result["issues"].append("counter_tuple_ambiguous")
    # The historical name can collide even when the tuple search has no match.
    if expected not in names and frappe.db.exists("ZATCA ICV Counter", expected):
        names.append(expected)
    if not names:
        result["issues"].append("counter_missing")
        return result
    for name in names:
        candidate = {"counter": name, "issues": []}
        try:
            counter = frappe.get_doc("ZATCA ICV Counter", name)
            counter.check_permission("read")
            values = {key: counter.get(key) for key in (
                "name", "company", "issuing_unit", "environment", "counter_key",
                "active", "last_issued_icv", "last_invoice", "last_invoice_doctype",
            )}
            candidate.update(
                company=values["company"], issuing_unit=values["issuing_unit"],
                purpose=values["environment"], counter_key=values["counter_key"],
                active=values["active"], last_invoice=values["last_invoice"],
                last_invoice_doctype=values["last_invoice_doctype"],
                last_issued_icv=str(values["last_issued_icv"]),
                issues=list(compare_counter_evidence(saved, values, expected)),
            )
        except frappe.PermissionError:
            candidate["issues"] = ["counter_permission"]
        except frappe.DoesNotExistError:
            candidate["issues"] = ["counter_record_missing"]
        result["candidates"].append(candidate)
    return result
