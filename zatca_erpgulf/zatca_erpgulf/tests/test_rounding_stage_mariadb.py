"""Ordered stage queries, source sharing and cleanup on NEW isolated SQL."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculation_defaults_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_rounding_stage import capture,mixed_currencies
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access_mariadb import native_case
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding_formats_mariadb import native_case as format_case
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema,defaults_schema,financial_schema,metadata_schema,isolated_server,connections,untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access_mariadb import field_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import empty_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator,operator,one_failure,InspectionFailed,
)

pytestmark=pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB")!="1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


@pytest.fixture(autouse=True)
def selected_schema(field_schema,empty_sources):
    pass


@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("child",[False,True])
def test_batch_uses_same_owned_query_count_as_single_field(defaults_operator,connections,doctype,major,child):
    case=native_case(defaults_operator,connections,doctype=doctype)
    queries=[]
    def record(owned):
        original=owned.cursor
        def cursor():
            current=original();execute=current.execute
            def run(sql,params=()):queries.append((sql,params));return execute(sql,params)
            current.execute=run;return current
        owned.cursor=cursor
    case.before_handoff=record
    names=("amount","net_amount") if child else ("grand_total","net_total")
    case.service.capture_field_rounding_context(case.invoice.name,names[0],erp_major=major,doctype=doctype,
        parentfield="items" if child else None,row_name="items-1" if child else None)
    baseline=len(queries);queries.clear()
    result=capture(case,major,names=names,child=child)
    assert len(result.fields)==2
    assert len(queries)==baseline
    assert len(case.opened)==2 and all(owned.rollback.call_count==2 for owned in case.opened)
    untouched(defaults_operator,case)


def test_native_same_scope_formats_have_one_initial_read(defaults_operator,connections):
    case=format_case(defaults_operator,connections)
    from zatca_erpgulf.zatca_erpgulf.tests.test_source_metadata import project
    from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql import observed_metadata
    raw=case.data.raw_metas[case.invoice.doctype]
    raw.definitions["net_total"].values["options"]="currency"
    case.applied[case.invoice.doctype]=case.data.metas[case.invoice.doctype]=project(raw)
    case.observations[case.invoice.doctype]=observed_metadata(raw)
    case.field_overrides[case.invoice.doctype,"net_total"]=case.applied[case.invoice.doctype].get_field("net_total")
    setup=connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabDocField` SET options='currency' WHERE parent=%s AND fieldname='net_total'",(case.invoice.doctype,))
    setup.commit();setup.close()
    result=capture(case)
    assert result.fields[0].formats.formats==result.fields[1].formats.formats
    assert case.format_metadata.call_count==2
    assert len(case.opened)==1
    untouched(defaults_operator,case)


def test_native_all_skipped_stage_does_not_read_unused_formats_or_precision(defaults_operator,connections):
    case=format_case(defaults_operator,connections)
    case.invoice._precision=object()
    defaults_operator.runtime.local.field_currency=object()
    result=capture(case,skips=("grand_total","net_total"))
    assert not result.fields
    case.format_metadata.assert_not_called();case.format_cache.assert_not_called()
    assert case.round_metadata.call_count==2
    untouched(defaults_operator,case)


@pytest.mark.parametrize("boundary",["cache","metadata"])
@pytest.mark.parametrize("changed",["first","second","default","method"])
def test_native_callback_changes_are_rejected_for_any_selected_source(defaults_operator,connections,boundary,changed):
    case=native_case(defaults_operator,connections)
    callback=case.cache if boundary=="cache" else case.metadata_provider
    old=callback.side_effect
    changed_at=[]
    def read(*args):
        result=old(*args) if old else callback.return_value
        if callback.call_count==(2 if boundary=="cache" else 4):
            with case.opened[0].cursor() as cursor:
                if changed=="first":cursor.execute("UPDATE `tabSales Invoice` SET grand_total=2")
                elif changed=="second":cursor.execute("UPDATE `tabSales Invoice` SET net_total=2")
                elif changed=="default":cursor.execute("UPDATE `tabDefaultValue` SET defvalue='3'")
                else:cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'",("Banker's Rounding",))
            changed_at.append(changed)
        return result
    callback.side_effect=read
    with pytest.raises(InspectionFailed):capture(case)
    assert changed_at==[changed]
    one_failure(defaults_operator,access.FINANCIAL_FAILED_MESSAGE)
    untouched(defaults_operator,case)


@pytest.mark.parametrize("borrowed",[False,True])
def test_stage_keeps_pending_caller_work_owned(defaults_operator,connections,borrowed):
    case=native_case(defaults_operator,connections)
    parent=connections()
    with parent.cursor() as cursor:cursor.execute("INSERT INTO financial_parent_work VALUES ('PENDING')")
    defaults_operator.runtime.db._conn=parent
    if borrowed:
        case.factory.side_effect,case.factory.return_value=None,parent
        with pytest.raises(InspectionFailed):capture(case)
    else:assert len(capture(case).fields)==2
    assert parent.open
    with parent.cursor() as cursor:
        cursor.execute("SELECT name FROM financial_parent_work")
        assert cursor.fetchall()==(("PENDING",),)


def test_native_mixed_invoice_and_base_formats_remain_separate(defaults_operator,connections):
    case=format_case(defaults_operator,connections,scope="company")
    mixed_currencies(case,defaults_operator)
    setup=connections()
    usd=defaults_operator.documents["Currency","USD"]
    with setup.cursor() as cursor:
        cursor.execute("INSERT INTO `tabCurrency` VALUES (%s,%s,%s)",(usd.name,usd.modified,usd.number_format))
    setup.commit();setup.close()
    result=capture(case,names=("grand_total","base_grand_total"))
    assert [value.precision.precision for value in result.fields]==[3,8]
    assert [value.formats.formats.currency for value in result.fields]==["USD","SAR"]
    assert len(case.opened)==1
    untouched(defaults_operator,case)
