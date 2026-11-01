"""Global Check acquisition on NEW guard-owned TCP-disabled SQL only."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import global_rounding_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_global_rounding_access import bind_global, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_context_access_mariadb import (
    native_case as context_case, empty_combined_sources, access_schema, metadata_schema,
    defaults_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_global(empty_combined_sources, format_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("DELETE FROM `tabSingles`")
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()


def native_case(operator, connections, *, raw="0", missing=False, secret=True, **options):
    case = context_case(operator, connections, **options)
    bind_global(case, operator, raw=raw, missing=missing)
    setup = connections()
    seed_metadata(setup, case.global_observation)
    with setup.cursor() as cursor:
        if not missing:
            cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,%s)", (source.DOCTYPE, source.FIELD, raw))
        if secret:
            cursor.execute("INSERT INTO `tabSingles` VALUES ('Global Defaults','api_secret','PRIVATE-NEVER-RETURN')")
    setup.commit()
    setup.close()
    case.statements = []
    def record(owned):
        original = owned.cursor
        def cursor():
            current = original()
            execute = current.execute
            def run(statement, params=()):
                case.statements.append((statement, params))
                return execute(statement, params)
            current.execute = run
            return current
        owned.cursor = cursor
    case.before_handoff = record
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("raw,missing", [(None, True), (None, False), ("", False), ("0", False), ("1", False)])
def test_normal_read_and_api_cache_bind_one_owned_native_transaction(defaults_operator, connections, doctype, major, isolation, raw, missing):
    case = native_case(defaults_operator, connections, raw=raw, missing=missing, doctype=doctype, isolation=isolation)
    result = capture(case, major=major)
    assert result.global_rounding.value == case.global_api and result.global_rounding.stored is not missing
    assert case.global_doc.disable_rounded_total == 1
    assert result.related[0].fields == result.related[0].values == ()
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    assert case.global_cache.call_count == 3
    assert b"PRIVATE" not in result.global_rounding._payload
    singles = [(sql, params) for sql, params in case.statements if "FROM `tabSingles`" in sql]
    assert singles and all(params == (source.DOCTYPE, source.FIELD, 2) for _, params in singles)
    assert all("*" not in sql for sql, _ in singles)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("boundary", ["cache_first", "cache_last", "metadata_last"])
@pytest.mark.parametrize("changed", ["value", "presence", "metadata"])
def test_native_edits_from_trusted_callbacks_are_refused_and_rolled_back(defaults_operator, connections, isolation, boundary, changed):
    case = native_case(defaults_operator, connections, isolation=isolation)
    provider = case.global_metadata if boundary == "metadata_last" else case.global_cache
    original = provider.side_effect
    def read(*args):
        result = original(*args)
        if provider.call_count == (1 if boundary == "cache_first" else 2):
            with case.opened[0].cursor() as cursor:
                if changed == "value": cursor.execute("UPDATE `tabSingles` SET value='1' WHERE field=%s", (source.FIELD,))
                elif changed == "presence": cursor.execute("DELETE FROM `tabSingles` WHERE field=%s", (source.FIELD,))
                else: cursor.execute("UPDATE `tabDocField` SET `default`='0' WHERE parent=%s", (source.DOCTYPE,))
        return result
    provider.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT value FROM `tabSingles` WHERE field=%s", (source.FIELD,))
        assert cursor.fetchall() == (("0",),)
        cursor.execute("SELECT `default` FROM `tabDocField` WHERE parent=%s", (source.DOCTYPE,))
        assert cursor.fetchall() == (("1",),)


@pytest.mark.parametrize("changed", ["defaults", "invoice", "company_metadata"])
def test_last_global_metadata_callback_runs_before_final_checks_of_other_sources(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    original = case.global_metadata.side_effect
    def supplied(*args):
        result = original(*args)
        if case.global_metadata.call_count == 2:
            with case.opened[0].cursor() as cursor:
                if changed == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                elif changed == "invoice": cursor.execute("UPDATE `tabSales Invoice` SET docstatus=1")
                else: cursor.execute("UPDATE `tabDocField` SET options='CHANGED' WHERE parent='Company'")
        return result
    case.global_metadata.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)


def test_last_root_metadata_callback_cannot_change_global_source_undetected(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    original = case.metadata_provider.side_effect
    def supplied(*args):
        result = original(*args)
        if case.metadata_provider.call_count == 2:
            with case.opened[0].cursor() as cursor:
                cursor.execute("UPDATE `tabSingles` SET value='1' WHERE field=%s", (source.FIELD,))
        return result
    case.metadata_provider.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)


@pytest.mark.parametrize("fault", ["duplicate", "case", "oversized", "noncanonical", "cache"])
def test_invalid_native_values_do_not_fall_back_to_a_document_default(defaults_operator, connections, fault):
    case = native_case(defaults_operator, connections)
    setup = connections()
    with setup.cursor() as cursor:
        if fault == "duplicate": cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,NULL)", (source.DOCTYPE, source.FIELD))
        elif fault == "case": cursor.execute("UPDATE `tabSingles` SET field='Disable_Rounded_Total' WHERE field=%s", (source.FIELD,))
        elif fault == "oversized": cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field=%s", ("PRIVATE" * 1000, source.FIELD))
        elif fault == "noncanonical": cursor.execute("UPDATE `tabSingles` SET value='false' WHERE field=%s", (source.FIELD,))
        else: case.global_cache.side_effect = lambda *args: None
    setup.commit()
    setup.close()
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)


def test_wholly_empty_singleton_api_zero_is_not_document_default_one(defaults_operator, connections):
    case = native_case(defaults_operator, connections, missing=True, secret=False)
    result = capture(case)
    assert case.global_doc.disable_rounded_total == 1 and case.global_df.default == "1"
    assert result.global_rounding.value == 0 and result.global_rounding.stored is False


def test_rc_missing_to_stored_null_phantom_is_caught_despite_same_api_zero(defaults_operator, connections):
    case = native_case(defaults_operator, connections, missing=True, isolation="READ COMMITTED")
    original = case.global_cache.side_effect
    def cached(*args):
        result = original(*args)
        if case.global_cache.call_count == 2:
            writer = connections("READ COMMITTED")
            with writer.cursor() as cursor:
                cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,NULL)", (source.DOCTYPE, source.FIELD))
            writer.commit()  # NEW synthetic competing writer only.
            writer.close()
        return result
    case.global_cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)


def test_initial_owned_rollback_excludes_pending_global_changes(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    trace = case.before_handoff
    def pending(owned):
        trace(owned)
        with owned.cursor() as cursor:
            cursor.execute("UPDATE `tabSingles` SET value='1' WHERE field=%s", (source.FIELD,))
    case.before_handoff = pending
    result = capture(case)
    assert result.global_rounding.value == 0
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_pending_ambient_work_is_neither_committed_nor_discarded(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO defaults_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect = None
        case.factory.return_value = parent
        with pytest.raises(InspectionFailed): capture(case)
        case.global_cache.assert_not_called()
    else:
        assert capture(case).global_rounding.value == 0
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM defaults_parent_work")
        assert cursor.fetchall() == (("PENDING",),)
    observer = connections("READ COMMITTED")
    with observer.cursor() as cursor:
        cursor.execute("SELECT name FROM defaults_parent_work")
        assert cursor.fetchall() == ()


@pytest.mark.parametrize("boundary", ["cleanup", "cache_after_cleanup"])
def test_late_global_access_loss_blocks_disclosure_after_real_close(defaults_operator, connections, boundary):
    case = native_case(defaults_operator, connections)
    if boundary == "cleanup":
        trace = case.before_handoff
        def wrapped(owned):
            trace(owned)
            original = owned.close.side_effect
            def close():
                result = original()
                defaults_operator.denied.add((source.DOCTYPE, source.DOCTYPE))
                return result
            owned.close.side_effect = close
        case.before_handoff = wrapped
    else:
        original = case.global_cache.side_effect
        def read(*args):
            result = original(*args)
            if case.global_cache.call_count == 3:
                defaults_operator.denied.add((source.DOCTYPE, source.DOCTYPE))
            return result
        case.global_cache.side_effect = read
    with pytest.raises(PermissionDenied): capture(case)
    one_failure(defaults_operator, access.DENIED_MESSAGE)
    assert not case.opened[0].raw.open
