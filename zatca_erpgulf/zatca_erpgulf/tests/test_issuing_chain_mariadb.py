"""Owned private chain/artifact SQL rehearsal; never a tenant or authority."""

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import issuing_chain as chain
from zatca_erpgulf.zatca_erpgulf import issuing_chain_repository as storage
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_chain import registration, prepared_for
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event


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
    assert table in ("zatca_issuing_chain_v1", "zatca_issuance_candidate_v1", "chain_parent_work")
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
