"""Lazy owner-field formats on NEW guard-owned TCP-disabled SQL only."""

from decimal import Decimal
import json
import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf import financial_source_observation as financial
from zatca_erpgulf.zatca_erpgulf.metadata_source import SelectedMetadataRows
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding_formats import configure, target
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import capture
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access_mariadb import native_case as previous_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema, defaults_schema, financial_schema, metadata_schema, isolated_server, connections, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access_mariadb import field_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import empty_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def selected_schema(field_schema, empty_sources):
    pass


def native_case(operator, connections, *, scope="invoice", default="", **options):
    case = previous_case(operator, connections, **options)
    configure(case, operator, scope=scope, default=default)
    setup = connections()
    changed = ("Company", case.invoice.doctype, financial._child_type(case.invoice.doctype, "items"))
    with setup.cursor() as cursor:
        for dt in changed: cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s", (dt,))
        cursor.execute("UPDATE `tabCompany` SET default_currency='SAR'")
        cursor.execute("UPDATE `tab"+case.invoice.doctype+"` SET currency='USD', base_grand_total=grand_total")
        cursor.execute("UPDATE `tab"+financial._child_type(case.invoice.doctype,"items")+"` SET base_amount=amount")
        cursor.execute("UPDATE `tabDefaultValue` SET defvalue=%s", (default,))
    for dt in changed:
        seed_metadata(setup, case.observations[dt], groups=("docfields",))
    for dt, observation in case.format_data.observations.items():
        if dt == "System Settings":
            # Its method profile already owns a synthetic field named -000.
            # Distinct physical DocFields must have distinct primary keys.
            body = json.loads(observation._payload)
            for row in body["docfields"]: row["name"] += "-FORMAT"
            observation = SelectedMetadataRows(observation.applied, financial._canonical(body))
            seed_metadata(setup, observation, groups=("docfields",))
        else: seed_metadata(setup, observation)
    with setup.cursor() as cursor:
        for dt in ("Currency", "Language", "System Settings"):
            for row in case.format_data.records[dt]:
                cursor.execute("INSERT INTO `tab"+("Singles" if dt == "System Settings" else dt)+"` VALUES (%s,%s,%s)", row)
    setup.commit()  # NEW synthetic fixture setup only, never the service.
    setup.close()
    return case


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("scope,precision", [("invoice",3),("company",8)])
@pytest.mark.parametrize("child", [False,True])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ","READ COMMITTED"])
def test_native_owner_currency_formats_and_numeric_sources_share_one_handle(defaults_operator, connections, doctype, scope, precision, child, isolation):
    case = native_case(defaults_operator, connections, doctype=doctype, scope=scope, isolation=isolation)
    result = capture(case, target=target(scope,child))
    assert result.precision.precision == precision
    result.require_result_match(1.0 if child else 8.7)
    assert result.formats.financial == result.numeric.financial
    assert b"PRIVATE" not in result.formats.formats._payload
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    untouched(defaults_operator, case)


@pytest.mark.parametrize("changed", ["format","method","default","amount","company"])
@pytest.mark.parametrize("boundary", ["metadata","cache"])
def test_late_format_callbacks_cannot_hide_changes_to_any_owned_source(defaults_operator, connections, changed, boundary):
    case = native_case(defaults_operator, connections, scope="company")
    callback = case.format_metadata if boundary == "metadata" else case.format_cache
    old = callback.side_effect
    edits = []
    def call(*args):
        result = old(*args)
        if callback.call_count == 2:
            with case.opened[0].cursor() as cursor:
                if changed == "format": cursor.execute("UPDATE `tabCurrency` SET number_format='#.###'")
                elif changed == "method": cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'", ("Banker's Rounding",))
                elif changed == "default": cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                elif changed == "amount": cursor.execute("UPDATE `tabSales Invoice Item` SET amount=2")
                else: cursor.execute("UPDATE `tabCompany` SET default_currency='EUR'")
            edits.append(changed)
        return result
    callback.side_effect = call
    with pytest.raises(InspectionFailed): capture(case, target=target("company",False))
    assert edits == [changed]
    one_failure(defaults_operator, access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator, case)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT amount FROM `tabSales Invoice Item`")
        assert cursor.fetchone() == (Decimal("1.000000000"),)
        cursor.execute("SELECT default_currency FROM `tabCompany`")
        assert cursor.fetchone() == ("SAR",)
    observer.close()


@pytest.mark.parametrize("changed", ["currency_cache","field_acl","locale"])
def test_real_close_keeps_cache_locale_and_field_access_binding(defaults_operator, connections, changed):
    case = native_case(defaults_operator, connections)
    def handoff(owned):
        close = owned.close.side_effect
        def done():
            close()
            if changed == "currency_cache": defaults_operator.runtime.local.field_currency = {}
            elif changed == "field_acl": case.format_fields["Currency"].permlevel = 1
            else: defaults_operator.runtime.local.lang = "en"
        owned.close.side_effect = done
    case.before_handoff = handoff
    with pytest.raises(PermissionDenied if changed == "field_acl" else InspectionFailed): capture(case)
    untouched(defaults_operator, case)


@pytest.mark.parametrize("major", [15,16])
@pytest.mark.parametrize("doctype", ["Sales Invoice","POS Invoice"])
def test_native_configured_precision_skips_all_format_sources(defaults_operator, connections, major, doctype):
    case = native_case(defaults_operator, connections, default="2", doctype=doctype)
    defaults_operator.denied.add(("Currency","USD"))
    result = capture(case,major)
    assert result.formats is None
    case.format_metadata.assert_not_called()
    case.format_cache.assert_not_called()
    untouched(defaults_operator,case)


@pytest.mark.parametrize("borrowed", [False,True])
def test_pending_caller_work_stays_with_its_owner(defaults_operator,connections,borrowed):
    case = native_case(defaults_operator,connections)
    parent = connections()
    with parent.cursor() as cursor: cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn = parent
    if borrowed:
        case.factory.side_effect,case.factory.return_value = None,parent
        with pytest.raises(InspectionFailed): capture(case)
    else: capture(case).require_result_match(8.7)
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall() == (("PENDING",),)


@pytest.mark.parametrize("absent", [False,True])
def test_native_zero_or_missing_format_flag_uses_locale_with_method_still_present(defaults_operator,connections,absent):
    case = native_case(defaults_operator,connections)
    setattr(case.related["System Settings"],"use_number_format_from_currency",0)
    setup = connections()
    with setup.cursor() as cursor:
        if absent: cursor.execute("DELETE FROM `tabSingles` WHERE field='use_number_format_from_currency'")
        else: cursor.execute("UPDATE `tabSingles` SET value='0' WHERE field='use_number_format_from_currency'")
    setup.commit()
    setup.close()
    result = capture(case)
    assert result.precision.precision == 2
    result.require_result_match(8.7)
    untouched(defaults_operator,case)
