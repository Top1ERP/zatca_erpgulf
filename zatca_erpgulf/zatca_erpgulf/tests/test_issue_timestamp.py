"""Explicit time normalization only; no Frappe/site/clock/network dependencies."""

import importlib
import sys
from dataclasses import FrozenInstanceError
from datetime import date, datetime, time, timedelta, timezone

import pytest

from zatca_erpgulf.zatca_erpgulf.issue_timestamp import (
    IssueTimestamp, IssueTimestampError, issue_timestamp_from_datetime,
    parse_issue_datetime, resolve_issue_timestamp,
)


@pytest.mark.parametrize("day", ["2026-09-27", date(2026, 9, 27), " 2026-09-27 "])
@pytest.mark.parametrize("clock", ["9:05:42", "09:05:42", "09:05:42.123456", time(9, 5, 42),
    time(9, 5, 42, 123456), timedelta(hours=9, minutes=5, seconds=42), timedelta(hours=9, minutes=5, seconds=42, microseconds=123456)])
def test_supported_erp_types_share_one_whole_second_instant(day, clock):
    stamp = resolve_issue_timestamp(day, clock, timezone_name="Asia/Riyadh")
    assert stamp.qr_value == "2026-09-27T06:05:42Z"
    assert stamp.xml_date + "T" + stamp.xml_time == stamp.qr_value
    assert stamp.utc_instant.tzinfo is timezone.utc


@pytest.mark.parametrize("clock", [timedelta(0), time(0, 0), "0:00:00", "00:00", "00:00:00.000000"])
def test_midnight_is_a_real_value_not_missing(clock):
    stamp = resolve_issue_timestamp(date(2026, 1, 1), clock, timezone_name="Asia/Riyadh")
    assert stamp.xml_date == "2025-12-31" and stamp.xml_time == "21:00:00Z"


@pytest.mark.parametrize("clock,expected", [
    ("9:05:42Z", "2026-09-27T09:05:42Z"),
    ("09:05:42+03:00", "2026-09-27T06:05:42Z"),
    ("09:05:42-03:30", "2026-09-27T12:35:42Z"),
    (time(9, 5, 42, tzinfo=timezone(timedelta(hours=3))), "2026-09-27T06:05:42Z"),
    ("23:59:59-02:00", "2026-09-28T01:59:59Z"),
    ("00:00:00+14:00", "2026-09-26T10:00:00Z"),
])
@pytest.mark.parametrize("ignored_zone", [None, "Asia/Riyadh", "PRIVATE-INVALID-TIMEZONE", object()])
def test_explicit_offset_defines_the_instant_without_a_fallback(clock, expected, ignored_zone):
    assert resolve_issue_timestamp("2026-09-27", clock, timezone_name=ignored_zone).qr_value == expected


@pytest.mark.parametrize("zone,day,clock,expected", [
    ("UTC", "2026-09-27", "9:05", "2026-09-27T09:05:00Z"),
    ("Asia/Kathmandu", "2026-09-27", "9:05:42", "2026-09-27T03:20:42Z"),
    ("Europe/Berlin", "2026-01-01", "9:05:42", "2026-01-01T08:05:42Z"),
    ("Europe/Berlin", "2026-07-01", "9:05:42", "2026-07-01T07:05:42Z"),
    ("America/New_York", "2026-07-01", "23:59:59.999999", "2026-07-02T03:59:59Z"),
])
def test_configured_zones_and_fraction_truncation(zone, day, clock, expected):
    assert resolve_issue_timestamp(day, clock, timezone_name=zone).qr_value == expected


@pytest.mark.parametrize("day,clock", [("2026-03-29", "02:30:00"), ("2026-10-25", "02:30:00")])
def test_dst_gap_and_fold_require_explicit_offset(day, clock):
    with pytest.raises(IssueTimestampError, match="^issue_dst$") as error:
        resolve_issue_timestamp(day, clock, timezone_name="Europe/Berlin")
    assert error.value.__context__ is None


@pytest.mark.parametrize("offset,expected", [("+02:00", "2026-10-25T00:30:00Z"), ("+01:00", "2026-10-25T01:30:00Z")])
def test_explicit_offsets_disambiguate_a_fold(offset, expected):
    assert resolve_issue_timestamp("2026-10-25", "02:30:00" + offset).qr_value == expected


@pytest.mark.parametrize("day", [None, "", False, 0, 20260927, b"2026-09-27", datetime(2026, 9, 27),
    "2026-02-29", "2026-09-31", "20260927", "2026-W39-7", "2026-09-27T09:05:42", "PRIVATE-RAW-INPUT", " " * 1000])
def test_bad_dates_never_infer_today_or_export_the_input(day):
    with pytest.raises(IssueTimestampError, match="^issue_fields$") as error:
        resolve_issue_timestamp(day, "9:05:42", timezone_name="UTC")
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("clock", [None, "", False, 0, 9, 9.5, b"09:05:42", datetime(2026, 9, 27, 9, 5, 42),
    timedelta(days=1), timedelta(days=-1), timedelta(microseconds=-1), timedelta(hours=25), "24:00:00", "9:60:00",
    "9:05:60", "9:5:42", "09", "090542", "9:05:42.1234567", "9:05:42,1", "9:05:42+03:60", "9:05:42+24:00",
    "9:05:42+0300", "9:05:42+03:00:30", "9:05:42z", "9:05:42Zsuffix", "PRIVATE-RAW-INPUT", " " * 1000])
def test_invalid_clock_fields_never_wrap_days_or_invent_midnight(clock):
    with pytest.raises(IssueTimestampError, match="^issue_fields$") as error:
        resolve_issue_timestamp("2026-09-27", clock, timezone_name="UTC")
    assert error.value.__context__ is None


@pytest.mark.parametrize("zone", [None, "", "PRIVATE-UNKNOWN", " UTC", "UTC ", "../UTC", 0, False, object(), "Z" * 256])
def test_naive_values_need_an_explicit_valid_zone(zone):
    with pytest.raises(IssueTimestampError, match="^issue_timezone$") as error:
        resolve_issue_timestamp("2026-09-27", "9:05:42", timezone_name=zone)
    assert error.value.__context__ is None


@pytest.mark.parametrize("day,clock", [("0001-01-01", "00:00:00+03:00"), ("9999-12-31", "23:59:59-03:00")])
def test_utc_date_overflow_is_a_static_failure(day, clock):
    with pytest.raises(IssueTimestampError, match="^issue_fields$"):
        resolve_issue_timestamp(day, clock)


def test_low_year_formatting_and_frozen_utc_contract():
    stamp = resolve_issue_timestamp("0009-01-01", "00:00:00Z")
    assert stamp.qr_value == "0009-01-01T00:00:00Z"
    with pytest.raises(FrozenInstanceError):
        stamp.utc_instant = datetime.now(timezone.utc)
    for value in (None, datetime(2026, 9, 27), datetime(2026, 9, 27, tzinfo=timezone(timedelta(hours=3)))):
        with pytest.raises(IssueTimestampError, match="issue_instant"):
            IssueTimestamp(value)


def test_core_import_and_explicit_input_do_not_need_frappe_or_system_clock(monkeypatch):
    monkeypatch.setitem(sys.modules, "frappe", None)
    monkeypatch.setitem(sys.modules, "frappe.utils", None)
    module = importlib.import_module("zatca_erpgulf.zatca_erpgulf.issue_timestamp")
    assert "frappe" not in module.__dict__ and "get_system_timezone" not in module.__dict__
    assert module.resolve_issue_timestamp("2026-09-27", "9:05:42Z").qr_value == "2026-09-27T09:05:42Z"
    assert parse_issue_datetime("2026-09-27", timedelta(0)) == datetime(2026, 9, 27)


@pytest.mark.parametrize("value", [None, 0, "2026-09-27T09:05:42Z", date(2026, 9, 27)])
def test_datetime_normalizer_does_not_accept_implicit_clock_inputs(value):
    with pytest.raises(IssueTimestampError, match="issue_fields"):
        issue_timestamp_from_datetime(value)
