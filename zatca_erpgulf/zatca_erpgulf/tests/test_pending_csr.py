"""Synthetic encrypted pending-key custody; no live source, key files or HTTP."""

import base64
import json
import pickle
import secrets
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf import pending_csr as pending
from zatca_erpgulf.zatca_erpgulf.pending_csr_repository import MariaDBPendingCSRRepository
from zatca_erpgulf.zatca_erpgulf.csr_draft import prepare_csr_draft
from zatca_erpgulf.zatca_erpgulf.tests.test_csr_draft import (
    crypto, sample, context, CONFIG, materials,
)


NAMESPACE = "80d5789f-9139-4762-879d-ef432c364583"
OTHER = "9b036c58-d164-4cc8-861f-a40284293e97"


@pytest.fixture
def cipher():
    return pending.PendingCSRCipher({"test-only-key": secrets.token_bytes(32)})


@pytest.fixture
def sealed(sample, cipher):
    return cipher.seal(sample, storage_namespace=NAMESPACE, key_id="test-only-key")


def record(sealed):
    context = sealed.manifest.context
    return (context.slot.sha256, context.flow_id, sealed.manifest_bytes,
            sealed.manifest_sha256, sealed.key_id, sealed.nonce, sealed.ciphertext)


def database(rows):
    cursor, connection = Mock(), Mock()
    cursor.fetchone.side_effect = rows
    connection.cursor.return_value.__enter__ = Mock(return_value=cursor)
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    return connection, cursor


def no_transaction_ownership(connection):
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()
    connection.close.assert_not_called()


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("kind", ["company", "linked_company", "multiple_setting"])
def test_encrypt_open_preserves_exact_material_and_context_without_issuance(crypto, cipher, environment, kind):
    draft = prepare_csr_draft(context(environment, kind), CONFIG)
    envelope = cipher.seal(draft, storage_namespace=NAMESPACE, key_id="test-only-key")
    recovered = cipher.open(envelope)
    assert recovered == draft
    assert recovered.private_key_pem == draft.private_key_pem and recovered.csr_pem == draft.csr_pem
    assert crypto.generator.call_count == 1
    assert envelope.manifest.context == draft.context
    assert pending.decode_pending_manifest(envelope.manifest_bytes).encode() == envelope.manifest_bytes
    assert draft.private_key_pem not in envelope.ciphertext + envelope.manifest_bytes
    assert draft.csr_pem not in envelope.ciphertext + envelope.manifest_bytes
    assert CONFIG.encode() not in envelope.ciphertext + envelope.manifest_bytes


def test_resealing_is_not_idempotent_and_does_not_generate_another_key(sample, crypto, cipher, sealed):
    another = cipher.seal(sample, storage_namespace=NAMESPACE, key_id="test-only-key")
    assert another.manifest_bytes == sealed.manifest_bytes
    assert another.nonce != sealed.nonce and another.ciphertext != sealed.ciphertext
    assert crypto.generator.call_count == 1


@pytest.mark.parametrize("keys", [None, {}, {"key": b"short"}, {"key": "PRIVATE"},
    {"bad key": b"x" * 32}, {"a": b"x" * 32, "b": b"x" * 32}])
def test_keyring_requires_explicit_bounded_independent_material(keys):
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_keyring$") as raised:
        pending.PendingCSRCipher(keys)
    assert raised.value.__context__ is None


@pytest.mark.parametrize("change", ["namespace", "key-id", "nonce", "ciphertext", "manifest"])
def test_namespace_key_nonce_ciphertext_and_exact_manifest_are_authenticated(sample, change):
    key = secrets.token_bytes(32)
    cipher = pending.PendingCSRCipher({"test-only-key": key})
    envelope = cipher.seal(sample, storage_namespace=NAMESPACE, key_id="test-only-key")
    values = {}
    if change == "namespace":
        values["storage_namespace"] = OTHER
    elif change == "key-id":
        values["key_id"] = "other-key"
        cipher = pending.PendingCSRCipher({"other-key": key})  # Demonstrate AAD, not key-ID lookup failure.
    elif change == "nonce":
        values["nonce"] = bytes([envelope.nonce[0] ^ 1]) + envelope.nonce[1:]
    elif change == "ciphertext":
        values["ciphertext"] = envelope.ciphertext[:-1] + bytes([envelope.ciphertext[-1] ^ 1])
    else:
        manifest = envelope.manifest
        values["manifest_bytes"] = replace(manifest, context=replace(manifest.context,
            prepared_at=manifest.context.prepared_at + timedelta(seconds=1))).encode()
    changed = replace(envelope, **values)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_authentication_failed$") as raised:
        cipher.open(changed)
    assert raised.value.__context__ is None and raised.value.__cause__ is None


@pytest.mark.parametrize("change", [{"storage_namespace": "PRIVATE"}, {"key_id": "bad key"},
    {"nonce": b""}, {"nonce": "PRIVATE"}, {"ciphertext": b""}, {"ciphertext": "PRIVATE"},
    {"ciphertext": b"x" * (pending.MAX_PLAINTEXT_BYTES + 17)}, {"manifest_bytes": b"PRIVATE"},
    {"manifest_bytes": b"x" * (pending.MAX_MANIFEST_BYTES + 1)}])
def test_bad_envelope_fields_fail_before_resource_use(sealed, change):
    with pytest.raises(pending.PendingCSRStorageError) as raised:
        replace(sealed, **change)
    assert "PRIVATE" not in str(raised.value) and raised.value.__context__ is None


@pytest.mark.parametrize("case", ["schema-bool", "schema-float", "extra", "missing", "timestamp", "fingerprint", "noncanonical", "duplicate"])
def test_strict_canonical_manifest_is_not_arbitrary_json(sealed, case):
    body = json.loads(sealed.manifest_bytes)
    if case == "schema-bool":
        body["schema_version"] = True
    elif case == "schema-float":
        body["schema_version"] = 1.0
    elif case == "extra":
        body["PRIVATE"] = "PRIVATE"
    elif case == "missing":
        del body["context"]["source_revision"]
    elif case == "timestamp":
        body["context"]["prepared_at"] = "2026-10-24T12:00:00Z"
    elif case == "fingerprint":
        body["public_key_sha256"] = "PRIVATE"
    data = pending._encode(body, pending.MAX_MANIFEST_BYTES)
    if case == "noncanonical":
        data = json.dumps(body, indent=2).encode()
    if case == "duplicate":
        data = data[:-1] + b',"schema_version":1}'
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_manifest$"):
        pending.decode_pending_manifest(data)


@pytest.mark.parametrize("case", ["schema", "extra", "missing", "invalid-base64", "base64-space", "wrong-config", "wrong-csr", "wrong-fingerprint", "duplicate", "not-object"])
def test_authenticated_but_invalid_payload_is_revalidated(sample, case):
    key = secrets.token_bytes(32)
    cipher = pending.PendingCSRCipher({"test-only-key": key})
    envelope = cipher.seal(sample, storage_namespace=NAMESPACE, key_id="test-only-key")
    aad = cipher._aad(NAMESPACE, envelope.key_id, envelope.manifest_bytes)
    body = json.loads(AESGCM(key).decrypt(envelope.nonce, envelope.ciphertext, aad))
    metadata = envelope.manifest_bytes
    if case == "schema":
        body["schema_version"] = True
    elif case == "extra":
        body["PRIVATE"] = "PRIVATE"
    elif case == "missing":
        del body["private_key_pem"]
    elif case == "invalid-base64":
        body["private_key_pem"] = "PRIVATE?"
    elif case == "base64-space":
        body["private_key_pem"] += "\n"
    elif case == "wrong-config":
        body["config_text"] = CONFIG.replace("TEST ONLY", "DIFFERENT TEST")
    elif case == "wrong-csr":
        body["csr_pem"] = base64.b64encode(b"PRIVATE invalid").decode()
    elif case == "wrong-fingerprint":
        metadata = replace(envelope.manifest, public_key_sha256="0" * 64).encode()
    payload = pending._encode(body, pending.MAX_PLAINTEXT_BYTES)
    if case == "duplicate":
        payload = payload[:-1] + b',"schema_version":1}'
    if case == "not-object":
        payload = b"[]"
    # A NEW nonce for every intentionally altered synthetic authenticated body.
    nonce = secrets.token_bytes(12)
    changed = replace(envelope, manifest_bytes=metadata, nonce=nonce,
        ciphertext=AESGCM(key).encrypt(nonce, payload, cipher._aad(NAMESPACE, envelope.key_id, metadata)))
    with pytest.raises(pending.PendingCSRStorageError) as raised:
        cipher.open(changed)
    assert raised.value.code in ("pending_csr_payload", "pending_csr_material")
    assert raised.value.__context__ is None and "PRIVATE" not in str(raised.value)


def test_tampered_draft_fingerprint_is_not_silently_repaired_before_sealing(sample, cipher):
    object.__setattr__(sample, "public_key_sha256", "0" * 64)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_material$"):
        cipher.seal(sample, storage_namespace=NAMESPACE, key_id="test-only-key")
    assert sample.public_key_sha256 == "0" * 64


def test_key_copy_rotation_and_unavailable_key_do_not_guess_or_discover(sample):
    original = secrets.token_bytes(32)
    keys = {"old": original}
    cipher = pending.PendingCSRCipher(keys)
    envelope = cipher.seal(sample, storage_namespace=NAMESPACE, key_id="old")
    keys["old"] = secrets.token_bytes(32)
    assert cipher.open(envelope) == sample
    rotated = pending.PendingCSRCipher({"old": original, "new": secrets.token_bytes(32)})
    assert rotated.open(envelope) == sample
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_key_unavailable$"):
        pending.PendingCSRCipher({"new": secrets.token_bytes(32)}).open(envelope)


def test_repr_and_metadata_never_export_raw_material_or_authority(sample, sealed, cipher):
    exported = repr(cipher) + repr(sealed) + repr(sealed.manifest) + json.dumps(sealed.manifest.diagnostic_projection())
    for private in (sample.private_key_pem.decode(), sample.csr_pem.decode(), CONFIG, "TEST COMPANY"):
        assert private not in exported
    assert sample.context.company_name.encode() in sealed.manifest_bytes  # Restricted business metadata, not anonymous.
    report = sealed.manifest.diagnostic_projection()
    assert all(value is False for name, value in report.items() if name.endswith(("_verified", "_authorized", "_confirmed")))
    report["activation_authorized"] = True
    assert sealed.manifest.diagnostic_projection()["activation_authorized"] is False


@pytest.mark.parametrize("kind", ["cipher", "sealed", "repository"])
def test_accidental_pickle_transport_is_denied(sealed, cipher, kind):
    value = cipher if kind == "cipher" else sealed if kind == "sealed" else MariaDBPendingCSRRepository(Mock(), NAMESPACE, cipher)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_not_pickleable$"):
        pickle.dumps(value)


@pytest.mark.parametrize("operation", ["stage", "load"])
def test_exact_repository_roundtrip_uses_only_ciphertext_and_owned_transaction(sealed, cipher, operation):
    connection, cursor = database([(0,), record(sealed)])
    repository = MariaDBPendingCSRRepository(connection, NAMESPACE, cipher)
    assert getattr(repository, operation)(sealed if operation == "stage" else sealed.manifest.context) == sealed
    if operation == "stage":
        parameters = cursor.execute.call_args_list[1].args[1]
        assert parameters[-1] == sealed.ciphertext
        assert all(b"BEGIN EC PRIVATE KEY" not in value for value in parameters if type(value) is bytes)
    no_transaction_ownership(connection)


@pytest.mark.parametrize("index", range(7))
def test_corrupt_storage_columns_are_not_repaired_or_returned(sealed, cipher, index):
    row = list(record(sealed))
    row[index] = "PRIVATE" if index in (0, 1, 3, 4) else b"PRIVATE"
    connection, cursor = database([(0,), tuple(row)])
    repository = MariaDBPendingCSRRepository(connection, NAMESPACE, cipher)
    with pytest.raises(pending.PendingCSRStorageError):
        repository.load(sealed.manifest.context)
    count = cursor.execute.call_count
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_transaction_unusable$"):
        repository.stage(sealed)
    assert cursor.execute.call_count == count
    no_transaction_ownership(connection)


@pytest.mark.parametrize("number,code", [(1062, "unique_conflict"), (1205, "lock_timeout"),
    (1213, "deadlock"), (None, "database_error"), ("PRIVATE", "database_error")])
def test_driver_faults_are_static_without_stringifying_or_reading_overridden_args(sealed, cipher, number, code):
    class OpaqueDriverError(Exception):
        def __str__(self):
            raise AssertionError("No private driver diagnostics")
        def __getattribute__(self, name):
            if name == "args":
                raise AssertionError("Do not invoke overridden diagnostic access")
            return super().__getattribute__(name)
    connection, cursor = database([])
    cursor.execute.side_effect = OpaqueDriverError(number, "PRIVATE")
    repository = MariaDBPendingCSRRepository(connection, NAMESPACE, cipher)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_" + code + "$") as raised:
        repository.stage(sealed)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    no_transaction_ownership(connection)


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_cancellation_poisoning_does_not_commit_rollback_retry_or_cleanup(sealed, cipher, stop):
    connection, cursor = database([])
    cursor.execute.side_effect = stop()
    repository = MariaDBPendingCSRRepository(connection, NAMESPACE, cipher)
    with pytest.raises(stop):
        repository.stage(sealed)
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_transaction_unusable$"):
        repository.load(sealed.manifest.context)
    no_transaction_ownership(connection)


@pytest.mark.parametrize("argument", [None, {}, "PRIVATE"])
@pytest.mark.parametrize("operation", ["stage", "load"])
def test_invalid_preflight_poisoning_precedes_all_sql(sealed, cipher, argument, operation):
    connection, cursor = database([])
    repository = MariaDBPendingCSRRepository(connection, NAMESPACE, cipher)
    with pytest.raises(pending.PendingCSRStorageError):
        getattr(repository, operation)(argument)
    cursor.execute.assert_not_called()
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_transaction_unusable$"):
        repository.stage(sealed)
    no_transaction_ownership(connection)


@pytest.mark.parametrize("change", [{"source_revision": "2026-10-24 11:00:01"},
    {"flow_id": OTHER}, {"prepared_at": context().prepared_at + timedelta(seconds=1)}])
def test_load_requires_exact_declared_revision_flow_and_time(sealed, cipher, change):
    connection, cursor = database([(0,), record(sealed)])
    with pytest.raises(pending.PendingCSRStorageError, match="^pending_csr_context$"):
        MariaDBPendingCSRRepository(connection, NAMESPACE, cipher).load(replace(sealed.manifest.context, **change))
    no_transaction_ownership(connection)
