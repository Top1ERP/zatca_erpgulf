"""Consumed rounding sources on NEW guard-owned TCP-disabled SQL only."""

from decimal import Decimal
import os

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_rounded_total_access import configure, capture, CASES
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_invoice_rounding_access_mariadb import (
    native_case as root_case, empty_sources as empty_owned_sources, empty_controls,
    control_schema, financial_schema, metadata_schema, combined_schema, defaults_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_fraction_source_mariadb import fraction_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_fraction_source import declarations as fraction_declarations
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(scope="module")
def selected_schema(fraction_schema, combined_schema, control_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root", database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            cursor.execute("CREATE TABLE `tabSingles` (doctype VARCHAR(140),field VARCHAR(140),value LONGTEXT) ENGINE=InnoDB")
    finally:
        setup.close()


@pytest.fixture(autouse=True)
def empty_selected(empty_owned_sources, selected_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for name in ("Currency", "Singles"): cursor.execute("DELETE FROM `tab" + name + "`")
    setup.commit()  # NEW synthetic fixture only.
    setup.close()


def native_case(operator, connections, *, global_value="0", fraction=Decimal("0.050000000"), **options):
    case = root_case(operator, connections, **options)
    configure(case, operator, fraction_declarations(value=fraction), global_value=global_value)
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabDocField` SET fieldtype='Link', options='Currency' WHERE parent=%s AND fieldname='currency'", (case.invoice.doctype,))
        cursor.execute("INSERT INTO `tabCurrency` VALUES (%s,%s,%s,'PRIVATE-NEVER-RETURN')", (case.currency.name, case.currency.modified, fraction))
        cursor.execute("INSERT INTO `tabSingles` VALUES ('Global Defaults','disable_rounded_total',%s)", (global_value,))
        cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','rounding_method',%s)", (case.round_doc.rounding_method,))
        cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','api_secret','PRIVATE-NEVER-RETURN')")
    for observed in (case.data.fraction, case.global_observation, case.round_observation): seed_metadata(setup, observed)
    setup.commit()
    setup.close()
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("consolidated,disabled,present,global_value,branch,origin", CASES)
def test_native_guarded_settings_share_one_transaction_without_unused_queries(defaults_operator, connections, doctype, major, consolidated, disabled, present, global_value, branch, origin):
    case = native_case(defaults_operator, connections, doctype=doctype, consolidated=consolidated,
        disabled=disabled, present=present, global_value=global_value)
    result = capture(case, major)
    assert (result.selection.branch, result.selection.disable_origin) == (branch, origin)
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    active = branch == "CURRENCY_FRACTION_THEN_FIELD_PRECISION"
    singles = [params[0] for sql, params in case.statements if "FROM `tabSingles`" in sql]
    assert ("Global Defaults" in singles) == (origin == "GLOBAL_DEFAULTS")
    assert ("System Settings" in singles) == (active or branch == "DISABLED" and major == 16)
    assert any("FROM `tabCurrency`" in sql for sql, _ in case.statements) == active
    assert all("api_secret" not in sql and "private_secret" not in sql for sql, _ in case.statements)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["global_last", "fraction_last", "method_last", "root_last"])
@pytest.mark.parametrize("changed", ["financial", "global", "fraction", "method", "defaults"])
def test_last_selected_callback_cannot_invalidate_any_captured_source(defaults_operator, connections, boundary, changed):
    present = ("is_consolidated", "rounding_adjustment", "rounded_total")
    case = native_case(defaults_operator, connections, present=present)
    callback = {"global_last": case.global_metadata, "fraction_last": case.fraction_metadata,
        "method_last": case.round_metadata, "root_last": case.metadata_provider}[boundary]
    original = callback.side_effect
    def read(*args):
        value = original(*args)
        if callback.call_count == (4 if boundary == "root_last" else 2):
            with case.opened[0].cursor() as cursor:
                if changed == "financial": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                elif changed == "global": cursor.execute("UPDATE `tabSingles` SET value='1' WHERE doctype='Global Defaults'")
                elif changed == "fraction": cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=0.1")
                elif changed == "method": cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'", ("Banker's Rounding",))
                else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        return value
    callback.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT smallest_currency_fraction_value FROM `tabCurrency`")
        assert cursor.fetchone() == (Decimal("0.050000000"),)
        cursor.execute("SELECT value FROM `tabSingles` WHERE doctype='Global Defaults'")
        assert cursor.fetchone() == ("0",)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("2",)


@pytest.mark.parametrize("changed", ["fraction", "method", "global", "getter"])
def test_real_close_rechecks_selected_api_and_original_guard(defaults_operator, connections, changed):
    present = ("is_consolidated", "rounding_adjustment", "rounded_total")
    case = native_case(defaults_operator, connections, present=present)
    def wrap(owned):
        original = owned.close.side_effect
        def close():
            value = original()
            if changed == "fraction": case.api_fraction = 0.1
            elif changed == "method": defaults_operator.denied.add(("System Settings", "System Settings"))
            elif changed == "global": case.global_api = 1
            else: case.invoice.disable_rounded_total = 1
            return value
        owned.close.side_effect = close
    case.before_handoff = wrap
    denied = changed == "method"
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    untouched(defaults_operator, case)


def test_initial_owned_rollback_excludes_pending_fraction_changes(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    def pending(owned):
        with owned.cursor() as cursor: cursor.execute("UPDATE `tabCurrency` SET smallest_currency_fraction_value=0.1")
    case.before_handoff = pending
    assert capture(case).selection.fraction.effective_fraction == 0.05
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_ambient_pending_work_remains_with_its_owner(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect = None
        case.factory.return_value = parent
        with pytest.raises(InspectionFailed): capture(case)
    else:
        assert capture(case).selection.fraction is not None
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall() == (("PENDING",),)
