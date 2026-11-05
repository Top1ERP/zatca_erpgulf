"""Native optional invoice controls bound to existing financial evidence.

Reuse the financial bounded projection and metadata readers on one authorized
caller-owned transaction. Prove optional physical columns rather than inventing
consolidation from its omission in the old financial profile. Raw money/Check
values remain unchanged; normalized Check projections are separate. No amount
calculation, document/cache discovery, cleanup, writes or authority requests.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .financial_source_observation import HEADER_FIELDS, _canonical, _scalar, _validate_scalar
from .financial_source_sql import MariaDBInvoiceFinancialReader, LockedInvoiceFinancialRead, _native, _pin_read as _pin_financial
from .metadata_source import MariaDBMetadataSourceReader, SelectedMetadataRows, _modified, _pin_rows
from .source_metadata import INVOICE_ROUNDING_PROFILE, INVOICE_ROUNDING_FIELDS, _pin_metadata

PROFILE = "invoice-rounding-controls-source-sql/v1"
FIELDS = ("is_consolidated", "rounding_adjustment", "rounded_total", "disable_rounded_total")
CHECKS = ("is_consolidated", "disable_rounded_total")
OVERLAP = tuple(name for name in FIELDS if name in HEADER_FIELDS)


class InvoiceRoundingSourceError(ValueError):
    """Static English code, without invoice amounts or driver disclosure."""


def _meta(value, *, profile=INVOICE_ROUNDING_PROFILE, fields=FIELDS, checks=CHECKS, links=()):
    meta = _pin_metadata(value)
    from .source_metadata import PROFILE_FIELDS
    if meta.profile != profile or meta.name not in PROFILE_FIELDS[profile]:
        raise ValueError
    links = dict(links)
    for name in fields:
        definition = meta.get_field(name)
        expected = "Link" if name in links else "Check" if name in checks else "Currency"
        # A None Link target denotes the source DocType itself (Sales/POS
        # return_against); literal targets such as Company stay exact.
        if definition is not None and (definition.fieldtype != expected
                or name in links and definition.options != (meta.name if links[name] is None else links[name])):
            raise ValueError
    return meta


def _check(encoded):
    """Explicit numeric-fix projection; ordinary saved loads can retain NULL.

    A present NULL Check normalizes to int0 in both inspected framework versions.
    Refuse noncanonical native Check values instead of silently repairing them.
    """
    if encoded == ["absent"]:
        return None
    raw = _validate_scalar(encoded)
    if raw is None:
        return 0
    if type(raw) is not int or raw not in (0, 1):
        raise ValueError
    return raw


def _root(financial, meta, overlap=OVERLAP):
    observed = financial.financial
    root = next(row.applied for row in financial.metadata if row.applied.name == observed.doctype)
    if meta.name != root.name or any(meta.get_field(name) != root.get_field(name) for name in overlap):
        raise ValueError
    return json.loads(observed._payload)


@dataclass(frozen=True, repr=False)
class LockedInvoiceRoundingRead:
    """Partial native controls/columns, NOT saved READ or complete ERP authority."""

    financial: LockedInvoiceFinancialRead = field(repr=False)
    metadata: SelectedMetadataRows = field(repr=False)
    _payload: bytes = field(repr=False)
    consolidated: bool = field(init=False)
    normalized_checks: tuple = field(init=False, repr=False)
    sha256: str = field(init=False)

    FIELDS, CHECKS, OVERLAP = FIELDS, CHECKS, OVERLAP
    LINKS = ()
    METADATA_PROFILE = INVOICE_ROUNDING_PROFILE
    ROW_PROFILE = PROFILE
    DOMAIN = b"zatca-invoice-rounding-source/v1\0"

    def __post_init__(self):
        try:
            financial, metadata = _pin_financial(self.financial), _pin_rows(self.metadata)
            meta = _meta(metadata.applied, profile=self.METADATA_PROFILE, fields=self.FIELDS, checks=self.CHECKS, links=self.LINKS)
            original = _root(financial, meta, self.OVERLAP)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= 65536:
                raise ValueError
            body = json.loads(self._payload)
            selected = tuple(name for name in self.FIELDS if meta.has_field(name))
            if (type(body) is not dict or set(body) != {"profile", "financial_sha256", "metadata_sha256", "columns", "modified", "types", "fields"}
                    or body["profile"] != self.ROW_PROFILE or body["financial_sha256"] != financial.sha256
                    or body["metadata_sha256"] != metadata.sha256 or body["columns"] != sorted(selected)
                    or body["modified"] != original["modified"] or _canonical(body) != self._payload
                    or type(body["types"]) is not list or type(body["fields"]) is not list
                    or len(body["types"]) != len(selected) or len(body["fields"]) != len(self.FIELDS)):
                raise ValueError
            _modified(body["modified"])
            if any(type(row) is not list or len(row) != 2 for row in (*body["types"], *body["fields"])):
                raise ValueError
            if tuple(row[0] for row in body["types"]) != selected or tuple(row[0] for row in body["fields"]) != self.FIELDS:
                raise ValueError
            types, fields = dict(body["types"]), dict(body["fields"])
            prior_types = dict(dict(json.loads(financial._payload)["types"])["header"])
            prior_values = dict(original["header"])
            for name in self.FIELDS:
                encoded = fields[name]
                if name in self.OVERLAP and (encoded != prior_values[name] or types.get(name) != prior_types.get(name)):
                    raise ValueError
                if not meta.has_field(name):
                    if encoded != ["absent"]:
                        raise ValueError
                    continue
                _native(_validate_scalar(encoded), meta.get_field(name).fieldtype, types[name])
            checks = tuple((name, _check(fields[name])) for name in self.CHECKS)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise InvoiceRoundingSourceError("invoice_rounding_rows")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "consolidated", bool(dict(checks).get("is_consolidated")))
        object.__setattr__(self, "normalized_checks", checks)
        object.__setattr__(self, "sha256", hashlib.sha256(self.DOMAIN + self._payload).hexdigest())

    def require_check_cache_match(self, supplied):
        """Compare exact post-numeric-fix getters; never call or warm a cache.

        Missing fields require getter None; present NULL requires normalized
        int0. No money projection or active invoice/global policy is certified.
        """
        self._require_check_view(supplied, saved=False)

    def require_saved_check_match(self, supplied):
        """Bind observed saved getters, retaining NULL instead of coercing it.

        A None getter needs exact native NULL or proved metadata/column absence.
        Canonical post-fix int0/1 getters remain supported. No money getter,
        default, fallback setting or source/ORM write participates in this match.
        """
        self._require_check_view(supplied, saved=True)

    def _require_check_view(self, supplied, *, saved):
        try:
            pinned = type(self)(self.financial, self.metadata, self._payload)
            if pinned != self or type(supplied) is not dict or set(supplied) != set(self.CHECKS):
                raise ValueError
            fields = dict(json.loads(pinned._payload)["fields"]) if saved else {}
            for name, expected in pinned.normalized_checks:
                if saved and supplied[name] is None and fields[name] == ["null"]:
                    continue
                if type(supplied[name]) is not type(expected) or supplied[name] != expected:
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise InvoiceRoundingSourceError("invoice_rounding_saved_check_mismatch" if saved else "invoice_rounding_check_cache_mismatch")

    def __repr__(self):
        return "<LockedInvoiceRoundingRead protected PARTIAL controls, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("invoice_rounding_not_serializable")


def _pin_read(value):
    if type(value) is not LockedInvoiceRoundingRead:
        raise ValueError
    pinned = LockedInvoiceRoundingRead(value.financial, value.metadata, value._payload)
    if pinned != value:
        raise ValueError
    return pinned


class MariaDBInvoiceRoundingReader:
    """Same borrowed handle; no cleanup/retry, and failed reads poison it.

    Caller must authorize the financial graph plus the additional controls and
    prove API/cache provenance. The financial recheck acquires table metadata
    locks before the fixed optional-column inspection. Nothing discovers a site.
    """

    READ_TYPE = LockedInvoiceRoundingRead
    PIN_READ = staticmethod(_pin_read)

    def __init__(self, connection):
        self._financial = MariaDBInvoiceFinancialReader(connection)
        self._connection, self._failed = connection, False

    def _columns(self, cursor, meta):
        fields = self.READ_TYPE.FIELDS
        cursor.execute("SELECT SUBSTRING(COLUMN_NAME,1,141) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND BINARY TABLE_NAME=%s "
            "AND COLUMN_NAME IN (" + ",".join(("%s",) * len(fields)) + ") ORDER BY BINARY COLUMN_NAME LIMIT " + str(len(fields) + 1),
            ("tab" + meta.name, *fields))
        rows = cursor.fetchall()
        expected = tuple((name,) for name in sorted(fields) if meta.has_field(name))
        if type(rows) not in (tuple, list) or tuple(rows) != expected:
            raise ValueError
        return [row[0] for row in rows]

    def _load(self, financial, applied_metadata):
        target = self.READ_TYPE
        financial, meta = _pin_financial(financial), _meta(applied_metadata,
            profile=target.METADATA_PROFILE, fields=target.FIELDS, checks=target.CHECKS, links=target.LINKS)
        _root(financial, meta, target.OVERLAP)
        self._financial.require_unchanged(financial)
        metadata_reader = MariaDBMetadataSourceReader(self._connection)
        selected_metadata = metadata_reader.load_for_update(meta)
        selected = tuple(name for name in target.FIELDS if meta.has_field(name))
        observed = financial.financial
        with self._connection.cursor() as cursor:
            columns = self._columns(cursor, meta)
            before, _, _ = self._financial._select(cursor, observed.doctype, observed.name, None,
                meta, selected, 1, values=False)
            after, documents, signatures = self._financial._select(cursor, observed.doctype, observed.name, None,
                meta, selected, 1, values=True)
            if before != after or columns != self._columns(cursor, meta):
                raise ValueError
        metadata_reader.require_unchanged(selected_metadata)
        self._financial.require_unchanged(financial)
        doc = documents[0]
        payload = _canonical(dict(profile=target.ROW_PROFILE, financial_sha256=financial.sha256,
            metadata_sha256=selected_metadata.sha256, columns=columns, modified=_scalar(doc.get("modified")),
            types=signatures, fields=[[name, _scalar(doc.get(name)) if meta.has_field(name) else ["absent"]]
                for name in target.FIELDS]))
        return target(financial, selected_metadata, payload)

    def load_for_update(self, financial, *, applied_metadata):
        if self._failed:
            raise InvoiceRoundingSourceError("invoice_rounding_transaction_unusable")
        try:
            return self._load(financial, applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        raise InvoiceRoundingSourceError("invoice_rounding_read")

    def require_unchanged(self, observed):
        if self._failed:
            raise InvoiceRoundingSourceError("invoice_rounding_transaction_unusable")
        try:
            pinned = self.PIN_READ(observed)
            if self._load(pinned.financial, pinned.metadata.applied) != pinned:
                raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return
        raise InvoiceRoundingSourceError("invoice_rounding_changed")

    def __repr__(self):
        return "<MariaDBInvoiceRoundingReader caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("invoice_rounding_not_serializable")
