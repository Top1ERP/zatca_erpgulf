"""Native selected metadata rows on a new guarded private SQL fixture only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
import json
import os
from threading import Event
from types import SimpleNamespace

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import metadata_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source import scenario, failure, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned guarded temporary SQL only; no installed metadata or authority access")


@pytest.fixture(scope="module")
def metadata_schema(isolated_server):
    connection = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with connection.cursor() as cursor:
            for group, (table, fields) in source.SPECS.items():
                columns = ["`name` VARCHAR(140) PRIMARY KEY", "`modified` DATETIME(6)"]
                for name in fields:
                    kind = "BIGINT" if name in source.NUMERIC else ("LONGTEXT" if name in ("default", "options", "value") else "VARCHAR(140)")
                    columns.append("`" + name + "` " + kind)
                if group == "docfields": columns.append("INDEX source_scope (`parent`,`fieldname`)")
                elif group == "custom_fields": columns.append("INDEX source_scope (`dt`,`fieldname`)")
                elif group == "property_setters": columns.append("INDEX source_scope (`doc_type`,`field_name`,`property`)")
                cursor.execute("CREATE TABLE `tab" + table + "` (" + ",".join(columns) + ") ENGINE=InnoDB")
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def empty_metadata(metadata_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for table, _ in source.SPECS.values(): cursor.execute("DELETE FROM `tab" + table + "`")
    setup.commit()  # Synthetic fixture owner, never a runtime reader.
    setup.close()


def insert(connection, group, records):
    table, fields = source.SPECS[group]
    columns = ("name", "modified", *fields)
    with connection.cursor() as cursor:
        for record in records:
            cursor.execute("INSERT INTO `tab" + table + "` (" + ",".join("`" + name + "`" for name in columns)
                + ") VALUES (" + ",".join("%s" for _ in columns) + ")", tuple(record.get(name) for name in columns))


def seed(connections, case):
    setup = connections()
    for group, records in case.records.items(): insert(setup, group, records)
    setup.commit()
    setup.close()


def native_case(connections, doctype="Sales Invoice", isolation="REPEATABLE READ"):
    case = scenario(doctype)
    seed(connections, case)
    case.connection = connections(isolation)
    case.reader = source.MariaDBMetadataSourceReader(case.connection)
    return case


def instrument(connection, hook=None):
    calls, returned = [], []
    class Cursor:
        @property
        def description(self): return self.raw.description
        def __enter__(self):
            self.raw = connection.cursor()
            return self
        def __exit__(self, *args): return self.raw.__exit__(*args)
        def execute(self, sql, args=()):
            calls.append((sql, args))
            self.sql = sql
            result = self.raw.execute(sql, args)
            if hook: hook(sql, args)
            return result
        def fetchone(self): return self.raw.fetchone()
        def fetchall(self):
            rows = self.raw.fetchall()
            returned.append((self.sql, rows))
            return rows
    return SimpleNamespace(cursor=Cursor), calls, returned


@pytest.mark.parametrize("doctype", source.SOURCE_FIELDS)
def test_every_selected_type_roundtrips_and_matches_applied_metadata(connections, doctype):
    case = native_case(connections, doctype)
    observed = case.reader.load_for_update(case.applied)
    assert observed.applied == case.applied and observed.match.base == observed.base
    case.reader.require_unchanged(observed)
    assert case.connection.open and case.connection.get_autocommit() is False
    case.connection.rollback()
    assert source.MariaDBMetadataSourceReader(case.connection).load_for_update(case.applied) == observed


def test_unselected_or_unrelated_password_defaults_and_ui_setters_are_not_returned(connections):
    case = scenario()
    case.records["docfields"] += [dict(case.records["docfields"][0], name="PRIVATE-FIELD",
        fieldname="custom_private_key", fieldtype="Password", default="PRIVATE-NEVER-RETURN")]
    case.records["property_setters"] += [dict(case.records["property_setters"][0], name="UI-ONLY",
        property="label", value="PRIVATE-LABEL")]
    seed(connections, case)
    observed = source.MariaDBMetadataSourceReader(connections()).load_for_update(case.applied)
    assert b"PRIVATE" not in observed._payload and b"UI-ONLY" not in observed._payload


@pytest.mark.parametrize("group", ["docfields", "custom_fields", "property_setters"])
def test_native_password_preflight_never_projects_sensitive_default_or_value(connections, group):
    case = scenario()
    if group == "property_setters":
        case.records[group][0].update(property_type="Password", value="PRIVATE-VALUE")
    else: case.records[group][0].update(fieldtype="Password", default="PRIVATE-VALUE")
    seed(connections, case)
    wrapped, calls, _ = instrument(connections())
    reader = source.MariaDBMetadataSourceReader(wrapped)
    failure(lambda: reader.load_for_update(case.applied))
    table = source.SPECS[group][0]
    queries = [sql for sql, _ in calls if "FROM `tab" + table + "`" in sql]
    assert len(queries) == 1 and "CASE WHEN" not in queries[0] and "SUBSTRING(`value`" not in queries[0]


def test_rc_password_field_phantom_is_masked_then_membership_is_refused(connections):
    case = native_case(connections, isolation="READ COMMITTED")
    selected = set(case.ordinary) | {case.custom} | set(source.BASE_TYPES)
    phantom_name = next(name for name in source.SOURCE_FIELDS[case.doctype] if name not in selected)
    done = []
    def add_after_preflight(sql, args):
        if not done and "FROM `tabDocField`" in sql and "CASE WHEN" not in sql:
            done.append(True)
            writer = connections("READ COMMITTED")
            insert(writer, "docfields", [dict(case.records["docfields"][0], name="Z-PHANTOM",
                fieldname=phantom_name, fieldtype="Password", default="PRIVATE-NEVER-RETURN", idx=3)])
            writer.commit()
    wrapped, _, returned = instrument(case.connection, add_after_preflight)
    failure(lambda: source.MariaDBMetadataSourceReader(wrapped).load_for_update(case.applied))
    full = [rows for sql, rows in returned if "FROM `tabDocField`" in sql and "CASE WHEN" in sql][0]
    phantom = next(row for row in full if row[0] == "Z-PHANTOM")
    default_index = 2 + source.STANDARD_FIELDS.index("default")
    assert phantom[default_index] is None and "PRIVATE-NEVER-RETURN" not in repr(full)


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_current_locked_rows_cannot_hide_behind_an_earlier_mvcc_snapshot(connections, isolation):
    case = native_case(connections, isolation=isolation)
    with case.connection.cursor() as cursor:
        cursor.execute("SELECT value FROM `tabProperty Setter`")
        assert cursor.fetchone() == ("2",)
    writer = connections(isolation)
    with writer.cursor() as cursor: cursor.execute("UPDATE `tabProperty Setter` SET value='3'")
    writer.commit()
    failure(lambda: case.reader.load_for_update(case.applied))


@pytest.mark.parametrize("group", ["doctype", "docfields", "custom_fields", "property_setters"])
def test_exact_raw_revision_is_rechecked_after_caller_releases_locks(connections, group):
    case = native_case(connections)
    observed = case.reader.load_for_update(case.applied)
    case.connection.rollback()
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("UPDATE `tab" + source.SPECS[group][0] + "` SET modified=%s", (NOW + timedelta(seconds=1),))
    writer.commit()
    failure(lambda: case.reader.require_unchanged(observed), "metadata_source_changed")


def test_rc_new_setter_with_unchanged_effect_is_still_detected_as_new_membership(connections):
    case = native_case(connections, isolation="READ COMMITTED")
    observed = case.reader.load_for_update(case.applied)
    writer = connections("READ COMMITTED")
    insert(writer, "property_setters", [dict(case.records["property_setters"][0], name="Z-NEW-SETTER",
        field_name=case.ordinary[1], property="fieldtype", property_type="Data", value="Data")])
    writer.commit()
    failure(lambda: case.reader.require_unchanged(observed), "metadata_source_changed")


@pytest.mark.parametrize("group", ["docfields", "custom_fields", "property_setters"])
def test_selected_rows_stay_locked_until_caller_cleanup(connections, group):
    case = native_case(connections)
    case.reader.load_for_update(case.applied)
    ready = Event()
    def competing():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            cursor.execute("UPDATE `tab" + source.SPECS[group][0] + "` SET modified=%s", (NOW + timedelta(seconds=1),))
        writer.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(competing)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        case.connection.rollback()
        future.result(timeout=5)


@pytest.mark.parametrize("fault", ["case", "storage", "virtual", "duplicate", "large", "nullable_revision"])
def test_native_unsupported_rows_fail_closed_or_preserve_explicit_null_revision(connections, fault):
    case = scenario()
    if fault == "case": case.records["docfields"][0]["fieldname"] = case.ordinary[0].upper()
    elif fault == "storage": case.records["property_setters"][0].update(
        doctype_or_field="DocType", field_name=None, property="issingle")
    elif fault == "virtual": case.records["docfields"][0]["is_virtual"] = 1
    elif fault == "duplicate": case.records["custom_fields"].append(dict(case.records["custom_fields"][0], name="Z-EXTRA"))
    elif fault == "large": case.records["docfields"][0]["options"] = "أ" * source.MAX_TEXT_BYTES
    else: case.records["docfields"][0]["modified"] = None
    seed(connections, case)
    reader = source.MariaDBMetadataSourceReader(connections())
    if fault == "nullable_revision":
        observed = reader.load_for_update(case.applied)
        assert json.loads(observed._payload)["docfields"][0]["modified"] == ["null"]
    else: failure(lambda: reader.load_for_update(case.applied))


def test_own_pending_metadata_is_visible_but_never_committed_by_the_reader(connections):
    case = native_case(connections)
    with case.connection.cursor() as cursor: cursor.execute("UPDATE `tabDocField` SET modified=%s", (NOW + timedelta(seconds=1),))
    pending = case.reader.load_for_update(case.applied)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT modified FROM `tabDocField` LIMIT 1")
        assert cursor.fetchone() == (NOW,)
    case.connection.rollback()
    assert source.MariaDBMetadataSourceReader(case.connection).load_for_update(case.applied) != pending


def test_rc_password_setter_phantom_is_masked_before_membership_rejection(connections):
    case = native_case(connections, isolation="READ COMMITTED")
    done = []
    def add_after_preflight(sql, args):
        if not done and "FROM `tabProperty Setter`" in sql and "CASE WHEN" not in sql:
            done.append(True)
            writer = connections("READ COMMITTED")
            insert(writer, "property_setters", [dict(case.records["property_setters"][0],
                name="Z-PHANTOM", field_name=case.ordinary[1], property="default",
                property_type="Password", value="PRIVATE-PASSWORD-VALUE")])
            writer.commit()
    wrapped, _, returned = instrument(case.connection, add_after_preflight)
    failure(lambda: source.MariaDBMetadataSourceReader(wrapped).load_for_update(case.applied))
    full = [rows for sql, rows in returned if "FROM `tabProperty Setter`" in sql and "CASE WHEN" in sql][0]
    phantom = next(row for row in full if row[0] == "Z-PHANTOM")
    assert phantom[-1] is None and "PRIVATE-PASSWORD-VALUE" not in repr(full)


@pytest.mark.parametrize("value", ["X" * 8192, "أ" * 4096])
def test_exact_utf8_bound_preserves_metadata_without_truncation(connections, value):
    case = scenario()
    case.records["docfields"][0]["options"] = value
    case.meta.definitions[case.ordinary[0]].values["options"] = value
    from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project
    case.applied = project(case.meta)
    seed(connections, case)
    observed = source.MariaDBMetadataSourceReader(connections()).load_for_update(case.applied)
    assert observed.base.get_field(case.ordinary[0]).get("options") == value
