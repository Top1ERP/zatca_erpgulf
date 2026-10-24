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
from zatca_erpgulf.zatca_erpgulf import pending_csr_provider as pinned
from zatca_erpgulf.zatca_erpgulf import pending_csr_transaction as transaction
from zatca_erpgulf.zatca_erpgulf import primary_receipt_provider as local_sql
from unittest.mock import Mock
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_access import access_case, invoke, Denied, Failed
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_password_state import configure_password_case
from zatca_erpgulf.zatca_erpgulf.tests.test_pending_csr_transaction import configure_transaction


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
            cursor.execute("CREATE TABLE `__Auth` (doctype VARCHAR(140) NOT NULL,name VARCHAR(255) NOT NULL,"
                "fieldname VARCHAR(140) NOT NULL,password TEXT NOT NULL,encrypted INT NOT NULL,"
                "PRIMARY KEY(doctype,name,fieldname)) ENGINE=InnoDB")


def private_access_case(access_case, connections, kind):
    case = access_case(kind)
    case.scope = access.CredentialStorageScope("private.test", str(uuid4()))
    case.sealed = case.cipher.seal(case.draft, storage_namespace=case.scope.storage_namespace, key_id="test-only-key")
    password_sources = tuple(access.PasswordStateSource(row.doctype, row.name, row.password_fields) for row in case.rows)
    case.binding = replace(case.binding, scope=case.scope, manifest=case.sealed.manifest,
        password_state_sha256=access.capture_password_state(case.database, case.scope.storage_namespace, password_sources))
    admin = connections()
    with admin.cursor() as cursor:
        for doc in case.documents.values():
            # Exact fictional fixture owners only; never an app/tenant cleanup.
            cursor.execute("DELETE FROM `__Auth` WHERE doctype=%s AND name=%s", (doc.doctype, doc.name))
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


@pytest.fixture(scope="module")
def private_provider_schema(isolated_server, private_access_schema):
    with pymysql.connect(unix_socket=isolated_server[0], user="root",
                         database="zatca_journal_rehearsal", autocommit=True) as connection:
        schema = Path(__file__).resolve().parents[3] / "docs/zatca_unification/pending_csr_provider_rehearsal.sql"
        text = "\n".join(line for line in schema.read_text().splitlines() if not line.lstrip().startswith("--"))
        with connection.cursor() as cursor:
            for statement in text.split(";"):
                if statement.strip():
                    cursor.execute(statement)


@pytest.fixture
def pinned_case(private_provider_schema, isolated_server, access_case, connections):
    leases = []
    def build(kind="company"):
        case = private_access_case(access_case, connections, kind)
        observed = os.stat(isolated_server[0])  # Exact fixture-owned socket only.
        admin = connections()
        with admin.cursor() as cursor:
            cursor.execute("SELECT @@server_id")
            server_id = cursor.fetchone()[0]
            registration = str(uuid4())
            cursor.execute("INSERT INTO zatca_pending_csr_storage_binding_v1 VALUES (%s,%s,%s,%s)",
                (case.scope.storage_namespace, case.scope.site, registration, "test-only-key"))
        admin.commit()  # TEST-only provisioning, never a runtime provider action.
        case.database_binding = pinned.PendingCSRDatabaseBinding(case.scope, isolated_server[0],
            observed.st_dev, observed.st_ino, observed.st_uid, "zatca_journal_rehearsal", server_id,
            registration, "test-only-key")
        # Empty root login is for this newly owned TCP-disabled TEST server only.
        case.login = Mock(return_value=local_sql.ReceiptDatabaseCredentials("root", ""))
        case.storage_keys = Mock(return_value=pinned.PendingCSRStorageKeys(case.scope, "test-only-key", case.cipher))
        case.lease = pinned.UnixPendingCSRResourceProvider(case.database_binding, case.login, case.storage_keys)
        leases.append(case.lease)
        case.service = access.SavedPendingCSRService(case.scope, case.lookup, case.lease)
        return case
    yield build
    for lease in leases:
        if lease._state == "HANDED_OFF" and not lease.resources.connection.closed:
            try:
                lease.resources.connection.rollback()  # TEST caller owns cleanup.
            finally:
                lease.resources.connection.close()


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("commit", [False, True])
def test_concrete_pending_provider_composes_actual_service_crypto_source_locks_and_parent_transaction(pinned_case, connections, kind, commit):
    case = pinned_case(kind)
    report = invoke(case, "stage")
    owned = case.lease.resources.connection
    assert report["state"] == "PENDING_CSR_STAGED_UNCOMMITTED" and report["storage_confirmed"] is False
    with owned.cursor() as cursor:
        cursor.execute("INSERT INTO pending_csr_parent_work VALUES (%s,%s)", (case.scope.storage_namespace, "TEST PARENT"))
    observer = connections()
    assert pending_count(observer, case) == count(observer, "pending_csr_parent_work", case.scope.storage_namespace) == 0
    owned.commit() if commit else owned.rollback()  # TEST caller, never service/provider.
    observer.rollback()
    assert pending_count(observer, case) == count(observer, "pending_csr_parent_work", case.scope.storage_namespace) == int(commit)
    case.login.assert_called_once_with(case.scope)
    case.storage_keys.assert_called_once_with(case.scope)
    with pytest.raises(pinned.PendingCSRProviderError):
        case.lease(case.scope)  # No second connection/retry through the same lease.


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_concrete_pending_provider_metadata_inspection_of_exact_committed_envelope(pinned_case, kind):
    case = pinned_case(kind)
    MariaDBPendingCSRRepository(case.writer, case.scope.storage_namespace, case.cipher).stage(case.sealed)
    case.writer.commit()
    report = invoke(case, "inspect")
    assert report["state"] == "PENDING_CSR_INSPECTION_OBSERVATION" and report["storage_confirmed"] is False
    assert report["credential_epoch_verified"] is False and "private_key_pem" not in report
    case.lease.resources.connection.rollback()


@pytest.mark.parametrize("fault", ["missing-registration", "site", "registration", "key-id", "server-id"])
def test_actual_pending_registration_or_server_mismatch_refuses_keys_and_staging(pinned_case, connections, fault):
    case = pinned_case()
    admin = connections()
    with admin.cursor() as cursor:
        if fault == "missing-registration":
            cursor.execute("DELETE FROM zatca_pending_csr_storage_binding_v1 WHERE storage_namespace=%s", (case.scope.storage_namespace,))
        elif fault != "server-id":
            field, value = {"site": ("site", "other.test"), "registration": ("registration_id", str(uuid4())),
                            "key-id": ("key_id", "other-key")}[fault]
            cursor.execute("UPDATE zatca_pending_csr_storage_binding_v1 SET " + field + "=%s WHERE storage_namespace=%s",
                           (value, case.scope.storage_namespace))
    admin.commit()
    if fault == "server-id":
        case.lease._binding = replace(case.database_binding,
            server_id=(case.database_binding.server_id + 1) % (2**32))
    with pytest.raises(Failed) as error:
        invoke(case, "stage")
    assert error.value.__context__ is None
    case.storage_keys.assert_not_called()
    assert pending_count(connections(), case) == 0
    with pytest.raises(pinned.PendingCSRProviderError):
        case.lease.resources


@pytest.mark.parametrize("operation", ["cursor", "commit"])
def test_concrete_pending_wait_drift_poisoning_does_not_reset_or_commit_pending_material(pinned_case, connections, operation):
    case = pinned_case()
    invoke(case, "stage")
    owned = case.lease.resources.connection
    with owned.cursor() as cursor:
        cursor.execute("SET SESSION lock_wait_timeout=2")  # Exact owned TEST handle only.
    with pytest.raises(pinned.PendingCSRProviderError) as error:
        getattr(owned, operation)()
    assert error.value.__context__ is None
    with pytest.raises(pinned.PendingCSRProviderError):
        owned.cursor()
    owned.rollback()
    assert pending_count(connections(), case) == 0


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_concrete_pending_provider_is_not_entered_before_saved_row_acl(pinned_case, kind, operation):
    case = pinned_case(kind)
    case.denied.add((case.target.doctype, case.target.name, operation))
    with pytest.raises(Denied):
        invoke(case, "stage")
    case.login.assert_not_called()
    case.storage_keys.assert_not_called()
    assert case.lease._state == "NEW"


def test_concrete_pending_registration_stays_locked_until_caller_releases_transaction(pinned_case, connections):
    case = pinned_case()
    invoke(case, "stage")
    mutator = connections()
    with mutator.cursor() as cursor:
        with pytest.raises(pymysql.err.OperationalError) as error:
            cursor.execute("UPDATE zatca_pending_csr_storage_binding_v1 SET key_id=%s WHERE storage_namespace=%s",
                           ("other-key", case.scope.storage_namespace))
    assert error.value.args[0] == 1205
    mutator.rollback()
    case.lease.resources.connection.rollback()
    with mutator.cursor() as cursor:
        cursor.execute("UPDATE zatca_pending_csr_storage_binding_v1 SET key_id=%s WHERE storage_namespace=%s",
                       ("other-key", case.scope.storage_namespace))
    mutator.commit()
    with pytest.raises(pinned.PendingCSRProviderError):
        case.lease.resources.connection.cursor()
    assert pending_count(connections(), case) == 0


def password_native_case(pinned_case, connections, kind="company", *, company=False):
    case = configure_password_case(pinned_case(kind), company=company)
    writer = connections()
    with writer.cursor() as cursor:
        for row in case.rows:
            for field in row.password_fields:
                cursor.execute("UPDATE `tab" + row.doctype + "` SET `" + field + "`=%s WHERE name=%s", (row.get(field), row.name))
            for field, encrypted, token in case.password_records.get((row.doctype, row.name), ()):
                cursor.execute("INSERT INTO `__Auth` (doctype,name,fieldname,encrypted,password) VALUES (%s,%s,%s,%s,%s)",
                               (row.doctype, row.name, field, encrypted, token))
    writer.commit()  # Exact fictional fixture rows, never a real Password write.
    return case


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("operation", ["stage", "inspect"])
def test_pinned_service_observes_actual_encrypted_backing_without_export_or_decryption(pinned_case, connections, kind, operation):
    case = password_native_case(pinned_case, connections, kind)
    if operation == "inspect":
        MariaDBPendingCSRRepository(case.writer, case.scope.storage_namespace, case.cipher).stage(case.sealed)
        case.writer.commit()
    result = invoke(case, operation)
    assert result["password_backing_state_match_observed"] is True and result["credential_epoch_verified"] is False
    assert "ENCRYPTED TEST" not in str(result) and case.binding.password_state_sha256 not in str(result)
    case.lease.resources.connection.rollback()
    assert pending_count(connections(), case) == int(operation == "inspect")


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("operation", ["stage", "inspect"])
@pytest.mark.parametrize("change", ["rotate", "remove", "unencrypted"])
def test_native_backing_rotation_deletion_or_unknown_flag_invalidates_old_masked_source_binding(pinned_case, connections, kind, operation, change):
    case = password_native_case(pinned_case, connections, kind)
    before = (case.target.modified, case.target.custom_basic_auth_from_csid)
    writer = connections()
    with writer.cursor() as cursor:
        identity = (case.target.doctype, case.target.name, "custom_basic_auth_from_csid")
        if change == "remove":
            cursor.execute("DELETE FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname=%s", identity)
        elif change == "rotate":
            cursor.execute("UPDATE `__Auth` SET password=%s WHERE doctype=%s AND name=%s AND fieldname=%s",
                           ("ENCRYPTED TEST ROTATED", *identity))
        else:
            cursor.execute("UPDATE `__Auth` SET encrypted=0 WHERE doctype=%s AND name=%s AND fieldname=%s", identity)
    writer.commit()  # TEST-only rotation, no source-row modified/mask change.
    with pytest.raises(Failed) as error:
        invoke(case, operation)
    assert error.value.__context__ is None and (case.target.modified, case.target.custom_basic_auth_from_csid) == before
    assert pending_count(connections(), case) == 0
    case.lease.resources.connection.rollback()


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_native_orphan_backing_for_non_password_credential_field_is_not_ignored_or_repaired(pinned_case, connections, kind):
    case = pinned_case(kind)
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("INSERT INTO `__Auth` (doctype,name,fieldname,encrypted,password) VALUES (%s,%s,%s,1,%s)",
                       (case.target.doctype, case.target.name, "custom_private_key", "ENCRYPTED TEST ORPHAN"))
    writer.commit()
    with pytest.raises(Failed):
        invoke(case, "stage")
    case.lease.resources.connection.rollback()
    with writer.cursor() as cursor:
        cursor.execute("SELECT password FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname=%s",
                       (case.target.doctype, case.target.name, "custom_private_key"))
        assert cursor.fetchone() == ("ENCRYPTED TEST ORPHAN",)
    assert pending_count(connections(), case) == 0


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
def test_native_after_insert_password_change_refuses_result_and_rolls_back_only_at_caller_decision(pinned_case, connections, monkeypatch, kind):
    case = password_native_case(pinned_case, connections, kind)
    original, calls = access.capture_password_state, []
    def late_change(connection, namespace, sources):
        digest = original(connection, namespace, sources)
        calls.append(True)
        if len(calls) == 1:
            # Inject a TEST-only same-transaction mutation, after the first
            # observation. The runtime observer itself never writes Passwords.
            with connection.cursor() as cursor:
                cursor.execute("UPDATE `__Auth` SET password=%s WHERE doctype=%s AND name=%s AND fieldname=%s",
                    ("ENCRYPTED TEST LATE", case.target.doctype, case.target.name, "custom_basic_auth_from_csid"))
        return digest
    monkeypatch.setattr(access, "capture_password_state", late_change)
    with pytest.raises(Failed) as error:
        invoke(case, "stage")
    assert error.value.__context__ is None
    owned, observer = case.lease.resources.connection, connections()
    assert pending_count(owned, case) == 1 and pending_count(observer, case) == 0
    owned.rollback()
    observer.rollback()
    assert pending_count(observer, case) == 0
    with observer.cursor() as cursor:
        cursor.execute("SELECT password FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname=%s",
                       (case.target.doctype, case.target.name, "custom_basic_auth_from_csid"))
        assert cursor.fetchone() == ("ENCRYPTED TEST ORIGINAL",)


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_native_existing_password_backing_lock_blocks_competing_rotation_until_caller_releases(pinned_case, connections, kind, isolation):
    case = password_native_case(pinned_case, connections, kind)
    invoke(case, "stage")
    other = connections(isolation)
    parameters = ("ENCRYPTED TEST ROTATED", case.target.doctype, case.target.name, "custom_basic_auth_from_csid")
    with other.cursor() as cursor:
        with pytest.raises(pymysql.err.OperationalError) as error:
            cursor.execute("UPDATE `__Auth` SET password=%s WHERE doctype=%s AND name=%s AND fieldname=%s", parameters)
    assert error.value.args[0] == 1205
    other.rollback()
    case.lease.resources.connection.rollback()
    with other.cursor() as cursor:
        cursor.execute("UPDATE `__Auth` SET password=%s WHERE doctype=%s AND name=%s AND fieldname=%s", parameters)
    other.rollback()
    assert pending_count(connections(), case) == 0


def test_native_related_company_backing_rotation_invalidates_own_device_draft(pinned_case, connections):
    case = password_native_case(pinned_case, connections, "multiple_setting", company=True)
    writer = connections()
    with writer.cursor() as cursor:
        cursor.execute("UPDATE `__Auth` SET password=%s WHERE doctype=%s AND name=%s AND fieldname=%s",
                       ("ENCRYPTED TEST ROTATED", "Company", case.company.name, "custom_basic_auth_from_csid"))
    writer.commit()
    with pytest.raises(Failed):
        invoke(case, "stage")
    case.lease.resources.connection.rollback()
    assert pending_count(connections(), case) == 0


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("password", [False, True])
def test_owned_pending_coordinator_commits_and_closes_exact_source_bound_envelope(pinned_case, connections, monkeypatch, kind, password):
    case = password_native_case(pinned_case, connections, kind) if password else pinned_case(kind)
    configure_transaction(case, monkeypatch)
    result = case.transaction.save("TC", case.identity, case.sealed)
    assert result["state"] == "PENDING_CSR_TRANSACTION_COMPLETED_OBSERVATION"
    assert result["local_transaction_completed"] is True and result["storage_confirmed"] is False
    assert case.lease.resources.connection.closed and case.lookup.call_count == 4
    assert pending_count(connections(), case) == 1
    with pytest.raises(Failed):
        case.transaction.save("TC", case.identity, case.sealed)
    assert pending_count(connections(), case) == 1


@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("fault", ["source", "password", "binding", "envelope"])
def test_owned_coordinator_native_final_guard_rolls_back_drift_and_staged_envelope_together(pinned_case, connections, monkeypatch, kind, fault):
    case = password_native_case(pinned_case, connections, kind)
    configure_transaction(case, monkeypatch)
    original, calls = case.lookup.side_effect, []
    def drift(*args):
        selected = original(*args)
        calls.append(True)
        if len(calls) == 2:
            owned = case.lease.resources.connection
            with owned.cursor() as cursor:
                if fault == "source":
                    cursor.execute("UPDATE `tab" + case.target.doctype + "` SET modified=%s WHERE name=%s",
                                   ("2026-10-24 11:00:01", case.target.name))
                elif fault == "password":
                    cursor.execute("UPDATE `__Auth` SET password=%s WHERE doctype=%s AND name=%s AND fieldname=%s",
                        ("ENCRYPTED TEST ROTATED", case.target.doctype, case.target.name, "custom_basic_auth_from_csid"))
                elif fault == "envelope":
                    changed = case.cipher.seal(case.draft, storage_namespace=case.scope.storage_namespace, key_id="test-only-key")
                    cursor.execute("UPDATE zatca_pending_csr_v1 SET nonce=%s,ciphertext=%s WHERE storage_namespace=%s AND draft_id=%s",
                        (changed.nonce, changed.ciphertext, case.scope.storage_namespace, case.draft.context.draft_id))
                else:
                    selected = replace(selected, source_rows_sha256="0" * 64)
        return selected
    case.lookup.side_effect = drift
    with pytest.raises(Failed) as error:
        case.transaction.save("TC", case.identity, case.sealed)
    assert error.value.__context__ is None and case.lease.resources.connection.closed
    assert pending_count(connections(), case) == 0
    with connections().cursor() as cursor:
        cursor.execute("SELECT password FROM `__Auth` WHERE doctype=%s AND name=%s AND fieldname=%s",
            (case.target.doctype, case.target.name, "custom_basic_auth_from_csid"))
        assert cursor.fetchone() == ("ENCRYPTED TEST ORIGINAL",)


@pytest.mark.parametrize("fault", ["commit-before", "commit-after", "close-after", "late-denial"])
def test_owned_coordinator_native_unknown_commit_close_or_late_denial_never_claims_success_or_undo(pinned_case, connections, monkeypatch, fault):
    case = pinned_case()
    configure_transaction(case, monkeypatch)
    lookup, calls = case.lookup.side_effect, []
    def inject(*args):
        selected = lookup(*args)
        calls.append(True)
        if len(calls) == 2:
            raw = case.lease.resources.connection._raw  # Exact owned TEST handle only.
            if fault == "close-after":
                original = raw.close
                def close():
                    original()
                    raise RuntimeError("PRIVATE close acknowledgment lost")
                monkeypatch.setattr(raw, "close", close)
            else:
                original = raw.commit
                def commit():
                    if fault != "commit-before":
                        original()
                    if fault == "late-denial":
                        case.denied.add((case.target.doctype, case.target.name, "write"))
                        return
                    raise RuntimeError("PRIVATE commit acknowledgment lost")
                monkeypatch.setattr(raw, "commit", commit)
        return selected
    case.lookup.side_effect = inject
    with pytest.raises(Denied if fault == "late-denial" else Failed) as error:
        case.transaction.save("TC", case.identity, case.sealed)
    assert error.value.__context__ is None and case.lease.resources.connection.closed
    assert pending_count(connections(), case) == int(fault != "commit-before")
    assert len(case.visible) == 1
    # Review the SAME original through an independently supplied fresh lease.
    # Restoring this fictional ACL is explicit TEST setup, never runtime repair.
    case.denied.clear()
    case.lookup.side_effect = lookup
    fresh_review(case, monkeypatch)
    result = case.transaction.observe("TC", case.identity, case.sealed)
    assert result["envelope_observation"] == ("ABSENT_OBSERVED" if fault == "commit-before" else "EXACT_OBSERVED")
    assert result["storage_confirmed"] is False and case.lease.resources.connection.closed
    assert pending_count(connections(), case) == int(fault != "commit-before")


@pytest.mark.parametrize("permission", ["read", "write"])
def test_owned_coordinator_native_precommit_revocation_closes_and_discards_pending_only(pinned_case, connections, monkeypatch, permission):
    case = pinned_case()
    configure_transaction(case, monkeypatch)
    lookup, calls = case.lookup.side_effect, []
    def revoke(*args):
        selected = lookup(*args)
        calls.append(True)
        if len(calls) == 2:
            case.denied.add((case.target.doctype, case.target.name, permission))
        return selected
    case.lookup.side_effect = revoke
    with pytest.raises(Denied):
        case.transaction.save("TC", case.identity, case.sealed)
    assert case.lease.resources.connection.closed and pending_count(connections(), case) == 0


def fresh_review(case, monkeypatch):
    """Explicit fixture-owned fresh lease only; no discovery or runtime retry."""
    case.lease = pinned.UnixPendingCSRResourceProvider(case.database_binding, case.login, case.storage_keys)
    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only review must never stage or commit")
    monkeypatch.setattr(MariaDBPendingCSRRepository, "stage", forbidden)
    monkeypatch.setattr(pinned._OwnedPendingCSRConnection, "commit", forbidden)
    configure_transaction(case, monkeypatch)


@pytest.mark.parametrize("stored", ["absent", "exact", "conflict"])
@pytest.mark.parametrize("kind", ["company", "multiple_setting"])
@pytest.mark.parametrize("password", [False, True])
def test_owned_native_review_observes_exact_absent_or_conflicting_envelope_without_writes(pinned_case, connections, monkeypatch, stored, kind, password):
    case = password_native_case(pinned_case, connections, kind) if password else pinned_case(kind)
    stored_envelope = case.sealed
    if stored != "absent":
        if stored == "conflict":
            stored_envelope = case.cipher.seal(case.draft, storage_namespace=case.scope.storage_namespace, key_id="test-only-key")
        MariaDBPendingCSRRepository(case.writer, case.scope.storage_namespace, case.cipher).stage(stored_envelope)
        case.writer.commit()  # Provision only this fictional fixture's envelope.
    fresh_review(case, monkeypatch)
    result = case.transaction.observe("TC", case.identity, case.sealed)
    assert result["state"] == "PENDING_CSR_LOCAL_REVIEW_OBSERVATION"
    assert result["envelope_observation"] == {"absent": "ABSENT_OBSERVED", "exact": "EXACT_OBSERVED", "conflict": "CONFLICT_OBSERVED"}[stored]
    assert result["local_read_transaction_closed"] is True and result["storage_confirmed"] is False
    assert case.lease.resources.connection.closed
    observer = connections()
    assert pending_count(observer, case) == int(stored != "absent")
    if stored != "absent":
        assert MariaDBPendingCSRRepository(observer, case.scope.storage_namespace, case.cipher).load(case.draft.context) == stored_envelope
    observer.rollback()


@pytest.mark.parametrize("fault", ["authentication", "row-binding", "unknown-key"])
def test_owned_native_review_refuses_corruption_instead_of_claiming_absence_or_conflict(pinned_case, connections, monkeypatch, fault):
    case = pinned_case()
    MariaDBPendingCSRRepository(case.writer, case.scope.storage_namespace, case.cipher).stage(case.sealed)
    with case.writer.cursor() as cursor:
        if fault == "authentication":
            value = case.sealed.ciphertext[:-1] + bytes([case.sealed.ciphertext[-1] ^ 1])
            cursor.execute("UPDATE zatca_pending_csr_v1 SET ciphertext=%s WHERE storage_namespace=%s", (value, case.scope.storage_namespace))
        elif fault == "row-binding":
            cursor.execute("UPDATE zatca_pending_csr_v1 SET manifest_sha256=%s WHERE storage_namespace=%s", ("0" * 64, case.scope.storage_namespace))
        else:
            cursor.execute("UPDATE zatca_pending_csr_v1 SET key_id=%s WHERE storage_namespace=%s", ("unknown-key", case.scope.storage_namespace))
    case.writer.commit()  # Deliberately damaged owned TEST row only.
    fresh_review(case, monkeypatch)
    with pytest.raises(Failed) as error:
        case.transaction.observe("TC", case.identity, case.sealed)
    assert error.value.__context__ is None and case.visible == [transaction.REVIEW_FAILED_MESSAGE]
    assert case.lease.resources.connection.closed and pending_count(connections(), case) == 1


@pytest.mark.parametrize("stored", ["absent", "exact", "conflict"])
def test_owned_native_review_rechecks_observation_before_releasing_locks_and_rolls_back_test_mutation(pinned_case, connections, monkeypatch, stored):
    case = pinned_case()
    if stored != "absent":
        envelope = case.sealed if stored == "exact" else case.cipher.seal(case.draft,
            storage_namespace=case.scope.storage_namespace, key_id="test-only-key")
        MariaDBPendingCSRRepository(case.writer, case.scope.storage_namespace, case.cipher).stage(envelope)
        case.writer.commit()
    fresh_review(case, monkeypatch)
    lookup, calls = case.lookup.side_effect, []
    def change(*args):
        selected = lookup(*args)
        calls.append(True)
        if len(calls) == 2:
            owned = case.lease.resources.connection
            if stored == "absent":
                # Bypass only the monkeypatched TEST trap, not runtime insertion.
                with owned.cursor() as cursor:
                    sealed, context = case.sealed, case.draft.context
                    cursor.execute("INSERT INTO zatca_pending_csr_v1 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (case.scope.storage_namespace, context.draft_id, context.slot.sha256, context.flow_id,
                         sealed.manifest_bytes, sealed.manifest_sha256, sealed.key_id, sealed.nonce, sealed.ciphertext))
            else:
                with owned.cursor() as cursor:
                    cursor.execute("DELETE FROM zatca_pending_csr_v1 WHERE storage_namespace=%s", (case.scope.storage_namespace,))
        return selected
    case.lookup.side_effect = change
    with pytest.raises(Failed):
        case.transaction.observe("TC", case.identity, case.sealed)
    assert case.lease.resources.connection.closed
    assert pending_count(connections(), case) == int(stored != "absent")


@pytest.mark.parametrize("operation", ["rollback", "close"])
def test_owned_native_review_cleanup_acknowledgment_failure_withholds_result_without_repeating(pinned_case, connections, monkeypatch, operation):
    case = pinned_case()
    fresh_review(case, monkeypatch)
    lookup, calls, attempted = case.lookup.side_effect, [], []
    def fail_ack(*args):
        selected = lookup(*args)
        calls.append(True)
        if len(calls) == 2:
            raw = case.lease.resources.connection._raw  # Exact owned TEST handle.
            original = getattr(raw, operation)
            def fail():
                attempted.append(True)
                original()
                raise RuntimeError("PRIVATE review cleanup acknowledgment lost")
            monkeypatch.setattr(raw, operation, fail)
        return selected
    case.lookup.side_effect = fail_ack
    with pytest.raises(Failed) as error:
        case.transaction.observe("TC", case.identity, case.sealed)
    assert error.value.__context__ is None and len(attempted) == 1
    assert case.visible == [transaction.REVIEW_FAILED_MESSAGE]
    assert case.lease.resources.connection.closed and pending_count(connections(), case) == 0
