"""Bounded rounding-method evidence on the caller's existing SQL transaction.

Reuse the format reader's text preflight/value/witness query and metadata reader.
No source discovery, cache lookup, defaults creation, writes, cleanup or I/O to
an authority. Missing Select storage requires a nonempty Singleton witness.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .calculation_rounding import _select_method
from .currency_format_source import MariaDBCurrencyFormatReader, _value
from .financial_source_observation import _canonical
from .metadata_source import MariaDBMetadataSourceReader, SelectedMetadataRows, _pin_rows
from .source_metadata import ROUNDING_PROFILE, _pin_metadata

PROFILE = "rounding-setting-source-sql/v1"


class RoundingSettingSourceError(ValueError):
    """Static English internal code; no setting, driver or source disclosure."""


def _meta(meta):
    meta = _pin_metadata(meta)
    df = meta.get_field("rounding_method")
    if meta.profile != ROUNDING_PROFILE or meta.name != "System Settings" or df is None or df.fieldtype != "Select":
        raise ValueError
    return meta


@dataclass(frozen=True, repr=False)
class LockedRoundingSettingRead:
    """Selected native/metadata binding, not actor or committed-source proof."""

    metadata: SelectedMetadataRows = field(repr=False)
    _payload: bytes = field(repr=False)
    value: str | None = field(init=False, repr=False)
    stored: bool = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            if type(self.metadata) is not SelectedMetadataRows:
                raise ValueError
            meta = _pin_rows(self.metadata)
            _meta(meta.applied)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= 65536:
                raise ValueError
            body = json.loads(self._payload)
            if (set(body) != {"profile", "metadata_sha256", "record"} or body["profile"] != PROFILE
                    or body["metadata_sha256"] != meta.sha256 or _canonical(body) != self._payload):
                raise ValueError
            row = body["record"]
            stored = "singleton_nonempty" not in row
            expected = {"doctype", "name", "field", "value", "sql_type"}
            if not stored:
                expected.add("singleton_nonempty")
            if (set(row) != expected or (row["doctype"], row["name"], row["field"])
                    != ("System Settings", "System Settings", "rounding_method")):
                raise ValueError
            if not stored and (row["singleton_nonempty"] is not True or row["value"] != ["absent"]):
                raise ValueError
            value = _value(row["value"] if stored else ["null"], row["sql_type"])
            _select_method(value, None)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise RoundingSettingSourceError("rounding_setting_rows")
        object.__setattr__(self, "metadata", meta)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "stored", stored)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-rounding-setting-source/v1\0" + self._payload).hexdigest())

    def __repr__(self):
        return "<LockedRoundingSettingRead protected PARTIAL SQL, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("rounding_setting_not_serializable")


def _pin_read(value):
    if type(value) is not LockedRoundingSettingRead:
        raise ValueError
    pinned = LockedRoundingSettingRead(value.metadata, value._payload)
    if pinned != value:
        raise ValueError
    return pinned


class MariaDBRoundingSettingReader:
    """Same borrowed handle, no cleanup/retry; any failed read poisons this reader."""

    def __init__(self, connection):
        self._text = MariaDBCurrencyFormatReader(connection, allow_missing_check=True)
        self._connection, self._failed = connection, False

    def _load(self, applied_metadata):
        meta = _meta(applied_metadata)
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            state = cursor.fetchone()
            if type(state) is not tuple or len(state) != 1 or type(state[0]) is not int or state[0] != 0:
                raise ValueError
        reader = MariaDBMetadataSourceReader(self._connection)
        selected = reader.load_for_update(meta)
        with self._connection.cursor() as cursor:
            before, _ = self._text._select(cursor, "System Settings", "System Settings", full=False, singleton_field="rounding_method")
            after, row = self._text._select(cursor, "System Settings", "System Settings", full=True, singleton_field="rounding_method")
        if before != after:
            raise ValueError
        reader.require_unchanged(selected)
        return LockedRoundingSettingRead(selected, _canonical(dict(profile=PROFILE,
            metadata_sha256=selected.sha256, record=row)))

    def load_for_update(self, *, applied_metadata):
        if self._failed:
            raise RoundingSettingSourceError("rounding_setting_transaction_unusable")
        try:
            return self._load(applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        raise RoundingSettingSourceError("rounding_setting_read")

    def require_unchanged(self, observed):
        if self._failed:
            raise RoundingSettingSourceError("rounding_setting_transaction_unusable")
        try:
            pinned = _pin_read(observed)
            if self._load(pinned.metadata.applied) != pinned:
                raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return
        raise RoundingSettingSourceError("rounding_setting_changed")

    def __repr__(self):
        return "<MariaDBRoundingSettingReader caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("rounding_setting_not_serializable")
