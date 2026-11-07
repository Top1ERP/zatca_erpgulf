"""Bounded native POS lookups on one explicitly authorized borrowed transaction.

Limit and default-payment reads are separate: an unconsumed default must not
invalidate a limit-only branch. Missing masters and ambiguous/orphan defaults
require review; never turn them into a zero limit or an arbitrary first row.
This internal source reader supplies no saved ACL/provider/cache provenance,
account eligibility, transaction cleanup, writes, jobs or tax authority calls.
"""

from dataclasses import dataclass, field
import hashlib
import json

from .financial_source_observation import (
    _canonical, _name, _scalar, _validate_projection, _validate_scalar,
)
from .financial_source_sql import (
    LockedInvoiceFinancialRead, MariaDBInvoiceFinancialReader, _native, _pin_read as _pin_financial,
)
from .metadata_source import MariaDBMetadataSourceReader, SelectedMetadataRows, _modified, _pin_rows
from .source_metadata import POS_LIMIT_PROFILE, POS_DEFAULT_PROFILE, _pin_metadata
from .calculation_pos_adjustments import PosLimitObservation, DefaultMopObservation

PROFILE = "invoice-pos-lookup-native-sql/v1"
MAX_PAYMENTS = 128
LIMIT_FIELDS = ("company", "write_off_limit")
PAYMENT_FIELDS = ("mode_of_payment", "default", "allow_in_returns")


class PosProfileSourceError(ValueError):
    """Static English diagnostics, without profile/payment/driver disclosure."""


def _metas(kind, values):
    if type(kind) is not str or kind not in ("limit", "default") or type(values) is not dict:
        raise ValueError
    names = ("POS Profile",) if kind == "limit" else ("POS Payment Method", "POS Profile")
    if set(values) != set(names):
        raise ValueError
    profile = POS_LIMIT_PROFILE if kind == "limit" else POS_DEFAULT_PROFILE
    expected = {"POS Profile": (("company", "Link", "Company"),)}
    if kind == "limit":
        expected["POS Profile"] += (("write_off_limit", "Currency", None),)
    else:
        expected["POS Profile"] += (("payments", "Table", "POS Payment Method"),)
        expected["POS Payment Method"] = (
            ("mode_of_payment", "Link", "Mode of Payment"),
            ("default", "Check", None), ("allow_in_returns", "Check", None),
        )
    result = {}
    for name in names:
        meta = _pin_metadata(values[name])
        if meta.name != name or meta.profile != profile:
            raise ValueError
        for fieldname, fieldtype, target in expected[name]:
            definition = meta.get_field(fieldname)
            if (definition is None or definition.fieldtype != fieldtype
                    or target is not None and definition.options != target):
                raise ValueError
        result[name] = meta
    return result


def _links(financial):
    root = next(row.applied for row in financial.metadata
                if row.applied.name == financial.financial.doctype)
    for name, target in (("company", "Company"), ("pos_profile", "POS Profile")):
        definition = root.get_field(name)
        if definition is None or definition.fieldtype != "Link" or definition.options != target:
            raise ValueError
    values = dict(json.loads(financial.financial._payload)["header"])
    return tuple(_name(_validate_scalar(values[name])) for name in ("company", "pos_profile"))


def _fields(record, names, meta, signatures):
    _validate_projection(record, names, names)
    if (type(signatures) is not list or len(signatures) != len(names)
            or any(type(row) is not list or len(row) != 2 for row in signatures)
            or tuple(row[0] for row in signatures) != names):
        raise ValueError
    values = {}
    for (name, encoded), (_, signature) in zip(record, signatures):
        value = _validate_scalar(encoded)
        _native(value, meta.get_field(name).fieldtype, signature)
        if meta.get_field(name).fieldtype == "Check" and value is not None:
            if type(value) is not int or value not in (0, 1):
                raise ValueError
        values[name] = value
    return values


@dataclass(frozen=True, repr=False)
class LockedPosProfileRead:
    """Protected consumed lookup, NOT an active provider or acceptance grant."""

    financial: LockedInvoiceFinancialRead = field(repr=False)
    kind: str
    metadata: tuple[SelectedMetadataRows, ...] = field(repr=False)
    _payload: bytes = field(repr=False)
    profile_name: str = field(init=False, repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            financial = _pin_financial(self.financial)
            company, profile_name = _links(financial)
            if type(self.metadata) is not tuple:
                raise ValueError
            metadata = tuple(_pin_rows(row) for row in self.metadata)
            names = tuple(row.applied.name for row in metadata)
            if names != tuple(sorted(set(names))):
                raise ValueError
            metas = _metas(self.kind, {row.applied.name: row.applied for row in metadata})
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= 1024 * 1024:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "kind", "financial_sha256",
                    "metadata", "record", "payments", "types", "default_names"}
                    or body["profile"] != PROFILE or body["kind"] != self.kind
                    or body["financial_sha256"] != financial.sha256
                    or body["metadata"] != [[row.applied.name, row.sha256] for row in metadata]
                    or _canonical(body) != self._payload):
                raise ValueError
            record, types = body["record"], body["types"]
            if (type(record) is not dict or set(record) != {"name", "modified", "fields"}
                    or record["name"] != profile_name or type(types) is not dict
                    or set(types) != {"profile", "payments"}):
                raise ValueError
            _modified(record["modified"])
            fields = LIMIT_FIELDS if self.kind == "limit" else ("company",)
            values = _fields(record["fields"], fields, metas["POS Profile"], types["profile"])
            if values["company"] != company:
                raise ValueError
            payments, default_names = body["payments"], body["default_names"]
            if (type(payments) is not list or len(payments) > MAX_PAYMENTS
                    or type(default_names) is not list or len(default_names) > 1):
                raise ValueError
            if self.kind == "limit":
                if payments != [] or types["payments"] != [] or default_names != []:
                    raise ValueError
            else:
                names, order, defaults = set(), [], []
                # Validate descriptors even when the table is empty.
                if not payments:
                    _fields([[name, ["null"]] for name in PAYMENT_FIELDS], PAYMENT_FIELDS,
                            metas["POS Payment Method"], types["payments"])
                for row in payments:
                    if (type(row) is not dict or set(row) != {"name", "parent", "parenttype",
                            "parentfield", "idx", "modified", "fields"}
                            or (row["parent"], row["parenttype"], row["parentfield"])
                            != (profile_name, "POS Profile", "payments")
                            or type(row["idx"]) is not int or row["idx"] <= 0):
                        raise ValueError
                    name = _name(row["name"])
                    if name in names:
                        raise ValueError
                    names.add(name)
                    order.append((row["idx"], name.encode("utf-8")))
                    _modified(row["modified"], nullable=True)
                    selected = _fields(row["fields"], PAYMENT_FIELDS,
                                       metas["POS Payment Method"], types["payments"])
                    if selected["default"] == 1:
                        defaults.append(name)
                if order != sorted(order) or len(defaults) > 1 or default_names != defaults:
                    raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PosProfileSourceError("pos_profile_rows")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "profile_name", profile_name)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-pos-profile-source/v1\0" + self._payload).hexdigest())

    def limit_observation(self):
        pinned = _pin_read(self)
        if pinned.kind != "limit":
            raise PosProfileSourceError("pos_profile_lookup_kind")
        values = dict(json.loads(pinned._payload)["record"]["fields"])
        return PosLimitObservation(True, _validate_scalar(values["write_off_limit"]))

    def default_observation(self):
        pinned = _pin_read(self)
        if pinned.kind != "default":
            raise PosProfileSourceError("pos_profile_lookup_kind")
        body = json.loads(pinned._payload)
        defaults = body["default_names"]
        value = None
        if defaults:
            row = next(row for row in body["payments"] if row["name"] == defaults[0])
            value = _validate_scalar(dict(row["fields"])["mode_of_payment"])
        return DefaultMopObservation(True, bool(defaults), value)

    def __repr__(self):
        return "<LockedPosProfileRead protected lookup, NOT ACL/account eligibility>"

    def __reduce__(self):
        raise TypeError("pos_profile_source_not_serializable")


def _pin_read(value):
    if type(value) is not LockedPosProfileRead:
        raise PosProfileSourceError("pos_profile_rows")
    pinned = LockedPosProfileRead(value.financial, value.kind, value.metadata, value._payload)
    if pinned != value:
        raise PosProfileSourceError("pos_profile_rows")
    return pinned


class MariaDBPosProfileReader:
    """Read only consumed dependencies; caller must authorize all selected fields.

    The default probe mirrors the primary parent/default filter WITHOUT adding
    parenttype/parentfield or return eligibility. It observes ambiguity instead
    of silently choosing a row. Every candidate must belong to the actual table.
    No commit, rollback, connection acquisition, cache or caller cleanup occurs.
    """

    def __init__(self, connection):
        self._financial = MariaDBInvoiceFinancialReader(connection)
        self._connection, self._failed = connection, False

    def _load(self, financial, kind, applied_metadata):
        financial = _pin_financial(financial)
        _, name = _links(financial)
        metas = _metas(kind, applied_metadata)
        self._financial.require_unchanged(financial)
        source = MariaDBMetadataSourceReader(self._connection)
        metadata = tuple(source.load_for_update(metas[key]) for key in sorted(metas))
        fields = LIMIT_FIELDS if kind == "limit" else ("company",)
        with self._connection.cursor() as cursor:
            before, _, _ = self._financial._select(cursor, "POS Profile", name, None,
                                                  metas["POS Profile"], fields, 1, values=False)
            after, docs, signatures = self._financial._select(cursor, "POS Profile", name, None,
                                                             metas["POS Profile"], fields, 1, values=True)
        if before != after:
            raise ValueError
        doc = docs[0]
        record = dict(name=doc.name, modified=_scalar(doc.get("modified")),
                      fields=[[field, _scalar(doc.get(field))] for field in fields])
        payments, payment_signatures, default_names = [], [], []
        if kind == "default":
            with self._connection.cursor() as cursor:
                before, _, _ = self._financial._select(cursor, "POS Profile", name, "payments",
                    metas["POS Payment Method"], PAYMENT_FIELDS, MAX_PAYMENTS, values=False)
                after, docs, payment_signatures = self._financial._select(cursor, "POS Profile", name, "payments",
                    metas["POS Payment Method"], PAYMENT_FIELDS, MAX_PAYMENTS, values=True)
                if before != after:
                    raise ValueError
                # Two rows are already enough to prove an ambiguous primary
                # get_value. Bounded names only: no private/master data export.
                cursor.execute("SELECT SUBSTRING(`name`,1,141) FROM `tabPOS Payment Method` "
                               "WHERE `parent`=%s AND `default`=1 ORDER BY BINARY `name` LIMIT 2 FOR UPDATE", (name,))
                rows = cursor.fetchall()
                if type(rows) not in (tuple, list) or len(rows) > 1:
                    raise ValueError
                for row in rows:
                    if type(row) is not tuple or len(row) != 1:
                        raise ValueError
                    default_names.append(_name(row[0]))
            for child in docs:
                payments.append({**{field: _scalar(child.get(field)) if field == "modified"
                                    else child.get(field) for field in
                                    ("name", "parent", "parenttype", "parentfield", "idx", "modified")},
                                 "fields": [[field, _scalar(child.get(field))] for field in PAYMENT_FIELDS]})
        for row in metadata:
            source.require_unchanged(row)
        self._financial.require_unchanged(financial)
        payload = _canonical(dict(profile=PROFILE, kind=kind, financial_sha256=financial.sha256,
            metadata=[[row.applied.name, row.sha256] for row in metadata], record=record,
            payments=payments, types=dict(profile=signatures, payments=payment_signatures), default_names=default_names))
        return LockedPosProfileRead(financial, kind, metadata, payload)

    def load_for_update(self, financial, *, kind, applied_metadata):
        if self._failed:
            raise PosProfileSourceError("pos_profile_transaction_unusable")
        try:
            return self._load(financial, kind, applied_metadata)
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        raise PosProfileSourceError("pos_profile_read") from None

    def require_unchanged(self, observed):
        if self._failed:
            raise PosProfileSourceError("pos_profile_transaction_unusable")
        try:
            pinned = _pin_read(observed)
            if self._load(pinned.financial, pinned.kind, {row.applied.name: row.applied for row in pinned.metadata}) != pinned:
                raise ValueError
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
        else:
            return
        raise PosProfileSourceError("pos_profile_changed") from None

    def __repr__(self):
        return "<MariaDBPosProfileReader explicit caller-owned transaction>"

    def __reduce__(self):
        raise TypeError("pos_profile_source_not_serializable")
