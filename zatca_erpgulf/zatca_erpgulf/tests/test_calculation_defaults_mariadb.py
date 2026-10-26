"""Native defaults reads on a guarded owned private SQL server, never a site."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
import json
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults as defaults
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import NOW, PARENTS, row, static_failure
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Guarded owned temporary SQL only; no tenant or authority access")


@pytest.fixture(scope="module")
def defaults_schema(isolated_server):
    # Deliberately synthetic storage. This is not an app installer, migration,
    # restored Frappe schema, installed-version acceptance or permission proof.
    connection = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""CREATE TABLE `tabDefaultValue` (
                `name` VARCHAR(140) PRIMARY KEY,`creation` DATETIME(6),`modified` DATETIME(6),
                `parent` VARCHAR(140),`defkey` VARCHAR(140),`defvalue` LONGTEXT,
                INDEX defaults_scope (`parent`,`defkey`,`creation`)
            ) ENGINE=InnoDB""")
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def empty_defaults(defaults_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("DELETE FROM `tabDefaultValue`")
    setup.commit()  # Only synthetic fixture ownership, never a runtime reader.
    setup.close()


def insert(connection, records):
    with connection.cursor() as cursor:
        for record in records:
            cursor.execute("""INSERT INTO `tabDefaultValue`
                (`name`,`creation`,`modified`,`parent`,`defkey`,`defvalue`)
                VALUES (%s,%s,%s,%s,%s,%s)""", record)


def seed(connections, records):
    setup = connections()
    insert(setup, records)
    setup.commit()
    setup.close()


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("parent", PARENTS)
def test_native_explicit_scope_and_selected_keys_only(connections, parent, isolation):
    seed(connections, [row(parent=parent),
        row("SECOND", parent=parent, value="0", offset=1),
        row("OTHER-SCOPE", parent="unrelated@example.invalid", value="PRIVATE-OTHER-SCOPE"),
        row("SECRET", parent=parent, key="api_secret", value="PRIVATE-UNSELECTED")])
    connection = connections(isolation)
    reader = defaults.MariaDBCalculationDefaultsReader(connection)
    observed = reader.load_for_update(parent)
    observed.require_cache_match(parent, {"currency_precision": ["2", "0"], "api_secret": object()})
    reader.require_unchanged(observed)
    assert b"PRIVATE" not in observed._payload
    connection.rollback()
    assert defaults.MariaDBCalculationDefaultsReader(connection).load_for_update(parent) == observed


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_locking_read_sees_current_data_even_after_a_stale_mvcc_snapshot(connections, isolation):
    seed(connections, [row()])
    reader = connections(isolation)
    with reader.cursor() as cursor:
        cursor.execute("SELECT defvalue FROM `tabDefaultValue` WHERE name=%s", ("SYNTHETIC-1",))
        assert cursor.fetchone() == ("2",)
    writer = connections(isolation)
    with writer.cursor() as cursor:
        cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3' WHERE name=%s", ("SYNTHETIC-1",))
    writer.commit()
    observed = defaults.MariaDBCalculationDefaultsReader(reader).load_for_update("__default")
    observed.require_cache_match("__default", {"currency_precision": "3"})
    static_failure(lambda: observed.require_cache_match("__default", {"currency_precision": "2"}),
        "calculation_defaults_cache_mismatch")


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("action", ["update", "delete"])
def test_loaded_row_locks_survive_return_until_caller_releases_transaction(connections, isolation, action):
    seed(connections, [row()])
    owner = connections(isolation)
    defaults.MariaDBCalculationDefaultsReader(owner).load_for_update("__default")
    ready = Event()

    def compete():
        writer = connections(isolation)
        ready.set()
        with writer.cursor() as cursor:
            sql = ("UPDATE `tabDefaultValue` SET defvalue='3' WHERE name=%s" if action == "update"
                else "DELETE FROM `tabDefaultValue` WHERE name=%s")
            cursor.execute(sql, ("SYNTHETIC-1",))
        writer.commit()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        owner.rollback()  # Explicit test owner; the reader did not release locks.
        future.result(timeout=5)


@pytest.mark.parametrize("empty", [False, True])
def test_read_committed_recheck_detects_phantom_membership_even_with_same_effect(connections, empty):
    if not empty: seed(connections, [row()])
    owner = connections("READ COMMITTED")
    reader = defaults.MariaDBCalculationDefaultsReader(owner)
    observed = reader.load_for_update("__default")
    writer = connections("READ COMMITTED")
    insert(writer, [row("NEW-MEMBER", offset=1)])
    writer.commit()
    static_failure(lambda: reader.require_unchanged(observed), "calculation_defaults_changed")
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_transaction_unusable")


@pytest.mark.parametrize("empty", [False, True])
def test_reviewed_repeatable_read_index_blocks_selected_insert_until_caller_rollback(connections, empty):
    if not empty: seed(connections, [row()])
    owner = connections("REPEATABLE READ")
    defaults.MariaDBCalculationDefaultsReader(owner).load_for_update("__default")
    ready = Event()

    def compete():
        writer = connections("REPEATABLE READ")
        ready.set()
        insert(writer, [row("NEW-MEMBER", offset=1)])
        writer.commit()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compete)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        owner.rollback()
        future.result(timeout=5)


@pytest.mark.parametrize("committed", [False, True])
def test_pending_other_transaction_is_not_read_as_committed(connections, committed):
    seed(connections, [row()])
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3' WHERE name=%s", ("SYNTHETIC-1",))
    ready = Event()

    def read():
        connection = connections()
        ready.set()
        return defaults.MariaDBCalculationDefaultsReader(connection).load_for_update("__default")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        writer.commit() if committed else writer.rollback()
        observed = future.result(timeout=5)
    observed.require_cache_match("__default", {"currency_precision": "3" if committed else "2"})


def test_same_transaction_own_writes_are_visible_and_never_implicitly_committed(connections):
    owner = connections()
    insert(owner, [row()])
    observed = defaults.MariaDBCalculationDefaultsReader(owner).load_for_update("__default")
    observed.require_cache_match("__default", {"currency_precision": "2"})
    # Honest boundary: a caller's pending writes cannot be labelled committed.
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM `tabDefaultValue`")
        assert cursor.fetchone() == (0,)
    owner.rollback()
    assert defaults.MariaDBCalculationDefaultsReader(owner).load_for_update("__default") != observed


@pytest.mark.parametrize("change", ["parent_case", "key_case", "ambiguous_creation", "value_size", "row_count"])
def test_native_ambiguity_collation_and_bounds_fail_closed(connections, change):
    records = [row()]
    if change == "parent_case": records = [row(parent="__DEFAULT")]
    elif change == "key_case": records = [row(key="Currency_Precision")]
    elif change == "ambiguous_creation": records += [row("SECOND", value="3")]
    elif change == "value_size": records = [row(value="X" * (defaults.MAX_VALUE_BYTES + 1))]
    else:
        records = [row(f"ROW-{index:03}", offset=index) for index in range(defaults.MAX_ROWS + 1)]
    seed(connections, records)
    connection = connections()
    reader = defaults.MariaDBCalculationDefaultsReader(connection)
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_read")
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_transaction_unusable")


@pytest.mark.parametrize("change", ["modified", "identity", "order"])
def test_recheck_after_explicit_release_detects_revisions_identity_and_order(connections, change):
    seed(connections, [row()])
    owner = connections()
    reader = defaults.MariaDBCalculationDefaultsReader(owner)
    observed = reader.load_for_update("__default")
    owner.rollback()
    writer = connections()
    with writer.cursor() as cursor:
        if change == "modified":
            cursor.execute("UPDATE `tabDefaultValue` SET modified=%s", (NOW + timedelta(seconds=1),))
        elif change == "identity": cursor.execute("UPDATE `tabDefaultValue` SET name='REPLACED'")
        else: cursor.execute("UPDATE `tabDefaultValue` SET creation=%s", (NOW + timedelta(seconds=1),))
    writer.commit()
    static_failure(lambda: reader.require_unchanged(observed), "calculation_defaults_changed")


def test_native_autocommit_is_refused_without_changing_the_session(connections):
    connection = connections(autocommit=True)
    reader = defaults.MariaDBCalculationDefaultsReader(connection)
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_read")
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@session.autocommit")
        assert cursor.fetchone() == (1,)


def test_all_three_calculation_keys_keep_separate_zero_blank_and_format_values(connections):
    seed(connections, [row(value="0"), row("FLOAT", key="float_precision", value="", offset=1),
        row("FORMAT", key="number_format", value="#,##0.000", offset=2)])
    observed = defaults.MariaDBCalculationDefaultsReader(connections()).load_for_update("__default")
    observed.require_cache_match("__default", {
        "currency_precision": "0", "float_precision": "", "number_format": "#,##0.000"})


@pytest.mark.parametrize("value", ["X" * 4096, "أ" * 2048])
def test_exact_value_byte_bound_roundtrips_without_silent_sql_truncation(connections, value):
    seed(connections, [row(key="number_format", value=value)])
    observed = defaults.MariaDBCalculationDefaultsReader(connections()).load_for_update("__default")
    observed.require_cache_match("__default", {"number_format": value})


def test_exact_membership_limit_is_accepted_and_not_coalesced_in_the_digest(connections):
    seed(connections, [row(f"ROW-{index:03}", offset=index) for index in range(defaults.MAX_ROWS)])
    observed = defaults.MariaDBCalculationDefaultsReader(connections()).load_for_update("__default")
    observed.require_cache_match("__default", {"currency_precision": "2"})
    assert observed != defaults.CalculationDefaultsRows("__default", defaults._canonical(dict(
        profile=defaults.PROFILE, parent="__default", keys=list(defaults.KEYS), rows=[])))


def test_real_lock_timeout_is_redacted_and_requires_caller_cleanup(connections):
    seed(connections, [row()])
    owner = connections()
    defaults.MariaDBCalculationDefaultsReader(owner).load_for_update("__default")
    blocked = connections()
    reader = defaults.MariaDBCalculationDefaultsReader(blocked)
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_read")
    static_failure(lambda: reader.load_for_update("__default"), "calculation_defaults_transaction_unusable")
    assert owner.open and blocked.open
    owner.rollback()
    blocked.rollback()
    defaults.MariaDBCalculationDefaultsReader(blocked).load_for_update("__default").require_cache_match(
        "__default", {"currency_precision": "2"})


@pytest.mark.parametrize("same_key", [True, False])
def test_equal_time_membership_order_uses_binary_names_without_fiscal_precedence(connections, same_key):
    seed(connections, [row("a", key="currency_precision"),
        row("B", key="currency_precision" if same_key else "float_precision")])
    connection = connections()
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM `tabDefaultValue` ORDER BY name")
        assert cursor.fetchall() == (("a",), ("B",))  # Fixture's normal CI collation.
    observed = defaults.MariaDBCalculationDefaultsReader(connection).load_for_update("__default")
    expected = {"currency_precision": "2"}
    if not same_key: expected["float_precision"] = "2"
    observed.require_cache_match("__default", expected)
    # Raw tie ordering is deterministic; equal-time different VALUES still fail.
    assert [item["name"] for item in json.loads(observed._payload)["rows"]] == ["B", "a"]
