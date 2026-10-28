"""Saved rounding capture on NEW guard-owned TCP-disabled SQL fixtures only."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import rounding_setting_source as source
from zatca_erpgulf.zatca_erpgulf.calculation_rounding import LEGACY_METHOD
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_rounding_access import bind_rounding, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, InspectionFailed,
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
def empty_rounding(empty_combined_sources, format_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("DELETE FROM `tabSingles`")
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()


def native_case(operator, connections, *, value=LEGACY_METHOD, missing=False, **options):
    case = context_case(operator, connections, **options)
    bind_rounding(case, operator, value=value, missing=missing)
    setup = connections()
    seed_metadata(setup, case.round_observation)
    with setup.cursor() as cursor:
        if not missing:
            cursor.execute("INSERT INTO `tabSingles` VALUES (%s,%s,%s)", ("System Settings", "rounding_method", value))
        cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','api_secret','PRIVATE-NEVER-RETURN')")
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
@pytest.mark.parametrize("value,missing", [(None, False), ("", False), (None, True), ("Commercial Rounding", False)])
def test_native_rounding_binding_has_one_handle_no_secret_projection(defaults_operator, connections, doctype, major, isolation, value, missing):
    case = native_case(defaults_operator, connections, doctype=doctype, isolation=isolation, value=value, missing=missing)
    result = capture(case, major=major)
    assert result.method == (value or LEGACY_METHOD) and result.erp_major == major
    assert result.rounding.stored is not missing and result.rounding.value == value
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    assert case.round_cache.call_count == 3
    assert b"PRIVATE" not in result.rounding._payload
    singles = [(statement, params) for statement, params in case.statements if "FROM `tabSingles`" in statement]
    assert singles and all(params in (("System Settings", "rounding_method", 2), ("System Settings",)) for _, params in singles)
    assert all("*" not in statement for statement, _ in singles)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major", [15, 16])
def test_native_override_does_not_access_unused_singleton(defaults_operator, connections, major):
    case = native_case(defaults_operator, connections)
    defaults_operator.denied.add(("System Settings", "System Settings"))
    result = capture(case, major=major, override="Commercial Rounding")
    assert result.method == "Commercial Rounding" and result.rounding is None
    case.round_cache.assert_not_called()
    case.round_metadata.assert_not_called()
    assert not any("tabSingles" in statement for statement, _ in case.statements)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("boundary", ["cache_first", "cache_last", "metadata_last"])
@pytest.mark.parametrize("changed", ["value", "presence", "metadata"])
def test_native_callback_changes_without_modified_are_refused_and_rolled_back(defaults_operator, connections, isolation, boundary, changed):
    case = native_case(defaults_operator, connections, isolation=isolation)
    provider = case.round_metadata if boundary == "metadata_last" else case.round_cache
    original = provider.side_effect
    def read(*args):
        result = original(*args)
        if provider.call_count == (1 if boundary == "cache_first" else 2):
            with case.opened[0].cursor() as cursor:
                if changed == "value": cursor.execute("UPDATE `tabSingles` SET value='Commercial Rounding' WHERE field='rounding_method'")
                elif changed == "presence": cursor.execute("DELETE FROM `tabSingles` WHERE field='rounding_method'")
                else: cursor.execute("UPDATE `tabDocField` SET `default`='Commercial Rounding' WHERE parent='System Settings'")
        return result
    provider.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT value FROM `tabSingles` WHERE field='rounding_method'")
        assert cursor.fetchall() == ((LEGACY_METHOD,),)
        cursor.execute("SELECT `default` FROM `tabDocField` WHERE parent='System Settings'")
        assert cursor.fetchall() == ((None,),)


@pytest.mark.parametrize("fault", ["duplicate", "case", "oversized", "unknown", "empty_singleton", "cache"])
def test_invalid_native_source_and_cache_never_return_a_fallback(defaults_operator, connections, fault):
    case = native_case(defaults_operator, connections)
    setup = connections()
    with setup.cursor() as cursor:
        if fault == "duplicate": cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','rounding_method',NULL)")
        elif fault == "case": cursor.execute("UPDATE `tabSingles` SET field='Rounding_Method' WHERE field='rounding_method'")
        elif fault == "oversized": cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'", ("X" * 4097,))
        elif fault == "unknown": cursor.execute("UPDATE `tabSingles` SET value='UNKNOWN-PRIVATE' WHERE field='rounding_method'")
        elif fault == "empty_singleton": cursor.execute("DELETE FROM `tabSingles`")
        else: case.round_cache.side_effect = lambda *args: None
    setup.commit()
    setup.close()
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)


def test_caller_owned_reader_preserves_pending_work_and_poisoned_state(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    borrowed = connections()
    with borrowed.cursor() as cursor:
        cursor.execute("UPDATE `tabSingles` SET value='Commercial Rounding' WHERE field='rounding_method'")
    reader = source.MariaDBRoundingSettingReader(borrowed)
    observed = reader.load_for_update(applied_metadata=case.round_observation.applied)
    assert observed.value == "Commercial Rounding"
    reader.require_unchanged(observed)
    with borrowed.cursor() as cursor:
        cursor.execute("UPDATE `tabSingles` SET value='' WHERE field='rounding_method'")
    with pytest.raises(source.RoundingSettingSourceError, match="^rounding_setting_changed$"):
        reader.require_unchanged(observed)
    with pytest.raises(source.RoundingSettingSourceError, match="^rounding_setting_transaction_unusable$"):
        reader.load_for_update(applied_metadata=case.round_observation.applied)
    assert borrowed.open
    borrowed.rollback()
    with borrowed.cursor() as cursor:
        cursor.execute("SELECT value FROM `tabSingles` WHERE field='rounding_method'")
        assert cursor.fetchone() == (LEGACY_METHOD,)


@pytest.mark.parametrize("changed", ["defaults", "invoice", "company_metadata"])
def test_last_rounding_provider_cannot_bypass_final_checks_of_other_sources(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    original = case.round_metadata.side_effect
    def supplied(*args):
        result = original(*args)
        if case.round_metadata.call_count == 2:
            with case.opened[0].cursor() as cursor:
                if changed == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                elif changed == "invoice": cursor.execute("UPDATE `tabSales Invoice` SET docstatus=1")
                else: cursor.execute("UPDATE `tabDocField` SET options='CHANGED' WHERE parent='Company'")
        return result
    case.round_metadata.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT DISTINCT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchall() == (("2",),)
        cursor.execute("SELECT docstatus FROM `tabSales Invoice`")
        assert cursor.fetchall() == ((0,),)
        cursor.execute("SELECT COUNT(*) FROM `tabDocField` WHERE options='CHANGED'")
        assert cursor.fetchone() == (0,)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_absent_row_becoming_stored_null_is_drift_despite_equal_method_and_cache(defaults_operator, connections, isolation):
    case = native_case(defaults_operator, connections, missing=True, isolation=isolation)
    original = case.round_cache.side_effect
    def read(*args):
        result = original(*args)
        if case.round_cache.call_count == 2:
            with case.opened[0].cursor() as cursor:
                cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','rounding_method',NULL)")
        return result
    case.round_cache.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM `tabSingles` WHERE field='rounding_method'")
        assert cursor.fetchone() == (0,)


def test_owned_initial_rollback_excludes_pending_rounding_values(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    trace = case.before_handoff
    def pending(owned):
        trace(owned)
        with owned.cursor() as cursor:
            cursor.execute("UPDATE `tabSingles` SET value='Commercial Rounding' WHERE field='rounding_method'")
    case.before_handoff = pending
    result = capture(case)
    assert result.method == LEGACY_METHOD and case.round_cache.call_count == 3
    untouched(defaults_operator, case)
