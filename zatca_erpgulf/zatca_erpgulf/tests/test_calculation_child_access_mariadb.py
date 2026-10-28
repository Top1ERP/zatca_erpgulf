"""Saved child ACL/native/default composition on NEW guard-owned SQL only."""

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_access import saved_graph, configure, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema, native_case as financial_case, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import financial_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import defaults_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import AppliedMeta, project
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
from zatca_erpgulf.zatca_erpgulf.source_metadata import CHILD_CURRENCY_PROFILE

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def empty_sources(combined_schema, financial_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for dt in ("Sales Invoice Item", "POS Invoice Item"):
            for name in ("currency", "company"):
                cursor.execute("ALTER TABLE `tab" + dt + "` ADD COLUMN IF NOT EXISTS `" + name + "` LONGTEXT")
        for dt in (*financial_schema, "Company", "DocType", "DocField", "Custom Field", "Property Setter", "DefaultValue"):
            cursor.execute("DELETE FROM `tab" + dt + "`")
        cursor.execute("DELETE FROM financial_parent_work")
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()


def native_case(operator, connections, *, doctype="Sales Invoice", isolation="REPEATABLE READ"):
    case = financial_case(operator, connections, doctype=doctype, optional=False, isolation=isolation)
    dt = financial._child_type(doctype, "items")
    raw = case.data.raw_metas[dt]
    raw.definitions["amount"].values["options"] = "currency"
    case.data.metas[dt] = project(raw)
    case.observations[dt] = observed_metadata(raw)
    case.applied[dt] = case.observations[dt].applied
    own = AppliedMeta(dt, ("currency", "company"))
    own.definitions["currency"].values.update(fieldtype="Link", options="Currency")
    own.definitions["company"].values.update(fieldtype="Link", options="Company")
    case.data.own = observed_metadata(own, profile=CHILD_CURRENCY_PROFILE)
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabDocField` SET options='currency' WHERE parent=%s AND fieldname='amount'", (dt,))
        cursor.execute("UPDATE `tab" + dt + "` SET currency='USD',company='SYNTHETIC-CHILD-CO'")
    for row in json.loads(case.data.own._payload)["docfields"]:
        values = {key: financial._validate_scalar(value) for key, value in row["header"]}
        insert(setup, "docfields", [dict(name="child-link-" + values["fieldname"],
            modified=financial._validate_scalar(row["modified"]), **values)])
    setup.commit()
    setup.close()
    case.data.records["items"][0].update(currency="USD", company="SYNTHETIC-CHILD-CO")
    saved_graph(operator, case)
    return configure(case)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("major", [15, 16])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_saved_graph_native_links_and_defaults_use_one_owned_connection(defaults_operator, connections, doctype, major, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, isolation=isolation)
    result = capture(case, major=major)
    assert result.resolve_currency("items-1", "amount").currency == "USD"
    assert result.resolve_precision("items-1", "amount").precision == 2
    assert tuple(name for name, _ in result.tables) == ("items", "taxes")
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["cache_first", "cache_second", "child_second", "metadata_last"])
@pytest.mark.parametrize("changed", ["currency", "company", "revision", "metadata"])
def test_callback_edits_to_child_sql_are_detected_and_rolled_back(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    provider = case.child_metadata if boundary == "child_second" else case.metadata_provider if boundary == "metadata_last" else case.cache
    original = provider.side_effect or (lambda *args: provider.return_value)
    def callback(*args):
        result = original(*args)
        expected = 4 if boundary == "metadata_last" else 1 if boundary == "cache_first" else 2
        if provider.call_count == expected:
            with case.opened[0].cursor() as cursor:
                if changed in ("currency", "company"):
                    cursor.execute("UPDATE `tabSales Invoice Item` SET `" + changed + "`='OTHER'")
                elif changed == "revision": cursor.execute("UPDATE `tabSales Invoice Item` SET modified=modified+INTERVAL 1 SECOND")
                else: cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND WHERE name='child-link-currency'")
        return result
    provider.side_effect = callback
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT currency,company FROM `tabSales Invoice Item`")
        assert cursor.fetchall() == (("USD", "SYNTHETIC-CHILD-CO"),)


@pytest.mark.parametrize("boundary", ["before", "close"])
@pytest.mark.parametrize("denied", [("Sales Invoice Item", None), ("Sales Invoice Item", "items-1"), ("Sales Taxes and Charges", "taxes-1")])
def test_normal_table_or_row_denial_prevents_or_withholds_native_disclosure(defaults_operator, connections, boundary, denied):
    case = native_case(defaults_operator, connections)
    if boundary == "before": defaults_operator.denied.add(denied)
    else:
        original = case.factory.side_effect
        def acquire(*args):
            owned = original(*args)
            raw_close = owned.close.side_effect
            def close():
                raw_close()
                defaults_operator.denied.add(denied)
            owned.close.side_effect = close
            return owned
        case.factory.side_effect = acquire
    with pytest.raises(PermissionDenied): capture(case)
    assert case.factory.call_count == (0 if boundary == "before" else 1)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE)
    untouched(defaults_operator, case)


def test_owned_cleanup_preserves_the_users_pending_ambient_work(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor:
        cursor.execute("INSERT INTO financial_parent_work VALUES ('ambient-pending')")
    defaults_operator.runtime.db._conn = parent
    capture(case)
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall() == (("ambient-pending",),)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert not cursor.fetchall()
    untouched(defaults_operator, case)
