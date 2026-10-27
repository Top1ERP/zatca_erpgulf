"""Native invoice/child reads on a new guarded synthetic SQL fixture only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from decimal import Decimal
import json
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import financial_source_sql as source
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import scenario, failure, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert as insert_meta, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned guarded temporary SQL only; no installed invoice or authority access")


def scalar_sql(kind):
    if kind in source.REAL_TYPES: return "DECIMAL(21,9)"
    if kind in ("Int", "Long Int", "Check"): return "BIGINT"
    if kind == "Date": return "DATE"
    if kind == "Datetime": return "DATETIME(6)"
    if kind == "Time": return "TIME(6)"
    return "LONGTEXT"


@pytest.fixture(scope="module")
def financial_schema(metadata_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root", database="zatca_journal_rehearsal", autocommit=True)
    created = set()
    try:
        with setup.cursor() as cursor:
            for doctype in ("Sales Invoice", "POS Invoice"):
                case = scenario(doctype)
                for group in case.records:
                    dt = doctype if group == "header" else financial._child_type(doctype, group)
                    if dt in created: continue
                    created.add(dt)
                    meta = case.metas[dt]
                    fields = financial.HEADER_FIELDS if group == "header" else financial.TABLE_FIELDS[group]
                    columns = ["`name` VARCHAR(140) PRIMARY KEY", "`modified` DATETIME(6)"]
                    if group != "header": columns += ["`parent` VARCHAR(140)", "`parenttype` VARCHAR(140)", "`parentfield` VARCHAR(140)", "`idx` BIGINT"]
                    columns += ["`" + name + "` " + scalar_sql(meta.get_field(name).fieldtype) for name in fields if meta.has_field(name)]
                    if group != "header": columns.append("INDEX source_scope (`parent`,`parenttype`,`parentfield`,`idx`)")
                    cursor.execute("CREATE TABLE `tab" + dt + "` (" + ",".join(columns) + ") ENGINE=InnoDB")
    finally:
        setup.close()
    return tuple(sorted(created))


@pytest.fixture(autouse=True)
def empty_financial(financial_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for dt in (*financial_schema, "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + dt + "`")
    setup.commit()  # Only synthetic fixture setup, never a runtime read.
    setup.close()


def insert_data(connection, doctype, group, records):
    dt = doctype if group == "header" else financial._child_type(doctype, group)
    with connection.cursor() as cursor:
        for row in records:
            names = tuple(row)
            cursor.execute("INSERT INTO `tab" + dt + "` (" + ",".join("`" + name + "`" for name in names)
                + ") VALUES (" + ",".join("%s" for _ in names) + ")", tuple(row.values()))


def native_case(connections, doctype="Sales Invoice", *, optional=True, isolation="REPEATABLE READ"):
    case = scenario(doctype, optional=optional)
    setup = connections()
    for observation in case.observations.values():
        body = json.loads(observation._payload)
        for group in ("doctype", "docfields", "custom_fields", "property_setters"):
            records = [body[group]] if group == "doctype" else body[group]
            for row in records:
                raw = dict(name=row["name"], modified=financial._validate_scalar(row["modified"]),
                    **{name: financial._validate_scalar(value) for name, value in row["header"]})
                insert_meta(setup, group, [raw])
    for group, records in case.records.items(): insert_data(setup, doctype, group, records)
    setup.commit()
    setup.close()
    case.connection = connections(isolation)
    case.reader = source.MariaDBInvoiceFinancialReader(case.connection)
    return case


def load(case, major=15):
    return case.reader.load_for_update(case.doctype, case.name, erp_major=major, applied_metadata=case.metas)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("optional", [True, False])
def test_real_native_values_roundtrip_with_exact_driver_types(connections, doctype, major, optional):
    case = native_case(connections, doctype, optional=optional)
    observed = load(case, major)
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT grand_total,posting_date,posting_time,docstatus FROM `tab" + doctype + "`")
        oracle = cursor.fetchone()
    header = dict(json.loads(observed.financial._payload)["header"])
    for name, value in zip(("grand_total", "posting_date", "posting_time", "docstatus"), oracle):
        assert header[name] == financial._scalar(value)
    assert header["grand_total"] == ["decimal", "8.700000000"]
    case.reader.require_unchanged(observed)
    assert case.connection.open and not case.connection.get_autocommit()


def test_installed_frappe_decimal_converter_is_detected_as_a_different_read_mode(connections, isolated_server):
    from frappe.database.mariadb.database import MariaDBDatabase
    case = native_case(connections)
    converted = pymysql.connect(unix_socket=isolated_server[0], user="root", database="zatca_journal_rehearsal",
        charset="utf8mb4", autocommit=False, conv=MariaDBDatabase.CONVERSION_MAP)
    try:
        with converted.cursor() as cursor:
            cursor.execute("SELECT grand_total FROM `tabSales Invoice`")
            assert type(cursor.fetchone()[0]) is float
        handle = source.MariaDBInvoiceFinancialReader(converted)
        failure(lambda: handle.load_for_update(case.doctype, case.name, erp_major=15, applied_metadata=case.metas))
    finally:
        converted.rollback()
        converted.close()


@pytest.mark.parametrize("group", ["header", "items", "taxes"])
def test_actual_value_changes_without_parent_timestamp_are_detected(connections, group):
    case = native_case(connections)
    observed = load(case)
    case.connection.rollback()
    writer = connections()
    dt = case.doctype if group == "header" else financial._child_type(case.doctype, group)
    field = {"header": "grand_total", "items": "amount", "taxes": "tax_amount"}[group]
    with writer.cursor() as cursor: cursor.execute("UPDATE `tab" + dt + "` SET `" + field + "`=2")
    writer.commit()
    failure(lambda: case.reader.require_unchanged(observed), "financial_sql_changed")


@pytest.mark.parametrize("change", ["insert", "delete", "reorder", "revision", "idx_gap"])
def test_child_membership_order_and_revision_are_not_parent_revision_aliases(connections, change):
    case = native_case(connections)
    observed = load(case)
    case.connection.rollback()
    writer = connections()
    with writer.cursor() as cursor:
        if change == "insert": insert_data(writer, case.doctype, "items", [dict(case.records["items"][0], name="items-2", idx=2)])
        elif change == "delete": cursor.execute("DELETE FROM `tabSales Invoice Item`")
        elif change == "revision": cursor.execute("UPDATE `tabSales Invoice Item` SET modified=%s", (NOW + timedelta(seconds=1),))
        elif change == "idx_gap": cursor.execute("UPDATE `tabSales Invoice Item` SET idx=2")
        else:
            cursor.execute("UPDATE `tabSales Invoice Item` SET idx=2")
            insert_data(writer, case.doctype, "items", [dict(case.records["items"][0], name="items-2", idx=1)])
    writer.commit()
    failure(lambda: case.reader.require_unchanged(observed), "financial_sql_changed")


def test_same_parent_name_in_another_invoice_type_is_not_adopted_or_rejected(connections):
    case = native_case(connections)
    setup = connections()
    insert_data(setup, case.doctype, "taxes", [dict(case.records["taxes"][0], name="OTHER-TYPE-TAX", parenttype="POS Invoice")])
    setup.commit()
    observed = load(case)
    assert [row[0] for row in dict(json.loads(observed.financial._payload)["tables"])["taxes"]["rows"]] == ["taxes-1"]


@pytest.mark.parametrize("fault", ["parent_case", "parentfield_case", "large_cell", "aggregate"])
def test_native_scope_and_preflight_limits_refuse_before_returning_large_values(connections, fault):
    case = native_case(connections)
    setup = connections()
    with setup.cursor() as cursor:
        if fault == "parent_case": cursor.execute("UPDATE `tabSales Invoice Item` SET parent=LOWER(parent)")
        elif fault == "parentfield_case": cursor.execute("UPDATE `tabSales Invoice Item` SET parentfield='ITEMS'")
        elif fault == "large_cell": cursor.execute("UPDATE `tabSales Invoice Item` SET description=%s", ("X" * (financial.MAX_TEXT_BYTES + 1),))
        else:
            cursor.execute("UPDATE `tabSales Invoice Item` SET description=%s", ("X" * financial.MAX_TEXT_BYTES,))
            insert_data(setup, case.doctype, "items", [dict(case.records["items"][0], name=f"items-{index:02}", idx=index,
                description="X" * financial.MAX_TEXT_BYTES) for index in range(2, 34)])
    setup.commit()
    wrapped, calls, _ = instrument(case.connection)
    handle = source.MariaDBInvoiceFinancialReader(wrapped)
    failure(lambda: handle.load_for_update(case.doctype, case.name, erp_major=15, applied_metadata=case.metas))
    queries = [sql for sql, _ in calls if "FROM `tabSales Invoice Item`" in sql]
    assert queries and all("CASE WHEN" not in sql for sql in queries)


def test_rc_large_child_phantom_is_masked_then_membership_drift_is_rejected(connections):
    case = native_case(connections, isolation="READ COMMITTED")
    done = []
    def add_after_preflight(sql, args):
        if not done and "FROM `tabSales Invoice Item`" in sql and "CASE WHEN" not in sql:
            done.append(True)
            writer = connections("READ COMMITTED")
            insert_data(writer, case.doctype, "items", [dict(case.records["items"][0], name="items-2", idx=2,
                description="PRIVATE" * 10000)])
            writer.commit()
    wrapped, _, returned = instrument(case.connection, add_after_preflight)
    handle = source.MariaDBInvoiceFinancialReader(wrapped)
    failure(lambda: handle.load_for_update(case.doctype, case.name, erp_major=15, applied_metadata=case.metas))
    assert done
    full = [rows for sql, rows in returned if "FROM `tabSales Invoice Item`" in sql and "CASE WHEN" in sql][0]
    assert "PRIVATE" not in repr(full)


def test_metadata_change_during_financial_read_is_rechecked_before_disclosure(connections):
    case = native_case(connections)
    done = []
    def mutate(sql, args):
        if not done and "FROM `tabSales Invoice Item`" in sql:
            done.append(True)
            with case.connection.cursor() as cursor:
                cursor.execute("UPDATE `tabDocField` SET modified=%s", (NOW + timedelta(seconds=1),))
    wrapped, _, _ = instrument(case.connection, mutate)
    handle = source.MariaDBInvoiceFinancialReader(wrapped)
    failure(lambda: handle.load_for_update(case.doctype, case.name, erp_major=15, applied_metadata=case.metas))
    assert done


@pytest.mark.parametrize("group", ["header", "items", "taxes"])
def test_financial_row_locks_last_until_explicit_caller_cleanup(connections, group):
    case = native_case(connections)
    load(case)
    dt = case.doctype if group == "header" else financial._child_type(case.doctype, group)
    ready = Event()
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            cursor.execute("UPDATE `tab" + dt + "` SET modified=%s", (NOW + timedelta(seconds=1),))
        writer.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        case.connection.rollback()
        future.result(timeout=5)


def test_raw_reader_sees_own_pending_money_without_implicitly_saving_it(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor: cursor.execute("UPDATE `tabSales Invoice` SET grand_total=2")
    observed = load(case)
    assert dict(json.loads(observed.financial._payload)["header"])["grand_total"] == ["decimal", "2.000000000"]
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT grand_total FROM `tabSales Invoice`")
        assert cursor.fetchone() == (Decimal("8.700000000"),)
    case.connection.rollback()


def test_child_rows_limit_is_shared_across_all_present_tables(connections, monkeypatch):
    case = native_case(connections)
    monkeypatch.setattr(financial, "MAX_ROWS", 1)
    failure(lambda: load(case))


def test_payments_and_old_advance_references_keep_zero_allocations_without_lookup(connections):
    case = native_case(connections)
    setup = connections()
    rows = {
        "payments": dict(mode_of_payment="SYNTHETIC-CASH", amount=Decimal("0.000000000")),
        "advances": dict(reference_type="Payment Entry", reference_name="SYNTHETIC-PE-2020-0001",
            allocated_amount=Decimal("0.000000000")),
        "custom_zatca_advance_deduction_details": dict(advance_invoice="SYNTHETIC-ADV-2020-0001"),
    }
    for table, values in rows.items():
        insert_data(setup, case.doctype, table, [dict(name=table + "-OLD", parent=case.name,
            parenttype=case.doctype, parentfield=table, idx=1, modified=None, **values)])
    setup.commit()
    observed = load(case)
    tables = dict(json.loads(observed.financial._payload)["tables"])
    advance = dict(tables["advances"]["rows"][0][2])
    assert advance["reference_name"] == ["str", "SYNTHETIC-PE-2020-0001"]
    # The existing canonical Decimal codec uses exponent notation for zero;
    # its -9 exponent retains the SQL scale without rewriting stored formats.
    assert advance["allocated_amount"] == ["decimal", "0E-9"]
    assert financial._validate_scalar(advance["allocated_amount"]).as_tuple().exponent == -9
    assert dict(tables["payments"]["rows"][0][2])["amount"] == ["decimal", "0E-9"]
    assert all(revisions[0][1] == ["null"] for table, revisions in json.loads(observed._payload)["revisions"] if table in rows)


def test_decimal_physical_scale_changes_are_bound_even_when_value_stays_null(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor: cursor.execute("UPDATE `tabSales Invoice` SET grand_total=NULL")
    case.connection.commit()  # Explicit fixture owner; never the reader.
    observed = load(case)
    case.connection.rollback()
    schema = connections(autocommit=True)
    try:
        with schema.cursor() as cursor:
            cursor.execute("ALTER TABLE `tabSales Invoice` MODIFY grand_total DECIMAL(21,6)")
        failure(lambda: case.reader.require_unchanged(observed), "financial_sql_changed")
    finally:
        case.connection.rollback()
        with schema.cursor() as cursor:
            cursor.execute("ALTER TABLE `tabSales Invoice` MODIFY grand_total DECIMAL(21,9)")
        schema.close()


def test_subcent_values_are_observed_without_fiscal_rounding(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        cursor.execute("UPDATE `tabSales Invoice` SET grand_total=%s", (Decimal("8.700000001"),))
    observed = load(case)
    assert dict(json.loads(observed.financial._payload)["header"])["grand_total"] == ["decimal", "8.700000001"]
