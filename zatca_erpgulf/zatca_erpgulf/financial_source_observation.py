"""Versioned invoice-owned financial observations, NOT a committed ERP verifier.

The caller supplies authorized saved documents and explicit child metadata.
No Frappe, SQL, files, clock, XML generation, rounding or transport occurs here.
Linked templates/parties/settings/credential provenance remain separate gates.
Never use this PARTIAL digest as PreparationContext.source_snapshot_sha256.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
import math
from types import MappingProxyType

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 65536
MAX_ROWS = 4096
PROFILE = "invoice-owned-financial/v1"

HEADER_FIELDS = (
    "company", "customer", "currency", "conversion_rate", "posting_date", "posting_time",
    "due_date", "docstatus", "is_pos", "is_return", "return_against", "is_debit_note",
    "cost_center", "pos_profile", "taxes_and_charges", "tax_category", "customer_address",
    "company_address", "total_qty", "total", "base_total", "net_total", "base_net_total",
    "total_taxes_and_charges", "base_total_taxes_and_charges", "grand_total", "base_grand_total",
    "rounded_total", "base_rounded_total", "rounding_adjustment", "base_rounding_adjustment",
    "disable_rounded_total", "apply_discount_on", "additional_discount_percentage",
    "discount_amount", "base_discount_amount", "paid_amount", "base_paid_amount",
    "change_amount", "base_change_amount", "outstanding_amount", "total_advance",
    "is_advance_payment", "custom_is_advance_payment", "custom_zatca_use_line_net_amounts",
    "custom_zatca_tax_category", "custom_exemption_reason_code", "custom_exemption_reason",
    "custom_zatca_prepaid_amount", "custom_zatca_advance_deducted_taxable_amount",
    "custom_zatca_advance_deducted_vat_amount", "custom_zatca_advance_deduction_count",
    "custom_zatca_payment_entry", "custom_zatca_pos_name", "custom_zatca_export_invoice",
    "custom_zatca_third_party_invoice", "custom_zatca_nominal_invoice",
    "custom_summary_invoice", "custom_self_billed_invoice",
)
ITEM_FIELDS = (
    "item_code", "item_name", "description", "qty", "uom", "stock_uom", "conversion_factor",
    "rate", "base_rate", "amount", "base_amount", "net_rate", "base_net_rate",
    "net_amount", "base_net_amount", "price_list_rate", "base_price_list_rate",
    "discount_percentage", "discount_amount", "distributed_discount_amount",
    "item_tax_template", "item_tax_rate", "income_account", "cost_center",
    "custom_zatca_tax_category", "custom_exemption_reason_code",
)
TAX_FIELDS = (
    "charge_type", "account_head", "description", "rate", "tax_amount", "base_tax_amount",
    "tax_amount_after_discount_amount", "base_tax_amount_after_discount_amount",
    "total", "base_total", "item_wise_tax_detail", "included_in_print_rate",
    "included_in_paid_amount", "row_id", "add_deduct_tax", "category", "cost_center",
)
PAYMENT_FIELDS = ("mode_of_payment", "type", "account", "amount", "base_amount", "default")
ADVANCE_FIELDS = ("reference_type", "reference_name", "reference_row", "remarks",
    "advance_amount", "allocated_amount", "exchange_rate", "difference_posting_date")
DEDUCTION_FIELDS = (
    "payment_entry", "advance_invoice", "advance_invoice_date", "advance_status", "currency",
    "available_advance_remaining_amount", "advance_total_amount", "advance_taxable_amount",
    "advance_tax_amount", "allocated_total_amount", "allocated_taxable_amount", "allocated_tax_amount",
)
TABLE_FIELDS = MappingProxyType({
    "items": ITEM_FIELDS, "taxes": TAX_FIELDS, "payments": PAYMENT_FIELDS,
    "advances": ADVANCE_FIELDS, "custom_zatca_advance_deduction_details": DEDUCTION_FIELDS,
})
REQUIRED_HEADER = ("company", "customer", "currency", "conversion_rate", "posting_date",
    "posting_time", "docstatus", "is_return", "total", "net_total", "grand_total")
CHILD_REQUIRED = MappingProxyType({
    "items": ("item_code", "qty", "amount", "net_amount"),
    "taxes": ("charge_type", "rate", "tax_amount", "item_wise_tax_detail"),
    "payments": ("mode_of_payment", "amount"),
    "advances": ("reference_type", "reference_name", "allocated_amount"),
    "custom_zatca_advance_deduction_details": ("advance_invoice", "allocated_total_amount"),
})


class FinancialSourceError(ValueError):
    """Static internal code; no protected field/driver/customer disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _name(value):
    if type(value) is not str or not value or len(value) > 140 or "\0" in value:
        raise ValueError
    value.encode("utf-8")
    return value


def _scalar(value):
    """Preserve types, scale, sign and lexical text; never round or coerce zeros."""
    kind = type(value)
    if value is None:
        return ["null"]
    if kind is bool:
        return ["bool", value]
    if kind is int and abs(value) < 10**64:
        return ["int", str(value)]
    if kind is float and math.isfinite(value) and abs(value) < 10**64:
        return ["float", value.hex()]
    if kind is Decimal and value.is_finite():
        _sign, digits, exponent = value.as_tuple()
        if len(digits) <= 64 and abs(exponent) <= 64:
            return ["decimal", str(value)]
    if kind is str and len(value) <= MAX_TEXT_BYTES and len(value.encode("utf-8")) <= MAX_TEXT_BYTES:
        return ["str", value]
    if kind is datetime:
        return ["datetime", value.isoformat(timespec="microseconds")]
    if kind is date:
        return ["date", value.isoformat()]
    if kind is time:
        return ["time", value.isoformat(timespec="microseconds")]
    if kind is timedelta and -timedelta(days=1) < value < timedelta(days=1):
        return ["timedelta-us", str((value.days * 86400 + value.seconds) * 1000000 + value.microseconds)]
    raise ValueError


def _present(meta, name):
    present = meta.has_field(name)
    if type(present) not in (bool, int) or present not in (0, 1):
        raise ValueError
    return bool(present)


def _reference(encoded):
    """Optional typed reference; do not trim or coerce false/numeric values."""
    if encoded in (["absent"], ["null"], ["str", ""]):
        return None
    if type(encoded) is not list or len(encoded) != 2 or encoded[0] != "str":
        raise ValueError
    return _name(encoded[1])


def _projection(document, meta, fields, required):
    # Presence is part of the snapshot: absent != NULL != zero != empty string.
    present = tuple(_present(meta, name) for name in fields)
    if any(not present[fields.index(name)] for name in required):
        raise ValueError
    values = [[name, _scalar(document.get(name)) if exists else ["absent"]]
        for name, exists in zip(fields, present)]
    return values


def _canonical(value):
    # Enforce the aggregate bound WHILE encoding, not after allocating a giant
    # JSON string from individually bounded but repeated child text values.
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False)
    content = bytearray()
    for fragment in encoder.iterencode(value):
        chunk = fragment.encode("utf-8")
        if len(content) + len(chunk) > MAX_PAYLOAD_BYTES:
            raise ValueError
        content.extend(chunk)
    return bytes(content)


def _child_type(doctype, table_name):
    if table_name == "items":
        return "Sales Invoice Item" if doctype == "Sales Invoice" else "POS Invoice Item"
    return {"taxes":"Sales Taxes and Charges", "payments":"Sales Invoice Payment",
        "advances":"Sales Invoice Advance",
        "custom_zatca_advance_deduction_details":"ZATCA Sales Invoice Advance Deduction"}[table_name]


def _validate_scalar(encoded, *, absent=False):
    """Validate canonical form; return its scalar for shared declaration policies.

    Callers allowing absence must retain the tag: absent and NULL both decode
    to None. No numeric/flag coercion or normalization is introduced here.
    """
    if type(encoded) is not list or not encoded or type(encoded[0]) is not str:
        raise ValueError
    if encoded == ["absent"] and absent:
        return
    if encoded == ["null"]:
        return
    if len(encoded) != 2:
        raise ValueError
    tag, value = encoded
    if tag == "bool":
        if type(value) is not bool:
            raise ValueError
        decoded = value
    else:
        if type(value) is not str or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError
        if tag == "str": decoded = value
        elif tag == "int": decoded = int(value)
        elif tag == "float": decoded = float.fromhex(value)
        elif tag == "decimal": decoded = Decimal(value)
        elif tag == "datetime": decoded = datetime.fromisoformat(value)
        elif tag == "date": decoded = date.fromisoformat(value)
        elif tag == "time": decoded = time.fromisoformat(value)
        elif tag == "timedelta-us": decoded = timedelta(microseconds=int(value))
        else: raise ValueError
    if _scalar(decoded) != encoded:
        raise ValueError
    return decoded


def _validate_projection(projection, fields, required):
    if type(projection) is not list or len(projection) != len(fields):
        raise ValueError
    presence = []
    for entry, name in zip(projection, fields):
        if type(entry) is not list or len(entry) != 2 or entry[0] != name:
            raise ValueError
        _validate_scalar(entry[1], absent=name not in required)
        presence.append(entry[1] != ["absent"])
    return presence


def _capture_table(document, child_meta, table_name, expected_type, fields, required, identities, *, max_rows=None):
    """Shared bounded ordered-child capture; no record loads or policy choice."""
    if not _present(document.meta, table_name):
        raise ValueError
    table_field = document.meta.get_field(table_name)
    if table_field.fieldtype != "Table" or table_field.options != expected_type or child_meta.name != expected_type:
        raise ValueError
    presence = tuple(_present(child_meta, name) for name in fields)
    if any(not presence[fields.index(name)] for name in required):
        raise ValueError
    rows = document.get(table_name)
    limit = MAX_ROWS if max_rows is None else min(MAX_ROWS, max_rows)
    if type(rows) not in (list, tuple) or len(rows) > limit:
        raise ValueError
    observed = []
    for index, row in enumerate(rows, 1):
        row_name = _name(row.name)
        identity = expected_type, row_name
        if (row.doctype != expected_type or row.get("parent") != document.name
            or row.get("parenttype") != document.doctype or row.get("parentfield") != table_name
            or type(row.get("idx")) is not int or row.get("idx") != index or identity in identities):
            raise ValueError
        identities.add(identity)
        observed.append([row_name, index, _projection(row, child_meta, fields, required)])
    return {"doctype":expected_type, "presence":presence, "rows":observed}


def _validate_table(table, expected_type, fields, required, identities):
    if type(table) is not dict or set(table) != {"doctype", "presence", "rows"}:
        raise ValueError
    presence, rows = table["presence"], table["rows"]
    if (table["doctype"] != expected_type or type(presence) is not list or len(presence) != len(fields)
        or any(type(value) is not bool for value in presence)
        or any(not presence[fields.index(field)] for field in required)
        or type(rows) is not list or len(rows) > MAX_ROWS):
        raise ValueError
    for index, row in enumerate(rows, 1):
        if type(row) is not list or len(row) != 3 or type(row[1]) is not int or row[1] != index:
            raise ValueError
        identity = expected_type, _name(row[0])
        if identity in identities or _validate_projection(row[2], fields, required) != presence:
            raise ValueError
        identities.add(identity)
    return len(rows)


def _validate_body(body):
    _validate_scalar(body["modified"])
    if body["modified"][0] not in ("str", "datetime") or not body["modified"][1]:
        raise ValueError
    _validate_projection(body["header"], HEADER_FIELDS, REQUIRED_HEADER)
    tables = body["tables"]
    if type(tables) is not list or len(tables) != len(TABLE_FIELDS):
        raise ValueError
    identities, total_rows = set(), 0
    for entry, (name, fields) in zip(tables, TABLE_FIELDS.items()):
        if type(entry) is not list or len(entry) != 2 or entry[0] != name:
            raise ValueError
        table = entry[1]
        if table == ["absent"] and name not in ("items", "taxes"):
            continue
        total_rows += _validate_table(table, _child_type(body["doctype"], name), fields, CHILD_REQUIRED[name], identities)
        if total_rows > MAX_ROWS or (name == "items" and not table["rows"]):
            raise ValueError


@dataclass(frozen=True, repr=False)
class InvoiceFinancialObservation:
    """Protected partial observation, not a persistence/acceptance capability.

    Immutable canonical bytes avoid retaining mutable document/meta references.
    The constructor is private by convention; observation capture is the entry.
    No public codec/export/projection exists; generic dataclass tools are NOT a
    security sandbox and must not be used to log or send this object.
    """

    erp_major: int
    doctype: str
    name: str
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        if (type(self.erp_major) is not int or self.erp_major not in (15, 16)
            or type(self.doctype) is not str or self.doctype not in ("Sales Invoice", "POS Invoice")
            or type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES):
            raise FinancialSourceError("financial_source_observation")
        try:
            _name(self.name)
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "erp_major", "doctype", "name", "modified", "header", "tables"}
                or body["profile"] != PROFILE or type(body["erp_major"]) is not int
                or (body["erp_major"], body["doctype"], body["name"]) != (self.erp_major, self.doctype, self.name)
                or _canonical(body) != self._payload):
                raise ValueError
            _validate_body(body)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise FinancialSourceError("financial_source_observation")
        object.__setattr__(self, "sha256", hashlib.sha256(
            b"zatca-invoice-owned-financial/v1\0" + self._payload).hexdigest())

    def __repr__(self):
        return "<InvoiceFinancialObservation protected PARTIAL source, not verified>"

    def __reduce__(self):
        raise TypeError("financial_source_not_serializable")


def _pin_financial(observation):
    """Independent validated copy, not authentication of a supplied source."""
    if type(observation) is not InvoiceFinancialObservation:
        raise ValueError
    pinned = InvoiceFinancialObservation(observation.erp_major, observation.doctype,
        observation.name, observation._payload)
    if pinned != observation:
        raise ValueError
    return pinned


def capture_invoice_financial_observation(document, *, erp_major, child_metas):
    """Read only an explicit allowlist, no loads/writes/calculations/alias choice.

    child_metas is an explicit server-supplied map for PRESENT table fields,
    including empty tables; infer neither schema nor missing columns from rows.
    Caller must obtain authorized/stable documents and metadata independently.
    Future committed reader/settings manifest is NOT implemented here.
    """
    try:
        if type(erp_major) is not int or erp_major not in (15, 16) or type(child_metas) is not dict:
            raise ValueError
        doctype, name = document.doctype, _name(document.name)
        if type(doctype) is not str or doctype not in ("Sales Invoice", "POS Invoice"):
            raise ValueError
        meta = document.meta
        if meta.name != doctype:
            raise ValueError
        modified = document.get("modified")
        if type(modified) not in (str, datetime) or not modified:
            raise ValueError
        header = _projection(document, meta, HEADER_FIELDS, REQUIRED_HEADER)
        present_tables = tuple(name for name in TABLE_FIELDS if _present(meta, name))
        if not {"items", "taxes"} <= set(present_tables) or set(child_metas) != set(present_tables):
            raise ValueError
        tables, identities, total_rows = [], set(), 0
        for table_name, fields in TABLE_FIELDS.items():
            if table_name not in present_tables:
                tables.append([table_name, ["absent"]])
                continue
            table = _capture_table(document, child_metas[table_name], table_name,
                _child_type(doctype, table_name), fields, CHILD_REQUIRED[table_name], identities,
                max_rows=MAX_ROWS-total_rows)
            total_rows += len(table["rows"])
            if total_rows > MAX_ROWS or (table_name == "items" and not table["rows"]):
                raise ValueError
            tables.append([table_name, table])
        payload = _canonical(dict(profile=PROFILE, erp_major=erp_major, doctype=doctype,
            name=name, modified=_scalar(modified), header=header, tables=tables))
        result = InvoiceFinancialObservation(erp_major, doctype, name, payload)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise FinancialSourceError("financial_source_capture")
    return result
