"""Selected child Company/format graph on NEW guard-owned native SQL only."""

import json
import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access import bind_sources, capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_access_mariadb import native_case as child_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import combined_schema, untouched
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import financial_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_metadata_source_mariadb import metadata_schema, insert
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_mariadb import defaults_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled SQL only; no tenant, installed or authority access")


@pytest.fixture(autouse=True)
def empty_sources(combined_schema, format_schema, financial_schema, connections):
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("ALTER TABLE `tabCompany` ADD COLUMN IF NOT EXISTS default_currency LONGTEXT")
        for dt in ("Sales Invoice Item", "POS Invoice Item"):
            for name in ("currency", "company"):
                cursor.execute("ALTER TABLE `tab" + dt + "` ADD COLUMN IF NOT EXISTS `" + name + "` LONGTEXT")
        for dt in (*financial_schema, "Company", "Currency", "Language", "Singles", "DefaultValue",
                "DocType", "DocField", "Custom Field", "Property Setter"):
            cursor.execute("DELETE FROM `tab" + dt + "`")
        for table in ("financial_parent_work", "currency_parent_work"):
            cursor.execute("DELETE FROM " + table)
    setup.commit()  # NEW synthetic fixture setup only; never a runtime service.
    setup.close()


def seed_metadata(setup, observation, *, groups=("doctype", "docfields", "custom_fields", "property_setters")):
    body = json.loads(observation._payload)
    for group in groups:
        rows = [body[group]] if group == "doctype" else body[group]
        for row in rows:
            insert(setup, group, [dict(name=row["name"], modified=financial._validate_scalar(row["modified"]),
                **{name: financial._validate_scalar(value) for name, value in row["header"]})])


def native_case(operator, connections, *, doctype="Sales Invoice", scope="company", major=16, isolation="REPEATABLE READ"):
    case = child_case(operator, connections, doctype=doctype, isolation=isolation)
    bind_sources(case, operator, scope=scope)
    setup = connections()
    seed_metadata(setup, case.observations["Company"], groups=("docfields",))
    for observation in case.format_data.observations.values(): seed_metadata(setup, observation)
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabDocField` SET options=%s WHERE parent=%s AND fieldname='amount'",
            ("Company:company:default_currency" if scope == "company" else "currency", case.data.own.applied.name))
        cursor.execute("INSERT INTO `tabCompany` (name,modified,default_currency) VALUES (%s,%s,%s)",
            (case.own_company.name, case.own_company.modified, case.own_company.default_currency))
        for dt in ("Currency", "Language", "System Settings"):
            table = "Singles" if dt == "System Settings" else dt
            for row in case.format_data.records[dt]: cursor.execute("INSERT INTO `tab" + table + "` VALUES (%s,%s,%s)", row)
        if major == 16:
            cursor.execute("UPDATE `tabDefaultValue` SET defvalue='' WHERE defkey='currency_precision'")
            case.cache.return_value = {"currency_precision": ""}
    setup.commit()
    setup.close()
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scope", ["invoice", "company"])
@pytest.mark.parametrize("major", [15, 16])
def test_native_child_scope_company_and_versioned_formats_share_one_owned_handle(defaults_operator, connections, doctype, scope, major):
    case = native_case(defaults_operator, connections, doctype=doctype, scope=scope, major=major)
    result = capture(case, major=major)
    assert result.resolve_currency().currency == case.expected_currency
    assert result.resolve_precision().precision == (2 if major == 15 else case.expected_precision)
    if scope == "company":
        assert result.company.name == case.own_company.name != case.company.name
        assert result.company.metadata == result.parent.financial.context.metadata[0]
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    assert case.format_cache.call_count == (2 if major == 16 else 0)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("boundary", ["cache_first", "cache_second", "format_second"])
@pytest.mark.parametrize("changed", ["company", "format", "child_link"])
def test_native_callback_drift_is_detected_without_modified_changes_and_rolled_back(defaults_operator, connections, boundary, changed):
    case = native_case(defaults_operator, connections)
    provider = case.format_cache if boundary.startswith("cache") else case.format_metadata
    original = provider.side_effect
    def read(*args):
        result = original(*args)
        if provider.call_count == (1 if boundary.endswith("first") else 2):
            with case.opened[0].cursor() as cursor:
                if changed == "company": cursor.execute("UPDATE `tabCompany` SET default_currency='SAR' WHERE name=%s", (case.own_company.name,))
                elif changed == "format": cursor.execute("UPDATE `tabCurrency` SET number_format='#.###'")
                else: cursor.execute("UPDATE `tabSales Invoice Item` SET company='OTHER'")
        return result
    provider.side_effect = read
    with pytest.raises(InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT default_currency FROM `tabCompany` WHERE name=%s", (case.own_company.name,))
        assert cursor.fetchone() == ("EUR",)
        cursor.execute("SELECT number_format FROM `tabCurrency`")
        assert cursor.fetchone() == ("#.########",)


@pytest.mark.parametrize("changed", ["company_permission", "currency_permission", "company_link", "locale"])
def test_cleanup_never_discloses_after_selected_related_access_drift(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    original = case.factory.side_effect
    def acquire(*args):
        owned = original(*args)
        raw_close = owned.close.side_effect
        def close():
            raw_close()
            if changed == "company_permission": defaults_operator.denied.add(("Company", case.own_company.name))
            elif changed == "currency_permission": defaults_operator.denied.add(("Currency", case.expected_currency))
            elif changed == "company_link": case.own_company.default_currency = "SAR"
            else: defaults_operator.runtime.local.lang = "en"
        owned.close.side_effect = close
        return owned
    case.factory.side_effect = acquire
    denied = changed.endswith("permission")
    with pytest.raises(PermissionDenied if denied else InspectionFailed): capture(case)
    one_failure(defaults_operator, access.FINANCIAL_DENIED_MESSAGE if denied else access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
