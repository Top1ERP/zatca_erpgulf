"""Original-pair-bound diagnostics; mocked ERP and SQL/observer, no HTTP."""

import csv
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import event_log, response_processing
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_event_log_contract import writer
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_reconciliation import scenario, MODES
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository import prepared
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import ValidationError


def invoke(case):
    return event_log.stage_retained_primary_event(case.captured.request, case.captured.sealed,
        reconciliation=case.service, cipher=case.core.cipher)


@pytest.mark.parametrize("status", [200, 202, 303, 400, 401, 406, 409, 503])
@pytest.mark.parametrize("body,expected", [(b"", ""), (b' \n{"ok":false}\n ', ' \n{"ok":false}\n '),
    ('رد محفوظ {"a":1}'.encode(), '{"a":1}')])
def test_only_matched_originals_supply_diagnostics_without_acceptance_or_new_capture(writer, prepared, monkeypatch, status, body, expected):
    case = scenario(monkeypatch, prepared, "matched", response={"http_status": status, "body": body})
    before = (case.core.journal, case.core.sealed, tuple(case.core.events))
    insert = writer.doc.insert.side_effect
    def write(**kwargs):
        assert all(owned.closed for owned in case.core.connections)
        assert kwargs == {"ignore_permissions": False}
        if insert:
            return insert(**kwargs)
    writer.doc.insert.side_effect = write
    assert invoke(case) is event_log.EventLogWriteResult.INSERT_RETURNED
    payload = writer.runtime.get_doc.call_args.args[0]
    assert payload == {"doctype": event_log.EVENT_LOG_DOCTYPE, "title": event_log.RETAINED_EVENT_TITLE,
        "invoice_number": prepared.context.scope.invoice_name, "custom_uuid": prepared.artifact.uuid,
        "time": "2026-10-16 12:00:00", "api_response": expected,
        "status": event_log.RETAINED_EVENT_STATUS.format(status)}
    assert (case.core.journal, case.core.sealed) == before[:2]
    assert case.core.cipher.open(case.captured.sealed).response_event.response_bytes == body
    case.core.observer.assert_called_once()  # Original synthetic setup only.
    case.core.cipher.seal.assert_not_called()
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.db.rollback.assert_not_called()
    case.core.connections[-1].commit.assert_not_called()
    assert case.factory.call_count == 1


@pytest.mark.parametrize("mode", [mode for mode in MODES if mode != "matched"])
def test_missing_partial_conflicting_and_unknown_pairs_are_never_repaired_or_logged(writer, prepared, monkeypatch, mode):
    case = scenario(monkeypatch, prepared, mode)
    before = (case.core.journal, case.core.sealed)
    with pytest.raises(event_log.RetainedEventLogError) as raised:
        invoke(case)
    assert str(raised.value) == event_log.RETAINED_EVENT_REVIEW
    assert raised.value.__context__ is raised.value.__cause__ is None and not vars(raised.value)
    assert (case.core.journal, case.core.sealed) == before
    writer.runtime.get_meta.assert_not_called()
    writer.runtime.get_doc.assert_not_called()
    case.core.connections[-1].commit.assert_not_called()
    case.core.observer.assert_called_once()
    case.core.cipher.seal.assert_not_called()


@pytest.mark.parametrize("body", [b"\xff", b"\x00\xff PRIVATE", b'{"a":"\xfe"}'])
def test_non_utf8_originals_remain_exact_in_custody_and_never_use_diagnostic_replacement(writer, prepared, monkeypatch, body):
    case = scenario(monkeypatch, prepared, "matched", response={"body": body})
    with pytest.raises(event_log.RetainedEventLogError) as raised:
        invoke(case)
    assert raised.value.__context__ is None
    assert case.core.cipher.open(case.captured.sealed).response_event.response_bytes == body
    writer.runtime.get_meta.assert_not_called()
    writer.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("fault", ["factory", "binding", "close", "rollback"])
def test_pair_inspection_uncertainty_cannot_be_substituted_by_old_success_fields(writer, prepared, monkeypatch, fault):
    case = scenario(monkeypatch, prepared, "matched")
    if fault == "factory":
        case.factory.side_effect = RuntimeError("PRIVATE acquisition")
    elif fault == "rollback":
        original = case.factory.side_effect
        def acquire():
            owned = original()
            action = owned.rollback.side_effect
            def fail():
                action()
                raise RuntimeError("PRIVATE rollback acknowledgment")
            owned.rollback.side_effect = fail
            return owned
        case.factory.side_effect = acquire
    else:
        case.core.fault = (3, fault)
    with pytest.raises(event_log.RetainedEventLogError):
        invoke(case)
    writer.runtime.get_doc.assert_not_called()
    assert (case.core.journal, case.core.sealed) == case.before_state


@pytest.mark.parametrize("error_type", [ValueError, TypeError, KeyError, ValidationError, PermissionError, RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("guarded", [False, True])
def test_insert_failures_cannot_modify_original_pair_or_repeat_inspection(writer, prepared, monkeypatch, error_type, guarded):
    case = scenario(monkeypatch, prepared, "matched")
    before = (case.core.journal, case.core.sealed)
    original = error_type("PRIVATE diagnostic insert")
    writer.doc.insert.side_effect = original
    known = error_type in (ValueError, TypeError, KeyError, ValidationError)
    expected = response_processing.LocalResponseProcessingError if guarded and known else error_type
    with pytest.raises(expected) as raised:
        if guarded:
            response_processing.run_received_response_step(invoke, case, validation_error_type=ValidationError)
        else:
            invoke(case)
    if guarded and known:
        assert raised.value.__context__ is None and not vars(raised.value)
    else:
        assert raised.value is original
    assert (case.core.journal, case.core.sealed) == before
    assert case.factory.call_count == 1
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.db.rollback.assert_not_called()
    writer.runtime.log_error.assert_not_called()
    case.core.observer.assert_called_once()


@pytest.mark.parametrize("defect", ["request", "seal", "cipher", "service", "wrong-key", "wrong-seal"])
def test_invalid_or_unrelated_protected_inputs_do_not_reach_diagnostic_writer(writer, prepared, monkeypatch, defect):
    case = scenario(monkeypatch, prepared, "matched")
    request, sealed, cipher, service = case.captured.request, case.captured.sealed, case.core.cipher, case.service
    if defect == "request":
        request = object()
    elif defect == "seal":
        sealed = object()
    elif defect == "cipher":
        cipher = object()
    elif defect == "service":
        service = Mock(state="PAIR_MATCHED_OBSERVATION_NO_REPLAY")
    elif defect == "wrong-key":
        cipher = PrimaryReceiptCustodyCipher({sealed.key_id: b"X" * 32})
    else:
        sealed = replace(sealed, ciphertext=sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1]))
    with pytest.raises(event_log.RetainedEventLogError) as raised:
        event_log.stage_retained_primary_event(request, sealed, reconciliation=service, cipher=cipher)
    assert raised.value.__context__ is None
    case.factory.assert_not_called()
    writer.runtime.get_meta.assert_not_called()
    writer.runtime.get_doc.assert_not_called()


def test_retained_event_labels_and_review_use_arabic_catalog_without_translating_body(writer, prepared, monkeypatch):
    with (Path(event_log.__file__).parents[1] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(event_log, "_", lambda message: entries[message])
    case = scenario(monkeypatch, prepared, "matched", response={"body": b'{"message":"UNCHANGED"}'})
    invoke(case)
    payload = writer.runtime.get_doc.call_args.args[0]
    assert payload["title"] == entries[event_log.RETAINED_EVENT_TITLE]
    assert payload["status"] == entries[event_log.RETAINED_EVENT_STATUS].format(case.captured.receipt.response_event.http_status)
    assert payload["api_response"] == '{"message":"UNCHANGED"}'


@pytest.mark.parametrize("defect", ["new-envelope", "other-namespace", "other-attempt"])
def test_readable_but_different_original_bindings_are_not_accepted_as_the_stored_pair(writer, prepared, monkeypatch, defect):
    case = scenario(monkeypatch, prepared, "matched")
    request, sealed = case.captured.request, case.captured.sealed
    if defect == "new-envelope":
        sealed = PrimaryReceiptCustodyCipher.seal(case.core.cipher, case.captured.receipt, key_id=sealed.key_id)
        assert sealed != case.captured.sealed  # Same plaintext is not the SAME original envelope.
    elif defect == "other-namespace":
        receipt = replace(case.captured.receipt, storage_namespace="90000000-0000-4000-8000-000000000001")
        sealed = PrimaryReceiptCustodyCipher.seal(case.core.cipher, receipt, key_id=sealed.key_id)
    else:
        started = replace(request.started, events=(replace(request.started.events[0],
            attempt_id="90000000-0000-4000-8000-000000000002"),))
        request = replace(request, started=started)
    with pytest.raises(event_log.RetainedEventLogError):
        event_log.stage_retained_primary_event(request, sealed, reconciliation=case.service, cipher=case.core.cipher)
    assert case.factory.call_count == (defect == "new-envelope")
    assert (case.core.journal, case.core.sealed) == case.before_state
    writer.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("step", ["guard", "rollback", "close"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_inspection_interruptions_propagate_after_owned_cleanup_without_logging(writer, prepared, monkeypatch, step, error_type):
    case = scenario(monkeypatch, prepared, "matched")
    original_error = error_type("PRIVATE inspection interruption")
    if step == "guard":
        case.guard.side_effect = original_error
    else:
        factory = case.factory.side_effect
        def acquire():
            owned = factory()
            action = getattr(owned, step).side_effect
            def interrupt():
                action()
                raise original_error
            getattr(owned, step).side_effect = interrupt
            return owned
        case.factory.side_effect = acquire
    with pytest.raises(error_type) as raised:
        invoke(case)
    assert raised.value is original_error
    owned = case.core.connections[-1]
    owned.rollback.assert_called_once()
    owned.close.assert_called_once()
    owned.commit.assert_not_called()
    writer.runtime.get_doc.assert_not_called()
    assert (case.core.journal, case.core.sealed) == case.before_state


def test_missing_diagnostic_schema_after_pair_read_preserves_originals(writer, prepared, monkeypatch):
    case = scenario(monkeypatch, prepared, "matched")
    meta = writer.runtime.get_meta.return_value
    meta.fields.remove(meta.get_field("status"))
    with pytest.raises(event_log.EventLogSchemaError):
        invoke(case)
    assert (case.core.journal, case.core.sealed) == case.before_state
    writer.runtime.get_doc.assert_not_called()
    assert all(owned.closed for owned in case.core.connections)


def test_retained_pair_review_error_is_arabic_and_not_a_raw_body_or_identity_export(writer, prepared, monkeypatch):
    with (Path(event_log.__file__).parents[1] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(event_log, "_", lambda message: entries[message])
    case = scenario(monkeypatch, prepared, "missing")
    with pytest.raises(event_log.RetainedEventLogError) as raised:
        invoke(case)
    assert str(raised.value) == entries[event_log.RETAINED_EVENT_REVIEW]
    assert raised.value.__context__ is None and not vars(raised.value)
    writer.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("code", ["388", "381", "383", "386"])
def test_scoped_invoice_identity_comes_from_the_original_candidate_for_all_declared_types(writer, certificates,
    monkeypatch, doctype, indicator, code):
    selected = candidate(certificates[0], selected_scope=scope(doctype=doctype), indicator=indicator, code=code)
    case = scenario(monkeypatch, selected, "matched")
    assert invoke(case) is event_log.EventLogWriteResult.INSERT_RETURNED
    payload = writer.runtime.get_doc.call_args.args[0]
    assert payload["invoice_number"] == selected.context.scope.invoice_name
    assert payload["custom_uuid"] == selected.artifact.uuid
    assert (case.core.journal, case.core.sealed) == case.before_state
    assert case.factory.call_count == 1
