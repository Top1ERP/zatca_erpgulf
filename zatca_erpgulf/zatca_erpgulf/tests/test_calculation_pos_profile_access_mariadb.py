"""Saved POS/financial/default acquisition on NEW guard-owned SQL only."""

from decimal import Decimal
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_pos_profile_access import normal_pos, configure, capture, detach_child_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_pos_profile_source_mariadb import (
    native_case as source_case, pos_schema, empty_pos, financial_schema, metadata_schema, isolated_server, connections,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import combined_schema, defaults_schema, untouched
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import insert as insert_defaults
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import row

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_sources(empty_pos, combined_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for table in ("Company", "DefaultValue"): cursor.execute(f"DELETE FROM `tab{table}`")
        cursor.execute("DELETE FROM financial_parent_work")
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()


def native_case(operator, connections, *, isolation="REPEATABLE READ", **options):
    data = source_case(connections, isolation=isolation, **options)
    data.connection.close()
    case = defaults_case(operator, doctype=data.doctype, docstatus=1)
    case.parent_kind = "site"
    bind(case, data, operator)
    normal_pos(case, operator)
    setup = connections()
    seed_metadata(setup, case.observations["Company"])
    with setup.cursor() as cursor:
        cursor.execute(f"UPDATE `tab{case.invoice.doctype}` SET modified=%s", (case.invoice.modified,))
        cursor.execute("INSERT INTO `tabCompany` VALUES (%s,%s)", (case.company.name, case.company.modified))
    insert_defaults(setup, [row(parent=case.parent)])
    setup.commit()
    setup.close()
    case.opened, case.statements, case.before_handoff = [], [], None
    def connect(scope):
        assert scope == case.scope
        raw = connections(isolation)
        owned = SimpleNamespace(cursor=raw.cursor, raw=raw, rollback=Mock(side_effect=raw.rollback),
            close=Mock(side_effect=raw.close), commit=Mock(side_effect=raw.commit))
        original = owned.cursor
        def cursor():
            current = original();execute = current.execute
            def run(sql, params=()):
                case.statements.append((sql, params))
                return execute(sql, params)
            current.execute = run
            return current
        owned.cursor = cursor
        case.opened.append(owned)
        if case.before_handoff: case.before_handoff(owned)
        return owned
    case.factory = Mock(side_effect=connect)
    return configure(case)


@pytest.mark.parametrize("kind", ["limit", "default"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_native_pos_graph_metadata_and_defaults_use_same_owned_connection(defaults_operator, connections, kind, major, isolation):
    case = native_case(defaults_operator, connections, kind=kind, major=major, isolation=isolation)
    result = capture(case, major=major)
    assert result.lookup.financial == result.financial.financial and result.master.name == "SYNTHETIC-POS"
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    if kind == "limit":
        assert result.lookup.limit_observation().value == Decimal("2.500000000")
        assert not any("FROM `tabPOS Payment Method`" in sql for sql, _ in case.statements)
    else:
        assert result.lookup.default_observation().mode_of_payment == "Cash"
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["pos_last", "root_last", "defaults_last"])
@pytest.mark.parametrize("changed", ["mode", "company", "metadata", "defaults", "financial_child"])
def test_last_callbacks_cannot_bypass_native_final_checks_or_leave_writes(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    callback = {"pos_last": case.pos_metadata, "root_last": case.metadata_provider, "defaults_last": case.cache}[boundary]
    original = callback.side_effect or (lambda *args: callback.return_value)
    def supply(*args):
        value = original(*args)
        if callback.call_count == (4 if boundary == "root_last" else 2):
            with case.opened[0].cursor() as cursor:
                if changed == "mode": cursor.execute("UPDATE `tabPOS Payment Method` SET mode_of_payment='Bank'")
                elif changed == "company": cursor.execute("UPDATE `tabPOS Profile` SET company='OTHER'")
                elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE parent='POS Profile'")
                elif changed == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                else: cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
        return value
    callback.side_effect = supply
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT company FROM `tabPOS Profile`");assert cursor.fetchone() == ("SYNTHETIC-CO",)
        cursor.execute("SELECT mode_of_payment FROM `tabPOS Payment Method`");assert cursor.fetchone() == ("Cash",)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`");assert cursor.fetchone() == ("2",)


@pytest.mark.parametrize("changed", ["permission", "field", "membership"])
def test_real_close_rechecks_normal_profile_and_child_access(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def wrap(owned):
        original = owned.close.side_effect
        def close():
            result = original()
            if changed == "permission": defaults_operator.denied.add(("POS Profile", case.master.name))
            elif changed == "field": case.pos_definitions["POS Payment Method"]["default"].permlevel = 2
            else: case.master.payments = []
            return result
        owned.close.side_effect = close
    case.before_handoff = wrap
    with pytest.raises(InspectionFailed if changed == "membership" else PermissionDenied): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE if changed == "membership" else access.FINANCIAL_DENIED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_ambient_pending_work_is_preserved_and_borrowed_handle_refused(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect = None;case.factory.return_value = parent
        with pytest.raises(InspectionFailed): capture(case)
    else: assert capture(case).lookup.kind == "default"
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work");assert cursor.fetchall() == (("PENDING",),)


def test_initial_owned_rollback_excludes_uncommitted_profile_change(defaults_operator, connections):
    case = native_case(defaults_operator, connections, kind="limit")
    def pending(owned):
        with owned.cursor() as cursor: cursor.execute("UPDATE `tabPOS Profile` SET write_off_limit=10")
    case.before_handoff = pending
    assert capture(case).lookup.limit_observation().value == Decimal("2.500000000")
    untouched(defaults_operator, case)


@pytest.mark.parametrize("target", ["reference", "saved"])
def test_real_close_cannot_hide_original_child_metadata_drift(defaults_operator, connections, target):
    case = native_case(defaults_operator, connections)
    child = case.pos_refs[0] if target == "reference" else case.pos_saved[0]
    def wrap(owned):
        original = owned.close.side_effect
        def close():
            value = original()
            detach_child_metadata(child)
            return value
        owned.close.side_effect = close
    case.before_handoff = wrap
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major", [15, 16])
def test_standalone_pos_root_uses_the_same_saved_source_boundary(defaults_operator, connections, major):
    case = native_case(defaults_operator, connections, doctype="POS Invoice", major=major)
    result = capture(case, major=major)
    assert result.financial.financial.financial.doctype == "POS Invoice"
    assert result.lookup.default_observation().mode_of_payment == "Cash"
    assert len(case.opened) == 1
    untouched(defaults_operator, case)
