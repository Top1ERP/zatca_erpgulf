import frappe


PHASE_2_VALUE = "Phase-2"


def _as_doc(doc_or_name, doctype=None):
    if not doc_or_name:
        return None

    if hasattr(doc_or_name, "doctype"):
        return doc_or_name

    if doctype:
        return frappe.get_doc(doctype, doc_or_name)

    return None


def _resolve_source_company(source_doc=None):
    source_doc = _as_doc(source_doc)

    if source_doc and getattr(source_doc, "company", None):
        return frappe.get_doc("Company", source_doc.company)

    return None


def _resolve_company_for_pih_holder(holder_doc=None, source_doc=None):
    holder_doc = _as_doc(holder_doc)
    source_company = _resolve_source_company(source_doc)

    if source_company:
        return source_company

    if not holder_doc:
        return None

    if getattr(holder_doc, "doctype", None) == "Company":
        return holder_doc

    linked_company = getattr(holder_doc, "custom_linked_doctype", None)

    if linked_company and frappe.db.exists("Company", linked_company):
        return frappe.get_doc("Company", linked_company)

    return None


def is_phase_2_company(company_doc) -> bool:
    if not company_doc:
        return False

    return str(getattr(company_doc, "custom_phase_1_or_2", "") or "").strip() == PHASE_2_VALUE


def update_pih_after_phase2_success(holder_doc, encoded_hash, source_doc=None) -> dict:
    """
    Persist Previous Invoice Hash only for successful Phase-2 flows.

    Phase-1 is generation/store only in this app policy and must not move the
    stored PIH chain.
    """
    holder_doc = _as_doc(holder_doc)

    if not holder_doc:
        return {"updated": False, "reason": "missing_pih_holder"}

    if not encoded_hash:
        return {
            "updated": False,
            "reason": "missing_encoded_hash",
            "holder_doctype": getattr(holder_doc, "doctype", None),
            "holder_name": getattr(holder_doc, "name", None),
        }

    company_doc = _resolve_company_for_pih_holder(holder_doc, source_doc)

    if not company_doc:
        frappe.log_error(
            title="ZATCA PIH update skipped - company not resolved",
            message=f"Holder: {getattr(holder_doc, 'doctype', None)} {getattr(holder_doc, 'name', None)}",
        )
        return {
            "updated": False,
            "reason": "company_not_resolved",
            "holder_doctype": getattr(holder_doc, "doctype", None),
            "holder_name": getattr(holder_doc, "name", None),
        }

    if not is_phase_2_company(company_doc):
        return {
            "updated": False,
            "reason": "phase_1_or_not_phase_2",
            "company": company_doc.name,
            "phase": getattr(company_doc, "custom_phase_1_or_2", None),
            "holder_doctype": getattr(holder_doc, "doctype", None),
            "holder_name": getattr(holder_doc, "name", None),
        }

    old_pih = getattr(holder_doc, "custom_pih", None)

    if old_pih == encoded_hash:
        return {
            "updated": False,
            "reason": "pih_already_current",
            "company": company_doc.name,
            "holder_doctype": getattr(holder_doc, "doctype", None),
            "holder_name": getattr(holder_doc, "name", None),
        }

    holder_doc.custom_pih = encoded_hash
    holder_doc.save(ignore_permissions=True)

    return {
        "updated": True,
        "reason": "updated",
        "company": company_doc.name,
        "holder_doctype": getattr(holder_doc, "doctype", None),
        "holder_name": getattr(holder_doc, "name", None),
        "old_pih": old_pih,
        "new_pih": encoded_hash,
    }
