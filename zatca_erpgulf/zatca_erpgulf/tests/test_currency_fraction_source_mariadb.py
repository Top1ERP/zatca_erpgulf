"""Invoice Currency fraction on NEW guard-owned TCP-disabled SQL only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from decimal import Decimal
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import currency_fraction_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_fraction_source import declarations, load, failure
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import financial_schema, insert_data
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(scope="module")
def fraction_schema(financial_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            cursor.execute("CREATE TABLE `tabCurrency` (name VARCHAR(140) PRIMARY KEY, modified DATETIME(6),"
                "smallest_currency_fraction_value DECIMAL(21,9),private_secret LONGTEXT) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE fraction_parent_work (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
    finally:
        setup.close()
    return financial_schema


@pytest.fixture(autouse=True)
def empty_sources(fraction_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for doctype in (*fraction_schema, "Currency", "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + doctype + "`")
        cursor.execute("DELETE FROM fraction_parent_work")
        cursor.execute("ALTER TABLE `tabCurrency` MODIFY smallest_currency_fraction_value DECIMAL(21,9)")
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()


def native_case(connections, *, currency="SAR", isolation="REPEATABLE READ", **options):
    case = declarations(**options)
    case.records["header"][0]["currency"] = currency
    case.currency_rows[0]["name"] = currency
    setup = connections()
    for observed in (*case.observations.values(), case.fraction): seed_metadata(setup, observed)
    for group, records in case.records.items(): insert_data(setup, case.doctype, group, records)
    with setup.cursor() as cursor:
        cursor.execute("INSERT INTO `tabCurrency` VALUES (%s,%s,%s,'PRIVATE-NEVER-RETURN')",
            (currency, case.currency_rows[0]["modified"], case.currency_rows[0]["value"]))
        cursor.execute("INSERT INTO `tabCurrency` VALUES (%s,%s,0.9,'UNRELATED-SECRET')",
            ("USD" if currency != "USD" else "SAR", case.currency_rows[0]["modified"]))
    setup.commit()
    setup.close()
    case.connection = connections(isolation)
    case.financial = native.MariaDBInvoiceFinancialReader(case.connection).load_for_update(case.doctype,
        case.name, erp_major=case.major, applied_metadata=case.metas)
    wrapped, case.calls, case.returned = instrument(case.connection)
    case.reader = source.MariaDBCurrencyFractionReader(wrapped)
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("value", [None, Decimal("0.000000000"), Decimal("0.050000000")])
def test_native_invoice_currency_only_raw_and_effective_views(connections, doctype, major, isolation, value):
    case = native_case(connections, doctype=doctype, major=major, isolation=isolation, value=value, currency="USD")
    result = load(case)
    assert result.currency == "USD" and result.effective_fraction == (0.0 if value is None else float(value))
    result.require_effective_cache_match(0.0 if value is None else float(value))
    case.reader.require_unchanged(result)
    queries = [(sql, params) for sql, params in case.calls if "FROM `tabCurrency`" in sql]
    assert queries and all(params == ("USD", 2) for _, params in queries)
    assert all("*" not in sql and "private_secret" not in sql for sql, _ in queries)
    assert all("SECRET" not in repr(rows) and "PRIVATE" not in repr(rows) for _, rows in case.returned)
    assert case.connection.open and not case.connection.get_autocommit()


@pytest.mark.parametrize("changed", ["fraction", "null_to_zero", "currency_revision", "invoice_currency", "financial_child", "metadata"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_same_handle_source_changes_are_caught_without_parent_cleanup(connections, changed, isolation):
    case = native_case(connections, value=None, isolation=isolation)
    result = load(case)
    with case.connection.cursor() as cursor:
        cursor.execute("INSERT INTO fraction_parent_work VALUES ('PENDING')")
        if changed == "fraction": cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=0.05 WHERE name='SAR'")
        elif changed == "null_to_zero": cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=0 WHERE name='SAR'")
        elif changed == "currency_revision": cursor.execute("UPDATE `tabCurrency` SET modified=modified+INTERVAL 1 SECOND WHERE name='SAR'")
        elif changed == "invoice_currency": cursor.execute("UPDATE `tabSales Invoice` SET currency='USD'")
        elif changed == "financial_child": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
        else: cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE parent='Currency'")
    failure(lambda: case.reader.require_unchanged(result), "currency_fraction_changed")
    failure(lambda: load(case), "currency_fraction_transaction_unusable")
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM fraction_parent_work")
        assert cursor.fetchall() == (("PENDING",),)
    observer = connections("READ COMMITTED")
    with observer.cursor() as cursor:
        cursor.execute("SELECT name FROM fraction_parent_work")
        assert cursor.fetchall() == ()
    case.connection.rollback()
    assert source.MariaDBCurrencyFractionReader(case.connection).load_for_update(case.financial,
        applied_metadata=case.fraction.applied) == result


@pytest.mark.parametrize("fault", ["missing_currency", "case", "negative", "text_type", "oversized", "metadata_missing"])
def test_bad_native_config_never_becomes_an_implicit_zero(connections, fault):
    case = native_case(connections)
    case.connection.rollback()
    setup = connections()
    with setup.cursor() as cursor:
        if fault == "missing_currency": cursor.execute("DELETE FROM `tabCurrency` WHERE name='SAR'")
        elif fault == "case": cursor.execute("UPDATE `tabCurrency` SET name='sar' WHERE name='SAR'")
        elif fault == "negative": cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=-0.05 WHERE name='SAR'")
        elif fault in ("text_type", "oversized"):
            cursor.execute("ALTER TABLE `tabCurrency` MODIFY smallest_currency_fraction_value LONGTEXT")
            cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=%s WHERE name='SAR'",
                ("PRIVATE" * 10000 if fault == "oversized" else "0.05",))
        else: cursor.execute("DELETE FROM `tabDocField` WHERE parent='Currency'")
    setup.commit()
    setup.close()
    failure(lambda: load(case))
    if fault == "oversized":
        assert not any("CASE WHEN" in sql for sql, _ in case.calls if "FROM `tabCurrency`" in sql)
        assert all("PRIVATE" not in repr(rows) for _, rows in case.returned)


@pytest.mark.parametrize("storage,value", [("DOUBLE", 0.05), ("DECIMAL(64,0)", Decimal("9" * 64))])
def test_native_descriptors_and_large_effective_config_are_preserved(connections, storage, value):
    case = native_case(connections)
    case.connection.rollback()
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("ALTER TABLE `tabCurrency` MODIFY smallest_currency_fraction_value " + storage)
        cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=%s WHERE name='SAR'", (value,))
    setup.commit()
    setup.close()
    result = load(case)
    result.require_effective_cache_match(float(value))
    case.reader.require_unchanged(result)


@pytest.mark.parametrize("target", ["currency", "metadata", "invoice"])
def test_native_source_locks_release_only_on_caller_rollback(connections, target):
    case = native_case(connections)
    load(case)
    ready = Event()
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            if target == "currency": cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=0.01 WHERE name='SAR'")
            elif target == "metadata": cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE parent='Currency'")
            else: cursor.execute("UPDATE `tabSales Invoice` SET currency='USD'")
        writer.commit()  # NEW synthetic competitor only.
        writer.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        case.connection.rollback()
        future.result(timeout=5)
