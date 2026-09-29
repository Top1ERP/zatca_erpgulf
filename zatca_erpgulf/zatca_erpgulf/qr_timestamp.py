"""Timestamp helpers shared by ZATCA QR-code generators."""

from __future__ import annotations

from datetime import datetime
import re

import pytz
from frappe import _
from frappe.utils import get_system_timezone


def format_zatca_qr_timestamp(issue_date, issue_time) -> str:
	"""Return an invoice timestamp in the ISO-8601 UTC form required by ZATCA.

	ERPNext stores posting times without a timezone. Treat those values as being
	in the configured system timezone, then serialize the instant in UTC with a
	``Z`` suffix. If the source already contains a timezone, preserve that
	instant and only normalize its representation.
	"""

	return format_zatca_issue_datetime(issue_date, issue_time).strftime(
		"%Y-%m-%dT%H:%M:%SZ"
	)


def format_zatca_issue_datetime(issue_date, issue_time) -> datetime:
	"""Return the invoice issue instant as an aware UTC datetime."""

	date_text = str(issue_date or "").strip()
	time_text = str(issue_time or "").strip()
	if not date_text or not time_text:
		raise ValueError("ZATCA QR timestamp requires both issue date and issue time")

	if time_text.endswith("Z"):
		time_text = time_text[:-1] + "+00:00"

	# MariaDB/ERPNext can return a single-digit hour (for example
	# ``9:05:42``). ISO-8601 requires the hour to be two digits.
	time_match = re.match(r"^(\d{1,2})(:.*)$", time_text)
	if time_match:
		time_text = time_match.group(1).zfill(2) + time_match.group(2)

	try:
		invoice_datetime = datetime.fromisoformat(f"{date_text}T{time_text}")
	except ValueError as exc:
		raise ValueError(
			_("Invalid issue date/time for ZATCA QR timestamp: {0}").format(exc)
		) from exc

	if invoice_datetime.tzinfo is None:
		invoice_datetime = pytz.timezone(get_system_timezone()).localize(invoice_datetime)

	return invoice_datetime.astimezone(pytz.UTC)
