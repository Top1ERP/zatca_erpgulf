"""Diagnostic event writes, not authority receipt custody or acceptance evidence.

The explicit staging entry point leaves transaction policy to its caller. The
legacy wrapper retains its ambient commit/fallback policy until whole-caller
receipt retention and transaction lifecycle can be migrated safely.
"""

from enum import Enum
from werkzeug.local import LocalProxy

from frappe.utils import now_datetime
import frappe
from frappe import _

from zatca_erpgulf.zatca_erpgulf.zatca_response import extract_raw_response
from .primary_capture import PrimaryCaptureRequest
from .primary_receipt_custody import PrimaryReceiptCustodyCipher, SealedPrimaryReceipt
from .primary_receipt_reconciliation import PrimaryReceiptReconciliation, PrimaryReconciliationResult


EVENT_LOG_DOCTYPE = "ZATCA ERPGulf Event Log"
EVENT_LOG_SCHEMA_REVIEW = "ZATCA event log schema requires review. No diagnostic event was inserted."
RETAINED_EVENT_REVIEW = "Retained ZATCA response requires custody review. No diagnostic event was inserted and no request was sent."
RETAINED_EVENT_TITLE = "Retained ZATCA response diagnostic"
RETAINED_EVENT_STATUS = "HTTP {0} (retained observation)"
EVENT_LOG_SOURCE_REVIEW = "Diagnostic source access changed. Review the retained response and any staged event before trying again."
EVENT_LOG_PARENT_REVIEW = "Diagnostic database context changed or is unavailable. Review the retained response and any staged event. Do not resend automatically."
EVENT_LOG_FIELD_TYPES = {
    "title": "Data", "invoice_number": "Data", "time": "Data",
    "api_response": "Long Text", "custom_uuid": "Data", "status": "Data",
}


class EventLogSchemaError(RuntimeError):
    """Static translated metadata failure, not a remote rejection or repair."""


class RetainedEventLogError(RuntimeError):
    """Exact pair/decoding review; no raw protected input or action capability."""


class EventLogSourceError(RuntimeError):
    """A late source check may follow insertion; never claim nothing was written."""


class EventLogParentError(RuntimeError):
    """Observed caller-handle drift, not a rollback or authority rejection."""


def _event_parent_identity():
    """Resolve the current owner, not the stable context-local proxy object.

    Read only: never initialize/connect, query, commit, rollback or close the
    caller's database. Unknown/lazy contexts must be reviewed, not repaired.
    """
    parent = frappe.db
    if issubclass(type(parent), LocalProxy):
        parent = parent._get_current_object()
    raw = getattr(parent, "_conn", None)
    if parent is None or raw is None:
        raise ValueError("event_log_parent_unavailable")
    return parent, raw


def _pin_event_parent():
    """Observe owner/raw identity at explicit boundaries, NOT a SQL sandbox.

    Identical handles do not prove an unchanged transaction: hooks can commit,
    rollback, write or temporarily switch and restore the context between checks.
    The caller still owns pending/uncertain work and exact original custody.
    """
    try:
        parent, raw = _event_parent_identity()
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise EventLogParentError(_(EVENT_LOG_PARENT_REVIEW))

    def check():
        try:
            current, connection = _event_parent_identity()
            valid = current is parent and connection is raw
        except Exception:
            valid = False
        if not valid:
            raise EventLogParentError(_(EVENT_LOG_PARENT_REVIEW))
        return True
    return check


def _recheck_event_source(check):
    if check is not None and (not callable(check) or check() is not True):
        raise EventLogSourceError(_(EVENT_LOG_SOURCE_REVIEW))


def require_event_log_schema(meta):
    """Read caller-loaded ORM metadata; never migrate, rename or discard fields.

    Enforce the six diagnostic payload fields and ordinary table storage before
    staging. This is NOT physical-column synchronization, installed-version
    attestation, field collision resolution or a guarantee against hook writes.
    Narrowed Data fields, fetched/virtual values and incompatible types require
    explicit migration review rather than silent loss/coercion of diagnostic data.
    """
    try:
        if meta.name != EVENT_LOG_DOCTYPE or any(meta.get(flag) not in (None, 0, False)
                for flag in ("issingle", "istable", "is_virtual")):
            raise ValueError
        fields = meta.get("fields")
        if type(fields) not in (list, tuple):
            raise ValueError
        for name, fieldtype in EVENT_LOG_FIELD_TYPES.items():
            if sum(field.fieldname == name for field in fields) != 1:
                raise ValueError
            field = meta.get_field(name)
            if (field is None or field.fieldname != name or field.fieldtype != fieldtype
                    or field.get("is_virtual") not in (None, 0, False)
                    or field.get("fetch_from")):
                raise ValueError
            if fieldtype == "Data":
                length = field.get("length")
                if length not in (None, 0):
                    if type(length) is not int or length < 140:
                        raise ValueError
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        # Outside the metadata exception handler: no raw field/site/driver data.
        raise EventLogSchemaError(_(EVENT_LOG_SCHEMA_REVIEW))


class EventLogWriteResult(Enum):
    """Only the insert call returned; no durable/accepted/success assertion."""

    INSERT_RETURNED = "INSERT_RETURNED"


def _insert_zatca_event(invoice_number, response_text, status, uuid, title, *, ignore_permissions, source_recheck=None):
    """Share the legacy payload/normalizer without owning transaction policy."""
    event_doc = frappe.get_doc({
        "doctype": EVENT_LOG_DOCTYPE,
        "title": title or f"ZATCA API Call for {invoice_number}",
        "invoice_number": invoice_number,
        "time": now_datetime(),
        # Diagnostic normalization is NOT exact-byte encrypted receipt custody.
        "api_response": extract_raw_response(response_text),
        "custom_uuid": uuid or "",
        "status": status,
    })
    _recheck_event_source(source_recheck)
    event_doc.insert(ignore_permissions=ignore_permissions)
    _recheck_event_source(source_recheck)


def stage_zatca_event(invoice_number, response_text, status, uuid=None, title=None, *, source_recheck=None):
    """Insert a diagnostic log with normal permissions and caller-owned SQL.

    No commit, rollback, fallback log, retry, permission override or exception
    translation is performed for insertion errors. A read-only metadata preflight
    fails with a static translated schema error before payload construction;
    other errors, including permission denial, propagate unchanged. Call inside
    the received-step guard when appropriate;
    do not let a legacy generic handler label local failure as remote rejection.

    INSERT_RETURNED distinguishes this contract from the legacy None return. It
    proves neither durability nor authority acceptance, exact receipt retention,
    schema completeness or absence of hook side effects. The caller must retain
    the original response and own pending work/failed transaction cleanup. This
    entry point is intentionally not wired into existing invoice submission.
    An optional trusted source callback must return literal True immediately
    before/after insertion. Its own effects are not sandboxed; late denial does
    not undo an insert/hook commit. No callback is inferred from browser input.

    An existing caller database owner/raw handle is pinned before metadata is
    loaded and rechecked around source callbacks and insertion. Observed context
    drift fails with static translated review, never parent cleanup/reconnect.
    This does not detect same-handle commits or guarantee hook/transaction isolation.
    """
    parent_check = _pin_event_parent()
    require_event_log_schema(frappe.get_meta(EVENT_LOG_DOCTYPE))
    parent_check()
    def source_and_parent_check():
        parent_check()
        _recheck_event_source(source_recheck)
        parent_check()
        return True
    _insert_zatca_event(invoice_number, response_text, status, uuid, title,
        ignore_permissions=False, source_recheck=source_and_parent_check)
    return EventLogWriteResult.INSERT_RETURNED


def stage_retained_primary_event(request, sealed, *, reconciliation, cipher, source_recheck=None):
    """Stage diagnostics ONLY after inspecting the exact original stored pair.

    Internal server-only adapter, NOT an endpoint or permission grant. Supply
    authorized saved-source guards, independently owned SQL and custody keys;
    dependency provenance is not attested here. Never supply a free-form response
    body, status/UUID or a caller-declared "stored" Boolean instead of inspection.

    Pair inspection rolls back/closes its owned transaction before diagnostic
    hooks run in the caller's ambient transaction. It never persists/repairs a
    missing pair. This observes a match at inspection time, not permanent custody
    or authority acceptance. Keep the ORIGINAL request/envelope on every outcome.
    Diagnostics may normalize text; invalid UTF-8 requires review, not replacement
    or resealing. Insertion errors propagate for the explicit received-step guard.
    No replay hold release, HTTP, retry, PIH/ICV or invoice mutation is added.
    """
    try:
        if (type(request) is not PrimaryCaptureRequest or type(sealed) is not SealedPrimaryReceipt
                or type(reconciliation) is not PrimaryReceiptReconciliation
                or type(cipher) is not PrimaryReceiptCustodyCipher):
            raise ValueError
        receipt = cipher.open(sealed)
        if receipt.before != request.started or receipt.storage_namespace != sealed.storage_namespace:
            raise ValueError
        inspected = reconciliation.inspect(request, sealed)
        if (type(inspected) is not PrimaryReconciliationResult
                or inspected.state != "PAIR_MATCHED_OBSERVATION_NO_REPLAY"
                or inspected.request != request or inspected.sealed != sealed):
            raise ValueError
        # Decryption/authentication and exact request checks are repeated after
        # the owned read finishes; no plaintext is taken from diagnostic fields.
        checked = cipher.open(sealed)
        if checked != receipt or checked.before != request.started:
            raise ValueError
        text = checked.response_event.response_bytes.decode("utf-8", errors="strict")
        invoice = checked.before.candidate.context.scope.invoice_name
        uuid = checked.before.candidate.artifact.uuid
        status = checked.response_event.http_status
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise RetainedEventLogError(_(RETAINED_EVENT_REVIEW))
    # Stored diagnostics are canonical English; localize labels only in a view.
    return stage_zatca_event(invoice, text, RETAINED_EVENT_STATUS.format(status),
        uuid=uuid, title=RETAINED_EVENT_TITLE, source_recheck=source_recheck)


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
