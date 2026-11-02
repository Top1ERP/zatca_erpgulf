"""Native-bound real-number getter observations, separate from fiscal math.

SAVED preserves exact raw tags. NUMERIC_FIXED compares the framework's explicit
precision-free conversion only, without changing the native parent or an ERP
document. No tax/currency rounding, XML formatting, source acquisition or writes.
"""

from dataclasses import dataclass, field
import hashlib
import json
import math

from .financial_source_observation import HEADER_FIELDS, TABLE_FIELDS, MAX_PAYLOAD_BYTES, _canonical, _scalar, _validate_scalar, _present
from .financial_source_sql import LockedInvoiceFinancialRead, REAL_TYPES, _pin_read

STAGES = ("SAVED", "NUMERIC_FIXED")
FIXED_TYPES = frozenset(("Float", "Currency", "Percent"))


class FinancialNumericViewError(ValueError):
    """Static English codes, without protected amounts or field disclosure."""


def _numeric_fields(meta, fields):
    return tuple((name, meta.get_field(name)) for name in fields
        if _present(meta, name) and meta.get_field(name).fieldtype in REAL_TYPES)


def _native_cells(financial):
    body = json.loads(financial.financial._payload)
    metas = {row.applied.name: row.applied for row in financial.metadata}
    root = metas[financial.financial.doctype]
    header = dict(body["header"])
    for name, definition in _numeric_fields(root, HEADER_FIELDS):
        yield "header", financial.financial.name, name, definition.fieldtype, header[name]
    for table, data in body["tables"]:
        if data == ["absent"]:
            continue
        fields = _numeric_fields(metas[data["doctype"]], TABLE_FIELDS[table])
        for row_name, _, values in data["rows"]:
            values = dict(values)
            for name, definition in fields:
                yield table, row_name, name, definition.fieldtype, values[name]


def _getter(value, stage, kind):
    if value is None:
        return ["null"]
    if stage == "NUMERIC_FIXED" and kind in FIXED_TYPES:
        # This derived getter may exceed the raw-float profile's 1e64 bound
        # after a valid bounded Decimal projects to float. Do not weaken raw
        # scalars or serialize this value as an invoice/XML monetary amount.
        if type(value) is not float or not math.isfinite(value):
            raise ValueError
        return ["float", value.hex()]
    encoded = _scalar(value)
    if encoded[0] not in ("decimal", "float"):
        raise ValueError
    return encoded


def _expected(encoded, stage, kind):
    if stage == "SAVED" or kind not in FIXED_TYPES or encoded == ["null"]:
        return encoded
    # Comparison witness for the ACTUAL explicit numeric-fix API. No rounding,
    # mutation or replacement of native data occurs, and NULL remains NULL.
    value = float(_validate_scalar(encoded))
    if not math.isfinite(value):
        raise ValueError
    return ["float", value.hex()]


@dataclass(frozen=True, repr=False)
class InvoiceNumericView:
    """Protected partial getter/native binding, NOT accounting/ORM authority."""

    financial: LockedInvoiceFinancialRead = field(repr=False)
    stage: str
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            financial = _pin_read(self.financial)
            if type(self.stage) is not str or self.stage not in STAGES:
                raise ValueError
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "financial_sha256", "stage", "cells"}
                    or body["profile"] != "invoice-real-numeric-view/v1" or body["financial_sha256"] != financial.sha256
                    or body["stage"] != self.stage or _canonical(body) != self._payload):
                raise ValueError
            expected = [[group, row, name, _expected(value, self.stage, kind)]
                for group, row, name, kind, value in _native_cells(financial)]
            if body["cells"] != expected:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FinancialNumericViewError("financial_numeric_view")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "sha256", hashlib.sha256(b"zatca-real-numeric-view/v1\0" + self._payload).hexdigest())

    @classmethod
    def from_values(cls, financial, *, stage, values):
        """Validate a COMPLETE ordered supplied getter set; never load or fix it."""
        try:
            financial = _pin_read(financial)
            if type(stage) is not str or stage not in STAGES or type(values) is not tuple:
                raise ValueError
            native = tuple(_native_cells(financial))
            if len(values) != len(native):
                raise ValueError
            cells = []
            for actual, (group, row, name, kind, _) in zip(values, native):
                if (type(actual) is not tuple or len(actual) != 4 or any(type(value) is not str for value in actual[:3])
                        or actual[:3] != (group, row, name)):
                    raise ValueError
                cells.append([group, row, name, _getter(actual[3], stage, kind)])
            payload = _canonical(dict(profile="invoice-real-numeric-view/v1", financial_sha256=financial.sha256,
                stage=stage, cells=cells))
            return cls(financial, stage, payload)
        except Exception:
            invalid = True
        if invalid:
            raise FinancialNumericViewError("financial_numeric_getters")

    def require_match(self, values):
        pinned = _pin_view(self)
        if type(self).from_values(pinned.financial, stage=pinned.stage, values=values) != pinned:
            raise FinancialNumericViewError("financial_numeric_getters_changed")

    def observe_fixed(self, values):
        """Compare supplied post-fix getters; their actual stage/origin is external."""
        pinned = _pin_view(self)
        return type(self).from_values(pinned.financial, stage="NUMERIC_FIXED", values=values)

    def __repr__(self):
        return "<InvoiceNumericView protected PARTIAL stage comparison, NOT money authority>"

    def __reduce__(self):
        raise TypeError("financial_numeric_view_not_serializable")


def _pin_view(observed):
    if type(observed) is not InvoiceNumericView:
        raise FinancialNumericViewError("financial_numeric_view_changed")
    pinned = InvoiceNumericView(observed.financial, observed.stage, observed._payload)
    if pinned != observed:
        raise FinancialNumericViewError("financial_numeric_view_changed")
    return pinned
