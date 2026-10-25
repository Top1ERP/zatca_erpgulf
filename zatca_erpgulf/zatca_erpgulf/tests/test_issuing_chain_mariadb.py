"""Owned private chain/artifact SQL rehearsal; never a tenant or authority."""

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import issuing_chain as chain
from zatca_erpgulf.zatca_erpgulf import issuing_chain_repository as storage
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.issuance_preparation import IssuancePreparation
from zatca_erpgulf.zatca_erpgulf.held_issuance_preparation import HeldIssuancePreparation
from zatca_erpgulf.zatca_erpgulf.preparation_hold import MariaDBPreparationHoldRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_preparation import build_for
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_chain import registration, prepared_for
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event
from zatca_erpgulf.zatca_erpgulf import preparation_review_access as review_access
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_review_access import (
    reviewer, operator, scenario as review_scenario, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf import preparation_recovery_access as recovery_access
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_recovery_access import recoverer
from zatca_erpgulf.zatca_erpgulf import preparation_custody as custody
from zatca_erpgulf.zatca_erpgulf import preparation_custody_access as custody_access
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_custody_access import custodian


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Only the guarded owned-private SQL runner may acquire this fixture")


@pytest.fixture(scope="module", autouse=True)
def install_private_chain_schema(isolated_server):
    with pymysql.connect(unix_socket=isolated_server[0], user="root",
                         database="zatca_journal_rehearsal", autocommit=True) as connection:
        schema = Path(__file__).resolve().parents[3] / "docs/zatca_unification/issuing_chain_rehearsal.sql"
        text = "\n".join(line for line in schema.read_text().splitlines() if not line.lstrip().startswith("--"))
        with connection.cursor() as cursor:
            for statement in text.split(";"):
                if statement.strip(): cursor.execute(statement)
            cursor.execute("CREATE TABLE chain_parent_work (namespace CHAR(36) PRIMARY KEY,payload LONGTEXT) ENGINE=InnoDB")


@pytest.fixture
def case(certificates):
    return dict(namespace=str(uuid4()), registered=registration(certificates[0]), der=certificates[0])


def repository(connection, case):
    return storage.MariaDBIssuingChainRepository(connection, case["namespace"])


def initialize(connection, case):
    before = repository(connection, case).create(case["registered"])
    connection.commit()  # Explicit TEST owner, never a service or document hook.
    return before


def count(connection, table, namespace):
    assert table in ("zatca_issuing_chain_v1", "zatca_issuance_candidate_v1", "chain_parent_work", "zatca_preparation_hold_v1", "zatca_preparation_custody_v1")
    column = "namespace" if table == "chain_parent_work" else "storage_namespace"
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM " + table + " WHERE " + column + "=%s", (namespace,))
        return cursor.fetchone()[0]


@pytest.mark.parametrize("commit", [True, False])
def test_genesis_parent_and_exact_first_artifact_share_one_transaction(connections, case, commit):
    writer, observer = connections(), connections()
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO chain_parent_work VALUES (%s,%s)", (case["namespace"], "SYNTHETIC PARENT"))
    handle = repository(writer, case)
    before = handle.create(case["registered"])
    first = prepared_for(case["der"], case["registered"])
    after = handle.record(before, first)
    assert before.last_icv == 0 and after.last_icv == 1
    tables = ("zatca_issuing_chain_v1", "zatca_issuance_candidate_v1", "chain_parent_work")
    for table in tables: assert count(observer, table, case["namespace"]) == 0
    writer.commit() if commit else writer.rollback()
    observer.rollback()
    for table in tables: assert count(observer, table, case["namespace"]) == int(commit)
    if commit:
        loaded = repository(observer, case).load(case["registered"])
        assert loaded == after
        original = MariaDBJournalRepository(observer, case["namespace"]).load(first.key_sha256)
        assert original.candidate.xml_bytes == first.xml_bytes and original.events == ()


def test_equal_creation_and_redelivery_never_reset_used_head(connections, case):
    writer = connections()
    before = initialize(writer, case)
    first = prepared_for(case["der"], case["registered"])
    one = repository(writer, case).record(before, first)
    writer.commit()
    assert repository(writer, case).create(case["registered"]) == one
    second = prepared_for(case["der"], case["registered"], icv=2, pih=one.previous_hash)
    two = repository(writer, case).record(one, second)
    writer.commit()
    assert repository(writer, case).record(before, first) == two
    writer.commit()
    assert repository(connections(), case).load(case["registered"]) == two
    assert count(writer, "zatca_issuance_candidate_v1", case["namespace"]) == 2


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("exact", [True, False])
def test_competing_first_artifacts_cannot_claim_the_same_position(connections, case, isolation, exact):
    writer = connections(isolation)
    before = initialize(writer, case)
    first = prepared_for(case["der"], case["registered"], name="FIRST")
    other = first if exact else prepared_for(case["der"], case["registered"], name="COMPETING")
    one = repository(writer, case).record(before, first)
    ready = Event()
    def competing():
        connection = connections(isolation)
        ready.set()
        try:
            result = repository(connection, case).record(before, other)
            connection.commit()
            return result
        except chain.IssuingChainError as error:
            connection.rollback()
            return error.code
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(competing)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        writer.commit()
        outcome = future.result(timeout=10)
    assert outcome == (one if exact else "chain_stale_state")
    observed = connections()
    assert repository(observed, case).load(case["registered"]) == one
    assert count(observed, "zatca_issuance_candidate_v1", case["namespace"]) == 1


@pytest.mark.parametrize("change", ["registration", "certificate", "chain"])
def test_registration_identity_conflicts_cannot_create_or_reset_a_chain(connections, case, change):
    writer = connections()
    before = initialize(writer, case)
    registered = case["registered"]
    changes = {"registration": dict(registration_id=str(uuid4())),
        "certificate": dict(credential_epoch=replace(registered.credential_epoch, version_id=str(uuid4()), certificate_der_sha256="a"*64)),
        "chain": dict(chain_id=str(uuid4()), registration_id=str(uuid4()))}[change]
    handle = repository(writer, case)
    with pytest.raises(chain.IssuingChainError):
        handle.create(replace(registered, **changes))
    with pytest.raises(chain.IssuingChainError, match="^chain_transaction_unusable$"):
        handle.load(registered)
    writer.rollback()
    assert repository(connections(), case).load(registered) == before


def test_two_registered_units_under_one_company_start_independently(connections, case, certificates):
    writer = connections()
    old = initialize(writer, case)
    one = repository(writer, case).record(old, prepared_for(case["der"], case["registered"]))
    writer.commit()
    other = registration(certificates[2], chain_id=str(uuid4()), registration_id=str(uuid4()))
    new = repository(writer, case).create(other)
    assert new.last_icv == 0
    new_one = repository(writer, case).record(new, prepared_for(certificates[2], other))
    writer.commit()
    assert new_one.last_icv == one.last_icv == 1
    assert repository(writer, case).load(case["registered"]) == one


def test_preexisting_unbound_artifact_is_not_adopted_as_a_first_invoice(connections, case):
    writer = connections()
    original = prepared_for(case["der"], case["registered"])
    MariaDBJournalRepository(writer, case["namespace"]).put(original)
    writer.commit()
    with pytest.raises(chain.IssuingChainError, match="^chain_unbound_candidate$"):
        repository(writer, case).create(case["registered"])
    writer.rollback()
    assert count(writer, "zatca_issuing_chain_v1", case["namespace"]) == 0
    assert count(writer, "zatca_issuance_candidate_v1", case["namespace"]) == 1


def test_unknown_commit_acknowledgment_uses_exact_fresh_review_not_regeneration(connections, case):
    writer = connections()
    handle = repository(writer, case)
    before = handle.create(case["registered"])
    original = prepared_for(case["der"], case["registered"])
    after = handle.record(before, original)
    def commit_with_lost_ack():
        writer.commit()
        raise RuntimeError("SYNTHETIC commit acknowledgment unavailable")
    with pytest.raises(RuntimeError): commit_with_lost_ack()
    writer.close()
    reader = connections()
    assert repository(reader, case).load(case["registered"]) == after
    assert repository(reader, case).record(before, original) == after
    assert count(reader, "zatca_issuance_candidate_v1", case["namespace"]) == 1


def test_changed_original_cannot_be_redelivered_under_the_same_issuance_key(connections, case):
    writer = connections()
    before = initialize(writer, case)
    original = prepared_for(case["der"], case["registered"])
    after = repository(writer, case).record(before, original)
    writer.commit()
    changed = replace(original, xml_bytes=original.xml_bytes.replace(b"><", b">\n<"))
    assert changed.key_sha256 == original.key_sha256
    with pytest.raises(chain.IssuingChainError, match="^chain_redelivery_conflict$"):
        repository(writer, case).record(before, changed)
    writer.rollback()
    observer = connections()
    assert repository(observer, case).load(case["registered"]) == after
    assert MariaDBJournalRepository(observer, case["namespace"]).load(original.key_sha256).candidate.xml_bytes == original.xml_bytes
    observer.rollback()


@pytest.mark.parametrize("status", [200, 202, 400, 401, 500])
def test_observed_http_result_cannot_roll_back_or_define_the_generation_chain(connections, case, status):
    writer = connections()
    before = initialize(writer, case)
    original = prepared_for(case["der"], case["registered"])
    after = repository(writer, case).record(before, original)
    writer.commit()
    journal = MariaDBJournalRepository(writer, case["namespace"])
    observed = journal.load(original.key_sha256)
    started = journal.append(original.key_sha256, event(original), expected_journal_sha256=observed.journal_sha256)
    journal.append(original.key_sha256, event(original,"HTTP_RESPONSE",2,http_status=status),
                   expected_journal_sha256=started.journal_sha256)
    writer.commit()
    assert repository(writer, case).load(case["registered"]) == after
    second = prepared_for(case["der"], case["registered"], icv=2, pih=after.previous_hash)
    assert repository(writer, case).record(after, second).last_icv == 2
    writer.rollback()


@pytest.mark.parametrize("column,value", [("state_sha256","0"*64), ("last_icv","9"),
    ("payload_bytes", b"PRIVATE-INVALID-PAYLOAD"), ("certificate_sha256","0"*64)])
def test_corrupt_header_or_payload_is_refused_without_repair(connections, case, column, value):
    writer = connections()
    initialize(writer, case)
    with writer.cursor() as cursor:
        cursor.execute("UPDATE zatca_issuing_chain_v1 SET " + column + "=%s WHERE storage_namespace=%s AND chain_id=%s",
                       (value, case["namespace"], case["registered"].chain_id))
    writer.commit()
    with pytest.raises(chain.IssuingChainError) as error:
        repository(writer, case).load(case["registered"])
    assert "PRIVATE" not in str(error.value)
    writer.rollback()
    assert count(writer, "zatca_issuing_chain_v1", case["namespace"]) == 1


def test_tail_artifact_corruption_is_not_hidden_by_a_valid_head(connections, case):
    writer = connections()
    before = initialize(writer, case)
    original = prepared_for(case["der"], case["registered"])
    repository(writer, case).record(before, original)
    writer.commit()
    with writer.cursor() as cursor:
        cursor.execute("UPDATE zatca_issuance_candidate_v1 SET xml_bytes=%s WHERE storage_namespace=%s AND key_sha256=%s",
                       (b"PRIVATE-BROKEN-XML", case["namespace"], original.key_sha256))
    writer.commit()
    with pytest.raises(chain.IssuingChainError) as error:
        repository(writer, case).load(case["registered"])
    assert error.value.code.startswith("chain_artifact_") and "PRIVATE" not in str(error.value)


def test_parent_rollback_after_staging_keeps_committed_genesis_unchanged(connections, case):
    writer = connections()
    before = initialize(writer, case)
    repository(writer, case).record(before, prepared_for(case["der"], case["registered"]))
    writer.rollback()
    assert repository(connections(), case).load(case["registered"]) == before
    assert count(writer, "zatca_issuance_candidate_v1", case["namespace"]) == 0


def test_autocommit_refused_without_implicit_session_changes(connections, case):
    writer = connections(autocommit=True)
    with pytest.raises(chain.IssuingChainError, match="^chain_autocommit$"):
        repository(writer, case).create(case["registered"])
    assert writer.get_autocommit() is True
    assert count(writer, "zatca_issuing_chain_v1", case["namespace"]) == 0


def test_owned_server_crash_rolls_back_uncommitted_head_and_original(connections, case, isolated_server):
    writer = connections()
    before = initialize(writer, case)
    original = prepared_for(case["der"], case["registered"])
    repository(writer, case).record(before, original)
    isolated_server[2]()
    observer = connections()
    assert repository(observer, case).load(case["registered"]) == before
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 0


def prepare_synthetic(connection, case, *, name="SYNTHETIC-1", guard=lambda ticket: True,
                      retain=lambda ticket, original: True, build=None, invoice_uuid=None):
    """Explicit private-fixture transaction; no installed adapter or authority."""
    template = prepared_for(case["der"], case["registered"], name=name)
    service = IssuancePreparation(repository(connection, case))
    after = service.prepare(case["registered"], template.context, invoice_uuid or str(uuid4()),
        build=build or (lambda ticket: build_for(case["der"], ticket)), retain=retain, guard=guard)
    return service, after


@pytest.mark.parametrize("commit", [True, False])
def test_preparation_stages_exact_original_and_parent_without_owning_commit(connections, case, commit):
    writer, observer = connections(), connections()
    before = initialize(writer, case)
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO chain_parent_work VALUES (%s,%s)", (case["namespace"], "SYNTHETIC"))
    retained = []
    def retain(ticket, original):
        retained.append((ticket, original))
        assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 0
        return True
    service, after = prepare_synthetic(writer, case, retain=retain)
    original = service.protected_original
    assert retained == [(service.protected_ticket, original)] and after.last_icv == 1
    assert count(observer, "chain_parent_work", case["namespace"]) == 0
    writer.commit() if commit else writer.rollback()
    observer.rollback()
    assert repository(observer, case).load(case["registered"]) == (after if commit else before)
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == int(commit)
    assert count(observer, "chain_parent_work", case["namespace"]) == int(commit)
    if commit:
        saved = MariaDBJournalRepository(observer, case["namespace"]).load(original.key_sha256)
        assert saved.candidate.xml_bytes == original.xml_bytes
    else:
        # Do NOT call a fresh builder after rollback. Keep the exact ticket and
        # original for explicit reconciliation with a fresh transaction instead.
        observer.rollback()
        assert repository(writer, case).record(service.protected_ticket.predecessor, original) == after
        writer.rollback()


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_preparation_late_guard_failure_is_rolled_back_with_parent_work(connections, case, stage):
    writer = connections()
    before = initialize(writer, case)
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO chain_parent_work VALUES (%s,%s)", (case["namespace"], "SYNTHETIC"))
    calls = []
    retained = []
    service = IssuancePreparation(repository(writer, case))
    template = prepared_for(case["der"], case["registered"])
    def guard(ticket):
        calls.append(ticket)
        return len(calls) != stage
    def retain(ticket, original):
        retained.append(original)
        return True
    with pytest.raises(chain.IssuingChainError, match="^preparation_source_guard$"):
        service.prepare(case["registered"], template.context, str(uuid4()), guard=guard,
            retain=retain, build=lambda ticket: build_for(case["der"], ticket))
    assert service.protected_original is not None if stage > 1 else service.protected_original is None
    writer.rollback()  # Caller owns ALL parent/chain/artifact rollback.
    observer = connections()
    assert repository(observer, case).load(case["registered"]) == before
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 0
    assert count(observer, "chain_parent_work", case["namespace"]) == 0


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("same_source", [True, False])
def test_competing_preparation_locks_before_builder_then_reviews_or_uses_next_head(connections, case, isolation, same_source):
    writer = connections(isolation)
    initialize(writer, case)
    first_service, first = prepare_synthetic(writer, case, name="FIRST")
    ready, built = Event(), Event()
    def competitor():
        connection = connections(isolation)
        ready.set()
        def build(ticket):
            built.set()
            return build_for(case["der"], ticket)
        try:
            service, after = prepare_synthetic(connection, case,
                name="FIRST" if same_source else "SECOND", build=build)
            connection.commit()
            return service, after
        except chain.IssuingChainError as error:
            connection.rollback()
            return error.code
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(competitor)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        assert not built.is_set()  # Crucially, no XML/UUID from the builder yet.
        writer.commit()
        outcome = future.result(timeout=10)
    if same_source:
        assert outcome == "chain_original_requires_review" and not built.is_set()
    else:
        service, after = outcome
        assert after.last_icv == 2 and service.protected_ticket.predecessor == first
        assert service.protected_original.artifact.previous_hash == first.previous_hash
        assert service.protected_original.artifact.uuid != first_service.protected_original.artifact.uuid
    observer = connections()
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == (1 if same_source else 2)


def test_unknown_preparation_commit_ack_uses_retained_original_not_a_second_builder(connections, case):
    writer = connections()
    initialize(writer, case)
    service, after = prepare_synthetic(writer, case)
    writer.commit()  # Synthetic successful commit with an unavailable acknowledgment.
    writer.close()
    reader = connections()
    before, original = service.protected_ticket.predecessor, service.protected_original
    assert repository(reader, case).record(before, original) == after
    reader.commit()
    builds = []
    with pytest.raises(chain.IssuingChainError, match="^chain_original_requires_review$"):
        prepare_synthetic(reader, case, build=lambda ticket: builds.append(ticket))
    assert builds == []
    reader.rollback()
    assert count(reader, "zatca_issuance_candidate_v1", case["namespace"]) == 1


def test_missing_explicit_chain_never_runs_preparation_builder(connections, case):
    writer = connections()
    builds = []
    with pytest.raises(chain.IssuingChainError, match="^chain_missing$"):
        prepare_synthetic(writer, case, build=lambda ticket: builds.append(ticket))
    assert builds == []
    writer.rollback()
    assert count(writer, "zatca_issuing_chain_v1", case["namespace"]) == 0


class InjectedCommitConnection:
    """Shared private-test commit/close fault adapter; never a site connection."""

    def __init__(self, connection, fault=None): self.raw, self.fault = connection, fault
    def cursor(self): return self.raw.cursor()
    def rollback(self): return self.raw.rollback()
    def commit(self):
        if self.fault == "before_commit": raise RuntimeError("PRIVATE commit unavailable")
        self.raw.commit()
        if self.fault == "after_commit": raise RuntimeError("PRIVATE commit acknowledgment lost")
    def close(self):
        self.raw.close()
        if self.fault == "close": raise RuntimeError("PRIVATE close acknowledgment lost")


def held_case(connections, case, *, name="HELD-FIRST", fault=None):
    """Private owned connections only; fault injection never touches a site."""
    acquired = []
    def factory():
        raw = connections()
        acquired.append(raw)
        return InjectedCommitConnection(raw, fault[1] if fault and fault[0] == len(acquired) else None)
    owner = HeldIssuancePreparation(factory, case["namespace"])
    template = prepared_for(case["der"], case["registered"], name=name)
    args = case["registered"], template.context, str(uuid4()), str(uuid4())
    callbacks = dict(guard=lambda ticket: True, retain=lambda ticket, original: True,
        build=lambda ticket: build_for(case["der"], ticket))
    return owner, args, callbacks, acquired


def reserve_held(connection, case, *, name="HELD-FIRST"):
    template = prepared_for(case["der"], case["registered"], name=name)
    hold = MariaDBPreparationHoldRepository(connection, case["namespace"]).reserve(
        case["registered"], template.context, str(uuid4()), str(uuid4()), guard=lambda ticket: True)
    connection.commit()  # Explicit test owner, not a library repository.
    return hold


def test_owned_hold_is_visible_and_first_connection_closed_before_builder(connections, case):
    initialize(connections(), case)
    owner, args, callbacks, acquired = held_case(connections, case)
    builds = []
    def build(ticket):
        assert len(acquired) == 1 and not acquired[0].open
        observer = connections()
        held = MariaDBPreparationHoldRepository(observer, case["namespace"]).load(owner.protected_hold)
        assert held.original_manifest_sha256 is None and ticket.icv == 1
        assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 0
        observer.rollback()
        # There is no long-held SQL lock while building: the prior internal
        # preparation path immediately observes the durable hold and refuses.
        with pytest.raises(chain.IssuingChainError, match="^preparation_held_requires_review$"):
            prepare_synthetic(observer, case, name="DIFFERENT")
        observer.rollback()
        builds.append(ticket)
        return build_for(case["der"], ticket)
    callbacks["build"] = build
    after = owner.prepare(*args, **callbacks)
    assert len(builds) == 1 and after.last_icv == 1 and len(acquired) == 2
    assert all(not connection.open for connection in acquired)
    observer = connections()
    held = MariaDBPreparationHoldRepository(observer, case["namespace"]).load(owner.protected_hold)
    assert held.original_manifest_sha256 == owner.protected_original.manifest_sha256
    assert count(observer, "zatca_preparation_hold_v1", case["namespace"]) == 1
    assert repository(observer, case).load(case["registered"]) == after


@pytest.mark.parametrize("method", ["before_commit", "after_commit", "close"])
def test_first_owned_transaction_failure_never_starts_builder(connections, case, method):
    initialize(connections(), case)
    owner, args, callbacks, _ = held_case(connections, case, fault=(1, method))
    builds = []
    callbacks["build"] = lambda ticket: builds.append(ticket)
    with pytest.raises(chain.IssuingChainError, match="^held_preparation_unconfirmed$"):
        owner.prepare(*args, **callbacks)
    assert builds == [] and owner.protected_original is None
    observer = connections()
    persisted = int(method != "before_commit")
    assert count(observer, "zatca_preparation_hold_v1", case["namespace"]) == persisted
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 0
    if persisted:
        assert MariaDBPreparationHoldRepository(observer, case["namespace"]).load(owner.protected_hold).original_manifest_sha256 is None


@pytest.mark.parametrize("method", ["before_commit", "after_commit", "close"])
def test_final_owned_uncertainty_reconciles_exact_original_without_rebuilding(connections, case, method):
    initialize(connections(), case)
    owner, args, callbacks, _ = held_case(connections, case, fault=(2, method))
    builds = []
    def build(ticket):
        builds.append(ticket)
        return build_for(case["der"], ticket)
    callbacks["build"] = build
    with pytest.raises(chain.IssuingChainError, match="^held_preparation_unconfirmed$"):
        owner.prepare(*args, **callbacks)
    assert len(builds) == 1 and owner.protected_original is not None
    observer = connections()
    stored = MariaDBPreparationHoldRepository(observer, case["namespace"]).load(owner.protected_hold)
    assert (stored.original_manifest_sha256 is None) == (method == "before_commit")
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == int(method != "before_commit")
    # A fresh owner cannot build even when the final original transaction rolled back.
    observer.rollback()
    fresh, fresh_args, fresh_callbacks, _ = held_case(connections, case)
    fresh_callbacks["build"] = lambda ticket: pytest.fail("No second builder is permitted")
    with pytest.raises(chain.IssuingChainError, match="^preparation_held_requires_review$"):
        fresh.prepare(*fresh_args, **fresh_callbacks)
    recovered, after = MariaDBPreparationHoldRepository(observer, case["namespace"]).complete(
        owner.protected_hold, owner.protected_original)
    observer.commit()
    assert after.last_icv == 1 and recovered.original_manifest_sha256 == owner.protected_original.manifest_sha256
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 1


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 5, 6])
def test_owned_source_drift_preserves_committed_hold_without_partial_original(connections, case, stage):
    before = initialize(connections(), case)
    owner, args, callbacks, _ = held_case(connections, case)
    calls = []
    def guard(ticket):
        calls.append(ticket)
        return len(calls) != stage
    callbacks["guard"] = guard
    with pytest.raises(chain.IssuingChainError, match="^preparation_source_guard$"):
        owner.prepare(*args, **callbacks)
    observer = connections()
    assert repository(observer, case).load(case["registered"]) == before
    assert count(observer, "zatca_preparation_hold_v1", case["namespace"]) == int(stage > 1)
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 0
    assert (owner.protected_original is not None) == (stage > 2)


def test_pending_hold_survives_owned_server_crash_and_blocks_fresh_worker(connections, case, isolated_server):
    before = initialize(connections(), case)
    hold = reserve_held(connections(), case)
    isolated_server[2]()  # Crash/restart ONLY this fixture's private SQL process.
    observer = connections()
    assert MariaDBPreparationHoldRepository(observer, case["namespace"]).load(hold) == hold
    assert repository(observer, case).load(case["registered"]) == before
    observer.rollback()
    fresh, args, callbacks, _ = held_case(connections, case)
    callbacks["build"] = lambda ticket: pytest.fail("No automatic crash rebuild")
    with pytest.raises(chain.IssuingChainError, match="^preparation_held_requires_review$"):
        fresh.prepare(*args, **callbacks)


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_fresh_worker_cannot_build_while_first_worker_is_building_outside_sql(connections, case, isolation):
    initialize(connections(), case)
    building, release = Event(), Event()
    def first_worker():
        owner, args, callbacks, _ = held_case(lambda: connections(isolation), case)
        def build(ticket):
            building.set()
            assert release.wait(10)
            return build_for(case["der"], ticket)
        callbacks["build"] = build
        return owner.prepare(*args, **callbacks)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first_worker)
        assert building.wait(5)
        try:
            second, args, callbacks, _ = held_case(lambda: connections(isolation), case, name="OTHER")
            callbacks["build"] = lambda ticket: pytest.fail("A pending chain has no next build")
            with pytest.raises(chain.IssuingChainError, match="^preparation_held_requires_review$"):
                second.prepare(*args, **callbacks)
        finally:
            release.set()
        assert future.result(timeout=10).last_icv == 1


def test_completed_hold_retains_source_identity_and_review_does_not_rewind_chain(connections, case):
    initialize(connections(), case)
    first, args, callbacks, _ = held_case(connections, case)
    one = first.prepare(*args, **callbacks)
    second, args, callbacks, _ = held_case(connections, case, name="SECOND")
    two = second.prepare(*args, **callbacks)
    assert two.last_icv == 2 and second.protected_hold.ticket.predecessor == one
    observer = connections()
    _, reviewed = MariaDBPreparationHoldRepository(observer, case["namespace"]).complete(
        first.protected_hold, first.protected_original)
    assert reviewed == two
    changed = replace(first.protected_original,
        xml_bytes=first.protected_original.xml_bytes.replace(b"><", b">\n<"))
    with pytest.raises(chain.IssuingChainError, match="^preparation_original_conflict$"):
        MariaDBPreparationHoldRepository(observer, case["namespace"]).complete(first.protected_hold, changed)
    observer.rollback()
    ctx = replace(first.protected_hold.ticket.context,
        scope=replace(first.protected_hold.ticket.context.scope, issuance_version=2))
    with pytest.raises(chain.IssuingChainError, match="^preparation_held_requires_review$"):
        repository(observer, case).begin_preparation(case["registered"], ctx)


@pytest.mark.parametrize("column,value", [("ticket_bytes", b"PRIVATE BROKEN"), ("ticket_sha256", "a"*64),
    ("invoice_uuid", str(uuid4())), ("candidate_key_sha256", "b"*64),
    ("active_chain_id", None), ("original_manifest_sha256", "c"*64)])
def test_corrupt_hold_is_refused_without_automatic_release_or_repair(connections, case, column, value):
    initialize(connections(), case)
    writer = connections()
    hold = reserve_held(writer, case)
    with writer.cursor() as cursor:
        cursor.execute("UPDATE zatca_preparation_hold_v1 SET " + column + "=%s WHERE storage_namespace=%s AND hold_id=%s",
            (value, case["namespace"], hold.hold_id))
    writer.commit()
    with pytest.raises(chain.IssuingChainError) as error:
        MariaDBPreparationHoldRepository(writer, case["namespace"]).load(hold)
    assert "PRIVATE" not in str(error.value)
    writer.rollback()
    assert count(writer, "zatca_preparation_hold_v1", case["namespace"]) == 1


def test_strict_redelivery_and_direct_unheld_record_cannot_bypass_pending_hold(connections, case):
    initialize(connections(), case)
    connection = connections()
    hold = reserve_held(connection, case)
    original = build_for(case["der"], hold.ticket)
    with pytest.raises(chain.IssuingChainError, match="^preparation_held_requires_review$"):
        MariaDBPreparationHoldRepository(connection, case["namespace"]).reserve(case["registered"],
            hold.ticket.context, hold.ticket.invoice_uuid, hold.hold_id, guard=lambda ticket: True)
    connection.rollback()
    with pytest.raises(chain.IssuingChainError, match="^preparation_held_requires_review$"):
        repository(connection, case).record(hold.ticket.predecessor, original)
    connection.rollback()
    assert count(connection, "zatca_issuance_candidate_v1", case["namespace"]) == 0
    _, after = MariaDBPreparationHoldRepository(connection, case["namespace"]).complete(hold, original)
    connection.commit()
    assert after.last_icv == 1


@pytest.mark.parametrize("same_uuid", [True, False])
def test_changing_unit_does_not_release_source_or_uuid_identity(connections, case, certificates, same_uuid):
    initialize(connections(), case)
    writer = connections()
    hold = reserve_held(writer, case)
    other = registration(certificates[2], chain_id=str(uuid4()), registration_id=str(uuid4()))
    repository(writer, case).create(other)
    writer.commit()
    name = "OTHER-SOURCE" if same_uuid else hold.ticket.context.scope.invoice_name
    template = prepared_for(certificates[2], other, name=name)
    expected = "chain_unique_conflict" if same_uuid else "preparation_held_requires_review"
    with pytest.raises(chain.IssuingChainError, match="^" + expected + "$"):
        MariaDBPreparationHoldRepository(writer, case["namespace"]).reserve(other, template.context,
            hold.ticket.invoice_uuid if same_uuid else str(uuid4()), str(uuid4()), guard=lambda ticket: True)
    writer.rollback()
    assert count(writer, "zatca_preparation_hold_v1", case["namespace"]) == 1
    assert repository(writer, case).load(other).last_icv == 0


@pytest.mark.parametrize("change", ["uuid", "source", "route"])
def test_exact_ticket_required_for_completion_not_just_the_hold_identifier(connections, case, change):
    initialize(connections(), case)
    writer = connections()
    hold = reserve_held(writer, case)
    ticket = hold.ticket
    if change == "uuid": ticket = replace(ticket, invoice_uuid=str(uuid4()))
    if change == "source": ticket = replace(ticket, context=replace(ticket.context, source_snapshot_sha256="a"*64))
    if change == "route":
        ticket = replace(ticket, context=replace(ticket.context,
            route=replace(ticket.context.route, url=ticket.context.route.url.replace("/phase2/", "/other/"))))
    changed = replace(hold, ticket=ticket)
    assert changed.ticket != hold.ticket
    original = build_for(case["der"], ticket)
    with pytest.raises(chain.IssuingChainError, match="^preparation_hold_conflict$"):
        MariaDBPreparationHoldRepository(writer, case["namespace"]).complete(changed, original)
    writer.rollback()
    assert count(writer, "zatca_issuance_candidate_v1", case["namespace"]) == 0


@pytest.mark.parametrize("operation", ["reserve", "load", "complete"])
def test_held_repository_refuses_autocommit_without_reconfiguring_session(connections, case, operation):
    initialize(connections(), case)
    hold = reserve_held(connections(), case)
    writer = connections(autocommit=True)
    handle = MariaDBPreparationHoldRepository(writer, case["namespace"])
    with pytest.raises(chain.IssuingChainError, match="^chain_autocommit$"):
        if operation == "reserve":
            handle.reserve(case["registered"], hold.ticket.context, str(uuid4()), str(uuid4()), guard=lambda ticket: True)
        elif operation == "load": handle.load(hold)
        else: handle.complete(hold, build_for(case["der"], hold.ticket))
    assert writer.get_autocommit() is True
    assert count(writer, "zatca_preparation_hold_v1", case["namespace"]) == 1


def test_unbound_partial_original_is_not_repaired_or_adopted(connections, case):
    initialize(connections(), case)
    owner, args, callbacks, _ = held_case(connections, case)
    one = owner.prepare(*args, **callbacks)
    writer = connections()
    pending = reserve_held(writer, case, name="SECOND")
    second = build_for(case["der"], pending.ticket)
    # Deliberately violate the writer protocol in this synthetic database only.
    MariaDBJournalRepository(writer, case["namespace"]).put(second)
    writer.commit()
    with pytest.raises(chain.IssuingChainError, match="^preparation_partial_original$"):
        MariaDBPreparationHoldRepository(writer, case["namespace"]).complete(pending, second)
    writer.rollback()
    assert repository(writer, case).load(case["registered"]) == one
    assert count(writer, "zatca_issuance_candidate_v1", case["namespace"]) == 2


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("exact", [True, False])
def test_competing_exact_completion_advances_once_and_different_bytes_require_review(connections, case, isolation, exact):
    initialize(connections(), case)
    writer = connections(isolation)
    pending = reserve_held(writer, case)
    original = build_for(case["der"], pending.ticket)
    changed = original if exact else replace(original, xml_bytes=original.xml_bytes.replace(b"><", b">\n<"))
    _, one = MariaDBPreparationHoldRepository(writer, case["namespace"]).complete(pending, original)
    ready = Event()
    def competitor():
        connection = connections(isolation)
        ready.set()
        try:
            _, after = MariaDBPreparationHoldRepository(connection, case["namespace"]).complete(pending, changed)
            connection.commit()
            return after
        except chain.IssuingChainError as error:
            connection.rollback()
            return error.code
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(competitor)
        assert ready.wait(5)
        with pytest.raises(TimeoutError): future.result(timeout=0.05)
        writer.commit()
        outcome = future.result(timeout=10)
    assert outcome == (one if exact else "preparation_original_conflict")
    observer = connections()
    assert repository(observer, case).load(case["registered"]) == one
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 1


@pytest.mark.parametrize("state", ["pending", "recorded", "missing"])
def test_protected_source_lookup_without_in_memory_ticket_is_observation_only(connections, case, state):
    writer = connections()
    initialize(writer, case)
    hold = None if state == "missing" else reserve_held(writer, case)
    if state == "recorded":
        original = build_for(case["der"], hold.ticket)
        hold, _ = MariaDBPreparationHoldRepository(writer, case["namespace"]).complete(hold, original)
        writer.commit()
    observer = connections()
    repository = MariaDBPreparationHoldRepository(observer, case["namespace"])
    assert repository.load_for_source("Sales Invoice", "TEST", "HELD-FIRST") == hold
    assert MariaDBPreparationHoldRepository(observer, str(uuid4())).load_for_source("Sales Invoice", "TEST", "HELD-FIRST") is None
    assert count(observer, "zatca_preparation_hold_v1", case["namespace"]) == int(state != "missing")
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == int(state == "recorded")


def test_source_lookup_after_owned_crash_does_not_need_the_original_process_ticket(connections, case, isolated_server):
    writer = connections()
    initialize(writer, case)
    expected = reserve_held(writer, case)
    isolated_server[2]()
    # Only the saved source identity, not the retained object, is supplied.
    observer = connections()
    observed = MariaDBPreparationHoldRepository(observer, case["namespace"]).load_for_source("Sales Invoice", "TEST", "HELD-FIRST")
    assert observed == expected and observed.original_manifest_sha256 is None
    assert count(observer, "zatca_issuance_candidate_v1", case["namespace"]) == 0


@pytest.fixture(scope="module")
def review_source_schema(isolated_server):
    """ONLY this fixture's synthetic source tables, not a Frappe site/schema."""
    with pymysql.connect(unix_socket=isolated_server[0], user="root",
        database="zatca_journal_rehearsal", autocommit=True) as connection:
        with connection.cursor() as cursor:
            for doctype, fields in review_access.REVIEW_FIELDS.items():
                columns = ["`name` VARCHAR(140) PRIMARY KEY", "`modified` DATETIME(6) NOT NULL"]
                numeric = ("docstatus", "custom__use_company_certificate__keys")
                columns += ["`" + field + "` " + ("BIGINT" if field in numeric else "LONGTEXT") for field in fields]
                cursor.execute("CREATE TABLE `tab" + doctype + "` (" + ",".join(columns) + ") ENGINE=InnoDB")


def native_review(connections, reviewer, certificates, monkeypatch, *, state="pending", doctype="Sales Invoice", owner="company", docstatus=0):
    selected = review_scenario(reviewer, certificates[0], monkeypatch, state="pending", doctype=doctype, owner=owner, docstatus=docstatus)
    selected.scope = replace(selected.scope, storage_namespace=str(uuid4()))
    selected.opened = []
    def factory(scope):
        assert scope == selected.scope
        connection = connections()
        selected.opened.append(connection)
        return connection
    selected.factory = factory
    selected.service = review_access.SavedPreparationReviewService(selected.scope, factory)
    monkeypatch.setattr(review_access, "MariaDBPreparationHoldRepository", MariaDBPreparationHoldRepository)
    writer = connections()
    with writer.cursor() as cursor:
        for doc in reviewer.documents.values():
            row = review_access.SavedPreparationReviewRow.from_document(doc)
            fields = ("name", "modified", *row.fields)
            cursor.execute("INSERT INTO `tab" + row.doctype + "` ("
                + ",".join("`" + field + "`" for field in fields) + ") VALUES ("
                + ",".join("%s" for _ in fields) + ") ON DUPLICATE KEY UPDATE "
                + ",".join("`" + field + "`=VALUES(`" + field + "`)" for field in fields),
                (row.name, doc.modified, *row.values))
    writer.commit()
    if state != "missing":
        template = selected.hold
        registered = template.ticket.predecessor.registration
        storage.MariaDBIssuingChainRepository(writer, selected.scope.storage_namespace).create(registered)
        selected.hold = MariaDBPreparationHoldRepository(writer, selected.scope.storage_namespace).reserve(
            registered, template.ticket.context, template.ticket.invoice_uuid, template.hold_id, guard=lambda ticket: True)
        if state == "recorded":
            original = build_for(certificates[0], selected.hold.ticket)
            selected.hold, _ = MariaDBPreparationHoldRepository(writer, selected.scope.storage_namespace).complete(selected.hold, original)
        writer.commit()
    else:
        selected.hold = None
    writer.close()
    return selected


@pytest.mark.parametrize("state", ["pending", "recorded", "missing"])
@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
def test_saved_review_uses_actual_owned_source_and_hold_reads_only(review_source_schema, connections, reviewer, certificates, monkeypatch, state, doctype):
    selected = native_review(connections, reviewer, certificates, monkeypatch, state=state, doctype=doctype)
    report = selected.service.inspect(selected.invoice.name, doctype=doctype)
    assert report["original_recorded_observed"] is {"pending":False, "recorded":True, "missing":None}[state]
    assert all(report[name] is False for name in review_access.FALSE_FLAGS)
    assert len(selected.opened) == 1 and not selected.opened[0].open
    reviewer.runtime.db.commit.assert_not_called()
    reviewer.runtime.db.rollback.assert_not_called()
    observer = connections()
    assert count(observer, "zatca_preparation_hold_v1", selected.scope.storage_namespace) == int(state != "missing")
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == int(state == "recorded")


@pytest.mark.parametrize("column,value", [("tax_id","OTHER"), ("custom_select","Simulation")])
def test_stale_ambient_source_cannot_hide_committed_database_change(review_source_schema, connections, reviewer, certificates, monkeypatch, column, value):
    selected = native_review(connections, reviewer, certificates, monkeypatch)
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("UPDATE `tabCompany` SET `" + column + "`=%s WHERE name=%s", (value, "TEST"))
    writer.commit()
    constructor = Mock(wraps=MariaDBPreparationHoldRepository)
    monkeypatch.setattr(review_access, "MariaDBPreparationHoldRepository", constructor)
    with pytest.raises(InspectionFailed): selected.service.inspect(selected.invoice.name)
    constructor.assert_not_called()
    assert len(selected.opened) == 1 and not selected.opened[0].open


def test_inspection_discards_only_its_owned_uncommitted_observation(review_source_schema, connections, reviewer, certificates, monkeypatch):
    selected = native_review(connections, reviewer, certificates, monkeypatch)
    owned = connections()
    with owned.cursor() as cursor:
        cursor.execute("UPDATE zatca_preparation_hold_v1 SET ticket_sha256=%s WHERE storage_namespace=%s",
            ("f"*64, selected.scope.storage_namespace))
    selected.service = review_access.SavedPreparationReviewService(selected.scope, lambda scope: owned)
    report = selected.service.inspect(selected.invoice.name)
    assert report["state"] == "PENDING_ORIGINAL_UNCONFIRMED_REVIEW" and not owned.open
    observer = connections()
    observed = MariaDBPreparationHoldRepository(observer, selected.scope.storage_namespace).load_for_source("Sales Invoice", "TEST", "INV-TEST")
    assert observed == selected.hold


@pytest.mark.parametrize("owner", ["device", "linked"])
def test_related_owner_reads_and_real_source_projections(review_source_schema, connections, reviewer, certificates, monkeypatch, owner):
    selected = native_review(connections, reviewer, certificates, monkeypatch, owner=owner)
    assert selected.service.inspect(selected.invoice.name)["state"] == "PENDING_ORIGINAL_UNCONFIRMED_REVIEW"
    assert len(selected.opened) == 1 and not selected.opened[0].open


def native_recovery(connections, recoverer, certificates, monkeypatch, *, doctype="Sales Invoice", owner="company"):
    selected = native_review(connections, recoverer, certificates, monkeypatch, doctype=doctype, owner=owner, docstatus=1)
    candidate = build_for(certificates[0], selected.hold.ticket)
    selected.retained = recovery_access.RetainedPreparationOriginal(selected.scope, selected.hold, candidate)
    selected.evidence = Mock(return_value=True)
    selected.recovery = recovery_access.SavedPreparationRecoveryService(selected.scope, selected.evidence, selected.factory)
    return selected


def recover(selected):
    return selected.recovery.persist(selected.invoice.name, selected.retained, doctype=selected.invoice.doctype)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_permissioned_recovery_and_exact_redelivery_use_real_source_and_original_locks(review_source_schema,
    connections, recoverer, certificates, monkeypatch, doctype, owner):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch, doctype=doctype, owner=owner)
    original = selected.retained.candidate
    for _ in range(2):
        assert recover(selected)["state"] == "PREPARATION_ORIGINAL_STORED_LOCAL_NO_REPLAY"
    assert all(not connection.open for connection in selected.opened) and len(selected.opened) == 2
    observer = connections()
    state = storage.MariaDBIssuingChainRepository(observer, selected.scope.storage_namespace).load(selected.hold.ticket.predecessor.registration)
    assert state.last_icv == 1
    saved = MariaDBJournalRepository(observer, selected.scope.storage_namespace).load(original.key_sha256)
    assert saved.candidate.xml_bytes == original.xml_bytes and saved.events == ()
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 1
    with observer.cursor() as cursor:
        cursor.execute("SELECT modified,docstatus FROM `tab" + doctype + "` WHERE name=%s", (selected.invoice.name,))
        assert cursor.fetchone() == (selected.invoice.modified, 1)
    recoverer.runtime.db.commit.assert_not_called()
    recoverer.runtime.db.rollback.assert_not_called()


@pytest.mark.parametrize("fault", ["before_commit", "after_commit", "close"])
def test_permissioned_unknown_commit_preserves_hold_and_explicit_exact_reconciliation(review_source_schema,
    connections, recoverer, certificates, monkeypatch, fault):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    opened = []
    def factory(scope):
        raw = connections()
        opened.append(raw)
        return InjectedCommitConnection(raw, fault)
    selected.recovery = recovery_access.SavedPreparationRecoveryService(selected.scope, selected.evidence, factory)
    assert recover(selected)["state"] == "PREPARATION_RECOVERY_UNCONFIRMED_NO_REBUILD"
    assert len(opened) == 1 and not opened[0].open
    observer = connections()
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == int(fault != "before_commit")
    hold = MariaDBPreparationHoldRepository(observer, selected.scope.storage_namespace).load_for_source(
        selected.invoice.doctype, selected.company.name, selected.invoice.name)
    assert (hold.original_manifest_sha256 is None) == (fault == "before_commit")
    observer.rollback()
    selected.recovery = recovery_access.SavedPreparationRecoveryService(selected.scope, selected.evidence, selected.factory)
    assert recover(selected)["local_transaction_completed"] is True  # Explicit separate LOCAL recovery.
    observer.rollback()
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 1
    saved = MariaDBJournalRepository(observer, selected.scope.storage_namespace).load(selected.retained.candidate.key_sha256)
    assert saved.candidate.xml_bytes == selected.retained.candidate.xml_bytes


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_permission_revocation_before_and_after_commit_never_clears_or_replays_original(review_source_schema,
    connections, recoverer, certificates, monkeypatch, stage):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    calls = []
    def evidence(*args, **kwargs):
        calls.append(kwargs["connection"])
        if len(calls) == stage:
            recoverer.denied_operations.add((selected.invoice.doctype, selected.invoice.name, "write"))
        return True
    selected.evidence.side_effect = evidence
    original = selected.retained.candidate.xml_bytes
    with pytest.raises(recoverer.runtime.PermissionError):
        recover(selected)
    observer = connections()
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == int(stage == 4)
    state = storage.MariaDBIssuingChainRepository(observer, selected.scope.storage_namespace).load(selected.hold.ticket.predecessor.registration)
    assert state.last_icv == int(stage == 4)
    assert selected.retained.candidate.xml_bytes == original
    assert all(not connection.open for connection in selected.opened)
    recoverer.runtime.db.commit.assert_not_called()
    recoverer.runtime.db.rollback.assert_not_called()


def test_recovery_rechecks_real_source_projection_not_stale_orm_snapshot(review_source_schema,
    connections, recoverer, certificates, monkeypatch):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("OTHER", "TEST"))
    writer.commit()
    constructor = Mock(wraps=MariaDBPreparationHoldRepository)
    monkeypatch.setattr(recovery_access, "MariaDBPreparationHoldRepository", constructor)
    assert recover(selected)["local_transaction_completed"] is False
    constructor.assert_not_called()
    assert count(writer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 0


def test_conflicting_exact_identity_but_changed_xml_is_not_overwritten(review_source_schema,
    connections, recoverer, certificates, monkeypatch):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    assert recover(selected)["local_transaction_completed"] is True
    original = selected.retained.candidate
    changed = replace(original, xml_bytes=original.xml_bytes.replace(b"><", b">\n<"))
    assert changed.artifact.uuid == original.artifact.uuid and changed.xml_bytes != original.xml_bytes
    selected.retained = replace(selected.retained, candidate=changed)
    assert recover(selected)["state"] == "PREPARATION_RECOVERY_UNCONFIRMED_NO_REBUILD"
    observer = connections()
    saved = MariaDBJournalRepository(observer, selected.scope.storage_namespace).load(original.key_sha256)
    assert saved.candidate.xml_bytes == original.xml_bytes
    assert storage.MariaDBIssuingChainRepository(observer, selected.scope.storage_namespace).load(
        selected.hold.ticket.predecessor.registration).last_icv == 1


def test_borrowed_parent_does_not_commit_rollback_or_close_private_parent(review_source_schema,
    connections, recoverer, certificates, monkeypatch):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    parent = connections()
    with parent.cursor() as cursor:
        cursor.execute("INSERT INTO chain_parent_work VALUES (%s,%s)", (selected.scope.storage_namespace, "SYNTHETIC UNCOMMITTED PARENT"))
    recoverer.runtime.db._conn = parent
    selected.recovery = recovery_access.SavedPreparationRecoveryService(selected.scope, selected.evidence, lambda scope: parent)
    assert recover(selected)["local_transaction_completed"] is False
    observer = connections()
    assert parent.open and count(parent, "chain_parent_work", selected.scope.storage_namespace) == 1
    assert count(observer, "chain_parent_work", selected.scope.storage_namespace) == 0
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 0
    parent.rollback()  # Explicit test owner cleanup only.
    parent.close()


def native_custody(connections, custodian, certificates, monkeypatch, **kwargs):
    selected = native_recovery(connections, custodian, certificates, monkeypatch, **kwargs)
    selected.cipher = custody.PreparationOriginalCipher({"test-preparation-v1": b"P"*32})
    selected.sealed = selected.cipher.seal(selected.retained, key_id="test-preparation-v1")
    selected.keys = Mock(return_value=custody_access.PreparationCustodyResources(selected.scope, selected.cipher))
    selected.custody = custody_access.SavedPreparationCustodyService(
        selected.scope, selected.keys, selected.evidence, selected.factory)
    return selected


def stage_custody(selected):
    return selected.custody.stage(selected.invoice.name, selected.sealed, doctype=selected.invoice.doctype)


def recover_custody(selected):
    return selected.custody.persist_from_custody(selected.invoice.name, doctype=selected.invoice.doctype)


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("owner", ["company", "device", "linked"])
def test_native_encrypted_copy_does_not_advance_hold_then_recovers_exact_original(review_source_schema,
    connections, custodian, certificates, monkeypatch, doctype, owner):
    selected = native_custody(connections, custodian, certificates, monkeypatch, doctype=doctype, owner=owner)
    namespace = selected.scope.storage_namespace
    assert stage_custody(selected)["local_transaction_completed"] is True
    observer = connections()
    assert count(observer, "zatca_preparation_custody_v1", namespace) == 1
    assert count(observer, "zatca_issuance_candidate_v1", namespace) == 0
    stored_hold = MariaDBPreparationHoldRepository(observer, namespace).load(selected.hold)
    assert stored_hold.original_manifest_sha256 is None
    stored = custody.MariaDBPreparationCustodyRepository(observer, namespace, selected.cipher).load(selected.hold.hold_id)
    assert stored == selected.sealed
    assert selected.retained.candidate.xml_bytes not in stored.ciphertext
    observer.rollback()
    # A new service receives only the saved source name, not the plaintext original.
    selected.custody = custody_access.SavedPreparationCustodyService(
        selected.scope, selected.keys, selected.evidence, selected.factory)
    assert recover_custody(selected)["local_transaction_completed"] is True
    assert recover_custody(selected)["local_transaction_completed"] is True
    assert count(observer, "zatca_issuance_candidate_v1", namespace) == 1
    saved = MariaDBJournalRepository(observer, namespace).load(selected.retained.candidate.key_sha256)
    assert saved.candidate.xml_bytes == selected.retained.candidate.xml_bytes and saved.events == ()
    state = storage.MariaDBIssuingChainRepository(observer, namespace).load(selected.hold.ticket.predecessor.registration)
    assert state.last_icv == 1
    assert all(not connection.open for connection in selected.opened)
    custodian.runtime.db.commit.assert_not_called()
    custodian.runtime.db.rollback.assert_not_called()


def test_ciphertext_survives_private_database_restart_without_resealing(review_source_schema,
    isolated_server, connections, custodian, certificates, monkeypatch):
    selected = native_custody(connections, custodian, certificates, monkeypatch)
    assert stage_custody(selected)["local_transaction_completed"] is True
    sealed = selected.sealed
    original = selected.retained.candidate.xml_bytes
    selected.retained = None  # No plaintext original is passed into the recovery API.
    isolated_server[2]()  # Owned private subprocess ONLY, never Bench or a tenant DB.
    fresh_cipher = custody.PreparationOriginalCipher({"test-preparation-v1": b"P"*32})
    selected.keys.return_value = custody_access.PreparationCustodyResources(selected.scope, fresh_cipher)
    assert selected.custody.load(selected.invoice.name) == sealed
    assert recover_custody(selected)["local_transaction_completed"] is True
    observer = connections()
    saved = MariaDBJournalRepository(observer, selected.scope.storage_namespace).load(sealed.candidate_sha256)
    assert saved.candidate.xml_bytes == original


@pytest.mark.parametrize("commit", [False, True])
def test_ciphertext_raw_stage_obeys_caller_atomicity(review_source_schema,
    connections, custodian, certificates, monkeypatch, commit):
    selected = native_custody(connections, custodian, certificates, monkeypatch)
    writer, observer = connections(), connections()
    repo = custody.MariaDBPreparationCustodyRepository(writer, selected.scope.storage_namespace, selected.cipher)
    assert repo.stage(selected.sealed) == selected.sealed
    assert count(observer, "zatca_preparation_custody_v1", selected.scope.storage_namespace) == 0
    writer.commit() if commit else writer.rollback()
    observer.rollback()
    assert count(observer, "zatca_preparation_custody_v1", selected.scope.storage_namespace) == int(commit)
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 0


def test_exact_ciphertext_redelivery_matches_but_reseal_cannot_overwrite(review_source_schema,
    connections, custodian, certificates, monkeypatch):
    selected = native_custody(connections, custodian, certificates, monkeypatch)
    original = selected.sealed
    for _ in range(2): assert stage_custody(selected)["local_transaction_completed"] is True
    selected.sealed = selected.cipher.seal(selected.retained, key_id="test-preparation-v1")
    assert stage_custody(selected)["local_transaction_completed"] is False
    assert selected.custody.load(selected.invoice.name) == original
    observer = connections()
    assert count(observer, "zatca_preparation_custody_v1", selected.scope.storage_namespace) == 1


@pytest.mark.parametrize("operation", ["stage", "recover"])
@pytest.mark.parametrize("fault", ["before_commit", "after_commit", "close"])
def test_unknown_custody_commit_never_retries_or_reseals(review_source_schema,
    connections, custodian, certificates, monkeypatch, operation, fault):
    selected = native_custody(connections, custodian, certificates, monkeypatch)
    if operation == "recover": assert stage_custody(selected)["local_transaction_completed"] is True
    acquired = []
    def factory(scope):
        raw = connections()
        acquired.append(raw)
        # Recovery first owns a rollback-only protected read; fault the write only.
        number = 1 if operation == "stage" else 2
        return InjectedCommitConnection(raw, fault if len(acquired) == number else None)
    selected.custody = custody_access.SavedPreparationCustodyService(
        selected.scope, selected.keys, selected.evidence, factory)
    report = stage_custody(selected) if operation == "stage" else recover_custody(selected)
    assert report["local_transaction_completed"] is False
    assert len(acquired) == (1 if operation == "stage" else 2)
    assert all(not conn.open for conn in acquired)
    observer = connections()
    table = "zatca_preparation_custody_v1" if operation == "stage" else "zatca_issuance_candidate_v1"
    assert count(observer, table, selected.scope.storage_namespace) == int(fault != "before_commit")
    observer.rollback()
    # A separate explicit local call uses the SAME ciphertext, never a new seal.
    selected.custody = custody_access.SavedPreparationCustodyService(
        selected.scope, selected.keys, selected.evidence, selected.factory)
    assert (stage_custody(selected) if operation == "stage" else recover_custody(selected))["local_transaction_completed"] is True
    assert selected.custody.load(selected.invoice.name) == selected.sealed


@pytest.mark.parametrize("column", ["nonce", "ciphertext", "payload_sha256"])
def test_authenticated_storage_corruption_cannot_fall_back_to_rebuilding(review_source_schema,
    connections, custodian, certificates, monkeypatch, column):
    selected = native_custody(connections, custodian, certificates, monkeypatch)
    assert stage_custody(selected)["local_transaction_completed"] is True
    writer = connections()
    value = {"nonce": b"N"*12, "ciphertext":b"PRIVATE CORRUPTED CIPHERTEXT",
        "payload_sha256":"f"*64}[column]
    with writer.cursor() as cursor:
        cursor.execute("UPDATE zatca_preparation_custody_v1 SET " + column + "=%s WHERE storage_namespace=%s AND hold_id=%s",
            (value, selected.scope.storage_namespace, selected.hold.hold_id))
    writer.commit()
    with pytest.raises(InspectionFailed): recover_custody(selected)
    assert count(writer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 0
    stored = MariaDBPreparationHoldRepository(writer, selected.scope.storage_namespace).load(selected.hold)
    assert stored.original_manifest_sha256 is None


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("exact", [False, True])
def test_competing_ciphertext_stages_share_hold_first_lock_order(review_source_schema,
    connections, custodian, certificates, monkeypatch, isolation, exact):
    selected = native_custody(connections, custodian, certificates, monkeypatch)
    first = connections(isolation)
    repo = custody.MariaDBPreparationCustodyRepository(first, selected.scope.storage_namespace, selected.cipher)
    repo.stage(selected.sealed)
    other = selected.sealed if exact else selected.cipher.seal(selected.retained, key_id="test-preparation-v1")
    ready = Event()
    def competing():
        conn = connections(isolation)
        ready.set()
        try:
            result = custody.MariaDBPreparationCustodyRepository(conn, selected.scope.storage_namespace, selected.cipher).stage(other)
            conn.commit()
            return result
        except custody.PreparationCustodyError:
            conn.rollback()
            return None
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(competing)
        assert ready.wait(2)
        with pytest.raises(TimeoutError): future.result(timeout=0.03)
        first.commit()
        assert future.result(timeout=5) == (selected.sealed if exact else None)
    observer = connections()
    stored = custody.MariaDBPreparationCustodyRepository(observer, selected.scope.storage_namespace, selected.cipher).load(selected.hold.hold_id)
    assert stored == selected.sealed
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 0


def test_missing_requested_hold_is_not_created_by_recovery(review_source_schema,
    connections, recoverer, certificates, monkeypatch):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    selected.retained = replace(selected.retained, hold=replace(selected.hold, hold_id=str(uuid4())))
    assert recover(selected)["local_transaction_completed"] is False
    observer = connections()
    assert count(observer, "zatca_preparation_hold_v1", selected.scope.storage_namespace) == 1
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 0


@pytest.mark.parametrize("docstatus", [0, 2])
def test_native_draft_cancelled_policy_never_opens_recovery_connection(review_source_schema,
    connections, recoverer, certificates, monkeypatch, docstatus):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    selected.invoice.docstatus = docstatus
    with pytest.raises(InspectionFailed): recover(selected)
    assert selected.opened == []
    selected.evidence.assert_not_called()


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_two_authorized_local_recoveries_advance_once_with_actual_source_locks(review_source_schema,
    connections, recoverer, certificates, monkeypatch, isolation):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    guarded, release = Event(), Event()
    calls = []
    def evidence(*args, **kwargs):
        calls.append(kwargs["connection"])
        if len(calls) == 3:
            guarded.set()
            assert release.wait(10)
        return True
    first = recovery_access.SavedPreparationRecoveryService(selected.scope, evidence, lambda scope: connections(isolation))
    second = recovery_access.SavedPreparationRecoveryService(selected.scope, lambda *args, **kwargs: True, lambda scope: connections(isolation))
    ready = Event()
    def competing():
        ready.set()
        return second.persist(selected.invoice.name, selected.retained, doctype=selected.invoice.doctype)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(first.persist, selected.invoice.name, selected.retained, doctype=selected.invoice.doctype)
        assert guarded.wait(5)
        try:
            second_result = pool.submit(competing)
            assert ready.wait(5)
            with pytest.raises(TimeoutError): second_result.result(timeout=0.05)
        finally:
            release.set()
        assert first_result.result(timeout=10)["local_transaction_completed"] is True
        assert second_result.result(timeout=10)["local_transaction_completed"] is True
    observer = connections()
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 1
    assert storage.MariaDBIssuingChainRepository(observer, selected.scope.storage_namespace).load(
        selected.hold.ticket.predecessor.registration).last_icv == 1


def test_evidence_callback_projected_sql_drift_is_rolled_back_not_committed(review_source_schema,
    connections, recoverer, certificates, monkeypatch):
    selected = native_recovery(connections, recoverer, certificates, monkeypatch)
    calls = []
    def evidence(*args, **kwargs):
        calls.append(kwargs["connection"])
        if len(calls) == 2:
            with kwargs["connection"].cursor() as cursor:
                cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("OTHER", "TEST"))
        return True
    selected.evidence.side_effect = evidence
    assert recover(selected)["local_transaction_completed"] is False
    observer = connections()
    with observer.cursor() as cursor:
        cursor.execute("SELECT tax_id FROM `tabCompany` WHERE name=%s", ("TEST",))
        assert cursor.fetchone() == (selected.company.tax_id,)
    assert count(observer, "zatca_issuance_candidate_v1", selected.scope.storage_namespace) == 0
