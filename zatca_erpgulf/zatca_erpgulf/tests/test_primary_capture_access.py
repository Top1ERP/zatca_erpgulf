"""Saved WRITE ACL/resources/protected handoff, synthetic capture only."""

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

from zatca_erpgulf.zatca_erpgulf import primary_capture_access as access
from zatca_erpgulf.zatca_erpgulf import primary_receipt_access as receipt_access
from zatca_erpgulf.zatca_erpgulf.primary_capture import PrimaryCaptureRequest
from zatca_erpgulf.zatca_erpgulf.primary_receipt_custody_access import PrimaryReceiptCustodyKeys
from zatca_erpgulf.zatca_erpgulf.journal_storage import encode_dispatch_event
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import start
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_access import (
    operator, receipt_operator, scenario as receipt_scenario, untouched, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_capture import Scenario


@pytest.fixture
def capture_operator(receipt_operator, monkeypatch):
    monkeypatch.setattr(access, "frappe", receipt_operator.runtime)
    monkeypatch.setattr(access, "_", lambda message: message)
    monkeypatch.setattr(access, "has_permission", receipt_access.has_permission)
    return receipt_operator


def configure(case, cipher, observe, *, key_id="synthetic-capture"):
    case.request = PrimaryCaptureRequest(start(case.original))
    case.binding = access.PrimaryCaptureBinding(case.scope, case.original.context,
        case.original.artifact.uuid, case.original.artifact.icv, case.request.started.journal_sha256,
        case.request.started.events[0].attempt_id, hashlib.sha256(encode_dispatch_event(case.request.started.events[0])).hexdigest(),
        case.request.body_sha256, key_id)
    case.lookup.return_value = case.binding
    case.retained_results = []
    def retain(scope, result):
        assert scope == case.scope
        case.retained_results.append(result)  # Test memory custody, NOT durability proof.
        return True
    case.retainer = Mock(side_effect=retain)
    case.resources = Mock(return_value=access.PrimaryCaptureResources(case.scope,
        PrimaryReceiptCustodyKeys(case.scope, key_id, cipher), observe, case.retainer))
    case.service = access.SavedPrimaryCaptureService(case.scope, case.lookup, case.resources, case.factory)
    return case


def scenario(capture_operator, der, monkeypatch, **options):
    case = receipt_scenario(capture_operator, der, monkeypatch, **options)
    case.core = Scenario(monkeypatch, case.original, namespace=case.scope.storage_namespace)
    case.factory = Mock(side_effect=lambda scope: case.core.factory())
    configure(case, case.core.cipher, case.core.observer)
    case.sql_guard = Mock()
    monkeypatch.setattr(access, "_verify_rows", case.sql_guard)
    return case


def invoke(case):
    return case.service.capture(case.invoice.name, case.request, doctype=case.invoice.doctype)


@pytest.mark.parametrize("wrong", ["missing", "mapping", "body", "invoice", "doctype"])
def test_invalid_request_or_target_never_reaches_saved_lookup_or_resources(capture_operator, certificates, monkeypatch, wrong):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    supplied, name, doctype = case.request, case.invoice.name, case.invoice.doctype
    if wrong == "missing":
        supplied = None
    elif wrong == "mapping":
        supplied = {"started": case.request.started}
    elif wrong == "body":
        object.__setattr__(supplied, "body", b"PRIVATE forged request")
    elif wrong == "invoice":
        name = "OTHER-INVOICE"
    else:
        doctype = "POS Invoice"
    with pytest.raises(InspectionFailed) as error:
        case.service.capture(name, supplied, doctype=doctype)
    assert error.value.__context__ is None
    capture_operator.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.resources.assert_not_called()
    case.factory.assert_not_called()
    case.retainer.assert_not_called()


@pytest.mark.parametrize("status", [None, "", "Not Submitted", "REPORTED", "CLEARED", "503 Service Unavailable"])
def test_saved_status_is_neither_capture_gate_nor_acceptance_authority(capture_operator, certificates, monkeypatch, status):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    case.invoice.custom_zatca_status = status
    report = invoke(case)
    assert report["state"] == "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY"
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    untouched(capture_operator)


def test_interruption_before_core_result_still_requires_observer_original_custody(capture_operator, certificates, monkeypatch):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    originals = []
    original = case.core.observer.side_effect
    def interrupted(request):
        originals.append(original(request))  # Explicit observer-owned custody, not durable evidence.
        raise KeyboardInterrupt("PRIVATE interrupted before result transfer")
    case.core.observer.side_effect = interrupted
    with pytest.raises(KeyboardInterrupt):
        invoke(case)
    assert len(originals) == 1 and originals[0].body
    case.retainer.assert_not_called()  # No invented coordinator result/handoff acknowledgment.
    assert all(connection.closed for connection in case.core.connections)
    case.core.observer.assert_called_once()
    untouched(capture_operator)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_permissioned_capture_hands_off_protected_result_and_returns_metadata_only(capture_operator, certificates,
    monkeypatch, doctype, indicator, owner):
    case = scenario(capture_operator, certificates[0], monkeypatch, doctype=doctype, indicator=indicator, owner=owner)
    report = invoke(case)
    assert report["state"] == "RECEIPT_CAPTURED_OBSERVATION_NO_REPLAY"
    assert report["server_custody_acknowledged"] is True and report["server_custody_durable_verified"] is False
    assert all(value is False for key, value in report.items() if key.endswith(("_verified", "_authorized")))
    assert not {"request", "response", "receipt", "sealed", "uuid", "invoice_name", "body"} & report.keys()
    assert "INV-TEST" not in json.dumps(report) and "authority evidence" not in json.dumps(report)
    assert len(case.retained_results) == 1 and case.retained_results[0].sealed is case.core.sealed
    case.retainer.assert_called_once_with(case.scope, case.retained_results[0])
    case.resources.assert_called_once_with(case.scope)
    assert case.sql_guard.call_count == 6 and case.factory.call_count == 3
    case.core.observer.assert_called_once()
    assert all(connection.closed for connection in case.core.connections)
    untouched(capture_operator)


@pytest.mark.parametrize("identity", ["source", "company", "device", "linked"])
def test_acl_denial_precedes_resource_keys_and_owned_acquisition(capture_operator, certificates, monkeypatch, identity):
    case = scenario(capture_operator, certificates[0], monkeypatch, owner="linked")
    key = {"source": ("Sales Invoice", "INV-TEST", "write"), "company": ("Company", "TEST", "read"),
        "device": ("ZATCA Multiple Setting", "DEVICE", "read"), "linked": ("Company", "LINKED", "read")}[identity]
    capture_operator.denied_operations.add(key)
    capture_operator.documents[key[:2]].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied) as error:
        invoke(case)
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.lookup.assert_not_called()
    case.resources.assert_not_called()
    case.factory.assert_not_called()
    case.retainer.assert_not_called()
    untouched(capture_operator)


@pytest.mark.parametrize("user,roles,site", [("Guest", ["System Manager"], "private.test"),
    (None, ["System Manager"], "private.test"), ("manager@example.test", [], "private.test"), ("Administrator", [], "other.test")])
def test_actor_role_site_checked_before_saved_source(capture_operator, certificates, monkeypatch, user, roles, site):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    capture_operator.runtime.session.user, capture_operator.runtime.local.site = user, site
    capture_operator.runtime.get_roles.return_value = roles
    with pytest.raises(PermissionDenied):
        invoke(case)
    capture_operator.runtime.get_doc.assert_not_called()
    case.resources.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("field,value", [("attempt_id", "50000000-0000-4000-8000-000000000001"),
    ("start_event_sha256", "0" * 64), ("request_sha256", "0" * 64), ("journal_sha256", "0" * 64)])
def test_exact_server_start_and_request_binding_precedes_resources(capture_operator, certificates, monkeypatch, field, value):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    case.lookup.return_value = replace(case.binding, **{field: value})
    with pytest.raises(InspectionFailed) as error:
        invoke(case)
    assert error.value.__context__ is None
    case.resources.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("wrong", ["type", "scope", "key", "observer", "retainer", "provider"])
def test_scoped_resource_shape_before_any_owned_sql(capture_operator, certificates, monkeypatch, wrong):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    if wrong == "type":
        case.resources.return_value = {}
    elif wrong == "scope":
        other = replace(case.scope, site="other.test")
        keys = PrimaryReceiptCustodyKeys(other, "synthetic-capture", case.core.cipher)
        case.resources.return_value = access.PrimaryCaptureResources(other, keys, case.core.observer, case.retainer)
    elif wrong == "key":
        keys = PrimaryReceiptCustodyKeys(case.scope, "other-key", case.core.cipher)
        case.resources.return_value = access.PrimaryCaptureResources(case.scope, keys, case.core.observer, case.retainer)
    elif wrong in ("observer", "retainer"):
        object.__setattr__(case.resources.return_value, "observe" if wrong == "observer" else "retain", None)
    else:
        case.resources.side_effect = RuntimeError("PRIVATE resource lookup")
    with pytest.raises(InspectionFailed) as error:
        invoke(case)
    assert error.value.__context__ is None
    case.factory.assert_not_called()
    case.core.observer.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "resources", "factory", "observer", "last-close", "retainer"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_late_denial_retains_result_before_refusing_metadata(capture_operator, certificates, monkeypatch, stage, change):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    def mutate():
        if change == "permission":
            capture_operator.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
        elif change == "actor":
            capture_operator.runtime.session.user = "other-manager@example.test"
        else:
            case.invoice.modified += timedelta(seconds=1)
    if stage in ("lookup", "resources", "factory"):
        target = {"lookup": case.lookup, "resources": case.resources, "factory": case.factory}[stage]
        original = target.side_effect
        def changed(*args):
            result = original(*args) if original is not None else target.return_value
            mutate()
            return result
        target.side_effect = changed
    elif stage == "observer":
        original = case.core.observer.side_effect
        def observe(request):
            response = original(request)
            mutate()
            return response  # Never drop the complete response on post-callback denial.
        case.core.observer.side_effect = observe
    elif stage == "last-close":
        original = case.core.factory.side_effect
        def acquire():
            connection = original()
            if connection.index == 2:
                close = connection.close.side_effect
                def changed_close():
                    close()
                    mutate()
                connection.close.side_effect = changed_close
            return connection
        case.core.factory.side_effect = acquire
    else:
        original = case.retainer.side_effect
        def retain(*args):
            outcome = original(*args)
            mutate()
            return outcome
        case.retainer.side_effect = retain
    with pytest.raises(InspectionFailed if change == "revision" else PermissionDenied) as error:
        invoke(case)
    assert error.value.__context__ is None
    if stage in ("lookup", "resources"):
        case.retainer.assert_not_called()
        case.factory.assert_not_called()
    else:
        assert len(case.retained_results) == 1
        if stage in ("observer", "last-close", "retainer"):
            assert case.retained_results[0].response is not None and case.retained_results[0].sealed is not None
    assert all(connection.closed for connection in case.core.connections)
    untouched(capture_operator)


@pytest.mark.parametrize("ack", [None, False, 1, "yes", "raise", "interrupt"])
def test_handoff_failure_keeps_exact_result_in_hidden_server_recovery_exception(capture_operator, certificates, monkeypatch, ack):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    case.retainer.side_effect = KeyboardInterrupt("PRIVATE interruption") if ack == "interrupt" else RuntimeError("PRIVATE custody") if ack == "raise" else None
    case.retainer.return_value = ack
    with pytest.raises(access.PrimaryCaptureHandoffRequired) as error:
        invoke(case)
    assert error.value.result.sealed is case.core.sealed
    assert error.value.interrupted is (ack == "interrupt")
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value) and "INV-TEST" not in repr(error.value)
    case.core.observer.assert_called_once()
    with pytest.raises(ValueError):
        pickle.dumps(error.value)


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_recognizable_borrowed_parent_untouched_and_unknown_result_handed_off(capture_operator, certificates, monkeypatch, borrowed):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    raw = SimpleNamespace(cursor=Mock(), commit=Mock(), rollback=Mock(), close=Mock())
    capture_operator.runtime.db._conn = raw
    case.factory.side_effect = None
    case.factory.return_value = capture_operator.runtime.db if borrowed == "db" else raw
    report = invoke(case)
    assert report["state"] == "RESERVATION_UNCONFIRMED_NO_OBSERVER"
    assert len(case.retained_results) == 1
    for handle in (capture_operator.runtime.db, raw):
        handle.commit.assert_not_called()
        handle.rollback.assert_not_called()
    raw.close.assert_not_called()
    case.core.observer.assert_not_called()


@pytest.mark.parametrize("failure", ["denied", "failed", "handoff"])
def test_arabic_static_messages_and_protected_nonpickleable_dependencies(capture_operator, certificates, monkeypatch, failure):
    case = scenario(capture_operator, certificates[0], monkeypatch)
    with (Path(__file__).resolve().parents[2] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(access, "_", lambda message: entries[message])
    if failure == "denied":
        capture_operator.denied.add(("Sales Invoice", "INV-TEST"))
    elif failure == "failed":
        case.resources.side_effect = RuntimeError("PRIVATE resource")
    else:
        case.retainer.side_effect = None
        case.retainer.return_value = False
    exception = {"denied": PermissionDenied, "failed": InspectionFailed, "handoff": access.PrimaryCaptureHandoffRequired}[failure]
    message = {"denied": access.DENIED_MESSAGE, "failed": access.FAILED_MESSAGE, "handoff": access.HANDOFF_MESSAGE}[failure]
    with pytest.raises(exception) as error:
        invoke(case)
    assert str(error.value) == entries[message] and error.value.__context__ is None
    for value in (case.binding, case.resources.return_value, case.service):
        assert "INV-TEST" not in repr(value)
        with pytest.raises(ValueError):
            pickle.dumps(value)


def test_no_runtime_activation_http_or_raw_export_endpoint():
    source = inspect.getsource(access)
    for forbidden in ("@frappe.whitelist", "import requests", "get_password(", "CREATE TABLE", ".save(", ".db_set("):
        assert forbidden not in source
    assert set(inspect.signature(access.SavedPrimaryCaptureService.capture).parameters) == {"self", "invoice_name", "supplied", "doctype"}
