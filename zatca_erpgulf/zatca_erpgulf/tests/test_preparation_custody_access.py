"""Submitted saved-WRITE custody boundaries; synthetic ACL, keys and evidence."""

import csv
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import preparation_custody_access as access
from zatca_erpgulf.zatca_erpgulf import preparation_recovery_access as recovery
from zatca_erpgulf.zatca_erpgulf.preparation_custody import PreparationOriginalCipher
from zatca_erpgulf.zatca_erpgulf.preparation_review_access import FALSE_FLAGS
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_recovery_access import (
    recoverer, reviewer, operator, scenario as recovery_scenario, untouched,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_review_access import PermissionDenied, InspectionFailed


@pytest.fixture
def custodian(recoverer, monkeypatch):
    monkeypatch.setattr(access, "frappe", recoverer.runtime)
    monkeypatch.setattr(access, "_", lambda text:text)
    monkeypatch.setattr(access, "has_permission", recovery.has_permission)
    return recoverer


def scenario(custodian, der, monkeypatch, **kwargs):
    case = recovery_scenario(custodian, der, monkeypatch, **kwargs)
    case.cipher = PreparationOriginalCipher({"test-preparation-v1": b"P"*32})
    case.sealed = case.cipher.seal(case.retained, key_id="test-preparation-v1")
    case.keys = Mock(return_value=access.PreparationCustodyResources(case.scope, case.cipher))
    case.custody_repo = Mock()
    case.custody_repo.stage.return_value = case.sealed
    case.custody_repo.load.return_value = case.sealed
    case.custody_factory = Mock(return_value=case.custody_repo)
    monkeypatch.setattr(access, "MariaDBPreparationCustodyRepository", case.custody_factory)
    monkeypatch.setattr(access, "MariaDBPreparationHoldRepository", case.repository_factory)
    case.repository.load_for_source.return_value = case.hold
    case.repository.load.return_value = case.hold
    case.custody = access.SavedPreparationCustodyService(case.scope, case.keys, case.evidence, case.factory)
    return case


def stage(case):
    return case.custody.stage(case.invoice.name, case.sealed, doctype=case.invoice.doctype)


def load(case):
    return case.custody.load(case.invoice.name, doctype=case.invoice.doctype)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_storage_metadata_only_and_protected_retrieval(custodian, certificates, monkeypatch, doctype, owner):
    case = scenario(custodian, certificates[0], monkeypatch, doctype=doctype, owner=owner)
    report = stage(case)
    assert report["local_transaction_completed"] is True
    assert all(report[name] is False for name in FALSE_FLAGS)
    assert "INV-TEST" not in json.dumps(report)
    case.custody_repo.stage.assert_called_once_with(case.sealed)
    case.repository.complete.assert_not_called()
    assert load(case) is case.sealed
    assert case.database.commit.call_count == 1
    assert case.database.close.call_count == 2
    untouched(custodian, case)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_internal_recovery_uses_exact_ciphertext_and_no_plaintext_export(custodian, certificates, monkeypatch, doctype):
    case = scenario(custodian, certificates[0], monkeypatch, doctype=doctype)
    report = case.custody.persist_from_custody(case.invoice.name, doctype=doctype)
    assert report["local_transaction_completed"] is True
    assert all(report[name] is False for name in FALSE_FLAGS)
    case.repository.complete.assert_called_once_with(case.retained.hold, case.retained.candidate)
    assert case.custody_repo.load.call_count == 3
    assert case.database.close.call_count == 2
    untouched(custodian, case)


@pytest.mark.parametrize("method", ["stage", "load", "persist_from_custody"])
@pytest.mark.parametrize("identity", [("Sales Invoice","INV-TEST"), ("Company","TEST"),
    ("ZATCA Multiple Setting","DEVICE"), ("Company","LINKED")])
def test_acl_precedes_keys_and_sql(custodian, certificates, monkeypatch, method, identity):
    case = scenario(custodian, certificates[0], monkeypatch, owner="linked")
    custodian.denied.add(identity)
    with pytest.raises(PermissionDenied) as caught:
        getattr(case.custody, method)(case.invoice.name, *([case.sealed] if method == "stage" else []))
    assert str(caught.value) == access.DENIED_MESSAGE and caught.value.__context__ is None
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("status", [0, 2])
@pytest.mark.parametrize("method", ["stage", "load", "persist_from_custody"])
def test_non_submitted_is_review_only(custodian, certificates, monkeypatch, status, method):
    case = scenario(custodian, certificates[0], monkeypatch)
    case.invoice.docstatus = status
    with pytest.raises(InspectionFailed):
        getattr(case.custody, method)(case.invoice.name, *([case.sealed] if method == "stage" else []))
    case.keys.assert_not_called()
    case.factory.assert_not_called()


def test_read_does_not_grant_write_or_decryption(custodian, certificates, monkeypatch):
    case = scenario(custodian, certificates[0], monkeypatch)
    custodian.denied_operations.add(("Sales Invoice","INV-TEST","write"))
    assert case.service.inspect(case.invoice.name)["state"] == "PENDING_ORIGINAL_UNCONFIRMED_REVIEW"
    case.factory.reset_mock()
    with pytest.raises(PermissionDenied): load(case)
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("value", [False, None, 1, "True", {}, []])
def test_evidence_requires_literal_true(custodian, certificates, monkeypatch, value):
    case = scenario(custodian, certificates[0], monkeypatch)
    case.evidence.return_value = value
    with pytest.raises(InspectionFailed): stage(case)
    case.factory.assert_not_called()


@pytest.mark.parametrize("field", ["site", "storage_namespace"])
def test_cross_scope_envelope_never_reaches_keys(custodian, certificates, monkeypatch, field):
    case = scenario(custodian, certificates[0], monkeypatch)
    case.sealed = replace(case.sealed, **{field: "other.test" if field == "site" else str(uuid4())})
    with pytest.raises(InspectionFailed): stage(case)
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("boundary", ["keys", "factory", "stage", "close"])
@pytest.mark.parametrize("change", ["permission", "revision", "actor"])
def test_late_drift_denies_disclosure_without_deleting_ciphertext(custodian, certificates, monkeypatch, boundary, change):
    case = scenario(custodian, certificates[0], monkeypatch)
    target = {"keys":case.keys, "factory":case.factory, "stage":case.custody_repo.stage, "close":case.database.close}[boundary]
    result = {"keys":case.keys.return_value, "factory":case.database, "stage":case.sealed, "close":None}[boundary]
    def mutate(*args, **kwargs):
        if change == "permission": custodian.denied_operations.add(("Sales Invoice","INV-TEST","write"))
        if change == "actor": custodian.runtime.session.user = "other@example.test"
        if change == "revision": case.invoice.modified += timedelta(seconds=1)
        return result
    target.side_effect = mutate
    with pytest.raises(InspectionFailed if change == "revision" else PermissionDenied): stage(case)
    if boundary == "close": case.database.commit.assert_called_once()
    case.repository.complete.assert_not_called()


@pytest.mark.parametrize("boundary", ["factory", "stage", "commit", "close"])
def test_storage_unknown_has_no_retry_or_reseal(custodian, certificates, monkeypatch, boundary):
    case = scenario(custodian, certificates[0], monkeypatch)
    exact = case.sealed
    {"factory":case.factory, "stage":case.custody_repo.stage, "commit":case.database.commit,
        "close":case.database.close}[boundary].side_effect = RuntimeError("PRIVATE driver")
    report = stage(case)
    assert report["local_transaction_completed"] is False
    assert case.sealed is exact
    assert case.custody_repo.stage.call_count <= 1
    case.repository.complete.assert_not_called()


@pytest.mark.parametrize("boundary", ["stage", "commit", "close"])
def test_interrupt_preserves_exact_envelope_and_cleans_owned_handle(custodian, certificates, monkeypatch, boundary):
    case = scenario(custodian, certificates[0], monkeypatch)
    {"stage":case.custody_repo.stage, "commit":case.database.commit,
        "close":case.database.close}[boundary].side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): stage(case)
    case.database.close.assert_called_once()


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_parent_transaction_is_not_used_or_cleaned(custodian, certificates, monkeypatch, borrowed):
    case = scenario(custodian, certificates[0], monkeypatch)
    custodian.runtime.db._conn = case.database
    case.factory.return_value = custodian.runtime.db if borrowed == "db" else case.database
    assert stage(case)["local_transaction_completed"] is False
    case.database.close.assert_not_called()
    case.database.rollback.assert_not_called()
    case.database.commit.assert_not_called()


def test_changed_ciphertext_inside_recovery_refuses_completion(custodian, certificates, monkeypatch):
    case = scenario(custodian, certificates[0], monkeypatch)
    resealed = case.cipher.seal(case.retained, key_id="test-preparation-v1")
    case.custody_repo.load.side_effect = [case.sealed, resealed]
    report = case.custody.persist_from_custody(case.invoice.name)
    assert report["local_transaction_completed"] is False
    case.repository.complete.assert_not_called()


@pytest.mark.parametrize("failure", ["missing_hold", "wrong_keys", "missing_ciphertext", "close"])
def test_protected_load_failures_are_static(custodian, certificates, monkeypatch, failure):
    case = scenario(custodian, certificates[0], monkeypatch)
    if failure == "missing_hold": case.repository.load_for_source.return_value = None
    if failure == "wrong_keys":
        case.keys.return_value = access.PreparationCustodyResources(case.scope,
            PreparationOriginalCipher({"test-preparation-v1":b"Q"*32}))
    if failure == "missing_ciphertext": case.custody_repo.load.side_effect = RuntimeError("PRIVATE")
    if failure == "close": case.database.close.side_effect = RuntimeError("PRIVATE")
    with pytest.raises(InspectionFailed) as caught: load(case)
    assert str(caught.value) == access.FAILED_MESSAGE and caught.value.__context__ is None
    case.database.commit.assert_not_called()
    if failure != "wrong_keys": case.database.close.assert_called_once()


def test_single_translated_presentation_does_not_translate_internal_states():
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open(newline="", encoding="utf-8") as handle:
        translations = {row[0]:row[1] for row in csv.reader(handle) if len(row) >= 2}
    for text in (access.TITLE, access.DENIED_MESSAGE, access.FAILED_MESSAGE, *access.MESSAGES.values()):
        assert translations[text] != text
    for completed in (True, False):
        report = access._projection(completed)
        original = json.dumps(report, sort_keys=True)
        shown = access.present_preparation_custody(report, translations.__getitem__)
        assert set(shown) == {"title","message","indicator"}
        assert shown["message"] == translations[access.MESSAGES[report["state"]]]
        assert json.dumps(report, sort_keys=True) == original


@pytest.mark.parametrize("change", ["extra", "grant", "number", "state"])
def test_presentation_refuses_secret_fields_and_fabricated_grants(change):
    report = access._projection(False)
    if change == "extra": report["xml_bytes"] = "PRIVATE"
    if change == "grant": report["replay_authorized"] = True
    if change == "number": report["local_transaction_completed"] = 0
    if change == "state": report["state"] = "ACCEPTED"
    with pytest.raises(access.PreparationCustodyAccessError):
        access.present_preparation_custody(report, lambda text:text)



@pytest.mark.parametrize("method", ["stage", "load", "persist_from_custody"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_access_authenticates_once_without_skipping_source_boundaries(
    custodian, certificates, monkeypatch, method, doctype, owner):
    case = scenario(custodian, certificates[0], monkeypatch, doctype=doctype, owner=owner)
    authenticated = Mock(wraps=case.cipher.open)
    monkeypatch.setattr(case.cipher, "open", authenticated)
    result = getattr(case.custody, method)(case.invoice.name,
        *([case.sealed] if method == "stage" else []), doctype=doctype)
    authenticated.assert_called_once_with(case.sealed)
    expected_boundaries = {"stage":4, "load":2, "persist_from_custody":6}[method]
    assert case.evidence.call_count == expected_boundaries
    if method == "load":
        assert result is case.sealed
        case.database.commit.assert_not_called()
    else:
        assert result["local_transaction_completed"] is True
    if method == "persist_from_custody":
        assert case.custody_repo.load.call_count == 3  # Read and both write boundaries.
        case.repository.complete.assert_called_once_with(case.retained.hold, case.retained.candidate)
    untouched(custodian, case)


@pytest.mark.parametrize("boundary", ["evidence", "factory", "stage", "close"])
@pytest.mark.parametrize("field", ["site", "storage_namespace", "hold_id", "ticket_sha256",
    "candidate_sha256", "manifest_sha256", "payload_sha256", "key_id", "nonce", "ciphertext"])
def test_every_envelope_field_remains_pinned_after_authentication(
    custodian, certificates, monkeypatch, boundary, field):
    case = scenario(custodian, certificates[0], monkeypatch)
    value = {"site":"other.test", "storage_namespace":str(uuid4()), "hold_id":str(uuid4()),
        "key_id":"other-key", "nonce":b"N"*12,
        "ciphertext":case.sealed.ciphertext[:-1] + bytes([case.sealed.ciphertext[-1] ^ 1])}.get(field, "f"*64)
    target = {"evidence":case.evidence, "factory":case.factory,
        "stage":case.custody_repo.stage, "close":case.database.close}[boundary]
    result = {"evidence":True, "factory":case.database, "stage":case.sealed, "close":None}[boundary]
    def mutate(*args, **kwargs):
        # Deliberate trusted-callback corruption, not a supported mutation API.
        object.__setattr__(case.sealed, field, value)
        return result
    target.side_effect = mutate
    authenticated = Mock(wraps=case.cipher.open)
    monkeypatch.setattr(case.cipher, "open", authenticated)
    with pytest.raises(InspectionFailed) as caught:
        stage(case)
    assert str(caught.value) == access.FAILED_MESSAGE and caught.value.__context__ is None
    authenticated.assert_called_once()
    case.repository.complete.assert_not_called()
    if boundary == "evidence":
        case.factory.assert_not_called()
    else:
        case.database.close.assert_called_once()
    if boundary == "close":
        case.database.commit.assert_called_once()  # Late denial cannot undo commit.


@pytest.mark.parametrize("field", ["xml_bytes", "key_sha256", "manifest_sha256",
    "scope", "ticket", "completed"])
@pytest.mark.parametrize("boundary", [1, 2, 3, 4])
def test_independent_original_pin_catches_callback_drift_without_redecoding(
    custodian, certificates, monkeypatch, field, boundary):
    case = scenario(custodian, certificates[0], monkeypatch)
    calls = []
    def mutate(scope, rows, original, *, connection=None):
        calls.append(connection)
        if len(calls) == boundary:
            if field in ("xml_bytes", "key_sha256", "manifest_sha256"):
                object.__setattr__(original.candidate, field, b"PRIVATE" if field == "xml_bytes" else "f"*64)
            elif field == "scope":
                object.__setattr__(original, "scope", replace(original.scope, site="other.test"))
            elif field == "ticket":
                object.__setattr__(original.hold, "ticket", replace(original.hold.ticket, invoice_uuid=str(uuid4())))
            else:
                object.__setattr__(original.hold, "original_manifest_sha256", "f"*64)
        return True
    case.evidence.side_effect = mutate
    authenticated = Mock(wraps=case.cipher.open)
    monkeypatch.setattr(case.cipher, "open", authenticated)
    with pytest.raises(InspectionFailed): stage(case)
    authenticated.assert_called_once()
    if boundary == 1: case.factory.assert_not_called()
    else: case.database.close.assert_called_once()
    if boundary == 4: case.database.commit.assert_called_once()


@pytest.mark.parametrize("boundary", ["load", "evidence", "close"])
@pytest.mark.parametrize("field", ["nonce", "ticket_sha256", "ciphertext"])
def test_protected_read_never_discloses_late_changed_envelope(
    custodian, certificates, monkeypatch, boundary, field):
    case = scenario(custodian, certificates[0], monkeypatch)
    if boundary == "load":
        # Retrieval returns an already corrupted envelope: authentication refuses it.
        target, result = case.custody_repo.load, case.sealed
    else:
        target = case.evidence if boundary == "evidence" else case.database.close
        result = True if boundary == "evidence" else None
    def mutate(*args, **kwargs):
        object.__setattr__(case.sealed, field,
            b"N"*12 if field == "nonce" else ("f"*64 if field == "ticket_sha256" else b"PRIVATE CORRUPTION"))
        return result
    target.side_effect = mutate
    with pytest.raises(InspectionFailed): load(case)
    case.database.commit.assert_not_called()
    case.database.close.assert_called_once()
