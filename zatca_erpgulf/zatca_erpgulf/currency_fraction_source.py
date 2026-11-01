"""Native invoice-currency rounding configuration on one borrowed transaction.

Reuse financial bounded SQL, native descriptors and metadata evidence. Keep raw
configuration separate from its precision-free framework flt projection. No
invoice amount is converted/calculated; no Company/POS/global currency fallback,
cache discovery, permission bypass, writes, cleanup or authority requests.
"""

from dataclasses import dataclass, field
import hashlib
import json
import math

from .financial_source_observation import _canonical, _name, _scalar, _validate_scalar
from .financial_source_sql import (
    LockedInvoiceFinancialRead, MariaDBInvoiceFinancialReader, _native, _pin_read as _pin_financial,
)
from .metadata_source import MariaDBMetadataSourceReader, SelectedMetadataRows, _modified, _pin_rows
from .rounded_total_control import _fraction_branch
from .source_metadata import CURRENCY_FRACTION_PROFILE, _pin_metadata

PROFILE = "invoice-currency-fraction-source-sql/v1"
FIELD = "smallest_currency_fraction_value"


class CurrencyFractionSourceError(ValueError):
    """Static English codes, without configuration or driver disclosure."""


def _meta(value):
    meta = _pin_metadata(value)
    definition = meta.get_field(FIELD)
    if (meta.name != "Currency" or meta.profile != CURRENCY_FRACTION_PROFILE
            or definition is None or definition.fieldtype != "Currency"):
        raise ValueError
    return meta


def _currency(financial):
    observed = financial.financial
    root = next(row.applied for row in financial.metadata if row.applied.name == observed.doctype)
    definition = root.get_field("currency")
    if definition is None or definition.fieldtype != "Link" or definition.options != "Currency":
        raise ValueError
    return _name(_validate_scalar(dict(json.loads(observed._payload)["header"])["currency"]))


def _effective(encoded):
    """Normalize CONFIGURATION only, matching flt(value) without precision.

    Native finite Decimal/float/NULL bounds and the shared fraction classifier
    precede conversion. Do not apply this projection to invoice money. Keep
    negative zero and tiny/large valid configuration float identities intact.
    """
    branch = _fraction_branch(encoded)
    raw = _validate_scalar(encoded)
    effective = 0.0 if raw is None else float(raw)
    if not math.isfinite(effective):
        raise ValueError
    return effective, branch


@dataclass(frozen=True, repr=False)
class LockedCurrencyFractionRead:
    """Partial raw/normalized config bound to financial currency, NOT authority."""

    financial: LockedInvoiceFinancialRead = field(repr=False)
    metadata: SelectedMetadataRows = field(repr=False)
    _payload: bytes = field(repr=False)
    currency: str = field(init=False, repr=False)
    effective_fraction: float = field(init=False, repr=False)
    branch: str = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            financial, metadata = _pin_financial(self.financial), _pin_rows(self.metadata)
            meta = _meta(metadata.applied)
            currency = _currency(financial)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= 65536:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "financial_sha256", "metadata_sha256", "record"}
                    or body["profile"] != PROFILE or body["financial_sha256"] != financial.sha256
                    or body["metadata_sha256"] != metadata.sha256 or _canonical(body) != self._payload):
                raise ValueError
            record = body["record"]
            if (type(record) is not dict or set(record) != {"doctype", "name", "modified", "field", "value", "sql_type"}
                    or (record["doctype"], record["name"], record["field"]) != ("Currency", currency, FIELD)):
                raise ValueError
            _modified(record["modified"])
            _native(_validate_scalar(record["value"]), meta.get_field(FIELD).fieldtype, record["sql_type"])
            effective, branch = _effective(record["value"])
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CurrencyFractionSourceError("currency_fraction_rows")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "effective_fraction", effective)
        object.__setattr__(self, "branch", branch)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-currency-fraction-source/v1\0" + self._payload).hexdigest())

    def require_effective_cache_match(self, supplied):
        """Compare a supplied post-flt configuration, not an untyped raw lookup.

        The caller must prove its scope/API origin. Exact finite float identity,
        including signed zero, is required; never fetch/populate/repair a cache.
        """
        try:
            pinned = _pin_read(self)
            if (type(supplied) is not float or not math.isfinite(supplied)
                    or supplied.hex() != pinned.effective_fraction.hex()):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise CurrencyFractionSourceError("currency_fraction_cache_mismatch")

    def __repr__(self):
        return "<LockedCurrencyFractionRead protected PARTIAL config, NOT rounding authority>"

    def __reduce__(self):
        raise TypeError("currency_fraction_not_serializable")


def _pin_read(value):
    if type(value) is not LockedCurrencyFractionRead:
        raise ValueError
    pinned = LockedCurrencyFractionRead(value.financial, value.metadata, value._payload)
    # Float equality alone cannot detect a tampered sign on zero.
    if pinned != value or pinned.effective_fraction.hex() != value.effective_fraction.hex():
        raise ValueError
    return pinned


class MariaDBCurrencyFractionReader:
    """Read/recheck the final invoice currency on the same authorized handle.

    Require normal invoice/Currency/field READ before use. No owned connection,
    transaction cleanup or retries; any failed read poisons this reader.
    """

    def __init__(self, connection):
        self._financial = MariaDBInvoiceFinancialReader(connection)
        self._connection, self._failed = connection, False

    def _load(self, financial, applied_metadata):
        financial, meta = _pin_financial(financial), _meta(applied_metadata)
        currency = _currency(financial)
        self._financial.require_unchanged(financial)
        metadata_reader = MariaDBMetadataSourceReader(self._connection)
        selected = metadata_reader.load_for_update(meta)
        with self._connection.cursor() as cursor:
            before, _, _ = self._financial._select(cursor, "Currency", currency, None, meta, (FIELD,), 1, values=False)
            after, documents, signatures = self._financial._select(cursor, "Currency", currency, None, meta, (FIELD,), 1, values=True)
        if before != after:
            raise ValueError
        metadata_reader.require_unchanged(selected)
        self._financial.require_unchanged(financial)
        doc = documents[0]
        record = dict(doctype="Currency", name=doc.name, modified=_scalar(doc.get("modified")),
            field=FIELD, value=_scalar(doc.get(FIELD)), sql_type=signatures[0][1])
        return LockedCurrencyFractionRead(financial, selected, _canonical(dict(profile=PROFILE,
            financial_sha256=financial.sha256, metadata_sha256=selected.sha256, record=record)))

    def load_for_update(self, financial, *, applied_metadata):
        if self._failed:
            raise CurrencyFractionSourceError("currency_fraction_transaction_unusable")
        try:
            return self._load(financial, applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        raise CurrencyFractionSourceError("currency_fraction_read")

    def require_unchanged(self, observed):
        if self._failed:
            raise CurrencyFractionSourceError("currency_fraction_transaction_unusable")
        try:
            pinned = _pin_read(observed)
            if self._load(pinned.financial, pinned.metadata.applied) != pinned:
                raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return
        raise CurrencyFractionSourceError("currency_fraction_changed")

    def __repr__(self):
        return "<MariaDBCurrencyFractionReader caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("currency_fraction_not_serializable")
