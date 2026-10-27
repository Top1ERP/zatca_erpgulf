"""Bounded locked DocType/DocField/customization reads, never installed here.

The caller authorizes and owns one exact SQL transaction and supplies applied
metadata. No Meta/record/cache discovery, writes, evaluation, commit, cleanup or
HTTP. This reads a selected metadata dependency, not a complete preparation
source or proof of tenant/provider/committed origin.
"""

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from types import SimpleNamespace

from frappe.model.meta import get_default_df
from frappe.model import data_fieldtypes, no_value_fields

from .financial_source_observation import (
    MAX_PAYLOAD_BYTES, _canonical, _name, _scalar, _validate_projection, _validate_scalar,
)
from .metadata_reconciliation import (
    CAST_TYPES, EDITABLE, FRAMEWORK_VERSION, MAX_CUSTOM_FIELDS,
    MAX_SETTERS, SETTER_FIELDS, FieldCustomizationMatch, reconcile_field_customizations,
)
from .source_metadata import BASE_TYPES, PROPERTIES, SOURCE_FIELDS, SourceMetadata, _pin_metadata, project_source_metadata

PROFILE = "selected-metadata-sql-rows/v1"
MAX_TEXT_BYTES = 8192
FIELD_TYPES = frozenset((*data_fieldtypes, *no_value_fields)) - {"Password"}
TYPE_FIELDS = ("issingle", "istable", "is_virtual", "custom")
STANDARD_FIELDS = ("parent", "parenttype", "parentfield", "idx", "fieldname", "is_virtual", *EDITABLE)
CUSTOM_SOURCE_FIELDS = ("dt", "idx", "fieldname", "is_virtual", *EDITABLE)
TYPE_SETTERS = ("issingle", "istable", "is_virtual", "custom", "name", "fields")
FIELD_SETTERS = (*PROPERTIES, "is_virtual")
NUMERIC = frozenset(("issingle", "istable", "is_virtual", "custom", "idx",
    "reqd", "read_only", "hidden", "non_negative", "allow_on_submit"))
SPECS = {
    "doctype": ("DocType", TYPE_FIELDS),
    "docfields": ("DocField", STANDARD_FIELDS),
    "custom_fields": ("Custom Field", CUSTOM_SOURCE_FIELDS),
    "property_setters": ("Property Setter", SETTER_FIELDS),
}
PREFLIGHT = {
    "docfields": ("parent", "parenttype", "parentfield", "idx", "fieldname", "is_virtual", "fieldtype"),
    "custom_fields": ("dt", "idx", "fieldname", "is_virtual", "fieldtype"),
    "property_setters": SETTER_FIELDS[:-1],
}


class MetadataSourceError(ValueError):
    """Static English codes without defaults, identities or driver detail."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _modified(encoded, *, nullable=False):
    value = _validate_scalar(encoded)
    if value is None and nullable:
        return
    if type(value) is not datetime or value.tzinfo is not None:
        raise ValueError


def _record(record, fields, *, nullable=False):
    if type(record) is not dict or set(record) != {"name", "modified", "header"}:
        raise ValueError
    _name(record["name"])
    _modified(record["modified"], nullable=nullable)
    _validate_projection(record["header"], fields, fields)
    values = {name: _validate_scalar(value) for name, value in record["header"]}
    for name, value in values.items():
        if name in NUMERIC:
            if value is not None and (type(value) is not int or not 0 <= value < 2**31
                    or (name != "idx" and value not in (0, 1))):
                raise ValueError
        elif value is not None and (type(value) is not str or len(value.encode("utf-8")) > MAX_TEXT_BYTES):
            raise ValueError
    return values


def _scope(doctype, group, values):
    selected = SOURCE_FIELDS[doctype]
    if group == "doctype":
        if values["is_virtual"] != 0 or any(type(values[name]) is not int for name in TYPE_FIELDS):
            raise ValueError
    elif group in ("docfields", "custom_fields"):
        scope = "parent" if group == "docfields" else "dt"
        name = _name(values["fieldname"])
        if (values[scope] != doctype or name not in selected or name in BASE_TYPES
                or values["is_virtual"] not in (None, 0) or values["fieldtype"] not in FIELD_TYPES):
            raise ValueError
        _name(values["fieldtype"])
        if group == "docfields" and (values["parenttype"], values["parentfield"]) != ("DocType", "fields"):
            raise ValueError
    else:
        if (values["doc_type"] != doctype or values["doctype_or_field"] != "DocField"
                or values["field_name"] not in selected or values["field_name"] in BASE_TYPES
                or values["property"] not in EDITABLE or values["property_type"] not in CAST_TYPES):
            raise ValueError


def _rows(doctype, group, records, *, preflight=False):
    fields = PREFLIGHT[group] if preflight else SPECS[group][1]
    limit = {"docfields": len(SOURCE_FIELDS[doctype]), "custom_fields": MAX_CUSTOM_FIELDS,
        "property_setters": MAX_SETTERS}[group]
    if type(records) is not list or len(records) > limit:
        raise ValueError
    names, fieldnames, order = set(), set(), []
    for record in records:
        values = _record(record, fields, nullable=group == "docfields")
        _scope(doctype, group, values)
        name = record["name"]
        if name in names:
            raise ValueError
        names.add(name)
        order.append(name)
        if group in ("docfields", "custom_fields"):
            if values["fieldname"] in fieldnames:
                raise ValueError
            fieldnames.add(values["fieldname"])
    if order != sorted(order):
        raise ValueError


def _document(group, record):
    """Narrow already-validated row facade for the existing shared matcher."""
    values = {name: _validate_scalar(value) for name, value in record["header"]}
    return SimpleNamespace(doctype=SPECS[group][0], name=record["name"],
        get=lambda name: _validate_scalar(record["modified"]) if name == "modified" else values.get(name))


def _baseline(doctype, type_values, records):
    definitions = {}
    for record in records:
        values = {name: _validate_scalar(value) for name, value in record["header"]}
        definitions[values["fieldname"]] = values
    meta = SimpleNamespace(name=doctype, issingle=type_values["issingle"], istable=type_values["istable"],
        has_field=definitions.__contains__, get_field=definitions.get)
    # Actual framework helper only; no Meta construction, site or schema guess.
    bases = {name: get_default_df(name) for name in BASE_TYPES if name in SOURCE_FIELDS[doctype]}
    return project_source_metadata(meta, base_fields=bases)


@dataclass(frozen=True, repr=False)
class SelectedMetadataRows:
    """Protected raw membership plus matched applied declarations; not origin."""

    applied: SourceMetadata = field(repr=False)
    _payload: bytes = field(repr=False)
    base: SourceMetadata = field(init=False, repr=False)
    match: FieldCustomizationMatch = field(init=False, repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            applied = _pin_metadata(self.applied)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "framework_version", "source_doctype", *SPECS}
                    or body["profile"] != PROFILE or body["framework_version"] != FRAMEWORK_VERSION
                    or body["source_doctype"] != applied.name or _canonical(body) != self._payload):
                raise ValueError
            doctype = applied.name
            type_values = _record(body["doctype"], TYPE_FIELDS)
            if body["doctype"]["name"] != doctype:
                raise ValueError
            _scope(doctype, "doctype", type_values)
            for group in PREFLIGHT:
                _rows(doctype, group, body[group])
            base = _baseline(doctype, type_values, body["docfields"])
            matched = reconcile_field_customizations(base, applied,
                custom_fields=[_document("custom_fields", row) for row in body["custom_fields"]],
                property_setters=[_document("property_setters", row) for row in body["property_setters"]])
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise MetadataSourceError("metadata_source_rows")
        object.__setattr__(self, "applied", applied)
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "match", matched)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-selected-metadata-sql/v1\0" + self._payload
            + bytes.fromhex(applied.sha256)).hexdigest())

    def __repr__(self):
        return "<SelectedMetadataRows protected SQL declarations matched, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("metadata_source_not_serializable")


def _pin_rows(observed):
    if type(observed) is not SelectedMetadataRows:
        raise ValueError
    pinned = SelectedMetadataRows(observed.applied, observed._payload)
    if pinned != observed:
        raise ValueError
    return pinned


def _literals(values):
    """Quote fixed framework/property catalogs only, never request values."""
    return ",".join("'" + value.replace("'", "''") + "'" for value in sorted(values))


def _columns(fields):
    columns = ["SUBSTRING(`name`,1,141)", "`modified`"]
    for name in fields:
        if name in NUMERIC:
            columns.append("`" + name + "`")
        elif name == "default":
            columns.append("CASE WHEN BINARY `fieldtype` IN (" + _literals(FIELD_TYPES)
                + ") THEN SUBSTRING(`default`,1,8193) ELSE NULL END")
        elif name == "value":
            columns.append("CASE WHEN BINARY `doctype_or_field`=BINARY 'DocField' AND BINARY `property_type` IN ("
                + _literals(CAST_TYPES) + ") AND BINARY `property` IN (" + _literals(EDITABLE)
                + ") THEN SUBSTRING(`value`,1,8193) ELSE NULL END")
        else:
            columns.append("SUBSTRING(`" + name + "`,1,8193)")
    return ",".join(columns)


class MariaDBMetadataSourceReader:
    """Fixed-table selected metadata on one authorized caller-owned handle.

    Existing rows stay locked; RC insertions require boundary rechecks. Own
    pending writes remain visible. No ownership/ACL/tenant attestation or cleanup
    is inferred from a cursor. Errors poison this reader without retries.
    """

    def __init__(self, connection):
        if not callable(getattr(connection, "cursor", None)):
            raise MetadataSourceError("metadata_source_connection")
        self._connection, self._failed = connection, False

    def __repr__(self):
        return "<MariaDBMetadataSourceReader explicit caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("metadata_source_reader_not_serializable")

    def _select(self, cursor, doctype, group, *, preflight=False):
        table, fields = SPECS[group]
        if preflight:
            fields = PREFLIGHT[group]
        selected = SOURCE_FIELDS[doctype]
        placeholders = ",".join("%s" for _ in selected)
        if group == "doctype":
            where, params, limit = "`name`=%s", (doctype,), 1
        elif group in ("docfields", "custom_fields"):
            scope = "parent" if group == "docfields" else "dt"
            where = "`" + scope + "`=%s AND `fieldname` IN (" + placeholders + ")"
            params = (doctype, *selected)
            limit = len(selected) if group == "docfields" else MAX_CUSTOM_FIELDS
        else:
            where = "`doc_type`=%s AND ((`field_name` IN (" + placeholders + ") AND `property` IN ("
            where += ",".join("%s" for _ in FIELD_SETTERS) + ")) OR (`doctype_or_field`='DocType' AND `property` IN ("
            where += ",".join("%s" for _ in TYPE_SETTERS) + ")))"
            params = (doctype, *selected, *FIELD_SETTERS, *TYPE_SETTERS)
            limit = MAX_SETTERS
        cursor.execute("SELECT " + _columns(fields) + " FROM `tab" + table + "` WHERE " + where
            + " ORDER BY BINARY `name` LIMIT %s FOR UPDATE", (*params, limit + 1))
        raw = cursor.fetchall()
        if type(raw) not in (tuple, list) or len(raw) > limit:
            raise ValueError
        records = []
        for row in raw:
            if type(row) is not tuple or len(row) != 2 + len(fields):
                raise ValueError
            records.append(dict(name=row[0], modified=_scalar(row[1]),
                header=[[name, _scalar(value)] for name, value in zip(fields, row[2:])]))
        return records

    def _load(self, applied):
        applied = _pin_metadata(applied)
        doctype = applied.name
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT @@session.autocommit")
            setting = cursor.fetchone()
            if type(setting) is not tuple or len(setting) != 1 or type(setting[0]) is not int or setting[0] != 0:
                raise ValueError
            records = self._select(cursor, doctype, "doctype")
            if len(records) != 1 or records[0]["name"] != doctype:
                raise ValueError
            values = _record(records[0], TYPE_FIELDS)
            _scope(doctype, "doctype", values)
            body = dict(profile=PROFILE, framework_version=FRAMEWORK_VERSION, doctype=records[0])
            for group in PREFLIGHT:
                preflight = self._select(cursor, doctype, group, preflight=True)
                _rows(doctype, group, preflight, preflight=True)
                complete = self._select(cursor, doctype, group)
                projected = [dict(name=row["name"], modified=row["modified"],
                    header=[[name, value] for name, value in row["header"] if name in PREFLIGHT[group]]) for row in complete]
                if projected != preflight:
                    raise ValueError
                body[group] = complete
        # The requested name is explicit and separate from the stored type row.
        body["source_doctype"] = doctype
        return SelectedMetadataRows(applied, _canonical(body))

    def load_for_update(self, applied):
        if self._failed:
            raise MetadataSourceError("metadata_source_transaction_unusable")
        try:
            result = self._load(applied)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return result
        raise MetadataSourceError("metadata_source_read")

    def require_unchanged(self, observed):
        if self._failed:
            raise MetadataSourceError("metadata_source_transaction_unusable")
        try:
            expected = _pin_rows(observed)
            if self._load(expected.applied) != expected:
                raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return
        raise MetadataSourceError("metadata_source_changed")
