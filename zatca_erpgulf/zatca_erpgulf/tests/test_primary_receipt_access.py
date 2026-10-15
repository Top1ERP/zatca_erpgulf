"""Saved source/WRITE ACL and exact local receipt binding, no tenant or HTTP."""

import ast
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

from zatca_erpgulf.zatca_erpgulf import primary_receipt_access as access
from zatca_erpgulf.zatca_erpgulf import primary_receipt_persistence as persistence
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import append_dispatch_event
from zatca_erpgulf.zatca_erpgulf.journal_storage import encode_dispatch_event
from zatca_erpgulf.zatca_erpgulf.tests.test_advance_source_access import operator, NOW, PermissionDenied, InspectionFailed
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_persistence import retained
from zatca_erpgulf.zatca_erpgulf.tests.test_qr_source_access import scenario as qr_scenario


@pytest.fixture(params=[15, 16])
def receipt_operator(operator, monkeypatch, request):
    operator.denied_operations = set()
    def permission(dt, operation, *, doc, user, **options):
        assert operation == ("write" if dt in ("Sales Invoice", "POS Invoice") else "read")
        assert list(options.values()) == [False]  # Quiet signature-compatible ACL.
        return (dt, doc.name) not in operator.denied and (dt, doc.name, operation) not in operator.denied_operations
    operator.acl = Mock(side_effect=permission)
    def v15(dt, operation, *, doc, user, raise_exception=True):
        return operator.acl(dt, operation, doc=doc, user=user, raise_exception=raise_exception)
    def v16(dt, operation, *, doc, user, print_logs=True):
        return operator.acl(dt, operation, doc=doc, user=user, print_logs=print_logs)
    monkeypatch.setattr(access, "frappe", operator.runtime)
    monkeypatch.setattr(access, "_", lambda message: message)
    monkeypatch.setattr(access, "has_permission", v15 if request.param == 15 else v16)
    return operator


def scenario(receipt_operator, der, monkeypatch, *, doctype="Sales Invoice", indicator="0200000", environment="Production",
    owner="company", unknown=False):
    case = qr_scenario(receipt_operator, der, monkeypatch, doctype=doctype, indicator=indicator, environment=environment, owner=owner)
    case.retained = retained(case.original, namespace=case.scope.storage_namespace, unknown=unknown)
    case.before, case.after = case.retained.before, append_dispatch_event(case.retained.before, case.retained.response_event)
    case.binding = access.PrimaryReceiptBinding(case.scope, case.original.context,
        case.original.artifact.uuid, case.original.artifact.icv, case.before.journal_sha256,
        case.retained.response_event.attempt_id, hashlib.sha256(encode_dispatch_event(case.retained.response_event)).hexdigest())
    case.lookup.return_value = case.binding
    case.repository.load.return_value, case.repository.append.return_value = case.before, case.after
    monkeypatch.setattr(persistence, "MariaDBJournalRepository", case.repository_factory)
    case.service = access.SavedPrimaryReceiptService(case.scope, case.lookup, case.factory)
    return case


def persist(case):
    return case.service.persist(case.invoice.name, case.retained, doctype=case.invoice.doctype)


def untouched(operator):
    operator.runtime.db.commit.assert_not_called()
    operator.runtime.db.rollback.assert_not_called()
    for doc in operator.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
@pytest.mark.parametrize("unknown", [False, True])
def test_exact_permissioned_receipt_uses_one_owned_write_transaction(receipt_operator, certificates, monkeypatch,
    doctype, indicator, owner, unknown):
    case = scenario(receipt_operator, certificates[0], monkeypatch, doctype=doctype, indicator=indicator, owner=owner, unknown=unknown)
    result = persist(case)
    assert result.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and result.receipt is case.retained
    case.lookup.assert_called_once()
    case.factory.assert_called_once_with(case.scope)
    case.database.rollback.assert_called_once()  # Clear owned handle before guards.
    case.database.commit.assert_called_once()
    case.database.close.assert_called_once()
    case.repository.append.assert_called_once_with(case.original.key_sha256, case.retained.response_event,
        expected_journal_sha256=case.before.journal_sha256)
    assert all(value is False for key, value in result.diagnostic_projection().items() if key.endswith(("_verified", "_authorized")))
    assert "PRIVATE" not in json.dumps(result.diagnostic_projection())
    untouched(receipt_operator)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("status", [None, "", "Not Submitted", "REPORTED", "CLEARED", "503 Service Unavailable"])
def test_current_invoice_status_is_not_acceptance_or_receipt_storage_authority(receipt_operator, certificates, monkeypatch, doctype, status):
    case = scenario(receipt_operator, certificates[0], monkeypatch, doctype=doctype)
    case.invoice.custom_zatca_status = status
    assert persist(case).state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY"
    untouched(receipt_operator)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_environment_is_bound_without_sending_or_switching_routes(receipt_operator, certificates, monkeypatch, environment, doctype):
    case = scenario(receipt_operator, certificates[0], monkeypatch, doctype=doctype, environment=environment)
    result = persist(case)
    assert result.receipt is case.retained and result.receipt.before.candidate.context.route.environment == environment
    untouched(receipt_operator)


@pytest.mark.parametrize("invalid", [None, {}, "PRIVATE invalid receipt"])
def test_bad_protected_input_is_rejected_before_lookup_or_sql(receipt_operator, certificates, monkeypatch, invalid):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    with pytest.raises(InspectionFailed) as error:
        case.service.persist(case.invoice.name, invalid)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    receipt_operator.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.factory.assert_not_called()


def test_source_guard_never_loads_legacy_secrets_or_uses_document_permission_shortcuts(receipt_operator, certificates, monkeypatch):
    case = scenario(receipt_operator, certificates[0], monkeypatch, owner="linked")
    for doc in receipt_operator.documents.values():
        original = doc.get
        def get(name, default=None, *, saved=original):
            if name != "custom__use_company_certificate__keys":  # Non-secret owner-selection flag.
                assert not any(part in name for part in ("private_key", "certificate", "basic_auth", "final_auth", "csid"))
            return saved(name, default)
        doc.get = get
    assert persist(case).state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY"
    untouched(receipt_operator)


def test_interruption_cleans_owned_transaction_without_mutating_parent_or_losing_input(receipt_operator, certificates, monkeypatch):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    original = case.retained
    case.repository.append.side_effect = KeyboardInterrupt("Synthetic interrupted write")
    with pytest.raises(KeyboardInterrupt):
        persist(case)
    assert case.retained is original
    assert case.database.rollback.call_count == 2
    case.database.close.assert_called_once()
    case.database.commit.assert_not_called()
    untouched(receipt_operator)


@pytest.mark.parametrize("identity", ["source", "company", "device", "linked"])
def test_saved_write_or_related_read_denial_precedes_lookup_and_acquisition(receipt_operator, certificates, monkeypatch, identity):
    case = scenario(receipt_operator, certificates[0], monkeypatch, owner="linked")
    key = {"source": ("Sales Invoice", "INV-TEST", "write"), "company": ("Company", "TEST", "read"),
        "device": ("ZATCA Multiple Setting", "DEVICE", "read"), "linked": ("Company", "LINKED", "read")}[identity]
    receipt_operator.denied_operations.add(key)
    receipt_operator.documents[key[:2]].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as error:
        persist(case)
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.lookup.assert_not_called()
    case.factory.assert_not_called()
    untouched(receipt_operator)


@pytest.mark.parametrize("user,roles,site", [("Guest", ["System Manager"], "private.test"),
    (None, ["System Manager"], "private.test"), ("manager@example.test", [], "private.test"), ("Administrator", [], "other.test")])
def test_actor_role_site_denial_precedes_saved_rows_and_receipt_processing(receipt_operator, certificates, monkeypatch, user, roles, site):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    receipt_operator.runtime.session.user, receipt_operator.runtime.local.site = user, site
    receipt_operator.runtime.get_roles.return_value = roles
    with pytest.raises(PermissionDenied):
        persist(case)
    receipt_operator.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("change", ["attempt", "event", "before", "epoch", "namespace", "owner", "route", "uuid", "icv", "doctype", "name", "revision", "docstatus"])
def test_exact_attempt_response_and_saved_binding_before_sql(receipt_operator, certificates, monkeypatch, change):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    other_id = "50000000-0000-4000-8000-000000000001"
    if change == "attempt":
        case.lookup.return_value = replace(case.binding, attempt_id=other_id)
    elif change == "event":
        case.lookup.return_value = replace(case.binding, response_event_sha256="0" * 64)
    elif change == "before":
        case.lookup.return_value = replace(case.binding, journal_sha256="0" * 64)
    elif change == "epoch":
        context = replace(case.binding.context, credential_epoch=replace(case.binding.context.credential_epoch, version_id=other_id))
        case.lookup.return_value = replace(case.binding, context=context)
    elif change == "namespace":
        case.retained = replace(case.retained, storage_namespace=other_id)
    elif change == "owner":
        case.invoice.custom_zatca_pos_name = "MISSING-DEVICE"
    elif change == "route":
        case.company.custom_production_url = "https://other.invalid/phase2"
    elif change == "uuid":
        case.invoice.custom_uuid = other_id
    elif change == "icv":
        case.invoice.custom_zatca_icv += 1
    elif change in ("doctype", "name"):
        with pytest.raises(InspectionFailed):
            case.service.persist("OTHER" if change == "name" else case.invoice.name, case.retained,
                doctype="POS Invoice" if change == "doctype" else "Sales Invoice")
        receipt_operator.runtime.get_doc.assert_not_called()
        return
    elif change == "revision":
        def drift(*args):
            case.invoice.modified += timedelta(seconds=1)
            return case.binding
        case.lookup.side_effect = drift
    else:
        case.invoice.docstatus = 2
    with pytest.raises(InspectionFailed) as error:
        persist(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()
    untouched(receipt_operator)


@pytest.mark.parametrize("stage", ["lookup", "factory", "load", "append", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_revocation_or_change_prevents_result_disclosure(receipt_operator, certificates, monkeypatch, stage, change):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    def mutate(*args, **kwargs):
        if change == "permission":
            receipt_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
        elif change == "actor":
            receipt_operator.runtime.session.user = "other-manager@example.test"
        else:
            case.invoice.modified += timedelta(seconds=1)
        return {"lookup": case.binding, "factory": case.database, "load": case.before,
            "append": case.after, "close": None}[stage]
    {"lookup": case.lookup, "factory": case.factory, "load": case.repository.load,
        "append": case.repository.append, "close": case.database.close}[stage].side_effect = mutate
    with pytest.raises(PermissionDenied if change != "revision" else InspectionFailed) as error:
        persist(case)
    assert error.value.__context__ is None
    if stage != "lookup":
        case.database.close.assert_called_once()
    if stage != "close":
        case.database.commit.assert_not_called()
    else:
        case.database.commit.assert_called_once()  # Commit cannot be undone by a later ACL change.
    untouched(receipt_operator)


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_borrowed_parent_handles_are_not_committed_rolled_back_or_closed(receipt_operator, certificates, monkeypatch, borrowed):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    raw = SimpleNamespace(commit=Mock(), rollback=Mock(), close=Mock(), cursor=Mock())
    receipt_operator.runtime.db._conn = raw
    case.factory.return_value = receipt_operator.runtime.db if borrowed == "db" else raw
    result = persist(case)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and result.receipt is case.retained
    for handle in (receipt_operator.runtime.db, raw):
        handle.commit.assert_not_called()
        handle.rollback.assert_not_called()
    raw.close.assert_not_called()
    case.repository_factory.assert_not_called()


@pytest.mark.parametrize("stage", ["factory", "load", "append", "commit", "rollback", "close"])
def test_storage_uncertainty_keeps_exact_protected_input_without_retry(receipt_operator, certificates, monkeypatch, stage):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    {"factory": case.factory, "load": case.repository.load, "append": case.repository.append,
        "commit": case.database.commit, "rollback": case.database.rollback, "close": case.database.close}[stage].side_effect = RuntimeError("PRIVATE storage detail")
    result = persist(case)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and result.receipt is case.retained
    assert "PRIVATE" not in repr(result) and "PRIVATE" not in json.dumps(result.diagnostic_projection())
    case.factory.assert_called_once()
    if stage != "factory":
        case.database.close.assert_called_once()
    untouched(receipt_operator)


@pytest.mark.parametrize("failure", ["denied", "failed"])
def test_operator_errors_are_static_unchained_arabic_keys(receipt_operator, certificates, monkeypatch, failure):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(access, "_", lambda message: entries[message])
    if failure == "denied":
        receipt_operator.denied.add(("Sales Invoice", "INV-TEST"))
    else:
        case.lookup.side_effect = RuntimeError("PRIVATE lookup details")
    with pytest.raises(PermissionDenied if failure == "denied" else InspectionFailed) as error:
        persist(case)
    message = access.DENIED_MESSAGE if failure == "denied" else access.FAILED_MESSAGE
    assert str(error.value) == entries[message] and entries[message] != message and error.value.__context__ is None
    case.factory.assert_not_called()


def test_service_and_binding_are_protected_and_not_public_json_endpoints(receipt_operator, certificates, monkeypatch):
    case = scenario(receipt_operator, certificates[0], monkeypatch)
    for value in (case.binding, case.service):
        assert "PRIVATE" not in repr(value) and "INV-TEST" not in repr(value)
        with pytest.raises(ValueError):
            pickle.dumps(value)
    parameters = inspect.signature(case.service.persist).parameters
    assert set(parameters) == {"invoice_name", "receipt", "doctype"}
    source = inspect.getsource(access)
    calls = {node.func.attr for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls.intersection({"post", "get_password", "save", "db_set", "set_value", "connect"})
    assert "whitelist" not in source.replace("No whitelist", "No public registration")
