"""Permission/revision gates for internal retained diagnostics; no actual site."""

import csv
from inspect import signature
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import event_log, primary_reconciliation_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_event_log_contract import writer
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_access import operator, receipt_operator, PermissionDenied
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_reconciliation_access import pair_operator, scenario, invoke


@pytest.fixture
def diagnostic_operator(pair_operator, writer, monkeypatch):
    """Keep source ACL and normal diagnostic insertion as separate boundaries."""
    original = access.has_permission
    state = SimpleNamespace(source=pair_operator, writer=writer, create=True, create_calls=[])
    def permission(dt, operation, *, doc, user, **options):
        if dt == event_log.EVENT_LOG_DOCTYPE and operation == "create":
            assert doc is None and user == pair_operator.runtime.session.user
            assert list(options.values()) == [False]
            state.create_calls.append((user, tuple(options)))
            return state.create
        return original(dt, operation, doc=doc, user=user, **options)
    # Preserve the actual v15/v16-shaped signature selected by the source fixture.
    permission.__signature__ = signature(original)
    monkeypatch.setattr(access, "has_permission", permission)
    return state


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_saved_diagnostic_checks_source_and_create_and_returns_metadata_only(diagnostic_operator, certificates,
    monkeypatch, doctype, indicator, owner):
    op = diagnostic_operator
    case = scenario(op.source, certificates[0], monkeypatch, mode="matched", doctype=doctype, indicator=indicator, owner=owner)
    before = case.corecase.before_state
    report = invoke(case, "stage_diagnostic")
    assert report["state"] == "DIAGNOSTIC_INSERT_RETURNED_OBSERVATION_NO_REPLAY"
    assert all(value is False for key, value in report.items() if key != "state")
    assert not {"request", "sealed", "body", "response", "uuid", "invoice_name", "key_id"} & report.keys()
    assert "INV-TEST" not in json.dumps(report)
    assert case.factory.call_count == 3  # Pair inspection + fresh source checks before/after insertion.
    assert case.sql_guard.call_count == 4  # Two pair guards + two fresh source guards.
    assert all(owned.closed and owned.commit.call_count == 0 for owned in case.corecase.core.connections[3:])
    op.writer.doc.insert.assert_called_once_with(ignore_permissions=False)
    op.writer.runtime.db.commit.assert_not_called()
    op.writer.runtime.db.rollback.assert_not_called()
    assert (case.corecase.core.journal, case.corecase.core.sealed) == before
    case.corecase.core.observer.assert_called_once()


@pytest.mark.parametrize("value", [False, None, 1, "yes"])
def test_create_permission_denial_precedes_source_lookup_keys_and_sql(diagnostic_operator, certificates, monkeypatch, value):
    op = diagnostic_operator
    case = scenario(op.source, certificates[0], monkeypatch, mode="matched")
    op.create = value
    with pytest.raises(PermissionDenied) as raised:
        invoke(case, "stage_diagnostic")
    assert str(raised.value) == access.DIAGNOSTIC_DENIED and raised.value.__context__ is None
    op.source.runtime.get_doc.assert_not_called()
    case.lookup.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()
    op.writer.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("identity", ["source", "company", "device", "linked"])
def test_write_and_related_read_acl_denial_cannot_decrypt_or_stage(diagnostic_operator, certificates, monkeypatch, identity):
    op = diagnostic_operator
    case = scenario(op.source, certificates[0], monkeypatch, mode="matched", owner="linked")
    key = {"source": ("Sales Invoice", "INV-TEST", "write"), "company": ("Company", "TEST", "read"),
        "device": ("ZATCA Multiple Setting", "DEVICE", "read"), "linked": ("Company", "LINKED", "read")}[identity]
    op.source.denied_operations.add(key)
    with pytest.raises(PermissionDenied):
        invoke(case, "stage_diagnostic")
    case.keys.assert_not_called()
    case.factory.assert_not_called()
    op.writer.runtime.get_doc.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "keys", "owned_close", "before_insert", "after_insert"])
@pytest.mark.parametrize("change", ["revision", "write_acl", "create_acl", "actor"])
def test_known_source_or_access_drift_never_returns_success_metadata(diagnostic_operator, certificates, monkeypatch, stage, change):
    op = diagnostic_operator
    case = scenario(op.source, certificates[0], monkeypatch, mode="matched")
    def mutate():
        if change == "revision":
            case.invoice.values["modified"] = "2026-10-21 12:00:00.000000"
        elif change == "write_acl":
            op.source.denied_operations.add((case.invoice.doctype, case.invoice.name, "write"))
        elif change == "create_acl":
            op.create = False
        else:
            op.source.runtime.session.user = "other@example.test"
    if stage in ("lookup", "keys"):
        target = case.lookup if stage == "lookup" else case.keys
        returned = target.return_value
        def supply(*args):
            mutate()
            return returned
        target.side_effect = supply
    elif stage == "owned_close":
        factory = case.factory.side_effect
        def acquire(scope):
            owned = factory(scope)
            close = owned.close.side_effect
            def closed():
                close()
                mutate()
            owned.close.side_effect = closed
            return owned
        case.factory.side_effect = acquire
    elif stage == "before_insert":
        get_doc = op.writer.runtime.get_doc.side_effect
        def create(payload):
            mutate()
            return get_doc(payload) if get_doc else op.writer.doc
        op.writer.runtime.get_doc.side_effect = create
    else:
        op.writer.doc.insert.side_effect = lambda **kwargs: mutate()
    with pytest.raises((PermissionDenied, access.PrimaryDiagnosticReviewError)) as raised:
        invoke(case, "stage_diagnostic")
    assert raised.value.__context__ is raised.value.__cause__ is None and not vars(raised.value)
    assert "PRIVATE" not in str(raised.value)
    assert op.writer.doc.insert.call_count == (stage == "after_insert")
    if stage == "lookup":
        case.keys.assert_not_called()
    if stage in ("lookup", "keys"):
        case.factory.assert_not_called()
    assert (case.corecase.core.journal, case.corecase.core.sealed) == case.corecase.before_state


@pytest.mark.parametrize("mode", ["missing", "custody-only", "journal-only", "different-seal", "unknown"])
def test_pair_review_does_not_become_a_diagnostic_permission(diagnostic_operator, certificates, monkeypatch, mode):
    op = diagnostic_operator
    case = scenario(op.source, certificates[0], monkeypatch, mode=mode)
    with pytest.raises(access.PrimaryDiagnosticReviewError) as raised:
        invoke(case, "stage_diagnostic")
    assert str(raised.value) == access.DIAGNOSTIC_FAILED and raised.value.__context__ is None
    op.writer.doc.insert.assert_not_called()
    assert (case.corecase.core.journal, case.corecase.core.sealed) == case.corecase.before_state


def test_late_static_review_is_not_a_legacy_validation_error_and_is_arabic(diagnostic_operator, certificates, monkeypatch):
    op = diagnostic_operator
    with (Path(event_log.__file__).parents[1] / "translations/ar.csv").open() as stream:
        entries = {row[0]: row[1] for row in csv.reader(stream) if len(row) == 2}
    monkeypatch.setattr(access, "_", lambda message: entries[message])
    case = scenario(op.source, certificates[0], monkeypatch, mode="missing")
    with pytest.raises(access.PrimaryDiagnosticReviewError) as raised:
        invoke(case, "stage_diagnostic")
    assert str(raised.value) == entries[access.DIAGNOSTIC_FAILED]
    assert isinstance(raised.value, RuntimeError) and raised.value.__context__ is None


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("change", ["wrapper", "raw"])
def test_saved_diagnostic_parent_drift_keeps_originals_and_static_review(diagnostic_operator, certificates,
    monkeypatch, doctype, late, change):
    op = diagnostic_operator
    case = scenario(op.source, certificates[0], monkeypatch, mode="matched", doctype=doctype)
    original_request, original_sealed = case.request, case.sealed
    parent = op.writer.runtime.db
    replacement = SimpleNamespace(_conn=parent._conn, commit=Mock(), rollback=Mock(), close=Mock())
    def drift():
        if change == "wrapper":
            op.writer.runtime.db = replacement
        else:
            parent._conn = object()
    if late:
        op.writer.doc.insert.side_effect = lambda **options: drift()
    else:
        def construct(payload):
            drift()
            return op.writer.doc
        op.writer.runtime.get_doc.side_effect = construct
    with pytest.raises(access.PrimaryDiagnosticReviewError) as raised:
        invoke(case, "stage_diagnostic")
    assert str(raised.value) == access.DIAGNOSTIC_FAILED
    assert raised.value.__context__ is raised.value.__cause__ is None and not vars(raised.value)
    assert case.request is original_request and case.sealed is original_sealed
    assert case.cipher.open(case.sealed) == case.corecase.captured.receipt
    assert (case.corecase.core.journal, case.corecase.core.sealed) == case.corecase.before_state
    assert all(owned.closed for owned in case.corecase.core.connections)
    if late:
        op.writer.doc.insert.assert_called_once_with(ignore_permissions=False)
    else:
        op.writer.doc.insert.assert_not_called()
    for database in (parent, replacement, op.source.runtime.db):
        database.commit.assert_not_called()
        database.rollback.assert_not_called()
    replacement.close.assert_not_called()
    op.writer.runtime.log_error.assert_not_called()
    case.corecase.core.observer.assert_called_once()
    case.cipher.seal.assert_not_called()


@pytest.mark.parametrize("actor", ["guest", "role", "site"])
def test_diagnostic_actor_denial_precedes_permission_engine_and_source_reads(diagnostic_operator, certificates, monkeypatch, actor):
    op = diagnostic_operator
    case = scenario(op.source, certificates[0], monkeypatch, mode="matched")
    if actor == "guest":
        op.source.runtime.session.user = "Guest"
    elif actor == "role":
        op.source.runtime.get_roles.return_value = []
    else:
        op.source.runtime.local.site = "OTHER.test"
    with pytest.raises(PermissionDenied):
        invoke(case, "stage_diagnostic")
    assert not op.create_calls
    op.source.runtime.get_doc.assert_not_called()
    case.keys.assert_not_called()
    case.factory.assert_not_called()


@pytest.mark.parametrize("late", [False, True])
@pytest.mark.parametrize("returned", [False, None, 1, "yes"])
def test_explicit_staging_source_callback_requires_literal_true_before_and_after_insert(writer, late, returned):
    check = Mock(side_effect=[True, returned] if late else [returned])
    with pytest.raises(event_log.EventLogSourceError) as raised:
        event_log.stage_zatca_event("TEST-INVOICE", "TEST-BODY", "Observed", source_recheck=check)
    assert str(raised.value) == event_log.EVENT_LOG_SOURCE_REVIEW
    assert writer.doc.insert.call_count == late
    assert check.call_count == (2 if late else 1)
    writer.runtime.db.commit.assert_not_called()
    writer.runtime.db.rollback.assert_not_called()
