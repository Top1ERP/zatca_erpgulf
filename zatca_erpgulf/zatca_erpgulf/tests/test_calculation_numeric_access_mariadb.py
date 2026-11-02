"""Numeric getter/native comparison on NEW TCP-disabled fixture SQL only."""

from decimal import Decimal
import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_numeric_view as numeric
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access import bind_numeric, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    native_case as financial_case, empty_sources, combined_schema, defaults_schema,
    financial_schema, metadata_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import insert_data

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


def native_case(operator, connections, *, populated=True, **options):
    case = financial_case(operator, connections, **options)
    if populated:
        setup = connections()
        for table in ("payments", "advances", "custom_zatca_advance_deduction_details"):
            if table not in case.data.records: continue
            meta = case.data.metas[financial._child_type(case.invoice.doctype, table)]
            row = dict(name=table+"-1", parent=case.invoice.name, parenttype=case.invoice.doctype,
                parentfield=table, idx=1, modified=case.invoice.modified)
            for name in financial.TABLE_FIELDS[table]:
                if meta.has_field(name):
                    kind = meta.get_field(name).fieldtype
                    row[name] = Decimal("1.000000000") if kind in numeric.REAL_TYPES else 0 if kind == "Int" else "SYNTHETIC"
            insert_data(setup, case.invoice.doctype, table, [row])
            case.data.records[table].append(row)
        setup.commit()  # NEW synthetic fixture only.
        setup.close()
    return bind_numeric(case, operator)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("populated", [False, True])
def test_native_header_rows_payments_and_advances_bind_same_owned_read(defaults_operator, connections, doctype, major, isolation, populated):
    case = native_case(defaults_operator, connections, doctype=doctype, isolation=isolation, populated=populated)
    result = capture(case, major)
    assert result.view.financial == result.financial.financial
    assert len(result.tables) == 5
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    if populated:
        import json
        groups = {cell[0] for cell in json.loads(result.view._payload)["cells"]}
        assert groups == {"header", *financial.TABLE_FIELDS}
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["cache_last", "metadata_last"])
@pytest.mark.parametrize("changed", ["header", "item", "advance", "defaults"])
def test_late_callbacks_are_followed_by_native_rechecks_and_rollback(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    callback = case.cache if boundary == "cache_last" else case.metadata_provider
    original = callback.side_effect or (lambda *args: callback.return_value)
    edits = []
    def read(*args):
        value = original(*args)
        if callback.call_count == (2 if boundary == "cache_last" else 4):
            with case.opened[0].cursor() as cursor:
                if changed == "header": cursor.execute("UPDATE `tabSales Invoice` SET grand_total=2")
                elif changed == "item": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                elif changed == "advance": cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=2")
                else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                edits.append(changed)
        return value
    callback.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    assert edits == [changed]
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT grand_total FROM `tabSales Invoice`")
        assert cursor.fetchone() == (Decimal("8.700000000"),)
        cursor.execute("SELECT allocated_amount FROM `tabSales Invoice Advance`")
        assert cursor.fetchone() == (Decimal("1.000000000"),)


@pytest.mark.parametrize("changed", ["header", "child", "permission"])
def test_real_close_rechecks_original_numeric_values_and_read_access(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def wrap(owned):
        close = owned.close.side_effect
        def done():
            value = close()
            if changed == "header": case.invoice.grand_total = Decimal("8.7")
            elif changed == "child": case.saved["advances","advances-1"].allocated_amount = 1.0
            else: defaults_operator.denied.add(("Sales Invoice Advance","advances-1"))
            return value
        owned.close.side_effect = done
    case.before_handoff = wrap
    with pytest.raises(PermissionDenied if changed == "permission" else InspectionFailed): capture(case)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_ambient_pending_work_remains_owned_by_the_caller(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect, case.factory.return_value = None, parent
        with pytest.raises(InspectionFailed): capture(case)
    else: assert capture(case).view.stage == "SAVED"
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall() == (("PENDING",),)


def test_initial_owned_rollback_excludes_pending_money_changes(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    def pending(owned):
        with owned.cursor() as cursor: cursor.execute("UPDATE `tabSales Invoice` SET grand_total=2")
    case.before_handoff = pending
    assert capture(case).view.stage == "SAVED"
    untouched(defaults_operator, case)
