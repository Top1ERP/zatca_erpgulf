"""Bounded calculation defaults reads in an explicit caller-owned transaction.

No Frappe context, cache lookup/repair, connection discovery, fiscal calculation,
schema installation, commit/rollback/close or HTTP. The caller authorizes and
owns the exact connection and must compose these reads with its other sources.
Locked rows are not a complete source snapshot or proof of provider/ACL origin.
"""

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json

from .financial_source_observation import (
    MAX_PAYLOAD_BYTES, _canonical, _name, _scalar, _validate_scalar,
)

PROFILE = "calculation-default-rows/v1"
KEYS = ("currency_precision", "float_precision", "number_format")
MAX_ROWS = 128
MAX_VALUE_BYTES = 4096

# Fixed columns and predicates only. LIMIT and SUBSTRING bound ordinary buffered
# drivers before Python validation. Collation matches the normal Frappe lookup;
# returned parent/key case variants are refused rather than silently normalized.
READ_SQL = """SELECT SUBSTRING(`name`,1,141),`creation`,`modified`,
    SUBSTRING(`parent`,1,141),SUBSTRING(`defkey`,1,141),
    SUBSTRING(`defvalue`,1,4097)
    FROM `tabDefaultValue`
    WHERE `parent`=%s AND `defkey` IN (%s,%s,%s)
    ORDER BY `creation` ASC,BINARY `name` ASC LIMIT %s FOR UPDATE"""


class CalculationDefaultsError(ValueError):
    """Static English codes; never include a default, scope or driver error."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _timestamp(encoded):
    value = _validate_scalar(encoded)
    # SQL NULL is retained, including historical rows without revision stamps.
    # Zero dates, date-only values and timezone conversions are not guessed.
    if value is not None and (type(value) is not datetime or value.tzinfo is not None):
        raise ValueError
    return value


def _value(encoded):
    value = _validate_scalar(encoded)
    if value is not None and (type(value) is not str or len(value.encode("utf-8")) > MAX_VALUE_BYTES):
        raise ValueError
    return value


def _validate_rows(rows):
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ValueError
    identities, orders, ties = set(), [], {}
    for row in rows:
        if type(row) is not dict or set(row) != {"name", "creation", "modified", "key", "value"}:
            raise ValueError
        name = _name(row["name"])
        if name in identities or row["key"] not in KEYS:
            raise ValueError
        identities.add(name)
        creation = _timestamp(row["creation"])
        _timestamp(row["modified"])
        value = _value(row["value"])
        orders.append((creation is not None, creation or datetime.min, name))
        tie = (row["key"], creation)
        if tie in ties and ties[tie] != value:
            # Framework ordering is creation-only. A name tiebreak cannot grant
            # a fiscal precedence that the framework did not establish.
            raise ValueError
        ties[tie] = value
    if orders != sorted(orders):
        raise ValueError


def _fold(rows):
    """Selected-key projection of inspected get_defaults_for row semantics.

    Preserve first-seen distinct values and NULL behavior. No numeric coercion,
    user overlay, permission filtering or first-list-value selection occurs.
    Tests compare this with the actual installed framework's cache-miss method.
    """
    values = {}
    for row in rows:
        key, value = row["key"], _value(row["value"])
        if key not in values:
            if value is not None:
                values[key] = value
        elif isinstance(values[key], list):
            if value not in values[key]:
                values[key].append(value)
        elif values[key] != value:
            values[key] = [values[key], value]
    return values


def _cache_value(value):
    if type(value) is list:
        if not 0 < len(value) <= MAX_ROWS:
            raise ValueError
        return ["list", [_scalar(_value(_scalar(item))) for item in value]]
    return _scalar(_value(_scalar(value)))


@dataclass(frozen=True, repr=False)
class CalculationDefaultsRows:
    """Protected scoped rows, not effective precision or committed-read proof."""

    parent: str = field(repr=False)
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            _name(self.parent)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "parent", "keys", "rows"}
                    or body["profile"] != PROFILE or body["parent"] != self.parent
                    or body["keys"] != list(KEYS) or _canonical(body) != self._payload):
                raise ValueError
            _validate_rows(body["rows"])
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationDefaultsError("calculation_defaults_rows")
        object.__setattr__(self, "sha256", hashlib.sha256(
            b"zatca-calculation-default-rows/v1\0" + self._payload).hexdigest())

    def __repr__(self):
        return "<CalculationDefaultsRows protected scoped rows, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("calculation_defaults_not_serializable")

    def require_cache_match(self, parent, cached):
        """Compare supplied selected cache keys; never fetch, refresh or repair.

        The caller must prove the cache API/parent/tenant. Unknown keys are not
        inspected. A None cache miss differs from an empty cached dictionary.
        Matching does not authorize issuance or establish freshness after return.
        """
        try:
            pinned = _pin_rows(self)
            if parent != pinned.parent or not isinstance(cached, dict):
                raise ValueError
            expected = _fold(json.loads(pinned._payload)["rows"])
            for key in KEYS:
                present = dict.__contains__(cached, key)
                if present != (key in expected):
                    raise ValueError
                if present and _cache_value(dict.__getitem__(cached, key)) != _cache_value(expected[key]):
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CalculationDefaultsError("calculation_defaults_cache_mismatch")


def _pin_rows(observed):
    if type(observed) is not CalculationDefaultsRows:
        raise ValueError
    pinned = CalculationDefaultsRows(observed.parent, observed._payload)
    if pinned != observed:
        raise ValueError
    return pinned


class MariaDBCalculationDefaultsReader:
    """Fixed read/lock operations on the SAME explicit caller-owned handle.

    The caller supplies authorized scope and a suitable audited connection,
    guards provider identity/ACL and owns all cleanup. Current locking reads
    bypass a stale MVCC snapshot, but can see this transaction's own writes.
    No committed-origin or phantom-free claim is made under READ COMMITTED.
    """

    def __init__(self, connection):
        if not callable(getattr(connection, "cursor", None)):
            raise CalculationDefaultsError("calculation_defaults_connection")
        self._connection, self._failed = connection, False

    def __repr__(self):
        return "<MariaDBCalculationDefaultsReader explicit caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("calculation_defaults_reader_not_serializable")

    def _load(self, parent):
        _name(parent)
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            setting = cursor.fetchone()
            if type(setting) is not tuple or len(setting) != 1 or type(setting[0]) is not int or setting[0] != 0:
                raise ValueError
            cursor.execute(READ_SQL, (parent, *KEYS, MAX_ROWS + 1))
            raw_rows = cursor.fetchall()
        if type(raw_rows) not in (tuple, list) or len(raw_rows) > MAX_ROWS:
            raise ValueError
        rows = []
        for raw in raw_rows:
            if type(raw) is not tuple or len(raw) != 6 or raw[3] != parent or raw[4] not in KEYS:
                raise ValueError
            rows.append(dict(name=raw[0], creation=_scalar(raw[1]), modified=_scalar(raw[2]),
                key=raw[4], value=_scalar(raw[5])))
        return CalculationDefaultsRows(parent, _canonical(dict(
            profile=PROFILE, parent=parent, keys=list(KEYS), rows=rows)))

    def load_for_update(self, parent):
        """Read every selected row, including duplicates/NULL and exact revisions."""
        if self._failed:
            raise CalculationDefaultsError("calculation_defaults_transaction_unusable")
        try:
            result = self._load(parent)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return result
        raise CalculationDefaultsError("calculation_defaults_read")

    def require_unchanged(self, observed):
        """Re-read membership/order/values/revisions in this owned transaction.

        Recheck again at the caller's completion boundary. This does not lock a
        cache or permission table, commit a snapshot, or protect future changes.
        """
        if self._failed:
            raise CalculationDefaultsError("calculation_defaults_transaction_unusable")
        try:
            expected = _pin_rows(observed)
            if self._load(expected.parent) != expected:
                raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return
        raise CalculationDefaultsError("calculation_defaults_changed")
