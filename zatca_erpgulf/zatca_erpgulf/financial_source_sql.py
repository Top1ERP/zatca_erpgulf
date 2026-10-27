"""Selected invoice-owned SQL data with native scalars and explicit metadata.

No ORM conversion, money calculation, source discovery, permission/provider
installation, writes, commit/cleanup or HTTP. The caller owns and authorizes the
exact transaction; this PARTIAL read is not a complete preparation source guard.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace

from pymysql.constants import FIELD_TYPE as FT

from . import financial_source_observation as financial
from .financial_source_observation import InvoiceFinancialObservation
from .metadata_source import (
    MariaDBMetadataSourceReader, SelectedMetadataRows, _modified,
    _pin_rows as _pin_metadata_rows,
)
from .source_metadata import _pin_metadata

PROFILE = "invoice-owned-native-sql/v1"
SCALAR_MODE = "native-sql-no-orm-coercion/v1"
INTEGER_CODES = frozenset((FT.TINY, FT.SHORT, FT.LONG, FT.LONGLONG, FT.INT24))
DECIMAL_CODES = frozenset((FT.DECIMAL, FT.NEWDECIMAL))
REAL_CODES = frozenset((FT.FLOAT, FT.DOUBLE))
TEXT_CODES = frozenset((FT.VARCHAR, FT.VAR_STRING, FT.STRING, FT.TINY_BLOB,
    FT.MEDIUM_BLOB, FT.LONG_BLOB, FT.BLOB, FT.JSON, FT.ENUM, FT.SET))
TEXT_TYPES = frozenset(("Data", "Select", "Link", "Dynamic Link", "Read Only", "Text", "Small Text",
    "Long Text", "Code", "Text Editor", "Markdown Editor", "HTML Editor", "JSON", "Geolocation",
    "Attach", "Attach Image", "Signature", "Color", "Barcode", "Icon", "Phone", "Autocomplete"))
REAL_TYPES = frozenset(("Currency", "Float", "Percent", "Rating", "Duration"))
ROOT_IDS = ("name", "modified")
CHILD_IDS = ("name", "parent", "parenttype", "parentfield", "idx", "modified")


class FinancialSQLSourceError(ValueError):
    """Static internal code without customer, payment or driver disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _codes(fieldtype):
    if fieldtype in ("Int", "Long Int", "Check"): return INTEGER_CODES
    if fieldtype in REAL_TYPES: return DECIMAL_CODES | REAL_CODES
    if fieldtype in TEXT_TYPES: return TEXT_CODES
    if fieldtype == "Date": return frozenset((FT.DATE, FT.NEWDATE))
    if fieldtype == "Datetime": return frozenset((FT.DATETIME, FT.TIMESTAMP))
    if fieldtype == "Time": return frozenset((FT.TIME,))
    raise ValueError


def _signature(value):
    if (type(value) is not list or len(value) != 4 or type(value[0]) is not int
            or any(item is not None and (type(item) is not int or not 0 <= item < 2**32)
                for item in value[1:3]) or value[3] is not None and type(value[3]) is not bool):
        raise ValueError
    if value[0] in DECIMAL_CODES and (value[1] is None or value[2] is None or value[2] > value[1]):
        raise ValueError
    return value[0]


def _native(value, fieldtype, signature):
    code = _signature(signature)
    if code not in _codes(fieldtype):
        raise ValueError
    financial._scalar(value)  # Existing finite/text/number/time bounds; no coercion.
    if value is None: return
    if code in DECIMAL_CODES:
        if type(value) is not Decimal or signature[2] is None or value.as_tuple().exponent != -signature[2]:
            raise ValueError  # Reject Frappe float/normalized-Decimal decoders.
    elif code in REAL_CODES:
        if type(value) is not float: raise ValueError
    elif code in INTEGER_CODES:
        if type(value) is not int: raise ValueError
    elif code in TEXT_CODES:
        if type(value) is not str: raise ValueError
    elif code in (FT.DATE, FT.NEWDATE):
        if type(value) is not date: raise ValueError
    elif code in (FT.DATETIME, FT.TIMESTAMP):
        if type(value) is not datetime or value.tzinfo is not None: raise ValueError
    elif code == FT.TIME:
        if type(value) is not timedelta: raise ValueError


def _manifest(doctype, metas):
    if doctype not in ("Sales Invoice", "POS Invoice") or type(metas) is not dict:
        raise ValueError
    root = metas[doctype]
    present = tuple(name for name in financial.TABLE_FIELDS if root.has_field(name))
    if not {"items", "taxes"} <= set(present): raise ValueError
    expected = {doctype}
    for name in present:
        child = financial._child_type(doctype, name)
        definition = root.get_field(name)
        if definition.fieldtype != "Table" or definition.options != child:
            raise ValueError
        expected.add(child)
    if set(metas) != expected or any(meta.name != name for name, meta in metas.items()):
        raise ValueError
    for name in financial.REQUIRED_HEADER:
        if not root.has_field(name): raise ValueError
    for table in present:
        meta = metas[financial._child_type(doctype, table)]
        if any(not meta.has_field(name) for name in financial.CHILD_REQUIRED[table]): raise ValueError
    return present


def _fields(meta, fields):
    present = tuple(name for name in fields if meta.has_field(name))
    for name in present: _codes(meta.get_field(name).fieldtype)
    return present


@dataclass(frozen=True, repr=False)
class LockedInvoiceFinancialRead:
    """Protected raw SQL financial/metadata binding, NOT an ORM-equivalent view."""

    financial: InvoiceFinancialObservation = field(repr=False)
    metadata: tuple[SelectedMetadataRows, ...] = field(repr=False)
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            observed = financial._pin_financial(self.financial)
            if type(self.metadata) is not tuple or not 3 <= len(self.metadata) <= 6:
                raise ValueError
            metadata = tuple(_pin_metadata_rows(row) for row in self.metadata)
            names = tuple(row.applied.name for row in metadata)
            if names != tuple(sorted(set(names))): raise ValueError
            metas = {row.applied.name: row.applied for row in metadata}
            present = _manifest(observed.doctype, metas)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= financial.MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "scalar_mode", "financial_sha256", "metadata", "types", "revisions"}
                    or body["profile"] != PROFILE or body["scalar_mode"] != SCALAR_MODE
                    or body["financial_sha256"] != observed.sha256
                    or body["metadata"] != [[row.applied.name, row.sha256] for row in metadata]
                    or financial._canonical(body) != self._payload):
                raise ValueError
            data = json.loads(observed._payload)
            _modified(data["modified"])
            table_data = dict(data["tables"])
            groups = ("header", *present)
            if (type(body["types"]) is not list or [row[0] for row in body["types"]] != list(groups)
                    or type(body["revisions"]) is not list or [row[0] for row in body["revisions"]] != list(present)):
                raise ValueError
            for group, types in body["types"]:
                meta = metas[observed.doctype if group == "header" else financial._child_type(observed.doctype, group)]
                allowed = financial.HEADER_FIELDS if group == "header" else financial.TABLE_FIELDS[group]
                selected = _fields(meta, allowed)
                if type(types) is not list or [row[0] for row in types] != list(selected): raise ValueError
                for entry in types:
                    if type(entry) is not list or len(entry) != 2: raise ValueError
                    if _signature(entry[1]) not in _codes(meta.get_field(entry[0]).fieldtype): raise ValueError
                projections = [data["header"]] if group == "header" else [row[2] for row in table_data[group]["rows"]]
                for projection in projections:
                    values = dict(projection)
                    if tuple(name for name in allowed if values[name] != ["absent"]) != selected: raise ValueError
                    for name, signature in types:
                        _native(financial._validate_scalar(values[name]), meta.get_field(name).fieldtype, signature)
                if group != "header" and table_data[group]["presence"] != [meta.has_field(name) for name in allowed]:
                    raise ValueError
            for table, revisions in body["revisions"]:
                if type(revisions) is not list or len(revisions) != len(table_data[table]["rows"]): raise ValueError
                for revision, row in zip(revisions, table_data[table]["rows"]):
                    if type(revision) is not list or len(revision) != 2 or revision[0] != row[0]: raise ValueError
                    _modified(revision[1], nullable=True)
            # Absent optional tables may not acquire invented schema or values.
            if any(table_data[name] != ["absent"] for name in financial.TABLE_FIELDS if name not in present):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid: raise FinancialSQLSourceError("financial_sql_rows")
        object.__setattr__(self, "financial", observed)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-invoice-owned-native-sql/v1\0" + self._payload).hexdigest())

    def __repr__(self):
        return "<LockedInvoiceFinancialRead protected PARTIAL native SQL, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("financial_sql_not_serializable")


def _pin_read(observed):
    if type(observed) is not LockedInvoiceFinancialRead: raise ValueError
    pinned = LockedInvoiceFinancialRead(observed.financial, observed.metadata, observed._payload)
    if pinned != observed: raise ValueError
    return pinned


def _identity(ids, *, doctype, name, table):
    financial._name(ids[0])
    if table is None:
        if ids[0] != name: raise ValueError
        _modified(financial._scalar(ids[1]))
    else:
        if ids[1:4] != (name, doctype, table) or type(ids[4]) is not int or ids[4] <= 0:
            raise ValueError
        _modified(financial._scalar(ids[5]), nullable=True)


class MariaDBInvoiceFinancialReader:
    """Fixed projections on an authorized caller-owned transaction; no cleanup.

    Length/identity preflight bounds returned data before value projection. SQL
    masks oversized concurrent values and rejects preflight/full drift. RC still
    needs a completion-boundary recheck and a reviewed full graph lock strategy.
    """

    def __init__(self, connection):
        if not callable(getattr(connection, "cursor", None)):
            raise FinancialSQLSourceError("financial_sql_connection")
        self._connection, self._failed = connection, False

    def __repr__(self):
        return "<MariaDBInvoiceFinancialReader explicit caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("financial_sql_reader_not_serializable")

    def _select(self, cursor, doctype, name, table, meta, selected, limit, *, values):
        ids = ROOT_IDS if table is None else CHILD_IDS
        columns = ["SUBSTRING(`" + field + "`,1,141)" if field not in ("idx", "modified") else "`" + field + "`" for field in ids]
        for field in selected:
            if values:
                columns.append("CASE WHEN OCTET_LENGTH(`" + field + "`)<=65536 OR `" + field
                    + "` IS NULL THEN `" + field + "` ELSE NULL END")
            columns.append("OCTET_LENGTH(`" + field + "`)")
        where = "`name`=%s" if table is None else "`parent`=%s AND `parenttype`=%s AND `parentfield`=%s"
        params = (name,) if table is None else (name, doctype, table)
        order = "BINARY `name`" if table is None else "`idx`,BINARY `name`"
        cursor.execute("SELECT " + ",".join(columns) + " FROM `tab" + meta.name + "` WHERE " + where
            + " ORDER BY " + order + " LIMIT %s FOR UPDATE", (*params, limit + 1))
        rows = cursor.fetchall()
        if type(rows) not in (tuple, list) or len(rows) > limit: raise ValueError
        if table is None and len(rows) != 1: raise ValueError
        description = cursor.description
        signatures = []
        if values:
            if type(description) not in (tuple, list) or len(description) != len(columns): raise ValueError
            for index, field in enumerate(selected):
                entry = description[len(ids) + index * 2]
                if type(entry) not in (tuple, list) or len(entry) != 7: raise ValueError
                signature = [entry[1], entry[4], entry[5], entry[6]]
                if _signature(signature) not in _codes(meta.get_field(field).fieldtype): raise ValueError
                signatures.append([field, signature])
        projected, documents = [], []
        for row in rows:
            if type(row) is not tuple or len(row) != len(columns): raise ValueError
            identity = row[:len(ids)]
            _identity(identity, doctype=doctype, name=name, table=table)
            lengths = row[len(ids) + (1 if values else 0)::(2 if values else 1)]
            if any(length is not None and (type(length) is not int or not 0 <= length <= financial.MAX_TEXT_BYTES) for length in lengths):
                raise ValueError
            projected.append((identity, lengths))
            if values:
                data = dict(zip(ids, identity))
                for index, (field, signature) in enumerate(signatures):
                    value = row[len(ids) + index * 2]
                    if (value is None) != (lengths[index] is None): raise ValueError
                    _native(value, meta.get_field(field).fieldtype, signature)
                    data[field] = value
                documents.append(SimpleNamespace(doctype=meta.name, name=identity[0], get=data.get))
        return projected, documents, signatures

    def _load(self, doctype, name, erp_major, applied_metadata):
        financial._name(name)
        if type(erp_major) is not int or erp_major not in (15, 16) or type(applied_metadata) is not dict: raise ValueError
        metas = {key: _pin_metadata(value) for key, value in applied_metadata.items()}
        present = _manifest(doctype, metas)
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            setting = cursor.fetchone()
            if type(setting) is not tuple or len(setting) != 1 or type(setting[0]) is not int or setting[0] != 0: raise ValueError
        metadata_reader = MariaDBMetadataSourceReader(self._connection)
        metadata = tuple(metadata_reader.load_for_update(metas[key]) for key in sorted(metas))
        root, child_metas = metas[doctype], {table: metas[financial._child_type(doctype, table)] for table in present}
        tables, types, revisions, rows_used, bytes_used = {}, [], [], 0, 0
        for table in (None, *present):
            meta = root if table is None else child_metas[table]
            allowed = financial.HEADER_FIELDS if table is None else financial.TABLE_FIELDS[table]
            selected = _fields(meta, allowed)
            limit = 1 if table is None else financial.MAX_ROWS - rows_used
            with self._connection.cursor() as cursor:
                before, _, _ = self._select(cursor, doctype, name, table, meta, selected, limit, values=False)
                bytes_used += sum(sum(length or 0 for length in lengths)
                    + sum(len(value.encode("utf-8")) for value in identity if type(value) is str) for identity, lengths in before)
                if bytes_used > financial.MAX_PAYLOAD_BYTES: raise ValueError
                after, documents, signatures = self._select(cursor, doctype, name, table, meta, selected, limit, values=True)
            if after != before: raise ValueError
            types.append(["header" if table is None else table, signatures])
            if table is None:
                document = documents[0]
            else:
                tables[table] = documents
                rows_used += len(documents)
                revisions.append([table, [[identity[0], financial._scalar(identity[5])] for identity, _ in after]])
        get_header = document.get
        document.meta = root
        document.get = lambda field: tables[field] if field in tables else get_header(field)
        observed = financial.capture_invoice_financial_observation(document, erp_major=erp_major, child_metas=child_metas)
        for row in metadata: metadata_reader.require_unchanged(row)
        payload = financial._canonical(dict(profile=PROFILE, scalar_mode=SCALAR_MODE, financial_sha256=observed.sha256,
            metadata=[[row.applied.name, row.sha256] for row in metadata], types=types, revisions=revisions))
        return LockedInvoiceFinancialRead(observed, metadata, payload)

    def load_for_update(self, doctype, name, *, erp_major, applied_metadata):
        if self._failed: raise FinancialSQLSourceError("financial_sql_transaction_unusable")
        try:
            result = self._load(doctype, name, erp_major, applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception): raise
        else:
            return result
        raise FinancialSQLSourceError("financial_sql_read")

    def require_unchanged(self, observed):
        if self._failed: raise FinancialSQLSourceError("financial_sql_transaction_unusable")
        try:
            expected = _pin_read(observed)
            metas = {row.applied.name: row.applied for row in expected.metadata}
            current = self._load(expected.financial.doctype, expected.financial.name, expected.financial.erp_major, metas)
            if current != expected: raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception): raise
        else:
            return
        raise FinancialSQLSourceError("financial_sql_changed")
