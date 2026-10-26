"""Permissioned acquisition on new fixture-owned SQL, with synthetic ACL only."""

from datetime import timedelta
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import row
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario, capture, one_failure, NOW, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import defaults_schema, insert
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Guarded owned temporary SQL only; no tenant or authority access")


@pytest.fixture(scope="module")
def access_schema(defaults_schema, isolated_server):
    connection = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE defaults_parent_work (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE `tabCompany` (name VARCHAR(140) PRIMARY KEY,modified DATETIME(6)) ENGINE=InnoDB")
            for table in ("tabSales Invoice", "tabPOS Invoice"):
                cursor.execute("CREATE TABLE `" + table + "` (name VARCHAR(140) PRIMARY KEY,modified DATETIME(6),"
                    "company VARCHAR(140),docstatus INT) ENGINE=InnoDB")
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def empty_sources(access_schema, connections):
    connection = connections()
    with connection.cursor() as cursor:
        for table in ("defaults_parent_work", "tabDefaultValue", "tabCompany", "tabSales Invoice", "tabPOS Invoice"):
            cursor.execute("DELETE FROM `" + table + "`")
    connection.commit()  # Only synthetic fixture setup, never a service operation.
    connection.close()


def native_case(operator, connections, *, isolation="REPEATABLE READ", **options):
    case = scenario(operator, **options)
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("INSERT INTO `tabCompany` VALUES (%s,%s)", (case.company.name, NOW))
        cursor.execute("INSERT INTO `tab" + case.invoice.doctype + "` VALUES (%s,%s,%s,%s)",
            (case.invoice.name, NOW, case.company.name, case.invoice.docstatus))
    insert(setup, [row(parent=case.parent)])
    setup.commit()
    setup.close()
    case.opened = []
    case.before_handoff = None

    def connect(scope):
        assert scope == case.scope
        raw = connections(isolation)
        owned = SimpleNamespace(cursor=raw.cursor, rollback=Mock(side_effect=raw.rollback),
            close=Mock(side_effect=raw.close), commit=Mock(side_effect=raw.commit), raw=raw)
        case.opened.append(owned)
        if case.before_handoff: case.before_handoff(owned)
        return owned

    case.factory = Mock(side_effect=connect)
    case.service = access.SavedCalculationDefaultsService(case.scope, case.factory, case.cache,
        parent_kind=options.get("parent_kind", "site"))
    return case


def untouched(operator, case):
    operator.runtime.db.commit.assert_not_called()
    operator.runtime.db.rollback.assert_not_called()
    for owned in case.opened:
        owned.commit.assert_not_called()
        owned.close.assert_called_once()
        assert not owned.raw.open
    for document in operator.documents.values():
        document.save.assert_not_called()
        document.db_set.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("parent_kind", access.PARENT_KINDS)
@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_native_authorized_read_needs_no_phase2_columns_or_owner_settings(defaults_operator, connections, doctype, parent_kind, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, parent_kind=parent_kind, isolation=isolation)
    result = capture(case)
    assert result.defaults.parent == case.parent and result.actor == defaults_operator.runtime.session.user
    result.defaults.require_cache_match(case.parent, {"currency_precision": "2"})
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("pending", ["defaults", "source"])
def test_new_owned_rollback_excludes_preexisting_uncommitted_source_and_default_edits(defaults_operator, connections, pending):
    case = native_case(defaults_operator, connections)
    def pending_work(owned):
        with owned.cursor() as cursor:
            if pending == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
            else: cursor.execute("UPDATE `tabCompany` SET modified=%s", (NOW + timedelta(seconds=1),))
    case.before_handoff = pending_work
    result = capture(case)
    result.defaults.require_cache_match(case.parent, {"currency_precision": "2"})
    assert case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_real_pending_parent_work_is_neither_saved_nor_discarded(defaults_operator, connections, borrowed):
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
    parent.rollback()  # Explicit fixture owner only.


@pytest.mark.parametrize("change", ["invoice_revision", "company_revision", "ownership", "status", "missing"])
def test_stale_ambient_document_cannot_hide_actual_committed_source_drift(defaults_operator, connections, change):
    case = native_case(defaults_operator, connections)
    writer = connections()
    with writer.cursor() as cursor:
        if change == "invoice_revision":
            cursor.execute("UPDATE `tabSales Invoice` SET modified=%s", (NOW + timedelta(seconds=1),))
        elif change == "company_revision":
            cursor.execute("UPDATE `tabCompany` SET modified=%s", (NOW + timedelta(seconds=1),))
        elif change == "ownership": cursor.execute("UPDATE `tabSales Invoice` SET company='OTHER'")
        elif change == "status": cursor.execute("UPDATE `tabSales Invoice` SET docstatus=1")
        else: cursor.execute("DELETE FROM `tabSales Invoice`")
    writer.commit()
    with pytest.raises(InspectionFailed): capture(case)
    case.cache.assert_not_called()
    untouched(defaults_operator, case)


def test_actual_default_change_denies_stale_cache_without_overwrite(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    writer = connections()
    with writer.cursor() as cursor: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
    writer.commit()
    with pytest.raises(InspectionFailed): capture(case)
    assert case.cache.call_count == 1
    one_failure(defaults_operator, access.FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("3",)


@pytest.mark.parametrize("boundary", [1, 2])
def test_actual_rc_membership_change_during_cache_callback_denies_even_equal_values(defaults_operator, connections, boundary):
    case = native_case(defaults_operator, connections, isolation="READ COMMITTED")
    def cache(*args):
        if case.cache.call_count == boundary:
            writer = connections("READ COMMITTED")
            insert(writer, [row("NEW-MEMBER", parent=case.parent, offset=1)])
            writer.commit()
        return {"currency_precision": "2"}
    case.cache.side_effect = cache
    with pytest.raises(InspectionFailed): capture(case)
    assert case.cache.call_count == boundary
    untouched(defaults_operator, case)


@pytest.mark.parametrize("selected", ["defaults", "source"])
def test_callback_own_transaction_changes_are_detected_and_rolled_back(defaults_operator, connections, selected):
    case = native_case(defaults_operator, connections)
    def cache(*args):
        if case.cache.call_count == 2:
            with case.opened[0].cursor() as cursor:
                if selected == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                else: cursor.execute("UPDATE `tabCompany` SET modified=%s", (NOW + timedelta(seconds=1),))
        return {"currency_precision": "2"}
    case.cache.side_effect = cache
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("2",)
        cursor.execute("SELECT modified FROM `tabCompany`")
        assert cursor.fetchone() == (NOW,)


@pytest.mark.parametrize("boundary", [1, 2])
def test_late_acl_revocation_denies_before_return_and_cleans_actual_handle(defaults_operator, connections, boundary):
    case = native_case(defaults_operator, connections)
    def cache(*args):
        if case.cache.call_count == boundary:
            defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        return {"currency_precision": "2"}
    case.cache.side_effect = cache
    with pytest.raises(PermissionDenied): capture(case)
    one_failure(defaults_operator, access.DENIED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("interrupt", [False, True])
def test_actual_cleanup_failure_does_not_return_a_protected_result(defaults_operator, connections, interrupt):
    case = native_case(defaults_operator, connections)
    def handoff(owned):
        def close():
            owned.raw.close()
            raise KeyboardInterrupt() if interrupt else RuntimeError("PRIVATE CLOSE")
        owned.close.side_effect = close
    case.before_handoff = handoff
    with pytest.raises(KeyboardInterrupt if interrupt else InspectionFailed): capture(case)
    untouched(defaults_operator, case)
