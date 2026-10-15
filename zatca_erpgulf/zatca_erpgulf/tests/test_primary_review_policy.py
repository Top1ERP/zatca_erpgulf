"""Non-authorizing exact capture/pair review and current writer separation."""

import ast
from dataclasses import replace
import inspect
import json
import pickle
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_review_policy as policy
from zatca_erpgulf.zatca_erpgulf import primary_capture as capture
from zatca_erpgulf.zatca_erpgulf import primary_receipt_reconciliation as pair
from zatca_erpgulf.zatca_erpgulf import response_processing
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate, scope
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository import prepared
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_capture import Scenario
from zatca_erpgulf.zatca_erpgulf.tests.test_retry_identity_contract import ADAPTERS
from zatca_erpgulf.zatca_erpgulf.tests.test_response_processing import (
    ROUTES, boundary, inject_failure, run_adapter, snapshot,
)


EXPECTED_REASONS = (
    "REVIEW_START_AND_HOLD_UNCERTAINTY", "REVIEW_STOPPED_PREFLIGHT",
    "REVIEW_MISSING_RESPONSE_CUSTODY", "REVIEW_UNBOUND_RESPONSE",
    "REVIEW_UNSEALED_RESPONSE", "REVIEW_LOCAL_PAIR_UNCERTAINTY",
    "REVIEW_RECORDED_RESPONSE_NOT_ACCEPTANCE",
)


def observed_case(monkeypatch, prepared, stage=6, *, changes=None):
    fault = {0: (0, "factory"), 1: (1, "factory"), 5: (2, "commit-before")}.get(stage)
    case = Scenario(monkeypatch, prepared, fault=fault)
    original = case.observer.side_effect
    if stage == 2:
        case.observer.side_effect = RuntimeError("PRIVATE unknown observer outcome")
    elif stage == 3:
        case.observer.side_effect = lambda request: replace(original(request), request_sha256="0" * 64)
    elif stage == 4:
        monkeypatch.setattr(case.cipher, "seal", Mock(side_effect=ValueError("PRIVATE custody unavailable")))
    elif changes is not None:
        case.observer.side_effect = lambda request: replace(original(request), **changes)
    result = case.run()
    assert result.state == capture.CAPTURE_STATES[stage]
    # Review must be inspection of supplied contracts ONLY, not another action.
    case.factory.side_effect = AssertionError("No new SQL acquisition")
    case.observer.side_effect = AssertionError("No new observation")
    monkeypatch.setattr(case.cipher, "seal", Mock(side_effect=AssertionError("No resealing")))
    monkeypatch.setattr(case.cipher, "open", Mock(side_effect=AssertionError("No key/decryption dependency")))
    return case, result


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("stage", range(7))
def test_capture_review_preserves_all_stages_without_automatic_action_or_acceptance(certificates, monkeypatch,
    doctype, indicator, stage):
    selected = candidate(certificates[0], selected_scope=scope(doctype=doctype), indicator=indicator)
    case, supplied = observed_case(monkeypatch, selected, stage)
    before = (case.journal, case.hold, case.binding, case.sealed, tuple(case.events))
    reviewed = policy.review_primary_outcome(supplied)
    report = reviewed.diagnostic_projection()
    assert report["review_reason"] == EXPECTED_REASONS[stage]
    assert report["capture_state"] == supplied.state and report["pair_state"] is None
    assert report["response_supplied"] is (stage >= 3) and report["sealed_input_supplied"] is (stage >= 5)
    assert report["local_history_disagreement"] is False
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert (case.journal, case.hold, case.binding, case.sealed, tuple(case.events)) == before
    assert not {"request", "response", "receipt", "sealed", "body", "uuid", "invoice_name", "key_id"} & report.keys()
    assert "INV-TEST" not in json.dumps(report) and "PRIVATE" not in json.dumps(report)
    protected = tuple(value for value in (supplied, supplied.request, supplied.sealed) if value is not None)
    assert not any(value is original for value in vars(reviewed).values() for original in protected)
    assert set(vars(reviewed)) == {"capture_state", "pair_state"}
    assert all(value is None or type(value) is str for value in vars(reviewed).values())


@pytest.mark.parametrize("stage", [5, 6])
@pytest.mark.parametrize("pair_state", pair.RESULT_STATES)
def test_same_original_pair_never_grants_acceptance_or_automatic_missing_half_repair(prepared, monkeypatch, stage, pair_state):
    case, supplied = observed_case(monkeypatch, prepared, stage)
    paired = pair.PrimaryReconciliationResult(pair_state, supplied.request, replace(supplied.sealed))
    assert paired.sealed is not supplied.sealed and paired.sealed == supplied.sealed
    report = policy.review_primary_outcome(supplied, paired).diagnostic_projection()
    assert report["review_reason"] == policy.PAIR_REASONS[pair_state]
    assert report["pair_state"] == pair_state
    expected_disagreement = stage == 6 and pair_state in (
        "PAIR_MISSING_OBSERVATION_NO_REPLAY", "CUSTODY_ONLY_REVIEW_NO_REPLAY",
        "JOURNAL_ONLY_REVIEW_NO_REPLAY", "PAIR_CONFLICT_REVIEW_NO_REPLAY")
    assert report["local_history_disagreement"] is expected_disagreement
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))


@pytest.mark.parametrize("stage", range(5))
def test_missing_unbound_or_unsealed_capture_cannot_be_given_an_unrelated_pair(prepared, monkeypatch, stage):
    _, complete = observed_case(monkeypatch, prepared)
    paired = pair.PrimaryReconciliationResult("PAIR_MATCHED_OBSERVATION_NO_REPLAY", complete.request, complete.sealed)
    _, supplied = observed_case(monkeypatch, prepared, stage)
    with pytest.raises(policy.PrimaryReviewError, match="primary_review_input") as error:
        policy.review_primary_outcome(supplied, paired)
    assert error.value.__context__ is None


@pytest.mark.parametrize("wrong", ["capture-type", "capture-state", "pair-type", "pair-state", "request", "reseal", "namespace"])
def test_wrong_or_substituted_protected_evidence_is_static_unchained_failure(prepared, certificates, monkeypatch, wrong):
    _, supplied = observed_case(monkeypatch, prepared)
    paired = pair.PrimaryReconciliationResult("PAIR_MATCHED_OBSERVATION_NO_REPLAY", supplied.request, supplied.sealed)
    if wrong == "capture-type":
        supplied = {"state": supplied.state}
    elif wrong == "capture-state":
        object.__setattr__(supplied, "state", "PRIVATE INVALID state")
    elif wrong == "pair-type":
        paired = {}
    elif wrong == "pair-state":
        object.__setattr__(paired, "state", "PRIVATE INVALID pair state")
    elif wrong == "request":
        other = candidate(certificates[0], selected_scope=scope(doctype="POS Invoice"))
        _, alternative = observed_case(monkeypatch, other)
        paired = pair.PrimaryReconciliationResult(paired.state, alternative.request, alternative.sealed)
    else:
        receipt = supplied.receipt
        if wrong == "namespace":
            receipt = replace(receipt, storage_namespace="50000000-0000-4000-8000-000000000001")
        cipher = PrimaryReceiptCustodyCipher({supplied.sealed.key_id: b"P" * 32})
        alternative = cipher.seal(receipt, key_id=supplied.sealed.key_id)
        paired = pair.PrimaryReconciliationResult(paired.state, supplied.request, alternative)
    with pytest.raises(policy.PrimaryReviewError) as error:
        policy.review_primary_outcome(supplied, paired)
    assert str(error.value) == "primary_review_input" and error.value.__context__ is None


@pytest.mark.parametrize("status", [200, 202, 400, 401, 403, 406, 409, 500])
@pytest.mark.parametrize("body", [b"", b"\x00\xff PRIVATE non-JSON", b'{"validationResults":{"status":"PASS"},"reportingStatus":"REPORTED"}'])
def test_http_status_or_success_shaped_body_never_becomes_authoritative_review(prepared, monkeypatch, status, body):
    _, supplied = observed_case(monkeypatch, prepared, changes={"http_status": status, "body": body})
    paired = pair.PrimaryReconciliationResult("PAIR_MATCHED_OBSERVATION_NO_REPLAY", supplied.request, supplied.sealed)
    report = policy.review_primary_outcome(supplied, paired).diagnostic_projection()
    assert report["review_reason"] == "REVIEW_MATCHED_PAIR_NOT_ACCEPTANCE"
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_current_twelve_runtime_adapters_are_not_wired_to_new_pair_storage_or_review(adapter):
    module, name, *_ = adapter
    source = inspect.getsource(getattr(module, name))
    names = {node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)}
    assert not names & {"PrimaryCaptureCoordinator", "SavedPrimaryCaptureService", "PrimaryReceiptPersistence",
        "SavedPrimaryReceiptService", "MariaDBPrimaryReceiptCustodyRepository", "SavedPrimaryReceiptCustodyService",
        "PrimaryReceiptReconciliation", "SavedPrimaryReconciliationService", "review_primary_outcome"}
    assert "zatca_primary_" not in source


@pytest.mark.parametrize("module,operation", ROUTES)
@pytest.mark.parametrize("status", [400, 401, 503])
def test_previously_characterized_error_status_logging_failure_no_longer_runs_mutable_error_writes(boundary, monkeypatch, module, operation, status):
    # Increment56 reproduced the gap; increment57 now guards the log step
    # without changing intentional HTTP-rejection branches when logging works.
    b = boundary
    b.response.status_code = status
    doc, observed = inject_failure(b, module, operation, monkeypatch, "log_zatca_event", ValueError)
    with pytest.raises(response_processing.LocalResponseProcessingError) as error:
        run_adapter(b, module, operation)
    assert len(observed) == 1 and snapshot(b, doc) == observed[0]
    assert str(error.value) == response_processing.LOCAL_RESPONSE_REVIEW and error.value.__context__ is None
    b.post.assert_called_once()


def test_metadata_contract_is_closed_and_has_no_action_methods_or_protected_exports(prepared, monkeypatch):
    assert set(policy.CAPTURE_REASONS) == set(capture.CAPTURE_STATES)
    assert set(policy.PAIR_REASONS) == set(pair.RESULT_STATES)
    _, supplied = observed_case(monkeypatch, prepared)
    reviewed = policy.review_primary_outcome(supplied)
    with pytest.raises(policy.PrimaryReviewError, match="not_pickleable"):
        pickle.dumps(reviewed)
    for args in (("PRIVATE",), (capture.CAPTURE_STATES[0], pair.RESULT_STATES[0]), (True,)):
        with pytest.raises(policy.PrimaryReviewError):
            policy.PrimaryReviewObservation(*args)
    source = inspect.getsource(policy)
    for forbidden in ("import frappe", "import requests", "whitelist", ".seal(", ".persist(", ".reserve(",
            ".append(", "datetime.now", "CREATE TABLE", ".save(", ".db_set("):
        assert forbidden not in source
