"""Owned private MariaDB encrypted observation archive, never a tenant."""

import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pymysql
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf.compliance_archive import ComplianceArchiveCipher, ComplianceArchiveError, encode_observation
from zatca_erpgulf.zatca_erpgulf.compliance_archive_repository import MariaDBComplianceArchiveRepository
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import ComplianceRequirements, ComplianceCheckSet
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle_mariadb import install_private_bundle_schema, context, stage
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import csr, exchange, response
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import basic


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
                               reason="Only the owned private MariaDB fixture may install the archive schema")


@pytest.fixture(scope="module", autouse=True)
def install_private_archive_schema(isolated_server, install_private_bundle_schema):
    # ONLY the socket returned by our owned subprocess; never a site/config/env
    # host override, running MariaDB instance, Frappe installer or tenant schema.
    with pymysql.connect(unix_socket=isolated_server[0], user="root", database="zatca_journal_rehearsal", autocommit=True) as database:
        schema = Path(__file__).resolve().parents[3] / "docs/zatca_unification/compliance_archive_rehearsal.sql"
        source = "\n".join(line for line in schema.read_text().splitlines() if not line.lstrip().startswith("--"))
        with database.cursor() as cursor:
            for statement in source.split(";"):
                if statement.strip():
                    cursor.execute(statement)


@pytest.fixture
def audit(connections, context, materials):
    namespace, bundle_cipher, seal, _ = context
    bundle = stage(connections(), namespace, bundle_cipher, seal())
    requirements = ComplianceRequirements(namespace, bundle.manifest, csr(materials[0]))
    receipt = exchange(requirements, materials[0])
    start = replace(receipt, http_status=None, response_bytes=None, received_at=None)
    key = secrets.token_bytes(32)
    archive_cipher = ComplianceArchiveCipher({"audit-test": key})
    left = archive_cipher.seal(start, sequence=1, key_id="audit-test")
    right = archive_cipher.seal(receipt, sequence=2, key_id="audit-test")

    def repo(database):
        return MariaDBComplianceArchiveRepository(database, namespace, bundle_cipher, archive_cipher)

    return namespace, bundle_cipher, archive_cipher, bundle, start, receipt, left, right, repo, key


def prepare(database, repository, sealed):
    result = repository(database).prepare(sealed)
    database.commit()  # Explicit TEST caller; not repository/Frappe/HTTP.
    return result


def receive(database, repository, sealed):
    result = repository(database).append_receipt(sealed)
    database.commit()
    return result


def read(database, repository, bundle, exchange_id):
    history = repository(database).load(bundle.manifest.slot, bundle.manifest.version_id, exchange_id)
    database.rollback()  # TEST caller releases read locks explicitly.
    return history


def test_committed_exact_requests_and_receipts_are_ciphertext_only(connections, audit, materials):
    namespace, _, protected, bundle, start, receipt, left, right, repo, _ = audit
    database = connections()
    prepare(database, repo, left)
    receive(database, repo, right)
    history = read(connections(), repo, bundle, start.exchange_id)
    assert history.start == start and history.receipt == receipt
    assert history.diagnostic_projection()["remote_receipt_verified"] is False
    with database.cursor() as cursor:
        cursor.execute("SELECT ciphertext FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s ORDER BY sequence", (namespace,))
        rows = cursor.fetchall()
    assert rows == ((left.ciphertext,), (right.ciphertext,))
    for row in rows:
        for private in (start.request_bytes, receipt.response_bytes, start.requirements.csr_der,
                        materials[0].pem.encode(), materials[0].text.encode(), basic(materials[0]).encode()):
            assert private not in row[0]


@pytest.mark.parametrize("status", [200, 401, 500])
def test_real_empty_http_body_survives_committed_recovery(connections, audit, status):
    _, _, protected, bundle, start, receipt, left, _, repo, _ = audit
    receipt = replace(receipt, http_status=status, response_bytes=b"")
    sealed = protected.seal(receipt, sequence=2, key_id="audit-test")
    prepare(connections(), repo, left)
    receive(connections(), repo, sealed)
    history = read(connections(), repo, bundle, start.exchange_id)
    assert history.start.response_bytes is None and history.receipt.response_bytes == b""
    assert history.receipt.outcome != "PASS_MATCHED_OBSERVATION"


@pytest.mark.parametrize("explicit_rollback", [True, False])
def test_uncommitted_capture_never_survives_rollback_or_connection_loss(connections, audit, explicit_rollback):
    _, _, _, bundle, start, _, left, _, repo, _ = audit
    database = connections()
    repo(database).prepare(left)
    if explicit_rollback:
        database.rollback()
    else:
        database.close()
    with pytest.raises(ComplianceArchiveError, match="archive_missing"):
        repo(connections()).load(bundle.manifest.slot, bundle.manifest.version_id, start.exchange_id)


@pytest.mark.parametrize("phase", ["request", "receipt"])
def test_exact_redelivery_is_idempotent_but_resealing_cannot_replace(connections, audit, phase):
    namespace, _, protected, bundle, start, receipt, left, right, repo, _ = audit
    database = connections()
    assert prepare(database, repo, left) == prepare(database, repo, left)
    if phase == "receipt":
        assert receive(database, repo, right) == receive(database, repo, right)
    new = protected.seal(start if phase == "request" else receipt, sequence=1 if phase == "request" else 2, key_id="audit-test")
    with pytest.raises(ComplianceArchiveError, match="archive_record_conflict"):
        (repo(database).prepare if phase == "request" else repo(database).append_receipt)(new)
    database.rollback()
    history = read(connections(), repo, bundle, start.exchange_id)
    assert history.start == start and history.receipt == (receipt if phase == "receipt" else None)


@pytest.mark.parametrize("change", ["no_start", "different_request", "different_version"])
def test_receipt_cannot_attach_without_exact_start_and_version(connections, audit, context, change):
    namespace, bundle_cipher, protected, bundle, start, receipt, left, right, repo, _ = audit
    database = connections()
    if change != "no_start":
        prepare(database, repo, left)
    if change == "different_request":
        receipt = replace(receipt, request_bytes=receipt.request_bytes + b" ")
    elif change == "different_version":
        _, _, seal, _ = context
        other_bundle = stage(connections(), namespace, bundle_cipher, seal())
        receipt = replace(receipt, requirements=replace(receipt.requirements, manifest=other_bundle.manifest))
    if change != "no_start":
        right = protected.seal(receipt, sequence=2, key_id="audit-test")
    with pytest.raises(ComplianceArchiveError):
        repo(database).append_receipt(right)
    database.rollback()
    with database.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s AND sequence=2", (namespace,))
        assert cursor.fetchone() == (0,)


@pytest.mark.parametrize("change", ["namespace", "version", "slot", "attempt"])
def test_explicit_load_never_falls_back_across_scope(connections, audit, change):
    namespace, bundle_cipher, protected, bundle, start, _, left, _, repo, _ = audit
    prepare(connections(), repo, left)
    slot, version, identity = bundle.manifest.slot, bundle.manifest.version_id, start.exchange_id
    if change == "namespace":
        repository = MariaDBComplianceArchiveRepository(connections(), str(uuid4()), bundle_cipher, protected)
    else:
        repository = repo(connections())
    if change == "version":
        version = str(uuid4())
    elif change == "slot":
        slot = replace(slot, environment="Simulation")
    elif change == "attempt":
        identity = str(uuid4())
    with pytest.raises(ComplianceArchiveError):
        repository.load(slot, version, identity)


@pytest.mark.parametrize("field", ["ciphertext", "observation_sha256", "key_id"])
def test_corrupt_storage_metadata_or_ciphertext_is_detected(connections, audit, field):
    namespace, _, _, bundle, start, _, left, _, repo, _ = audit
    prepare(connections(), repo, left)
    database = connections()
    with database.cursor() as cursor:
        if field == "ciphertext":
            value = left.ciphertext[:-1] + bytes([left.ciphertext[-1] ^ 1])
        elif field == "observation_sha256":
            value = "0" * 64
        else:
            value = "missing-key"
        cursor.execute("UPDATE zatca_compliance_archive_v1 SET " + field + "=%s WHERE storage_namespace=%s AND exchange_id=%s",
                       (value, namespace, start.exchange_id))
    database.commit()  # Deliberate TEST corruption, not a repair/runtime API.
    with pytest.raises(ComplianceArchiveError):
        repo(connections()).load(bundle.manifest.slot, bundle.manifest.version_id, start.exchange_id)


def test_archive_nonce_collision_cannot_append_or_overwrite(connections, audit):
    namespace, _, _, bundle, start, receipt, left, right, repo, key = audit
    prepare(connections(), repo, left)
    # Deliberately unsafe synthetic nonce reuse, exclusively to test the SQL
    # guard. Never use this fixture technique for production encryption.
    reused = replace(right, nonce=left.nonce)
    reused = replace(reused, ciphertext=AESGCM(key).encrypt(reused.nonce, encode_observation(receipt), reused.aad()))
    database = connections()
    with pytest.raises(ComplianceArchiveError):
        repo(database).append_receipt(reused)
    database.rollback()
    assert read(connections(), repo, bundle, start.exchange_id).receipt is None


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
@pytest.mark.parametrize("conflicting", [False, True])
def test_two_receipt_workers_have_one_immutable_result(connections, audit, isolation, conflicting):
    namespace, _, protected, bundle, start, receipt, left, right, repo, _ = audit
    prepare(connections(), repo, left)
    different = protected.seal(replace(receipt, response_bytes=json.dumps(response("WARNING")).encode()),
                               sequence=2, key_id="audit-test") if conflicting else right
    a, b = connections(isolation), connections(isolation)

    def worker(database, sealed):
        try:
            result = repo(database).append_receipt(sealed)
            database.commit()
            return result
        except ComplianceArchiveError as error:
            database.rollback()
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, a, right), executor.submit(worker, b, different)]
        results = [future.result(timeout=5) for future in futures]
    winners = [result for result in results if not isinstance(result, str)]
    assert len(winners) == (1 if conflicting else 2)
    if conflicting:
        assert "archive_record_conflict" in results
    history = read(connections(), repo, bundle, start.exchange_id)
    assert history.receipt.observation_sha256 == winners[0].observation_sha256
    with a.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM zatca_compliance_archive_v1 WHERE storage_namespace=%s AND exchange_id=%s",
                       (namespace, start.exchange_id))
        assert cursor.fetchone() == (2,)


@pytest.mark.parametrize("committed_receipt", [True, False])
def test_owned_server_crash_keeps_committed_request_and_only_committed_receipt(connections, audit, isolated_server, committed_receipt):
    _, _, _, bundle, start, receipt, left, right, repo, _ = audit
    prepare(connections(), repo, left)
    database = connections()
    repo(database).append_receipt(right)
    if committed_receipt:
        database.commit()
    isolated_server[2]()  # Kill/restart ONLY the exact fixture-owned process.
    history = read(connections(), repo, bundle, start.exchange_id)
    assert history.start == start and history.receipt == (receipt if committed_receipt else None)


def test_lock_timeout_poison_needs_whole_transaction_rollback(connections, audit):
    _, _, _, bundle, start, _, left, right, repo, _ = audit
    prepare(connections(), repo, left)
    holder = connections()
    repo(holder).load(bundle.manifest.slot, bundle.manifest.version_id, start.exchange_id)
    waiting = connections()
    repository = repo(waiting)
    with pytest.raises(ComplianceArchiveError):
        repository.append_receipt(right)
    with pytest.raises(ComplianceArchiveError, match="archive_transaction_unusable"):
        repository.prepare(left)
    waiting.rollback()
    holder.rollback()
    assert read(connections(), repo, bundle, start.exchange_id).receipt is None


def test_complete_set_rehydrates_six_receipts_but_keeps_authority_false(connections, audit, materials):
    _, _, protected, bundle, first, _, _, _, repo, _ = audit
    recovered = []
    writer, reader = connections(), connections()
    for step in first.requirements.required_steps:
        receipt = exchange(first.requirements, materials[0], step=step)
        start = replace(receipt, http_status=None, response_bytes=None, received_at=None)
        left = protected.seal(start, sequence=1, key_id="audit-test")
        right = protected.seal(receipt, sequence=2, key_id="audit-test")
        prepare(writer, repo, left)
        receive(writer, repo, right)
        recovered.append(read(reader, repo, bundle, start.exchange_id).current_observation)
    report = ComplianceCheckSet(first.requirements, tuple(recovered)).diagnostic_projection()
    assert report["state"] == "COMPLETE_MATCHED_OBSERVATIONS"
    assert report["compliance_completion_verified"] is report["activation_authorized"] is False
