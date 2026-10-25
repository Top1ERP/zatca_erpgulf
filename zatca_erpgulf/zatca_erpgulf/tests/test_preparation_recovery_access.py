"""WRITE-only exact local recovery tests; synthetic original/evidence, never HTTP."""

import csv
import inspect
import json
import pickle
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import preparation_recovery_access as access
from zatca_erpgulf.zatca_erpgulf import preparation_review_access as review_access
from zatca_erpgulf.zatca_erpgulf.issuing_chain import record_generated_candidate
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_preparation import build_for
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_review_access import (
    reviewer, operator, scenario as review_scenario, PermissionDenied, InspectionFailed,
)


@pytest.fixture
def recoverer(reviewer, monkeypatch):
    reviewer.denied_operations = set()
    def check(dt, operation, *, doc, user):
        if operation == "write":
            return (dt, doc.name, operation) not in reviewer.denied_operations and (dt, doc.name) not in reviewer.denied
        return reviewer.acl(dt, operation, doc=doc, user=user, raise_exception=False)
    reviewer.recovery_acl = Mock(side_effect=check)
    def v15(dt, operation, *, doc, user, raise_exception=False):
        assert raise_exception is False
        return reviewer.recovery_acl(dt, operation, doc=doc, user=user)
    def v16(dt, operation, *, doc, user, print_logs=True):
        assert print_logs is False
        return reviewer.recovery_acl(dt, operation, doc=doc, user=user)
    permission = v16 if "print_logs" in inspect.signature(review_access.has_permission).parameters else v15
    monkeypatch.setattr(access, "frappe", reviewer.runtime)
    monkeypatch.setattr(access, "_", lambda message: message)
    monkeypatch.setattr(access, "has_permission", permission)
    return reviewer


def scenario(recoverer, der, monkeypatch, *, doctype="Sales Invoice", owner="company", environment="Production", indicator="0200000"):
    case = review_scenario(recoverer, der, monkeypatch, doctype=doctype, owner=owner,
        environment=environment, indicator=indicator, state="pending", docstatus=1)
    candidate = build_for(der, case.hold.ticket)
    case.retained = access.RetainedPreparationOriginal(case.scope, case.hold, candidate)
    case.after = record_generated_candidate(case.hold.ticket.predecessor, candidate)
    case.completed_hold = replace(case.hold, original_manifest_sha256=candidate.manifest_sha256)
    case.repository.complete.return_value = (case.completed_hold, case.after)
    case.evidence = Mock(return_value=True)
    monkeypatch.setattr(access, "MariaDBPreparationHoldRepository", case.repository_factory)
    case.recovery = access.SavedPreparationRecoveryService(case.scope, case.evidence, case.factory)
    return case


def persist(case):
    return case.recovery.persist(case.invoice.name, case.retained, doctype=case.invoice.doctype)


def untouched(recoverer, case):
    recoverer.runtime.db.commit.assert_not_called()
    recoverer.runtime.db.rollback.assert_not_called()
    case.repository.reserve.assert_not_called()
    for doc in recoverer.documents.values():
        doc.save.assert_not_called()
        doc.db_set.assert_not_called()
        doc.check_permission.assert_not_called()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
def test_submitted_write_recovery_keeps_original_and_returns_metadata_only(recoverer, certificates, monkeypatch, doctype, owner, indicator):
    case = scenario(recoverer, certificates[0], monkeypatch, doctype=doctype, owner=owner, indicator=indicator)
    before = case.retained.candidate.xml_bytes
    report = persist(case)
    assert report["state"] == "PREPARATION_ORIGINAL_STORED_LOCAL_NO_REPLAY"
    assert report["local_transaction_completed"] is True
    assert all(report[name] is False for name in review_access.FALSE_FLAGS)
    assert "INV-TEST" not in json.dumps(report) and "PRIVATE" not in json.dumps(report)
    assert not {"hold_id", "uuid", "xml_bytes", "candidate", "retained", "ticket", "icv", "previous_hash"} & report.keys()
    case.repository.complete.assert_called_once_with(case.retained.hold, case.retained.candidate)
    assert case.retained.candidate.xml_bytes is before
    assert case.evidence.call_count == 4
    assert [call.kwargs["connection"] for call in case.evidence.call_args_list] == [None, case.database, case.database, None]
    assert case.database.commit.call_count == case.database.close.call_count == 1
    assert case.database.rollback.call_count == 1
    assert any(call.args[1] == "write" for call in recoverer.recovery_acl.call_args_list)
    untouched(recoverer, case)


def test_read_permission_does_not_grant_recovery_write(recoverer, certificates, monkeypatch):
    case = scenario(recoverer, certificates[0], monkeypatch)
    recoverer.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
    assert case.service.inspect(case.invoice.name)["state"] == "PENDING_ORIGINAL_UNCONFIRMED_REVIEW"
    case.factory.reset_mock()
    case.repository_factory.reset_mock()
    with pytest.raises(PermissionDenied) as error: persist(case)
    assert str(error.value) == access.DENIED_MESSAGE and error.value.__context__ is None
    case.evidence.assert_not_called()
    case.factory.assert_not_called()
    case.repository_factory.assert_not_called()
    untouched(recoverer, case)


@pytest.mark.parametrize("identity", [("Sales Invoice","INV-TEST"), ("Company","TEST"),
    ("ZATCA Multiple Setting","DEVICE"), ("Company","LINKED")])
def test_all_related_acl_precedes_evidence_and_owned_sql(recoverer, certificates, monkeypatch, identity):
    case = scenario(recoverer, certificates[0], monkeypatch, owner="linked")
    recoverer.denied.add(identity)
    recoverer.documents[identity].flags = SimpleNamespace(ignore_permissions=True)
    with pytest.raises(PermissionDenied): persist(case)
    case.evidence.assert_not_called()
    case.factory.assert_not_called()
    untouched(recoverer, case)


@pytest.mark.parametrize("status", [0, 2])
def test_draft_and_cancelled_remain_review_only_under_conservative_policy(recoverer, certificates, monkeypatch, status):
    case = scenario(recoverer, certificates[0], monkeypatch)
    case.invoice.docstatus = status
    with pytest.raises(InspectionFailed): persist(case)
    case.evidence.assert_not_called()
    case.factory.assert_not_called()
    assert case.service.inspect(case.invoice.name)["state"] == "PENDING_ORIGINAL_UNCONFIRMED_REVIEW"


@pytest.mark.parametrize("value", [False, None, 1, "True", {}, []])
def test_mandatory_evidence_requires_literal_true_before_acquisition(recoverer, certificates, monkeypatch, value):
    case = scenario(recoverer, certificates[0], monkeypatch)
    case.evidence.return_value = value
    with pytest.raises(InspectionFailed) as error: persist(case)
    assert str(error.value) == access.FAILED_MESSAGE and error.value.__context__ is None
    case.factory.assert_not_called()


@pytest.mark.parametrize("field", ["key_sha256", "manifest_sha256", "xml_bytes"])
def test_corrupt_derived_fields_or_original_are_refused_before_source_lookup(recoverer, certificates, monkeypatch, field):
    case = scenario(recoverer, certificates[0], monkeypatch)
    object.__setattr__(case.retained.candidate, field, b"PRIVATE INVALID XML" if field == "xml_bytes" else "f"*64)
    recoverer.runtime.get_doc.reset_mock()
    with pytest.raises(InspectionFailed): persist(case)
    recoverer.runtime.get_doc.assert_not_called()
    case.evidence.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("change", ["target", "doctype", "namespace"])
def test_cross_target_and_namespace_precede_saved_reads(recoverer, certificates, monkeypatch, change):
    case = scenario(recoverer, certificates[0], monkeypatch)
    name, doctype = case.invoice.name, case.invoice.doctype
    if change == "target": name = "OTHER"
    if change == "doctype": doctype = "POS Invoice"
    if change == "namespace":
        case.retained = replace(case.retained, scope=replace(case.scope,
            storage_namespace="51234567-1234-4123-8123-123456789abc"))
    recoverer.runtime.get_doc.reset_mock()
    with pytest.raises(InspectionFailed): case.recovery.persist(name, case.retained, doctype=doctype)
    recoverer.runtime.get_doc.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("stage", ["evidence", "factory", "complete", "close"])
@pytest.mark.parametrize("change", ["permission", "actor", "revision"])
def test_late_drift_refuses_disclosure_without_clearing_committed_original(recoverer, certificates, monkeypatch, stage, change):
    case = scenario(recoverer, certificates[0], monkeypatch)
    def mutate(*args, **kwargs):
        if change == "permission": recoverer.denied_operations.add(("Sales Invoice", "INV-TEST", "write"))
        if change == "actor": recoverer.runtime.session.user = "OTHER@example.test"
        if change == "revision": case.invoice.modified += timedelta(seconds=1)
        return {"evidence":True, "factory":case.database, "complete":(case.completed_hold, case.after), "close":None}[stage]
    {"evidence":case.evidence, "factory":case.factory, "complete":case.repository.complete,
        "close":case.database.close}[stage].side_effect = mutate
    with pytest.raises(InspectionFailed if change == "revision" else PermissionDenied): persist(case)
    if stage == "close": assert case.database.commit.call_count == 1
    if stage != "evidence": case.database.close.assert_called_once()
    else: case.factory.assert_not_called()
    untouched(recoverer, case)


@pytest.mark.parametrize("stage", ["factory", "complete", "commit", "close"])
def test_owned_failure_returns_unconfirmed_without_retrying_or_claiming_rollback(recoverer, certificates, monkeypatch, stage):
    case = scenario(recoverer, certificates[0], monkeypatch)
    {"factory":case.factory, "complete":case.repository.complete, "commit":case.database.commit,
        "close":case.database.close}[stage].side_effect = RuntimeError("PRIVATE driver/XML/credential")
    report = persist(case)
    assert report["state"] == "PREPARATION_RECOVERY_UNCONFIRMED_NO_REBUILD"
    assert report["local_transaction_completed"] is False
    assert case.repository.complete.call_count <= 1
    assert all(report[name] is False for name in review_access.FALSE_FLAGS)
    untouched(recoverer, case)


@pytest.mark.parametrize("stage", ["evidence", "complete", "commit", "close"])
def test_interruption_propagates_and_caller_still_has_exact_original(recoverer, certificates, monkeypatch, stage):
    case = scenario(recoverer, certificates[0], monkeypatch)
    retained = case.retained
    {"evidence":case.evidence, "complete":case.repository.complete,
        "commit":case.database.commit, "close":case.database.close}[stage].side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): persist(case)
    assert case.retained is retained
    if stage != "evidence": case.database.close.assert_called_once()


@pytest.mark.parametrize("borrowed", ["db", "raw"])
def test_borrowed_parent_is_refused_without_commit_cleanup_or_close(recoverer, certificates, monkeypatch, borrowed):
    case = scenario(recoverer, certificates[0], monkeypatch)
    recoverer.runtime.db._conn = case.database
    case.factory.return_value = recoverer.runtime.db if borrowed == "db" else case.database
    report = persist(case)
    assert report["local_transaction_completed"] is False
    case.database.rollback.assert_not_called()
    case.database.close.assert_not_called()
    case.database.commit.assert_not_called()
    case.repository.complete.assert_not_called()
    untouched(recoverer, case)


def test_presenter_translates_one_message_without_changing_english_metadata():
    path = Path(__file__).resolve().parents[2] / "translations/ar.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        translations = {row[0]:row[1] for row in csv.reader(handle) if len(row) >= 2}
    for text in (access.DENIED_MESSAGE, access.FAILED_MESSAGE, access.TITLE, *access.MESSAGES.values()):
        assert translations[text] != text
    for completed in (False, True):
        report = access._projection(completed)
        before = json.dumps(report, sort_keys=True)
        message = access.present_preparation_recovery(report, translations.__getitem__)
        assert message["message"] == translations[access.MESSAGES[report["state"]]]
        assert set(message) == {"title","message","indicator"} and json.dumps(report, sort_keys=True) == before


@pytest.mark.parametrize("change", ["extra", "state", "grant", "number"])
def test_presenter_cannot_disclose_protected_fields_or_fabricate_permissions(change):
    report = access._projection(False)
    if change == "extra": report["xml_bytes"] = "PRIVATE"
    if change == "state": report["state"] = "REPORTED"
    if change == "grant": report["replay_authorized"] = True
    if change == "number": report["local_transaction_completed"] = 1
    with pytest.raises(access.PreparationRecoveryAccessError): access.present_preparation_recovery(report, lambda text:text)


def test_protected_input_and_write_service_are_not_pickled_or_replay_capabilities(recoverer, certificates, monkeypatch):
    case = scenario(recoverer, certificates[0], monkeypatch)
    for value in (case.retained, case.recovery):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(value)
        assert case.retained.candidate.xml_bytes.decode() not in repr(value)
    assert not any(hasattr(case.recovery, name) for name in ("prepare", "reserve", "release", "send", "inspect"))


def test_even_coherent_original_substitution_by_evidence_callback_is_refused(recoverer, certificates, monkeypatch):
    case = scenario(recoverer, certificates[0], monkeypatch)
    original = case.retained.candidate
    def mutate(*args, **kwargs):
        changed = replace(original, xml_bytes=original.xml_bytes.replace(b"><", b">\n<"))
        object.__setattr__(case.retained, "candidate", changed)
        return True
    case.evidence.side_effect = mutate
    with pytest.raises(InspectionFailed): persist(case)
    case.factory.assert_not_called()


@pytest.mark.parametrize("kind", ["type", "manifest", "registration"])
def test_unexpected_repository_result_is_unconfirmed_not_success(recoverer, certificates, monkeypatch, kind):
    case = scenario(recoverer, certificates[0], monkeypatch)
    if kind == "type": case.repository.complete.return_value = (None, None)
    if kind == "manifest":
        case.repository.complete.return_value = (replace(case.completed_hold, original_manifest_sha256="f"*64), case.after)
    if kind == "registration":
        registration = replace(case.after.registration, registration_id="51234567-1234-4123-8123-123456789abc")
        case.repository.complete.return_value = (case.completed_hold, replace(case.after, registration=registration))
    assert persist(case)["local_transaction_completed"] is False
    case.database.commit.assert_not_called()
