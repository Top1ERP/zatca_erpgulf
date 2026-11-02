"""Selected field composition on NEW guard-owned TCP-disabled SQL only."""

from decimal import Decimal
import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import configure, capture, TARGETS
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_numeric_access_mariadb import (
    native_case as numeric_case, empty_sources, combined_schema, defaults_schema,
    financial_schema, metadata_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, InspectionFailed, PermissionDenied,
)

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled fixture only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_method(empty_sources, format_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("DELETE FROM `tabSingles`")
    setup.commit()  # NEW synthetic setup only.
    setup.close()


def native_case(operator, connections, **options):
    case = numeric_case(operator, connections, **options)
    configure(case, operator, value="Commercial Rounding")
    setup = connections()
    seed_metadata(setup, case.round_observation)
    with setup.cursor() as cursor:
        cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','rounding_method','Commercial Rounding')")
        cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','api_secret','PRIVATE-NEVER-RETURN')")
    setup.commit()
    setup.close()
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("target", [TARGETS[0], TARGETS[1], ("payments", "payments-1", "amount"),
    ("advances", "advances-1", "allocated_amount"),
    ("custom_zatca_advance_deduction_details", "custom_zatca_advance_deduction_details-1", "allocated_total_amount")])
def test_native_values_defaults_method_and_selected_owner_cache_bind_one_handle(defaults_operator, connections, doctype, major, isolation, target):
    case = native_case(defaults_operator, connections, doctype=doctype, isolation=isolation)
    case.invoice._precision = {target[0] or "main": {target[2]: 2}}
    result = capture(case, major, target)
    result.require_result_match(8.7 if target[0] is None else 1.0)
    assert result.method.context == result.numeric.financial.context
    assert b"PRIVATE" not in result.method.rounding._payload
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["method_metadata", "method_cache", "defaults_cache"])
@pytest.mark.parametrize("changed", ["amount", "default", "method"])
def test_late_callbacks_cannot_change_same_owned_native_sources(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    callback = {"method_metadata": case.round_metadata, "method_cache": case.round_cache,
        "defaults_cache": case.cache}[boundary]
    original = callback.side_effect
    edits = []
    def read(*args):
        result = original(*args) if original else callback.return_value
        if callback.call_count == 2:
            with case.opened[0].cursor() as cursor:
                if changed == "amount": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                elif changed == "default": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                else: cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'", ("Banker's Rounding",))
            edits.append(changed)
        return result
    callback.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    assert edits == [changed]
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT amount FROM `tabSales Invoice Item`")
        assert cursor.fetchone() == (Decimal("1.000000000"),)
        cursor.execute("SELECT value FROM `tabSingles` WHERE field='rounding_method'")
        assert cursor.fetchone() == ("Commercial Rounding",)
    observer.close()


@pytest.mark.parametrize("changed", ["cache", "method_acl", "getter"])
def test_real_cleanup_cannot_hide_selected_owner_or_access_drift(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def wrap(owned):
        close = owned.close.side_effect
        def done():
            close()
            if changed == "cache": case.invoice._precision = {"main": {"grand_total": 2}}
            elif changed == "getter": case.invoice.grand_total = Decimal("8.7")
            else: defaults_operator.denied.add(("System Settings", "System Settings"))
        owned.close.side_effect = done
    case.before_handoff = wrap
    with pytest.raises(PermissionDenied if changed == "method_acl" else InspectionFailed): capture(case)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_caller_pending_work_is_never_cleaned(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect, case.factory.return_value = None, parent
        with pytest.raises(InspectionFailed): capture(case)
    else: capture(case).require_result_match(8.7)
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall() == (("PENDING",),)
