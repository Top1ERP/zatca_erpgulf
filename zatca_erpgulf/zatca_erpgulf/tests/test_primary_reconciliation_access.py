"""Synthetic saved WRITE/owner/key/exact-envelope ACL for local pair access."""

import csv
from dataclasses import replace
from datetime import timedelta
import hashlib
import inspect
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_reconciliation_access as access
from zatca_erpgulf.zatca_erpgulf import primary_receipt_access as receipt_access
from zatca_erpgulf.zatca_erpgulf.journal_storage import encode_dispatch_event
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody_access import PrimaryReceiptCustodyKeys
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_access import (
    operator, receipt_operator, scenario as receipt_scenario, PermissionDenied, InspectionFailed, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_reconciliation import scenario as pair_scenario, MODES


@pytest.fixture
def pair_operator(receipt_operator, monkeypatch):
    monkeypatch.setattr(access, "frappe", receipt_operator.runtime)
    monkeypatch.setattr(access, "_", lambda message: message)
    monkeypatch.setattr(access, "has_permission", receipt_access.has_permission)
    return receipt_operator


def configure(case, request, sealed, cipher):
    case.request, case.sealed, case.cipher = request, sealed, cipher
    candidate = request.started.candidate
    case.binding = access.PrimaryReconciliationBinding(case.scope, candidate.context, candidate.artifact.uuid,
        candidate.artifact.icv, request.started.journal_sha256, request.started.events[0].attempt_id,
        hashlib.sha256(encode_dispatch_event(request.started.events[0])).hexdigest(), request.body_sha256,
        sealed.key_id, sealed.receipt_sha256, access.sealed_envelope_sha256(sealed))
    case.lookup.return_value = case.binding
    case.keys = Mock(return_value=PrimaryReceiptCustodyKeys(case.scope, sealed.key_id, cipher))
    case.service = access.SavedPrimaryReconciliationService(case.scope, case.lookup, case.keys, case.factory)
    return case


def scenario(pair_operator, der, monkeypatch, *, mode="missing", **options):
    case = receipt_scenario(pair_operator, der, monkeypatch, **options)
    case.corecase = pair_scenario(monkeypatch, case.original, mode, namespace=case.scope.storage_namespace)
    case.factory = Mock(side_effect=lambda scope: case.corecase.factory())
    captured = case.corecase.captured
    configure(case, captured.request, captured.sealed, case.corecase.core.cipher)
    case.sql_guard = Mock()
    monkeypatch.setattr(access, "_verify_rows", case.sql_guard)
    return case


def invoke(case, operation):
    return getattr(case.service, operation)(case.invoice.name, case.request, case.sealed, doctype=case.invoice.doctype)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_saved_pair_access_returns_only_metadata_without_transport_or_new_ciphertext(pair_operator, certificates,
    monkeypatch, operation, doctype, indicator, owner):
    case = scenario(pair_operator, certificates[0], monkeypatch, doctype=doctype, indicator=indicator, owner=owner)
    report = invoke(case, operation)
    assert report["state"] == (MODES["missing"] if operation == "inspect" else "PAIR_STORED_OBSERVATION_NO_REPLAY")
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert not {"request", "receipt", "response", "sealed", "body", "uuid", "invoice_name", "key_id"} & report.keys()
    assert "INV-TEST" not in json.dumps(report) and "PRIVATE" not in json.dumps(report)
    case.keys.assert_called_once_with(case.scope)
    case.factory.assert_called_once_with(case.scope)
    assert case.sql_guard.call_count == 2
    owned = case.corecase.core.connections[-1]
    assert owned.closed and owned.rollback.call_count == 2  # Owned acquisition + final cleanup.
    assert owned.commit.call_count == (operation == "persist")
    case.corecase.core.observer.assert_called_once()  # Initial fixture capture ONLY.
    case.cipher.seal.assert_not_called()
    untouched(pair_operator)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("mode", list(MODES))
def test_saved_pair_policy_does_not_turn_partial_conflicting_or_unknown_records_into_success(pair_operator,
    certificates, monkeypatch, operation, mode):
    case = scenario(pair_operator, certificates[0], monkeypatch, mode=mode)
    report = invoke(case, operation)
    expected = MODES[mode]
    if operation == "persist" and mode in ("missing", "matched"):
        expected = "PAIR_STORED_OBSERVATION_NO_REPLAY" if mode == "missing" else "PAIR_ALREADY_STORED_OBSERVATION_NO_REPLAY"
    assert report["state"] == expected
    if operation == "inspect" or mode != "missing":
        assert (case.corecase.core.journal, case.corecase.core.sealed) == case.corecase.before_state
    case.cipher.seal.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("status", [None, "", "Not Submitted", "REPORTED", "CLEARED", "503 Service Unavailable"])
def test_current_status_is_not_pair_access_or_remote_acceptance_authority(pair_operator, certificates, monkeypatch,
    operation, status):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    case.invoice.custom_zatca_status = status
    report = invoke(case, operation)
    assert report["state"] == (MODES["missing"] if operation == "inspect" else "PAIR_STORED_OBSERVATION_NO_REPLAY")
    assert report["remote_acceptance_verified"] is report["dispatch_authorized"] is report["replay_authorized"] is False
    untouched(pair_operator)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
def test_interruption_propagates_after_owned_cleanup_and_caller_keeps_original_request_and_envelope(pair_operator,
    certificates, monkeypatch, operation):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    original_request, original_sealed = case.request, case.sealed
    case.sql_guard.side_effect = KeyboardInterrupt("PRIVATE synthetic interrupted guard")
    with pytest.raises(KeyboardInterrupt):
        invoke(case, operation)
    assert case.request is original_request and case.sealed is original_sealed
    assert case.cipher.open(original_sealed) == case.corecase.captured.receipt
    assert (case.corecase.core.journal, case.corecase.core.sealed) == case.corecase.before_state
    assert all(owned.closed for owned in case.corecase.core.connections)
    case.corecase.core.observer.assert_called_once()
    case.cipher.seal.assert_not_called()
    untouched(pair_operator)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("identity", ["source", "company", "device", "linked"])
def test_saved_pair_acl_denial_precedes_lookup_keys_and_sql_even_with_ignore_permissions(pair_operator, certificates,
    monkeypatch, operation, identity):
    case = scenario(pair_operator, certificates[0], monkeypatch, owner="linked")
    key = {"source": ("Sales Invoice", "INV-TEST", "write"), "company": ("Company", "TEST", "read"),
        "device": ("ZATCA Multiple Setting", "DEVICE", "read"), "linked": ("Company", "LINKED", "read")}[identity]
    pair_operator.denied_operations.add(key)
    pair_operator.documents[key[:2]].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as error:
        invoke(case, operation)
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.lookup.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()
    untouched(pair_operator)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("actor", ["guest", "role", "site"])
def test_saved_pair_actor_role_and_site_precede_all_saved_reads(pair_operator, certificates, monkeypatch, operation, actor):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    if actor == "guest":
        pair_operator.runtime.session.user = "Guest"
    elif actor == "role":
        pair_operator.runtime.get_roles.return_value = []
    else:
        pair_operator.runtime.local.site = "OTHER.test"
    with pytest.raises(PermissionDenied):
        invoke(case, operation)
    pair_operator.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("field,value", [("attempt_id", "50000000-0000-4000-8000-000000000001"),
    ("journal_sha256", "0" * 64), ("start_event_sha256", "0" * 64), ("request_sha256", "0" * 64),
    ("receipt_sha256", "0" * 64), ("envelope_sha256", "0" * 64), ("custody_key_id", "other-key")])
def test_saved_exact_request_and_original_seal_binding_precedes_keys(pair_operator, certificates, monkeypatch,
    operation, field, value):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    case.lookup.return_value = replace(case.binding, **{field: value})
    with pytest.raises(InspectionFailed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("substitution", ["reseal", "nonce", "ciphertext"])
def test_same_plaintext_different_original_envelope_is_rejected_before_keys(pair_operator, certificates, monkeypatch,
    operation, substitution):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    if substitution == "reseal":
        alternate = PrimaryReceiptCustodyCipher({case.sealed.key_id: b"P" * 32})
        case.sealed = alternate.seal(case.corecase.captured.receipt, key_id=case.sealed.key_id)
    elif substitution == "nonce":
        case.sealed = replace(case.sealed, nonce=bytes([case.sealed.nonce[0] ^ 1]) + case.sealed.nonce[1:])
    else:
        case.sealed = replace(case.sealed, ciphertext=case.sealed.ciphertext[:-1] + bytes([case.sealed.ciphertext[-1] ^ 1]))
    with pytest.raises(InspectionFailed):
        invoke(case, operation)
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("wrong", ["request", "body", "envelope", "scope", "target", "doctype"])
def test_bad_request_scope_or_target_precedes_saved_lookup(pair_operator, certificates, monkeypatch, operation, wrong):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    name, doctype = case.invoice.name, case.invoice.doctype
    if wrong == "request":
        case.request = None
    elif wrong == "body":
        object.__setattr__(case.request, "body", b"FORGED PRIVATE BODY")
    elif wrong == "envelope":
        case.sealed = {}
    elif wrong == "scope":
        case.sealed = replace(case.sealed, storage_namespace="50000000-0000-4000-8000-000000000001")
    elif wrong == "target":
        name = "OTHER-INVOICE"
    else:
        doctype = "POS Invoice"
    with pytest.raises(InspectionFailed) as error:
        getattr(case.service, operation)(name, case.request, case.sealed, doctype=doctype)
    assert error.value.__context__ is None
    pair_operator.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("wrong", ["type", "scope", "key-id", "wrong-key", "provider"])
def test_scoped_typed_keys_and_authentication_before_owned_sql(pair_operator, certificates, monkeypatch, operation, wrong):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    if wrong == "type":
        case.keys.return_value = {}
    elif wrong == "scope":
        case.keys.return_value = PrimaryReceiptCustodyKeys(replace(case.scope, site="OTHER.test"), case.sealed.key_id, case.cipher)
    elif wrong == "key-id":
        case.keys.return_value = PrimaryReceiptCustodyKeys(case.scope, "OTHER-KEY", case.cipher)
    elif wrong == "wrong-key":
        case.keys.return_value = PrimaryReceiptCustodyKeys(case.scope, case.sealed.key_id,
            PrimaryReceiptCustodyCipher({case.sealed.key_id: b"X" * 32}))
    else:
        case.keys.side_effect = RuntimeError("PRIVATE key provider")
    with pytest.raises(InspectionFailed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("stage", ["lookup", "keys", "factory", "first-guard", "last-guard", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_late_source_or_acl_drift_refuses_even_metadata_without_losing_original_input(pair_operator, certificates,
    monkeypatch, operation, stage, change):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    original_sealed = case.sealed
    def mutate():
        if change == "permission":
            pair_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
        elif change == "actor":
            pair_operator.runtime.session.user = "OTHER-MANAGER@example.test"
        else:
            case.invoice.modified += timedelta(seconds=1)
    if stage in ("lookup", "keys", "factory"):
        target = {"lookup": case.lookup, "keys": case.keys, "factory": case.factory}[stage]
        original = target.side_effect
        def changed(*args):
            result = original(*args) if original is not None else target.return_value
            mutate()
            return result
        target.side_effect = changed
    elif stage in ("first-guard", "last-guard"):
        def locked(*args):
            if case.sql_guard.call_count == (1 if stage == "first-guard" else 2):
                mutate()
        case.sql_guard.side_effect = locked
    else:
        original = case.factory.side_effect
        def changed(scope):
            owned = original(scope)
            close = owned.close.side_effect
            def changed_close():
                close()
                mutate()
            owned.close.side_effect = changed_close
            return owned
        case.factory.side_effect = changed
    with pytest.raises(InspectionFailed if change == "revision" else PermissionDenied) as error:
        invoke(case, operation)
    assert error.value.__context__ is None and case.sealed is original_sealed
    assert case.cipher.open(original_sealed) == case.corecase.captured.receipt
    if stage in ("lookup", "keys"):
        case.factory.assert_not_called()
    elif operation == "persist" and stage == "close":
        assert case.corecase.core.sealed is original_sealed  # Final denial cannot undo commit.
    else:
        assert (case.corecase.core.journal, case.corecase.core.sealed) == case.corecase.before_state
    assert all(owned.closed for owned in case.corecase.core.connections)
    case.cipher.seal.assert_not_called()
    untouched(pair_operator)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_ambient_handles_are_rejected_untouched_with_unconfirmed_metadata(pair_operator, certificates, monkeypatch, operation, borrowed):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    raw = SimpleNamespace(cursor=Mock(), commit=Mock(), rollback=Mock(), close=Mock())
    pair_operator.runtime.db._conn = raw
    case.factory.side_effect = None
    case.factory.return_value = pair_operator.runtime.db if borrowed == "db" else raw
    report = invoke(case, operation)
    assert report["state"] == ("PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY" if operation == "inspect" else "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY")
    raw.commit.assert_not_called()
    raw.rollback.assert_not_called()
    raw.close.assert_not_called()
    untouched(pair_operator)


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("denied", [False, True])
def test_arabic_static_unchained_failure_messages(pair_operator, certificates, monkeypatch, operation, denied):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(access, "_", lambda message: entries[message])
    if denied:
        pair_operator.denied.add(("Sales Invoice", "INV-TEST"))
    else:
        case.keys.side_effect = RuntimeError("PRIVATE key provider")
    with pytest.raises(PermissionDenied if denied else InspectionFailed) as error:
        invoke(case, operation)
    assert str(error.value) == entries[access.DENIED_MESSAGE if denied else access.FAILED_MESSAGE]
    assert error.value.__context__ is None


def test_protected_nonpickleable_inputs_and_no_runtime_endpoint(pair_operator, certificates, monkeypatch):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    for value in (case.binding, case.keys.return_value, case.service):
        assert "INV-TEST" not in repr(value)
        with pytest.raises(ValueError):
            pickle.dumps(value)
    source = inspect.getsource(access)
    for forbidden in ("@frappe.whitelist", "import requests", "get_password(", "CREATE TABLE", ".seal(", ".save(", ".db_set("):
        assert forbidden not in source
    for operation in ("inspect", "persist"):
        assert set(inspect.signature(getattr(access.SavedPrimaryReconciliationService, operation)).parameters) == {
            "self", "invoice_name", "request", "sealed", "doctype"}


@pytest.mark.parametrize("field,value", [("storage_namespace", "50000000-0000-4000-8000-000000000001"),
    ("candidate_sha256", "0" * 64), ("attempt_id", "50000000-0000-4000-8000-000000000001"),
    ("predecessor_sha256", "0" * 64), ("receipt_sha256", "0" * 64), ("key_id", "OTHER-KEY"),
    ("nonce", b"N" * 12), ("ciphertext", b"C" * 17)])
def test_lookup_fingerprint_binds_every_original_envelope_field(pair_operator, certificates, monkeypatch, field, value):
    case = scenario(pair_operator, certificates[0], monkeypatch)
    changed = replace(case.sealed, **{field: value})
    assert access.sealed_envelope_sha256(changed) != case.binding.envelope_sha256
    case.keys.assert_not_called()  # Fingerprinting does not decrypt/discover a key.
