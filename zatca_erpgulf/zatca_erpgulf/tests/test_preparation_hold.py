"""Local no-rebuild tickets/owner tests. No genuine keys, ERP site or HTTP."""

import json
import pickle
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import held_issuance_preparation as owned
from zatca_erpgulf.zatca_erpgulf import preparation_hold as holds
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import preparation_source_sha256
from zatca_erpgulf.zatca_erpgulf.issuance_preparation import PreparationTicket
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_chain import (
    assert_code, mock_repository, prepared_for, registration,
)
from zatca_erpgulf.zatca_erpgulf.issuing_chain import initialize_declared_chain, record_generated_candidate


def sample(der):
    candidate = prepared_for(der)
    ticket = PreparationTicket(initialize_declared_chain(registration(der)), candidate.context, candidate.artifact.uuid)
    return holds.PreparationHold(str(uuid4()), ticket), candidate


@pytest.mark.parametrize("environment", ["Production", "Simulation", "Sandbox"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_ticket_codec_roundtrip_without_xml_or_current_settings(certificates, environment, doctype):
    hold, candidate = sample(certificates[0])
    registered = replace(hold.ticket.predecessor.registration, environment=environment)
    original = prepared_for(certificates[0], registered)
    ctx = replace(original.context, scope=replace(original.context.scope, doctype=doctype))
    ticket = PreparationTicket(initialize_declared_chain(registered), ctx, candidate.artifact.uuid)
    content = holds.encode_preparation_ticket(ticket)
    assert holds.decode_preparation_ticket(content) == ticket
    assert b"<Invoice" not in content and candidate.xml_bytes not in content
    assert b"private_key" not in content and b"Authorization" not in content


@pytest.mark.parametrize("change", ["extra", "version", "uuid", "context", "predecessor", "nested", "whitespace"])
def test_ticket_codec_refuses_corrupt_or_noncanonical_data(certificates, change):
    hold, _ = sample(certificates[0])
    body = json.loads(holds.encode_preparation_ticket(hold.ticket))
    if change == "extra": body["secret"] = "PRIVATE"
    elif change == "version": body["schema_version"] = True
    elif change == "uuid": body["invoice_uuid"] = "PRIVATE"
    elif change == "context": body["context"] = []
    elif change == "predecessor": body["predecessor"]["last_icv"] = 8
    elif change == "nested": body["context"]["route"]["secret"] = "PRIVATE"
    content = json.dumps(body, ensure_ascii=False, sort_keys=True,
        separators=(",", ":") if change != "whitespace" else (", ", ": ")).encode()
    assert_code(lambda: holds.decode_preparation_ticket(content), "preparation_ticket_invalid")


@pytest.mark.parametrize("content", [None, b"", b"PRIVATE", b"[]", b"x" * (holds.MAX_TICKET_BYTES + 1)])
def test_ticket_codec_rejects_unbounded_or_wrong_input(content):
    assert_code(lambda: holds.decode_preparation_ticket(content), "preparation_ticket_invalid")


@pytest.mark.parametrize("change", ["version", "chain", "environment", "unit", "source", "route", "epoch"])
def test_source_hold_cannot_be_bypassed_by_new_preparation_settings(certificates, change):
    hold, _ = sample(certificates[0])
    ctx = hold.ticket.context
    scope = ctx.scope
    if change == "version": scope = replace(scope, issuance_version=2)
    if change == "chain": scope = replace(scope, chain_id=str(uuid4()))
    if change == "environment": scope = replace(scope, environment="Simulation")
    if change == "unit": scope = replace(scope, legacy_issuing_unit="OTHER")
    if change == "source": ctx = replace(ctx, source_snapshot_sha256="f"*64)
    if change == "route": ctx = replace(ctx, route=replace(ctx.route, url=ctx.route.url.replace("/phase2/", "/other/")))
    if change == "epoch": ctx = replace(ctx, credential_epoch=replace(ctx.credential_epoch, version_id=str(uuid4())))
    assert scope != hold.ticket.context.scope or ctx != hold.ticket.context
    # Context-only changes deliberately cannot affect the scope-derived key.
    assert preparation_source_sha256(scope) == hold.source_sha256


@pytest.mark.parametrize("field", ["doctype", "invoice_name", "company_name"])
def test_different_saved_source_has_different_hold_key(certificates, field):
    hold, _ = sample(certificates[0])
    scope = hold.ticket.context.scope
    changed = replace(scope, **{field: "POS Invoice" if field == "doctype" else "OTHER"})
    assert preparation_source_sha256(changed) != hold.source_sha256


def test_hold_frozen_repr_pickle_and_invalid_identity(certificates):
    hold, original = sample(certificates[0])
    with pytest.raises(FrozenInstanceError): hold.hold_id = str(uuid4())
    assert original.xml_bytes.decode() not in repr(hold)
    assert hold.ticket.previous_hash not in repr(hold)
    with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(hold)
    assert_code(lambda: replace(hold, hold_id="PRIVATE"), "preparation_hold_id")
    assert_code(lambda: replace(hold, original_manifest_sha256="PRIVATE"), "preparation_original_manifest")


def owner_case(certificates, monkeypatch, *, fault=None):
    hold, candidate = sample(certificates[0])
    trace = []
    connections = []
    def factory():
        number = len(connections) + 1
        connection = SimpleNamespace(cursor=Mock(), rollback=Mock(), closed=False)
        def commit():
            trace.append(("commit", number))
            if fault == ("commit", number): raise RuntimeError("PRIVATE driver error")
        def close():
            connection.closed = True
            trace.append(("close", number))
            if fault == ("close", number): raise RuntimeError("PRIVATE close error")
        connection.commit, connection.close = Mock(side_effect=commit), Mock(side_effect=close)
        connections.append(connection)
        return connection
    repository = Mock()
    def reserve(*args, guard):
        assert guard(hold.ticket) is True
        trace.append(("reserve", 1))
        return hold
    repository.reserve.side_effect = reserve
    after = record_generated_candidate(hold.ticket.predecessor, candidate)
    def complete(expected, original):
        assert expected == hold and original is candidate
        trace.append(("complete", 2))
        return replace(hold, original_manifest_sha256=candidate.manifest_sha256), after
    repository.complete.side_effect = complete
    monkeypatch.setattr(owned, "MariaDBPreparationHoldRepository", Mock(return_value=repository))
    def build(ticket):
        assert ticket == hold.ticket and len(connections) == 1 and connections[0].closed
        assert trace[:3] == [("reserve", 1), ("commit", 1), ("close", 1)]
        trace.append(("build", 0))
        return candidate
    callbacks = dict(build=Mock(side_effect=build), retain=Mock(return_value=True), guard=Mock(return_value=True))
    owner = owned.HeldIssuancePreparation(factory, str(uuid4()))
    args = hold.ticket.predecessor.registration, hold.ticket.context, hold.ticket.invoice_uuid, hold.hold_id
    return SimpleNamespace(owner=owner, hold=hold, candidate=candidate, args=args,
        callbacks=callbacks, repository=repository, trace=trace, connections=connections, after=after)


def test_hold_commit_and_close_precede_single_build_then_second_owned_transaction(certificates, monkeypatch):
    case = owner_case(certificates, monkeypatch)
    assert case.owner.prepare(*case.args, **case.callbacks) == case.after
    assert case.owner.protected_hold == case.hold and case.owner.protected_original is case.candidate
    assert case.trace == [("reserve",1),("commit",1),("close",1),("build",0),
                          ("complete",2),("commit",2),("close",2)]
    assert case.callbacks["guard"].call_count == 6
    case.callbacks["retain"].assert_called_once_with(case.hold.ticket, case.candidate)
    assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "held_preparation_unusable")
    case.callbacks["build"].assert_called_once()


@pytest.mark.parametrize("number", [1, 2])
@pytest.mark.parametrize("method", ["commit", "close"])
def test_owned_transaction_uncertainty_never_retries_build_or_discards_original(certificates, monkeypatch, number, method):
    case = owner_case(certificates, monkeypatch, fault=(method, number))
    assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "held_preparation_unconfirmed")
    assert case.callbacks["build"].call_count == (0 if number == 1 else 1)
    assert case.owner.protected_hold == case.hold
    assert case.owner.protected_original is (None if number == 1 else case.candidate)
    assert len(case.connections) == number and all(c.closed for c in case.connections)
    assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "held_preparation_unusable")


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5, 6])
def test_source_or_acl_drift_at_every_owned_boundary_stops_without_rebuild(certificates, monkeypatch, stage):
    case = owner_case(certificates, monkeypatch)
    case.callbacks["guard"].side_effect = [True] * (stage - 1) + [False]
    assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "preparation_source_guard")
    assert case.callbacks["build"].call_count == (0 if stage <= 2 else 1)
    assert case.owner.protected_original is (None if stage <= 2 else case.candidate)
    if stage >= 2: assert case.connections[0].closed and case.connections[0].commit.call_count == 1
    assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "held_preparation_unusable")


@pytest.mark.parametrize("callback", ["build", "retain", "guard"])
def test_recursive_use_cannot_be_swallowed_to_resume_outer_build(certificates, monkeypatch, callback):
    case = owner_case(certificates, monkeypatch)
    def recursive(*args):
        assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "held_preparation_unusable")
        return case.candidate if callback == "build" else True
    case.callbacks[callback].side_effect = recursive
    assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "held_preparation_unusable")
    case.repository.complete.assert_not_called()


@pytest.mark.parametrize("callback", ["build", "retain", "guard"])
@pytest.mark.parametrize("fault", [RuntimeError("PRIVATE XML/key/SQL"), KeyboardInterrupt()])
def test_callback_errors_preserve_static_diagnostics_and_never_replay(certificates, monkeypatch, callback, fault):
    case = owner_case(certificates, monkeypatch)
    case.callbacks[callback].side_effect = fault
    if isinstance(fault, Exception):
        assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "held_preparation_unconfirmed")
    else:
        with pytest.raises(KeyboardInterrupt): case.owner.prepare(*case.args, **case.callbacks)
    assert case.callbacks["build"].call_count <= 1
    case.repository.complete.assert_not_called()


@pytest.mark.parametrize("value", [1, "True", None, {}, []])
def test_custody_requires_literal_true_and_keeps_exact_original_on_failure(certificates, monkeypatch, value):
    case = owner_case(certificates, monkeypatch)
    case.callbacks["retain"].return_value = value
    assert_code(lambda: case.owner.prepare(*case.args, **case.callbacks), "preparation_custody")
    assert case.owner.protected_original is case.candidate and len(case.connections) == 1


def test_previous_caller_transaction_path_checks_pending_and_permanent_source_holds(certificates, monkeypatch):
    repo, _, cursor, _, original = mock_repository(certificates, monkeypatch)
    # Restore the real bounded guard rather than a mock allowing everything.
    guard = type(repo)._preparation_available.__get__(repo)
    hold_id = str(uuid4())
    for row in ((hold_id,), (str(uuid4()),)):
        cursor.fetchone.return_value = row
        assert_code(lambda: guard(cursor, original.context), "preparation_held_requires_review")
    cursor.fetchone.return_value = (hold_id,)
    assert guard(cursor, original.context, hold_id) is None
    sql, parameters = cursor.execute.call_args.args
    assert "LIMIT 1 FOR UPDATE" in sql and "source_sha256=%s" in sql
    assert parameters[-1] == preparation_source_sha256(original.context.scope)
