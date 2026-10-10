"""Opt-in encrypted staging on the OWNED private server, never a tenant schema."""

import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymysql
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher, CredentialBundleError
from zatca_erpgulf.zatca_erpgulf.credential_bundle_repository import MariaDBCredentialBundleRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture, owner, basic
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository_mariadb import isolated_server, connections
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle_access import (
    operator, service, PermissionDenied, InspectionFailed,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import csr, exchange, SELLER
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import ComplianceRequirements, ComplianceCheckSet


pytestmark = pytest.mark.skipif(os.environ.get("ZATCA_RUN_ISOLATED_MARIADB") != "1",
                               reason="Only the owned private MariaDB fixture may install this rehearsal schema")
NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def install_private_bundle_schema(isolated_server):
    # Socket comes ONLY from the fixture creating its own subprocess. There is
    # no external socket/host/site configuration override or runtime installer.
    with pymysql.connect(unix_socket=isolated_server[0], user="root", database="zatca_journal_rehearsal", autocommit=True) as database:
        schema = Path(__file__).resolve().parents[3] / "docs/zatca_unification/credential_bundle_rehearsal.sql"
        content = "\n".join(line for line in schema.read_text().splitlines() if not line.lstrip().startswith("--"))
        with database.cursor() as cursor:
            for statement in content.split(";"):
                if statement.strip():
                    cursor.execute(statement)


@pytest.fixture
def context(materials):
    namespace, flow = str(uuid4()), str(uuid4())
    key = secrets.token_bytes(32)
    cipher = CredentialBundleCipher({"test-key": key})

    def sealed(purpose="compliance", environment="Production", *, parent=None, **changes):
        snapshot = capture(materials[0], environment=environment,
                           endpoint="compliance/invoices" if purpose == "compliance" else "invoices/reporting/single")
        values = dict(storage_namespace=namespace, key_id="test-key", version_id=str(uuid4()),
                      flow_id=flow, compliance_request_id="TEST_REQUEST", parent_compliance_version_id=parent)
        values.update(changes)
        return cipher.seal(snapshot, **values)

    return namespace, cipher, sealed, key


def stage(database, namespace, cipher, envelope):
    result = MariaDBCredentialBundleRepository(database, namespace, cipher).stage(envelope)
    database.commit()  # Explicit TEST caller, not repository/Frappe hook.
    return result


@pytest.mark.parametrize("case", ["metadata", "denied", "wrong_environment"])
def test_permissioned_service_on_owned_private_storage(connections, context, operator, case):
    namespace, cipher, seal, _ = context
    envelope = stage(connections(), namespace, cipher,
                     seal(environment="Simulation" if case == "wrong_environment" else "Production"))
    database = connections()
    inspector, provider = service(operator, database, cipher, namespace=namespace)
    if case == "denied":
        operator.denied.add(("Company", "SOURCE"))
        with pytest.raises(PermissionDenied):
            inspector.inspect("TC", None, "compliance/invoices", version_id=envelope.manifest.version_id)
        provider.assert_not_called()
    elif case == "wrong_environment":
        with pytest.raises(InspectionFailed):
            inspector.inspect("TC", None, "compliance/invoices", version_id=envelope.manifest.version_id)
    else:
        report = inspector.inspect("TC", None, "compliance/invoices", version_id=envelope.manifest.version_id)
        assert report == envelope.manifest.diagnostic_projection()
        assert report["activation_authorized"] is False
    # The TEST caller releases any read lock. The service never commits or owns
    # this private connection; no Frappe tenant database participates.
    database.rollback()


@pytest.mark.parametrize("case", ["complete", "previous", "incomplete", "wrong_request_id"])
def test_bound_compliance_observations_use_authenticated_private_version(connections, context, operator, materials, case):
    namespace, cipher, seal, _ = context
    envelope = stage(connections(), namespace, cipher, seal())
    manifest = envelope.manifest
    if case == "wrong_request_id":
        manifest = replace(manifest, compliance_request_id="OTHER_REQUEST")
    requirements = ComplianceRequirements(namespace, manifest, csr(materials[0]))
    steps = requirements.required_steps[:1] if case == "incomplete" else requirements.required_steps
    observations = tuple(exchange(requirements, materials[0], step=step,
                                  status=406 if case == "previous" else 200) for step in steps)
    check_set = ComplianceCheckSet(requirements, observations)
    operator.documents["Company", "SOURCE"].values["tax_id"] = SELLER
    database = connections()
    inspector, _ = service(operator, database, cipher, namespace=namespace)
    if case == "wrong_request_id":
        with pytest.raises(InspectionFailed):
            inspector.inspect_compliance_checks("TC", None, version_id=manifest.version_id, check_set=check_set)
    else:
        report = inspector.inspect_compliance_checks("TC", None, version_id=manifest.version_id, check_set=check_set)
        assert report["state"] == ("INCOMPLETE_OBSERVATIONS" if case == "incomplete" else "COMPLETE_MATCHED_OBSERVATIONS")
        assert report["compliance_completion_verified"] is report["activation_authorized"] is False
    database.rollback()


def test_actual_commit_roundtrip_contains_only_ciphertext_for_secret_fields(connections, context, materials):
    namespace, cipher, seal, _ = context
    envelope = seal()
    database = connections()
    stage(database, namespace, cipher, envelope)
    with database.cursor() as cursor:
        cursor.execute("SELECT manifest_bytes,ciphertext FROM zatca_credential_bundle_v1 WHERE storage_namespace=%s", (namespace,))
        metadata, ciphertext = cursor.fetchone()
    for value in (materials[0].pem.encode(), materials[0].text.encode(), basic(materials[0]).encode(), b"PRIVATE-SECRET"):
        assert value not in metadata and value not in ciphertext
    recovered = MariaDBCredentialBundleRepository(connections(), namespace, cipher).load(envelope.manifest.slot, envelope.manifest.version_id)
    assert recovered == envelope
    assert cipher.open(recovered, observed_at=NOW).certificate_text == materials[0].text


def test_compliance_and_production_versions_remain_separate(connections, context):
    namespace, cipher, seal, _ = context
    database = connections()
    compliance = stage(database, namespace, cipher, seal())
    production = stage(database, namespace, cipher, seal("production", parent=compliance.manifest.version_id))
    newer = stage(database, namespace, cipher, seal())
    reader = MariaDBCredentialBundleRepository(connections(), namespace, cipher)
    assert reader.load(production.manifest.slot, production.manifest.version_id) == production
    assert reader.load(compliance.manifest.slot, compliance.manifest.version_id) == compliance
    assert newer.manifest.version_id != compliance.manifest.version_id
    assert not hasattr(reader, "activate")


def test_idempotence_requires_exact_envelope_not_certificate_fingerprint(connections, context, materials):
    namespace, cipher, seal, _ = context
    original = seal()
    database = connections()
    stage(database, namespace, cipher, original)
    assert stage(database, namespace, cipher, original) == original
    selected = owner(materials[0], custom_basic_auth_from_csid=basic(materials[0], password="CHANGED-SECRET"))
    snapshot = capture(materials[0], endpoint="compliance/invoices", selected_owner=selected)
    changed = cipher.seal(snapshot, storage_namespace=namespace, key_id="test-key", version_id=original.manifest.version_id,
                          flow_id=original.manifest.flow_id, compliance_request_id=original.manifest.compliance_request_id)
    assert changed.manifest_bytes == original.manifest_bytes
    with pytest.raises(CredentialBundleError, match="^bundle_version_conflict$"):
        MariaDBCredentialBundleRepository(database, namespace, cipher).stage(changed)
    database.rollback()
    assert MariaDBCredentialBundleRepository(database, namespace, cipher).load(original.manifest.slot, original.manifest.version_id) == original


@pytest.mark.parametrize("explicit_rollback", [False, True])
def test_interrupted_connection_and_rollback_leave_no_partial_stage(connections, context, explicit_rollback):
    namespace, cipher, seal, _ = context
    envelope = seal()
    database = connections()
    MariaDBCredentialBundleRepository(database, namespace, cipher).stage(envelope)
    if explicit_rollback:
        database.rollback()
    database.close()
    with pytest.raises(CredentialBundleError, match="^bundle_missing$"):
        MariaDBCredentialBundleRepository(connections(), namespace, cipher).load(envelope.manifest.slot, envelope.manifest.version_id)


@pytest.mark.parametrize("change", ["flow", "request", "environment", "key", "owner", "missing"])
def test_production_parent_requires_same_owner_environment_key_and_flow(connections, context, materials, change):
    namespace, cipher, seal, _ = context
    database = connections()
    compliance = stage(database, namespace, cipher, seal())
    production = seal("production", parent=compliance.manifest.version_id)
    if change == "flow":
        production = seal("production", parent=compliance.manifest.version_id, flow_id=str(uuid4()))
    elif change == "request":
        production = seal("production", parent=compliance.manifest.version_id, compliance_request_id="OTHER_REQUEST")
    elif change == "environment":
        production = seal("production", "Sandbox", parent=compliance.manifest.version_id)
    elif change in ("key", "owner"):
        material = materials[1] if change == "key" else materials[0]
        selected = owner(material, kind="linked_company") if change == "owner" else owner(material)
        production = cipher.seal(capture(material, selected_owner=selected), storage_namespace=namespace,
                                 key_id="test-key", version_id=str(uuid4()), flow_id=compliance.manifest.flow_id,
                                 compliance_request_id="TEST_REQUEST", parent_compliance_version_id=compliance.manifest.version_id)
    else:
        production = seal("production", parent=str(uuid4()))
    code = "bundle_missing" if change == "missing" else "bundle_parent_mismatch"
    with pytest.raises(CredentialBundleError, match=f"^{code}$"):
        MariaDBCredentialBundleRepository(database, namespace, cipher).stage(production)
    database.rollback()
    assert MariaDBCredentialBundleRepository(database, namespace, cipher).load(compliance.manifest.slot, compliance.manifest.version_id) == compliance


@pytest.mark.parametrize("change", ["namespace", "purpose", "environment", "owner"])
def test_exact_version_read_does_not_fall_back_across_slots(connections, context, change):
    namespace, cipher, seal, _ = context
    database = connections()
    envelope = stage(database, namespace, cipher, seal())
    requested = envelope.manifest.slot
    if change == "namespace":
        namespace = str(uuid4())
    else:
        requested = replace(requested, **{
            "purpose": {"purpose": "production"}, "environment": {"environment": "Sandbox"}, "owner": {"owner_name": "OTHER"},
        }[change])
    code = "bundle_missing" if change == "namespace" else "bundle_slot_mismatch"
    with pytest.raises(CredentialBundleError, match=f"^{code}$"):
        MariaDBCredentialBundleRepository(database, namespace, cipher).load(requested, envelope.manifest.version_id)
    database.rollback()


def test_ciphertext_corruption_is_detected_with_unchanged_public_headers(connections, context):
    namespace, cipher, seal, _ = context
    database = connections()
    envelope = stage(database, namespace, cipher, seal())
    changed = bytes([envelope.ciphertext[0] ^ 1]) + envelope.ciphertext[1:]
    with database.cursor() as cursor:
        cursor.execute("UPDATE zatca_credential_bundle_v1 SET ciphertext=%s WHERE storage_namespace=%s AND version_id=%s",
                       (changed, namespace, envelope.manifest.version_id))
    database.commit()
    with pytest.raises(CredentialBundleError, match="^bundle_authentication_failed$"):
        MariaDBCredentialBundleRepository(database, namespace, cipher).load(envelope.manifest.slot, envelope.manifest.version_id)
    database.rollback()


def test_nonce_collision_cannot_create_second_version(connections, context):
    namespace, cipher, seal, key = context
    database = connections()
    original = stage(database, namespace, cipher, seal())
    other = seal()
    # Synthetic nonce reuse solely verifies SQL collision rejection. NEVER use
    # this construction in an encryption service: SQL is not a nonce allocator.
    aad = cipher._aad(namespace, other.key_id, other.manifest_bytes)
    plaintext = AESGCM(key).decrypt(other.nonce, other.ciphertext, aad)
    colliding = replace(other, nonce=original.nonce, ciphertext=AESGCM(key).encrypt(original.nonce, plaintext, aad))
    with pytest.raises(CredentialBundleError, match="^bundle_identity_collision$"):
        MariaDBCredentialBundleRepository(database, namespace, cipher).stage(colliding)
    database.rollback()
    assert MariaDBCredentialBundleRepository(database, namespace, cipher).load(original.manifest.slot, original.manifest.version_id) == original


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_concurrent_identical_stage_does_not_duplicate(connections, context, isolation):
    namespace, cipher, seal, _ = context
    envelope = seal()
    left, right = connections(isolation), connections(isolation)
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(stage, left, namespace, cipher, envelope)
        b = executor.submit(stage, right, namespace, cipher, envelope)
        assert a.result(timeout=5) == b.result(timeout=5) == envelope
    with left.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM zatca_credential_bundle_v1 WHERE storage_namespace=%s", (namespace,))
        assert cursor.fetchone() == (1,)


def test_private_server_crash_retains_committed_encrypted_version(connections, context, isolated_server):
    namespace, cipher, seal, _ = context
    envelope = stage(connections(), namespace, cipher, seal())
    partial = seal()
    MariaDBCredentialBundleRepository(connections(), namespace, cipher).stage(partial)
    isolated_server[2]()  # Kills/restarts only the exact owned test subprocess.
    assert MariaDBCredentialBundleRepository(connections(), namespace, cipher).load(envelope.manifest.slot, envelope.manifest.version_id) == envelope
    with pytest.raises(CredentialBundleError, match="^bundle_missing$"):
        MariaDBCredentialBundleRepository(connections(), namespace, cipher).load(partial.manifest.slot, partial.manifest.version_id)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "READ COMMITTED"])
def test_concurrent_conflicting_envelopes_have_one_winner_no_replacement(connections, context, isolation):
    namespace, cipher, seal, _ = context
    first = seal()
    other = seal(version_id=first.manifest.version_id)
    left, right = connections(isolation), connections(isolation)

    def insert(database, envelope):
        try:
            return stage(database, namespace, cipher, envelope)
        except CredentialBundleError as error:
            database.rollback()
            assert error.code == "bundle_version_conflict"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(insert, left, first)
        b = executor.submit(insert, right, other)
        results = [a.result(timeout=5), b.result(timeout=5)]
    assert sum(value is not None for value in results) == 1
    winner = next(value for value in results if value is not None)
    assert MariaDBCredentialBundleRepository(connections(), namespace, cipher).load(winner.manifest.slot, winner.manifest.version_id) == winner


def test_lock_timeout_poison_requires_whole_transaction_rollback(connections, context):
    namespace, cipher, seal, _ = context
    envelope = stage(connections(), namespace, cipher, seal())
    holder = connections()
    MariaDBCredentialBundleRepository(holder, namespace, cipher).load(envelope.manifest.slot, envelope.manifest.version_id)
    waiting = connections()
    repo = MariaDBCredentialBundleRepository(waiting, namespace, cipher)
    with pytest.raises(CredentialBundleError, match="^bundle_lock_timeout$"):
        repo.stage(envelope)
    with pytest.raises(CredentialBundleError, match="^bundle_transaction_unusable$"):
        repo.load(envelope.manifest.slot, envelope.manifest.version_id)
    waiting.rollback()
    holder.rollback()
    assert MariaDBCredentialBundleRepository(waiting, namespace, cipher).load(envelope.manifest.slot, envelope.manifest.version_id) == envelope
