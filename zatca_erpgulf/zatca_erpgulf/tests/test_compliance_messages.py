"""Synthetic, request-local presentation contracts; no site or HTTP transport."""

import ast
import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf.compliance_messages import (
    ALREADY_COMPLETED, COMPLETED, WITH_WARNINGS, FAILED, UNCONFIRMED,
    collect_compliance_results,
)
from zatca_erpgulf.zatca_erpgulf import operation_messages
from zatca_erpgulf.zatca_erpgulf.operation_messages import mute_operation_messages
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES


class ValidationError(Exception):
    pass


def runtime(flags):
    return SimpleNamespace(flags=flags, ValidationError=ValidationError,
                           message_log=[{"message": "Unrelated parent message"}])


def confirmed():
    return {"validationResults": {"status": "PASS"}}


@pytest.mark.parametrize("initial", [{}, {"mute_messages": False}, {"mute_messages": True},
                                    {"mute_messages": None}, {"mute_messages": "parent-value"}])
@pytest.mark.parametrize("failure", [False, True])
def test_request_flag_is_restored_and_parent_messages_are_untouched(initial, failure):
    app = runtime(dict(initial))
    flags, messages = app.flags, app.message_log
    raw = 'ERROR: {"message":"Original هيئة response", "request_id":"mock-id"}\n'
    calls = []

    def submit(kind):
        calls.append(kind)
        assert app.flags["mute_messages"] is True
        # Model Frappe msgprint/throw: muting suppresses only enqueueing.
        if not app.flags.get("mute_messages"):
            app.message_log.append({"message": raw})
        if failure:
            raise ValidationError(raw)
        return confirmed()

    rows = collect_compliance_results(app, COMPLIANCE_TYPES, submit)
    assert calls == list(COMPLIANCE_TYPES)
    assert app.flags is flags and flags == initial
    assert app.message_log is messages and messages == [{"message": "Unrelated parent message"}]
    assert all(row["message"] == (FAILED if failure else COMPLETED) for row in rows)
    if failure:
        assert all(row["technical_details"] == raw for row in rows)
        assert all(row["status"] == "FAIL" for row in rows)


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_interrupts_propagate_without_leaving_request_muted(stop):
    app = runtime({"mute_messages": False})
    interrupt = stop("synthetic cancellation")

    def submit(kind):
        raise interrupt

    with pytest.raises(stop) as raised:
        collect_compliance_results(app, COMPLIANCE_TYPES, submit)
    assert raised.value is interrupt
    assert app.flags == {"mute_messages": False}


def test_nested_batches_restore_the_outer_mute_without_clearing_messages():
    app = runtime({})
    with mute_operation_messages(app):
        rows = collect_compliance_results(app, COMPLIANCE_TYPES, lambda kind: confirmed())
        assert app.flags == {"mute_messages": True}
        assert all(row["status"] == "PASS" for row in rows)
    assert app.flags == {}
    assert len(app.message_log) == 1


@pytest.mark.parametrize("response", [None, {}, "OK", {"validationResults": {"status": "ERROR"}}])
def test_unknown_acceptance_is_a_canonical_english_failure_not_a_success(response):
    app = runtime({})
    rows = collect_compliance_results(app, COMPLIANCE_TYPES, lambda kind: response)
    assert len(rows) == 6
    assert all(row == {"type": kind, "status": "FAIL", "message": FAILED,
                       "technical_details": UNCONFIRMED} for row, kind in zip(rows, COMPLIANCE_TYPES))


def test_known_summary_and_type_keys_have_arabic_display_translations():
    path = Path(__file__).parents[2] / "translations/ar.csv"
    with path.open(encoding="utf-8", newline="") as source:
        translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
    for key in (*COMPLIANCE_TYPES, COMPLETED, WITH_WARNINGS, ALREADY_COMPLETED, FAILED, "Technical details", "PASS", "FAIL",
                "No compliance results were returned. Completion has not been confirmed.",
                "The operation could not be completed. Reload the form and try again."):
        assert any("\u0600" <= char <= "\u06ff" for char in translations[key])


@pytest.mark.parametrize("status", ["PASS", "WARNING"])
def test_warnings_remain_visible_and_do_not_change_the_existing_acceptance_rule(status):
    validation = {"status": status, "warningMessages": [{"code": "mock-warning", "message": "UNCHANGED تحذير"}]}
    rows = collect_compliance_results(runtime({}), COMPLIANCE_TYPES, lambda kind: {"validationResults": validation})
    assert all(row["status"] == "PASS" and row["message"] == WITH_WARNINGS for row in rows)
    assert all(row["validation_details"] is validation for row in rows)
    assert validation == {"status": status, "warningMessages": [{"code": "mock-warning", "message": "UNCHANGED تحذير"}]}


def test_debug_and_single_message_keys_have_arabic_display_entries():
    path = Path(__file__).parents[2] / "translations/ar.csv"
    with path.open(encoding="utf-8", newline="") as source:
        translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
    keys = [getattr(operation_messages, name) for name in vars(operation_messages) if name.startswith("DEBUG_")]
    for key in (*keys, "Debug XML Result", "Compliance Check Result", "Compliance Check Failed",
                "Running compliance check...", "This is a local debug operation, not a ZATCA submission.",
                "No confirmed Debug XML result was returned. Review before trying again."):
        assert any("\u0600" <= char <= "\u06ff" for char in translations[key])


def test_shared_presenter_is_declared_once_in_development_desk_assets():
    root = Path(__file__).parents[2]
    tree = ast.parse((root / "hooks.py").read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "app_include_js" for target in node.targets))
    asset = "/assets/zatca_erpgulf/js/operation_messages.js"
    assert ast.literal_eval(assignment.value).count(asset) == 1
    shared = root / "public/js/operation_messages.js"
    assert "function zatca_compliance_summary" in shared.read_text(encoding="utf-8")
    assert "function zatca_debug_summary" in shared.read_text(encoding="utf-8")
    assert "function zatca_compliance_summary" not in (root / "public/js/company.js").read_text(encoding="utf-8")
