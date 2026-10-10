"""Two-phase collector with synthetic SQL/transport only, never a real send."""

import json
import pickle
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import compliance_capture as capture
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import STEP_CLASSIFICATION
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive import archive_cipher, archive_record
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import requirements, request, response, exchange, csr
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle import cipher, record, NAMESPACE, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import basic
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings as route_settings
from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route


class OwnedFakeTransaction:
    """Tiny owned transactional fake; integration tests use actual private SQL."""

    def __init__(self, context, index):
        self.context, self.index, self.pending, self.row = context, index, {}, None
        self.closed = False
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.execute.side_effect = self.execute
        cursor.fetchone.side_effect = lambda: self.row
        self.cursor = Mock(return_value=cursor)
        self.commit = Mock(side_effect=self._commit)
        self.rollback = Mock(side_effect=self._rollback)
        self.close = Mock(side_effect=self._close)

    def execute(self, sql, values=None):
        assert not self.closed
        if sql == "SELECT @@session.autocommit":
            self.row = (0,)
        elif sql.startswith("SELECT slot_sha256"):
            self.row = record(self.context.bundle)
        elif sql.startswith("INSERT INTO zatca_compliance_archive_v1"):
            key = values[1], values[2]
            old = self.pending.get(key, self.context.rows.get(key))
            if old is not None and "ON DUPLICATE" not in sql:
                raise RuntimeError(1062, "PRIVATE-SECRET duplicate")
            if old is None:
                self.pending[key] = tuple(values[index] for index in (4, 5, 6, 7, 8, 9))
        elif sql.startswith("SELECT version_id"):
            key = values[-2], values[-1]
            self.row = self.pending.get(key, self.context.rows.get(key))
        else:
            raise AssertionError("Unexpected SQL")

    def _commit(self):
        self.context.rows.update(self.pending)
        self.pending.clear()
        self.context.events.append(("commit", self.index))

    def _rollback(self):
        self.pending.clear()
        self.context.events.append(("rollback", self.index))

    def _close(self):
        self.closed = True
        self.context.events.append(("close", self.index))


class Scenario:
    def __init__(self, material, cipher, archive_cipher, *, environment="Production", step="SIMPLIFIED", status=200):
        self.requirements, self.bundle = requirements(material, cipher, environment=environment)
        self.route = resolve_api_route(route_settings(environment), "compliance/invoices")
        self.identity, self.body = str(uuid4()), request(material, step)
        self.rows, self.connections, self.events = {}, [], []
        self.clock = Mock(side_effect=[NOW + timedelta(seconds=1), NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)])
        def acquire():
            database = OwnedFakeTransaction(self, len(self.connections))
            self.connections.append(database)
            return database
        self.factory = Mock(side_effect=acquire)
        def send(prepared):
            assert self.connections and all(connection.closed for connection in self.connections)
            assert all(not connection.pending for connection in self.connections)
            assert (self.identity, 1) in self.rows  # Committed, not only pending.
            assert prepared.body == self.body and prepared.url == self.route.url
            assert prepared.headers()["Authorization"] == "Basic " + basic(material)
            self.events.append(("transport",))
            return capture.ComplianceTransportResponse(status, json.dumps(response(step=step, previous=status == 406)).encode())
        self.transport = Mock(side_effect=send)
        self.coordinator = capture.ComplianceCaptureCoordinator(NAMESPACE, cipher, archive_cipher, "audit-test",
            connection_factory=self.factory, transport=self.transport, clock=self.clock)

    def run(self, **changes):
        values = dict(exchange_id=self.identity, route=self.route, request_bytes=self.body)
        values.update(changes)
        return self.coordinator.capture(self.requirements, **values)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("step", list(STEP_CLASSIFICATION))
@pytest.mark.parametrize("status", [200, 202, 406, 401])
def test_two_owned_transactions_capture_exact_material_once_without_authority(materials, cipher, archive_cipher, environment, step, status):
    scenario = Scenario(materials[0], cipher, archive_cipher, environment=environment, step=step, status=status)
    result = scenario.run()
    assert result.state == "RECEIPT_CAPTURED_OBSERVATION"
    scenario.transport.assert_called_once()
    assert scenario.events == [("commit", 0), ("close", 0), ("transport",), ("commit", 1), ("close", 1)]
    assert scenario.rows[scenario.identity, 1] == archive_record(result.start_envelope)
    assert scenario.rows[scenario.identity, 2] == archive_record(result.receipt_envelope)
    assert archive_cipher.open(result.receipt_envelope).request_bytes == scenario.body
    assert result.observation.step == step
    assert result.observation.outcome == ({200: "PASS_MATCHED_OBSERVATION", 202: "PASS_MATCHED_OBSERVATION",
        406: "ALREADY_COMPLETED_MATCHED_OBSERVATION", 401: "AUTHORIZATION_FAILED"}[status])
    public = json.dumps(result.diagnostic_projection()) + repr(result) + repr(scenario.coordinator) + repr(scenario.transport.call_args.args[0])
    for private in (materials[0].pem, materials[0].text, basic(materials[0]), "PRIVATE-CSR-SUBJECT", "gw-fatoora", scenario.body.decode()):
        assert private not in public
    assert all(value is False for key, value in result.diagnostic_projection().items() if key.endswith(("_verified", "_authorized")))


@pytest.mark.parametrize("status", [200, 401, 500])
def test_empty_body_is_committed_not_fabricated_into_success(materials, cipher, archive_cipher, status):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    scenario.transport.side_effect = None
    scenario.transport.return_value = capture.ComplianceTransportResponse(status, b"")
    result = scenario.run()
    assert result.state == "RECEIPT_CAPTURED_OBSERVATION"
    assert archive_cipher.open(result.receipt_envelope).response_bytes == b""
    assert result.observation.outcome not in ("PASS_MATCHED_OBSERVATION", "ALREADY_COMPLETED_MATCHED_OBSERVATION")


@pytest.mark.parametrize("fault", ["factory", "sql", "commit_before", "commit_after", "close"])
def test_first_transaction_failure_or_unknown_commit_never_calls_transport(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    original = scenario.factory.side_effect
    if fault == "factory":
        scenario.factory.side_effect = RuntimeError("PRIVATE-SECRET acquire")
    else:
        def acquire():
            connection = original()
            def fail():
                if fault == "commit_after":
                    connection._commit()
                raise RuntimeError("PRIVATE-SECRET uncertain outcome")
            if fault == "sql":
                connection.cursor.side_effect = RuntimeError("PRIVATE-SECRET driver")
            elif fault == "close":
                connection.close.side_effect = fail
            else:
                connection.commit.side_effect = fail
            return connection
        scenario.factory.side_effect = acquire
    result = scenario.run()
    assert result.state == "PREPARATION_UNCONFIRMED_NO_SEND"
    scenario.transport.assert_not_called()
    assert "PRIVATE-SECRET" not in json.dumps(result.diagnostic_projection())
    assert ((scenario.identity, 1) in scenario.rows) is (fault in ("commit_after", "close"))


@pytest.mark.parametrize("existing", ["reserved", "receipt"])
def test_reserved_identity_is_never_redispatched_even_by_new_coordinator(materials, cipher, archive_cipher, existing):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    first = scenario.run()
    if existing == "reserved":
        scenario.rows.pop((scenario.identity, 2))
    scenario.clock.side_effect = None
    scenario.clock.return_value = NOW + timedelta(seconds=3)
    result = scenario.run()
    assert result.state == "PREPARATION_UNCONFIRMED_NO_SEND"
    assert scenario.transport.call_count == 1
    assert scenario.rows[scenario.identity, 1] == archive_record(first.start_envelope)
    scenario.connections[-1].rollback.assert_called_once()
    scenario.connections[-1].close.assert_called_once()


@pytest.mark.parametrize("fault", ["exception", "wrong_type", "clock_failure", "clock_backwards"])
def test_transport_unknown_never_resends_or_opens_receipt_transaction(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    if fault == "exception":
        scenario.transport.side_effect = RuntimeError("PRIVATE-SECRET timeout with auth")
    elif fault == "wrong_type":
        scenario.transport.side_effect = None
        scenario.transport.return_value = {"status": 200, "body": "PRIVATE-SECRET"}
    else:
        scenario.clock.side_effect = [NOW + timedelta(seconds=1), NOW + timedelta(seconds=1),
                                     RuntimeError("PRIVATE-SECRET clock") if fault == "clock_failure" else NOW]
    result = scenario.run()
    assert result.state == "TRANSPORT_UNKNOWN_NO_REPLAY"
    assert scenario.transport.call_count == 1 and len(scenario.connections) == 1
    assert list(scenario.rows) == [(scenario.identity, 1)]
    assert result.receipt_envelope is None and "PRIVATE-SECRET" not in repr(result)


@pytest.mark.parametrize("fault", ["factory", "sql", "commit_before", "commit_after", "close"])
def test_second_transaction_failure_preserves_exact_private_receipt_without_replay(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    original = scenario.factory.side_effect
    def acquire():
        if len(scenario.connections) == 1 and fault == "factory":
            raise RuntimeError("PRIVATE-SECRET acquire")
        connection = original()
        if connection.index == 1:
            def fail():
                if fault == "commit_after":
                    connection._commit()
                raise RuntimeError("PRIVATE-SECRET receipt")
            if fault == "sql":
                connection.cursor.side_effect = RuntimeError("PRIVATE-SECRET sql")
            elif fault == "close":
                connection.close.side_effect = fail
            else:
                connection.commit.side_effect = fail
        return connection
    scenario.factory.side_effect = acquire
    result = scenario.run()
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and scenario.transport.call_count == 1
    assert archive_cipher.open(result.receipt_envelope) == result.observation
    assert ((scenario.identity, 2) in scenario.rows) is (fault in ("commit_after", "close"))
    assert "PRIVATE-SECRET" not in json.dumps(result.diagnostic_projection())


@pytest.mark.parametrize("fault", ["expired", "backwards", "too_old", "clock_failure"])
def test_dispatch_preflight_after_close_can_spend_reservation_without_sending(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    observed = {"expired": NOW + timedelta(days=3650), "backwards": NOW,
                "too_old": NOW + timedelta(seconds=32), "clock_failure": RuntimeError("PRIVATE-SECRET")}[fault]
    scenario.clock.side_effect = [NOW + timedelta(seconds=1), observed]
    result = scenario.run()
    assert result.state == "DISPATCH_PREFLIGHT_FAILED_NO_SEND"
    assert (scenario.identity, 1) in scenario.rows and len(scenario.connections) == 1
    scenario.transport.assert_not_called()
    scenario.connections[0].close.assert_called_once()


@pytest.mark.parametrize("fault", ["namespace", "version", "flow", "csr", "route"])
def test_manifest_csr_route_changes_cannot_select_other_authentication(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    if fault in ("version", "flow"):
        scenario.requirements = replace(scenario.requirements, manifest=replace(scenario.requirements.manifest,
            **{("version_id" if fault == "version" else "flow_id"): str(uuid4())}))
    elif fault == "namespace":
        scenario.requirements = replace(scenario.requirements, storage_namespace=str(uuid4()))
    elif fault == "csr":
        # Another key's CSR must fail before calling the coordinator.
        with pytest.raises(ValueError):
            replace(scenario.requirements, csr_der=csr(materials[1]))
        scenario.factory.assert_not_called()
        return
    else:
        scenario.route = resolve_api_route({"custom_select": "Production", "custom_production_url": "https://gateway.invalid/phase2"}, "compliance/invoices")
    if fault == "namespace":
        with pytest.raises(capture.ComplianceCaptureError, match="capture_input"):
            scenario.run()
        scenario.factory.assert_not_called()
    else:
        assert scenario.run().state == "PREPARATION_UNCONFIRMED_NO_SEND"
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("fault", ["identity", "body", "requirements", "clock"])
def test_invalid_inputs_fail_safely_before_acquiring_connections(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    changes = {}
    if fault == "identity":
        changes["exchange_id"] = "latest"
    elif fault == "body":
        changes["request_bytes"] = b"PRIVATE-SECRET"
    elif fault == "requirements":
        scenario.requirements = object()
    else:
        scenario.clock.side_effect = RuntimeError("PRIVATE-SECRET clock")
    with pytest.raises(capture.ComplianceCaptureError, match="capture_input") as error:
        scenario.run(**changes)
    assert error.value.__context__ is None
    scenario.factory.assert_not_called()
    scenario.transport.assert_not_called()


@pytest.mark.parametrize("status,body", [(True, b""), (99, b""), (600, b""), (200, "PRIVATE-SECRET"), (200, b"x" * (capture.MAX_RESPONSE_BYTES + 1))])
def test_response_bounds_are_exact_without_parser_detail(status, body):
    with pytest.raises(capture.ComplianceCaptureError, match="capture_response"):
        capture.ComplianceTransportResponse(status, body)


def test_protected_objects_are_frozen_unpickleable_and_no_http_or_file_discovery(materials, cipher, archive_cipher, monkeypatch):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    def forbidden(*args, **kwargs):
        raise AssertionError("No default HTTP/filesystem discovery")
    import requests
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    result = scenario.run()
    assert result.state == "RECEIPT_CAPTURED_OBSERVATION"
    for protected in (scenario.coordinator, result, result.response, scenario.transport.call_args.args[0]):
        with pytest.raises(capture.ComplianceCaptureError, match="capture_not_pickleable"):
            pickle.dumps(protected)
    with pytest.raises(FrozenInstanceError):
        result.state = "PASS"


@pytest.mark.parametrize("fault", ["namespace", "key_id", "missing_key", "bundle_cipher", "archive_cipher", "reused_keys", "factory", "transport", "clock"])
def test_dependencies_are_explicit_and_fail_before_acquisition(materials, cipher, archive_cipher, fault):
    factory, transport, clock = Mock(), Mock(), Mock()
    values = dict(storage_namespace=NAMESPACE, bundle_cipher=cipher, archive_cipher=archive_cipher, key_id="audit-test",
                  connection_factory=factory, transport=transport, clock=clock)
    if fault == "namespace":
        values["storage_namespace"] = "latest"
    elif fault == "key_id":
        values["key_id"] = True
    elif fault == "missing_key":
        values["key_id"] = "missing"
    elif fault in ("bundle_cipher", "archive_cipher"):
        values[fault] = object()
    elif fault == "reused_keys":
        values["archive_cipher"] = capture.ComplianceArchiveCipher({"audit-test": next(iter(cipher._keys.values()))})
    else:
        values[{"factory": "connection_factory", "transport": "transport", "clock": "clock"}[fault]] = None
    with pytest.raises(capture.ComplianceCaptureError):
        capture.ComplianceCaptureCoordinator(**values)
    factory.assert_not_called()
    transport.assert_not_called()
    clock.assert_not_called()


@pytest.mark.parametrize("fault", ["route", "snapshot_type", "start_type", "certificate", "owner", "age", "past", "response_as_start"])
def test_transport_request_cannot_mix_headers_and_body_material(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = scenario.run()
    prepared = scenario.transport.call_args.args[0]
    if fault == "route":
        from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture as snapshot
        material = snapshot(materials[0], environment="Simulation", endpoint="compliance/invoices")
        changes = {"snapshot": material}
    elif fault == "snapshot_type":
        changes = {"snapshot": object()}
    elif fault == "start_type":
        changes = {"start": object()}
    elif fault == "certificate":
        from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture as snapshot
        changes = {"snapshot": snapshot(materials[1], endpoint="compliance/invoices")}
    elif fault == "owner":
        changes = {"snapshot": replace(prepared.snapshot, owner=replace(prepared.snapshot.owner, name="OTHER", company_name="OTHER"))}
    elif fault in ("age", "past"):
        changes = {"snapshot": replace(prepared.snapshot, observed_at=NOW + timedelta(seconds=32) if fault == "age" else NOW)}
    else:
        changes = {"start": result.observation}
    with pytest.raises(capture.ComplianceCaptureError):
        replace(prepared, **changes)


@pytest.mark.parametrize("fault", ["state", "identity", "version", "start_envelope", "receipt_envelope", "observation", "response", "phase"])
def test_result_recovery_envelopes_cannot_be_misbound(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = scenario.run()
    changes = {"state": {"state": "PASS"}, "identity": {"exchange_id": str(uuid4())},
               "version": {"version_id": str(uuid4())}, "start_envelope": {"start_envelope": result.receipt_envelope},
               "receipt_envelope": {"receipt_envelope": None}, "observation": {"observation": None},
               "response": {"response": capture.ComplianceTransportResponse(401, b"")},
               "phase": {"state": "DISPATCH_PREFLIGHT_FAILED_NO_SEND"}}[fault]
    with pytest.raises(capture.ComplianceCaptureError, match="capture_result"):
        replace(result, **changes)


@pytest.mark.parametrize("phase", ["reservation", "transport"])
def test_process_interruption_propagates_with_owned_cleanup_and_no_automatic_replay(materials, cipher, archive_cipher, phase):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    if phase == "reservation":
        original = scenario.factory.side_effect
        def acquire():
            connection = original()
            connection.cursor.side_effect = KeyboardInterrupt()
            return connection
        scenario.factory.side_effect = acquire
    else:
        scenario.transport.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        scenario.run()
    assert all(connection.closed for connection in scenario.connections)
    if phase == "reservation":
        assert scenario.rows == {}
        scenario.connections[0].rollback.assert_called_once()
        scenario.transport.assert_not_called()
    else:
        assert list(scenario.rows) == [(scenario.identity, 1)]
        scenario.clock.side_effect = None
        scenario.clock.return_value = NOW + timedelta(seconds=3)
        assert scenario.run().state == "PREPARATION_UNCONFIRMED_NO_SEND"
        assert scenario.transport.call_count == 1
