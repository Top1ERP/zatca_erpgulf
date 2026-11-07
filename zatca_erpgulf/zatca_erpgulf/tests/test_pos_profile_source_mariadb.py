"""POS master/default reads on NEW guard-owned, TCP-disabled SQL only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from decimal import Decimal
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import pos_profile_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_profile_source import declarations, load, failure
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import financial_schema, insert_data
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guarded temporary SQL only; no tenant or authority access")


@pytest.fixture(scope="module")
def pos_schema(financial_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            for dt in ("Sales Invoice", "POS Invoice"):
                cursor.execute(f"ALTER TABLE `tab{dt}` ADD COLUMN IF NOT EXISTS pos_profile LONGTEXT")
            cursor.execute("CREATE TABLE `tabPOS Profile` (name VARCHAR(140) PRIMARY KEY, modified DATETIME(6),"
                "company VARCHAR(140), write_off_limit DECIMAL(21,9),private_secret LONGTEXT) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE `tabPOS Payment Method` (name VARCHAR(140) PRIMARY KEY, modified DATETIME(6),"
                "parent VARCHAR(140),parenttype VARCHAR(140),parentfield VARCHAR(140),idx BIGINT,"
                "mode_of_payment LONGTEXT,`default` BIGINT,allow_in_returns BIGINT,private_secret LONGTEXT,"
                "INDEX source_scope(parent,parenttype,parentfield,idx),INDEX default_scope(parent,`default`)) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE pos_lookup_parent_work (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
    finally:
        setup.close()
    return financial_schema


@pytest.fixture(autouse=True)
def empty_pos(pos_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for dt in (*pos_schema, "POS Profile", "POS Payment Method", "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute(f"DELETE FROM `tab{dt}`")
        cursor.execute("DELETE FROM pos_lookup_parent_work")
    setup.commit()  # NEW synthetic fixture setup only, never a runtime reader.
    setup.close()


def native_case(connections, *, isolation="REPEATABLE READ", **options):
    case = declarations(**options)
    setup = connections()
    for row in (*case.observations.values(), *case.pos_metadata.values()): seed_metadata(setup, row)
    for group, rows in case.records.items(): insert_data(setup, case.doctype, group, rows)
    with setup.cursor() as cursor:
        for row in case.master_rows:
            cursor.execute("INSERT INTO `tabPOS Profile` VALUES (%s,%s,%s,%s,'NEVER-RETURN-PRIVATE-MASTER')",
                (row["name"], row["modified"], row["company"], row["write_off_limit"]))
        for row in case.payment_rows:
            cursor.execute("INSERT INTO `tabPOS Payment Method` VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'NEVER-RETURN-PRIVATE-PAYMENT')",
                tuple(row[name] for name in ("name", "modified", "parent", "parenttype", "parentfield", "idx",
                                             "mode_of_payment", "default", "allow_in_returns")))
    setup.commit()
    setup.close()
    case.connection = connections(isolation)
    case.financial = native.MariaDBInvoiceFinancialReader(case.connection).load_for_update(
        case.doctype, case.name, erp_major=case.major, applied_metadata=case.metas)
    wrapped, case.calls, case.returned = instrument(case.connection)
    case.reader = source.MariaDBPosProfileReader(wrapped)
    return case


@pytest.mark.parametrize("kind", ["limit", "default"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_native_selected_lookup_no_private_columns_or_parent_cleanup(connections, kind, major, doctype):
    case = native_case(connections, kind=kind, major=major, doctype=doctype)
    before = case.financial._payload, case.financial.financial._payload
    result = load(case)
    if kind == "limit":
        assert result.limit_observation().value == Decimal("2.500000000")
        assert not any("tabPOS Payment Method" in sql for sql, _ in case.calls)
    else:
        assert result.default_observation().mode_of_payment == "Cash"
        assert not any("write_off_limit" in sql for sql, _ in case.calls)
    case.reader.require_unchanged(result)
    assert before == (case.financial._payload, case.financial.financial._payload)
    queries = [(sql, params) for sql, params in case.calls if "FROM `tabPOS " in sql]
    assert queries and all("*" not in sql and "private_secret" not in sql and "FOR UPDATE" in sql for sql, _ in queries)
    assert all("NEVER-RETURN" not in repr(rows) for _, rows in case.returned)
    assert case.connection.open and not case.connection.get_autocommit()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("changed", ["mode", "default", "returns", "revision", "invoice_link", "financial_child", "metadata", "orphan_default"])
def test_native_changes_keep_caller_pending_work_and_poison_reader(connections, isolation, changed):
    case = native_case(connections, isolation=isolation)
    observed = load(case)
    with case.connection.cursor() as cursor:
        cursor.execute("INSERT INTO pos_lookup_parent_work VALUES ('PENDING')")
        if changed == "mode": cursor.execute("UPDATE `tabPOS Payment Method` SET mode_of_payment='Bank'")
        elif changed == "default": cursor.execute("UPDATE `tabPOS Payment Method` SET `default`=0")
        elif changed == "returns": cursor.execute("UPDATE `tabPOS Payment Method` SET allow_in_returns=1")
        elif changed == "revision": cursor.execute("UPDATE `tabPOS Profile` SET modified=modified+INTERVAL 1 SECOND")
        elif changed == "invoice_link": cursor.execute("UPDATE `tabSales Invoice` SET pos_profile='OTHER'")
        elif changed == "financial_child": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
        elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE parent='POS Profile'")
        else:
            cursor.execute("INSERT INTO `tabPOS Payment Method` (name,parent,parenttype,parentfield,idx,`default`) "
                           "VALUES ('ORPHAN','SYNTHETIC-POS','OTHER','other',1,1)")
    failure(lambda: case.reader.require_unchanged(observed), "pos_profile_changed")
    failure(lambda: load(case), "pos_profile_transaction_unusable")
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM pos_lookup_parent_work")
        assert cursor.fetchall() == (("PENDING",),)
    observer = connections("READ COMMITTED")
    with observer.cursor() as cursor:
        cursor.execute("SELECT name FROM pos_lookup_parent_work")
        assert cursor.fetchall() == ()
    case.connection.rollback()
    assert source.MariaDBPosProfileReader(case.connection).load_for_update(
        case.financial, kind=case.kind, applied_metadata=case.applied_pos) == observed


@pytest.mark.parametrize("fault", ["missing", "company", "multiple_defaults", "orphan", "check", "row_bound", "oversized"])
def test_native_missing_or_conflicting_sources_fail_before_calculation(connections, fault):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        if fault == "missing": cursor.execute("DELETE FROM `tabPOS Profile`")
        elif fault == "company": cursor.execute("UPDATE `tabPOS Profile` SET company='OTHER'")
        elif fault in ("multiple_defaults", "orphan"):
            if fault == "orphan": cursor.execute("UPDATE `tabPOS Payment Method` SET `default`=0")
            cursor.execute("INSERT INTO `tabPOS Payment Method` (name,parent,parenttype,parentfield,idx,`default`) "
                "VALUES ('EXTRA','SYNTHETIC-POS',%s,'payments',2,1)",
                ("OTHER" if fault == "orphan" else "POS Profile",))
        elif fault == "check": cursor.execute("UPDATE `tabPOS Payment Method` SET allow_in_returns=2")
        elif fault == "oversized": cursor.execute("UPDATE `tabPOS Payment Method` SET mode_of_payment=%s", ("PRIVATE" * 10000,))
        else:
            cursor.executemany("INSERT INTO `tabPOS Payment Method` (name,parent,parenttype,parentfield,idx,`default`) "
                "VALUES (%s,'SYNTHETIC-POS','POS Profile','payments',%s,0)", [(f"MORE-{i}", i + 2) for i in range(128)])
    failure(lambda: load(case))
    failure(lambda: load(case), "pos_profile_transaction_unusable")


@pytest.mark.parametrize("kind", ["limit", "default"])
def test_profile_lock_blocks_competing_writers_until_caller_rollback(connections, kind):
    case = native_case(connections, kind=kind)
    load(case)
    competitor = connections()
    started = Event()
    def write():
        with competitor.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout=4")
            started.set()
            cursor.execute("UPDATE `tabPOS Profile` SET company='CHANGED' WHERE name='SYNTHETIC-POS'")
        competitor.rollback()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write)
        assert started.wait(1)
        with pytest.raises(TimeoutError): future.result(timeout=0.1)
        case.connection.rollback()
        future.result(timeout=4)


@pytest.mark.parametrize("value", [None, Decimal("0.000000000"), Decimal("-2.500000000")])
def test_native_null_zero_and_negative_limits_are_distinct(connections, value):
    case = native_case(connections, kind="limit", limit=value)
    result = load(case)
    actual = result.limit_observation().value
    assert type(actual) is type(value)
    if value is not None: assert actual.as_tuple() == value.as_tuple()


@pytest.mark.parametrize("shape", ["empty", "no_default", "null_mode"])
def test_native_absent_default_differs_from_found_null_mode(connections, shape):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        if shape == "empty": cursor.execute("DELETE FROM `tabPOS Payment Method`")
        elif shape == "no_default": cursor.execute("UPDATE `tabPOS Payment Method` SET `default`=0")
        else: cursor.execute("UPDATE `tabPOS Payment Method` SET mode_of_payment=NULL")
    lookup = load(case).default_observation()
    assert lookup.found is (shape == "null_mode") and lookup.mode_of_payment is None


def test_read_committed_detects_later_orphan_insertion_on_completion_recheck(connections):
    case = native_case(connections, isolation="READ COMMITTED")
    observed = load(case)
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO `tabPOS Payment Method` (name,parent,parenttype,parentfield,idx,`default`) "
                       "VALUES ('LATE-ORPHAN','SYNTHETIC-POS','OTHER','other',1,1)")
    writer.commit()  # Only an independent writer on the NEW owned test server.
    failure(lambda: case.reader.require_unchanged(observed), "pos_profile_changed")


@pytest.mark.parametrize("kind", ["limit", "default"])
def test_unconsumed_setting_changes_do_not_create_a_false_source_conflict(connections, kind):
    case = native_case(connections, kind=kind)
    observed = load(case)
    with case.connection.cursor() as cursor:
        if kind == "limit":
            cursor.execute("INSERT INTO `tabPOS Payment Method` (name,parent,parenttype,parentfield,idx,`default`) "
                           "VALUES ('UNUSED','SYNTHETIC-POS','OTHER','other',1,1)")
        else:
            cursor.execute("UPDATE `tabPOS Profile` SET write_off_limit=1000")
    case.reader.require_unchanged(observed)


def test_selected_payment_row_lock_is_retained_by_caller(connections):
    case = native_case(connections)
    load(case)
    competitor = connections()
    started = Event()
    def write():
        with competitor.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout=4")
            started.set()
            cursor.execute("UPDATE `tabPOS Payment Method` SET mode_of_payment='CHANGED' WHERE name='PAY-1'")
        competitor.rollback()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write)
        assert started.wait(1)
        with pytest.raises(TimeoutError): future.result(timeout=0.1)
        case.connection.rollback()
        future.result(timeout=4)
