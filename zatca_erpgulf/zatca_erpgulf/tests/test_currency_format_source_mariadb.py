"""Native locale/currency/Singleton reads on new guard-owned SQL only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import currency_format_source as source
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.calculation_precision import FieldPrecisionResolution
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source import scenario, load, failure, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import declarations
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Guard-owned temporary SQL only; no site/tenant or authority access")


@pytest.fixture(scope="module")
def format_schema(metadata_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            for table in ("Language", "Currency"):
                cursor.execute("CREATE TABLE `tab" + table + "` (name VARCHAR(140) PRIMARY KEY,"
                    "modified DATETIME(6),number_format LONGTEXT) ENGINE=InnoDB")
            # Deliberately permits duplicate selected keys to exercise refusal.
            cursor.execute("CREATE TABLE `tabSingles` (doctype VARCHAR(140),field VARCHAR(140),"
                "value LONGTEXT,INDEX source_scope(doctype,field)) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE currency_parent_work (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
    finally:
        setup.close()


@pytest.fixture(autouse=True)
def empty_sources(format_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for table in ("Language", "Currency", "Singles", "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + table + "`")
        cursor.execute("DELETE FROM currency_parent_work")
    setup.commit()  # Synthetic fixture owner only, never a source reader.
    setup.close()


def native_case(connections, *, isolation="REPEATABLE READ", **options):
    case = scenario(**options)
    setup = connections()
    for observation in case.observations.values():
        body = json.loads(observation._payload)
        for group in ("doctype", "docfields", "custom_fields", "property_setters"):
            rows = [body[group]] if group == "doctype" else body[group]
            for row in rows:
                insert(setup, group, [dict(name=row["name"], modified=financial._validate_scalar(row["modified"]),
                    **{key: financial._validate_scalar(value) for key, value in row["header"]})])
    with setup.cursor() as cursor:
        for doctype, rows in case.records.items():
            table = "Singles" if doctype == "System Settings" else doctype
            for row in rows: cursor.execute("INSERT INTO `tab" + table + "` VALUES (%s,%s,%s)", row)
        cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','api_secret','PRIVATE-NEVER-RETURN')")
    setup.commit()
    setup.close()
    case.connection = connections(isolation)
    case.reader = source.MariaDBCurrencyFormatReader(case.connection)
    return case


@pytest.mark.parametrize("flag", [None, "", "0", "1"])
@pytest.mark.parametrize("number_format", [None, "", "#.########"])
@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_native_values_metadata_and_singleton_storage_are_bound_without_cleanup(connections, flag, number_format, isolation):
    case = native_case(connections, flag=flag, currency_format=number_format, isolation=isolation)
    observed = load(case, case.reader)
    assert observed.context.use_currency_format is (flag == "1")
    assert observed.context.currency_number_format == number_format
    assert b"PRIVATE-NEVER-RETURN" not in observed._payload
    case.reader.require_unchanged(observed)
    observed.require_context_match(observed.context)
    assert case.connection.open and not case.connection.get_autocommit()


@pytest.mark.parametrize("changed", ["flag", "null_to_blank", "language", "currency", "revision", "metadata", "membership"])
def test_native_rechecks_detect_changes_including_equal_effective_flag_values(connections, changed):
    case = native_case(connections, flag=None)
    original = load(case, case.reader)
    with case.connection.cursor() as cursor:
        if changed == "flag": cursor.execute("UPDATE `tabSingles` SET value='1' WHERE field=%s", (source.FLAG,))
        elif changed == "null_to_blank": cursor.execute("UPDATE `tabSingles` SET value='' WHERE field=%s", (source.FLAG,))
        elif changed == "language": cursor.execute("UPDATE `tabLanguage` SET number_format='#.###'")
        elif changed == "currency": cursor.execute("UPDATE `tabCurrency` SET number_format='#.###'")
        elif changed == "revision": cursor.execute("UPDATE `tabLanguage` SET modified=modified+INTERVAL 1 SECOND")
        elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND")
        else: cursor.execute("DELETE FROM `tabSingles` WHERE field=%s", (source.FLAG,))
    failure(lambda: case.reader.require_unchanged(original), "currency_format_source_changed")
    assert case.connection.open  # The caller still owns dirty work/cleanup.


@pytest.mark.parametrize("fault", ["missing", "duplicate", "missing_language", "missing_currency"])
def test_missing_and_duplicate_sources_do_not_become_default_configuration(connections, fault):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        if fault == "duplicate": cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,'1')", ("System Settings", source.FLAG))
        elif fault == "missing": cursor.execute("DELETE FROM `tabSingles` WHERE field=%s", (source.FLAG,))
        else: cursor.execute("DELETE FROM `tab" + ("Language" if fault == "missing_language" else "Currency") + "`")
    failure(lambda: load(case, case.reader))


@pytest.mark.parametrize("target", ["Currency", "Language", "Singles", "DocField"])
def test_selected_value_and_metadata_locks_last_until_caller_cleanup(connections, target):
    case = native_case(connections)
    load(case, case.reader)
    ready = Event()
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            if target == "Singles": cursor.execute("UPDATE `tabSingles` SET value='0' WHERE field=%s", (source.FLAG,))
            elif target == "DocField": cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND")
            else: cursor.execute("UPDATE `tab" + target + "` SET number_format='#.###'")
        writer.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        case.connection.rollback()
        future.result(timeout=5)


def test_rc_duplicate_insertion_is_detected_at_the_next_completion_boundary(connections):
    case = native_case(connections, isolation="READ COMMITTED")
    original = load(case, case.reader)
    writer = connections("READ COMMITTED")
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,'1')", ("System Settings", source.FLAG))
    writer.commit()
    failure(lambda: case.reader.require_unchanged(original), "currency_format_source_changed")


def test_oversized_growth_between_length_and_value_is_sql_masked(connections):
    case = native_case(connections)
    done = []
    def mutate(sql, params):
        if not done and "FROM `tabCurrency`" in sql and "CASE WHEN" not in sql:
            done.append(True)
            with case.connection.cursor() as cursor:
                cursor.execute("UPDATE `tabCurrency` SET number_format=%s", ("PRIVATE" * 1000,))
    wrapped, calls, returned = instrument(case.connection, mutate)
    failure(lambda: load(case, source.MariaDBCurrencyFormatReader(wrapped)))
    full = [rows for sql, rows in returned if "FROM `tabCurrency`" in sql and "CASE WHEN" in sql]
    assert full and "PRIVATE" not in repr(full)
    assert all("FROM `tabSystem Settings`" not in sql for sql, _ in calls)


def test_native_context_resolves_precision_without_rewriting_persisted_values(connections):
    case = native_case(connections, currency_format="#.########")
    observed = load(case, case.reader)
    meta, defaults = declarations(values={})
    resolution = FieldPrecisionResolution(meta, "grand_total", defaults, 16, observed.context)
    assert resolution.precision == 8
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT number_format,modified FROM `tabCurrency`")
        assert cursor.fetchone() == ("#.########", NOW)


def test_reader_observes_own_pending_values_without_saving_or_discarding_parent_work(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor:
        cursor.execute("INSERT INTO currency_parent_work VALUES ('PENDING')")
        cursor.execute("UPDATE `tabCurrency` SET number_format='#.###'")
    observed = load(case, case.reader)
    assert observed.context.currency_number_format == "#.###"
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM currency_parent_work")
        assert cursor.fetchone() == (0,)
        cursor.execute("SELECT number_format FROM `tabCurrency`")
        assert cursor.fetchone() == ("#.########",)
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT name FROM currency_parent_work")
        assert cursor.fetchone() == ("PENDING",)


def test_missing_field_currency_avoids_a_currency_table_lookup(connections):
    case = native_case(connections, currency=None, flag="0")
    wrapped, calls, _ = instrument(case.connection)
    observed = load(case, source.MariaDBCurrencyFormatReader(wrapped))
    assert observed.context.currency is None
    assert not any("FROM `tabCurrency`" in sql for sql, _ in calls)


def test_null_text_still_binds_the_physical_column_family(connections):
    case = native_case(connections, currency_format=None)
    original = load(case, case.reader)
    case.connection.rollback()
    setup = connections(autocommit=True)
    try:
        with setup.cursor() as cursor: cursor.execute("ALTER TABLE `tabCurrency` MODIFY number_format BIGINT")
        failure(lambda: case.reader.require_unchanged(original), "currency_format_source_changed")
    finally:
        case.connection.rollback()
        with setup.cursor() as cursor: cursor.execute("ALTER TABLE `tabCurrency` MODIFY number_format LONGTEXT")


def test_format_metadata_uses_the_existing_property_setter_reconciliation(connections):
    from zatca_erpgulf.zatca_erpgulf import source_metadata as schema
    case = native_case(connections)
    raw = case.raw_metas["Language"]
    raw.definitions["number_format"].values["options"] = "SYNTHETIC-FORMAT-LIST"
    case.metas["Language"] = schema.project_source_metadata(raw, base_fields={}, profile=schema.FORMAT_PROFILE)
    setup = connections()
    insert(setup, "property_setters", [dict(name="LANG-FORMAT-SETTER", modified=NOW,
        doctype_or_field="DocField", doc_type="Language", field_name="number_format",
        property="options", property_type="Data", value="SYNTHETIC-FORMAT-LIST")])
    setup.commit()
    observed = load(case, case.reader)
    language_metadata = next(row for row in observed.metadata if row.applied.name == "Language")
    assert language_metadata.base.get_field("number_format").options is None
    assert language_metadata.applied.get_field("number_format").options == "SYNTHETIC-FORMAT-LIST"
    with case.connection.cursor() as cursor:
        cursor.execute("UPDATE `tabProperty Setter` SET value='CHANGED'")
    failure(lambda: case.reader.require_unchanged(observed), "currency_format_source_changed")
