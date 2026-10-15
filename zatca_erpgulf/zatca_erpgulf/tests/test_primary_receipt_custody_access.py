"""Protected custody ACL/keys/owned SQL tests with synthetic saved sources."""

import csv
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib
import inspect
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import primary_receipt_access as receipt_access
from zatca_erpgulf.zatca_erpgulf import primary_receipt_custody_access as access
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody import PrimaryReceiptCustodyCipher, encode_retained_receipt
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_access import (
    operator, receipt_operator, scenario as receipt_scenario, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates


@pytest.fixture
def custody_operator(receipt_operator, monkeypatch):
    monkeypatch.setattr(access, "frappe", receipt_operator.runtime)
    monkeypatch.setattr(access, "_", lambda message: message)
    monkeypatch.setattr(access, "has_permission", receipt_access.has_permission)
    return receipt_operator


def configure(case):
    """Explicit synthetic keys/declarations, never production key discovery."""
    case.cipher = PrimaryReceiptCustodyCipher({"synthetic-custody": b"A" * 32})
    case.sealed = case.cipher.seal(case.retained, key_id="synthetic-custody")
    case.binding = access.PrimaryReceiptCustodyBinding(case.scope, case.original.context,
        case.original.artifact.uuid, case.original.artifact.icv, case.before.journal_sha256,
        case.binding.attempt_id, case.binding.response_event_sha256,
        hashlib.sha256(encode_retained_receipt(case.retained)).hexdigest(), "synthetic-custody")
    case.lookup.return_value = case.binding
    case.keys = Mock(return_value=access.PrimaryReceiptCustodyKeys(case.scope, "synthetic-custody", case.cipher))
    case.custody_repository = Mock()
    case.custody_repository.stage.return_value = case.sealed
    case.custody_repository.load.return_value = case.sealed
    case.custody_repository_factory = Mock(return_value=case.custody_repository)
    case.service = access.SavedPrimaryReceiptCustodyService(case.scope, case.lookup, case.keys, case.factory)
    return case


def scenario(custody_operator, der, monkeypatch, **options):
    case = configure(receipt_scenario(custody_operator, der, monkeypatch, **options))
    monkeypatch.setattr(access, "MariaDBPrimaryReceiptCustodyRepository", case.custody_repository_factory)
    return case


def invoke(case, operation):
    if operation == "stage":
        return case.service.stage(case.invoice.name, case.sealed, doctype=case.invoice.doctype)
    return case.service.load(case.invoice.name, doctype=case.invoice.doctype)


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
@pytest.mark.parametrize("unknown", [False, True])
def test_shared_acl_source_binding_keys_then_owned_custody(custody_operator, certificates, monkeypatch,
    operation, doctype, indicator, owner, unknown):
    case = scenario(custody_operator, certificates[0], monkeypatch,
        doctype=doctype, indicator=indicator, owner=owner, unknown=unknown)
    # No sealing/resealing inside this service, including storage uncertainty.
    monkeypatch.setattr(PrimaryReceiptCustodyCipher, "seal", Mock(side_effect=AssertionError("Never reseal")))
    result = invoke(case, operation)
    assert result.sealed is case.sealed
    assert result.state == ("CUSTODY_STORED_OBSERVATION_NO_REPLAY" if operation == "stage" else "CUSTODY_READ_OBSERVATION_NO_REPLAY")
    case.lookup.assert_called_once()
    case.keys.assert_called_once_with(case.scope)
    case.factory.assert_called_once_with(case.scope)
    assert case.database.commit.call_count == (1 if operation == "stage" else 0)
    assert case.database.rollback.call_count == (1 if operation == "stage" else 2)
    case.database.close.assert_called_once()
    if operation == "stage":
        case.custody_repository.stage.assert_called_once_with(case.sealed)
    else:
        case.custody_repository.load.assert_called_once_with(case.original.key_sha256, case.binding.attempt_id)
    report = result.diagnostic_projection()
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert "INV-TEST" not in json.dumps(report) and "PRIVATE" not in repr(result)
    assert not hasattr(result, "receipt") and not hasattr(result, "xml_bytes")
    untouched(custody_operator)


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("identity", ["source", "company", "device", "linked"])
def test_write_and_related_read_acl_precede_keys_and_sql(custody_operator, certificates, monkeypatch, operation, identity):
    case = scenario(custody_operator, certificates[0], monkeypatch, owner="linked")
    key = {"source": ("Sales Invoice", "INV-TEST", "write"), "company": ("Company", "TEST", "read"),
        "device": ("ZATCA Multiple Setting", "DEVICE", "read"), "linked": ("Company", "LINKED", "read")}[identity]
    custody_operator.denied_operations.add(key)
    custody_operator.documents[key[:2]].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as error:
        invoke(case, operation)
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.lookup.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()
    untouched(custody_operator)


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("user,roles,site", [("Guest", ["System Manager"], "private.test"),
    (None, ["System Manager"], "private.test"), ("manager@example.test", [], "private.test"), ("Administrator", [], "other.test")])
def test_actor_before_source_keys_and_cipher(custody_operator, certificates, monkeypatch, operation, user, roles, site):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    custody_operator.runtime.session.user, custody_operator.runtime.local.site = user, site
    custody_operator.runtime.get_roles.return_value = roles
    with pytest.raises(PermissionDenied):
        invoke(case, operation)
    custody_operator.runtime.get_doc.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("invalid", [None, {}, "PRIVATE", True])
def test_invalid_protected_stage_input_never_loads_rows_keys_or_sql(custody_operator, certificates, monkeypatch, invalid):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    with pytest.raises(InspectionFailed) as error:
        case.service.stage(case.invoice.name, invalid)
    assert error.value.__context__ is None
    custody_operator.runtime.get_doc.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("field,value", [("storage_namespace", "50000000-0000-4000-8000-000000000001"),
    ("candidate_sha256", "0" * 64), ("attempt_id", "50000000-0000-4000-8000-000000000001"),
    ("predecessor_sha256", "0" * 64), ("receipt_sha256", "0" * 64), ("key_id", "other-key")])
def test_envelope_metadata_mismatch_precedes_key_acquisition(custody_operator, certificates, monkeypatch, field, value):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    case.sealed = replace(case.sealed, **{field: value})
    with pytest.raises(InspectionFailed):
        invoke(case, "stage")
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("wrong", ["type", "scope", "key", "cipher", "provider"])
def test_wrong_scoped_resources_never_acquire_sql(custody_operator, certificates, monkeypatch, operation, wrong):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    if wrong == "type":
        case.keys.return_value = {"PRIVATE": True}
    elif wrong == "scope":
        scope = replace(case.scope, site="other.test")
        case.keys.return_value = access.PrimaryReceiptCustodyKeys(scope, "synthetic-custody", case.cipher)
    elif wrong == "key":
        case.keys.return_value = access.PrimaryReceiptCustodyKeys(case.scope, "other-key", case.cipher)
    elif wrong == "cipher":
        object.__setattr__(case.keys.return_value, "cipher", None)
    else:
        case.keys.side_effect = RuntimeError("PRIVATE key provider")
    with pytest.raises(InspectionFailed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    case.factory.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("stage", ["lookup", "keys", "factory", "repository", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_revocation_or_source_change_never_discloses_result(custody_operator, certificates, monkeypatch, operation, stage, change):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    def drift(*args, **kwargs):
        if change == "permission":
            custody_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
        elif change == "actor":
            custody_operator.runtime.session.user = "other-manager@example.test"
        else:
            case.invoice.modified += timedelta(seconds=1)
        return {"lookup": case.binding, "keys": access.PrimaryReceiptCustodyKeys(case.scope, "synthetic-custody", case.cipher),
            "factory": case.database, "repository": case.sealed, "close": None}[stage]
    repository_method = case.custody_repository.stage if operation == "stage" else case.custody_repository.load
    {"lookup": case.lookup, "keys": case.keys, "factory": case.factory,
        "repository": repository_method, "close": case.database.close}[stage].side_effect = drift
    with pytest.raises(InspectionFailed if change == "revision" else PermissionDenied) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    if stage in ("lookup", "keys"):
        case.factory.assert_not_called()
    else:
        case.database.close.assert_called_once()
    assert case.database.commit.call_count == (1 if operation == "stage" and stage == "close" else 0)
    untouched(custody_operator)


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_borrowed_parent_is_never_cleaned_or_committed(custody_operator, certificates, monkeypatch, operation, borrowed):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    raw = SimpleNamespace(cursor=Mock(), commit=Mock(), rollback=Mock(), close=Mock())
    custody_operator.runtime.db._conn = raw
    case.factory.return_value = custody_operator.runtime.db if borrowed == "db" else raw
    if operation == "stage":
        result = invoke(case, operation)
        assert result.state == "CUSTODY_COMMIT_UNCONFIRMED_NO_REPLAY" and result.sealed is case.sealed
    else:
        with pytest.raises(InspectionFailed):
            invoke(case, operation)
    for handle in (raw, custody_operator.runtime.db):
        handle.commit.assert_not_called()
        handle.rollback.assert_not_called()
    raw.close.assert_not_called()
    case.custody_repository_factory.assert_not_called()


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("fault", ["factory", "repository", "rollback", "close", "interrupt"])
def test_storage_cleanup_uncertainty_preserves_input_and_never_retries(custody_operator, certificates, monkeypatch, operation, fault):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    method = case.custody_repository.stage if operation == "stage" else case.custody_repository.load
    target = {"factory": case.factory, "repository": method, "rollback": case.database.rollback,
        "close": case.database.close, "interrupt": method}[fault]
    target.side_effect = KeyboardInterrupt("Synthetic interruption") if fault == "interrupt" else RuntimeError("PRIVATE storage")
    original = case.sealed
    if fault == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            invoke(case, operation)
    elif operation == "stage":
        result = invoke(case, operation)
        assert result.state == "CUSTODY_COMMIT_UNCONFIRMED_NO_REPLAY" and result.sealed is original
    else:
        with pytest.raises(InspectionFailed) as error:
            invoke(case, operation)
        assert error.value.__context__ is None
    case.factory.assert_called_once()
    if fault != "factory":
        case.database.close.assert_called_once()
    untouched(custody_operator)


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("fault", ["ciphertext", "response-declaration", "context", "epoch"])
def test_authenticated_exact_receipt_binding_before_write_or_disclosure(custody_operator, certificates,
    monkeypatch, operation, fault):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    if fault == "ciphertext":
        case.sealed = replace(case.sealed, ciphertext=b"PRIVATE invalid ciphertext")
        case.custody_repository.load.return_value = case.sealed
    elif fault == "response-declaration":
        case.lookup.return_value = replace(case.binding, response_event_sha256="0" * 64)
    else:
        if fault == "context":
            context = replace(case.binding.context, source_snapshot_sha256="0" * 64)
        else:
            epoch = replace(case.binding.context.credential_epoch, version_id="50000000-0000-4000-8000-000000000001")
            context = replace(case.binding.context, credential_epoch=epoch)
        case.lookup.return_value = replace(case.binding, context=context)
    with pytest.raises(InspectionFailed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None
    case.keys.assert_called_once()
    case.database.commit.assert_not_called()
    if operation == "stage":
        case.factory.assert_not_called()
    else:
        case.database.close.assert_called_once()


@pytest.mark.parametrize("operation", ["stage", "load"])
@pytest.mark.parametrize("status", [None, "Not Submitted", "REPORTED", "CLEARED", "503 Service Unavailable"])
def test_current_status_is_never_custody_or_remote_acceptance_proof(custody_operator, certificates, monkeypatch, operation, status):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    case.invoice.custom_zatca_status = status
    result = invoke(case, operation)
    assert result.sealed is case.sealed
    assert result.diagnostic_projection()["remote_acceptance_verified"] is False
    untouched(custody_operator)


@pytest.mark.parametrize("failure", ["denied", "failed"])
@pytest.mark.parametrize("operation", ["stage", "load"])
def test_static_unchained_arabic_messages(custody_operator, certificates, monkeypatch, operation, failure):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(access, "_", lambda message: entries[message])
    if failure == "denied":
        custody_operator.denied.add(("Sales Invoice", "INV-TEST"))
    else:
        case.keys.side_effect = RuntimeError("PRIVATE provider detail")
    with pytest.raises(PermissionDenied if failure == "denied" else InspectionFailed) as error:
        invoke(case, operation)
    message = access.DENIED_MESSAGE if failure == "denied" else access.FAILED_MESSAGE
    assert str(error.value) == entries[message] and entries[message] != message and error.value.__context__ is None
    case.factory.assert_not_called()


def test_protected_bindings_keys_results_and_service_are_not_pickle_or_operator_json(custody_operator, certificates, monkeypatch):
    case = scenario(custody_operator, certificates[0], monkeypatch)
    result = invoke(case, "load")
    for value in (case.binding, case.keys.return_value, case.service, result):
        assert "INV-TEST" not in repr(value) and "synthetic-custody" not in repr(value)
        with pytest.raises(ValueError):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        result.sealed = None
    assert set(inspect.signature(case.service.load).parameters) == {"invoice_name", "doctype"}
    source = inspect.getsource(access)
    for forbidden in ("@frappe.whitelist", "import requests", ".seal(", "CREATE TABLE", "get_password(", ".save(", ".db_set("):
        assert forbidden not in source
