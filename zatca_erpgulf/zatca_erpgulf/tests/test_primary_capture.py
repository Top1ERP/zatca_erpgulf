"""Synthetic observer/transaction capture; no site, HTTP or real credentials."""

import base64
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib
import inspect
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_capture as capture
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal, append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import NOW, start
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository import NAMESPACE, prepared
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope


def observed(request, **changes):
    values = dict(request_sha256=request.body_sha256, attempt_id=request.started.events[0].attempt_id,
        event_id="80000000-0000-4000-8000-000000000002", received_at=request.started.events[0].occurred_at + timedelta(seconds=1),
        http_status=200, body=b' {"synthetic":"not authority evidence"}\n')
    values.update(changes)
    return capture.PrimaryObservedResponse(**values)


class Scenario:
    """Owned SQL model only; actual repository/SQL behavior is checked separately."""

    def __init__(self, monkeypatch, prepared, *, fault=None, namespace=NAMESPACE):
        self.namespace = namespace
        self.request = capture.PrimaryCaptureRequest(start(prepared))
        self.journal, self.hold, self.binding, self.sealed = DispatchJournal(prepared), None, None, None
        self.connections, self.events, self.fault = [], [], fault
        def factory():
            index = len(self.connections)
            if self.fault == (index, "factory"):
                raise RuntimeError("PRIVATE acquisition")
            connection = SimpleNamespace(index=index, closed=False, cursor=Mock(), pending=[self.journal, self.hold, self.binding, self.sealed])
            def commit():
                self.events.append(("commit", index))
                if self.fault == (index, "commit-before"):
                    raise RuntimeError("PRIVATE before commit")
                self.journal, self.hold, self.binding, self.sealed = connection.pending
                if self.fault == (index, "commit-after"):
                    raise RuntimeError("PRIVATE commit acknowledgment lost")
            def close():
                connection.closed = True
                self.events.append(("close", index))
                if self.fault == (index, "close"):
                    raise RuntimeError("PRIVATE close")
            def rollback():
                connection.pending = [self.journal, self.hold, self.binding, self.sealed]
                self.events.append(("rollback", index))
            connection.commit, connection.close, connection.rollback = Mock(side_effect=commit), Mock(side_effect=close), Mock(side_effect=rollback)
            self.connections.append(connection)
            return connection
        self.factory = Mock(side_effect=factory)
        def hold_repository(connection, namespace):
            assert namespace == self.namespace
            expected = capture._declaration(namespace, self.request.started)
            def reserve(started):
                if connection.pending[0] != DispatchJournal(prepared) or connection.pending[1] is not None:
                    raise RuntimeError("Synthetic spent reservation")
                connection.pending[0:2] = [started, expected]
                return expected
            def load(started):
                if connection.pending[1] != expected:
                    raise RuntimeError("Synthetic missing hold")
                return expected
            return SimpleNamespace(reserve=Mock(side_effect=reserve), load=Mock(side_effect=load))
        def binding_repository(connection, namespace):
            def check(request, *, insert=False):
                if insert:
                    if connection.pending[2] is not None:
                        raise RuntimeError("Synthetic spent binding")
                    connection.pending[2] = request.body_sha256
                if connection.pending[2] != request.body_sha256:
                    raise RuntimeError("Synthetic wrong request binding")
                if self.fault == (connection.index, "binding"):
                    raise RuntimeError("PRIVATE binding failure")
            return SimpleNamespace(check=check)
        def journal_repository(connection, namespace):
            def append(key, supplied, *, expected_journal_sha256):
                before = connection.pending[0]
                after = append_dispatch_event(before, supplied)
                if before != after and before.journal_sha256 != expected_journal_sha256:
                    raise RuntimeError("Synthetic changed predecessor")
                connection.pending[0] = after
                if self.fault == (connection.index, "append"):
                    raise RuntimeError("PRIVATE journal failure after custody")
                return after
            return SimpleNamespace(load=lambda key: connection.pending[0], append=append)
        def custody_repository(connection, namespace, cipher):
            def stage(sealed):
                if connection.pending[3] not in (None, sealed):
                    raise RuntimeError("Synthetic conflicting custody")
                connection.pending[3] = sealed
                return sealed
            return SimpleNamespace(stage=stage)
        monkeypatch.setattr(capture, "MariaDBPrimaryAttemptHoldRepository", hold_repository)
        monkeypatch.setattr(capture, "_RequestBinding", binding_repository)
        monkeypatch.setattr(capture, "MariaDBJournalRepository", journal_repository)
        monkeypatch.setattr(capture, "MariaDBPrimaryReceiptCustodyRepository", custody_repository)
        self.guard = Mock(return_value=True)
        self.cipher = PrimaryReceiptCustodyCipher({"synthetic-capture": b"P" * 32})
        self.seal = Mock(wraps=self.cipher.seal)
        monkeypatch.setattr(self.cipher, "seal", self.seal)
        def observe(request):
            assert self.connections and all(connection.closed for connection in self.connections)
            assert self.journal == request.started and self.hold is not None and self.binding == request.body_sha256
            assert request == self.request and request is not self.request
            self.events.append(("observer",))
            return observed(request)
        self.observer = Mock(side_effect=observe)
        self.coordinator = capture.PrimaryCaptureCoordinator(namespace, self.cipher, "synthetic-capture",
            connection_factory=self.factory, observe=self.observer, source_guard=self.guard)

    def run(self):
        return self.coordinator.capture(self.request)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("code", ["388", "381", "383", "386"])
@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
def test_exact_three_transaction_capture_uses_one_auth_free_synthetic_observer(certificates, monkeypatch,
    doctype, indicator, code, environment):
    selected = candidate(certificates[0], selected_scope=scope(doctype=doctype, environment=environment), indicator=indicator, code=code)
    case = Scenario(monkeypatch, selected)
    result = case.run()
    assert result.state == "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY"
    assert case.events == [("commit", 0), ("close", 0), ("commit", 1), ("close", 1), ("observer",), ("commit", 2), ("close", 2)]
    case.observer.assert_called_once()
    case.seal.assert_called_once()
    assert case.guard.call_count == 6
    assert case.sealed is result.sealed and case.cipher.open(result.sealed) == result.receipt
    assert case.journal == capture._validate_retained(result.receipt)
    body = json.loads(case.request.body)
    assert set(body) == {"invoiceHash", "uuid", "invoice"}
    assert body["uuid"] == selected.artifact.uuid and body["invoiceHash"] == selected.artifact.invoice_digest
    assert base64.b64decode(body["invoice"], validate=True) == selected.xml_bytes
    assert case.request.url == selected.context.route.url and not hasattr(case.request, "headers")
    assert all(value is False for key, value in result.diagnostic_projection().items() if key.endswith(("_verified", "_authorized")))


@pytest.mark.parametrize("status", [200, 202, 303, 400, 401, 403, 406, 409, 500])
@pytest.mark.parametrize("body", [b"", b"\xff\x00PRIVATE\r\n", b'{"reportingStatus":"REPORTED"}'])
def test_status_or_body_never_becomes_acceptance_or_replay(prepared, monkeypatch, status, body):
    case = Scenario(monkeypatch, prepared)
    case.observer.side_effect = lambda request: observed(request, http_status=status, body=body)
    result = case.run()
    assert result.state == "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY"
    assert result.receipt.response_event.response_bytes == body and result.response.body == body
    assert result.diagnostic_projection()["remote_acceptance_verified"] is False
    assert result.diagnostic_projection()["replay_authorized"] is False
    assert "PRIVATE" not in repr(result) and "REPORTED" not in json.dumps(result.diagnostic_projection())


@pytest.mark.parametrize("phase", [0, 1, 2])
@pytest.mark.parametrize("fault", ["factory", "binding", "commit-before", "commit-after", "close"])
def test_transaction_uncertainty_never_repeats_observer_and_retains_exact_receipt(prepared, monkeypatch, phase, fault):
    case = Scenario(monkeypatch, prepared, fault=(phase, fault))
    result = case.run()
    expected = ("RESERVATION_UNCONFIRMED_NO_OBSERVER", "PREFLIGHT_FAILED_NO_OBSERVER", "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY")[phase]
    assert result.state == expected
    assert case.observer.call_count == (1 if phase == 2 else 0)
    assert all(connection.closed for connection in case.connections)
    if phase == 2:
        assert result.sealed is not None and case.cipher.open(result.sealed) == result.receipt
        assert (case.sealed == result.sealed) is (fault in ("commit-after", "close"))
        case.seal.assert_called_once()
    else:
        case.seal.assert_not_called()
    assert "PRIVATE" not in json.dumps(result.diagnostic_projection())


@pytest.mark.parametrize("phase", range(6))
@pytest.mark.parametrize("value", [None, False, 1, "yes", "raise"])
def test_guard_requires_literal_true_at_every_boundary(prepared, monkeypatch, phase, value):
    case = Scenario(monkeypatch, prepared)
    values = [True] * phase + [RuntimeError("PRIVATE source/ACL") if value == "raise" else value]
    case.guard.side_effect = values
    result = case.run()
    expected = ("RESERVATION_UNCONFIRMED_NO_OBSERVER" if phase < 2 else
        "PREFLIGHT_FAILED_NO_OBSERVER" if phase < 4 else "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY")
    assert result.state == expected and case.guard.call_count == phase + 1
    assert case.observer.call_count == (1 if phase >= 4 else 0)
    assert all(connection.closed for connection in case.connections)
    if phase >= 4:
        assert case.sealed is None and case.journal == case.request.started


@pytest.mark.parametrize("cause", [TimeoutError, RuntimeError, ValueError])
def test_observer_failure_keeps_hold_without_inventing_unknown_event_or_retry(prepared, monkeypatch, cause):
    case = Scenario(monkeypatch, prepared)
    case.observer.side_effect = cause("PRIVATE observer error")
    result = case.run()
    assert result.state == "OBSERVER_OUTCOME_UNKNOWN_NO_REPLAY" and result.response is None
    assert case.hold is not None and case.journal == case.request.started
    assert len(case.connections) == 2
    case.observer.assert_called_once()
    case.seal.assert_not_called()


@pytest.mark.parametrize("fault", ["request", "attempt", "clock", "event", "type"])
def test_unbound_complete_response_cannot_become_receipt(prepared, monkeypatch, fault):
    case = Scenario(monkeypatch, prepared)
    changes = {"request": {"request_sha256": "0" * 64}, "attempt": {"attempt_id": "50000000-0000-4000-8000-000000000001"},
        "clock": {"received_at": case.request.started.events[0].occurred_at - timedelta(seconds=1)},
        "event": {"event_id": case.request.started.events[0].event_id}}
    case.observer.side_effect = lambda request: {} if fault == "type" else observed(request, **changes[fault])
    result = case.run()
    assert result.state == ("OBSERVER_OUTCOME_UNKNOWN_NO_REPLAY" if fault == "type" else "RESPONSE_UNBOUND_NO_REPLAY")
    assert (result.response is None) is (fault == "type") and result.receipt is None and result.sealed is None
    assert case.hold is not None and len(case.connections) == 2


def test_seal_failure_keeps_exact_timed_response_and_retained_input(prepared, monkeypatch):
    case = Scenario(monkeypatch, prepared)
    case.seal.side_effect = RuntimeError("PRIVATE key store")
    result = case.run()
    assert result.state == "RECEIPT_PREPARATION_UNCONFIRMED_NO_REPLAY"
    assert result.response is not None and result.receipt is not None and result.sealed is None
    assert result.receipt.response_event.response_bytes == result.response.body
    assert case.hold is not None and len(case.connections) == 2


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_interruptions_propagate_after_owned_cleanup_without_releasing_hold(prepared, monkeypatch, phase):
    case = Scenario(monkeypatch, prepared)
    case.guard.side_effect = [True] * (phase * 2) + [KeyboardInterrupt("Synthetic interruption")]
    with pytest.raises(KeyboardInterrupt):
        case.run()
    assert all(connection.closed for connection in case.connections)
    assert case.observer.call_count == (1 if phase == 2 else 0)
    assert (case.hold is not None) is (phase > 0)


def test_second_capture_is_not_resume_or_another_observation(prepared, monkeypatch):
    case = Scenario(monkeypatch, prepared)
    first = case.run()
    assert first.state == "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY"
    second = case.run()
    assert second.state == "RESERVATION_UNCONFIRMED_NO_OBSERVER"
    case.observer.assert_called_once()
    case.seal.assert_called_once()


@pytest.mark.parametrize("changes", [{"request_sha256": "PRIVATE"}, {"attempt_id": None}, {"event_id": "BAD"},
    {"received_at": None}, {"received_at": NOW.replace(tzinfo=None)}, {"http_status": True},
    {"http_status": 199}, {"http_status": 600}, {"body": "PRIVATE"}, {"body": bytearray(b"PRIVATE")},
    {"body": b"X" * (capture.MAX_RESPONSE_BYTES + 1)}, {"request_id": ""}])
def test_response_shape_errors_are_static_and_unchained(prepared, changes):
    request = capture.PrimaryCaptureRequest(start(prepared))
    with pytest.raises(capture.PrimaryCaptureError, match="primary_capture_response") as error:
        observed(request, **changes)
    assert error.value.__context__ is None


@pytest.mark.parametrize("wrong", ["namespace", "cipher", "key", "key-id", "factory", "observer", "guard"])
def test_constructor_requires_explicit_reviewed_dependencies_without_acquisition(prepared, monkeypatch, wrong):
    case = Scenario(monkeypatch, prepared)
    values = dict(namespace=NAMESPACE, cipher=case.cipher, key_id="synthetic-capture", connection_factory=case.factory,
        observe=case.observer, source_guard=case.guard)
    key, value = {"namespace": ("namespace", "PRIVATE"), "cipher": ("cipher", None), "key": ("key_id", "unavailable"),
        "key-id": ("key_id", "bad key"), "factory": ("connection_factory", None),
        "observer": ("observe", None), "guard": ("source_guard", None)}[wrong]
    values[key] = value
    with pytest.raises(capture.PrimaryCaptureError, match="primary_capture_dependencies") as error:
        capture.PrimaryCaptureCoordinator(**values)
    assert error.value.__context__ is None
    case.factory.assert_not_called()
    case.observer.assert_not_called()


@pytest.mark.parametrize("wrong", ["state", "early-state", "request", "response", "receipt", "sealed"])
def test_invalid_result_stages_never_masquerade_as_capture(prepared, monkeypatch, wrong):
    case = Scenario(monkeypatch, prepared)
    result = case.run()
    changes = {"state": {"state": "ACCEPTED"}, "early-state": {"state": "RESERVATION_UNCONFIRMED_NO_OBSERVER"},
        "request": {"request": None}, "response": {"response": replace(result.response, request_sha256="0" * 64)},
        "receipt": {"receipt": None}, "sealed": {"sealed": None}}[wrong]
    with pytest.raises(capture.PrimaryCaptureError, match="primary_capture_result") as error:
        replace(result, **changes)
    assert error.value.__context__ is None


def test_observer_interruption_keeps_spent_hold_without_any_open_sql_or_retry(prepared, monkeypatch):
    case = Scenario(monkeypatch, prepared)
    case.observer.side_effect = KeyboardInterrupt("Synthetic observer interruption")
    with pytest.raises(KeyboardInterrupt):
        case.run()
    assert case.hold is not None and len(case.connections) == 2 and all(connection.closed for connection in case.connections)
    case.observer.assert_called_once()


def test_after_append_error_rolls_back_pending_ciphertext_and_journal_together(prepared, monkeypatch):
    case = Scenario(monkeypatch, prepared, fault=(2, "append"))
    result = case.run()
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    assert result.sealed is not None and case.sealed is None and case.journal == case.request.started
    case.observer.assert_called_once()


@pytest.mark.parametrize("fault", ["body", "hash", "start"])
def test_changed_request_is_rejected_before_owned_acquisition(prepared, monkeypatch, fault):
    case = Scenario(monkeypatch, prepared)
    object.__setattr__(case.request, {"body": "body", "hash": "body_sha256", "start": "started"}[fault],
        {"body": b"PRIVATE", "hash": "0" * 64, "start": DispatchJournal(prepared)}[fault])
    with pytest.raises(capture.PrimaryCaptureError) as error:
        case.run()
    assert error.value.__context__ is None
    case.factory.assert_not_called()
    case.observer.assert_not_called()


def test_result_inputs_and_services_are_hidden_frozen_nonpickleable_and_not_runtime_endpoints(prepared, monkeypatch):
    case = Scenario(monkeypatch, prepared)
    result = case.run()
    for value in (case.request, result, result.response, case.coordinator):
        assert "INV-TEST" not in repr(value) and "authority evidence" not in repr(value)
        with pytest.raises(capture.PrimaryCaptureError, match="not_pickleable"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        case.request.body = b"REPLACE"
    assert case.request.body_sha256 == hashlib.sha256(case.request.body).hexdigest()
    source = inspect.getsource(capture)
    for forbidden in ("import frappe", "import requests", "@frappe.whitelist", "get_password(", "utcnow(", "CREATE TABLE", "DELETE FROM"):
        assert forbidden not in source
