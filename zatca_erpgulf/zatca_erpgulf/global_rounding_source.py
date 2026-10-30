"""Selected native Global Defaults Check on a caller-owned SQL transaction.

This is the get_single_value projection, not a Singleton document load: a
missing row casts to int0 without a nonempty witness or document defaults.
Raw absence/NULL/blank/zero stay distinct. No discovery, cache lookup, amount
calculation, permission bypass, writes, cleanup or authority requests occur.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .currency_format_source import MariaDBCurrencyFormatReader, _value
from .financial_source_observation import _canonical
from .metadata_source import MariaDBMetadataSourceReader, SelectedMetadataRows, _pin_rows
from .rounded_total_control import RoundedTotalControl
from .source_metadata import GLOBAL_ROUNDING_PROFILE, _pin_metadata

PROFILE = "global-rounding-check-source-sql/v1"
DOCTYPE, FIELD = "Global Defaults", "disable_rounded_total"


class GlobalRoundingSourceError(ValueError):
    """Static English code; no configuration or driver disclosure."""


def _meta(value):
    meta = _pin_metadata(value)
    definition = meta.get_field(FIELD)
    if (meta.name != DOCTYPE or meta.profile != GLOBAL_ROUNDING_PROFILE
            or definition is None or definition.fieldtype != "Check"):
        raise ValueError
    return meta


@dataclass(frozen=True, repr=False)
class LockedGlobalRoundingRead:
    """Protected raw/API projection, NOT actor or committed-source proof.

    The supported storage is canonical Check text/NULL. Frappe accepts broader
    cint/sbool inputs; malformed Check storage is refused instead of repaired.
    Metadata defaults are evidence only: get_single_value does not apply them.
    """

    metadata: SelectedMetadataRows = field(repr=False)
    _payload: bytes = field(repr=False)
    value: int = field(init=False)
    stored: bool = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            if type(self.metadata) is not SelectedMetadataRows:
                raise ValueError
            metadata = _pin_rows(self.metadata)
            _meta(metadata.applied)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= 65536:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "metadata_sha256", "record"}
                    or body["profile"] != PROFILE or body["metadata_sha256"] != metadata.sha256
                    or _canonical(body) != self._payload):
                raise ValueError
            row = body["record"]
            if (type(row) is not dict or set(row) != {"doctype", "name", "field", "value", "sql_type"}
                    or (row["doctype"], row["name"], row["field"]) != (DOCTYPE, DOCTYPE, FIELD)):
                raise ValueError
            stored = row["value"] != ["absent"]
            raw = _value(row["value"] if stored else ["null"], row["sql_type"])
            if raw not in (None, "", "0", "1"):
                raise ValueError
            value = 1 if raw == "1" else 0
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise GlobalRoundingSourceError("global_rounding_rows")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "stored", stored)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-global-rounding-source/v1\0" + self._payload).hexdigest())

    def require_cache_match(self, cached):
        """Compare a supplied exact int API projection without cache access."""
        try:
            pinned = _pin_read(self)
            if type(cached) is not int or cached not in (0, 1) or cached != pinned.value:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise GlobalRoundingSourceError("global_rounding_cache_mismatch")

    def require_control_match(self, control):
        """Bind the consumed normalized global Check, without inventing a graph.

        A matching declared plan does not establish its invoice/consolidation/
        remaining settings provenance or authorize runtime adoption. Unused
        global evidence is refused, not silently attached to an invoice branch.
        """
        try:
            pinned = _pin_read(self)
            if type(control) is not RoundedTotalControl or control.disable_origin != "GLOBAL_DEFAULTS":
                raise ValueError
            control.require_disable_cache_match(pinned.value)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise GlobalRoundingSourceError("global_rounding_control_mismatch")

    def __repr__(self):
        return "<LockedGlobalRoundingRead protected PARTIAL SQL, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("global_rounding_not_serializable")


def _pin_read(value):
    if type(value) is not LockedGlobalRoundingRead:
        raise ValueError
    pinned = LockedGlobalRoundingRead(value.metadata, value._payload)
    if pinned != value:
        raise ValueError
    return pinned


class MariaDBGlobalRoundingReader:
    """Same borrowed handle; any failed read poisons it, with no cleanup/retry.

    The caller must authorize Global Defaults/field READ and choose this source
    only when the invoice's disable field is absent. No invoice/profile lookup
    or normal-row revision is invented here. Native metadata is checked before
    and after bounded two-pass reads using the shared Singleton text transport.
    """

    def __init__(self, connection):
        self._text = MariaDBCurrencyFormatReader(connection)
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
            before, _ = self._text._select(cursor, DOCTYPE, DOCTYPE, full=False, singleton_field=FIELD)
            after, row = self._text._select(cursor, DOCTYPE, DOCTYPE, full=True, singleton_field=FIELD)
        if before != after:
            raise ValueError
        reader.require_unchanged(selected)
        return LockedGlobalRoundingRead(selected, _canonical(dict(profile=PROFILE,
            metadata_sha256=selected.sha256, record=row)))

    def load_for_update(self, *, applied_metadata):
        if self._failed:
            raise GlobalRoundingSourceError("global_rounding_transaction_unusable")
        try:
            return self._load(applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        raise GlobalRoundingSourceError("global_rounding_read")

    def require_unchanged(self, observed):
        if self._failed:
            raise GlobalRoundingSourceError("global_rounding_transaction_unusable")
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
        raise GlobalRoundingSourceError("global_rounding_changed")

    def __repr__(self):
        return "<MariaDBGlobalRoundingReader caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("global_rounding_not_serializable")
