"""Invoice/Company field-currency scopes on new guarded native SQL only."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import os
from threading import Event

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access import bind_fields, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import native_case as format_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import combined_schema, untouched
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import financial_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import defaults_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert, instrument
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _validate_scalar

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Guard-owned temporary SQL only; no customer site or authority access")


@pytest.fixture(scope="module")
def field_schema(combined_schema, format_schema, isolated_server):
    setup = pymysql.connect(unix_socket=isolated_server[0], user="root", database="zatca_journal_rehearsal", autocommit=True)
    try:
        with setup.cursor() as cursor:
            cursor.execute("ALTER TABLE `tabCompany` ADD default_currency VARCHAR(140)")
            for table in ("Sales Invoice", "POS Invoice"):
                cursor.execute("ALTER TABLE `tab" + table + "` ADD base_grand_total DECIMAL(21,9)")
            for table in ("Sales Invoice Item", "POS Invoice Item"):
                cursor.execute("ALTER TABLE `tab" + table + "` ADD base_amount DECIMAL(21,9)")
    finally:
        setup.close()


@pytest.fixture(autouse=True)
def empty_sources(field_schema, financial_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for table in (*financial_schema, "Company", "Currency", "Language", "Singles", "DefaultValue",
                "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + table + "`")
        for table in ("financial_parent_work", "currency_parent_work"):
            cursor.execute("DELETE FROM " + table)
    setup.commit()  # Synthetic fixture owner only, never an acquisition service.
    setup.close()


def native_case(operator, connections, *, scope="company", **options):
    case = format_case(operator, connections, **options)
    bind_fields(case, operator, scope=scope)
    setup = connections()
    child = "Sales Invoice Item" if case.invoice.doctype == "Sales Invoice" else "POS Invoice Item"
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabCompany` SET default_currency='SAR'")
        cursor.execute("UPDATE `tab" + case.invoice.doctype + "` SET currency='USD',base_grand_total=grand_total")
        cursor.execute("UPDATE `tab" + child + "` SET base_amount=amount")
        cursor.execute("UPDATE `tabDefaultValue` SET defvalue=''")
        cursor.execute("DELETE FROM `tabCurrency`")
        cursor.execute("INSERT INTO `tabCurrency` VALUES (%s,%s,%s)", case.format_data.records["Currency"][0])
        for doctype in ("Company", case.invoice.doctype, child):
            cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s", (doctype,))
    for doctype in ("Company", case.invoice.doctype, child):
        for row in json.loads(case.observations[doctype]._payload)["docfields"]:
            insert(setup, "docfields", [dict(name=row["name"], modified=_validate_scalar(row["modified"]),
                **{name: _validate_scalar(value) for name, value in row["header"]})])
    setup.commit()
    setup.close()
    case.cache.return_value = {"currency_precision": ""}
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scope", ["invoice", "company"])
@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_real_company_and_invoice_currencies_remain_distinct_for_parent_child_precision(defaults_operator, connections, doctype, scope, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, scope=scope, isolation=isolation)
    result = capture(case)
    root, child, currency, precision = ("base_grand_total", "base_amount", "SAR", 8) if scope == "company" else ("grand_total", "amount", "USD", 3)
    assert result.formats.currency == currency
    assert result.resolve_precision(root).precision == result.resolve_precision(child, parentfield="items").precision == precision
    result.require_field_currency_match(child, currency, parentfield="items")
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("changed", ["link", "revision", "metadata", "format", "financial"])
def test_last_cache_callback_company_or_dependency_drift_is_detected_and_rolled_back(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    original = case.format_cache.side_effect
    def cached(*args):
        result = original(*args)
        if case.format_cache.call_count == 2:
            with case.opened[0].cursor() as cursor:
                if changed == "link": cursor.execute("UPDATE `tabCompany` SET default_currency='EUR'")
                elif changed == "revision": cursor.execute("UPDATE `tabCompany` SET modified=modified+INTERVAL 1 SECOND")
                elif changed == "metadata": cursor.execute("UPDATE `tabDocField` SET options='Account' WHERE parent='Company' AND fieldname='default_currency'")
                elif changed == "format": cursor.execute("UPDATE `tabCurrency` SET number_format='#.###'")
                else: cursor.execute("UPDATE `tabSales Invoice Item` SET base_amount=2")
        return result
    case.format_cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT default_currency,modified FROM `tabCompany`")
        assert cursor.fetchone() == ("SAR", case.company.modified)


def test_stale_saved_company_link_is_refused_before_reading_currency_formats(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    setup = connections()
    with setup.cursor() as cursor: cursor.execute("UPDATE `tabCompany` SET default_currency='EUR'")
    setup.commit()
    calls = []
    def handoff(owned):
        wrapped, seen, _ = instrument(owned.raw)
        owned.cursor = wrapped.cursor
        calls.append(seen)
    case.before_handoff = handoff
    with pytest.raises(InspectionFailed): capture(case)
    assert not any("FROM `tabCurrency`" in sql for sql, _ in calls[0])
    case.format_cache.assert_not_called()
    untouched(defaults_operator, case)


def test_company_lock_survives_until_shared_cleanup(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    ready, futures = Event(), []
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor: cursor.execute("UPDATE `tabCompany` SET default_currency='EUR'")
        writer.commit()
    original = case.format_cache.side_effect
    with ThreadPoolExecutor(max_workers=1) as pool:
        def cached(*args):
            if case.format_cache.call_count == 2:
                future = pool.submit(compete)
                futures.append(future)
                assert ready.wait(5)
                with pytest.raises(TimeoutError): future.result(timeout=0.05)
            return original(*args)
        case.format_cache.side_effect = cached
        capture(case)
        futures[0].result(timeout=5)
    untouched(defaults_operator, case)


def test_parent_pending_work_survives_base_currency_capture(defaults_operator, connections):
    case = native_case(defaults_operator, connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    capture(case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM financial_parent_work")
        assert cursor.fetchone() == (0,)
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchone() == ("PENDING",)
    assert parent.open
    untouched(defaults_operator, case)
