"""Diagnostic event writes, not authority receipt custody or acceptance evidence.

The explicit staging entry point leaves transaction policy to its caller. The
legacy wrapper retains its ambient commit/fallback policy until whole-caller
receipt retention and transaction lifecycle can be migrated safely.
"""

from enum import Enum

from frappe.utils import now_datetime
import frappe

from zatca_erpgulf.zatca_erpgulf.zatca_response import extract_raw_response


class EventLogWriteResult(Enum):
    """Only the insert call returned; no durable/accepted/success assertion."""

    INSERT_RETURNED = "INSERT_RETURNED"


def _insert_zatca_event(invoice_number, response_text, status, uuid, title, *, ignore_permissions):
    """Share the legacy payload/normalizer without owning transaction policy."""
    event_doc = frappe.get_doc({
        "doctype": "ZATCA ERPGulf Event Log",
        "title": title or f"ZATCA API Call for {invoice_number}",
        "invoice_number": invoice_number,
        "time": now_datetime(),
        # Diagnostic normalization is NOT exact-byte encrypted receipt custody.
        "api_response": extract_raw_response(response_text),
        "custom_uuid": uuid or "",
        "status": status,
    })
    event_doc.insert(ignore_permissions=ignore_permissions)


def stage_zatca_event(invoice_number, response_text, status, uuid=None, title=None):
    """Insert a diagnostic log with normal permissions and caller-owned SQL.

    No commit, rollback, fallback log, retry, permission override or exception
    translation is performed here. Every error, including permission denial,
    propagates unchanged. Call inside the received-step guard when appropriate;
    do not let a legacy generic handler label local failure as remote rejection.

    INSERT_RETURNED distinguishes this contract from the legacy None return. It
    proves neither durability nor authority acceptance, exact receipt retention,
    schema completeness or absence of hook side effects. The caller must retain
    the original response and own pending work/failed transaction cleanup. This
    entry point is intentionally not wired into existing invoice submission.
    """
    _insert_zatca_event(invoice_number, response_text, status, uuid, title, ignore_permissions=False)
    return EventLogWriteResult.INSERT_RETURNED


def log_zatca_event(invoice_number, response_text, status, uuid=None, title=None):
    """Legacy compatibility: ambient commit, ignored permissions, None/fallback.

    Do not reinterpret None as success or failure. Keep this policy separate
    from staging until caller transaction/receipt retention migration is ready.
    """
    try:
        _insert_zatca_event(invoice_number, response_text, status, uuid, title, ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to log ZATCA Event: {str(e)}", "ZATCA Event Log")
