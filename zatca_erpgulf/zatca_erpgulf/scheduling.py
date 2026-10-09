"""Site-free scheduling rules shared by Sales and POS background workers.

Windows are inclusive and may cross midnight. A missing window is disabled;
a partially configured or malformed window is an error, not permission to send.
"""

from datetime import datetime, time, timedelta


WINDOW_FIELDS = (
    ("custom_start_time", "custom_end_time"),
    ("custom_start_time_session", "custom_end_time_session"),
)
PENDING_STATUSES = ("Not Submitted", "503 Service Unavailable")


def convert_to_time(value):
    """Accept Frappe Time values without silently wrapping invalid durations."""
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise ValueError("Schedule times must use the site's local clock.")
        return value
    if isinstance(value, timedelta):
        if not timedelta(0) <= value < timedelta(days=1):
            raise ValueError("Schedule durations must be within a single day.")
        return (datetime.min + value).time()
    if isinstance(value, str):
        for pattern in ("%H:%M:%S", "%H:%M:%S.%f"):
            try:
                return datetime.strptime(value.strip(), pattern).time()
            except ValueError:
                continue
    raise ValueError("Unsupported schedule time; use HH:MM:SS or a Frappe Time value.")


def is_time_in_range(start, end, current):
    """Include both boundaries, including for a window crossing midnight."""
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _missing(value):
    # Midnight represented by timedelta(0) is a valid boundary, not missing.
    return value is None or (isinstance(value, str) and not value.strip())


def is_within_company_windows(company, current):
    """Validate both windows before deciding whether either permits this run."""
    windows = []
    for start_field, end_field in WINDOW_FIELDS:
        start, end = company.get(start_field), company.get(end_field)
        if _missing(start) and _missing(end):
            continue
        if _missing(start) or _missing(end):
            raise ValueError(f"Both {start_field} and {end_field} must be configured.")
        windows.append((convert_to_time(start), convert_to_time(end)))
    return any(is_time_in_range(start, end, current) for start, end in windows)


def is_pending_invoice(invoice):
    """Recheck the saved record; the discovery query may already be stale."""
    return (
        invoice.get("docstatus") in (0, 1)
        and invoice.get("custom_zatca_status") in PENDING_STATUSES
    )
