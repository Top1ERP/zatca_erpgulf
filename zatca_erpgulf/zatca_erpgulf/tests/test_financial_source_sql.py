"""Native scalar/preflight/financial envelope contracts; synthetic data only."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pymysql.constants import FIELD_TYPE as FT

from zatca_erpgulf.zatca_erpgulf import financial_source_sql as source
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf import metadata_source as metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project

NOW = datetime(2026, 10, 27, 14, 0, 0)


def fieldtype(name):
    if name in ("docstatus", "is_return", "is_advance_payment", "custom_is_advance_payment", "default"): return "Int"
    if name in ("posting_date", "difference_posting_date", "advance_invoice_date"): return "Date"
    if name == "posting_time": return "Time"
    if name in ("conversion_rate", "qty", "rate", "exchange_rate"): return "Float"
    if "amount" in name or name in ("total", "net_total", "grand_total"): return "Currency"
    return "Data"


def observed_metadata(raw):
    applied = project(raw)
    records = []
    for index, (name, definition) in enumerate(sorted(raw.definitions.items())):
        values = {prop: definition.get(prop) for prop in metadata.EDITABLE}
        records.append(dict(name=f"{raw.name}-{index:03}", modified=financial._scalar(NOW),
            header=[[key, financial._scalar(value)] for key, value in dict(
                parent=raw.name, parenttype="DocType", parentfield="fields", idx=index + 1,
                fieldname=name, is_virtual=0, **values).items()]))
    payload = financial._canonical(dict(profile=metadata.PROFILE, framework_version=metadata.FRAMEWORK_VERSION,
        source_doctype=raw.name, doctype=dict(name=raw.name, modified=financial._scalar(NOW),
            header=[[key, financial._scalar(value)] for key, value in dict(
                issingle=0, istable=int(raw.istable), is_virtual=0, custom=0).items()]),
        docfields=records, custom_fields=[], property_setters=[]))
    return metadata.SelectedMetadataRows(applied, payload)


def scenario(doctype="Sales Invoice", *, optional=True):
    tables = tuple(financial.TABLE_FIELDS) if optional else ("items", "taxes")
    header_fields = (*financial.REQUIRED_HEADER, "is_advance_payment", "custom_is_advance_payment")
    raw = AppliedMeta(doctype, (*header_fields, *tables),
        {table: financial._child_type(doctype, table) for table in tables})
    for name in header_fields:
        if name in raw.definitions: raw.definitions[name].values["fieldtype"] = fieldtype(name)
    header = dict(name="SYNTHETIC-INV", modified=NOW, company="SYNTHETIC-CO", customer="SYNTHETIC-CUSTOMER",
        currency="SAR", conversion_rate=Decimal("1.000000000"), posting_date=date(2026, 10, 27),
        posting_time=timedelta(hours=9, minutes=5, seconds=42), docstatus=1, is_return=0,
        total=Decimal("10.000000000"), net_total=Decimal("7.570000000"), grand_total=Decimal("8.700000000"),
        is_advance_payment=0, custom_is_advance_payment=1)
    metas, raw_metas, records = {doctype: project(raw)}, {doctype: raw}, {"header": [header]}
    for table in tables:
        dt = financial._child_type(doctype, table)
        names = (*financial.CHILD_REQUIRED[table], "description") if table == "items" else financial.CHILD_REQUIRED[table]
        child = AppliedMeta(dt, names)
        values = {}
        for name in names:
            kind = fieldtype(name)
            child.definitions[name].values["fieldtype"] = kind
            values[name] = Decimal("1.000000000") if kind in source.REAL_TYPES else (0 if kind == "Int" else "SYNTHETIC")
        records[table] = [dict(name=table + "-1", parent=header["name"], parenttype=doctype,
            parentfield=table, idx=1, modified=NOW, **values)] if table in ("items", "taxes") else []
        metas[dt], raw_metas[dt] = project(child), child
    observations = {name: observed_metadata(meta) for name, meta in raw_metas.items()}
    connection = SimpleNamespace(queries=[], records=records, autocommit=(0,), hook=None,
        signatures={}, commit=Mock(), rollback=Mock(), close=Mock(), error=None)
    for group in records:
        meta = metas[doctype if group == "header" else financial._child_type(doctype, group)]
        fields = financial.HEADER_FIELDS if group == "header" else financial.TABLE_FIELDS[group]
        for name in fields:
            if not meta.has_field(name): continue
            kind = meta.get_field(name).fieldtype
            code = FT.NEWDECIMAL if kind in source.REAL_TYPES else (FT.LONG if kind in ("Int", "Check")
                else FT.DATE if kind == "Date" else FT.TIME if kind == "Time" else FT.VAR_STRING)
            connection.signatures[group, name] = [code, 23, 9 if code == FT.NEWDECIMAL else 0, True]

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, args=()):
            connection.queries.append((sql, args))
            if connection.error: raise connection.error
            if sql == "SELECT @@session.autocommit": return
            table = sql.split("FROM `tab", 1)[1].split("`", 1)[0]
            group = "header" if table == doctype else next(key for key in tables if financial._child_type(doctype, key) == table)
            selected = [name for name in (financial.HEADER_FIELDS if group == "header" else financial.TABLE_FIELDS[group]) if metas[table].has_field(name)]
            ids = source.ROOT_IDS if group == "header" else source.CHILD_IDS
            full = "CASE WHEN" in sql
            if connection.hook: connection.hook(group, full)
            self.rows, self.description = [], [(name, FT.VAR_STRING, None, None, 140, 0, True) for name in ids]
            for name in selected:
                if full:
                    code, precision, scale, nullable = connection.signatures[group, name]
                    self.description.append((name, code, None, None, precision, scale, nullable))
                self.description.append(("length", FT.LONG, None, None, 20, 0, True))
            for record in connection.records[group][:args[-1]]:
                values = [record.get(name) for name in ids]
                for name in selected:
                    value = record.get(name)
                    length = None if value is None else len((value if type(value) is str else str(value)).encode())
                    if full: values.append(value if length is None or length <= financial.MAX_TEXT_BYTES else None)
                    values.append(length)
                self.rows.append(tuple(values))
            self.rows = tuple(self.rows)
        def fetchone(self): return connection.autocommit
        def fetchall(self): return self.rows

    connection.cursor = Mock(side_effect=Cursor)
    return SimpleNamespace(doctype=doctype, name=header["name"], records=records, metas=metas,
        raw_metas=raw_metas, observations=observations, connection=connection)


def reader(case, monkeypatch):
    provider = Mock()
    provider.load_for_update.side_effect = lambda meta: case.observations[meta.name]
    provider.require_unchanged.return_value = None
    monkeypatch.setattr(source, "MariaDBMetadataSourceReader", Mock(return_value=provider))
    return source.MariaDBInvoiceFinancialReader(case.connection), provider


def load(case, handle, major=15):
    return handle.load_for_update(case.doctype, case.name, erp_major=major, applied_metadata=case.metas)


def failure(call, code="financial_sql_read"):
    with pytest.raises(source.FinancialSQLSourceError) as caught: call()
    assert str(caught.value) == code and caught.value.__context__ is None


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("optional", [False, True])
def test_native_financial_snapshot_is_bounded_typed_and_has_no_writes(monkeypatch, doctype, major, optional):
    case = scenario(doctype, optional=optional)
    handle, provider = reader(case, monkeypatch)
    result = load(case, handle, major)
    handle.require_unchanged(result)
    body = json.loads(result.financial._payload)
    assert dict(body["header"])["grand_total"] == ["decimal", "8.700000000"]
    assert dict(body["header"])["is_advance_payment"] == ["int", "0"]
    assert dict(body["header"])["custom_is_advance_payment"] == ["int", "1"]
    assert json.loads(result._payload)["scalar_mode"] == source.SCALAR_MODE
    assert provider.load_for_update.call_count == len(case.metas) * 2
    assert "PARTIAL" in repr(result) and case.name not in repr(result)
    with pytest.raises(FrozenInstanceError): result.sha256 = "f" * 64
    for protected in (result, handle):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(protected)
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))


@pytest.mark.parametrize("value", [8.7, Decimal("8.7")])
def test_lossy_or_normalizing_decimal_driver_is_rejected_not_silently_adopted(monkeypatch, value):
    case = scenario()
    case.records["header"][0]["grand_total"] = value
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))
    failure(lambda: load(case, handle), "financial_sql_transaction_unusable")


@pytest.mark.parametrize("table", financial.TABLE_FIELDS)
def test_child_modification_without_parent_timestamp_is_detected(monkeypatch, table):
    case = scenario()
    handle, _ = reader(case, monkeypatch)
    observed = load(case, handle)
    if not case.records[table]:
        dt = financial._child_type(case.doctype, table)
        values = {name: None for name in financial.CHILD_REQUIRED[table]}
        case.records[table].append(dict(name=table + "-1", parent=case.name, parenttype=case.doctype,
            parentfield=table, idx=1, modified=NOW, **values))
    else: case.records[table][0]["modified"] += timedelta(seconds=1)
    failure(lambda: handle.require_unchanged(observed), "financial_sql_changed")


@pytest.mark.parametrize("fault", ["parent", "parenttype", "parentfield", "idx", "duplicate", "empty_items",
    "oversize", "timestamp", "code", "metadata_extra", "metadata_missing", "table_options"])
def test_malformed_scope_schema_rows_types_and_bounds_fail_closed(monkeypatch, fault):
    case = scenario()
    item = case.records["items"][0]
    if fault in ("parent", "parenttype", "parentfield"): item[fault] = "OTHER"
    elif fault == "idx": item["idx"] = True
    elif fault == "duplicate": case.records["items"].append(dict(item, idx=2))
    elif fault == "empty_items": case.records["items"] = []
    elif fault == "oversize": item["description"] = "X" * (financial.MAX_TEXT_BYTES + 1)
    elif fault == "timestamp": item["modified"] = "0000-00-00"
    elif fault == "code": case.connection.signatures["header", "grand_total"] = [FT.VAR_STRING, 40, 0, True]
    elif fault == "metadata_extra": case.metas["Company"] = project(AppliedMeta("Company", ()))
    elif fault == "metadata_missing": case.metas.pop(financial._child_type(case.doctype, "taxes"))
    else:
        case.raw_metas[case.doctype].definitions["items"].values["options"] = "OTHER"
        case.metas[case.doctype] = project(case.raw_metas[case.doctype])
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))


@pytest.mark.parametrize("group", ["header", "items", "taxes"])
def test_full_values_cannot_hide_changed_identity_or_length_preflight(monkeypatch, group):
    case = scenario()
    def change(current, full):
        if current == group and full: case.records[group][0]["modified"] += timedelta(seconds=1)
    case.connection.hook = change
    handle, _ = reader(case, monkeypatch)
    failure(lambda: load(case, handle))


@pytest.mark.parametrize("change", ["profile", "mode", "financial_hash", "metadata_hash", "types", "revisions", "noncanonical"])
def test_reconstruction_rechecks_financial_metadata_types_and_child_revisions(monkeypatch, change):
    case = scenario()
    handle, _ = reader(case, monkeypatch)
    observed = load(case, handle)
    body = json.loads(observed._payload)
    if change == "profile": body["profile"] = "OTHER"
    elif change == "mode": body["scalar_mode"] = "ORM"
    elif change == "financial_hash": body["financial_sha256"] = "f" * 64
    elif change == "metadata_hash": body["metadata"][0][1] = "f" * 64
    elif change == "types": body["types"][0][1].pop()
    elif change == "revisions": body["revisions"][0][1] = []
    payload = financial._canonical(body)
    if change == "noncanonical": payload = json.dumps(body).encode()
    failure(lambda: replace(observed, _payload=payload), "financial_sql_rows")


@pytest.mark.parametrize("interrupt", [False, True])
def test_failure_poisoning_does_not_take_caller_cleanup_ownership(monkeypatch, interrupt):
    case = scenario()
    case.connection.error = KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE DRIVER")
    handle, _ = reader(case, monkeypatch)
    if interrupt:
        with pytest.raises(KeyboardInterrupt): load(case, handle)
    else: failure(lambda: load(case, handle))
    failure(lambda: load(case, handle), "financial_sql_transaction_unusable")
    assert all(not getattr(case.connection, name).called for name in ("commit", "rollback", "close"))
