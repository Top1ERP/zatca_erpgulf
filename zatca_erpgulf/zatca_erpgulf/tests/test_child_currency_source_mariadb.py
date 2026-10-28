"""Native child links/metadata/column evidence on NEW guard-owned SQL only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import child_currency_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.source_metadata import CHILD_CURRENCY_PROFILE, project_source_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_child_currency_source import failure
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import (
    financial_schema, native_case as financial_case, load as load_financial,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW owned guarded temporary SQL only; no tenant or authority access")


@pytest.fixture(scope="module")
def child_schema(financial_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            cursor.execute("CREATE TABLE child_currency_parent_work (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
    finally:
        setup.close()
    return financial_schema


@pytest.fixture(autouse=True)
def empty_sources(child_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        # Private fixture owner only; reset DDL variants left by the previous case.
        for doctype in ("Sales Invoice Item", "POS Invoice Item"):
            for fieldname in source.FIELDS:
                cursor.execute("ALTER TABLE `tab" + doctype + "` ADD COLUMN IF NOT EXISTS `" + fieldname + "` LONGTEXT")
                cursor.execute("ALTER TABLE `tab" + doctype + "` MODIFY COLUMN `" + fieldname + "` LONGTEXT")
        for doctype in (*child_schema, "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + doctype + "`")
        cursor.execute("DELETE FROM child_currency_parent_work")
    setup.commit()
    setup.close()


def native_case(connections, *, doctype="Sales Invoice", major=16, present=("currency", "company"),
        isolation="REPEATABLE READ", currency="USD"):
    case = financial_case(connections, doctype, optional=False, isolation=isolation)
    dt = financial._child_type(doctype, "items")
    case.raw_metas[dt].definitions["amount"].values["options"] = "currency"
    case.metas[dt] = project(case.raw_metas[dt])
    raw = AppliedMeta(dt, present)
    for name in present:
        raw.definitions[name].values.update(fieldtype="Link", options="Currency" if name == "currency" else "Company")
    case.applied = project_source_metadata(raw, base_fields={}, profile=CHILD_CURRENCY_PROFILE)
    setup = connections()
    with setup.cursor() as cursor:
        for name in source.FIELDS:
            if name not in present:
                cursor.execute("ALTER TABLE `tab" + dt + "` DROP COLUMN `" + name + "`")
            else:
                cursor.execute("UPDATE `tab" + dt + "` SET `" + name + "`=%s",
                    (currency if name == "currency" else "SYNTHETIC-CHILD-CO",))
        cursor.execute("UPDATE `tabDocField` SET options='currency' WHERE parent=%s AND fieldname='amount'", (dt,))
    body = json.loads(observed_metadata(raw, profile=CHILD_CURRENCY_PROFILE)._payload)
    for row in body["docfields"]:
        values = {key: financial._validate_scalar(value) for key, value in row["header"]}
        insert(setup, "docfields", [dict(name="child-link-" + values["fieldname"],
            modified=financial._validate_scalar(row["modified"]), **values)])
    setup.commit()
    setup.close()
    case.financial = load_financial(case, major)
    case.reader = source.MariaDBChildCurrencyReader(case.connection)
    return case


def load(case):
    return case.reader.load_for_update(case.financial, "items", applied_metadata=case.applied)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", [(), ("currency",), ("company",), ("currency", "company")])
def test_exact_native_links_absence_and_parent_currency_on_both_versions(connections, doctype, major, present):
    case = native_case(connections, doctype=doctype, major=major, present=present)
    result = load(case)
    expected = "USD" if "currency" in present else "SAR"
    assert result.resolve_currency("items-1", "amount").currency == expected
    assert result.inputs_for("items-1").company_lookup == ()
    assert result.financial == case.financial
    case.reader.require_unchanged(result)
    assert case.connection.open and not case.connection.get_autocommit()


@pytest.mark.parametrize("currency", [None, "", "EUR"])
def test_native_null_blank_and_text_are_retained_exactly(connections, currency):
    case = native_case(connections, currency=currency)
    result = load(case)
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT currency FROM `tabSales Invoice Item` WHERE name='items-1'")
        native_value = cursor.fetchone()[0]
    assert result.inputs_for("items-1").row_currency == tuple(financial._scalar(native_value))
    assert result.resolve_currency("items-1", "amount").currency == (currency or "SAR")


@pytest.mark.parametrize("fault", ["orphan", "missing", "numeric", "oversized"])
def test_invalid_physical_columns_or_oversized_links_fail_before_own_values(connections, fault):
    case = native_case(connections)
    case.connection.rollback()
    setup = connections()
    with setup.cursor() as cursor:
        if fault == "orphan":
            cursor.execute("DELETE FROM `tabDocField` WHERE name='child-link-currency'")
            raw = AppliedMeta("Sales Invoice Item", ("company",))
            raw.definitions["company"].values.update(fieldtype="Link", options="Company")
            case.applied = project_source_metadata(raw, base_fields={}, profile=CHILD_CURRENCY_PROFILE)
        elif fault == "missing": cursor.execute("ALTER TABLE `tabSales Invoice Item` DROP COLUMN currency")
        elif fault == "numeric":
            cursor.execute("UPDATE `tabSales Invoice Item` SET currency=NULL")
            cursor.execute("ALTER TABLE `tabSales Invoice Item` MODIFY currency BIGINT")
        else: cursor.execute("UPDATE `tabSales Invoice Item` SET currency=%s", ("X" * (financial.MAX_TEXT_BYTES + 1),))
    setup.commit()
    wrapped, calls, returned = instrument(case.connection)
    case.reader = source.MariaDBChildCurrencyReader(wrapped)
    failure(lambda: load(case))
    own_values = [sql for sql, _ in calls if "FROM `tabSales Invoice Item`" in sql and "CASE WHEN OCTET_LENGTH(`currency`)" in sql]
    assert len(own_values) == int(fault == "numeric")
    assert not any("X" * 1000 in str(rows) for _, rows in returned)


@pytest.mark.parametrize("changed", ["currency", "company", "null_to_blank", "revision", "insert", "metadata"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_rechecks_detect_native_changes_without_parent_modified(connections, changed, isolation):
    case = native_case(connections, currency=None if changed == "null_to_blank" else "USD", isolation=isolation)
    original = load(case)
    case.connection.rollback()
    writer = connections()
    with writer.cursor() as cursor:
        if changed in ("currency", "company"): cursor.execute("UPDATE `tabSales Invoice Item` SET `" + changed + "`='OTHER'")
        elif changed == "null_to_blank": cursor.execute("UPDATE `tabSales Invoice Item` SET currency=''")
        elif changed == "revision": cursor.execute("UPDATE `tabSales Invoice Item` SET modified=modified+INTERVAL 1 SECOND")
        elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND WHERE name='child-link-currency'")
        else: cursor.execute("INSERT INTO `tabSales Invoice Item` (name,parent,parenttype,parentfield,idx,modified) SELECT 'items-2',parent,parenttype,parentfield,2,modified FROM `tabSales Invoice Item` WHERE name='items-1'")
    writer.commit()
    failure(lambda: case.reader.require_unchanged(original), "child_currency_source_changed")


@pytest.mark.parametrize("target", ["currency", "company", "metadata", "ddl"])
def test_native_row_metadata_and_table_locks_last_until_caller_cleanup(connections, target):
    case = native_case(connections)
    load(case)
    ready = Event()
    def compete():
        writer = connections()
        with writer.cursor() as cursor:
            cursor.execute("SET SESSION lock_wait_timeout=2")
            ready.set()
            if target in ("currency", "company"):
                cursor.execute("UPDATE `tabSales Invoice Item` SET `" + target + "`='OTHER'")
            elif target == "metadata":
                cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND WHERE name='child-link-currency'")
            else:
                cursor.execute("ALTER TABLE `tabSales Invoice Item` ADD COLUMN unused_column BIGINT")
        writer.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        case.connection.rollback()
        future.result(timeout=5)


def test_reader_does_not_commit_rollback_or_close_pending_caller_work(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        cursor.execute("INSERT INTO child_currency_parent_work VALUES ('pending')")
    result = load(case)
    case.reader.require_unchanged(result)
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM child_currency_parent_work")
        assert cursor.fetchall() == (("pending",),)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT name FROM child_currency_parent_work")
        assert not cursor.fetchall()
    case.connection.rollback()
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM child_currency_parent_work")
        assert not cursor.fetchall()


def test_rc_inserted_child_definition_is_detected_at_completion_recheck(connections):
    case = native_case(connections, present=(), isolation="READ COMMITTED")
    original = load(case)
    writer = connections("READ COMMITTED")
    insert(writer, "docfields", [dict(name="phantom-currency", modified=case.records["items"][0]["modified"],
        parent="Sales Invoice Item", parenttype="DocType", parentfield="fields", idx=99,
        fieldname="currency", fieldtype="Link", options="Currency", is_virtual=0)])
    writer.commit()
    failure(lambda: case.reader.require_unchanged(original), "child_currency_source_changed")


def test_native_empty_optional_table_never_acquires_an_invented_row(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        cursor.execute("DELETE FROM `tabSales Taxes and Charges`")
    case.financial = native.MariaDBInvoiceFinancialReader(case.connection).load_for_update(
        case.doctype, case.name, erp_major=16, applied_metadata=case.metas)
    meta = project_source_metadata(AppliedMeta("Sales Taxes and Charges", ()),
        base_fields={}, profile=CHILD_CURRENCY_PROFILE)
    result = case.reader.load_for_update(case.financial, "taxes", applied_metadata=meta)
    assert json.loads(result._payload)["rows"] == []
    failure(lambda: result.inputs_for("taxes-1"), "child_currency_source_inputs")
    case.reader.require_unchanged(result)
