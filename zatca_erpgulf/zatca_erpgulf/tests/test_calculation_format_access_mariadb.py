"""Saved currency-format acquisition on one new guarded synthetic SQL server."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import json
import os
from threading import Event

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import currency_format_source as source
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access import bind_formats, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema, native_case as financial_case, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import financial_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import defaults_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.financial_source_observation import _validate_scalar

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Guard-owned temporary SQL only; no working site or authority access")


@pytest.fixture(autouse=True)
def empty_sources(combined_schema, format_schema, financial_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        for table in (*financial_schema, "Company", "Currency", "Language", "Singles", "DefaultValue",
                "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + table + "`")
        for table in ("financial_parent_work", "currency_parent_work"):
            cursor.execute("DELETE FROM " + table)
    setup.commit()  # Synthetic fixture owner only, never the acquisition service.
    setup.close()


def native_case(operator, connections, *, missing_check=False, **options):
    case = financial_case(operator, connections, **options)
    bind_formats(case, operator, missing_check=missing_check)
    setup = connections()
    for observation in case.format_data.observations.values():
        body = json.loads(observation._payload)
        for group in ("doctype", "docfields", "custom_fields", "property_setters"):
            records = [body[group]] if group == "doctype" else body[group]
            for row in records:
                insert(setup, group, [dict(name=row["name"], modified=_validate_scalar(row["modified"]),
                    **{name: _validate_scalar(value) for name, value in row["header"]})])
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabDocField` SET options='currency' WHERE parent=%s AND fieldname='grand_total'",
            (case.invoice.doctype,))
        for doctype, records in case.format_data.records.items():
            table = "Singles" if doctype == "System Settings" else doctype
            for row in records: cursor.execute("INSERT INTO `tab" + table + "` VALUES (%s,%s,%s)", row)
        cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings','api_secret','PRIVATE-NEVER-RETURN')")
    setup.commit()
    setup.close()
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("missing_check", [False, True])
@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_currency_formats_financials_defaults_and_acl_share_one_owned_read(defaults_operator, connections, doctype, missing_check, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, missing_check=missing_check, isolation=isolation)
    result = capture(case)
    assert result.resolve_precision("grand_total").precision == 2
    assert result.formats.context.use_currency_format is not missing_check
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    assert case.format_cache.call_count == case.format_metadata.call_count == 2
    assert b"PRIVATE-NEVER-RETURN" not in result.formats._payload
    untouched(defaults_operator, case)


@pytest.mark.parametrize("missing_check", [False, True])
def test_unset_currency_default_uses_the_permissioned_native_format_context(defaults_operator, connections, missing_check):
    case = native_case(defaults_operator, connections, missing_check=missing_check)
    setup = connections()
    with setup.cursor() as cursor: cursor.execute("UPDATE `tabDefaultValue` SET defvalue=''")
    setup.commit()
    case.cache.return_value = {"currency_precision": ""}
    result = capture(case)
    assert result.resolve_precision("grand_total").precision == (2 if missing_check else 8)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["cache_first", "cache_second", "metadata_second"])
@pytest.mark.parametrize("changed", ["format", "singleton", "financial", "defaults", "metadata"])
def test_callbacks_cannot_hide_native_changes_and_owned_edits_roll_back(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    def mutate():
        with case.opened[0].cursor() as cursor:
            if changed == "format": cursor.execute("UPDATE `tabCurrency` SET number_format='#.###'")
            elif changed == "singleton": cursor.execute("UPDATE `tabSingles` SET value='0' WHERE field=%s", (source.FLAG,))
            elif changed == "financial": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
            elif changed == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
            else: cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND WHERE parent='Language'")
    if boundary == "metadata_second":
        original = case.format_metadata.side_effect
        def metadata(*args):
            if case.format_metadata.call_count == 2: mutate()
            return original(*args)
        case.format_metadata.side_effect = metadata
    else:
        original = case.format_cache.side_effect
        def cached(*args):
            result = original(*args)
            if case.format_cache.call_count == (1 if boundary == "cache_first" else 2): mutate()
            return result
        case.format_cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT number_format FROM `tabCurrency`")
        assert cursor.fetchone() == ("#.########",)
        cursor.execute("SELECT value FROM `tabSingles` WHERE field=%s", (source.FLAG,))
        assert cursor.fetchone() == ("1",)
        cursor.execute("SELECT defvalue FROM `tabDefaultValue`")
        assert cursor.fetchone() == ("2",)


@pytest.mark.parametrize("borrowed", [False, True])
def test_pending_parent_transaction_is_untouched_including_borrow_refusal(defaults_operator, connections, borrowed):
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


@pytest.mark.parametrize("changed", ["permission", "locale", "currency"])
def test_close_time_acl_locale_and_currency_drift_withhold_results(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def handoff(owned):
        def close():
            owned.raw.close()
            if changed == "permission": defaults_operator.denied.add(("Language", "ar"))
            elif changed == "locale": defaults_operator.runtime.local.lang = "en"
            else: case.invoice.currency = "OTHER"
        owned.close.side_effect = close
    case.before_handoff = handoff
    with pytest.raises(PermissionDenied if changed == "permission" else InspectionFailed): capture(case)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("target", ["financial", "singleton", "defaults", "metadata"])
def test_all_dependency_locks_coexist_until_the_single_owned_cleanup(defaults_operator, connections, target):
    case = native_case(defaults_operator, connections)
    ready, futures = Event(), []
    def compete():
        writer = connections()
        ready.set()
        with writer.cursor() as cursor:
            if target == "financial": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
            elif target == "singleton": cursor.execute("UPDATE `tabSingles` SET value='0' WHERE field=%s", (source.FLAG,))
            elif target == "defaults": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
            else: cursor.execute("UPDATE `tabDocField` SET modified=modified+INTERVAL 1 SECOND WHERE parent='Language'")
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


def test_rc_explicit_zero_insert_cannot_replace_the_captured_absent_check(defaults_operator, connections):
    case = native_case(defaults_operator, connections, missing_check=True, isolation="READ COMMITTED")
    original = case.format_cache.side_effect
    def cached(*args):
        if case.format_cache.call_count == 2:
            writer = connections("READ COMMITTED")
            with writer.cursor() as cursor:
                cursor.execute("INSERT INTO `tabSingles` VALUES ('System Settings',%s,'0')", (source.FLAG,))
            writer.commit()
        return original(*args)
    case.format_cache.side_effect = cached
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)


def test_wholly_empty_singleton_does_not_invoke_document_creation(defaults_operator, connections):
    case = native_case(defaults_operator, connections, missing_check=True)
    setup = connections()
    with setup.cursor() as cursor: cursor.execute("DELETE FROM `tabSingles`")
    setup.commit()
    with pytest.raises(InspectionFailed): capture(case)
    untouched(defaults_operator, case)
