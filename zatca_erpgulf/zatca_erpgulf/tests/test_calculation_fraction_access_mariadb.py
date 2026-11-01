"""Permissioned Currency API read on NEW guard-owned TCP-disabled SQL only."""

from decimal import Decimal
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_fraction_access import bind_fraction, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_fraction_source_mariadb import (
    native_case as source_case, fraction_schema, empty_sources as empty_fraction,
    financial_schema, metadata_schema, isolated_server, connections,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import combined_schema, defaults_schema, untouched
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import insert as insert_defaults
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import row

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_sources(empty_fraction, combined_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for table in ("Company", "DefaultValue"): cursor.execute("DELETE FROM `tab" + table + "`")
        cursor.execute("DELETE FROM financial_parent_work")
    setup.commit()  # NEW synthetic fixture owner only.
    setup.close()


def native_case(operator, connections, *, doctype="Sales Invoice", isolation="REPEATABLE READ", **options):
    data = source_case(connections, doctype=doctype, isolation=isolation, **options)
    data.connection.close()
    case = defaults_case(operator, doctype=doctype, docstatus=1)
    case.parent_kind = "site"
    bind(case, data, operator)
    setup = connections()
    seed_metadata(setup, case.observations["Company"])
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tab" + doctype + "` SET modified=%s", (case.invoice.modified,))
        cursor.execute("INSERT INTO `tabCompany` VALUES (%s,%s)", (case.company.name, case.company.modified))
    insert_defaults(setup, [row(parent=case.parent)])
    setup.commit()
    setup.close()
    case.opened, case.before_handoff, case.statements = [], None, []
    def connect(scope):
        assert scope == case.scope
        raw = connections(isolation)
        owned = SimpleNamespace(cursor=raw.cursor, rollback=Mock(side_effect=raw.rollback),
            close=Mock(side_effect=raw.close), commit=Mock(side_effect=raw.commit), raw=raw)
        original = owned.cursor
        def cursor():
            current = original()
            execute = current.execute
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
    return bind_fraction(case, operator)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("value", [None, Decimal("0.000000000"), Decimal("0.050000000")])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_native_fraction_graph_defaults_and_exact_api_share_one_owned_handle(defaults_operator, connections, doctype, major, value, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, isolation=isolation, value=value, currency="USD")
    result = capture(case, major)
    assert result.fraction.financial == result.financial.financial
    assert result.fraction.currency == result.related[0].name == "USD"
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    selected = [(sql, args) for sql, args in case.statements if "FROM `tabCurrency`" in sql]
    assert selected and all(args == ("USD", 2) for _, args in selected)
    assert all("private_secret" not in sql and "*" not in sql for sql, _ in selected)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["fraction_last", "api_last", "root_last", "defaults_last"])
@pytest.mark.parametrize("changed", ["fraction", "metadata", "financial_child", "defaults"])
def test_last_callbacks_are_followed_by_native_rechecks_of_all_sources(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    callback = {"fraction_last": case.fraction_metadata, "api_last": case.fraction_cache,
        "root_last": case.metadata_provider, "defaults_last": case.cache}[boundary]
    original = callback.side_effect or (lambda *args: callback.return_value)
    def supplied(*args):
        result = original(*args)
        if callback.call_count == (4 if boundary == "root_last" else 2):
            with case.opened[0].cursor() as cursor:
                if changed == "fraction": cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=0.1 WHERE name='SAR'")
                elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE parent='Currency'")
                elif changed == "financial_child": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        return result
    callback.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT smallest_currency_fraction_value FROM `tabCurrency` WHERE name='SAR'")
        assert cursor.fetchone() == (Decimal("0.050000000"),)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("2",)


@pytest.mark.parametrize("changed", ["api", "permission", "field", "child_permission"])
def test_real_close_rechecks_consumed_api_and_normal_access(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def wrapped(owned):
        original = owned.close.side_effect
        def close():
            result = original()
            if changed == "api": case.api_fraction = 0.1
            elif changed == "permission": defaults_operator.denied.add(("Currency", case.currency.name))
            elif changed == "field": case.fraction_definition.permlevel = 1
            else: defaults_operator.denied.add(("Sales Taxes and Charges", "taxes-1"))
            return result
        owned.close.side_effect = close
    case.before_handoff = wrapped
    denied = changed != "api"
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_ambient_pending_work_is_neither_committed_nor_discarded(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect = None
        case.factory.return_value = parent
        with pytest.raises(InspectionFailed): capture(case)
    else: assert capture(case).fraction.effective_fraction == 0.05
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall() == (("PENDING",),)


def test_fresh_owned_initial_rollback_excludes_pending_fraction_change(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    def pending(owned):
        with owned.cursor() as cursor:
            cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=0.1 WHERE name='SAR'")
    case.before_handoff = pending
    assert capture(case).fraction.effective_fraction == 0.05
    untouched(defaults_operator, case)
