"""Generated in-memory keys and material only; no tenant, key files or HTTP."""

import hashlib
import json
import pickle
import secrets
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf import credential_bundle as bundle
from zatca_erpgulf.zatca_erpgulf.credential_bundle_repository import MariaDBCredentialBundleRepository
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import capture, owner, basic
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials


NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
NAMESPACE = "315c254e-91d3-4c5f-a399-a9c54c24d756"
VERSION = "d7a5c639-1fda-46a9-aebd-07c4a9d08e37"
FLOW = "11cc149a-0bd9-4919-a9b9-031f518c6760"
PARENT = "e8d42e8a-3d28-45e9-ae4d-662814932f66"


@pytest.fixture
def cipher():
    return bundle.CredentialBundleCipher({"test-key": secrets.token_bytes(32)})


def seal(cipher, snapshot, **changes):
    values = dict(storage_namespace=NAMESPACE, key_id="test-key", version_id=VERSION,
                  flow_id=FLOW, compliance_request_id="TEST_REQUEST_1",
                  parent_compliance_version_id=PARENT if snapshot is not None and snapshot.authorization.purpose == "production" else None)
    values.update(changes)
    return cipher.seal(snapshot, **values)


def record(sealed):
    manifest = sealed.manifest
    return (manifest.slot.sha256, manifest.slot.environment, manifest.slot.purpose,
            manifest.flow_id, manifest.parent_compliance_version_id, sealed.manifest_bytes,
            sealed.manifest_sha256, sealed.key_id, sealed.nonce, sealed.ciphertext)


def connection(rows):
    cursor = Mock()
    cursor.fetchone.side_effect = rows
    database = Mock()
    database.cursor.return_value.__enter__ = Mock(return_value=cursor)
    database.cursor.return_value.__exit__ = Mock(return_value=False)
    return database, cursor


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("purpose", ["compliance", "production"])
@pytest.mark.parametrize("doctype,kind", [("Company", "company"), ("Company", "linked_company"), ("ZATCA Multiple Setting", "multiple_setting")])
def test_encrypt_open_preserves_exact_material_for_all_slots(materials, cipher, environment, purpose, doctype, kind):
    material = materials[0]
    selected = owner(material, doctype=doctype, kind=kind)
    snapshot = capture(material, environment=environment, endpoint="compliance/invoices" if purpose == "compliance" else "invoices/reporting/single", selected_owner=selected)
    sealed = seal(cipher, snapshot)
    recovered = cipher.open(sealed, observed_at=NOW)
    assert recovered.authorization.header == snapshot.authorization.header
    assert recovered.certificate_text == snapshot.certificate_text
    assert recovered.owner.values == snapshot.owner.values
    assert recovered.route == snapshot.route
    assert sealed.manifest.slot.environment == environment and sealed.manifest.slot.purpose == purpose
    for protected in (material.pem.encode(), basic(material).encode(), material.text.encode(), b"PRIVATE-SECRET"):
        assert protected not in sealed.ciphertext
        assert protected not in sealed.manifest_bytes
        assert protected.decode() not in repr(sealed)
    assert all(value is False for name, value in sealed.manifest.diagnostic_projection().items() if name.endswith(("_authorized", "_verified")))


def test_exact_certificate_whitespace_survives_without_digest_repair(materials, cipher):
    text = "\n" + materials[0].text + "\n"
    snapshot = capture(materials[0], text=text)
    sealed = seal(cipher, snapshot)
    assert cipher.open(sealed, observed_at=NOW).certificate_text == text
    assert sealed.manifest.certificate_text_sha256 == hashlib.sha256(text.encode()).hexdigest()


def test_sealing_same_material_twice_does_not_reuse_nonce_or_claim_idempotence(materials, cipher):
    snapshot = capture(materials[0])
    left, right = seal(cipher, snapshot), seal(cipher, snapshot)
    assert left.manifest_bytes == right.manifest_bytes
    assert left.nonce != right.nonce and left.ciphertext != right.ciphertext


@pytest.mark.parametrize("change", [
    {"storage_namespace": str(uuid4())}, {"key_id": "other-key"},
    {"nonce": b"x" * 12},
])
def test_namespace_key_id_and_nonce_are_authenticated(materials, change):
    key = secrets.token_bytes(32)
    # Repeated material under different IDs is rejected in ordinary keyrings;
    # separate providers here show that key-ID substitution also changes AAD.
    first = bundle.CredentialBundleCipher({"test-key": key})
    sealed = seal(first, capture(materials[0]))
    changed = replace(sealed, **change)
    provider = bundle.CredentialBundleCipher({changed.key_id: key})
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_authentication_failed$"):
        provider.open(changed, observed_at=NOW)


@pytest.mark.parametrize("field,value", [
    ("version_id", str(uuid4())), ("flow_id", str(uuid4())),
    ("compliance_request_id", "OTHER_REQUEST"), ("certificate_der_sha256", "a" * 64),
    ("parent_compliance_version_id", str(uuid4())), ("company_name", "OTHER"),
])
def test_manifest_is_authenticated_not_merely_hashed(materials, cipher, field, value):
    sealed = seal(cipher, capture(materials[0], selected_owner=owner(materials[0], kind="linked_company")))
    changed = replace(sealed.manifest, **{field: value})
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_authentication_failed$"):
        cipher.open(replace(sealed, manifest_bytes=changed.encode()), observed_at=NOW)


def test_ciphertext_tampering_wrong_key_and_truncation_are_static(materials, cipher):
    sealed = seal(cipher, capture(materials[0]))
    for content in (bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:], sealed.ciphertext[:-1]):
        with pytest.raises(bundle.CredentialBundleError, match="^bundle_authentication_failed$"):
            cipher.open(replace(sealed, ciphertext=content), observed_at=NOW)
    wrong = bundle.CredentialBundleCipher({"test-key": secrets.token_bytes(32)})
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_authentication_failed$"):
        wrong.open(sealed, observed_at=NOW)


@pytest.mark.parametrize("keys,code", [
    (None, "bundle_keyring"), ({}, "bundle_keyring"), ({"test-key": b"short"}, "bundle_key_material"),
    ({"PRIVATE invalid/key": b"x" * 32}, "bundle_key_id"), ({"test-key": "PRIVATE"}, "bundle_key_material"),
    ({"one": b"x" * 32, "two": b"x" * 32}, "bundle_duplicate_key_material"),
])
def test_keyring_rejects_bad_material_without_exposing_it(keys, code):
    with pytest.raises(bundle.CredentialBundleError, match=f"^{code}$"):
        bundle.CredentialBundleCipher(keys)


def test_keyring_copy_rotation_and_pickle_privacy(materials):
    original_key = secrets.token_bytes(32)
    keys = {"test-key": original_key}
    cipher = bundle.CredentialBundleCipher(keys)
    sealed = seal(cipher, capture(materials[0]))
    keys["test-key"] = secrets.token_bytes(32)
    assert cipher.open(sealed, observed_at=NOW).certificate_text == materials[0].text
    assert original_key.hex() not in repr(cipher)
    for value in (cipher, sealed):
        with pytest.raises(bundle.CredentialBundleError, match="^bundle_not_pickleable$"):
            pickle.dumps(value)
    retained = bundle.CredentialBundleCipher({"old": original_key, "test-key": keys["test-key"]})
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_authentication_failed$"):
        retained.open(sealed, observed_at=NOW)
    # Keeping the ORIGINAL key ID enables old versions after adding a new key.
    retained = bundle.CredentialBundleCipher({"test-key": original_key, "new": keys["test-key"]})
    assert retained.open(sealed, observed_at=NOW).certificate_text == materials[0].text


@pytest.mark.parametrize("change,code", [
    ({"version_id": "bad"}, "bundle_version"), ({"flow_id": "bad"}, "bundle_flow"),
    ({"compliance_request_id": "PRIVATE:secret"}, "bundle_request_id"),
    ({"parent_compliance_version_id": None}, "bundle_parent"),
    ({"parent_compliance_version_id": VERSION}, "bundle_parent"),
    ({"storage_namespace": "bad"}, "bundle_namespace"), ({"key_id": "not-present"}, "bundle_key_unavailable"),
])
def test_staging_declarations_are_explicit_and_bounded(materials, cipher, change, code):
    with pytest.raises(bundle.CredentialBundleError, match=f"^{code}$"):
        seal(cipher, capture(materials[0]), **change)


def test_compliance_cannot_declare_production_parent(materials, cipher):
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_parent$"):
        seal(cipher, capture(materials[0], endpoint="compliance/invoices"), parent_compliance_version_id=PARENT)


@pytest.mark.parametrize("at,code", [
    (None, "bundle_observation_time"), (NOW.replace(tzinfo=None), "bundle_observation_time"),
    (datetime(2031, 1, 1, tzinfo=timezone.utc), "bundle_material_invalid"),
])
def test_open_requires_explicit_fresh_local_validity(materials, cipher, at, code):
    sealed = seal(cipher, capture(materials[0]))
    with pytest.raises(bundle.CredentialBundleError, match=f"^{code}$"):
        cipher.open(sealed, observed_at=at)


@pytest.mark.parametrize("content", [b"{}", b"[]", b'{"schema_version":1,"schema_version":1}', b"PRIVATE", b"a" * (8192 + 1)])
def test_manifest_parser_rejects_bad_json_schema_and_size(content):
    with pytest.raises(bundle.CredentialBundleError) as error:
        bundle.decode_bundle_manifest(content)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("change", [{"nonce": b"short"}, {"ciphertext": b"short"}, {"ciphertext": b"a" * (1024 * 1024 + 17)}])
def test_envelope_bounds_before_crypto(materials, cipher, change):
    sealed = seal(cipher, capture(materials[0]))
    with pytest.raises(bundle.CredentialBundleError):
        replace(sealed, **change)


def test_authenticated_plaintext_still_requires_strict_schema_and_binding(materials):
    key = secrets.token_bytes(32)
    cipher = bundle.CredentialBundleCipher({"test-key": key})
    sealed = seal(cipher, capture(materials[0]))
    aad = cipher._aad(NAMESPACE, sealed.key_id, sealed.manifest_bytes)
    body = json.loads(AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, aad))
    for change in ({"private_key": "PRIVATE invalid"}, {"authorization": basic(materials[1])}, {"route": {}}, {"extra": "PRIVATE"}):
        nonce = secrets.token_bytes(12)
        data = json.dumps({**body, **change}).encode()
        forged = replace(sealed, nonce=nonce, ciphertext=AESGCM(key).encrypt(nonce, data, aad))
        with pytest.raises(bundle.CredentialBundleError) as error:
            cipher.open(forged, observed_at=NOW)
        assert "PRIVATE" not in str(error.value)


def test_snapshot_and_envelope_types_are_required(cipher):
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_snapshot$"):
        seal(cipher, None)
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_envelope$"):
        cipher.open(None, observed_at=NOW)


def test_repository_roundtrip_and_identical_envelope_redelivery(materials, cipher):
    sealed = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, cursor = connection([(0,), record(sealed), (0,), record(sealed)])
    repo = MariaDBCredentialBundleRepository(database, NAMESPACE, cipher)
    assert repo.stage(sealed) == sealed
    assert repo.load(sealed.manifest.slot, VERSION) == sealed
    database.commit.assert_not_called()
    database.rollback.assert_not_called()
    queries = [call.args[0] for call in cursor.execute.call_args_list]
    assert all("PRIVATE" not in query for query in queries)
    parameters = cursor.execute.call_args_list[1].args[1]
    assert sealed.ciphertext in parameters
    assert not any(materials[0].pem in value for value in parameters if type(value) is str)


def test_same_certificate_different_password_cannot_replace_version(materials, cipher):
    old = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    selected = owner(materials[0], custom_basic_auth_from_csid=basic(materials[0], password="CHANGED-SECRET"))
    new = seal(cipher, capture(materials[0], endpoint="compliance/invoices", selected_owner=selected))
    assert old.manifest_bytes == new.manifest_bytes
    database, _ = connection([(0,), record(old)])
    repo = MariaDBCredentialBundleRepository(database, NAMESPACE, cipher)
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_version_conflict$"):
        repo.stage(new)
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_transaction_unusable$"):
        repo.load(old.manifest.slot, VERSION)


@pytest.mark.parametrize("autocommit", [1, True])
def test_autocommit_is_rejected_without_session_repair(materials, cipher, autocommit):
    sealed = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, cursor = connection([(autocommit,)])
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_autocommit$"):
        MariaDBCredentialBundleRepository(database, NAMESPACE, cipher).stage(sealed)
    assert cursor.execute.call_count == 1
    database.commit.assert_not_called()


@pytest.mark.parametrize("position,value", [(0, "a" * 64), (1, "Sandbox"), (2, "production"), (3, str(uuid4())), (4, str(uuid4())), (6, "a" * 64)])
def test_denormalized_row_corruption_detected(materials, cipher, position, value):
    sealed = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    row = list(record(sealed))
    row[position] = value
    database, _ = connection([(0,), tuple(row)])
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_row_fingerprint$"):
        MariaDBCredentialBundleRepository(database, NAMESPACE, cipher).load(sealed.manifest.slot, VERSION)


@pytest.mark.parametrize("number,code", [(1062, "bundle_unique_conflict"), (1205, "bundle_lock_timeout"), (1213, "bundle_deadlock"), (999, "bundle_database_error")])
def test_driver_errors_do_not_leak_parameters(materials, cipher, number, code):
    sealed = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, cursor = connection([])
    cursor.execute.side_effect = Exception(number, "PRIVATE DB parameter")
    repo = MariaDBCredentialBundleRepository(database, NAMESPACE, cipher)
    with pytest.raises(bundle.CredentialBundleError, match=f"^{code}$"):
        repo.stage(sealed)
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_transaction_unusable$"):
        repo.load(sealed.manifest.slot, VERSION)


def test_bad_preflight_also_poisoned_transaction_and_wrong_slot_never_falls_back(materials, cipher):
    sealed = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, _ = connection([(0,), record(sealed)])
    repo = MariaDBCredentialBundleRepository(database, NAMESPACE, cipher)
    wrong = replace(sealed.manifest.slot, purpose="production")
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_slot_mismatch$"):
        repo.load(wrong, VERSION)
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_transaction_unusable$"):
        repo.stage(sealed)
    database, cursor = connection([])
    repo = MariaDBCredentialBundleRepository(database, NAMESPACE, cipher)
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_version$"):
        repo.load(sealed.manifest.slot, "latest")
    cursor.execute.assert_not_called()
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_transaction_unusable$"):
        repo.stage(sealed)


def test_repository_has_no_activation_or_transaction_management_api(cipher):
    repo = MariaDBCredentialBundleRepository(Mock(), NAMESPACE, cipher)
    for name in ("activate", "latest", "get_active", "commit", "rollback", "migrate", "install_schema", "send"):
        assert not hasattr(repo, name)


@pytest.mark.parametrize("change", [
    {"owner_doctype": "User"}, {"owner_name": ""}, {"owner_name": " PRIVATE "},
    {"environment": None}, {"environment": "production"}, {"purpose": "otp"},
])
def test_slot_rejects_unsupported_identity_environment_or_purpose(change):
    values = dict(owner_doctype="Company", owner_name="TEST", environment="Production", purpose="compliance")
    with pytest.raises(bundle.CredentialBundleError):
        bundle.CredentialSlot(**{**values, **change})


@pytest.mark.parametrize("change", [
    {"company_name": ""}, {"source_kind": "unknown"}, {"prepared_at": NOW.replace(tzinfo=None)},
    {"certificate_der_sha256": "invalid"}, {"public_key_sha256": "invalid"}, {"certificate_text_sha256": "invalid"},
])
def test_manifest_revalidates_owner_time_and_all_public_fingerprints(materials, cipher, change):
    manifest = seal(cipher, capture(materials[0])).manifest
    with pytest.raises(bundle.CredentialBundleError):
        replace(manifest, **change)


@pytest.mark.parametrize("attribute,value", [("environment", "Sandbox"), ("owner_name", "OTHER")])
def test_changing_slot_in_manifest_cannot_move_secret_material(materials, cipher, attribute, value):
    sealed = seal(cipher, capture(materials[0], selected_owner=owner(materials[0], kind="linked_company")))
    manifest = replace(sealed.manifest, slot=replace(sealed.manifest.slot, **{attribute: value}))
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_authentication_failed$"):
        cipher.open(replace(sealed, manifest_bytes=manifest.encode()), observed_at=NOW)


def test_metadata_wire_representation_must_be_canonical(materials, cipher):
    sealed = seal(cipher, capture(materials[0]))
    noncanonical = json.dumps(json.loads(sealed.manifest_bytes), indent=2).encode()
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_manifest_representation$"):
        replace(sealed, manifest_bytes=noncanonical)
    body = json.loads(sealed.manifest_bytes)
    body["schema_version"] = True
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_schema_version$"):
        bundle.decode_bundle_manifest(json.dumps(body).encode())


def test_wrong_namespace_or_bad_envelope_fails_before_sql_and_poisons_handle(materials, cipher):
    sealed = seal(cipher, capture(materials[0], endpoint="compliance/invoices"))
    database, cursor = connection([])
    repo = MariaDBCredentialBundleRepository(database, str(uuid4()), cipher)
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_namespace_or_envelope$"):
        repo.stage(sealed)
    cursor.execute.assert_not_called()
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_transaction_unusable$"):
        repo.stage(None)


def test_key_unavailability_is_static_without_using_other_key(materials, cipher):
    sealed = seal(cipher, capture(materials[0]))
    unavailable = bundle.CredentialBundleCipher({"other": secrets.token_bytes(32)})
    with pytest.raises(bundle.CredentialBundleError, match="^bundle_key_unavailable$"):
        unavailable.open(sealed, observed_at=NOW)


def test_encrypt_open_do_not_discover_files_database_network_or_site_keys(materials, cipher, monkeypatch):
    import requests
    from zatca_erpgulf.zatca_erpgulf import credential_settings

    snapshot = capture(materials[0])

    def forbidden(*args, **kwargs):
        pytest.fail("Encrypted credential staging attempted external access")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(credential_settings.frappe, "get_doc", forbidden)
    sealed = seal(cipher, snapshot)
    assert cipher.open(sealed, observed_at=NOW).authorization.header == snapshot.authorization.header
