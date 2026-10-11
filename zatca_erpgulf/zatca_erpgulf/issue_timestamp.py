"""Explicit invoice issue-time contract, independent of Frappe/site/clock.

Accept ERP date/time objects and bounded text; never infer today, midnight or a
server timezone. Naive values require an explicit IANA timezone. DST gaps/folds
fail closed unless the source already supplies an offset/aware instant. Local
timezone data is supplied by the existing pytz dependency; no remote lookup.
This normalizes time only, not invoice/credential/transport provenance.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import pytz


class IssueTimestampError(ValueError):
    """Static code only; never include invoice input or timezone parser details."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def parse_issue_datetime(issue_date, issue_time):
    """Parse exact clock fields without defaults or timezone discovery.

    MariaDB TIME durations must be within the SAME day, including zero. String
    hours may have one digit; minutes/seconds have two. Existing minute-only
    values remain supported. Fractions are bounded to six microsecond digits.
    """
    try:
        if type(issue_date) is str:
            if len(issue_date) > 32:
                raise IssueTimestampError("issue_fields")
            value = issue_date.strip()
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
                raise IssueTimestampError("issue_fields")
            issue_date = date.fromisoformat(value)
        if type(issue_date) is not date:
            raise IssueTimestampError("issue_fields")
        if type(issue_time) is timedelta:
            if not timedelta(0) <= issue_time < timedelta(days=1):
                raise IssueTimestampError("issue_fields")
            issue_time = (datetime.combine(issue_date, time()) + issue_time).time()
        elif type(issue_time) is str:
            if len(issue_time) > 64:
                raise IssueTimestampError("issue_fields")
            value = issue_time.strip()
            if (len(value) > 32 or re.fullmatch(
                    r"[0-9]{1,2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?", value) is None):
                raise IssueTimestampError("issue_fields")
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            hour, tail = value.split(":", 1)
            # fromisoformat normalizes offset minutes >=60; reject instead.
            offset = re.search(r"[+-]([0-9]{2}):([0-9]{2})$", value)
            if offset and (int(offset[1]) > 23 or int(offset[2]) > 59):
                raise IssueTimestampError("issue_fields")
            issue_time = time.fromisoformat(hour.zfill(2) + ":" + tail)
        if type(issue_time) is not time:
            raise IssueTimestampError("issue_fields")
        return datetime.combine(issue_date, issue_time)
    except (ValueError, TypeError, OverflowError):
        invalid = True
    if invalid:
        raise IssueTimestampError("issue_fields")


@dataclass(frozen=True)
class IssueTimestamp:
    """One UTC instant supplies QR Tag 3 AND XML date/time, at whole seconds.

    Retain microseconds in memory, truncate (never round) on serialization, as
    the existing QR/XML wrappers did. Do not rewrite an already issued artifact.
    """

    utc_instant: datetime

    def __post_init__(self):
        if type(self.utc_instant) is not datetime or self.utc_instant.tzinfo is not timezone.utc:
            raise IssueTimestampError("issue_instant")

    @property
    def qr_value(self):
        value = self.utc_instant
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}T{value.hour:02d}:{value.minute:02d}:{value.second:02d}Z"

    @property
    def xml_date(self):
        return self.qr_value.split("T", 1)[0]

    @property
    def xml_time(self):
        return self.qr_value.split("T", 1)[1]


def issue_timestamp_from_datetime(value, *, timezone_name=None):
    """Normalize an explicit datetime; an aware source never uses a fallback."""
    try:
        if type(value) is not datetime:
            raise IssueTimestampError("issue_fields")
        if value.tzinfo is None:
            if type(timezone_name) is not str or len(timezone_name) > 255 or timezone_name not in pytz.all_timezones_set:
                raise IssueTimestampError("issue_timezone")
            try:
                value = pytz.timezone(timezone_name).localize(value, is_dst=None)
            except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
                raise IssueTimestampError("issue_dst") from None
        if value.utcoffset() is None:
            raise IssueTimestampError("issue_timezone")
        return IssueTimestamp(value.astimezone(timezone.utc))
    except IssueTimestampError as error:
        code = error.code
    except (ValueError, TypeError, OverflowError):
        code = "issue_fields"
    raise IssueTimestampError(code)


def resolve_issue_timestamp(issue_date, issue_time, *, timezone_name=None):
    """Explicit-input entry point; no ERP/database/clock/default discovery."""
    return issue_timestamp_from_datetime(parse_issue_datetime(issue_date, issue_time), timezone_name=timezone_name)
