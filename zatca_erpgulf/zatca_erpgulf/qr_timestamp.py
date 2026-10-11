"""Compatibility ERP timezone adapter over the explicit issue-time contract."""

from datetime import datetime

from frappe import _
from frappe.utils import get_system_timezone

from zatca_erpgulf.zatca_erpgulf.issue_timestamp import (
    IssueTimestampError, issue_timestamp_from_datetime, parse_issue_datetime,
)


INVALID_FIELDS = "Invalid invoice issue date or time. Use a valid date and a time within the same day."
INVALID_TIMEZONE = "A valid system timezone is required to interpret the invoice issue time."
INVALID_DST = "Invoice issue time is ambiguous or does not exist in the configured timezone. Provide an explicit UTC offset."


def resolve_zatca_issue_timestamp(issue_date, issue_time):
    """Read configured timezone ONLY for naive fields; no default time/date.

    Explicit offsets/UTC never consult Company/site timezone. Invalid input and
    settings/parser failures are translated outside handlers without raw context.
    """
    message = INVALID_FIELDS
    try:
        value = parse_issue_datetime(issue_date, issue_time)
        message = INVALID_TIMEZONE
        zone = get_system_timezone() if value.tzinfo is None else None
        return issue_timestamp_from_datetime(value, timezone_name=zone)
    except IssueTimestampError as error:
        message = {"issue_fields": INVALID_FIELDS, "issue_timezone": INVALID_TIMEZONE, "issue_dst": INVALID_DST}[error.code]
    except Exception:
        pass
    raise ValueError(_(message))


def format_zatca_qr_timestamp(issue_date, issue_time) -> str:
    """Return the shared whole-second UTC value used by QR Tag 3 and XML."""
    return resolve_zatca_issue_timestamp(issue_date, issue_time).qr_value


def format_zatca_issue_datetime(issue_date, issue_time) -> datetime:
    """Preserve the compatibility API's aware UTC datetime result."""
    return resolve_zatca_issue_timestamp(issue_date, issue_time).utc_instant
