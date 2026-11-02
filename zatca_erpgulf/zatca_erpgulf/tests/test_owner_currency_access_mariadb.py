"""Supplemental party currency and Company cache on NEW isolated SQL only."""

from decimal import Decimal
import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_owner_currency_access import configure
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access import capture
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding_formats_mariadb import native_case as previous_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema,defaults_schema,financial_schema,metadata_schema,isolated_server,connections,untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access_mariadb import field_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import empty_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator,operator,one_failure,PermissionDenied,InspectionFailed,
)

pytestmark=pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB")!="1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def selected_schema(field_schema,empty_sources,connections):
    setup=connections()
    with setup.cursor() as cursor:
        for dt in ("Sales Invoice","POS Invoice"):
            cursor.execute("ALTER TABLE `tab"+dt+"` ADD COLUMN IF NOT EXISTS party_account_currency LONGTEXT")
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()


def native_case(operator,connections,**options):
    case=previous_case(operator,connections,**options)
    configure(case,operator)
    setup=connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tab"+case.invoice.doctype+"` SET party_account_currency='EUR'")
        cursor.execute("UPDATE `tabCurrency` SET name='EUR',number_format='#.########'")
        cursor.execute("UPDATE `tabDocField` SET options='party_account_currency' WHERE (parent=%s AND fieldname='grand_total') OR (parent='Sales Invoice Advance' AND fieldname='allocated_amount')",(case.invoice.doctype,))
    seed_metadata(setup,case.owner_observation,groups=("docfields",))
    setup.commit()
    setup.close()
    return case


@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("child",[False,True])
@pytest.mark.parametrize("isolation",["REPEATABLE READ","READ COMMITTED"])
def test_party_account_and_advance_currency_are_native_bound(defaults_operator,connections,doctype,child,isolation):
    case=native_case(defaults_operator,connections,doctype=doctype,isolation=isolation)
    selected=("advances","advances-1","allocated_amount") if child else (None,None,"grand_total")
    result=capture(case,target=selected)
    assert result.formats.formats.currency=="EUR"
    assert result.formats.owner_currency.metadata.applied.name==doctype
    assert result.precision.precision==8
    result.require_result_match(1.0 if child else 8.7)
    assert len(case.opened)==1 and case.opened[0].rollback.call_count==2
    untouched(defaults_operator,case)


@pytest.mark.parametrize("changed",["party","metadata","amount","default","method"])
def test_last_party_metadata_callback_is_followed_by_all_native_checks(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    old=case.owner_metadata.side_effect
    edits=[]
    def callback(*args):
        result=old(*args)
        if case.owner_metadata.call_count==2:
            with case.opened[0].cursor() as cursor:
                if changed=="party":cursor.execute("UPDATE `tabSales Invoice` SET party_account_currency='GBP'")
                elif changed=="metadata":cursor.execute("UPDATE `tabDocField` SET options='Company' WHERE fieldname='party_account_currency'")
                elif changed=="amount":cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=2")
                elif changed=="default":cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                else:cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'",("Banker's Rounding",))
            edits.append(changed)
        return result
    case.owner_metadata.side_effect=callback
    with pytest.raises(InspectionFailed):capture(case)
    assert edits==[changed]
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)
    observer=connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT party_account_currency FROM `tabSales Invoice`")
        assert cursor.fetchone()==("EUR",)
        cursor.execute("SELECT allocated_amount FROM `tabSales Invoice Advance`")
        assert cursor.fetchone()==(Decimal("1.000000000"),)
    observer.close()


@pytest.mark.parametrize("changed",["party","field_access"])
def test_party_original_getter_and_field_read_are_checked_after_close(defaults_operator,connections,changed):
    case=native_case(defaults_operator,connections)
    def wrap(owned):
        close=owned.close.side_effect
        def done():
            close()
            if changed=="party":case.invoice.party_account_currency="GBP"
            else:case.field_overrides[case.invoice.doctype,"party_account_currency"]=type(case.round_df)(fieldtype="Link",options="Currency",permlevel=1)
        owned.close.side_effect=done
    case.before_handoff=wrap
    with pytest.raises(PermissionDenied if changed=="field_access" else InspectionFailed):capture(case)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("boundary",["cache","close"])
def test_company_api_cache_drift_is_not_hidden_by_current_native_company(defaults_operator,connections,boundary):
    case=previous_case(defaults_operator,connections,scope="company")
    if boundary=="cache":
        old=case.company_api_cache.side_effect
        def observe(*args):
            if case.company_api_cache.call_count==2:case.company_cache_value="EUR"
            return old(*args)
        case.company_api_cache.side_effect=observe
    else:
        def wrap(owned):
            close=owned.close.side_effect
            def done():close();setattr(case,"company_cache_value","EUR")
            owned.close.side_effect=done
        case.before_handoff=wrap
    with pytest.raises(InspectionFailed):capture(case,target=(None,None,"base_grand_total"))
    untouched(defaults_operator,case)


@pytest.mark.parametrize("borrowed",[False,True])
def test_party_capture_preserves_caller_pending_work(defaults_operator,connections,borrowed):
    case=native_case(defaults_operator,connections)
    parent=connections()
    with parent.cursor() as cursor:cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn=parent
    if borrowed:
        case.factory.side_effect,case.factory.return_value=None,parent
        with pytest.raises(InspectionFailed):capture(case)
    else:assert capture(case).formats.owner_currency.currency=="EUR"
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall()==(("PENDING",),)
