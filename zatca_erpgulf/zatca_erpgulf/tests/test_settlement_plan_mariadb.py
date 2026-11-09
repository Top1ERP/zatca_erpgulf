"""Lazy two-call saved-numeric plans on NEW guarded TCP-disabled SQL only."""

from dataclasses import replace
from decimal import Decimal
import os
import pickle

import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_settlement_plan import SavedSettlementPlan
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_access import SettlementAccessError
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_sequence_mariadb import primary_probe
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_access_mariadb import (
    native_case, empty_pos_sources, combined_schema, defaults_schema, financial_schema, metadata_schema,
    isolated_server, connections, untouched, format_schema, field_schema, empty_sources, selected_schema, pos_schema,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.calculation_defaults_access import FINANCIAL_DENIED_MESSAGE, FINANCIAL_FAILED_MESSAGE
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_outstanding_guard import primary_methods

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guarded temporary SQL only; no tenant or authority access")

LABELS = ("OBSERVED-FIRST", "OBSERVED-SECOND")


def money(value): return Decimal(str(value)).quantize(Decimal("0.000000001"))


def setup_case(operator, connections, *, scenario="late", raw="Commercial Rounding"):
    is_return = int(scenario in ("late", "initial", "unused"))
    kind = "limit" if scenario == "limit" else "default"
    automatic = None if scenario == "inactive" else 0 if scenario == "limit" else 1
    case = native_case(operator, connections, kind=kind, is_return=is_return,
        consolidated=int(scenario == "limit"), foreign=scenario == "initial", auto=automatic,
        is_pos=int(scenario != "ordinary"), internal=scenario == "internal")
    loyalty = 0 if scenario in ("limit", "unused", "inactive") else 1.2345
    amount = -12 if scenario == "initial" else -5 if is_return else 7 if scenario == "limit" else 5
    grand = -8.7 if is_return else 8.7
    values = dict(grand_total=money(grand), base_grand_total=money(Decimal(str(grand)) * Decimal("1.2")),
        rounded_total=money(0), base_rounded_total=money(0), conversion_rate=money(1.2), loyalty_amount=money(loyalty))
    for name, value in values.items():
        setattr(case.invoice, name, value)
        if name != "loyalty_amount": case.data.records["header"][0][name] = value
    for index, record in enumerate(case.data.records["payments"]):
        value = money(amount if index == 0 else 0)
        record["amount"] = value
        case.saved["payments", record["name"]].amount = value
        case.refs["payments"][index].amount = value
    case.round_doc.rounding_method = raw
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabSales Invoice` SET grand_total=%s,base_grand_total=%s,rounded_total=%s,"
            "base_rounded_total=%s,conversion_rate=%s,loyalty_amount=%s", tuple(values.values()))
        for record in case.data.records["payments"]:
            cursor.execute("UPDATE `tabSales Invoice Payment` SET amount=%s WHERE name=%s", (record["amount"], record["name"]))
        cursor.execute("UPDATE `tabSingles` SET value=%s WHERE field='rounding_method'", (raw,))
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    case.plan_statements = []
    def record(owned):
        original = owned.cursor
        def cursor():
            current = original()
            execute = current.execute
            def run(statement, params=()):
                case.plan_statements.append((statement, params));return execute(statement, params)
            current.execute = run
            return current
        owned.cursor = cursor
    case.before_handoff = record
    return case


def capture(case, major=16, labels=LABELS):
    return case.service.capture_settlement_plan_context(case.invoice.name, erp_major=major, append_names=labels)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("scenario,major,raw,expected", [
    ("late", 16, "Commercial Rounding", (None, "default")),
    ("initial", 15, None, ("default", None)),
    ("unused", 16, "", (None, None)),
    ("limit", 15, "Banker's Rounding", ("limit", "limit")),
    ("ordinary", 16, "Commercial Rounding", (None, None)),
    ("internal", 15, "Commercial Rounding", (None, None)),
    ("inactive", 16, "Commercial Rounding", (None, None)),
])
def test_planned_sources_follow_actual_need_on_one_owner(defaults_operator, connections, monkeypatch, upstream16,
        primary_methods, scenario, major, raw, expected):
    case = setup_case(defaults_operator, connections, scenario=scenario, raw=raw)
    if scenario in ("unused", "ordinary", "internal", "inactive"):
        defaults_operator.denied.add(("POS Profile", "SYNTHETIC-POS"))
    if scenario == "limit": defaults_operator.denied.add(("POS Payment Method", "PAY-1"))
    result = capture(case, major)
    assert type(result) is SavedSettlementPlan and result.lookups == expected
    assert result.first.pos_deferred is (scenario == "late")
    assert (result.source.pos is None) is (expected == (None, None))
    assert result.first.entry.paid.representation == "NUMERIC_FIXED"
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    if expected == (None, None):
        case.pos_metadata.assert_not_called()
        assert not any("FROM `tabPOS Profile`" in sql or "FROM `tabPOS Payment Method`" in sql for sql, _ in case.plan_statements)
    else:
        assert case.pos_metadata.call_count == 2
        assert {call.args[1] for call in case.pos_metadata.call_args_list} == {"limit" if scenario == "limit" else "default"}
    if scenario == "limit": assert not any("FROM `tabPOS Payment Method`" in sql for sql, _ in case.plan_statements)
    if scenario in ("late", "limit", "internal"):
        first_doc = primary_probe(result.first, major, upstream16, monkeypatch, methods=primary_methods[major])
        if result.second is not None:
            final = primary_probe(result.second, major, upstream16, monkeypatch,
                continuation=first_doc, via_write_off=True, methods=primary_methods[major])
            assert final.outstanding_amount == result.second.outstanding.amount
    if scenario in ("internal", "inactive"): assert result.second is None
    if scenario == "inactive":
        assert result.pin() == result
        object.__setattr__(result, "lookups", ("default", None))
        with pytest.raises(SettlementAccessError): result.pin()
    if scenario == "ordinary": assert result.second.entry.paid.rows == ()
    if scenario == "late":
        assert result.first.return_paid.appended_row_name is None
        assert result.second.return_paid.appended_row_name == LABELS[1]
        with pytest.raises(SettlementAccessError): replace(result, second=None)
        with pytest.raises(SettlementAccessError): replace(result.first, pos_deferred=False)
    assert case.invoice.name not in repr(result)
    with pytest.raises(TypeError): pickle.dumps(result)
    case.invoice.precision.assert_not_called()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15, 16], indirect=True)
@pytest.mark.parametrize("denial", ["profile", "child", "field"])
def test_lazy_related_authorization_precedes_its_provider_and_native_read(defaults_operator, connections, denial):
    case = setup_case(defaults_operator, connections)
    if denial == "profile": defaults_operator.denied.add(("POS Profile", "SYNTHETIC-POS"))
    elif denial == "child": defaults_operator.denied.add(("POS Payment Method", "PAY-1"))
    else:
        original = case.normal_metas["POS Payment Method"].get_field
        definition = original("default")
        definition.permlevel = 2
    with pytest.raises(PermissionDenied): capture(case)
    assert case.factory.call_count == 1
    case.pos_metadata.assert_not_called()
    assert not any("FROM `tabPOS Profile`" in sql or "FROM `tabPOS Payment Method`" in sql for sql, _ in case.plan_statements)
    one_failure(defaults_operator, FINANCIAL_DENIED_MESSAGE)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("boundary", ["provider", "close"])
def test_late_pos_dependency_cannot_hide_other_source_or_permission_drift(defaults_operator, connections, boundary):
    case = setup_case(defaults_operator, connections)
    if boundary == "provider":
        original = case.pos_metadata.side_effect
        def changed(*args):
            result = original(*args)
            if case.pos_metadata.call_count == 2:
                with case.opened[0].cursor() as cursor: cursor.execute("UPDATE `tabSales Invoice` SET total_advance=42")
            return result
        case.pos_metadata.side_effect = changed
    else:
        record = case.before_handoff
        def wrap(owned):
            record(owned)
            original = owned.close.side_effect
            def close():
                result = original()
                defaults_operator.denied.add(("POS Payment Method", "PAY-1"))
                return result
            owned.close.side_effect = close
        case.before_handoff = wrap
    with pytest.raises(PermissionDenied if boundary == "close" else InspectionFailed): capture(case)
    one_failure(defaults_operator, FINANCIAL_DENIED_MESSAGE if boundary == "close" else FINANCIAL_FAILED_MESSAGE)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT total_advance FROM `tabSales Invoice`")
        assert cursor.fetchone() == (money(0),)
    observer.close()
    untouched(defaults_operator, case)
