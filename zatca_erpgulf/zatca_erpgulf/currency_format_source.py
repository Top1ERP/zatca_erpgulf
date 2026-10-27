"""Explicit locale/currency format SQL on an authorized caller-owned handle.

The caller supplies the effective language, already resolved field currency and
exact applied format metadata. No site/actor/currency discovery, cache lookup,
write, transaction cleanup, rounding, XML generation or authority I/O occurs.
"""

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from .calculation_precision import CurrencyFormatContext, _pin_currency
from .financial_source_observation import _canonical, _name, _scalar, _validate_scalar
from .financial_source_sql import TEXT_CODES, _native
from .metadata_source import (
    MariaDBMetadataSourceReader, SelectedMetadataRows, _modified,
    _pin_rows as _pin_metadata_rows,
)
from .source_metadata import FORMAT_PROFILE, _pin_metadata

PROFILE = "currency-format-source-sql/v1"
ABSENT_PROFILE = "currency-format-source-sql/absent-check-v1"
FLAG = "use_number_format_from_currency"
MAX_VALUE_BYTES = 4096
MAX_PAYLOAD_BYTES = 65536
TEXT_FIELDS = MappingProxyType({"Currency": "number_format", "Language": "number_format", "Company": "default_currency"})


class CurrencyFormatSourceError(ValueError):
    """Static English code, without settings, identities or driver disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _types(language, currency):
    _name(language)
    if currency is not None:
        _name(currency)
    return ("Language", "System Settings") if currency is None else ("Currency", "Language", "System Settings")


def _metas(language, currency, supplied):
    required = _types(language, currency)
    if type(supplied) is not dict or set(supplied) != set(required):
        raise ValueError
    pinned = {name: _pin_metadata(supplied[name]) for name in required}
    for name, meta in pinned.items():
        fieldname = FLAG if name == "System Settings" else "number_format"
        definition = meta.get_field(fieldname)
        if (meta.name != name or meta.profile != FORMAT_PROFILE or definition is None
                or definition.fieldtype not in (("Check",) if name == "System Settings" else ("Data", "Select"))):
            raise ValueError
    return pinned


def _value(encoded, signature):
    value = _validate_scalar(encoded)
    _native(value, "Data", signature)  # Bind native text type even for NULL values.
    if value is not None and (len(value.encode("utf-8")) > MAX_VALUE_BYTES or "\0" in value):
        raise ValueError
    return value


def _context(language, currency, records, *, absent_check=False):
    expected = [(name, language if name == "Language" else currency if name == "Currency" else name)
        for name in _types(language, currency)]
    if type(records) is not list or [(row.get("doctype"), row.get("name")) for row in records] != expected:
        raise ValueError
    values = {}
    for row, (doctype, name) in zip(records, expected):
        keys = {"doctype", "name", "field", "value", "sql_type"}
        if doctype != "System Settings": keys.add("modified")
        if doctype == "System Settings" and absent_check:
            keys.add("singleton_nonempty")
        if set(row) != keys or row["field"] != (FLAG if doctype == "System Settings" else "number_format"):
            raise ValueError
        if doctype != "System Settings": _modified(row["modified"])
        if doctype == "System Settings" and absent_check:
            if row["value"] != ["absent"] or row["singleton_nonempty"] is not True:
                raise ValueError
            _value(["null"], row["sql_type"])  # Validate text descriptor, without inventing NULL storage.
            values[doctype] = None
        else:
            values[doctype] = _value(row["value"], row["sql_type"])
    raw_flag = values["System Settings"]
    # A witnessed NONEMPTY Singleton initializes an absent Check to zero. A
    # wholly empty Singleton can run new_doc defaults and remains unsupported.
    if raw_flag not in (None, "", "0", "1"):
        raise ValueError
    return CurrencyFormatContext(language, values["Language"], raw_flag == "1",
        currency, values.get("Currency"))


@dataclass(frozen=True, repr=False)
class LockedCurrencyFormatRead:
    """Protected selected raw values/metadata, not actor/source provenance."""

    language: str = field(repr=False)
    currency: str | None = field(repr=False)
    metadata: tuple[SelectedMetadataRows, ...] = field(repr=False)
    _payload: bytes = field(repr=False)
    context: CurrencyFormatContext = field(init=False, repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            required = _types(self.language, self.currency)
            if type(self.metadata) is not tuple or len(self.metadata) != len(required):
                raise ValueError
            metadata = tuple(_pin_metadata_rows(row) for row in self.metadata)
            if tuple(row.applied.name for row in metadata) != required:
                raise ValueError
            _metas(self.language, self.currency, {row.applied.name: row.applied for row in metadata})
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "language", "currency", "metadata", "records"}
                    or body["profile"] not in (PROFILE, ABSENT_PROFILE)
                    or (body["language"], body["currency"]) != (self.language, self.currency)
                    or body["metadata"] != [[row.applied.name, row.sha256] for row in metadata]
                    or _canonical(body) != self._payload):
                raise ValueError
            context = _context(self.language, self.currency, body["records"], absent_check=body["profile"] == ABSENT_PROFILE)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CurrencyFormatSourceError("currency_format_source_rows")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "context", context)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-currency-format-source-sql/v1\0" + self._payload).hexdigest())

    def __repr__(self):
        return "<LockedCurrencyFormatRead protected PARTIAL SQL, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("currency_format_source_not_serializable")

    def require_context_match(self, cached):
        """Compare one exact supplied projection, without fetching or refreshing.

        The caller must establish cache/API/language/currency provenance. Matching
        is neither proof of committed origin nor authority to build or send.
        """
        try:
            pinned = _pin_read(self)
            if _pin_currency(cached) != pinned.context:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CurrencyFormatSourceError("currency_format_source_cache_mismatch")


def _pin_read(observed):
    if type(observed) is not LockedCurrencyFormatRead:
        raise ValueError
    pinned = LockedCurrencyFormatRead(observed.language, observed.currency, observed.metadata, observed._payload)
    if pinned != observed:
        raise ValueError
    return pinned


class MariaDBCurrencyFormatReader:
    """Bounded two-pass locking reads on the exact borrowed transaction.

    Singleton values use tabSingles, without an invented modified timestamp.
    Existing rows remain locked until CALLER cleanup; own pending writes are
    visible and RC phantoms still require completion checks. No cleanup/retry.
    """

    def __init__(self, connection, *, allow_missing_check=False):
        if not callable(getattr(connection, "cursor", None)) or type(allow_missing_check) is not bool:
            raise CurrencyFormatSourceError("currency_format_source_connection")
        self._connection, self._failed = connection, False
        self._allow_missing_check = allow_missing_check

    def __repr__(self):
        return "<MariaDBCurrencyFormatReader explicit caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("currency_format_source_not_serializable")

    def _select(self, cursor, doctype, name, *, full):
        singleton = doctype == "System Settings"
        table, column = ("Singles", "value") if singleton else (doctype, TEXT_FIELDS[doctype])
        ids = "SUBSTRING(`doctype`,1,141),SUBSTRING(`field`,1,141)" if singleton else "SUBSTRING(`name`,1,141),`modified`"
        length = "OCTET_LENGTH(`" + column + "`)"
        projection = ("CASE WHEN " + length + "<=4096 OR `" + column + "` IS NULL THEN `"
            + column + "` ELSE NULL END,") if full else ""
        where, params = ("`doctype`=%s AND `field`=%s", (doctype, FLAG)) if singleton else ("`name`=%s", (name,))
        cursor.execute("SELECT " + ids + "," + projection + length + " FROM `tab" + table + "` WHERE "
            + where + " LIMIT %s FOR UPDATE", (*params, 2))
        rows = cursor.fetchall()
        if type(rows) in (tuple, list) and not rows and singleton and self._allow_missing_check:
            signature = None
            if full:
                descriptor = cursor.description[2]
                signature = [descriptor[1], descriptor[4], descriptor[5], descriptor[6]]
                _value(["null"], signature)
            # Fetch NO field name or value from the witness row. A nonempty
            # Singles dictionary skips new_doc and _fix_numeric_types sets the
            # missing Check to zero in the inspected framework implementations.
            cursor.execute("SELECT SUBSTRING(`doctype`,1,141) FROM `tabSingles` WHERE `doctype`=%s LIMIT 1 FOR UPDATE",
                (doctype,))
            witness = cursor.fetchall()
            if type(witness) not in (tuple, list) or tuple(witness) != ((doctype,),):
                raise ValueError
            record = None if not full else dict(doctype=doctype, name=name, field=FLAG,
                value=["absent"], sql_type=signature, singleton_nonempty=True)
            return ("absent-check",), record
        if type(rows) not in (tuple, list) or len(rows) != 1:
            raise ValueError  # Missing/duplicate/collation-variant sources are never invented.
        row = rows[0]
        if type(row) is not tuple or len(row) != (4 if full else 3): raise ValueError
        if singleton:
            if row[:2] != (doctype, FLAG): raise ValueError
        else:
            if row[0] != name: raise ValueError
            _modified(_scalar(row[1]))
        count = row[-1]
        if count is not None and (type(count) is not int or not 0 <= count <= MAX_VALUE_BYTES): raise ValueError
        if not full: return (row[0], row[1], count), None
        descriptor = cursor.description[2]
        signature = [descriptor[1], descriptor[4], descriptor[5], descriptor[6]]
        if signature[0] not in TEXT_CODES: raise ValueError
        value = _value(_scalar(row[2]), signature)
        if count != (None if value is None else len(value.encode("utf-8"))): raise ValueError
        record = dict(doctype=doctype, name=name, field=FLAG if singleton else column,
            value=_scalar(value), sql_type=signature)
        if not singleton: record["modified"] = _scalar(row[1])
        return (row[0], row[1], count), record

    def _load(self, language, currency, applied_metadata):
        metas = _metas(language, currency, applied_metadata)
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            setting = cursor.fetchone()
            if type(setting) is not tuple or len(setting) != 1 or type(setting[0]) is not int or setting[0] != 0:
                raise ValueError
        metadata_reader = MariaDBMetadataSourceReader(self._connection)
        metadata = tuple(metadata_reader.load_for_update(meta) for meta in metas.values())
        records = []
        for doctype in metas:
            name = language if doctype == "Language" else currency if doctype == "Currency" else doctype
            with self._connection.cursor() as cursor:
                before, _ = self._select(cursor, doctype, name, full=False)
                after, record = self._select(cursor, doctype, name, full=True)
            if before != after: raise ValueError
            records.append(record)
        for row in metadata: metadata_reader.require_unchanged(row)
        profile = ABSENT_PROFILE if any(row.get("singleton_nonempty") is True for row in records) else PROFILE
        payload = _canonical(dict(profile=profile, language=language, currency=currency,
            metadata=[[row.applied.name, row.sha256] for row in metadata], records=records))
        return LockedCurrencyFormatRead(language, currency, metadata, payload)

    def load_for_update(self, language, *, currency=None, applied_metadata):
        if self._failed: raise CurrencyFormatSourceError("currency_format_source_transaction_unusable")
        try:
            result = self._load(language, currency, applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception): raise
        else:
            return result
        raise CurrencyFormatSourceError("currency_format_source_read")

    def require_unchanged(self, observed):
        if self._failed: raise CurrencyFormatSourceError("currency_format_source_transaction_unusable")
        try:
            pinned = _pin_read(observed)
            metas = {row.applied.name: row.applied for row in pinned.metadata}
            if self._load(pinned.language, pinned.currency, metas) != pinned: raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception): raise
        else:
            return
        raise CurrencyFormatSourceError("currency_format_source_changed")
