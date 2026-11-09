"""Saved advance consistency without lookup/relink or writes; NEW SQL only."""

from dataclasses import replace
import os
import pickle

import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_settlement_advances import compare_saved_advances, SettlementAdvanceComparison
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_access import SettlementAccessError
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_plan_mariadb import setup_case, capture, money
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_access_mariadb import (
    empty_pos_sources, combined_schema, defaults_schema, financial_schema, metadata_schema,
    isolated_server, connections, untouched, format_schema, field_schema, empty_sources, selected_schema, pos_schema,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import defaults_operator, operator

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled SQL only; no tenants or authority")


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("major,kind", [(15, "match"), (16, "match"), (16, "mismatch"), (16, "not_consumed")])
def test_advance_rows_match_consumed_totals_or_report_staleness_without_repair(defaults_operator, connections, major, kind):
    case = setup_case(defaults_operator, connections, scenario="internal" if kind == "not_consumed" else "inactive")
    records = case.data.records["advances"]
    total = money(len(records) * 1.25)
    stored = money(0) if kind == "mismatch" else total
    case.invoice.total_advance = stored
    case.data.records["header"][0]["total_advance"] = stored
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabSales Invoice` SET total_advance=%s", (stored,))
        for index, row in enumerate(records):
            reference = "HISTORICAL-2020-" + str(index + 1)
            row.update(allocated_amount=money(1.25), reference_name=reference)
            for obj in (case.saved["advances", row["name"]], case.refs["advances"][index]):
                obj.allocated_amount, obj.reference_name = money(1.25), reference
            cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=%s,reference_name=%s WHERE name=%s",
                (money(1.25), reference, row["name"]))
    setup.commit();setup.close()  # NEW synthetic setup only.
    result = capture(case, major)
    queries = len(case.plan_statements)
    report = compare_saved_advances(result)
    assert type(report) is SettlementAdvanceComparison
    assert report.row_count == len(records)
    assert report.status == {"match": "MATCH", "mismatch": "MISMATCH", "not_consumed": "NOT_CONSUMED"}[kind]
    assert case.invoice.total_advance == stored and len(case.plan_statements) == queries and len(case.opened) == 1
    assert tuple(row.reference_name for row in case.refs["advances"]) == tuple(row["reference_name"] for row in records)
    if kind == "mismatch":
        assert report.expected[0][1] == float(total) and report.observed[0][1] == 0.0
        calculated = replace(report.aggregate.rows, representation="CALCULATED")
        aggregate = replace(report.aggregate, rows=calculated)
        with pytest.raises(SettlementAccessError): SettlementAdvanceComparison(result, aggregate)
        object.__setattr__(report, "status", "MATCH")
        with pytest.raises(SettlementAccessError): report.pin()
    assert case.invoice.name not in repr(report)
    with pytest.raises(TypeError): pickle.dumps(report)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT total_advance FROM `tabSales Invoice`")
        assert cursor.fetchone() == (stored,)
    observer.close()
    untouched(defaults_operator, case)
