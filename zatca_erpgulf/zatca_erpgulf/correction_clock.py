"""Explicit replacement XML clock, independent of ERP posting/financial fields.

The caller supplies an aware server generation instant and authenticated original.
Reporting retains its original calendar date and uses the new UTC clock time;
Clearance uses the current UTC date/time. This is a deliberate correction policy,
not an ordinary invoice clock, automatic retry or accounting-date update.
"""

from datetime import datetime,timezone

from .issue_timestamp import IssueTimestamp,issue_timestamp_from_datetime,parse_issue_datetime
from .native_response import _original
from .qr_xml_contract import _clock


class CorrectionClockError(RuntimeError):
    def __init__(self,code):self.code=code;super().__init__(code)


def corrected_issue_timestamp(header,original,*,generation_instant):
    if type(generation_instant) is not datetime or generation_instant.tzinfo is None:
        raise CorrectionClockError('correction_clock_aware_server_time')
    now=issue_timestamp_from_datetime(generation_instant).utc_instant.replace(microsecond=0)
    xml,_evidence=_original(header,original)
    old=parse_issue_datetime(*_clock(xml))
    if old.tzinfo is None:raise CorrectionClockError('correction_clock_original_offset')
    if header['endpoint']=='invoices/reporting/single':
        selected=datetime.combine(old.date(),now.time(),tzinfo=timezone.utc)
    elif header['endpoint']=='invoices/clearance/single':selected=now
    else:raise CorrectionClockError('correction_clock_original_operation')
    if selected==old:raise CorrectionClockError('correction_clock_unchanged_second')
    return IssueTimestamp(selected)
