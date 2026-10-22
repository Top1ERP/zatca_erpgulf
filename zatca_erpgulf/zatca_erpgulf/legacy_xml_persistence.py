"""Existing-XML response writes, NOT atomic custody or acceptance evidence.

Reviewed server code supplies its current Frappe-compatible runtime and a fixed
policy. This is not an endpoint, permission grant, setting resolver or retry path.
Keep this I/O adapter separate from the transaction-free response-step guard.
"""


def persist_existing_xml_rejection(runtime, invoice_doctype, invoice_number, response, *, commit_uuid):
    """Preserve legacy ordering; call ONLY through the received-response guard.

    The two simplified paths usually commit the UUID placeholder independently;
    Sales simplified 404 and both machine paths use an ordinary assignment.
    This difference is an explicit code policy, never a browser/Company option.

    Load, raw text read, save and final commit errors must propagate to the guard.
    Prior UUID/hook/commit effects and mutated objects are not undone. The caller
    retains originals and owns pending cleanup; no fallback or replay is added.
    Deliberate HTTP-rejection throws belong outside this persistence callback.
    """
    if (type(invoice_doctype) is not str or invoice_doctype not in ("Sales Invoice", "POS Invoice")
            or type(commit_uuid) is not bool):
        raise ValueError("legacy_xml_rejection_policy")
    invoice_doc = runtime.get_doc(invoice_doctype, invoice_number)
    if commit_uuid:
        invoice_doc.db_set("custom_uuid", "Not Submitted", commit=True, update_modified=True)
    else:
        invoice_doc.custom_uuid = "Not Submitted"
    invoice_doc.custom_zatca_status = "Not Submitted"
    invoice_doc.custom_zatca_full_response = response.text
    invoice_doc.save(ignore_permissions=True)
    runtime.db.commit()


def persist_existing_xml_reported(runtime, invoice_doctype, invoice_number, response, uuid):
    """Preserve the legacy REPORTED-labelled write; call through the step guard.

    The existing caller selects 200/202/409 branches and updates its pinned owner
    first. This helper does not validate authority acceptance, select credentials
    or modify PIH/ICV. Keep raw text -> UUID -> status -> save -> commit ordering.
    Save/hook/commit effects may precede failure and are not compensated here.
    """
    if type(invoice_doctype) is not str or invoice_doctype not in ("Sales Invoice", "POS Invoice"):
        raise ValueError("legacy_xml_reported_policy")
    invoice_doc = runtime.get_doc(invoice_doctype, invoice_number)
    invoice_doc.custom_zatca_full_response = response.text
    invoice_doc.custom_uuid = uuid
    invoice_doc.custom_zatca_status = "REPORTED"
    invoice_doc.save(ignore_permissions=True)
    runtime.db.commit()
