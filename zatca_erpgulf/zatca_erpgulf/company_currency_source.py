"""Company default-currency evidence on an explicit caller-owned transaction.

Reuse the bounded text projection and shared selected-metadata reader. No
Company/tenant discovery, cache lookup, writes, cleanup, FX or amount calculation.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .currency_format_source import MariaDBCurrencyFormatReader, _value
from .financial_source_observation import _canonical, _name, _validate_scalar
from .metadata_source import MariaDBMetadataSourceReader, SelectedMetadataRows, _modified, _pin_rows
from .source_metadata import PROFILE as METADATA_PROFILE

PROFILE = "company-currency-source-sql/v1"


class CompanyCurrencySourceError(ValueError):
    """Static English code, no Company/currency/driver disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _metadata(observed):
    pinned = _pin_rows(observed)
    meta = pinned.applied
    definition = meta.get_field("default_currency")
    if (meta.name != "Company" or meta.profile != METADATA_PROFILE or definition is None
            or definition.fieldtype != "Link" or definition.options != "Currency"):
        raise ValueError
    return pinned


@dataclass(frozen=True, repr=False)
class LockedCompanyCurrencyRead:
    """Protected typed Company link/revision, NOT saved ACL or source provenance."""

    name: str = field(repr=False)
    metadata: SelectedMetadataRows = field(repr=False)
    _payload: bytes = field(repr=False)
    currency: str = field(init=False, repr=False)
    revision: str = field(init=False, repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            _name(self.name)
            metadata = _metadata(self.metadata)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= 16384:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "metadata_sha256", "record"}
                    or body["profile"] != PROFILE or body["metadata_sha256"] != metadata.sha256
                    or _canonical(body) != self._payload):
                raise ValueError
            record = body["record"]
            if (type(record) is not dict or set(record) != {"doctype", "name", "field", "value", "sql_type", "modified"}
                    or (record["doctype"], record["name"], record["field"]) != ("Company", self.name, "default_currency")):
                raise ValueError
            _modified(record["modified"])
            currency = _name(_value(record["value"], record["sql_type"]))
            revision = _validate_scalar(record["modified"]).isoformat(timespec="microseconds")
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CompanyCurrencySourceError("company_currency_source_rows")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-company-currency-source-sql/v1\0" + self._payload).hexdigest())

    def __repr__(self):
        return "<LockedCompanyCurrencyRead protected Company link, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("company_currency_source_not_serializable")


def _pin_read(observed):
    if type(observed) is not LockedCompanyCurrencyRead:
        raise ValueError
    pinned = LockedCompanyCurrencyRead(observed.name, observed.metadata, observed._payload)
    if pinned != observed: raise ValueError
    return pinned


class MariaDBCompanyCurrencyReader:
    """Read/recheck one authorized Company using its exact selected metadata.

    The supplied metadata is checked on this same handle. Ordinary text bounds,
    native type signatures and preflight/CASE masking reuse the format reader.
    Errors poison the reader, never committing/cleaning/retrying parent work.
    """

    def __init__(self, connection):
        self._text = MariaDBCurrencyFormatReader(connection)
        self._connection, self._failed = connection, False

    def _load(self, name, metadata):
        _name(name)
        metadata = _metadata(metadata)
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            setting = cursor.fetchone()
            if type(setting) is not tuple or len(setting) != 1 or type(setting[0]) is not int or setting[0] != 0:
                raise ValueError
        source = MariaDBMetadataSourceReader(self._connection)
        source.require_unchanged(metadata)
        with self._connection.cursor() as cursor:
            before, _ = self._text._select(cursor, "Company", name, full=False)
            after, record = self._text._select(cursor, "Company", name, full=True)
        if before != after: raise ValueError
        source.require_unchanged(metadata)
        return LockedCompanyCurrencyRead(name, metadata, _canonical(dict(profile=PROFILE,
            metadata_sha256=metadata.sha256, record=record)))

    def load_for_update(self, name, *, metadata):
        if self._failed: raise CompanyCurrencySourceError("company_currency_source_transaction_unusable")
        try:
            result = self._load(name, metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception): raise
        else:
            return result
        raise CompanyCurrencySourceError("company_currency_source_read")

    def require_unchanged(self, observed):
        if self._failed: raise CompanyCurrencySourceError("company_currency_source_transaction_unusable")
        try:
            pinned = _pin_read(observed)
            if self._load(pinned.name, pinned.metadata) != pinned: raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception): raise
        else:
            return
        raise CompanyCurrencySourceError("company_currency_source_changed")

    def __repr__(self):
        return "<MariaDBCompanyCurrencyReader explicit caller-owned read>"

    def __reduce__(self):
        raise TypeError("company_currency_source_not_serializable")
