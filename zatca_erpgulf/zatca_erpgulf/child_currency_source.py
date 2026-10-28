"""Native own-child currency/Company evidence on one caller-owned transaction.

Compose the existing financial preflight/value and metadata readers. The caller
must supply authorized invoice evidence; this reader does not perform saved READ,
discover a tenant, own cleanup, write, repair cache or contact any authority.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .child_field_currency import ChildCurrencyInputs, ChildFieldCurrencyResolution
from .company_currency_source import _pin_read as _pin_company
from .financial_source_observation import (
    TABLE_FIELDS, MAX_ROWS, MAX_PAYLOAD_BYTES, _canonical, _child_type, _name,
    _scalar, _validate_scalar,
)
from .financial_source_sql import (
    LockedInvoiceFinancialRead, MariaDBInvoiceFinancialReader, _native,
    _pin_read as _pin_financial,
)
from .metadata_source import MariaDBMetadataSourceReader, SelectedMetadataRows, _pin_rows
from .source_metadata import CHILD_CURRENCY_PROFILE, CHILD_CURRENCY_FIELDS, SOURCE_FIELDS, _pin_metadata

PROFILE = "invoice-child-currency-source-sql/v1"
FIELDS = ("currency", "company")


class ChildCurrencySourceError(ValueError):
    """Static internal English code, without source or driver disclosure."""


def _declaration(meta):
    meta = _pin_metadata(meta)
    if meta.profile != CHILD_CURRENCY_PROFILE or meta.name not in CHILD_CURRENCY_FIELDS:
        raise ValueError
    for name, target in (("currency", "Currency"), ("company", "Company")):
        definition = meta.get_field(name)
        if definition is not None and (definition.fieldtype != "Link" or definition.options != target):
            raise ValueError
    return meta


def _binding(financial, parentfield):
    if type(parentfield) is not str or parentfield not in TABLE_FIELDS:
        raise ValueError
    observed = financial.financial
    metas = {row.applied.name: row.applied for row in financial.metadata}
    root = metas[observed.doctype]
    child = _child_type(observed.doctype, parentfield)
    definition = root.get_field(parentfield)
    if definition is None or definition.fieldtype != "Table" or definition.options != child:
        raise ValueError
    body = json.loads(observed._payload)
    rows = dict(body["tables"])[parentfield]["rows"]
    revisions = dict(json.loads(financial._payload)["revisions"])[parentfield]
    return root, metas[child], body, [[row[0], row[1], revision[1]] for row, revision in zip(rows, revisions)]


def _overlap(child, applied):
    """Advance-deduction currency is ALREADY selected by financial v1."""
    overlap = tuple(name for name in FIELDS if name in SOURCE_FIELDS[child.name])
    if any(child.get_field(name) != applied.get_field(name) for name in overlap):
        raise ValueError
    return overlap


@dataclass(frozen=True, repr=False)
class LockedChildCurrencyRead:
    """Exact row membership/links bound to native financial evidence, NOT ACL."""

    financial: LockedInvoiceFinancialRead = field(repr=False)
    parentfield: str = field(repr=False)
    metadata: SelectedMetadataRows = field(repr=False)
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            financial, metadata = _pin_financial(self.financial), _pin_rows(self.metadata)
            _, child, financial_body, identities = _binding(financial, self.parentfield)
            applied = _declaration(metadata.applied)
            overlap = _overlap(child, applied)
            if applied.name != child.name or type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            selected = tuple(name for name in FIELDS if applied.has_field(name))
            if (type(body) is not dict or set(body) != {"profile", "financial_sha256", "parentfield", "metadata_sha256", "columns", "types", "rows"}
                    or body["profile"] != PROFILE or body["financial_sha256"] != financial.sha256
                    or body["parentfield"] != self.parentfield or body["metadata_sha256"] != metadata.sha256
                    or body["columns"] != sorted(selected) or _canonical(body) != self._payload
                    or type(body["types"]) is not list or [row[0] for row in body["types"]] != list(selected)
                    or type(body["rows"]) is not list or len(body["rows"]) != len(identities)):
                raise ValueError
            signatures = dict(body["types"])
            if any(type(entry) is not list or len(entry) != 2 for entry in body["types"]):
                raise ValueError
            # Validate signatures even for an empty child table.
            for name, signature in body["types"]:
                _native(None, "Link", signature)
            financial_rows = dict(financial_body["tables"])[self.parentfield]["rows"]
            for row, identity, financial_row in zip(body["rows"], identities, financial_rows):
                if (type(row) is not list or len(row) != 4 or type(row[1]) is not int
                        or row[:3] != identity):
                    raise ValueError
                projection = row[3]
                if type(projection) is not list or [entry[0] for entry in projection] != list(FIELDS):
                    raise ValueError
                parent_values = dict(financial_row[2])
                for entry in projection:
                    if type(entry) is not list or len(entry) != 2:
                        raise ValueError
                    name, encoded = entry
                    if name in overlap and encoded != parent_values[name]:
                        raise ValueError
                    if not applied.has_field(name):
                        if encoded != ["absent"]:
                            raise ValueError
                        continue
                    value = _validate_scalar(encoded)
                    _native(value, "Link", signatures[name])
                    if value:
                        _name(value)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ChildCurrencySourceError("child_currency_source_rows")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-invoice-child-currency-source-sql/v1\0" + self._payload).hexdigest())

    def inputs_for(self, row_name, *, company_currency=None):
        """Build saved-row declarations; no implicit parent Company/parent_doc.

        A supplied own-Company proof must already be authorized and captured on
        the caller's transaction. Its type/name binding is not provenance proof.
        """
        try:
            pinned = _pin_read(self)
            _name(row_name)
            root, child, financial, _ = _binding(pinned.financial, pinned.parentfield)
            rows = [row for row in json.loads(pinned._payload)["rows"] if row[0] == row_name]
            if len(rows) != 1:
                raise ValueError
            values = dict(rows[0][3])
            lookup = ()
            if company_currency is not None:
                company = _pin_company(company_currency)
                if values["company"] != ["str", company.name]:
                    raise ValueError
                lookup = (company.name, ("str", company.currency))
            return ChildCurrencyInputs(child.name, row_name, root.name,
                pinned.financial.financial.name, pinned.parentfield,
                tuple(values["currency"]), tuple(values["company"]), root.has_field("currency"),
                tuple(dict(financial["header"])["currency"]), company_lookup=lookup)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ChildCurrencySourceError("child_currency_source_inputs")

    def resolve_currency(self, row_name, fieldname, *, company_currency=None):
        """Delegate direct-child semantics to the existing pure contract."""
        try:
            inputs = self.inputs_for(row_name, company_currency=company_currency)
            _, child, _, _ = _binding(self.financial, self.parentfield)
            return ChildFieldCurrencyResolution(child, fieldname, inputs, self.financial.financial.erp_major)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise ChildCurrencySourceError("child_currency_source_resolution")

    def __repr__(self):
        return "<LockedChildCurrencyRead protected PARTIAL native child links, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("child_currency_source_not_serializable")


def _pin_read(observed):
    if type(observed) is not LockedChildCurrencyRead:
        raise ValueError
    pinned = LockedChildCurrencyRead(observed.financial, observed.parentfield, observed.metadata, observed._payload)
    if pinned != observed:
        raise ValueError
    return pinned


class MariaDBChildCurrencyReader:
    """Bounded metadata/column/child reads on the caller's unchanged handle.

    First recheck native financial evidence, acquiring normal table metadata
    locks before inspecting selected physical column membership. Recheck values,
    metadata and financial membership before returning. No cleanup or retry.
    """

    def __init__(self, connection):
        self._financial = MariaDBInvoiceFinancialReader(connection)
        self._connection, self._failed = connection, False

    def _columns(self, cursor, applied):
        # Fixed field/table allowlists; never discover unrelated columns/values.
        cursor.execute("SELECT SUBSTRING(COLUMN_NAME,1,141) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND BINARY TABLE_NAME=%s "
            "AND COLUMN_NAME IN (%s,%s) ORDER BY BINARY COLUMN_NAME LIMIT 3",
            ("tab" + applied.name, *FIELDS))
        rows = cursor.fetchall()
        expected = tuple((name,) for name in sorted(FIELDS) if applied.has_field(name))
        if type(rows) not in (tuple, list) or tuple(rows) != expected:
            raise ValueError
        return [row[0] for row in rows]

    def _load(self, financial, parentfield, applied):
        financial, applied = _pin_financial(financial), _declaration(applied)
        _, child, _, _ = _binding(financial, parentfield)
        if applied.name != child.name:
            raise ValueError
        _overlap(child, applied)
        self._financial.require_unchanged(financial)
        metadata_reader = MariaDBMetadataSourceReader(self._connection)
        metadata = metadata_reader.load_for_update(applied)
        selected = tuple(name for name in FIELDS if applied.has_field(name))
        observed = financial.financial
        with self._connection.cursor() as cursor:
            columns = self._columns(cursor, applied)
            before, _, _ = self._financial._select(cursor, observed.doctype, observed.name,
                parentfield, applied, selected, MAX_ROWS, values=False)
            size = sum(sum(length or 0 for length in lengths)
                + sum(len(value.encode("utf-8")) for value in identity if type(value) is str)
                for identity, lengths in before)
            if size > MAX_PAYLOAD_BYTES:
                raise ValueError
            after, documents, signatures = self._financial._select(cursor, observed.doctype, observed.name,
                parentfield, applied, selected, MAX_ROWS, values=True)
            if before != after or self._columns(cursor, applied) != columns:
                raise ValueError
        metadata_reader.require_unchanged(metadata)
        self._financial.require_unchanged(financial)
        rows = [[doc.name, doc.get("idx"), _scalar(doc.get("modified")),
            [[name, _scalar(doc.get(name)) if applied.has_field(name) else ["absent"]] for name in FIELDS]]
            for doc in documents]
        payload = _canonical(dict(profile=PROFILE, financial_sha256=financial.sha256,
            parentfield=parentfield, metadata_sha256=metadata.sha256, columns=columns,
            types=signatures, rows=rows))
        return LockedChildCurrencyRead(financial, parentfield, metadata, payload)

    def load_for_update(self, financial, parentfield, *, applied_metadata):
        if self._failed:
            raise ChildCurrencySourceError("child_currency_source_transaction_unusable")
        try:
            result = self._load(financial, parentfield, applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return result
        raise ChildCurrencySourceError("child_currency_source_read")

    def require_unchanged(self, observed):
        if self._failed:
            raise ChildCurrencySourceError("child_currency_source_transaction_unusable")
        try:
            expected = _pin_read(observed)
            if self._load(expected.financial, expected.parentfield, expected.metadata.applied) != expected:
                raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return
        raise ChildCurrencySourceError("child_currency_source_changed")

    def __repr__(self):
        return "<MariaDBChildCurrencyReader explicit caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("child_currency_source_not_serializable")
