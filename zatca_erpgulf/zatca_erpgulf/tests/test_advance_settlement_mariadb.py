"""Complete advance/settlement arithmetic on NEW guard-owned SQL only.

Execute actual15/pinned16 controller bodies on one synthetic document. Native
fixture data stays unchanged; this does not exercise installed ERP or GL hooks.
"""

from dataclasses import replace
import inspect
import json
import os
import pickle
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf.calculation_advance_settlement import SavedAdvanceSettlementPlan
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_access import SettlementAccessError
from zatca_erpgulf.zatca_erpgulf.calculation_settlement_plan import _saved_inputs
from zatca_erpgulf.zatca_erpgulf.calculation_receivable import AUTO
from zatca_erpgulf.zatca_erpgulf.calculation_field_rounding_access import _result_tag
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_plan_mariadb import setup_case, money, LABELS
from zatca_erpgulf.zatca_erpgulf.tests.test_calculated_totals import controller
from zatca_erpgulf.zatca_erpgulf.tests.test_field_rounding import framework
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_precision import upstream16
from zatca_erpgulf.zatca_erpgulf.tests.test_outstanding_guard import primary_methods
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_settlement_access_mariadb import (
    empty_pos_sources, combined_schema, defaults_schema, financial_schema, metadata_schema,
    isolated_server, connections, untouched, format_schema, field_schema, empty_sources, selected_schema, pos_schema,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_calculation_defaults_access import (
    defaults_operator, operator, one_failure, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.calculation_defaults_access import FINANCIAL_DENIED_MESSAGE, FINANCIAL_FAILED_MESSAGE

pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="NEW guard-owned TCP-disabled SQL only; no tenant or authority access")


def configure(case, connections, *, allocation=1.25, write_off=0.37):
    """Change only NEW fixture rows; keep an intentionally stale stored total."""
    case.invoice.write_off_amount = money(write_off)
    setup = connections()
    with setup.cursor() as cursor:
        cursor.execute("UPDATE `tabSales Invoice` SET write_off_amount=%s", (money(write_off),))
        if allocation is None:
            cursor.execute("DELETE FROM `tabSales Invoice Advance`")
            case.data.records["advances"].clear()
            case.refs["advances"].clear()
        for index, row in enumerate(case.data.records["advances"]):
            reference = "HISTORICAL-2020-" + str(index + 1)
            row.update(allocated_amount=money(allocation), reference_name=reference)
            for obj in (case.saved["advances", row["name"]], case.refs["advances"][index]):
                obj.allocated_amount, obj.reference_name = money(allocation), reference
            cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=%s,reference_name=%s WHERE name=%s",
                (money(allocation), reference, row["name"]))
    setup.commit();setup.close()  # NEW synthetic fixture setup only.
    return case


def capture(case, major=16):
    return case.service.capture_advance_settlement_context(case.invoice.name, erp_major=major, append_names=LABELS)


def primary_chain(case, result, major, upstream16, monkeypatch, methods):
    """Run the full primary call tree, retaining the SAME document and children."""
    source, limit = result.source, result.limit
    raw = source.prefix.method.rounding.value
    probe = framework(major, upstream16, monkeypatch, setting=raw)
    precisions = {proof.target[2]: proof.precision.precision for proof in
        (*source.guarded.payment.stage.fields, *source.receivable.stage.fields, *source.prefix.fields)}
    precisions.update((name, proof.precision) for name, proof in source.receivable.precisions)
    headers, rows, prefix = _saved_inputs(source)
    native_header = dict(json.loads(source.prefix.numeric.view.financial.financial._payload)["header"])
    checks = dict(source.guarded.payment.controls.normalized_checks)
    inputs = None if result.settlement is None else result.settlement.first.entry.decision.inputs
    calls, states, resets = [], [], []
    active = {"ready": False, "outstanding": -1}

    class Rejected(Exception): pass

    class Root(SimpleNamespace):
        def get(self, name): return getattr(self, name, None)
        def set(self, name, value): setattr(self, name, value)
        def precision(self, name, parentfield=None): return precisions[name]
        def round_floats_in(self, doc, names): probe.method(self, doc, names)
        def __setattr__(self, name, value):
            if active["ready"] and name == "write_off_amount" and active["outstanding"] < 0:
                resets.append(value)
                calls.append("reset_write_off")
            object.__setattr__(self, name, value)
        def append(self, table, values):
            assert table == "payments"
            name = LABELS[active["outstanding"]]
            self.payments.append(SimpleNamespace(name=name, base_amount=None, type=None, **values))

    initial = dict(prefix)
    initial.update(headers)
    doc = Root(doctype="Sales Invoice", company=case.company.name,
        currency=native_header["currency"][1], party_account_currency=source.receivable.party.currency,
        docstatus=SimpleNamespace(is_cancelled=lambda: False),
        is_internal_customer=0 if inputs is None else inputs.is_internal_customer,
        represents_company=None if inputs is None else inputs.represents_company,
        return_against=None, update_outstanding_for_self=0,
        pos_profile="SYNTHETIC-POS", is_pos=checks["is_pos"], is_return=int(source.receivable.is_return),
        is_consolidated=dict(source.controls.checks)["is_consolidated"],
        redeem_loyalty_points=checks["redeem_loyalty_points"], **initial)
    setattr(doc, AUTO, case.invoice.write_off_outstanding_amount_automatically)
    types = {name: None if tag == ("null",) else tag[1] for name, tag in source.guarded.payment.payment_types}
    doc.payments = [SimpleNamespace(name=name, amount=amount, base_amount=999.0, type=types[name]) for name, amount in rows]
    row_precisions = dict(limit.source.advance.row_precisions)
    doc.advances = [SimpleNamespace(allocated_amount=amount,
        precision=lambda field, name=name: row_precisions[name]) for name, amount in limit.aggregate.rows.values]
    owner = SimpleNamespace(doc=doc)
    def internal_transfer(): return methods["is_internal_transfer"](doc)
    doc.is_internal_transfer = internal_transfer
    def reject(message):
        assert _result_tag(inspect.currentframe().f_back.f_locals["invoice_total"]) == _result_tag(limit.invoice_total)
        raise Rejected
    def get_value(dt, *args, **kwargs):
        assert source.pos is not None
        if dt == "POS Profile": return source.pos.lookup.limit_observation().value
        assert dt == "POS Payment Method"
        lookup = source.pos.lookup.default_observation()
        return SimpleNamespace(mode_of_payment=lookup.mode_of_payment) if lookup.found else None
    namespace = {"flt": probe.flt, "frappe": SimpleNamespace(throw=reject,
        db=SimpleNamespace(get_value=get_value)), "_": lambda value: value}
    for name in ("calculate_paid_amount", "calculate_change_amount", "_set_in_company_currency",
                 "calculate_write_off_amount", "calculate_outstanding_amount", "set_total_amount_to_default_mop"):
        primary = controller(name, major, dict(namespace))
        setattr(owner, name, lambda *args, primary=primary: primary(owner, *args))
    owner.is_internal_invoice = lambda: methods["is_internal_invoice"](owner)
    actual_outstanding, actual_write_off = owner.calculate_outstanding_amount, owner.calculate_write_off_amount
    def outstanding():
        active["outstanding"] += 1
        calls.append("calculate_outstanding_amount")
        sequence = result.settlement.first if active["outstanding"] == 0 else result.settlement.second
        assert sequence is not None
        if active["outstanding"] == 0:
            assert _result_tag(inspect.currentframe().f_back.f_locals["invoice_total"]) == _result_tag(limit.invoice_total)
            if sequence.prefix is not None:
                for name, value in sequence.prefix.values:
                    assert _result_tag(doc.get(name)) == _result_tag(value)
        actual_outstanding()
        expected = 0 if sequence.outstanding is None else sequence.outstanding.amount
        assert _result_tag(doc.outstanding_amount) == _result_tag(expected)
        paid = sequence.return_paid if sequence.return_paid is not None else sequence.entry.paid
        for name, value in paid.totals:
            assert _result_tag(doc.get(name)) == _result_tag(value)
        if doc.is_pos:
            assert tuple((row.name, row.amount, row.base_amount) for row in doc.payments) == paid.payments
        states.append(doc.outstanding_amount)
    def write_off():
        calls.append("calculate_write_off_amount")
        actual_write_off()
    owner.calculate_outstanding_amount, owner.calculate_write_off_amount = outstanding, write_off
    active["ready"] = True
    blocked = False
    try: controller("calculate_total_advance", major, dict(namespace))(owner)
    except Rejected: blocked = True
    assert blocked is limit.blocked
    assert _result_tag(doc.total_advance) == _result_tag(limit.aggregate.total_advance)
    assert resets == ([0] if limit.reset_write_off else [])
    assert all(type(value) is int for value in resets)
    assert tuple(calls) == result.calls[2:]
    if not blocked:
        assert len(states) == (2 if result.settlement.second is not None else 1)
    return doc


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("major,scenario,allocation,raw", [
    (15, "ordinary", 1.25, "Commercial Rounding"),
    (16, "ordinary", 1.25, None),
    (16, "initial", 1.25, "Commercial Rounding"),
    (15, "limit", 0.25, "Banker's Rounding"),
    (16, "internal", 0.25, "Commercial Rounding"),
    (16, "inactive", 20, "Commercial Rounding"),
    (16, "empty", None, "Commercial Rounding"),
])
def test_full_primary_advance_to_settlement_chain(defaults_operator, connections, monkeypatch, upstream16,
        primary_methods, major, scenario, allocation, raw):
    case = configure(setup_case(defaults_operator, connections, scenario="ordinary" if scenario == "empty" else scenario, raw=raw), connections,
        allocation=allocation)
    if scenario == "inactive": defaults_operator.denied.add(("POS Profile", "SYNTHETIC-POS"))
    result = capture(case, major)
    assert type(result) is SavedAdvanceSettlementPlan
    assert result.status == ("LIMIT_EXCEEDED" if scenario == "inactive" else "CALCULATED")
    assert len(case.opened) == 1 and case.opened[0].rollback.call_count == 2
    assert result.limit.source.advance.stage.numeric == result.source.prefix.numeric
    assert result.limit.source.advance.stage.owner_document == id(case.invoice)
    statements = len(case.plan_statements)
    primary_chain(case, result, major, upstream16, monkeypatch, primary_methods[major])
    assert len(case.plan_statements) == statements
    if scenario == "inactive":
        assert result.settlement is None and result.source.pos is None
        case.pos_metadata.assert_not_called()
    if scenario == "internal":
        assert result.settlement.first.entry.decision.skip_balance
        assert result.settlement.second.entry.decision.skip_balance
        assert result.settlement.second.prefix is None
    if scenario == "empty":
        assert result.limit.aggregate.rows.values == result.limit.source.advance.row_precisions == ()
    if scenario == "ordinary" and major == 16:
        # Derived advance values cannot be passed off as the original saved
        # total or detached from their exact ceiling and source evidence.
        with pytest.raises(SettlementAccessError): replace(result.settlement, advance=None)
        calculated_limit = replace(result.limit, representation="CALCULATED")
        with pytest.raises(SettlementAccessError): replace(result, limit=calculated_limit)
        tampered = replace(result)
        object.__setattr__(tampered, "status", "PASS")
        with pytest.raises(SettlementAccessError): tampered.pin()
    assert case.invoice.total_advance == money(0) and case.invoice.write_off_amount == money(0.37)
    assert case.invoice.name not in repr(result)
    assert not any("FROM `tabPayment Entry`" in sql or "FROM `tabAdvance Sales Invoice`" in sql
        for sql, _ in case.plan_statements)
    with pytest.raises(TypeError): pickle.dumps(result)
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT total_advance,write_off_amount FROM `tabSales Invoice`")
        assert cursor.fetchone() == (money(0), money(0.37))
    observer.close()
    untouched(defaults_operator, case)


@pytest.mark.parametrize("defaults_operator", [15], indirect=True)
@pytest.mark.parametrize("boundary", ["field", "native", "close", "cancelled"])
def test_advance_access_and_drift_use_one_localized_failure(defaults_operator, connections, boundary):
    case = configure(setup_case(defaults_operator, connections, scenario="ordinary"), connections)
    if boundary == "field":
        case.field_overrides["Sales Invoice Advance", "allocated_amount"] = Document(fieldtype="Currency", permlevel=2)
    elif boundary == "cancelled":
        case.invoice.docstatus = case.data.records["header"][0]["docstatus"] = 2
        setup = connections()
        with setup.cursor() as cursor: cursor.execute("UPDATE `tabSales Invoice` SET docstatus=2")
        setup.commit();setup.close()  # NEW synthetic setup only.
    elif boundary == "native":
        old = case.write_metadata.side_effect
        def changed(*args):
            value = old(*args)
            if case.write_metadata.call_count == 2:
                with case.opened[0].cursor() as cursor:
                    cursor.execute("UPDATE `tabSales Invoice Advance` SET allocated_amount=99")
            return value
        case.write_metadata.side_effect = changed
    else:
        record = case.before_handoff
        def handoff(owned):
            record(owned)
            old = owned.close.side_effect
            def close():
                result = old()
                case.refs["advances"][0]._precision = {"main": {"allocated_amount": 7}}
                return result
            owned.close.side_effect = close
        case.before_handoff = handoff
    with pytest.raises(PermissionDenied if boundary == "field" else InspectionFailed): capture(case)
    if boundary == "field":
        case.factory.assert_not_called()
        case.metadata_provider.assert_not_called()
    one_failure(defaults_operator, FINANCIAL_DENIED_MESSAGE if boundary == "field" else FINANCIAL_FAILED_MESSAGE)
    if boundary == "cancelled": case.pos_metadata.assert_not_called()
    untouched(defaults_operator, case)
