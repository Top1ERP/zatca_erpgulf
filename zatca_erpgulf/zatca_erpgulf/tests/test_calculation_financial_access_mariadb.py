"""Combined permission boundary on a new guarded, TCP-disabled SQL fixture."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from decimal import Decimal
import json
import os
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, scenario as defaults_case, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access import bind, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults import row
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import defaults_schema, insert as insert_defaults
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import (
    financial_schema, native_case as financial_case, insert_data,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert as insert_meta
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Guarded owned temporary SQL only; no site, customer or authority access")


@pytest.fixture(scope="module")
def combined_schema(financial_schema, defaults_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            cursor.execute("CREATE TABLE `tabCompany` (name VARCHAR(140) PRIMARY KEY,modified DATETIME(6)) ENGINE=InnoDB")
            cursor.execute("CREATE TABLE financial_parent_work (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB")
    finally:
        setup.close()


@pytest.fixture(autouse=True)
def empty_sources(combined_schema, financial_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for dt in (*financial_schema, "Company", "DocType", "DocField", "Custom Field", "Property Setter", "DefaultValue"):
            cursor.execute("DELETE FROM `tab" + dt + "`")
        cursor.execute("DELETE FROM financial_parent_work")
    setup.commit()  # Synthetic fixture ownership, never a service operation.
    setup.close()


def native_case(operator, connections, *, doctype="Sales Invoice", optional=True,
        parent_kind="site", isolation="REPEATABLE READ"):
    data = financial_case(connections, doctype, optional=optional, isolation=isolation)
    data.connection.close()  # The permissioned service acquires its own handle.
    case = defaults_case(operator, doctype=doctype, parent_kind=parent_kind, docstatus=1)
    case.parent_kind = parent_kind
    bind(case, data, operator)
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tab" + doctype + "` SET modified=%s", (case.invoice.modified,))
        cursor.execute("INSERT INTO `tabCompany` VALUES (%s,%s)", (case.company.name, case.company.modified))
    company_metadata = json.loads(case.observations["Company"]._payload)
    raw = company_metadata["doctype"]
    insert_meta(setup, "doctype", [dict(name=raw["name"], modified=financial._validate_scalar(raw["modified"]),
        **{name: financial._validate_scalar(value) for name, value in raw["header"]})])
    insert_defaults(setup, [row(parent=case.parent)])
    setup.commit()
    setup.close()
    case.opened, case.before_handoff = [], None

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
        parent_kind=parent_kind, applied_metadata_reader=case.metadata_provider)
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
@pytest.mark.parametrize("optional", [True, False])
@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_actual_financial_metadata_and_defaults_share_one_owned_read(defaults_operator, connections, doctype, optional, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, optional=optional, isolation=isolation)
    result = capture(case, major=16)
    header = dict(json.loads(result.financial.financial._payload)["header"])
    assert header["grand_total"] == ["decimal", "8.700000000"]
    assert result.context.settings.defaults.parent == case.parent
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", [1, 2])
@pytest.mark.parametrize("changed", ["header", "child", "child_revision", "child_insert", "child_delete", "metadata", "defaults"])
def test_native_cache_callback_edits_without_parent_timestamp_are_detected_and_rolled_back(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    def cached(*args):
        if case.cache.call_count == boundary:
            owned = case.opened[0]
            if changed == "child_insert":
                insert_data(owned, case.invoice.doctype, "items", [dict(case.data.records["items"][0], name="items-2", idx=2)])
            else:
                with owned.cursor() as cursor:
                    if changed == "header": cursor.execute("UPDATE `tabSales Invoice` SET grand_total=2")
                    elif changed == "child": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                    elif changed == "child_revision": cursor.execute("UPDATE `tabSales Invoice Item` SET modified=modified+INTERVAL 1 SECOND")
                    elif changed == "child_delete": cursor.execute("DELETE FROM `tabSales Invoice Item`")
                    elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND")
                    else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        return {"currency_precision": "2"}
    case.cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT grand_total,modified FROM `tabSales Invoice`")
        assert cursor.fetchone() == (Decimal("8.700000000"), case.invoice.modified)
        cursor.execute("SELECT amount,modified FROM `tabSales Invoice Item`")
        item = case.data.records["items"][0]
        assert cursor.fetchall() == ((item["amount"], item["modified"]),)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("2",)


@pytest.mark.parametrize("changed", ["financial", "metadata", "defaults"])
def test_last_extended_metadata_callback_is_followed_by_native_rechecks(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def supplied(scope, types):
        if case.metadata_provider.call_count == 4:
            with case.opened[0].cursor() as cursor:
                if changed == "financial": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND")
                else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        return {name: case.applied[name] for name in types}
    case.metadata_provider.side_effect = supplied
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)


def test_actual_rc_child_membership_change_is_not_a_parent_revision_check(defaults_operator, connections):
    case = native_case(defaults_operator, connections, isolation="READ COMMITTED")
    def cached(*args):
        if case.cache.call_count == 2:
            writer = connections("READ COMMITTED")
            insert_data(writer, case.invoice.doctype, "items", [dict(case.data.records["items"][0], name="items-2", idx=2)])
            writer.commit()
        return {"currency_precision": "2"}
    case.cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("pending", ["financial", "metadata", "defaults"])
def test_owned_pending_changes_are_discarded_before_capture(defaults_operator, connections, pending):
    case = native_case(defaults_operator, connections)
    def handoff(owned):
        with owned.cursor() as cursor:
            if pending == "financial": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
            elif pending == "metadata": cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND")
            else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
    case.before_handoff = handoff
    result = capture(case)
    tables = dict(json.loads(result.financial.financial._payload)["tables"])
    assert dict(tables["items"]["rows"][0][2])["amount"] == ["decimal", "1.000000000"]
    untouched(defaults_operator, case)


@pytest.mark.parametrize("borrowed", [False, True])
def test_pending_parent_work_survives_capture_and_borrow_refusal(defaults_operator, connections, borrowed):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect = None
        case.factory.return_value = parent
        with pytest.raises(InspectionFailed): capture(case)
    else: capture(case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM financial_parent_work")
        assert cursor.fetchone() == (0,)
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchone() == ("PENDING",)
    assert parent.open
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["cache", "close"])
@pytest.mark.parametrize("fault", ["denied", "error", "interrupt"])
def test_late_denial_and_cleanup_failure_never_disclose_financial_result(defaults_operator, connections, boundary, fault):
    case = native_case(defaults_operator, connections)
    def fail():
        if fault == "denied": defaults_operator.denied.add((case.invoice.doctype, case.invoice.name))
        elif fault == "error": defaults_operator.runtime.throw("PRIVATE-OWNED-CALLBACK", InspectionFailed)
        else: raise KeyboardInterrupt()
    if boundary == "cache":
        def cached(*args): fail(); return {"currency_precision": "2"}
        case.cache.side_effect = cached
    else:
        def handoff(owned):
            def close(): owned.raw.close(); fail()
            owned.close.side_effect = close
        case.before_handoff = handoff
    with pytest.raises(KeyboardInterrupt if fault == "interrupt" else PermissionDenied if fault == "denied" else InspectionFailed): capture(case)
    untouched(defaults_operator, case)
    if fault != "interrupt": one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if fault == "denied" else access.FINANCIAL_FAILED_MESSAGE)


@pytest.mark.parametrize("selected", ["financial", "metadata", "defaults"])
def test_all_selected_locks_coexist_until_shared_owned_cleanup(defaults_operator, connections, selected):
    case = native_case(defaults_operator, connections)
    ready, futures = Event(), []
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            if selected == "financial": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
            elif selected == "metadata": cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND")
            else: cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
        writer.commit()
    with ThreadPoolExecutor(max_workers=1) as pool:
        def cached(*args):
            if case.cache.call_count == 1:
                future = pool.submit(compete)
                futures.append(future)
                assert ready.wait(5)
                with pytest.raises(TimeoutError): future.result(timeout=0.05)
            return {"currency_precision": "2"}
        case.cache.side_effect = cached
        capture(case)
        futures[0].result(timeout=5)
    untouched(defaults_operator, case)


def test_old_advance_refs_and_zero_payments_are_preserved_without_resolution(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    setup = connections()
    for table, values in (
        ("payments", dict(mode_of_payment="SYNTHETIC-CASH", amount=Decimal("0.000000000"))),
        ("advances", dict(reference_type="Payment Entry", reference_name="SYNTHETIC-PE-2020-0001", allocated_amount=Decimal("0.000000000"))),
        ("custom_zatca_advance_deduction_details", dict(advance_invoice="SYNTHETIC-ADV-2020-0001")),
    ):
        insert_data(setup, case.invoice.doctype, table, [dict(name=table + "-OLD", parent=case.invoice.name,
            parenttype=case.invoice.doctype, parentfield=table, idx=1, modified=None, **values)])
    setup.commit()
    result = capture(case)
    tables = dict(json.loads(result.financial.financial._payload)["tables"])
    assert dict(tables["advances"]["rows"][0][2])["reference_name"] == ["str", "SYNTHETIC-PE-2020-0001"]
    assert dict(tables["advances"]["rows"][0][2])["allocated_amount"] == ["decimal", "0E-9"]
    assert dict(tables["payments"]["rows"][0][2])["amount"] == ["decimal", "0E-9"]
    assert dict(tables["custom_zatca_advance_deduction_details"]["rows"][0][2])["advance_invoice"] == ["str", "SYNTHETIC-ADV-2020-0001"]
    untouched(defaults_operator, case)
