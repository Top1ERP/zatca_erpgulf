"""One new guarded SQL fixture for saved source, metadata and defaults context."""

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
from threading import Event
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_context_access import declarations, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access_mariadb import (
    access_schema, native_case as saved_case, untouched, NOW,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import defaults_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Owned guarded temporary SQL only; no working-site or authority access")


@pytest.fixture(autouse=True)
def empty_combined_sources(access_schema, metadata_schema, connections):
    setup = connections()
    tables = ("defaults_parent_work", "tabDefaultValue", "tabCompany", "tabSales Invoice", "tabPOS Invoice",
        "tabDocType", "tabDocField", "tabCustom Field", "tabProperty Setter")
    with setup.cursor() as cursor:
        for table in tables: cursor.execute("DELETE FROM `" + table + "`")
    setup.commit()  # Only fixture setup; no service commits.
    setup.close()


def native_case(operator, connections, *, isolation="REPEATABLE READ", **options):
    case = saved_case(operator, connections, isolation=isolation, **options)
    case.metadata_cases = {name: declarations(name) for name in ("Company", case.invoice.doctype)}
    case.applied = {name: item.applied for name, item in case.metadata_cases.items()}
    setup = connections()
    for selected in case.metadata_cases.values():
        for group, records in selected.records.items(): insert(setup, group, records)
    setup.commit()
    setup.close()
    case.metadata_provider = Mock(side_effect=lambda scope, types: dict(case.applied))
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=options.get("parent_kind", "site"), applied_metadata_reader=case.metadata_provider)
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("parent_kind", access.PARENT_KINDS)
def test_actual_context_uses_one_owned_handle_for_all_three_sources(defaults_operator, connections, doctype, parent_kind):
    case = native_case(defaults_operator, connections, doctype=doctype, parent_kind=parent_kind)
    result = capture(case)
    assert result.settings.defaults.parent == case.parent
    assert tuple(selected.applied.name for selected in result.metadata) == ("Company", doctype)
    assert case.metadata_provider.call_count == 2 and len(case.opened) == 1
    assert case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


def test_owned_pending_metadata_is_discarded_before_combined_acquisition(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    def pending(owned):
        with owned.cursor() as cursor: cursor.execute("UPDATE `tabProperty Setter` SET value='3'")
    case.before_handoff = pending
    result = capture(case)
    assert all(selected.applied == case.applied[selected.applied.name] for selected in result.metadata)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", [1, 2])
@pytest.mark.parametrize("changed", ["metadata", "defaults", "source"])
def test_cache_callback_sql_edits_are_detected_and_rolled_back_together(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    def cached(*args):
        if case.cache.call_count == boundary:
            with case.opened[0].cursor() as cursor:
                if changed == "metadata": cursor.execute("UPDATE `tabProperty Setter` SET value='3'")
                elif changed == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                else: cursor.execute("UPDATE `tabCompany` SET modified=%s", (NOW + timedelta(seconds=1),))
        return {"currency_precision": "2"}
    case.cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT DISTINCT value FROM `tabProperty Setter`")
        assert cursor.fetchall() == (("2",),)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("2",)
        cursor.execute("SELECT modified FROM `tabCompany`")
        assert cursor.fetchone() == (NOW,)


@pytest.mark.parametrize("changed", ["applied", "metadata", "defaults"])
def test_final_metadata_callback_is_checked_before_any_result_or_cleanup_disclosure(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def supplied(*args):
        if case.metadata_provider.call_count == 2:
            if changed == "applied":
                selected = case.metadata_cases[case.invoice.doctype]
                selected.meta.definitions[selected.ordinary[0]].values["options"] = "CHANGED"
                case.applied[case.invoice.doctype] = project(selected.meta)
            else:
                with case.opened[0].cursor() as cursor:
                    if changed == "metadata": cursor.execute("UPDATE `tabProperty Setter` SET value='3'")
                    else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        return dict(case.applied)
    case.metadata_provider.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)


def test_rc_same_effect_metadata_insertion_is_not_hidden_by_matching_cached_values(defaults_operator, connections):
    case = native_case(defaults_operator, connections, isolation="READ COMMITTED")
    def cached(*args):
        if case.cache.call_count == 2:
            writer = connections("READ COMMITTED")
            selected = case.metadata_cases[case.invoice.doctype]
            insert(writer, "property_setters", [dict(selected.records["property_setters"][0], name="NEW-SAME-EFFECT",
                field_name=selected.ordinary[1], property="fieldtype", property_type="Data", value="Data")])
            writer.commit()
        return {"currency_precision": "2"}
    case.cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_combined_read_preserves_pending_parent_even_with_borrowed_raw_rejection(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO defaults_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect = None
        case.factory.return_value = parent
        with pytest.raises(InspectionFailed): capture(case)
        case.cache.assert_not_called()
    else: capture(case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM defaults_parent_work")
        assert cursor.fetchone() == (0,)
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM defaults_parent_work")
        assert cursor.fetchone() == ("PENDING",)
    assert parent.open
    untouched(defaults_operator, case)
    parent.rollback()


@pytest.mark.parametrize("boundary", [1, 2])
def test_metadata_callback_acl_loss_denies_protected_result(defaults_operator, connections, boundary):
    case = native_case(defaults_operator, connections)
    def supplied(*args):
        if case.metadata_provider.call_count == boundary:
            defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        return dict(case.applied)
    case.metadata_provider.side_effect = supplied
    with pytest.raises(PermissionDenied): capture(case)
    one_failure(defaults_operator, access.DENIED_MESSAGE)
    assert len(case.opened) == (0 if boundary == 1 else 1)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("selected", ["metadata", "defaults"])
def test_both_metadata_and_default_locks_survive_until_combined_cleanup(defaults_operator, connections, selected):
    case = native_case(defaults_operator, connections)
    ready, futures = Event(), []
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            if selected == "metadata":
                name = case.metadata_cases["Company"].records["property_setters"][0]["name"]
                cursor.execute("UPDATE `tabProperty Setter` SET value='3' WHERE name=%s", (name,))
            else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        writer.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        def cached(*args):
            if case.cache.call_count == 2:
                futures.append(pool.submit(compete))
                assert ready.wait(5)
                with pytest.raises(TimeoutError): futures[0].result(timeout=0.05)
            return {"currency_precision": "2"}
        case.cache.side_effect = cached
        result = capture(case)
        futures[0].result(timeout=5)
    assert result.settings.defaults.parent == case.parent
    untouched(defaults_operator, case)
