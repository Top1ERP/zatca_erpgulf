"""Calculated aggregates from NEW guard-owned native financial data only."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import calculated_totals as calc
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import configure,capture,item_values
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_field_rounding_access_mariadb import native_case as previous_case
from zatca_erpgulf.zatca_erpgulf.tests.test_rounding_stage_mariadb import selected_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_financial_access_mariadb import (
    combined_schema,defaults_schema,financial_schema,metadata_schema,isolated_server,connections,untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_currency_format_source_mariadb import format_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_field_currency_access_mariadb import field_schema
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_format_access_mariadb import empty_sources
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_child_format_access_mariadb import seed_metadata
from zatca_erpgulf.zatca_erpgulf.tests.test_financial_source_sql_mariadb import insert_data
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator,operator,InspectionFailed

pytestmark=pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB")!="1",
    reason="NEW guard-owned TCP-disabled temporary SQL only; no tenant or authority access")


def native_case(operator,connections,*,rows=3,advance_rows=None,advance_root_precision=None,**options):
    case=previous_case(operator,connections,**options)
    configure(case,operator,rows=rows,advance_rows=advance_rows,advance_root_precision=advance_root_precision)
    itemtype="Sales Invoice Item" if case.invoice.doctype=="Sales Invoice" else "POS Invoice Item"
    setup=connections()
    with setup.cursor() as cursor:
        for name in ("base_total","base_net_total","total_qty","total_advance"):
            cursor.execute("ALTER TABLE `tab"+case.invoice.doctype+"` ADD COLUMN IF NOT EXISTS `"+name+"` DECIMAL(21,9)")
        for name in ("base_amount","base_net_amount"):
            cursor.execute("ALTER TABLE `tab"+itemtype+"` ADD COLUMN IF NOT EXISTS `"+name+"` DECIMAL(21,9)")
        cursor.execute("UPDATE `tab"+case.invoice.doctype+"` SET base_total=0,base_net_total=0,total_qty=0,total_advance=0")
        for dt in (itemtype,"Sales Invoice Advance"):
            cursor.execute("DELETE FROM `tab"+dt+"`")
        for dt in (case.invoice.doctype,itemtype):
            cursor.execute("DELETE FROM `tabDocField` WHERE parent=%s",(dt,))
    for dt in (case.invoice.doctype,itemtype):seed_metadata(setup,case.observations[dt],groups=("docfields",))
    for group in ("items","advances"):insert_data(setup,case.invoice.doctype,group,case.data.records[group])
    setup.commit()  # NEW synthetic fixture setup only.
    setup.close()
    return case


@pytest.mark.parametrize("doctype",["Sales Invoice","POS Invoice"])
@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("rows",[0,3])
def test_native_current_items_are_distinct_from_saved_header_totals(defaults_operator,connections,doctype,major,rows):
    case=native_case(defaults_operator,connections,doctype=doctype,rows=rows)
    if not rows:
        with pytest.raises(InspectionFailed):capture(case,major,calc.TOTAL_FIELDS)
        untouched(defaults_operator,case)
        return
    source=capture(case,major,calc.TOTAL_FIELDS)
    result=calc.NetTotalsCalculation(source,item_values(source))
    assert result.before[0]==("total",float(rows))
    assert result.total_qty==float(rows)
    assert len(case.opened)==1
    untouched(defaults_operator,case)


@pytest.mark.parametrize("major",[15,16])
@pytest.mark.parametrize("advance_rows",[0,3])
def test_native_advance_prefix_keeps_root_and_direct_row_precision_separate(defaults_operator,connections,major,advance_rows):
    case=native_case(defaults_operator,connections,advance_rows=advance_rows,advance_root_precision=3)
    source=capture(case,major,("total_advance",))
    values=tuple(("advances-"+str(i+1),1.0) for i in range(advance_rows))
    rows=calc.CalculationRows(source.numeric.view.financial,"advances","NUMERIC_FIXED",values)
    result=calc.AdvanceAggregateCalculation(source,rows)
    assert result.total_advance==float(advance_rows)
    assert result.row_precision==(2 if advance_rows else None)
    assert result.source.fields[0].precision.precision==3
    untouched(defaults_operator,case)


@pytest.mark.parametrize("group",["items","advances"])
def test_late_native_inputs_cannot_be_hidden_by_a_derived_observation(defaults_operator,connections,group):
    case=native_case(defaults_operator,connections)
    old=case.cache.side_effect
    edits=[]
    def read(*args):
        result=old(*args) if old else case.cache.return_value
        if case.cache.call_count==2:
            with case.opened[0].cursor() as cursor:
                if group=="items":cursor.execute("UPDATE `tabSales Invoice Item` SET net_amount=2")
                else:cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=2")
            edits.append(group)
        return result
    case.cache.side_effect=read
    with pytest.raises(InspectionFailed):capture(case,16,calc.TOTAL_FIELDS)
    assert edits==[group]
    untouched(defaults_operator,case)
