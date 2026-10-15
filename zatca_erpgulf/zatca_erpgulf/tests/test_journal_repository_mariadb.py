"""Opt-in real InnoDB rehearsal in a NEW private server, never a site database.

Run through tools/run_unification_rehearsal.py --private-sql and its mandatory
offline guard. An inherited environment flag alone cannot acquire resources.
No socket/host/site credentials are read
from environment or bench configuration. This fixture creates its own data dir,
disables TCP/default option files, verifies that exact private socket/data dir,
and terminates only its own subprocess. No schema installer exists in runtime.
"""

import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pymysql
import pytest
from lxml import etree

from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.dispatch_journal import DispatchJournal
from zatca_erpgulf.zatca_erpgulf.journal_repository import MariaDBJournalRepository
from zatca_erpgulf.zatca_erpgulf.journal_storage import JournalStorageError
from zatca_erpgulf.zatca_erpgulf.response_assessment import ResponseAssessment
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_dispatch_journal import event
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import candidate
from zatca_erpgulf.zatca_erpgulf.tests.offline_rehearsal_plugin import active_guard
from zatca_erpgulf.zatca_erpgulf.primary_receipt_persistence import PrimaryReceiptPersistence
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_persistence import retained
from zatca_erpgulf.zatca_erpgulf.tests.test_issuance_candidate import scope


pytestmark = pytest.mark.skipif(
    os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Opt-in private MariaDB subprocess rehearsal, not a configured site connection",
)


@pytest.fixture(scope="module")
def isolated_server(tmp_path_factory):
    guard = active_guard()
    if guard is None:
        pytest.fail("Private SQL requires tools/run_unification_rehearsal.py --private-sql and its offline guard")
    server_binary, install_binary = shutil.which("mariadbd"), shutil.which("mariadb-install-db")
    if not server_binary or not install_binary:
        pytest.fail("Private MariaDB rehearsal requires local server/install binaries")
    root = guard.new_private_directory()
    root.chmod(0o700)
    data, socket = root / "data", root / "server.sock"
    if len(str(socket).encode()) >= 100:
        pytest.fail("Private rehearsal socket path exceeds the conservative bound")
    install_arguments, arguments = guard.register_private_server(root, install_binary, server_binary)
    with (root / "install.log").open("wb") as install_log:
        subprocess.run(install_arguments, check=True, stdout=install_log, stderr=subprocess.STDOUT, timeout=30)
    with (root / "server.log").open("wb") as server_log:
        process = subprocess.Popen(arguments, stdout=server_log, stderr=subprocess.STDOUT)

        def ready():
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    pytest.fail("Private MariaDB subprocess exited before readiness")
                try:
                    return pymysql.connect(unix_socket=str(socket), user="root", connect_timeout=1, autocommit=True)
                except pymysql.OperationalError:
                    time.sleep(0.05)
            pytest.fail("Private MariaDB subprocess readiness timeout")

        def crash_and_restart():
            # Only this exact owned subprocess is killed. No service command or
            # process-name lookup; redo/rollback is exercised on synthetic data.
            nonlocal process
            process.kill()
            process.wait(timeout=5)
            process = subprocess.Popen(arguments, stdout=server_log, stderr=subprocess.STDOUT)
            with ready() as admin:
                with admin.cursor() as cursor:
                    cursor.execute("SELECT @@socket,@@datadir,@@skip_networking")
                    returned_socket, returned_data, networking = cursor.fetchone()
                    assert Path(returned_socket).resolve() == socket.resolve()
                    assert Path(returned_data).resolve() == data.resolve()
                    assert networking == 1

        try:
            with ready() as admin:
                with admin.cursor() as cursor:
                    cursor.execute("SELECT @@socket,@@datadir,@@skip_networking,@@innodb_flush_log_at_trx_commit,VERSION()")
                    configured_socket, configured_data, networking, flush_mode, version = cursor.fetchone()
                    assert Path(configured_socket).resolve() == socket.resolve()
                    assert Path(configured_data).resolve() == data.resolve()
                    assert networking == 1 and flush_mode == 1
                    cursor.execute("CREATE DATABASE zatca_journal_rehearsal CHARACTER SET utf8mb4")
                    cursor.execute("USE zatca_journal_rehearsal")
                    schema = Path(__file__).resolve().parents[3] / "docs/zatca_unification/rehearsal_schema.sql"
                    text = "\n".join(line for line in schema.read_text().splitlines() if not line.lstrip().startswith("--"))
                    for statement in text.split(";"):
                        if statement.strip():
                            cursor.execute(statement)
            yield str(socket), version, crash_and_restart
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert process.poll() is not None


@pytest.fixture
def connections(isolated_server):
    socket = isolated_server[0]
    opened = []

    def connect(isolation="REPEATABLE READ", *, autocommit=False):
        assert isolation in ("REPEATABLE READ", "READ COMMITTED")
        connection = pymysql.connect(
            unix_socket=socket, user="root", database="zatca_journal_rehearsal",
            charset="utf8mb4", autocommit=autocommit, connect_timeout=2,
            read_timeout=5, write_timeout=5,
        )
        opened.append(connection)
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL " + isolation)
            cursor.execute("SET SESSION innodb_lock_wait_timeout=1")
        return connection

    yield connect
    for connection in opened:
        if connection.open:
            try:
                connection.rollback()
            except pymysql.Error:
                pass  # Expected for deliberately crash-interrupted connections.
            finally:
                connection.close()


@pytest.fixture
def namespace():
    return str(uuid4())


@pytest.fixture(scope="module")
def prepared(certificates):
    return candidate(certificates[0])


def save(connection, namespace, prepared):
    journal = MariaDBJournalRepository(connection, namespace).put(prepared)
    connection.commit()  # Test caller, never repository or document hook.
    return journal


def test_committed_roundtrip_new_connection_preserves_context_bytes_and_receipts(connections, namespace, prepared, isolated_server):
    connection = connections()
    empty = save(connection, namespace, prepared)
    repo = MariaDBJournalRepository(connection, namespace)
    started = repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256)
    connection.commit()
    unknown = repo.append(prepared.key_sha256, event(prepared, "TRANSPORT_UNKNOWN", 2), expected_journal_sha256=started.journal_sha256)
    connection.commit()
    raw = b'{"validationResults":{"status":"PASS","errorMessages":[]},"reportingStatus":"REPORTED"}'
    observed = event(prepared, "HTTP_RESPONSE", 3, response_bytes=raw)
    complete = repo.append(prepared.key_sha256, observed, expected_journal_sha256=unknown.journal_sha256)
    connection.commit()
    connection.close()
    recovered = MariaDBJournalRepository(connections(), namespace).load(prepared.key_sha256)
    assert recovered == complete
    assert recovered.candidate == prepared
    assert recovered.candidate.xml_bytes == prepared.xml_bytes
    assert recovered.events[-1].response_bytes == raw
    assert ResponseAssessment(recovered).outcome == "REPORTING_ACCEPTANCE_MATCHED"
    assert recovered.diagnostic_projection()["replay_authorized"] is False
    assert isolated_server[1]  # The exercised server revision is available.


def test_duplicate_put_and_event_redelivery_are_idempotent_without_overwrite(connections, namespace, prepared):
    connection = connections()
    empty = save(connection, namespace, prepared)
    repo = MariaDBJournalRepository(connection, namespace)
    assert repo.put(prepared) == empty
    started = repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256)
    connection.commit()
    completed = repo.append(prepared.key_sha256, event(prepared, "HTTP_RESPONSE", 2), expected_journal_sha256=started.journal_sha256)
    connection.commit()
    assert repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256) == completed
    assert repo.put(prepared) == completed
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM zatca_dispatch_event_v1 WHERE storage_namespace=%s", (namespace,))
        assert cursor.fetchone() == (2,)


def test_candidate_drift_cannot_replace_original_issued_bytes(connections, namespace, prepared):
    connection = connections()
    original = save(connection, namespace, prepared)
    drift = replace(prepared, xml_bytes=prepared.xml_bytes.replace(b"><", b">\n<"))
    repo = MariaDBJournalRepository(connection, namespace)
    with pytest.raises(JournalStorageError, match="^repository_candidate_conflict$"):
        repo.put(drift)
    connection.rollback()
    assert MariaDBJournalRepository(connection, namespace).load(prepared.key_sha256) == original


def test_rollback_and_connection_loss_do_not_leave_partial_committed_journals(connections, namespace, prepared):
    connection = connections()
    MariaDBJournalRepository(connection, namespace).put(prepared)
    connection.close()  # Uncommitted creation is rolled back by InnoDB.
    reader = connections()
    with pytest.raises(JournalStorageError, match="^repository_missing$"):
        MariaDBJournalRepository(reader, namespace).load(prepared.key_sha256)
    reader.rollback()
    empty = save(reader, namespace, prepared)
    writer = connections()
    MariaDBJournalRepository(writer, namespace).append(prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256)
    writer.close()  # Inserted event + updated header both roll back.
    recovered = MariaDBJournalRepository(reader, namespace).load(prepared.key_sha256)
    assert recovered.events == () and recovered.journal_sha256 == empty.journal_sha256


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_contending_workers_cannot_append_two_starts(connections, namespace, prepared, isolation):
    setup = connections(isolation)
    empty = save(setup, namespace, prepared)
    worker1, worker2 = connections(isolation), connections(isolation)
    began, attempted = threading.Event(), threading.Event()

    def first():
        result = MariaDBJournalRepository(worker1, namespace).append(
            prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256,
        )
        began.set()
        assert attempted.wait(2)
        worker1.commit()
        return result

    def second():
        assert began.wait(2)
        attempted.set()
        changed = event(prepared, event_id=str(uuid4()), attempt_id=str(uuid4()))
        try:
            MariaDBJournalRepository(worker2, namespace).append(
                prepared.key_sha256, changed, expected_journal_sha256=empty.journal_sha256,
            )
        except JournalStorageError as error:
            worker2.rollback()
            return error.code
        pytest.fail("A competing stale start was appended")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future, second_future = pool.submit(first), pool.submit(second)
        winner = first_future.result(timeout=4)
        assert second_future.result(timeout=4) == "repository_stale_journal"
    recovered = MariaDBJournalRepository(setup, namespace).load(prepared.key_sha256)
    assert recovered == winner and len(recovered.events) == 1


def test_row_lock_timeout_is_static_requires_rollback_and_does_not_reset_identity(connections, namespace, prepared):
    holder, blocked = connections(), connections()
    original = save(holder, namespace, prepared)
    MariaDBJournalRepository(holder, namespace).load(prepared.key_sha256)
    repo = MariaDBJournalRepository(blocked, namespace)
    with pytest.raises(JournalStorageError, match="^repository_lock_timeout$"):
        repo.load(prepared.key_sha256)
    with pytest.raises(JournalStorageError, match="^repository_transaction_unusable$"):
        repo.put(prepared)
    blocked.rollback()
    holder.rollback()
    assert MariaDBJournalRepository(blocked, namespace).load(prepared.key_sha256) == original


@pytest.mark.parametrize("identity", ["uuid", "icv"])
def test_identity_unique_constraints_reject_new_key_with_reused_identity(connections, namespace, prepared, identity):
    connection = connections()
    save(connection, namespace, prepared)
    # A declared new version is not permission to reuse already stored identity.
    newer = replace(prepared, context=replace(prepared.context, scope=replace(prepared.context.scope, issuance_version=2)))
    root = etree.fromstring(newer.xml_bytes)
    if identity == "uuid":
        root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=NS)[0].text = "78"
    else:
        root.find("cbc:UUID", namespaces=NS).text = str(uuid4())
    newer = replace(newer, xml_bytes=etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    with pytest.raises(JournalStorageError, match="^repository_identity_collision$"):
        MariaDBJournalRepository(connection, namespace).put(newer)
    connection.rollback()
    recovered = MariaDBJournalRepository(connection, namespace).load(prepared.key_sha256)
    assert recovered.candidate == prepared
    connection.rollback()
    with pytest.raises(JournalStorageError, match="^repository_missing$"):
        MariaDBJournalRepository(connection, namespace).load(newer.key_sha256)


def test_namespace_isolation_does_not_create_cross_tenant_acceptance(connections, namespace, prepared):
    connection, other_namespace = connections(), str(uuid4())
    save(connection, namespace, prepared)
    other = save(connection, other_namespace, prepared)
    started = MariaDBJournalRepository(connection, other_namespace).append(
        prepared.key_sha256, event(prepared), expected_journal_sha256=other.journal_sha256,
    )
    connection.commit()
    assert len(started.events) == 1
    own = MariaDBJournalRepository(connection, namespace).load(prepared.key_sha256)
    assert own.events == ()


@pytest.mark.parametrize("target", ["xml", "header", "response", "event", "journal"])
def test_corruption_is_detected_on_reconstruction(connections, namespace, prepared, target):
    connection = connections()
    empty = save(connection, namespace, prepared)
    repo = MariaDBJournalRepository(connection, namespace)
    started = repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256)
    repo.append(prepared.key_sha256, event(prepared, "HTTP_RESPONSE", 2), expected_journal_sha256=started.journal_sha256)
    connection.commit()
    queries = {
        "xml": "UPDATE zatca_issuance_candidate_v1 SET xml_bytes=CONCAT(xml_bytes,' ') WHERE storage_namespace=%s",
        "header": "UPDATE zatca_issuance_candidate_v1 SET file_sha256=REPEAT('0',64) WHERE storage_namespace=%s",
        "response": "UPDATE zatca_dispatch_event_v1 SET response_bytes='PRIVATE OTHER BODY' WHERE storage_namespace=%s AND sequence=2",
        "event": "UPDATE zatca_dispatch_event_v1 SET event_id='e0000000-0000-4000-8000-000000000000' WHERE storage_namespace=%s AND sequence=2",
        "journal": "UPDATE zatca_issuance_candidate_v1 SET revision=1 WHERE storage_namespace=%s",
    }
    with connection.cursor() as cursor:
        cursor.execute(queries[target], (namespace,))
    connection.commit()  # Deliberate corruption in this private test database only.
    with pytest.raises(JournalStorageError) as error:
        MariaDBJournalRepository(connection, namespace).load(prepared.key_sha256)
    assert error.value.code in (
        "repository_candidate_fingerprint", "storage_response_fingerprint",
        "repository_event_fingerprint", "repository_journal_fingerprint",
    )
    assert "PRIVATE" not in str(error.value)


def test_autocommit_rejected_before_candidate_mutation(connections, namespace, prepared):
    connection = connections(autocommit=True)
    with pytest.raises(JournalStorageError, match="^repository_autocommit$"):
        MariaDBJournalRepository(connection, namespace).put(prepared)
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM zatca_issuance_candidate_v1 WHERE storage_namespace=%s", (namespace,))
        assert cursor.fetchone() == (0,)


@pytest.mark.parametrize("status", [400, 401, 409, 503])
def test_persisted_failure_or_duplicate_never_allows_second_attempt_or_changes_identity(connections, namespace, prepared, status):
    connection = connections()
    empty = save(connection, namespace, prepared)
    repo = MariaDBJournalRepository(connection, namespace)
    started = repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256)
    finished = repo.append(prepared.key_sha256, event(prepared, "HTTP_RESPONSE", 2, http_status=status), expected_journal_sha256=started.journal_sha256)
    connection.commit()
    with pytest.raises(JournalStorageError, match="^attempt_reconciliation_required$"):
        repo.append(
            prepared.key_sha256, event(prepared, sequence=3, event_id=str(uuid4()), attempt_id=str(uuid4())),
            expected_journal_sha256=finished.journal_sha256,
        )
    connection.rollback()
    recovered = MariaDBJournalRepository(connection, namespace).load(prepared.key_sha256)
    assert recovered == finished and recovered.candidate == prepared
    assert recovered.diagnostic_projection()["replay_authorized"] is False


@pytest.mark.parametrize("collision", ["event_id", "attempt_id"])
def test_cross_candidate_event_and_attempt_uniqueness_roll_back_partial_append(connections, namespace, prepared, collision):
    connection = connections()
    first = save(connection, namespace, prepared)
    other = replace(prepared, context=replace(prepared.context, scope=replace(prepared.context.scope, issuance_version=2)))
    root = etree.fromstring(other.xml_bytes)
    root.find("cbc:UUID", namespaces=NS).text = str(uuid4())
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=NS)[0].text = "78"
    other = replace(other, xml_bytes=etree.tostring(root, encoding="UTF-8", xml_declaration=True))
    second = save(connection, namespace, other)
    repo = MariaDBJournalRepository(connection, namespace)
    first_started = repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=first.journal_sha256)
    connection.commit()
    changes = {"attempt_id": str(uuid4())} if collision == "event_id" else {"event_id": str(uuid4())}
    with pytest.raises(JournalStorageError, match="^repository_unique_conflict$"):
        repo.append(other.key_sha256, event(other, **changes), expected_journal_sha256=second.journal_sha256)
    connection.rollback()
    repaired = MariaDBJournalRepository(connection, namespace)
    assert repaired.load(other.key_sha256) == second
    assert repaired.load(prepared.key_sha256) == first_started


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_concurrent_idempotent_candidate_creation_keeps_one_record(connections, namespace, prepared, isolation):
    one, two = connections(isolation), connections(isolation)
    barrier = threading.Barrier(2)

    def create(connection):
        barrier.wait(timeout=2)
        journal = MariaDBJournalRepository(connection, namespace).put(prepared)
        connection.commit()
        return journal

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future, second_future = pool.submit(create, one), pool.submit(create, two)
        assert first_future.result(timeout=4) == second_future.result(timeout=4)
    with one.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM zatca_issuance_candidate_v1 WHERE storage_namespace=%s", (namespace,))
        assert cursor.fetchone() == (1,)


def test_private_server_crash_recovery_preserves_commit_and_rolls_back_incomplete_append(connections, namespace, prepared, isolated_server):
    connection = connections()
    empty = save(connection, namespace, prepared)
    repo = MariaDBJournalRepository(connection, namespace)
    committed = repo.append(prepared.key_sha256, event(prepared), expected_journal_sha256=empty.journal_sha256)
    connection.commit()
    repo.append(prepared.key_sha256, event(prepared, "TRANSPORT_UNKNOWN", 2), expected_journal_sha256=committed.journal_sha256)
    # No commit; crash only the temporary database process while the transaction
    # contains both event/header changes. Live MariaDB/bench are out of scope.
    isolated_server[2]()
    recovered = MariaDBJournalRepository(connections(), namespace).load(prepared.key_sha256)
    assert recovered == committed
    assert recovered.candidate.xml_bytes == prepared.xml_bytes
    assert len(recovered.events) == 1
    assert recovered.diagnostic_projection()["replay_authorized"] is False


def store_receipt_predecessor(connections, receipt):
    connection = connections()
    try:
        repository = MariaDBJournalRepository(connection, receipt.storage_namespace)
        journal = repository.put(receipt.before.candidate)
        for observed in receipt.before.events:
            journal = repository.append(journal.candidate.key_sha256, observed,
                expected_journal_sha256=journal.journal_sha256)
        connection.commit()
        assert journal == receipt.before
    finally:
        connection.close()


def read_receipt_journal(connections, receipt):
    connection = connections()
    try:
        return MariaDBJournalRepository(connection, receipt.storage_namespace).load(receipt.before.candidate.key_sha256)
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize("doctype", ["Sales Invoice", "POS Invoice"])
@pytest.mark.parametrize("indicator", ["0100000", "0200000"])
@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("status", [200, 401, 409])
def test_primary_receipt_owned_sql_preserves_exact_response_and_local_redelivery(connections, namespace, certificates,
    doctype, indicator, unknown, status):
    selected = candidate(certificates[0], selected_scope=scope(doctype=doctype), indicator=indicator)
    receipt = retained(selected, namespace=namespace, unknown=unknown, status=status,
        body=b'  {"synthetic": "not authority acceptance"}\r\n')
    store_receipt_predecessor(connections, receipt)
    service = PrimaryReceiptPersistence(namespace, connection_factory=connections)
    first = service.persist(receipt)
    assert first.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and first.receipt is receipt
    stored = read_receipt_journal(connections, receipt)
    assert stored.events == (*receipt.before.events, receipt.response_event)
    assert stored.candidate == selected and stored.events[-1].response_bytes == receipt.response_event.response_bytes
    assert service.persist(receipt).state == first.state
    assert read_receipt_journal(connections, receipt) == stored
    assert all(value is False for key, value in first.diagnostic_projection().items()
        if key.endswith(("_verified", "_authorized")))


class ReceiptFaultConnection:
    """Own only the supplied private fixture connection; inject lost SQL ACKs."""

    def __init__(self, connection, fault):
        self.connection, self.fault, self.events = connection, fault, []

    def cursor(self):
        return self.connection.cursor()

    def commit(self):
        self.events.append("commit")
        if self.fault == "commit_before":
            raise RuntimeError("PRIVATE failed commit")
        self.connection.commit()
        if self.fault == "commit_after":
            raise RuntimeError("PRIVATE lost commit acknowledgement")

    def rollback(self):
        self.events.append("rollback")
        self.connection.rollback()

    def close(self):
        self.events.append("close")
        self.connection.close()
        if self.fault == "close":
            raise RuntimeError("PRIVATE lost close acknowledgement")


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("fault", ["commit_before", "commit_after", "close"])
def test_primary_receipt_uncertain_commit_keeps_exact_input_and_never_replays(connections, namespace, prepared, unknown, fault):
    receipt = retained(prepared, namespace=namespace, unknown=unknown)
    store_receipt_predecessor(connections, receipt)
    acquired = []
    def factory():
        wrapper = ReceiptFaultConnection(connections(), fault)
        acquired.append(wrapper)
        return wrapper
    uncertain = PrimaryReceiptPersistence(namespace, connection_factory=factory).persist(receipt)
    assert uncertain.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and uncertain.receipt is receipt
    expected_cleanup = ["commit", "close", "rollback"] if fault == "close" else ["commit", "rollback", "close"]
    assert len(acquired) == 1 and acquired[0].events == expected_cleanup
    assert not acquired[0].connection.open
    stored = read_receipt_journal(connections, receipt)
    assert stored.events == (receipt.before.events if fault == "commit_before" else (*receipt.before.events, receipt.response_event))
    completed = PrimaryReceiptPersistence(namespace, connection_factory=connections).persist(uncertain.receipt)
    assert completed.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and completed.receipt is receipt
    assert read_receipt_journal(connections, receipt).events == (*receipt.before.events, receipt.response_event)


@pytest.mark.parametrize("absent", ["candidate", "start"])
def test_primary_receipt_never_creates_candidate_or_start_to_repair_missing_history(connections, namespace, prepared, absent):
    receipt = retained(prepared, namespace=namespace)
    if absent == "start":
        connection = connections()
        save(connection, namespace, prepared)
        connection.close()
    result = PrimaryReceiptPersistence(namespace, connection_factory=connections).persist(receipt)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and result.receipt is receipt
    connection = connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM zatca_issuance_candidate_v1 WHERE storage_namespace=%s", (namespace,))
            assert cursor.fetchone() == (int(absent == "start"),)
            cursor.execute("SELECT COUNT(*) FROM zatca_dispatch_event_v1 WHERE storage_namespace=%s", (namespace,))
            assert cursor.fetchone() == (0,)
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize("changed", ["unknown_revision", "other_response"])
def test_primary_receipt_rejects_newer_or_conflicting_history_without_overwrite(connections, namespace, prepared, changed):
    receipt = retained(prepared, namespace=namespace)
    store_receipt_predecessor(connections, receipt)
    connection = connections()
    repository = MariaDBJournalRepository(connection, namespace)
    other = event(prepared, "TRANSPORT_UNKNOWN", 2) if changed == "unknown_revision" else replace(
        receipt.response_event, response_bytes=b"OTHER synthetic observation")
    expected = repository.append(prepared.key_sha256, other, expected_journal_sha256=receipt.before.journal_sha256)
    connection.commit()
    connection.close()
    result = PrimaryReceiptPersistence(namespace, connection_factory=connections).persist(receipt)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY"
    assert read_receipt_journal(connections, receipt) == expected


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_primary_receipt_concurrent_identical_redelivery_keeps_one_response(connections, namespace, prepared, isolation):
    receipt = retained(prepared, namespace=namespace)
    store_receipt_predecessor(connections, receipt)
    barrier = threading.Barrier(2)
    def persist():
        barrier.wait(timeout=3)
        return PrimaryReceiptPersistence(namespace, connection_factory=lambda: connections(isolation)).persist(receipt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda index: persist(), range(2)))
    assert all(result.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY" and result.receipt is receipt for result in results)
    assert read_receipt_journal(connections, receipt).events == (*receipt.before.events, receipt.response_event)


def test_primary_receipt_rejects_autocommit_without_changing_session(connections, namespace, prepared):
    receipt = retained(prepared, namespace=namespace)
    store_receipt_predecessor(connections, receipt)
    acquired = []
    def factory():
        connection = connections(autocommit=True)
        acquired.append(connection)
        return connection
    result = PrimaryReceiptPersistence(namespace, connection_factory=factory).persist(receipt)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and len(acquired) == 1 and not acquired[0].open
    assert read_receipt_journal(connections, receipt) == receipt.before


@pytest.mark.parametrize("stage", [1, 2])
def test_primary_receipt_saved_source_guard_rejection_rolls_back_append(connections, namespace, prepared, stage):
    receipt = retained(prepared, namespace=namespace)
    store_receipt_predecessor(connections, receipt)
    seen = []
    def guard(connection, supplied):
        assert supplied is receipt
        seen.append(connection)
        return len(seen) != stage
    result = PrimaryReceiptPersistence(namespace, connection_factory=connections, source_guard=guard).persist(receipt)
    assert result.state == "RECEIPT_COMMIT_UNCONFIRMED_NO_REPLAY" and len(seen) == stage
    assert all(item is seen[0] for item in seen) and not seen[0].open
    assert read_receipt_journal(connections, receipt) == receipt.before


@pytest.mark.parametrize("commit_parent", [False, True])
def test_primary_receipt_owned_commit_does_not_touch_other_parent_transaction(connections, namespace, prepared, commit_parent):
    receipt = retained(prepared, namespace=namespace)
    store_receipt_predecessor(connections, receipt)
    parent_namespace = str(uuid4())
    parent = connections()
    save(parent, parent_namespace, prepared)
    # Deliberately synthetic pending header change, not an event/revision model.
    # Avoid unrelated empty-child-range locks obscuring transaction ownership.
    with parent.cursor() as cursor:
        cursor.execute("UPDATE zatca_issuance_candidate_v1 SET revision=1 WHERE storage_namespace=%s AND key_sha256=%s",
            (parent_namespace, prepared.key_sha256))
    try:
        result = PrimaryReceiptPersistence(namespace, connection_factory=connections).persist(receipt)
        assert result.state == "RECEIPT_STORED_OBSERVATION_NO_REPLAY"
        reader = connections("READ COMMITTED")
        try:
            with reader.cursor() as cursor:
                cursor.execute("SELECT revision FROM zatca_issuance_candidate_v1 WHERE storage_namespace=%s", (parent_namespace,))
                assert cursor.fetchone() == (0,)
            (parent.commit if commit_parent else parent.rollback)()
            with reader.cursor() as cursor:
                cursor.execute("SELECT revision FROM zatca_issuance_candidate_v1 WHERE storage_namespace=%s", (parent_namespace,))
                assert cursor.fetchone() == (1 if commit_parent else 0,)
        finally:
            reader.rollback()
            reader.close()
    finally:
        parent.close()
