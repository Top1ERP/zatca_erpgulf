"""Local persistence recovery with fake owned SQL and synthetic transport only."""

import json
import pickle
from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceCaptureResult
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import STEP_CLASSIFICATION
from zatca_erpgulf.zatca_erpgulf.compliance_receipt_recovery import ComplianceReceiptRecovery, ComplianceReceiptRecoveryError
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_capture import Scenario
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive import archive_cipher, archive_record
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle import cipher, NAMESPACE
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials


def uncertain(scenario, *, committed=False):
    original = scenario.factory.side_effect
    def acquire():
        database = original()
        if database.index == 1:
            def fail():
                if committed:
                    database._commit()
                raise RuntimeError("PRIVATE-SECRET uncertain receipt commit")
            database.commit.side_effect = fail
        return database
    scenario.factory.side_effect = acquire
    result = scenario.run()
    scenario.factory.side_effect = original
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    return result


def recovery(scenario, cipher, archive_cipher, **changes):
    values = dict(connection_factory=scenario.factory)
    values.update(changes)
    return ComplianceReceiptRecovery(NAMESPACE, cipher, archive_cipher, **values)


def forbid_nonstorage(scenario, archive_cipher, monkeypatch):
    scenario.transport.side_effect = AssertionError("No second transport invocation")
    scenario.clock.side_effect = AssertionError("No current clock discovery")
    monkeypatch.setattr(archive_cipher, "seal", Mock(side_effect=AssertionError("No resealing")))


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("status", [200, 202, 400, 401, 406, 500])
def test_exact_retained_receipt_is_recovered_in_one_transaction_without_sending(materials, cipher, archive_cipher, monkeypatch, committed, status):
    scenario = Scenario(materials[0], cipher, archive_cipher, status=status)
    result = uncertain(scenario, committed=committed)
    forbid_nonstorage(scenario, archive_cipher, monkeypatch)
    recovered = recovery(scenario, cipher, archive_cipher).persist_receipt(result)
    assert recovered == replace(result, state="RECEIPT_CAPTURED_OBSERVATION")
    assert recovered.start_envelope is result.start_envelope and recovered.receipt_envelope is result.receipt_envelope
    assert recovered.response is result.response and recovered.observation is result.observation
    assert scenario.rows[scenario.identity, 2] == archive_record(result.receipt_envelope)
    assert len(scenario.connections) == 3 and all(connection.closed for connection in scenario.connections)
    assert scenario.events[-2:] == [("commit", 2), ("close", 2)]
    assert scenario.transport.call_count == 1 and scenario.clock.call_count == 3
    assert all(value is False for key, value in recovered.diagnostic_projection().items() if key.endswith(("_authorized", "_verified")))
    # The retained uncertain input can be explicitly redelivered. This confirms
    # identical storage only, not a second dispatch or a new remote observation.
    assert recovery(scenario, cipher, archive_cipher).persist_receipt(result) == recovered
    assert scenario.transport.call_count == 1
    with pytest.raises(ComplianceReceiptRecoveryError, match="recovery_input"):
        recovery(scenario, cipher, archive_cipher).persist_receipt(recovered)
    assert len(scenario.connections) == 4


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("step", list(STEP_CLASSIFICATION))
def test_scope_and_invoice_type_are_preserved_not_promoted_to_compliance(materials, cipher, archive_cipher, environment, step):
    scenario = Scenario(materials[0], cipher, archive_cipher, environment=environment, step=step)
    result = uncertain(scenario)
    recovered = recovery(scenario, cipher, archive_cipher).persist_receipt(result)
    assert recovered.observation.step == step and recovered.observation.route.environment == environment
    assert recovered.diagnostic_projection()["compliance_completion_verified"] is False


@pytest.mark.parametrize("fault", ["factory", "sql", "autocommit", "commit_before", "commit_after", "close", "rollback_cleanup"])
def test_recovery_uncertainty_preserves_the_same_input_and_never_retries(materials, cipher, archive_cipher, monkeypatch, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = uncertain(scenario)
    original = scenario.factory.side_effect
    def acquire():
        if fault == "factory":
            raise RuntimeError("PRIVATE-SECRET acquire")
        database = original()
        def fail():
            if fault == "commit_after":
                database._commit()
            raise RuntimeError("PRIVATE-SECRET persistence")
        if fault in ("sql", "rollback_cleanup"):
            database.cursor.side_effect = fail
            if fault == "rollback_cleanup":
                database.rollback.side_effect = fail
        elif fault == "autocommit":
            execute = database.execute
            def query(sql, values=None):
                execute(sql, values)
                if sql == "SELECT @@session.autocommit":
                    database.row = (1,)
            database.cursor.return_value.execute.side_effect = query
        elif fault == "close":
            database.close.side_effect = fail
        else:
            database.commit.side_effect = fail
        return database
    scenario.factory.side_effect = acquire
    forbid_nonstorage(scenario, archive_cipher, monkeypatch)
    assert recovery(scenario, cipher, archive_cipher).persist_receipt(result) is result
    assert scenario.factory.call_count == 3 and scenario.transport.call_count == 1
    assert ((scenario.identity, 2) in scenario.rows) is (fault in ("commit_after", "close"))
    if fault != "factory":
        scenario.connections[-1].rollback.assert_called_once()
        scenario.connections[-1].close.assert_called_once()
    assert "PRIVATE-SECRET" not in json.dumps(result.diagnostic_projection())


@pytest.mark.parametrize("fault", ["start_ciphertext", "receipt_ciphertext", "start_nonce", "receipt_key", "namespace", "wrong_type", "subclass"])
def test_bad_or_unauthenticated_input_fails_before_acquiring_sql(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = uncertain(scenario)
    namespace = NAMESPACE
    if fault in ("start_ciphertext", "receipt_ciphertext", "start_nonce", "receipt_key"):
        name = "start_envelope" if fault.startswith("start") else "receipt_envelope"
        sealed = getattr(result, name)
        changes = {"ciphertext": sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1])}
        if fault == "start_nonce":
            changes = {"nonce": bytes([sealed.nonce[0] ^ 1]) + sealed.nonce[1:]}
        if fault == "receipt_key":
            changes = {"key_id": "missing-private-key"}
        result = replace(result, **{name: replace(sealed, **changes)})
    elif fault == "namespace":
        namespace = str(uuid4())
    elif fault == "wrong_type":
        result = {"state": "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"}
    else:
        class UntrustedResult(ComplianceCaptureResult):
            pass
        result = UntrustedResult(**vars(result))
    service = ComplianceReceiptRecovery(namespace, cipher, archive_cipher, connection_factory=scenario.factory)
    with pytest.raises(ComplianceReceiptRecoveryError, match="^recovery_input$") as error:
        service.persist_receipt(result)
    assert error.value.__context__ is None and scenario.factory.call_count == 2
    assert scenario.transport.call_count == 1


@pytest.mark.parametrize("state", ["PREPARATION_UNCONFIRMED_NO_SEND", "DISPATCH_PREFLIGHT_FAILED_NO_SEND", "TRANSPORT_UNKNOWN_NO_REPLAY", "RECEIPT_CAPTURED_OBSERVATION"])
def test_only_uncertain_receipt_stage_can_be_reconciled(materials, cipher, archive_cipher, state):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    captured = scenario.run()
    observation = captured.observation
    if state in ("PREPARATION_UNCONFIRMED_NO_SEND", "DISPATCH_PREFLIGHT_FAILED_NO_SEND"):
        observation = replace(observation, http_status=None, response_bytes=None, received_at=None)
    result = ComplianceCaptureResult(state, captured.exchange_id, captured.version_id, captured.start_envelope,
        captured.receipt_envelope if state == "RECEIPT_CAPTURED_OBSERVATION" else None, observation,
        captured.response if observation.http_status is not None else None)
    with pytest.raises(ComplianceReceiptRecoveryError, match="recovery_input"):
        recovery(scenario, cipher, archive_cipher).persist_receipt(result)
    assert scenario.factory.call_count == 2


@pytest.mark.parametrize("fault", ["missing_start", "resealed_start", "corrupt_start", "resealed_receipt", "corrupt_bundle", "wrong_version"])
def test_persisted_conflicts_never_replace_history_or_create_a_start(materials, cipher, archive_cipher, fault):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = uncertain(scenario)
    start_key, receipt_key = (scenario.identity, 1), (scenario.identity, 2)
    if fault == "missing_start":
        scenario.rows.pop(start_key)
    elif fault == "resealed_start":
        start = archive_cipher.open(result.start_envelope)
        scenario.rows[start_key] = archive_record(archive_cipher.seal(start, sequence=1, key_id="audit-test"))
    elif fault == "corrupt_start":
        values = list(scenario.rows[start_key])
        values[-1] = values[-1][:-1] + bytes([values[-1][-1] ^ 1])
        scenario.rows[start_key] = tuple(values)
    elif fault == "resealed_receipt":
        scenario.rows[receipt_key] = archive_record(archive_cipher.seal(result.observation, sequence=2, key_id="audit-test"))
    elif fault == "corrupt_bundle":
        scenario.bundle = replace(scenario.bundle, ciphertext=scenario.bundle.ciphertext[:-1] + bytes([scenario.bundle.ciphertext[-1] ^ 1]))
    else:
        scenario.bundle = replace(scenario.bundle, manifest_bytes=replace(scenario.bundle.manifest, version_id=str(uuid4())).encode())
    before = dict(scenario.rows)
    assert recovery(scenario, cipher, archive_cipher).persist_receipt(result) is result
    assert scenario.rows == before and scenario.transport.call_count == 1
    scenario.connections[-1].commit.assert_not_called()
    scenario.connections[-1].rollback.assert_called_once()
    scenario.connections[-1].close.assert_called_once()


@pytest.mark.parametrize("phase", ["cursor", "commit", "close"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interruptions_cleanup_and_propagate_without_network(materials, cipher, archive_cipher, phase, interruption):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = uncertain(scenario)
    original = scenario.factory.side_effect
    def acquire():
        database = original()
        getattr(database, phase).side_effect = interruption("PRIVATE-SECRET interrupted")
        return database
    scenario.factory.side_effect = acquire
    with pytest.raises(interruption):
        recovery(scenario, cipher, archive_cipher).persist_receipt(result)
    scenario.connections[-1].rollback.assert_called_once()
    scenario.connections[-1].close.assert_called_once()
    assert scenario.transport.call_count == 1


@pytest.mark.parametrize("fault", ["namespace", "bundle_type", "archive_type", "key_reuse", "factory"])
def test_dependency_binding_is_explicit_and_static(cipher, archive_cipher, fault):
    namespace, bundle, archive, factory = NAMESPACE, cipher, archive_cipher, Mock()
    if fault == "namespace":
        namespace = "PRIVATE-SECRET invalid namespace"
    elif fault == "bundle_type":
        bundle = object()
    elif fault == "archive_type":
        archive = object()
    elif fault == "key_reuse":
        archive = type(archive_cipher)(cipher._keys)
    else:
        factory = None
    with pytest.raises(ComplianceReceiptRecoveryError, match="^recovery_dependencies$") as error:
        ComplianceReceiptRecovery(namespace, bundle, archive, connection_factory=factory)
    assert error.value.__context__ is None
    if fault != "factory":
        factory.assert_not_called()


def test_recovery_diagnostics_and_objects_do_not_export_private_material(materials, cipher, archive_cipher):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = uncertain(scenario)
    service = recovery(scenario, cipher, archive_cipher)
    recovered = service.persist_receipt(result)
    public = repr(service) + repr(recovered) + json.dumps(recovered.diagnostic_projection())
    for private in (materials[0].pem, materials[0].text, scenario.body.decode(), result.receipt_envelope.ciphertext.hex(), "gw-fatoora"):
        assert private not in public
    with pytest.raises(ComplianceReceiptRecoveryError, match="recovery_not_pickleable"):
        pickle.dumps(service)
    assert scenario.transport.call_count == 1


def test_historical_bundle_authentication_uses_preparation_time_only(materials, cipher, archive_cipher, monkeypatch):
    scenario = Scenario(materials[0], cipher, archive_cipher)
    result = uncertain(scenario)
    opening = Mock(wraps=cipher.open)
    monkeypatch.setattr(cipher, "open", opening)
    forbid_nonstorage(scenario, archive_cipher, monkeypatch)
    assert recovery(scenario, cipher, archive_cipher).persist_receipt(result).state == "RECEIPT_CAPTURED_OBSERVATION"
    assert opening.call_count == 1 and opening.call_args.kwargs["observed_at"] == scenario.bundle.manifest.prepared_at
    assert scenario.transport.call_count == 1
