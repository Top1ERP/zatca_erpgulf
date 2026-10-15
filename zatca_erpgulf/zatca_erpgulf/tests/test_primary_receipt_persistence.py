"""Exact local receipt/redelivery with synthetic contracts and owned SQL doubles."""

import ast
import inspect
import json
import pickle
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_receipt_persistence as persistence
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal, append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository import NAMESPACE


@pytest.fixture(scope="module")
def prepared(certificates):
    return candidate(certificates[0])


def retained(prepared, *, namespace=NAMESPACE, unknown=False, status=200, body=b' {"observation":"synthetic only"}\n'):
    before = append_dispatch_event(DispatchJournal(prepared), event(prepared))
    if unknown:
        before = append_dispatch_event(before, event(prepared, "TRANSPORT_UNKNOWN", 2))
    response = event(prepared, "HTTP_RESPONSE", len(before.events) + 1, http_status=status, response_bytes=body)
    return persistence.RetainedPrimaryReceipt(namespace, before, response)


class Scenario:
    """Transaction simulator only; real repository SQL is checked separately."""

    def __init__(self, monkeypatch, receipt, *, fault=None, already=False):
        self.receipt, self.fault = receipt, fault
        self.after = append_dispatch_event(receipt.before, receipt.response_event)
        self.saved = self.after if already else receipt.before
        self.events, self.connections = [], []
        self.factory = Mock(side_effect=self.acquire)
        monkeypatch.setattr(persistence, "MariaDBJournalRepository", self.repository)

    def acquire(self):
        if self.fault == "factory":
            raise RuntimeError("PRIVATE failed factory")
        connection = SimpleNamespace(cursor=Mock(), commit=Mock(), rollback=Mock(), close=Mock(),
            pending=self.saved, closed=False)
        def commit():
            self.events.append("commit")
            if self.fault == "commit_before":
                raise RuntimeError("PRIVATE commit before persistence")
            self.saved = connection.pending
            if self.fault == "commit_after":
                raise RuntimeError("PRIVATE lost commit acknowledgement")
        def rollback():
            self.events.append("rollback")
            connection.pending = self.saved
            if self.fault == "rollback":
                raise RuntimeError("PRIVATE failed rollback")
        def close():
            self.events.append("close")
            connection.closed = True
            if self.fault == "close":
                raise RuntimeError("PRIVATE failed close")
        connection.commit.side_effect, connection.rollback.side_effect, connection.close.side_effect = commit, rollback, close
        self.connections.append(connection)
        return connection

    def repository(self, connection, namespace):
        assert namespace == self.receipt.storage_namespace
        def load(key):
            self.events.append("load")
            assert key == self.receipt.before.candidate.key_sha256
            if self.fault in ("sql", "rollback"):
                raise RuntimeError("PRIVATE SQL contents")
            if self.fault == "interrupt":
                raise KeyboardInterrupt("Synthetic interruption")
            if self.fault == "conflict":
                return DispatchJournal(self.receipt.before.candidate)
            return connection.pending
        def append(key, supplied, *, expected_journal_sha256):
            self.events.append("append")
            assert supplied is self.receipt.response_event and expected_journal_sha256 == self.receipt.before.journal_sha256
            assert key == self.receipt.before.candidate.key_sha256
            connection.pending = self.after
            if self.fault == "append":
                raise RuntimeError("PRIVATE SQL append")
            if self.fault == "wrong_result":
                return self.receipt.before
            return self.after
        return SimpleNamespace(load=load, append=append)

    def service(self, **changes):
        values = dict(connection_factory=self.factory)
        values.update(changes)
        return persistence.PrimaryReceiptPersistence(self.receipt.storage_namespace, **values)


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("status", [200, 202, 303, 400, 401, 403, 406, 409, 500])
@pytest.mark.parametrize("already", [False, True])
def test_one_owned_transaction_preserves_exact_observation_and_never_authorizes_replay(prepared, monkeypatch, unknown, status, already):
    receipt = retained(prepared, unknown=unknown, status=status)
    scenario = Scenario(monkeypatch, receipt, already=already)
    result = scenario.service().persist(receipt)
    assert result.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and result.receipt is receipt
    assert scenario.saved == scenario.after and scenario.saved.events[-1] is receipt.response_event
    assert scenario.events == ["load", "append", "commit", "close"]
    assert scenario.factory.call_count == 1 and scenario.connections[0].closed
    report = result.diagnostic_projection()
    assert report["local_transaction_completed"] is True
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "synthetic only" not in json.dumps(report)


@pytest.mark.parametrize("fault", ["factory", "sql", "append", "conflict", "wrong_result", "commit_before", "commit_after", "close", "rollback"])
def test_unknown_storage_outcome_retains_exact_input_for_explicit_local_redelivery(prepared, monkeypatch, fault):
    receipt = retained(prepared)
    scenario = Scenario(monkeypatch, receipt, fault=fault)
    result = scenario.service().persist(receipt)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and result.receipt is receipt
    assert scenario.factory.call_count == 1
    assert (scenario.saved == scenario.after) is (fault in ("commit_after", "close"))
    assert "PRIVATE" not in repr(result) and "PRIVATE" not in json.dumps(result.diagnostic_projection())
    if fault != "factory":
        scenario.connections[0].rollback.assert_called_once()
        scenario.connections[0].close.assert_called_once()
    scenario.fault = None
    recovered = scenario.service().persist(result.receipt)
    assert recovered.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and recovered.receipt is receipt
    assert scenario.factory.call_count == 2 and scenario.saved == scenario.after


@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.parametrize("guard_result", [False, None, 1, "yes", "raise"])
def test_source_guard_must_return_literal_true_before_and_after_append(prepared, monkeypatch, stage, guard_result):
    receipt = retained(prepared)
    scenario = Scenario(monkeypatch, receipt)
    def reject(*args):
        if guard_result == "raise":
            raise RuntimeError("PRIVATE source/permission")
        return guard_result
    guard = Mock(side_effect=reject if stage == 1 else [True, RuntimeError("PRIVATE guard")
        if guard_result == "raise" else guard_result])
    result = scenario.service(source_guard=guard).persist(receipt)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and scenario.saved == receipt.before
    assert scenario.factory.call_count == 1 and guard.call_count == stage
    assert ("append" in scenario.events) is (stage == 2)
    scenario.connections[0].commit.assert_not_called()
    scenario.connections[0].rollback.assert_called_once()
    scenario.connections[0].close.assert_called_once()


def test_source_guard_uses_the_same_owned_transaction_and_exact_receipt(prepared, monkeypatch):
    receipt = retained(prepared)
    scenario = Scenario(monkeypatch, receipt)
    guard = Mock(return_value=True)
    assert scenario.service(source_guard=guard).persist(receipt).state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY"
    assert all(call.args == (scenario.connections[0], receipt) for call in guard.call_args_list)
    assert guard.call_count == 2


@pytest.mark.parametrize("mutation", ["namespace", "before_state", "before_hash", "before_events", "event_body", "event_hash", "event_type", "candidate_hash"])
def test_tampered_frozen_inputs_are_rebuilt_before_acquiring_sql(prepared, monkeypatch, mutation):
    receipt = retained(prepared)
    # Construct fresh contracts before bypassing frozen assignment for negatives.
    receipt = persistence.RetainedPrimaryReceipt(receipt.storage_namespace,
        replace(receipt.before, candidate=replace(receipt.before.candidate)), replace(receipt.response_event))
    if mutation == "namespace":
        object.__setattr__(receipt, "storage_namespace", "PRIVATE")
    elif mutation in ("before_state", "before_hash", "before_events"):
        name, value = {"before_state": ("state", "HTTP_RESPONSE_OBSERVED"),
            "before_hash": ("journal_sha256", "0" * 64), "before_events": ("events", [receipt.before.events[0]])}[mutation]
        object.__setattr__(receipt.before, name, value)
    elif mutation in ("event_body", "event_hash", "event_type"):
        name, value = {"event_body": ("response_bytes", b"PRIVATE changed bytes"),
            "event_hash": ("response_sha256", "0" * 64), "event_type": ("kind", "TRANSPORT_UNKNOWN")}[mutation]
        object.__setattr__(receipt.response_event, name, value)
    else:
        object.__setattr__(receipt.before.candidate, "key_sha256", "0" * 64)
    factory = Mock()
    service = persistence.PrimaryReceiptPersistence(NAMESPACE, connection_factory=factory)
    with pytest.raises(persistence.PrimaryReceiptError, match="^primary_receipt_input$") as error:
        service.persist(receipt)
    assert error.value.__context__ is None
    factory.assert_not_called()


@pytest.mark.parametrize("invalid", [None, {}, "PRIVATE", True])
def test_wrong_input_type_never_acquires_sql(invalid):
    factory = Mock()
    service = persistence.PrimaryReceiptPersistence(NAMESPACE, connection_factory=factory)
    with pytest.raises(persistence.PrimaryReceiptError, match="^primary_receipt_input$"):
        service.persist(invalid)
    factory.assert_not_called()


def test_scope_mismatch_never_acquires_sql(prepared):
    factory = Mock()
    service = persistence.PrimaryReceiptPersistence("50000000-0000-4000-8000-000000000001", connection_factory=factory)
    with pytest.raises(persistence.PrimaryReceiptError, match="^primary_receipt_scope$"):
        service.persist(retained(prepared))
    factory.assert_not_called()


@pytest.mark.parametrize("namespace,factory,guard", [(None, lambda: None, None),
    (NAMESPACE.upper(), lambda: None, None), (NAMESPACE, None, None), (NAMESPACE, lambda: None, True)])
def test_invalid_dependencies_are_static(namespace, factory, guard):
    with pytest.raises(persistence.PrimaryReceiptError, match="^primary_receipt_dependencies$") as error:
        persistence.PrimaryReceiptPersistence(namespace, connection_factory=factory, source_guard=guard)
    assert error.value.__context__ is None


@pytest.mark.parametrize("stage", ["empty", "terminal", "wrong_attempt", "not_response", "event_id_conflict", "sequence"])
def test_retained_input_requires_exact_started_attempt_and_next_response(prepared, stage):
    receipt = retained(prepared)
    before, response = receipt.before, receipt.response_event
    if stage == "empty":
        before = DispatchJournal(prepared)
    elif stage == "terminal":
        before = append_dispatch_event(before, response)
    elif stage == "wrong_attempt":
        response = replace(response, attempt_id="50000000-0000-4000-8000-000000000001")
    elif stage == "not_response":
        response = event(prepared, "TRANSPORT_UNKNOWN", 2)
    elif stage == "event_id_conflict":
        response = replace(response, event_id=before.events[0].event_id)
    else:
        response = replace(response, sequence=3)
    with pytest.raises(persistence.PrimaryReceiptError, match="^primary_receipt_input$"):
        persistence.RetainedPrimaryReceipt(NAMESPACE, before, response)


def test_interruption_propagates_after_owned_cleanup_and_input_is_still_available(prepared, monkeypatch):
    receipt = retained(prepared)
    scenario = Scenario(monkeypatch, receipt, fault="interrupt")
    with pytest.raises(KeyboardInterrupt):
        scenario.service().persist(receipt)
    scenario.connections[0].rollback.assert_called_once()
    scenario.connections[0].close.assert_called_once()
    assert scenario.saved == receipt.before


def test_protected_inputs_results_and_service_are_frozen_redacted_and_not_pickleable(prepared, monkeypatch):
    receipt = retained(prepared)
    scenario = Scenario(monkeypatch, receipt)
    result = scenario.service().persist(receipt)
    for value in (receipt, result, scenario.service()):
        assert "synthetic only" not in repr(value) and "TEST" not in repr(value)
        with pytest.raises(persistence.PrimaryReceiptError, match="primary_receipt_not_pickleable"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        receipt.response_event = None
    with pytest.raises(FrozenInstanceError):
        result.state = "SUCCESS"


def test_no_runtime_activation_transport_clock_connection_discovery_or_start_creation():
    source = inspect.getsource(persistence)
    tree = ast.parse(source)
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls.intersection({"post", "connect", "put", "get_doc", "save", "db_set", "set_value", "now", "utcnow"})
    assert "whitelist" not in source and "requests" not in source
