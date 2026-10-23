"""Small saved-form comparison validators; no ERP, clocks, writes or authority.

Modified markers compare observed naive DATETIME values, not trusted epochs,
cross-request locks, issuance timestamps or evidence of a committed reload.
"""

import re
from datetime import datetime


class SavedFormSourceError(ValueError):
    """Static source error; never retain or stringify the supplied value."""


def saved_form_name(value):
    if (type(value) is not str or not 0 < len(value) <= 140 or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise SavedFormSourceError("source_identity")
    return value


def saved_form_revision(value):
    if type(value) is datetime and value.tzinfo is None:
        return value
    if type(value) is str and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?", value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    raise SavedFormSourceError("source_revision")
