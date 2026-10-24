"""Owned private InnoDB pending CSR tests, never a site schema or service."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import pending_csr as pending
from zatca_erpgulf.zatca_erpgulf.pending_csr_repository import MariaDBPendingCSRRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import sample, crypto, materials
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf import pending_csr_access as access
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_access import access_case, invoke, Denied, Failed


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
    reason="Only the fixed guarded runner's owned private SQL fixture is allowed")


@pytest.fixture(scope="module", autouse=True)
def install_private_pending_schema(isolated_server):
    # The socket/datadir/process are created/registered by the guarded fixture;
    # no tenant/socket/host/config override or runtime schema installer exists.
    with pymysql.connect(unix_socket=isolated_server[0], user="root",
                         database="zatca_journal_rehearsal", autocommit=True) as connection:
        schema = Path(__file__).resolve().parents[3] / "docs/zatca_unification/pending_csr_rehearsal.sql"
        text = "\n".join(line for line in schema.read_text().splitlines() if not line.lstrip().startswith("--"))
        with connection.cursor() as cursor:
            for statement in text.split(";"):
                if statement.strip():
                    cursor.execute(statement)
            cursor.execute("CREATE TABLE pending_csr_parent_work (namespace CHAR(36) PRIMARY KEY,payload LONGTEXT) ENGINE=InnoDB")


@pytest.fixture
def custody(sample):
    namespace = str(uuid4())
    key = secrets.token_bytes(32)
    cipher = pending.PendingCSRCipher({"test-only-key": key})
    envelope = cipher.seal(sample, storage_namespace=namespace, key_id="test-only-key")
    return SimpleNamespace(namespace=namespace, key=key, cipher=cipher, envelope=envelope, draft=sample)


def repository(connection, case):
    return MariaDBPendingCSRRepository(connection, case.namespace, case.cipher)


def committed(connections, case):
    writer = connections()
    result = repository(writer, case).stage(case.envelope)
    writer.commit()  # Explicit TEST transaction owner, not a runtime helper.
    return result


def count(connection, table, namespace):
    assert table in ("zatca_pending_csr_v1", "pending_csr_parent_work")
    column = "storage_namespace" if table == "zatca_pending_csr_v1" else "namespace"
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM " + table + " WHERE " + column + "=%s", (namespace,))
        return cursor.fetchone()[0]


def test_committed_envelope_roundtrip_stores_no_raw_key_config_or_csr(connections, custody):
    case = custody
    committed(connections, case)
    reader = connections()
    result = repository(reader, case).load(case.draft.context)
    assert result == case.envelope and case.cipher.open(result) == case.draft
    with reader.cursor() as cursor:
        cursor.execute("SELECT manifest_bytes,ciphertext FROM zatca_pending_csr_v1 WHERE storage_namespace=%s", (case.namespace,))
        metadata, ciphertext = cursor.fetchone()
    for value in (case.draft.private_key_pem, case.draft.csr_pem, case.draft.config_text.encode()):
        assert value not in metadata and value not in ciphertext
    assert result.manifest.diagnostic_projection()["storage_confirmed"] is False
    reader.rollback()


@pytest.mark.parametrize("commit", [False, True])
def test_parent_work_and_pending_stage_remain_owned_by_one_caller_transaction(connections, custody, commit):
    case = custody
    writer, observer = connections(), connections()
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO pending_csr_parent_work VALUES (%s,%s)", (case.namespace, "TEST PARENT"))
    repository(writer, case).stage(case.envelope)
    for table in ("zatca_pending_csr_v1", "pending_csr_parent_work"):
        assert count(observer, table, case.namespace) == 0
    writer.commit() if commit else writer.rollback()
    observer.rollback()
    for table in ("zatca_pending_csr_v1", "pending_csr_parent_work"):
        assert count(observer, table, case.namespace) == int(commit)


def test_exact_redelivery_is_accepted_but_resealing_cannot_replace_a_draft(connections, custody):
    case = custody
    committed(connections, case)
    writer = connections()
    assert repository(writer, case).stage(case.envelope) == case.envelope
    writer.commit()
    changed = case.cipher.seal(case.draft, storage_namespace=case.namespace, key_id="test-only-key")
    handle = repository(writer, case)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_draft_conflict$"):
        handle.stage(changed)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_transaction_unusable$"):
        handle.load(case.draft.context)
    writer.rollback()
    assert repository(connections(), case).load(case.draft.context) == case.envelope


@pytest.mark.parametrize("field", ["revision", "flow", "time", "environment", "owner"])
def test_exact_historical_context_is_required_without_latest_or_owner_fallback(connections, custody, field):
    case = custody
    committed(connections, case)
    original = case.draft.context
    if field == "revision":
        changed = replace(original, source_revision="2026-10-24 11:00:01")
    elif field == "flow":
        changed = replace(original, flow_id=str(uuid4()))
    elif field == "time":
        changed = replace(original, prepared_at=original.prepared_at + timedelta(seconds=1))
    elif field == "environment":
        changed = replace(original, slot=replace(original.slot, environment="Simulation"))
    else:
        changed = replace(original, company_name="OTHER TEST", slot=replace(original.slot, owner_name="OTHER TEST"))
    reader = connections()
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_context$"):
        repository(reader, case).load(changed)
    reader.rollback()


def test_another_declared_namespace_cannot_load_the_envelope(connections, custody):
    case = custody
    committed(connections, case)
    reader = connections()
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_missing$"):
        MariaDBPendingCSRRepository(reader, str(uuid4()), case.cipher).load(case.draft.context)
    reader.rollback()


@pytest.mark.parametrize("field", ["slot_sha256", "flow_id", "manifest_bytes", "manifest_sha256", "key_id", "nonce", "ciphertext"])
def test_modified_storage_is_rejected_not_reconstructed_or_repaired(connections, custody, field):
    case = custody
    committed(connections, case)
    values = {"slot_sha256": "0" * 64, "flow_id": str(uuid4()), "manifest_bytes": b"PRIVATE",
              "manifest_sha256": "0" * 64, "key_id": "missing-key", "nonce": b"x" * 12,
              "ciphertext": case.envelope.ciphertext[:-1] + bytes([case.envelope.ciphertext[-1] ^ 1])}
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("UPDATE zatca_pending_csr_v1 SET " + field + "=%s WHERE storage_namespace=%s",
                       (values[field], case.namespace))
    writer.commit()
    reader = connections()
    with pytest.raises(pending.PendingCSRStorageError) as raised:
        repository(reader, case).load(case.draft.context)
    assert "PRIVATE" not in str(raised.value) and raised.value.__context__ is None
    reader.rollback()


def test_autocommit_is_refused_before_insert(connections, custody):
    case = custody
    writer = connections(autocommit=True)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_autocommit$"):
        repository(writer, case).stage(case.envelope)
    assert count(connections(), "zatca_pending_csr_v1", case.namespace) == 0


def test_connection_loss_does_not_commit_pending_stage_or_parent_work(connections, custody):
    case = custody
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO pending_csr_parent_work VALUES (%s,%s)", (case.namespace, "TEST PARENT"))
    handle = repository(writer, case)
    handle.stage(case.envelope)
    writer.close()  # Only this fixture-owned handle; server rolls back its work.
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_database_error$"):
        handle.load(case.draft.context)
    reader = connections()
    for table in ("zatca_pending_csr_v1", "pending_csr_parent_work"):
        assert count(reader, table, case.namespace) == 0


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
@pytest.mark.parametrize("conflict", [False, True])
def test_competing_exact_or_changed_envelopes_are_serialized_without_retry(connections, custody, isolation, conflict):
    case = custody
    second = case.cipher.seal(case.draft, storage_namespace=case.namespace, key_id="test-only-key") if conflict else case.envelope
    def stage(envelope):
        connection = connections(isolation)
        try:
            repository(connection, case).stage(envelope)
            connection.commit()
            return "stored"
        except pending.PendingCSRStorageError as error:
            connection.rollback()
            return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(stage, (case.envelope, second)))
    assert sorted(results) == (["pending_csr_draft_conflict", "stored"] if conflict else ["stored", "stored"])
    reader = connections()
    assert count(reader, "zatca_pending_csr_v1", case.namespace) == 1
    assert repository(reader, case).load(case.draft.context) in (case.envelope, second)
    reader.rollback()


def test_lock_timeout_poisoning_leaves_previous_ciphertext_unchanged(connections, custody):
    case = custody
    committed(connections, case)
    locker, blocked = connections(), connections()
    with locker.cursor() as cursor:
        cursor.execute("SELECT draft_id FROM zatca_pending_csr_v1 WHERE storage_namespace=%s FOR UPDATE", (case.namespace,))
    handle = repository(blocked, case)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_lock_timeout$"):
        handle.stage(case.envelope)
    blocked.rollback()
    locker.rollback()
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_transaction_unusable$"):
        handle.load(case.draft.context)
    reader = connections()
    assert repository(reader, case).load(case.draft.context) == case.envelope
    reader.rollback()


@pytest.mark.parametrize("commit", [False, True])
def test_owned_server_crash_recovers_only_committed_pending_material(connections, isolated_server, custody, commit):
    case = custody
    writer = connections()
    repository(writer, case).stage(case.envelope)
    if commit:
        writer.commit()
    isolated_server[2]()  # Crash/restart ONLY the exact owned private subprocess.
    reader = connections()
    if commit:
        assert repository(reader, case).load(case.draft.context) == case.envelope
    else:
        with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_missing$"):
            repository(reader, case).load(case.draft.context)
    reader.rollback()


def test_synthetic_bad_nonce_provider_cannot_overwrite_a_different_draft(connections, custody, monkeypatch):
    case = custody
    committed(connections, case)
    changed_draft = replace(case.draft, context=replace(case.draft.context, draft_id=str(uuid4())))
    # Deliberately INVALID nonce reuse under TEST-ONLY keys. SQL rejection is
    # not a safe nonce allocator or permission to do this in a real deployment.
    monkeypatch.setattr(pending.secrets, "token_bytes", lambda count: case.envelope.nonce)
    changed = case.cipher.seal(changed_draft, storage_namespace=case.namespace, key_id="test-only-key")
    writer = connections()
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_identity_collision$"):
        repository(writer, case).stage(changed)
    writer.rollback()
    reader = connections()
    assert count(reader, "zatca_pending_csr_v1", case.namespace) == 1
    assert repository(reader, case).load(case.draft.context) == case.envelope
    reader.rollback()


@pytest.fixture(scope="module")
def private_access_schema(isolated_server, install_private_pending_schema):
    # App-like table names exist ONLY in this fixture-owned temporary database.
    # No tenant/schema override or runtime installer is accepted by the runner.
    with pymysql.connect(unix_socket=isolated_server[0], user="root",
                         database="zatca_journal_rehearsal", autocommit=True) as connection:
        with connection.cursor() as cursor:
            for kind, fields in access.FIELD_MAP.items():
                columns = ["`name` VARCHAR(140) PRIMARY KEY", "`modified` DATETIME(6) NOT NULL"] + [
                    "`" + name + "` " + ("INT" if name == access.LINK_FLAG else "LONGTEXT") for name in fields]
                cursor.execute("CREATE TABLE `tab" + kind + "` (" + ",".join(columns) + ") ENGINE=InnoDB")


def private_access_case(access_case, connections, kind):
    case = access_case(kind)
    case.scope = access.CredentialStorageScope("private.test", str(uuid4()))
    case.sealed = case.cipher.seal(case.draft, storage_namespace=case.scope.storage_namespace, key_id="test-only-key")
    case.binding = replace(case.binding, scope=case.scope, manifest=case.sealed.manifest)
    admin = connections()
    with admin.cursor() as cursor:
        for doc in case.documents.values():
            fields = ("name", "modified", *access.FIELD_MAP[doc.doctype])
            cursor.execute("INSERT INTO `tab" + doc.doctype + "` (" + ",".join("`" + name + "`" for name in fields)
                + ") VALUES (" + ",".join("%s" for name in fields) + ") ON DUPLICATE KEY UPDATE "
                + ",".join("`" + name + "`=VALUES(`" + name + "`)" for name in fields if name != "name"),
                tuple(doc.get(name) for name in fields))
    admin.commit()  # TEST owner only; app service never installs or commits.
    case.writer = connections()
    case.resources = replace(case.resources, scope=case.scope, connection=case.writer)
    case.service = access.SavedPendingCSRService(case.scope, case.lookup, case.provider)
    return case


def pending_count(connection, case):
    return count(connection, "zatca_pending_csr_v1", case.scope.storage_namespace)


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("commit", [False, True])
def test_permissioned_stage_and_parent_work_commit_or_rollback_only_together(private_access_schema, access_case, connections, kind, commit):
    case = private_access_case(access_case, connections, kind)
    with case.writer.cursor() as cursor:
        cursor.execute("INSERT INTO pending_csr_parent_work VALUES (%s,%s)", (case.scope.storage_namespace, "TEST PARENT"))
    report = invoke(case, "stage")
    assert report["state"] == "PENDING_CSR_STAGED_UNCOMMITTED" and report["storage_confirmed"] is False
    observer = connections()
    assert pending_count(observer, case) == 0
    assert count(observer, "pending_csr_parent_work", case.scope.storage_namespace) == 0
    case.writer.commit() if commit else case.writer.rollback()
    observer.rollback()
    assert pending_count(observer, case) == int(commit)
    assert count(observer, "pending_csr_parent_work", case.scope.storage_namespace) == int(commit)
    for doc in case.documents.values():
        doc.save.assert_not_called()


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("field", ["modified", "custom_csr_config", "custom_certificate"])
def test_locked_native_source_drift_is_rejected_before_pending_insert_without_parent_cleanup(private_access_schema, access_case, connections, kind, field):
    case = private_access_case(access_case, connections, kind)
    mutator = connections()
    value = "2026-10-24 11:00:01" if field == "modified" else "CHANGED TEST"
    with mutator.cursor() as cursor:
        cursor.execute("UPDATE `tab" + case.target.doctype + "` SET `" + field + "`=%s WHERE name=%s", (value, case.target.name))
    mutator.commit()
    with case.writer.cursor() as cursor:
        cursor.execute("INSERT INTO pending_csr_parent_work VALUES (%s,%s)", (case.scope.storage_namespace, "TEST PARENT"))
    with pytest.raises(Failed) as error:
        invoke(case, "stage")
    assert error.value.__context__ is None and case.writer.open
    assert count(case.writer, "pending_csr_parent_work", case.scope.storage_namespace) == 1
    observer = connections()
    assert pending_count(observer, case) == 0
    assert count(observer, "pending_csr_parent_work", case.scope.storage_namespace) == 0
    case.writer.rollback()  # Explicit TEST owner, including its earlier parent work.
    observer.rollback()
    assert count(observer, "pending_csr_parent_work", case.scope.storage_namespace) == 0


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("fault", ["permission", "revision"])
def test_native_post_insert_revocation_refuses_result_but_leaves_whole_pending_transaction_to_caller(private_access_schema, access_case, connections, monkeypatch, kind, fault):
    case = private_access_case(access_case, connections, kind)
    original, calls = access._verify_locked_rows, []
    def guarded(connection, rows):
        original(connection, rows)
        calls.append(True)
        if len(calls) == 2:
            if fault == "permission":
                case.denied.add((case.target.doctype, case.target.name, "write"))
            else:
                case.target.modified = "2026-10-24 11:00:01"
    monkeypatch.setattr(access, "_verify_locked_rows", guarded)
    with pytest.raises(Denied if fault == "permission" else Failed) as error:
        invoke(case, "stage")
    assert error.value.__context__ is None
    assert pending_count(case.writer, case) == 1  # No automatic rollback/commit.
    observer = connections()
    assert pending_count(observer, case) == 0
    case.writer.rollback()
    observer.rollback()
    assert pending_count(observer, case) == 0


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_permissioned_native_inspection_returns_metadata_not_material(private_access_schema, access_case, connections, kind):
    case = private_access_case(access_case, connections, kind)
    invoke(case, "stage")
    case.writer.commit()  # TEST owner only.
    case.service = access.SavedPendingCSRService(case.scope, case.lookup, case.provider)
    report = invoke(case, "inspect")
    assert report["state"] == "PENDING_CSR_INSPECTION_OBSERVATION"
    assert report["storage_confirmed"] is False and report["credential_epoch_verified"] is False
    assert "sealed" not in report and "private_key_pem" not in report and "config_text" not in report
    case.writer.rollback()


def test_source_row_lock_blocks_competing_changes_until_test_owner_releases_transaction(private_access_schema, access_case, connections):
    case = private_access_case(access_case, connections, "company")
    invoke(case, "stage")
    other = connections()
    with other.cursor() as cursor:
        with pytest.raises(pymysql.err.OperationalError) as error:
            cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("CHANGED TEST", case.company.name))
    assert error.value.args[0] == 1205
    other.rollback()
    case.writer.rollback()  # Caller releases BOTH source locks and pending draft.
    with other.cursor() as cursor:
        cursor.execute("UPDATE `tabCompany` SET tax_id=%s WHERE name=%s", ("CHANGED TEST", case.company.name))
    other.rollback()
    assert pending_count(connections(), case) == 0
