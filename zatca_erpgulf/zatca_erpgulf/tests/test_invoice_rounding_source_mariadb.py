"""Optional invoice controls on NEW guard-owned TCP-disabled MariaDB only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import invoice_rounding_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_sql as native
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.source_metadata import INVOICE_ROUNDING_PROFILE
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_rounding_source import declarations, load, failure
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import financial_schema, insert_data
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(scope="module")
def control_schema(financial_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            cursor.execute("CREATE TABLE rounding_parent_work (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
    finally:
        setup.close()
    return financial_schema


@pytest.fixture(autouse=True)
def empty_sources(control_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for doctype in (*control_schema, "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + doctype + "`")
        cursor.execute("DELETE FROM rounding_parent_work")
        for doctype in ("Sales Invoice", "POS Invoice"):
            for name in source.FIELDS:
                kind = "BIGINT" if name in source.CHECKS else "DECIMAL(21,9)"
                cursor.execute("ALTER TABLE `tab" + doctype + "` ADD COLUMN IF NOT EXISTS `" + name + "` " + kind)
                cursor.execute("ALTER TABLE `tab" + doctype + "` MODIFY COLUMN `" + name + "` " + kind)
    setup.commit()  # NEW private fixture setup only.
    setup.close()


def native_case(connections, *, isolation="REPEATABLE READ", **options):
    case = declarations(**options)
    setup = connections()
    for observation in case.observations.values(): seed_metadata(setup, observation)
    if case.own.applied.has_field("is_consolidated"):
        raw = AppliedMeta(case.doctype, ("is_consolidated",))
        raw.definitions["is_consolidated"] = case.own_raw.definitions["is_consolidated"]
        selected = observed_metadata(raw, profile=INVOICE_ROUNDING_PROFILE)
        body = json.loads(selected._payload)
        body["docfields"][0]["name"] = case.doctype + "-rounding-consolidated"
        selected = type(selected)(selected.applied, financial._canonical(body))
        seed_metadata(setup, selected, groups=("docfields",))
    with setup.cursor() as cursor:
        for name in source.FIELDS:
            if not case.own.applied.has_field(name):
                cursor.execute("ALTER TABLE `tab" + case.doctype + "` DROP COLUMN `" + name + "`")
    for group, records in case.records.items(): insert_data(setup, case.doctype, group, records)
    setup.commit()
    setup.close()
    case.connection = connections(isolation)
    case.financial = native.MariaDBInvoiceFinancialReader(case.connection).load_for_update(case.doctype,
        case.name, erp_major=case.major, applied_metadata=case.metas)
    wrapped, case.calls, case.returned = instrument(case.connection)
    case.reader = source.MariaDBInvoiceRoundingReader(wrapped)
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", [(), source.FIELDS, ("rounding_adjustment", "rounded_total"), ("is_consolidated",)])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_optional_physical_controls_bind_native_financial_and_metadata(connections, doctype, major, present, isolation):
    case = native_case(connections, doctype=doctype, major=major, present=present, isolation=isolation)
    observed = load(case)
    assert observed.metadata.applied == case.own.applied
    assert observed.financial == case.financial
    expected = {name: 0 if name in present else None for name in source.CHECKS}
    observed.require_check_cache_match(expected)
    assert dict(observed.normalized_checks) == expected and observed.consolidated is False
    case.reader.require_unchanged(observed)
    assert case.connection.open and not case.connection.get_autocommit()
    queries = [(sql, args) for sql, args in case.calls if "information_schema.COLUMNS" in sql]
    assert queries and all(args == ("tab" + doctype, *source.FIELDS) for _, args in queries)


@pytest.mark.parametrize("value", [None, 0, 1])
def test_native_null_zero_and_one_keep_raw_and_getter_views_separate(connections, value):
    case = native_case(connections, consolidated=value, disabled=value)
    result = load(case)
    assert dict(json.loads(result._payload)["fields"])["is_consolidated"] == financial._scalar(value)
    assert result.consolidated is (value == 1)
    result.require_check_cache_match(dict(is_consolidated=value or 0, disable_rounded_total=value or 0))


@pytest.mark.parametrize("fault", ["orphan", "missing", "text_type", "oversized", "metadata_missing"])
def test_bad_native_optional_schema_is_never_treated_as_false(connections, fault):
    case = native_case(connections)
    case.connection.rollback()
    setup = connections()
    with setup.cursor() as cursor:
        if fault == "orphan":
            cursor.execute("DELETE FROM `tabDocField` WHERE fieldname='is_consolidated'")
            case.own_raw.definitions.pop("is_consolidated")
            case.own = observed_metadata(case.own_raw, profile=INVOICE_ROUNDING_PROFILE)
        elif fault == "missing": cursor.execute("ALTER TABLE `tabSales Invoice` DROP COLUMN is_consolidated")
        elif fault in ("text_type", "oversized"):
            cursor.execute("ALTER TABLE `tabSales Invoice` MODIFY is_consolidated LONGTEXT")
            cursor.execute("UPDATE `tabSales Invoice` SET is_consolidated=%s", ("PRIVATE" * 10000 if fault == "oversized" else "0",))
        else: cursor.execute("DELETE FROM `tabDocField` WHERE fieldname='is_consolidated'")
    setup.commit()
    setup.close()
    failure(lambda: load(case))
    assert case.connection.open
    if fault == "oversized":
        assert not any("CASE WHEN OCTET_LENGTH(`is_consolidated`)" in sql for sql, _ in case.calls)
        assert all("PRIVATE" not in repr(rows) for _, rows in case.returned)


@pytest.mark.parametrize("changed", ["null_to_zero", "consolidation", "adjustment", "financial_child", "metadata"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_same_handle_drift_poisoning_does_not_clean_parent_work(connections, changed, isolation):
    case = native_case(connections, isolation=isolation)
    observed = load(case)
    with case.connection.cursor() as cursor:
        cursor.execute("INSERT INTO rounding_parent_work VALUES ('PENDING')")
        if changed == "null_to_zero": cursor.execute("UPDATE `tabSales Invoice` SET is_consolidated=0")
        elif changed == "consolidation": cursor.execute("UPDATE `tabSales Invoice` SET is_consolidated=1")
        elif changed == "adjustment": cursor.execute("UPDATE `tabSales Invoice` SET rounding_adjustment=0.02")
        elif changed == "financial_child": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
        else: cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE fieldname='is_consolidated'")
    failure(lambda: case.reader.require_unchanged(observed), "invoice_rounding_changed")
    failure(lambda: load(case), "invoice_rounding_transaction_unusable")
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM rounding_parent_work")
        assert cursor.fetchall() == (("PENDING",),)
    observer = connections("READ COMMITTED")
    with observer.cursor() as cursor:
        cursor.execute("SELECT name FROM rounding_parent_work")
        assert cursor.fetchall() == ()
    case.connection.rollback()
    restored = source.MariaDBInvoiceRoundingReader(case.connection).load_for_update(case.financial,
        applied_metadata=case.own.applied)
    assert restored == observed


@pytest.mark.parametrize("target", ["value", "metadata"])
def test_control_value_and_metadata_locks_belong_to_caller_cleanup(connections, target):
    case = native_case(connections)
    load(case)
    ready = Event()
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            if target == "value": cursor.execute("UPDATE `tabSales Invoice` SET is_consolidated=1")
            else: cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE fieldname='is_consolidated'")
        writer.commit()  # NEW synthetic competitor only.
        writer.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        case.connection.rollback()
        future.result(timeout=5)


def test_case_variant_physical_column_does_not_match_canonical_metadata(connections):
    case = native_case(connections)
    case.connection.rollback()
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("ALTER TABLE `tabSales Invoice` CHANGE COLUMN is_consolidated Is_Consolidated BIGINT")
    try:
        failure(lambda: load(case))
    finally:
        case.connection.rollback()
        with setup.cursor() as cursor:
            cursor.execute("ALTER TABLE `tabSales Invoice` CHANGE COLUMN Is_Consolidated is_consolidated BIGINT")
        setup.close()


@pytest.mark.parametrize("name", source.CHECKS)
@pytest.mark.parametrize("value", [2, -1])
def test_noncanonical_physical_check_values_are_not_booleanized(connections, name, value):
    case = native_case(connections, **{"consolidated" if name == "is_consolidated" else "disabled": value})
    failure(lambda: load(case))
