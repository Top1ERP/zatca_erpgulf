"""Opt-in real InnoDB rehearsal in a NEW private server, never a site database.

Run with ZATCA_RUN_ISOLATED_MARIADB=1. No socket/host/site credentials are read
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


pytestmark = pytest.mark.skipif(
    os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Opt-in private MariaDB subprocess rehearsal, not a configured site connection",
)


@pytest.fixture(scope="module")
def isolated_server(tmp_path_factory):
    server_binary, install_binary = shutil.which("mariadbd"), shutil.which("mariadb-install-db")
    if not server_binary or not install_binary:
        pytest.fail("Private MariaDB rehearsal requires local server/install binaries")
    root = tmp_path_factory.mktemp("zjr")
    root.chmod(0o700)
    data, socket = root / "data", root / "server.sock"
    if len(str(socket).encode()) >= 100:
        pytest.fail("Private rehearsal socket path exceeds the conservative bound")
    with (root / "install.log").open("wb") as install_log:
        subprocess.run([
            install_binary, "--no-defaults", f"--datadir={data}",
            "--auth-root-authentication-method=normal", "--skip-test-db",
        ], check=True, stdout=install_log, stderr=subprocess.STDOUT, timeout=30)
    with (root / "server.log").open("wb") as server_log:
        arguments = [
            server_binary, "--no-defaults", f"--datadir={data}", f"--socket={socket}",
            f"--pid-file={root / 'server.pid'}", "--skip-networking", "--skip-log-bin",
            "--innodb-buffer-pool-size=32M", "--innodb-log-file-size=8M",
            "--innodb-flush-log-at-trx-commit=1", "--innodb-use-native-aio=0",
            "--max-connections=16", "--max-allowed-packet=32M", "--performance-schema=OFF",
        ]
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
