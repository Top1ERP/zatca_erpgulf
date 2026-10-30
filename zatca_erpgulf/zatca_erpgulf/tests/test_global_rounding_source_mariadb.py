"""Selected Global Check on NEW guard-owned TCP-disabled MariaDB only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
from threading import Event

import pytest

from zatca_erpgulf.zatca_erpgulf import global_rounding_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_global_rounding_source import scenario, load, failure
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_sources(format_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for table in ("Singles", "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + table + "`")
        cursor.execute("DELETE FROM currency_parent_work")
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()


def native_case(connections, *, isolation="REPEATABLE READ", secret=False, **options):
    case = scenario(**options)
    setup = connections()
    seed_metadata(setup, case.metadata)
    with setup.cursor() as cursor:
        for row in case.connection.rows:
            cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,%s)", row)
        if secret:
            cursor.execute("INSERT INTO `tabSingles` VALUES ('Global Defaults','api_secret','PRIVATE-NEVER-RETURN')")
    setup.commit()
    setup.close()
    case.connection = connections(isolation)
    instrumented, case.calls, case.returned = instrument(case.connection)
    case.reader = source.MariaDBGlobalRoundingReader(instrumented)
    return case


@pytest.mark.parametrize("raw,missing", [(None, True), (None, False), ("", False), ("0", False), ("1", False)])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("secret", [False, True])
def test_native_api_projection_keeps_raw_presence_and_never_reads_a_witness(connections, raw, missing, isolation, secret):
    case = native_case(connections, raw=raw, missing=missing, isolation=isolation, secret=secret)
    observed = load(case, case.reader)
    assert observed.value == (1 if raw == "1" else 0) and observed.stored is not missing
    case.reader.require_unchanged(observed)
    observed.require_cache_match(observed.value)
    assert case.connection.open and not case.connection.get_autocommit()
    assert b"PRIVATE" not in observed._payload
    selects = [(sql, params) for sql, params in case.calls if "FROM `tabSingles`" in sql]
    assert len(selects) == 4
    assert all(params == (source.DOCTYPE, source.FIELD, 2) for _, params in selects)
    assert not any("*" in sql for sql, _ in selects)
    assert all("PRIVATE" not in repr(rows) for _, rows in case.returned)


@pytest.mark.parametrize("changed", ["value", "null_to_blank", "delete", "absent_to_null", "metadata_default", "metadata_type"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_pending_same_handle_changes_are_caught_without_cleanup(connections, changed, isolation):
    case = native_case(connections, raw=None, missing=changed == "absent_to_null", isolation=isolation)
    observed = load(case, case.reader)
    with case.connection.cursor() as cursor:
        if changed == "value": cursor.execute("UPDATE `tabSingles` SET value='1'")
        elif changed == "null_to_blank": cursor.execute("UPDATE `tabSingles` SET value=''")
        elif changed == "delete": cursor.execute("DELETE FROM `tabSingles`")
        elif changed == "absent_to_null": cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,NULL)", (source.DOCTYPE, source.FIELD))
        elif changed == "metadata_default": cursor.execute("UPDATE `tabDocField` SET `default`='0'")
        else: cursor.execute("UPDATE `tabDocField` SET fieldtype='Data'")
    failure(lambda: case.reader.require_unchanged(observed), "global_rounding_changed")
    failure(lambda: load(case, case.reader), "global_rounding_transaction_unusable")
    assert case.connection.open
    case.connection.rollback()
    # Only the caller's explicit rollback restores the previously observed rows.
    restored = source.MariaDBGlobalRoundingReader(case.connection).load_for_update(applied_metadata=case.metadata.applied)
    assert restored == observed


@pytest.mark.parametrize("fault", ["duplicate", "doctype_case", "field_case", "oversize", "noncanonical", "missing_metadata"])
def test_ambiguous_native_rows_are_refused_without_disclosing_values(connections, fault):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        if fault == "duplicate": cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,'0')", (source.DOCTYPE, source.FIELD))
        elif fault == "doctype_case": cursor.execute("UPDATE `tabSingles` SET doctype='global defaults'")
        elif fault == "field_case": cursor.execute("UPDATE `tabSingles` SET field='Disable_Rounded_Total'")
        elif fault == "oversize": cursor.execute("UPDATE `tabSingles` SET value=%s", ("PRIVATE" * 1000,))
        elif fault == "noncanonical": cursor.execute("UPDATE `tabSingles` SET value='true'")
        else: cursor.execute("DELETE FROM `tabDocField`")
    failure(lambda: load(case, case.reader))
    assert case.connection.open
    if fault == "oversize":
        assert not any("CASE WHEN" in sql for sql, _ in case.calls if "FROM `tabSingles`" in sql)
        assert all("PRIVATE" not in repr(rows) for _, rows in case.returned)


@pytest.mark.parametrize("raw,missing", [(None, True), (None, False), ("0", False)])
def test_rc_phantom_insertion_requires_completion_recheck_even_with_equal_api_value(connections, raw, missing):
    case = native_case(connections, raw=raw, missing=missing, isolation="READ COMMITTED")
    observed = load(case, case.reader)
    writer = connections("READ COMMITTED")
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,NULL)", (source.DOCTYPE, source.FIELD))
    writer.commit()  # NEW fixture competing writer only.
    writer.close()
    assert observed.value == 0
    failure(lambda: case.reader.require_unchanged(observed), "global_rounding_changed")


@pytest.mark.parametrize("target", ["value", "metadata", "absent_gap"])
def test_native_locks_release_only_when_caller_rolls_back(connections, target):
    case = native_case(connections, missing=target == "absent_gap")
    load(case, case.reader)
    ready = Event()
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            if target == "metadata": cursor.execute("UPDATE `tabDocField` SET `default`='0'")
            elif target == "absent_gap": cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,'1')", (source.DOCTYPE, source.FIELD))
            else: cursor.execute("UPDATE `tabSingles` SET value='1' WHERE doctype=%s AND field=%s", (source.DOCTYPE, source.FIELD))
        writer.commit()  # NEW synthetic competitor only.
        writer.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        case.connection.rollback()
        future.result(timeout=5)


def test_reader_never_commits_discards_or_closes_parent_pending_work(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        cursor.execute("INSERT INTO currency_parent_work VALUES ('PENDING')")
    observed = load(case, case.reader)
    with case.connection.cursor() as cursor:
        cursor.execute("UPDATE `tabSingles` SET value='1'")
    failure(lambda: case.reader.require_unchanged(observed), "global_rounding_changed")
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM currency_parent_work")
        assert cursor.fetchall() == (("PENDING",),)
        cursor.execute("SELECT value FROM `tabSingles`")
        assert cursor.fetchall() == (("1",),)
    observer = connections("READ COMMITTED")
    with observer.cursor() as cursor:
        cursor.execute("SELECT name FROM currency_parent_work")
        assert cursor.fetchall() == ()
    assert case.connection.open
    case.connection.rollback()
