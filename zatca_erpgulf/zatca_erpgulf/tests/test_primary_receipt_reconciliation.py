"""Exact LOCAL pair inspection/persistence; synthetic ownership and no HTTP."""

from dataclasses import replace
import inspect
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_capture as capture
from zatca_erpgulf.zatca_erpgulf import primary_receipt_reconciliation as pair
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository import NAMESPACE, prepared
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_capture import Scenario


MODES = {
    "missing": "PAIR_MISSING_OBSERVATION_NO_REPLAY",
    "matched": "PAIR_MATCHED_OBSERVATION_NO_REPLAY",
    "custody-only": "CUSTODY_ONLY_REVIEW_NO_REPLAY",
    "journal-only": "JOURNAL_ONLY_REVIEW_NO_REPLAY",
    "different-seal": "PAIR_CONFLICT_REVIEW_NO_REPLAY",
    "different-journal": "PAIR_CONFLICT_REVIEW_NO_REPLAY",
    "unknown": "PAIR_CONFLICT_REVIEW_NO_REPLAY",
}


def configure(case, monkeypatch, mode):
    sealed, receipt = case.captured.sealed, case.captured.receipt
    after = pair._validate_retained(receipt)
    case.core.journal = after if mode in ("matched", "journal-only") else receipt.before
    case.core.sealed = sealed if mode in ("matched", "custody-only") else None
    if mode == "different-seal":
        case.core.sealed = case.core.cipher.seal(receipt, key_id=sealed.key_id)
        assert case.core.sealed != sealed
    elif mode == "different-journal":
        case.core.journal = append_dispatch_event(receipt.before, replace(receipt.response_event, response_bytes=b"OTHER PRIVATE bytes"))
    elif mode == "unknown":
        case.core.journal = append_dispatch_event(receipt.before, event(receipt.before.candidate, "TRANSPORT_UNKNOWN", 2))
    case.before_state = (case.core.journal, case.core.sealed)
    case.core.fault = None
    def factory():
        owned = case.core.factory()
        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, statement, parameters):
                assert statement.startswith("SELECT candidate_sha256 FROM zatca_primary_receipt_custody_v1 ")
                assert parameters == (NAMESPACE, sealed.candidate_sha256, sealed.attempt_id)
            def fetchone(self):
                return None if owned.pending[3] is None else (sealed.candidate_sha256,)
        owned.cursor.side_effect = Cursor
        return owned
    case.factory = Mock(side_effect=factory)
    case.guard = Mock(return_value=True)
    case.service = pair.PrimaryReceiptReconciliation(NAMESPACE, case.core.cipher,
        connection_factory=case.factory, source_guard=case.guard)
    for name in ("_RequestBinding", "MariaDBJournalRepository"):
        monkeypatch.setattr(pair, name, getattr(capture, name))
    def custody_repository(connection, namespace, cipher):
        stages = capture.MariaDBPrimaryReceiptCustodyRepository(connection, namespace, cipher)
        def load(candidate_sha256, attempt_id):
            stored = connection.pending[3]
            assert (candidate_sha256, attempt_id) == (sealed.candidate_sha256, sealed.attempt_id)
            cipher.open(stored)  # Preserve the actual repository's authentication contract.
            return stored
        return SimpleNamespace(stage=stages.stage, load=load)
    monkeypatch.setattr(pair, "MariaDBPrimaryReceiptCustodyRepository", custody_repository)
    # No reconciliation operation may replace the original cryptographic envelope.
    monkeypatch.setattr(case.core.cipher, "seal", Mock(side_effect=AssertionError("Must not reseal")))
    return case


def scenario(monkeypatch, selected, mode="missing", *, response=None):
    core = Scenario(monkeypatch, selected, fault=(2, "commit-before"))
    if response is not None:
        original = core.observer.side_effect
        core.observer.side_effect = lambda request: replace(original(request), **response)
    captured = core.run()
    assert captured.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    return configure(SimpleNamespace(core=core, captured=captured), monkeypatch, mode)


def invoke(case, operation):
    return getattr(case.service, operation)(case.captured.request, case.captured.sealed)


@pytest.mark.parametrize("status", [200, 202, 400, 401, 406, 500])
@pytest.mark.parametrize("body", [b"", b"\x00\xff PRIVATE non-JSON response\n"])
def test_local_pair_keeps_http_errors_and_empty_binary_bodies_without_acceptance_inference(prepared, monkeypatch, status, body):
    case = scenario(monkeypatch, prepared, response={"http_status": status, "body": body})
    result = invoke(case, "persist")
    assert result.state == "PAIR_STORED_OBSERVATION_NO_REPLAY"
    assert invoke(case, "inspect").state == "PAIR_MATCHED_OBSERVATION_NO_REPLAY"
    receipt = case.core.cipher.open(result.sealed)
    assert receipt.response_event.http_status == status and receipt.response_event.response_bytes == body
    assert all(value is False for key, value in result.diagnostic_projection().items() if key.endswith(("_verified", "_authorized")))
    case.core.observer.assert_called_once()
    case.core.cipher.seal.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("code", ["388", "381", "383", "386"])
@pytest.mark.parametrize("operation", ["inspect", "persist"])
def test_pair_missing_exact_response_can_only_be_stored_locally_without_new_observer(certificates, monkeypatch,
    doctype, indicator, code, operation):
    selected = candidate(certificates[0], selected_scope=scope(doctype=doctype), indicator=indicator, code=code)
    case = scenario(monkeypatch, selected)
    result = invoke(case, operation)
    assert result.state == (MODES["missing"] if operation == "inspect" else "PAIR_STORED_OBSERVATION_NO_REPLAY")
    assert result.request == case.captured.request and result.sealed is case.captured.sealed
    if operation == "inspect":
        assert (case.core.journal, case.core.sealed) == case.before_state
        case.core.connections[-1].commit.assert_not_called()
    else:
        assert case.core.journal == pair._validate_retained(case.captured.receipt)
        assert case.core.sealed is case.captured.sealed
        case.core.connections[-1].commit.assert_called_once()
    case.core.connections[-1].rollback.assert_called_once()
    case.core.connections[-1].close.assert_called_once()
    assert case.guard.call_count == 2 and case.factory.call_count == 1
    case.core.observer.assert_called_once()  # Initial synthetic capture ONLY.
    case.core.cipher.seal.assert_not_called()
    report = result.diagnostic_projection()
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "synthetic" not in json.dumps(report) and "INV-TEST" not in repr(result)


@pytest.mark.parametrize("mode", list(MODES))
@pytest.mark.parametrize("operation", ["inspect", "persist"])
def test_identical_pair_is_observed_partial_conflicting_pairs_never_repaired(prepared, monkeypatch, mode, operation):
    case = scenario(monkeypatch, prepared, mode)
    result = invoke(case, operation)
    expected = MODES[mode]
    if operation == "persist" and mode in ("missing", "matched"):
        expected = "PAIR_STORED_OBSERVATION_NO_REPLAY" if mode == "missing" else "PAIR_ALREADY_STORED_OBSERVATION_NO_REPLAY"
    assert result.state == expected
    if operation == "inspect" or mode != "missing":
        assert (case.core.journal, case.core.sealed) == case.before_state
    assert result.sealed is case.captured.sealed
    case.core.observer.assert_called_once()
    case.core.cipher.seal.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("fault", ["factory", "binding", "append", "commit-before", "commit-after", "close", "rollback"])
def test_uncertain_work_and_cleanup_preserve_original_inputs_without_loop(prepared, monkeypatch, operation, fault):
    case = scenario(monkeypatch, prepared)
    if fault == "factory":
        case.factory.side_effect = RuntimeError("PRIVATE acquisition")
    elif fault == "rollback":
        original = case.factory.side_effect
        def acquire():
            owned = original()
            rollback = owned.rollback.side_effect
            def failed():
                rollback()
                raise RuntimeError("PRIVATE rollback acknowledgment")
            owned.rollback.side_effect = failed
            return owned
        case.factory.side_effect = acquire
    else:
        case.core.fault = (3, fault)
    result = invoke(case, operation)
    # Inspect has no append or commit to fail, and must NEVER call them.
    irrelevant = operation == "inspect" and fault in ("append", "commit-before", "commit-after")
    expected = MODES["missing"] if irrelevant else (
        "PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY" if operation == "inspect" else "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY")
    assert result.state == expected and result.sealed is case.captured.sealed
    assert case.factory.call_count == 1
    if fault != "factory":
        assert case.core.connections[-1].closed
        if operation == "inspect":
            case.core.connections[-1].commit.assert_not_called()
    if operation == "inspect" or fault not in ("commit-after", "close", "rollback"):
        assert (case.core.journal, case.core.sealed) == case.before_state
    case.core.observer.assert_called_once()
    case.core.cipher.seal.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("step", [0, 1])
@pytest.mark.parametrize("denied", [None, False, 1, "yes", "raise"])
def test_literal_source_guard_on_both_sides_rolls_back_all_pair_changes(prepared, monkeypatch, operation, step, denied):
    case = scenario(monkeypatch, prepared)
    rejection = RuntimeError("PRIVATE ACL") if denied == "raise" else denied
    case.guard.side_effect = [True, rejection] if step else [rejection]
    result = invoke(case, operation)
    assert result.state == ("PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY" if operation == "inspect" else "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY")
    assert (case.core.journal, case.core.sealed) == case.before_state
    case.core.connections[-1].commit.assert_not_called()
    assert case.core.connections[-1].closed and result.sealed is case.captured.sealed


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("stage", ["guard", "rollback", "close"])
def test_interruptions_always_attempt_both_owned_cleanup_operations(prepared, monkeypatch, operation, stage):
    case = scenario(monkeypatch, prepared)
    if stage == "guard":
        case.guard.side_effect = KeyboardInterrupt("PRIVATE guard interruption")
    else:
        original = case.factory.side_effect
        def acquire():
            owned = original()
            action = getattr(owned, stage).side_effect
            def interrupted():
                action()
                raise KeyboardInterrupt("PRIVATE cleanup interruption")
            getattr(owned, stage).side_effect = interrupted
            return owned
        case.factory.side_effect = acquire
    with pytest.raises(KeyboardInterrupt):
        invoke(case, operation)
    owned = case.core.connections[-1]
    owned.rollback.assert_called_once()
    owned.close.assert_called_once()
    assert owned.closed
    case.core.observer.assert_called_once()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("wrong", ["request", "type", "scope", "attempt", "ciphertext", "unknown-predecessor", "wrong-key"])
def test_wrong_protected_input_fails_before_factory(prepared, monkeypatch, operation, wrong):
    case = scenario(monkeypatch, prepared)
    request, sealed = case.captured.request, case.captured.sealed
    if wrong == "request":
        request = None
    elif wrong == "type":
        sealed = {}
    elif wrong == "scope":
        sealed = replace(sealed, storage_namespace="70000000-0000-4000-8000-000000000001")
    elif wrong == "attempt":
        sealed = replace(sealed, attempt_id="70000000-0000-4000-8000-000000000001")
    elif wrong == "ciphertext":
        sealed = replace(sealed, ciphertext=sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1]))
    elif wrong == "unknown-predecessor":
        from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_persistence import retained
        from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher
        cipher = PrimaryReceiptCustodyCipher({"other": b"O" * 32})
        sealed = cipher.seal(retained(prepared, unknown=True), key_id="other")
        case.service = pair.PrimaryReceiptReconciliation(NAMESPACE, cipher, connection_factory=case.factory, source_guard=case.guard)
    else:
        from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher
        cipher = PrimaryReceiptCustodyCipher({sealed.key_id: b"Z" * 32})
        case.service = pair.PrimaryReceiptReconciliation(NAMESPACE, cipher, connection_factory=case.factory, source_guard=case.guard)
    with pytest.raises(pair.PrimaryReconciliationError, match="primary_pair_input") as error:
        getattr(case.service, operation)(request, sealed)
    assert error.value.__context__ is None
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["inspect", "persist"])
@pytest.mark.parametrize("malformed", [[], ("wrong",), ("extra", "column")])
def test_bad_optional_presence_row_never_becomes_missing_or_repair(prepared, monkeypatch, operation, malformed):
    case = scenario(monkeypatch, prepared)
    original = case.factory.side_effect
    def acquire():
        owned = original()
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchone.return_value = malformed
        owned.cursor.side_effect = None
        owned.cursor.return_value = cursor
        return owned
    case.factory.side_effect = acquire
    result = invoke(case, operation)
    assert result.state == ("PAIR_INSPECTION_UNCONFIRMED_NO_REPLAY" if operation == "inspect" else "PAIR_PERSISTENCE_UNCONFIRMED_NO_REPLAY")
    assert (case.core.journal, case.core.sealed) == case.before_state
    case.core.connections[-1].commit.assert_not_called()


def test_no_discovery_export_transport_resealing_or_runtime_registration(prepared, monkeypatch):
    case = scenario(monkeypatch, prepared)
    result = invoke(case, "inspect")
    for value in (result, case.service):
        assert "INV-TEST" not in repr(value) and "synthetic" not in repr(value)
        with pytest.raises(ValueError, match="not_pickleable"):
            pickle.dumps(value)
    source = inspect.getsource(pair)
    for forbidden in ("import frappe", "import requests", "whitelist", ".seal(", ".reserve(", "CREATE TABLE", ".save(", ".db_set("):
        assert forbidden not in source
    assert set(inspect.signature(pair.PrimaryReceiptReconciliation.__init__).parameters) == {
        "self", "namespace", "cipher", "connection_factory", "source_guard"}


@pytest.mark.parametrize("wrong", ["namespace", "cipher", "factory", "guard"])
def test_dependencies_must_be_explicit_and_typed(prepared, monkeypatch, wrong):
    case = scenario(monkeypatch, prepared)
    values = dict(namespace=NAMESPACE, cipher=case.core.cipher, connection_factory=case.factory, source_guard=case.guard)
    values[{"namespace": "namespace", "cipher": "cipher", "factory": "connection_factory", "guard": "source_guard"}[wrong]] = None
    with pytest.raises(pair.PrimaryReconciliationError, match="primary_pair_dependencies") as error:
        pair.PrimaryReceiptReconciliation(**values)
    assert error.value.__context__ is None
