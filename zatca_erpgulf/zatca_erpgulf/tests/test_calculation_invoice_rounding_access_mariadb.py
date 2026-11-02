"""Permissioned invoice controls on NEW guard-owned TCP-disabled SQL only."""

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_invoice_rounding_access import bind_controls, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind
from zatca_erpgulf.zatca_erpgulf.tests.test_invoice_rounding_source_mariadb import (
    native_case as source_case, control_schema, empty_sources as empty_controls,
    financial_schema, metadata_schema, isolated_server, connections,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import combined_schema, defaults_schema, untouched
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import insert as insert_defaults
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import row
from zatca_erpgulf.zatca_erpgulf.invoice_rounding_source import FIELDS

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_sources(empty_controls, combined_schema, connections):
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
    return bind_controls(case, operator)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("present", [(), FIELDS, ("rounding_adjustment", "rounded_total")])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_native_graph_controls_and_getters_use_one_connection_without_child_link_reads(defaults_operator, connections, doctype, major, present, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, present=present, isolation=isolation)
    result = capture(case, major)
    assert result.controls.financial == result.financial.financial
    assert dict(result.checks) == dict(result.controls.normalized_checks)
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    columns = [(sql, args) for sql, args in case.statements if "information_schema.COLUMNS" in sql]
    assert columns and all(args == ("tab" + doctype, *FIELDS) for _, args in columns)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["control_last", "root_last", "cache_last"])
@pytest.mark.parametrize("changed", ["control_value", "control_meta", "financial_child", "defaults"])
def test_late_callbacks_cannot_invalidate_any_captured_native_source(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    callback = case.control_metadata if boundary == "control_last" else case.metadata_provider if boundary == "root_last" else case.cache
    original = callback.side_effect or (lambda *args: callback.return_value)
    def supplied(*args):
        result = original(*args)
        if callback.call_count == (4 if boundary == "root_last" else 2):
            with case.opened[0].cursor() as cursor:
                if changed == "control_value": cursor.execute("UPDATE `tabSales Invoice` SET is_consolidated=1")
                elif changed == "control_meta": cursor.execute("UPDATE `tabDocField` SET `default`='1' WHERE fieldname='is_consolidated'")
                elif changed == "financial_child": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        return result
    callback.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT is_consolidated FROM `tabSales Invoice`")
        assert cursor.fetchone() == (None,)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("2",)


@pytest.mark.parametrize("changed", ["getter", "permission", "child_permission"])
def test_real_cleanup_rechecks_original_getters_and_normal_access(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def wrapped(owned):
        original = owned.close.side_effect
        def close():
            result = original()
            if changed == "getter": case.invoice.is_consolidated = 1
            elif changed == "permission": defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
            else: defaults_operator.denied.add(("Sales Taxes and Charges", "taxes-1"))
            return result
        owned.close.side_effect = close
    case.before_handoff = wrapped
    with pytest.raises(InspectionFailed if changed == "getter" else PermissionDenied): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE if changed == "getter" else access.FINANCIAL_DENIED_MESSAGE)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_ambient_pending_work_is_neither_saved_nor_discarded(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect = None
        case.factory.return_value = parent
        with pytest.raises(InspectionFailed): capture(case)
    else:
        assert capture(case).controls.consolidated is False
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall() == (("PENDING",),)


def test_fresh_owned_initial_rollback_excludes_pending_control_changes(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    def pending(owned):
        with owned.cursor() as cursor: cursor.execute("UPDATE `tabSales Invoice` SET is_consolidated=1")
    case.before_handoff = pending
    result = capture(case)
    assert result.controls.consolidated is False
    assert dict(json.loads(result.controls._payload)["fields"])["is_consolidated"] == ["null"]
    untouched(defaults_operator, case)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
def test_native_null_and_normal_none_stay_distinct_from_fixed_zero(defaults_operator, connections, doctype, major):
    case = native_case(defaults_operator, connections, doctype=doctype)
    case.invoice.is_consolidated = case.invoice.disable_rounded_total = None
    result = capture(case, major)
    assert result.checks == (("is_consolidated", None), ("disable_rounded_total", None))
    assert dict(result.controls.normalized_checks) == dict(is_consolidated=0, disable_rounded_total=0)
    raw = dict(json.loads(result.controls._payload)["fields"])
    assert raw["is_consolidated"] == raw["disable_rounded_total"] == ["null"]
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("changed", ["native_null_to_zero", "getter_none_to_zero"])
def test_late_false_equivalent_native_or_getter_change_is_not_hidden(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    case.invoice.is_consolidated = case.invoice.disable_rounded_total = None
    def read(*args):
        if case.cache.call_count == 2:
            if changed == "native_null_to_zero":
                with case.opened[0].cursor() as cursor: cursor.execute("UPDATE `tabSales Invoice` SET disable_rounded_total=0")
            else: case.invoice.disable_rounded_total = 0
        return {"currency_precision": "2"}
    case.cache.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)
