"""Offline pinned preparation tests with synthetic, unsigned XML only."""

import pickle
from dataclasses import FrozenInstanceError, replace
from unittest.mock import Mock
from uuid import uuid4

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import PreparedIssuanceCandidate
from zatca_erpgulf.zatca_erpgulf.issuance_preparation import IssuancePreparation, PreparationTicket
from zatca_erpgulf.zatca_erpgulf.issuing_chain import MAX_CHAIN_ICV, initialize_declared_chain
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_chain import (
    assert_code, mock_repository, prepared_for, registration,
)


def build_for(der, ticket, *, code="388", indicator=None):
    """Synthetic adapter observes the pinned ticket; it does NOT sign XML."""
    indicator = indicator or ("0200000" if "reporting" in ticket.context.route.endpoint else "0100000")
    original = prepared_for(der, ticket.predecessor.registration, icv=ticket.icv,
        pih=ticket.previous_hash, name=ticket.context.scope.invoice_name,
        code=code, indicator=indicator)
    root = etree.fromstring(original.xml_bytes)
    root.find("cbc:UUID", NS).text = ticket.invoice_uuid
    return PreparedIssuanceCandidate(ticket.context,
        etree.tostring(root, encoding="UTF-8", xml_declaration=True))


def setup(certificates, monkeypatch):
    repo, connection, cursor, before, original = mock_repository(certificates, monkeypatch)
    service = IssuancePreparation(repo)
    callbacks = dict(build=Mock(return_value=original), retain=Mock(return_value=True),
        guard=Mock(return_value=True))
    args = before.registration, original.context, original.artifact.uuid
    return service, repo, connection, cursor, before, original, callbacks, args


def test_one_shot_pins_identity_keeps_exact_original_and_never_owns_transaction(certificates, monkeypatch):
    service, repo, connection, _, before, original, callbacks, args = setup(certificates, monkeypatch)
    after = service.prepare(*args, **callbacks)
    ticket = service.protected_ticket
    assert ticket == PreparationTicket(before, original.context, original.artifact.uuid)
    assert ticket.icv == 1 and ticket.previous_hash == before.previous_hash
    assert ticket.key_sha256 == original.key_sha256
    assert after.last_icv == 1 and service.protected_original is original
    callbacks["build"].assert_called_once_with(ticket)
    callbacks["retain"].assert_called_once_with(ticket, original)
    assert callbacks["guard"].call_count == 4
    repo._artifacts.put.assert_called_once_with(original)
    for method in (connection.commit, connection.rollback, connection.close): method.assert_not_called()
    assert_code(lambda: service.prepare(*args, **callbacks), "preparation_unusable")
    callbacks["build"].assert_called_once()
    assert_code(lambda: repo.load(before.registration), "chain_transaction_unusable")


@pytest.mark.parametrize("environment", ["Production", "Simulation", "Sandbox"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("code,indicator", [("388","0100000"),("388","0200000"),
    ("381","0100000"),("381","0200000"),("383","0100000"),("383","0200000"),("386","0100000")])
def test_synthetic_adapter_preserves_ticket_across_sources_and_types(certificates, environment, doctype, code, indicator):
    registered = registration(certificates[0], environment=environment)
    original = prepared_for(certificates[0], registered, code=code, indicator=indicator)
    ctx = replace(original.context, scope=replace(original.context.scope, doctype=doctype))
    ticket = PreparationTicket(initialize_declared_chain(registered), ctx, str(uuid4()))
    built = build_for(certificates[0], ticket, code=code, indicator=indicator)
    assert built.context == ctx and built.artifact.uuid == ticket.invoice_uuid
    assert built.artifact.icv == ticket.icv and built.artifact.previous_hash == ticket.previous_hash
    assert built.key_sha256 == ticket.key_sha256


@pytest.mark.parametrize("value", [None, "", True, "PRIVATE", "00000000-0000-0000-0000-000000000000"])
def test_invalid_uuid_never_acquires_sql_lock_or_builds(certificates, monkeypatch, value):
    service, repo, connection, _, _, _, callbacks, args = setup(certificates, monkeypatch)
    assert_code(lambda: service.prepare(*args[:2], value, **callbacks), "preparation_uuid")
    connection.cursor.assert_not_called()
    callbacks["build"].assert_not_called()
    assert repo._failed


def test_already_recorded_source_is_refused_before_generation(certificates, monkeypatch):
    service, repo, _, _, _, _, callbacks, args = setup(certificates, monkeypatch)
    repo._has_candidate.return_value = True
    assert_code(lambda: service.prepare(*args, **callbacks), "chain_original_requires_review")
    callbacks["build"].assert_not_called()
    callbacks["retain"].assert_not_called()
    assert service.protected_original is None


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_source_or_permission_drift_at_each_boundary_requires_whole_owner_rollback(certificates, monkeypatch, stage):
    service, repo, connection, _, before, original, callbacks, args = setup(certificates, monkeypatch)
    callbacks["guard"].side_effect = [True] * (stage - 1) + [False]
    assert_code(lambda: service.prepare(*args, **callbacks), "preparation_source_guard")
    assert service.protected_original is (None if stage == 1 else original)
    assert callbacks["build"].call_count == (0 if stage == 1 else 1)
    assert repo._artifacts.put.call_count == (1 if stage == 4 else 0)
    assert_code(lambda: repo.load(before.registration), "chain_transaction_unusable")
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()


@pytest.mark.parametrize("callback", ["guard", "retain"])
@pytest.mark.parametrize("value", [1, "True", None, {}, []])
def test_truthy_or_missing_acknowledgments_are_not_accepted(certificates, monkeypatch, callback, value):
    service, _, _, _, _, original, callbacks, args = setup(certificates, monkeypatch)
    callbacks[callback].return_value = value
    expected = "preparation_source_guard" if callback == "guard" else "preparation_custody"
    assert_code(lambda: service.prepare(*args, **callbacks), expected)
    assert service.protected_original is (None if callback == "guard" else original)


@pytest.mark.parametrize("change,expected", [("uuid","preparation_uuid_drift"),
    ("source","preparation_context_drift"), ("route","preparation_context_drift"),
    ("counter","chain_candidate_counter"), ("pih","chain_candidate_previous_hash")])
def test_changed_builder_identity_or_context_never_reaches_custody_or_store(certificates, monkeypatch, change, expected):
    service, repo, _, _, _, original, callbacks, args = setup(certificates, monkeypatch)
    if change in ("uuid", "counter", "pih"):
        root = etree.fromstring(original.xml_bytes)
        if change == "uuid": root.find("cbc:UUID", NS).text = str(uuid4())
        if change == "counter": root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=NS)[0].text = "2"
        if change == "pih": root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces=NS)[0].text = "eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg="
        changed = replace(original, xml_bytes=etree.tostring(root))
    else:
        ctx = original.context
        if change == "source": ctx = replace(ctx, source_snapshot_sha256="a"*64)
        else:
            ctx = replace(ctx, route=replace(ctx.route, url=ctx.route.url.replace("/phase2/", "/alternate/")))
            assert ctx.route.url != original.context.route.url
        changed = replace(original, context=ctx)
    callbacks["build"].return_value = changed
    assert_code(lambda: service.prepare(*args, **callbacks), expected)
    assert service.protected_original is changed
    callbacks["retain"].assert_not_called()
    repo._artifacts.put.assert_not_called()


@pytest.mark.parametrize("callback", ["build", "guard", "retain"])
@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE XML/auth/database"), KeyboardInterrupt()])
def test_callback_failure_is_static_and_never_automatically_retries(certificates, monkeypatch, callback, failure):
    service, repo, _, _, _, _, callbacks, args = setup(certificates, monkeypatch)
    callbacks[callback].side_effect = failure
    if isinstance(failure, Exception):
        assert_code(lambda: service.prepare(*args, **callbacks), "preparation_callback_failed")
    else:
        with pytest.raises(KeyboardInterrupt): service.prepare(*args, **callbacks)
    assert repo._failed
    assert_code(lambda: service.prepare(*args, **callbacks), "preparation_unusable")
    assert callbacks["build"].call_count <= 1


@pytest.mark.parametrize("callback", ["guard", "build", "retain"])
def test_caught_recursive_call_still_poison_outer_operation(certificates, monkeypatch, callback):
    service, repo, _, _, _, original, callbacks, args = setup(certificates, monkeypatch)
    def recursive(*unused):
        assert_code(lambda: service.prepare(*args, **callbacks), "preparation_unusable")
        return original if callback == "build" else True
    callbacks[callback].side_effect = recursive
    assert_code(lambda: service.prepare(*args, **callbacks), "preparation_unusable")
    repo._artifacts.put.assert_not_called()


@pytest.mark.parametrize("field", ["invoice_uuid", "context", "predecessor"])
def test_ticket_is_frozen_and_protected_objects_are_not_pickled(certificates, monkeypatch, field):
    service, _, _, _, _, original, callbacks, args = setup(certificates, monkeypatch)
    service.prepare(*args, **callbacks)
    ticket = service.protected_ticket
    with pytest.raises(FrozenInstanceError): setattr(ticket, field, None)
    for value in (ticket, service):
        with pytest.raises(TypeError, match="not_serializable"): pickle.dumps(value)
        assert original.xml_bytes.decode() not in repr(value)
        assert ticket.previous_hash not in repr(value)


@pytest.mark.parametrize("callback", ["guard", "build", "retain"])
def test_missing_callback_rejected_without_locking(certificates, monkeypatch, callback):
    service, _, connection, _, _, _, callbacks, args = setup(certificates, monkeypatch)
    callbacks[callback] = None
    assert_code(lambda: service.prepare(*args, **callbacks), "preparation_callbacks")
    connection.cursor.assert_not_called()


@pytest.mark.parametrize("value", [None, b"PRIVATE XML", {}, True])
def test_builder_requires_an_exact_candidate_not_serialized_data(certificates, monkeypatch, value):
    service, repo, _, _, _, _, callbacks, args = setup(certificates, monkeypatch)
    callbacks["build"].return_value = value
    assert_code(lambda: service.prepare(*args, **callbacks), "preparation_candidate")
    assert service.protected_original is None
    repo._artifacts.put.assert_not_called()


@pytest.mark.parametrize("change", ["company", "seller", "environment", "chain", "epoch"])
def test_registration_drift_is_rejected_before_builder_or_lock(certificates, monkeypatch, change):
    service, _, connection, _, before, _, callbacks, args = setup(certificates, monkeypatch)
    values = {"company": dict(company_name="OTHER"), "seller": dict(seller_tax_id="OTHER"),
        "environment": dict(environment="Simulation"), "chain": dict(chain_id=str(uuid4())),
        "epoch": dict(credential_epoch=registration(certificates[1]).credential_epoch)}[change]
    changed = replace(before.registration, **values)
    assert_code(lambda: service.prepare(changed, *args[1:], **callbacks),
        "chain_candidate_epoch" if change == "epoch" else "chain_candidate_scope")
    callbacks["build"].assert_not_called()
    connection.cursor.assert_not_called()


def test_counter_exhaustion_is_checked_before_builder_not_after_signing(certificates, monkeypatch):
    service, repo, _, _, before, _, callbacks, args = setup(certificates, monkeypatch)
    full = replace(before, last_icv=MAX_CHAIN_ICV,
        previous_hash="eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg=",
        tail_key_sha256="a"*64, tail_manifest_sha256="b"*64)
    repo._load.return_value = full
    assert_code(lambda: service.prepare(*args, **callbacks), "chain_counter_exhausted")
    callbacks["build"].assert_not_called()


def test_record_failure_preserves_retained_original_without_retry_or_commit(certificates, monkeypatch):
    service, repo, connection, cursor, before, original, callbacks, args = setup(certificates, monkeypatch)
    cursor.rowcount = 0
    assert_code(lambda: service.prepare(*args, **callbacks), "chain_compare_and_swap")
    assert service.protected_original is original
    assert service.protected_ticket.predecessor == before
    callbacks["retain"].assert_called_once_with(service.protected_ticket, original)
    callbacks["build"].assert_called_once()
    repo._artifacts.put.assert_called_once()
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()


def test_callback_order_places_custody_before_store_and_source_check_after_store(certificates, monkeypatch):
    service, repo, _, _, _, original, callbacks, args = setup(certificates, monkeypatch)
    calls = []
    callbacks["guard"].side_effect = lambda ticket: (calls.append("guard") or True)
    callbacks["build"].side_effect = lambda ticket: (calls.append("build") or original)
    callbacks["retain"].side_effect = lambda ticket, candidate: (calls.append("retain") or True)
    put = repo._artifacts.put.return_value
    repo._artifacts.put.side_effect = lambda candidate: (calls.append("store") or put)
    service.prepare(*args, **callbacks)
    assert calls == ["guard", "build", "guard", "retain", "guard", "store", "guard"]


@pytest.mark.parametrize("value", [None, Mock(), {}])
def test_repository_must_be_explicit_not_a_discovered_or_generic_facade(value):
    assert_code(lambda: IssuancePreparation(value), "preparation_repository")
