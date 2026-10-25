"""Synthetic invoice-owned snapshots, no ERP site, authority or financial writes."""

import json
import pickle
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import financial_source_observation as source


class Document:
    def __init__(self, **values):
        self.__dict__.update(values)
        self.reads = []
        self.save, self.db_set = Mock(), Mock()

    def get(self, name):
        assert name not in ("custom_private_key", "custom_basic_auth_from_production",
            "custom_certificate", "custom_final_auth_csid")
        self.reads.append(name)
        return self.__dict__.get(name)


class Metadata:
    def __init__(self, name, fields, tables=None):
        self.name, self.fields, self.tables = name, set(fields), tables or {}

    def has_field(self, name):
        return name in self.fields

    def get_field(self, name):
        return SimpleNamespace(fieldtype="Table", options=self.tables[name])


@pytest.fixture(params=[15, 16])
def erp_major(request):
    return request.param


@pytest.fixture(params=["Sales Invoice", "POS Invoice"])
def case(request, erp_major):
    doctype = request.param
    tables = {name:source._child_type(doctype, name) for name in source.TABLE_FIELDS}
    doc = Document(doctype=doctype, name="SYNTHETIC-INV", modified=datetime(2026, 10, 25, 12),
        company="SYNTHETIC-CO", customer="SYNTHETIC-CUSTOMER", currency="SAR",
        conversion_rate=Decimal("1.00"), posting_date=date(2026, 10, 25),
        posting_time=timedelta(hours=9, minutes=5, seconds=42), docstatus=1, is_return=0,
        total=Decimal("10.00"), net_total=Decimal("7.57"), grand_total=Decimal("8.70"),
        custom_private_key="DO NOT READ PRIVATE", custom_final_auth_csid="DO NOT READ AUTH",
        meta=Metadata(doctype, (*source.HEADER_FIELDS, *tables), tables))
    metas, children = {}, []
    for name, fields in source.TABLE_FIELDS.items():
        dt = tables[name]
        metas[name] = Metadata(dt, fields)
        rows = []
        for index in range(1, 3):
            row = Document(doctype=dt, name=name + "-ROW-" + str(index), idx=index,
                parent=doc.name, parenttype=doctype, parentfield=name)
            for field in fields:
                setattr(row, field, None)
            rows.append(row)
            children.append(row)
        setattr(doc, name, rows)
    return SimpleNamespace(doc=doc, metas=metas, children=children, erp_major=erp_major)


def capture(case):
    return source.capture_invoice_financial_observation(case.doc,
        erp_major=case.erp_major, child_metas=case.metas)


def assert_static(call, code="financial_source_capture"):
    with pytest.raises(source.FinancialSourceError) as caught:
        call()
    assert str(caught.value) == code and caught.value.__context__ is None


def test_observation_deterministic_immutable_protected_and_side_effect_free(case):
    before = case.doc.modified
    result = capture(case)
    assert capture(case) == result and len(result.sha256) == 64
    assert "SYNTHETIC" not in repr(result) and "8.70" not in repr(result)
    assert "PARTIAL" in repr(result)
    with pytest.raises(FrozenInstanceError): result.sha256 = "f"*64
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(result)
    assert case.doc.modified == before and "custom_private_key" not in case.doc.reads
    assert not hasattr(result, "dispatch_authorized") and not hasattr(result, "source_snapshot_verified")
    for doc in (case.doc, *case.children):
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()


@pytest.mark.parametrize("field", source.HEADER_FIELDS)
def test_every_declared_header_dependency_changes_digest_even_if_modified_stays_fixed(case, field):
    before, modified = capture(case), case.doc.modified
    setattr(case.doc, field, "SYNTHETIC CHANGED VALUE")
    after = capture(case)
    assert after.sha256 != before.sha256 and case.doc.modified == modified


@pytest.mark.parametrize("table,field", [
    (table, field) for table, fields in source.TABLE_FIELDS.items() for field in fields
])
def test_every_declared_child_dependency_changes_digest_without_parent_revision(case, table, field):
    before, modified = capture(case), case.doc.modified
    setattr(case.doc.get(table)[0], field, "SYNTHETIC CHANGED VALUE")
    assert capture(case).sha256 != before.sha256 and case.doc.modified == modified


@pytest.mark.parametrize("table", source.TABLE_FIELDS)
@pytest.mark.parametrize("change", ["insert", "delete", "reorder", "row_identity", "schema"])
def test_child_membership_order_identity_and_schema_are_not_hidden_by_parent_timestamp(case, table, change):
    before, modified = capture(case), case.doc.modified
    rows = case.doc.get(table)
    if change == "insert":
        row = Document(**{key:value for key,value in rows[0].__dict__.items()
            if key not in ("reads", "save", "db_set")})
        row.name, row.idx = table + "-ROW-3", 3
        rows.append(row)
    elif change == "delete":
        rows.pop()
    elif change == "reorder":
        rows.reverse()
        for index, row in enumerate(rows, 1): row.idx = index
    elif change == "row_identity": rows[0].name = "OTHER-SYNTHETIC-ROW"
    else:
        optional = next(field for field in source.TABLE_FIELDS[table] if field not in source.CHILD_REQUIRED[table])
        case.metas[table].fields.remove(optional)
    assert capture(case).sha256 != before.sha256 and case.doc.modified == modified


@pytest.mark.parametrize("field", ["is_advance_payment", "custom_is_advance_payment", "base_discount_amount"])
def test_absent_null_zero_empty_and_false_are_distinct_without_alias_fallback(case, field):
    hashes = []
    for value in (None, 0, "", False, "0", Decimal("0.00"), -0.0):
        setattr(case.doc, field, value)
        hashes.append(capture(case).sha256)
    case.doc.meta.fields.remove(field)
    hashes.append(capture(case).sha256)
    assert len(hashes) == len(set(hashes))


def test_no_money_rounding_or_decimal_context_dependence(case):
    case.doc.grand_total = Decimal("8.7000001")
    with localcontext() as ctx:
        ctx.prec = 6
        before = capture(case)
    with localcontext() as ctx:
        ctx.prec = 28
        assert capture(case) == before
    case.doc.grand_total = Decimal("8.7000002")
    assert capture(case).sha256 != before.sha256


@pytest.mark.parametrize("value", [None, True, False, 0, -4, 0.0, -0.0, 8.7, Decimal("8.70"),
    "العربية<&>", date(2026,10,25), datetime(2026,10,25,12), datetime(2026,10,25,12,tzinfo=timezone.utc),
    time(9,5,42,123456), timedelta(hours=9,minutes=5,seconds=42), -timedelta(microseconds=1)])
def test_supported_typed_scalars_roundtrip_without_coercion(value):
    encoded = source._scalar(value)
    source._validate_scalar(encoded)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), Decimal("Infinity"),
    Decimal("1e1000"), 10**64, b"PRIVATE", bytearray(b"PRIVATE"), [], {},
    timedelta(days=1), "x"*(source.MAX_TEXT_BYTES+1)])
def test_unbounded_or_unsupported_values_are_static(case, value):
    case.doc.grand_total = value
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("field", source.REQUIRED_HEADER)
def test_missing_required_header_schema_cannot_silently_become_null(case, field):
    case.doc.meta.fields.remove(field)
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("table", source.TABLE_FIELDS)
@pytest.mark.parametrize("fault", ["missing_meta", "wrong_type", "parent", "parenttype", "parentfield",
    "idx", "duplicate_name", "rows_none", "required_column", "table_type"])
def test_bad_child_binding_or_schema_fails_closed(case, table, fault):
    row = case.doc.get(table)[0]
    if fault == "missing_meta": del case.metas[table]
    elif fault == "wrong_type": row.doctype = "PRIVATE"
    elif fault in ("parent", "parenttype", "parentfield"): setattr(row, fault, "PRIVATE")
    elif fault == "idx": row.idx = True
    elif fault == "duplicate_name": case.doc.get(table)[1].name = row.name
    elif fault == "rows_none": setattr(case.doc, table, None)
    elif fault == "required_column": case.metas[table].fields.remove(source.CHILD_REQUIRED[table][0])
    else: case.doc.meta.tables[table] = "PRIVATE"
    assert_static(lambda:capture(case))


def test_empty_optional_tables_keep_schema_and_items_cannot_disappear(case):
    case.doc.payments = []
    before = capture(case)
    case.metas["payments"].fields.remove("account")
    assert capture(case).sha256 != before.sha256
    case.doc.items = []
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("change", ["extra", "profile", "version_bool", "header_drop", "header_extra",
    "required_absent", "noncanonical", "table_order", "table_presence", "row_idx", "row_extra",
    "duplicate_row", "scalar_bool", "scalar_nan", "scalar_leading_zero", "trailing", "modified"])
def test_direct_payload_cannot_bypass_strict_structure_or_typed_values(case, change):
    result = capture(case)
    body = json.loads(result._payload)
    header = body["header"]
    table = body["tables"][0][1]
    if change == "extra": body["secret"] = "PRIVATE"
    elif change == "profile": body["profile"] = "PRIVATE"
    elif change == "version_bool": body["erp_major"] = True
    elif change == "header_drop": header.pop()
    elif change == "header_extra": header.append(["private_key", ["str","PRIVATE"]])
    elif change == "required_absent": header[0][1] = ["absent"]
    elif change == "table_order": body["tables"].reverse()
    elif change == "table_presence": table["presence"][0] = 1
    elif change == "row_idx": table["rows"][0][1] = True
    elif change == "row_extra": table["rows"][0].append("PRIVATE")
    elif change == "duplicate_row": table["rows"][1][0] = table["rows"][0][0]
    elif change == "scalar_bool": header[0][1] = ["bool", 1]
    elif change == "scalar_nan": header[0][1] = ["float", "nan"]
    elif change == "scalar_leading_zero": header[0][1] = ["int", "01"]
    elif change == "modified": body["modified"] = ["null"]
    payload = source._canonical(body)
    if change == "noncanonical": payload = json.dumps(body).encode()
    if change == "trailing": payload += b"PRIVATE"
    assert_static(lambda:replace(result, _payload=payload), "financial_source_observation")


@pytest.mark.parametrize("version", [None, True, 14, 17, "15"])
def test_unknown_erp_profile_not_inferred(case, version):
    case.erp_major = version
    assert_static(lambda:capture(case))


def test_present_metadata_flags_are_not_truthy_aliases(case):
    case.doc.meta.has_field = lambda name:"1"
    assert_static(lambda:capture(case))


def test_caller_mutation_cannot_change_already_captured_observation(case):
    result = capture(case)
    original = result.sha256
    case.doc.grand_total = Decimal("999")
    case.doc.items[0].net_amount = Decimal("777")
    case.doc.meta.fields.clear()
    assert result.sha256 == original
    result.__post_init__()
    assert result.sha256 == original



@pytest.mark.parametrize("fault", ["name", "doctype", "meta", "modified", "child_meta", "extra_meta", "items_schema", "taxes_schema"])
def test_root_and_table_identity_failures_are_static(case, fault):
    if fault == "name": case.doc.name = "PRIVATE\0NAME"
    elif fault == "doctype": case.doc.doctype = "Purchase Invoice"
    elif fault == "meta": case.doc.meta.name = "Company"
    elif fault == "modified": case.doc.modified = None
    elif fault == "child_meta": case.metas["items"].name = "Purchase Invoice Item"
    elif fault == "extra_meta": case.metas["PRIVATE"] = case.metas["items"]
    else: case.doc.meta.fields.remove("items" if fault == "items_schema" else "taxes")
    assert_static(lambda:capture(case))


@pytest.mark.parametrize("limit", ["rows", "payload", "utf8_text"])
def test_work_is_bounded_before_retaining_an_observation(case, monkeypatch, limit):
    if limit == "rows":
        monkeypatch.setattr(source, "MAX_ROWS", 2)  # Global across tables, not just each table.
    elif limit == "payload":
        monkeypatch.setattr(source, "MAX_PAYLOAD_BYTES", 100)
    else:
        case.doc.items[0].description = "ع" * (source.MAX_TEXT_BYTES // 2 + 1)
    assert_static(lambda:capture(case))


def test_version_and_document_type_are_explicit_digest_domains(case):
    before = capture(case)
    other = source.capture_invoice_financial_observation(case.doc,
        erp_major=16 if case.erp_major == 15 else 15, child_metas=case.metas)
    assert other.sha256 != before.sha256


def test_optional_table_absence_is_not_empty_table(case):
    case.doc.payments = []
    before = capture(case)
    case.doc.meta.fields.remove("payments")
    del case.metas["payments"]
    assert capture(case).sha256 != before.sha256


def test_no_caller_owned_xml_or_generated_identity_is_included(case):
    before = capture(case)
    case.doc.custom_uuid = "PRIVATE-GENERATED-UUID"
    case.doc.custom_zatca_icv = 200
    case.doc.custom_zatca_status = "REPORTED"
    case.doc.ksa_einv_qr = "/private/files/PRIVATE.png"
    case.doc.custom_private_key = "CHANGED PRIVATE KEY"
    assert capture(case) == before
    assert not {"custom_uuid", "custom_zatca_icv", "custom_zatca_status", "ksa_einv_qr", "custom_private_key"} & set(case.doc.reads)



def test_payload_encoder_stops_before_consuming_unbounded_fragments(monkeypatch):
    consumed = []
    def fragments(value):
        for chunk in ("x"*60, "y"*60, "PRIVATE UNREACHED"):
            consumed.append(chunk)
            yield chunk
    monkeypatch.setattr(source, "MAX_PAYLOAD_BYTES", 100)
    monkeypatch.setattr(source.json, "JSONEncoder",
        lambda **kwargs: SimpleNamespace(iterencode=fragments))
    with pytest.raises(ValueError): source._canonical({})
    assert consumed == ["x"*60, "y"*60]


@pytest.mark.parametrize("value", [None, [], {"x":"العربية"}, {"x":"\0\n\"\\"}, {"n":-0.0},
    {"a":[True,1,"0",None],"b":{"x":1}}])
def test_streamed_canonical_bytes_match_existing_json_encoding(value):
    expected = json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert source._canonical(value) == expected
