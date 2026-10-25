"""Synthetic exact-original encryption; no real keys, tenant or transport."""

import pickle
from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf import preparation_custody as custody
from zatca_erpgulf.zatca_erpgulf.credential_bundle_access import CredentialStorageScope
from zatca_erpgulf.zatca_erpgulf.preparation_recovery_access import RetainedPreparationOriginal
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_preparation_hold import sample


@pytest.fixture
def retained(certificates):
    hold, candidate = sample(certificates[0])
    return RetainedPreparationOriginal(CredentialStorageScope("private.test", str(uuid4())), hold, candidate)


@pytest.fixture
def cipher():
    return custody.PreparationOriginalCipher({"test-preparation-v1": b"P" * 32})


def seal(cipher, retained):
    return cipher.seal(retained, key_id="test-preparation-v1")


def assert_private(call, code):
    with pytest.raises(custody.PreparationCustodyError) as caught:
        call()
    assert str(caught.value) == code
    assert caught.value.__context__ is None


@pytest.mark.parametrize("completed", [False, True])
def test_exact_codec_and_cipher_roundtrip(retained, cipher, completed):
    if completed:
        retained = replace(retained, hold=replace(retained.hold,
            original_manifest_sha256=retained.candidate.manifest_sha256))
    payload = custody.encode_preparation_original(retained)
    assert custody.decode_preparation_original(payload) == retained
    assert retained.candidate.xml_bytes in payload
    first, second = seal(cipher, retained), seal(cipher, retained)
    assert first != second and first.nonce != second.nonce
    assert cipher.open(first) == cipher.open(second) == retained
    assert custody.sealed_preparation_sha256(first) != custody.sealed_preparation_sha256(second)
    assert retained.candidate.xml_bytes not in first.ciphertext
    assert retained.candidate.xml_bytes.decode() not in repr(first)
    for protected in (first, cipher):
        with pytest.raises(custody.PreparationCustodyError, match="not_pickleable"):
            pickle.dumps(protected)


@pytest.mark.parametrize("cut", [0, 1, 4, 20, 39, 100, -1])
def test_truncation_is_static(retained, cut):
    payload = custody.encode_preparation_original(retained)
    assert_private(lambda: custody.decode_preparation_original(payload[:cut]), "preparation_custody_payload")


@pytest.mark.parametrize("change", ["type", "magic", "trailing", "length", "ticket", "context", "xml"])
def test_frame_corruption_is_static(retained, change):
    payload = custody.encode_preparation_original(retained)
    if change == "type": payload = bytearray(payload)
    elif change == "magic": payload = b"!" + payload[1:]
    elif change == "trailing": payload += b"PRIVATE"
    elif change == "length":
        n = len(custody.MAGIC)
        payload = payload[:n] + (256).to_bytes(4, "big") + payload[n+4:]
    else:
        parts = list(custody.decode_frames(custody.MAGIC, custody.FRAME_BOUNDS, payload))
        parts[{"ticket":3, "context":5, "xml":6}[change]] = b"PRIVATE"
        payload = custody.encode_frames(custody.MAGIC, custody.FRAME_BOUNDS, tuple(parts))
    assert_private(lambda: custody.decode_preparation_original(payload), "preparation_custody_payload")


@pytest.mark.parametrize("field", [*custody.AAD_FIELDS, "nonce", "ciphertext"])
def test_all_envelope_fields_are_authenticated(retained, cipher, field):
    sealed = seal(cipher, retained)
    values = {"site":"other.test", "storage_namespace":str(uuid4()), "hold_id":str(uuid4()),
        "key_id":"other-key", "nonce":b"N"*12,
        "ciphertext":sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1])}
    changed = replace(sealed, **{field:values.get(field, "f"*64)})
    assert_private(lambda: cipher.open(changed), "preparation_custody_authentication")


def test_valid_gcm_with_false_metadata_is_not_a_valid_original(retained, cipher):
    sealed = seal(cipher, retained)
    metadata = {name:getattr(sealed, name) for name in custody.AAD_FIELDS}
    metadata["ticket_sha256"] = "f"*64
    ciphertext = AESGCM(b"P"*32).encrypt(sealed.nonce,
        custody.encode_preparation_original(retained), custody._aad(metadata))
    changed = replace(sealed, ticket_sha256="f"*64, ciphertext=ciphertext)
    assert_private(lambda: cipher.open(changed), "preparation_custody_authentication")


@pytest.mark.parametrize("keys", [{}, {"x":b"short"}, {"x":bytearray(b"P"*32)}, None])
def test_invalid_keyrings_do_not_disclose_material(keys):
    assert_private(lambda: custody.PreparationOriginalCipher(keys), "preparation_custody_keyring")


def test_keyring_is_copied_and_wrong_key_rejected(retained):
    keys = {"test-preparation-v1": b"P"*32}
    cipher = custody.PreparationOriginalCipher(keys)
    sealed = seal(cipher, retained)
    keys["test-preparation-v1"] = b"Q"*32
    assert cipher.open(sealed) == retained
    wrong = custody.PreparationOriginalCipher(keys)
    assert_private(lambda: wrong.open(sealed), "preparation_custody_authentication")


def repository_case(retained, cipher, monkeypatch, *, autocommit=0):
    sealed = seal(cipher, retained)
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.fetchone.side_effect = lambda: ((autocommit,) if cursor.execute.call_args.args[0].startswith("SELECT @@")
        else tuple(getattr(sealed, name) for name in ("site", "ticket_sha256", "candidate_sha256",
            "manifest_sha256", "payload_sha256", "key_id", "nonce", "ciphertext")))
    connection = Mock()
    connection.cursor.return_value = cursor
    holds = Mock()
    monkeypatch.setattr(custody, "MariaDBPreparationHoldRepository", Mock(return_value=holds))
    repository = custody.MariaDBPreparationCustodyRepository(connection, retained.scope.storage_namespace, cipher)
    return sealed, repository, connection, cursor, holds


def test_raw_storage_is_caller_owned_and_exact(retained, cipher, monkeypatch):
    sealed, repo, conn, cursor, holds = repository_case(retained, cipher, monkeypatch)
    assert repo.stage(sealed) == sealed
    holds.load.assert_called_once_with(retained.hold)
    holds.complete.assert_not_called()
    holds.reserve.assert_not_called()
    assert repo.load(sealed.hold_id) == sealed
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.close.assert_not_called()
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("SUBSTRING(ciphertext" in query for query in sql)
    assert not any("DELETE " in query or "issuance_candidate" in query for query in sql)


@pytest.mark.parametrize("autocommit", [True, False, 1, None, "0"])
def test_raw_storage_requires_real_explicit_transaction(retained, cipher, monkeypatch, autocommit):
    sealed, repo, conn, cursor, holds = repository_case(retained, cipher, monkeypatch, autocommit=autocommit)
    assert_private(lambda: repo.load(sealed.hold_id), "preparation_custody_autocommit")
    assert_private(lambda: repo.load(sealed.hold_id), "preparation_custody_transaction_unusable")


def test_resealing_cannot_replace_even_equal_plaintext(retained, cipher, monkeypatch):
    sealed, repo, conn, cursor, holds = repository_case(retained, cipher, monkeypatch)
    assert_private(lambda: repo.stage(seal(cipher, retained)), "preparation_custody_conflict")
    assert_private(lambda: repo.stage(sealed), "preparation_custody_transaction_unusable")


def test_bad_envelope_fails_before_sql(retained, cipher, monkeypatch):
    sealed, repo, conn, cursor, holds = repository_case(retained, cipher, monkeypatch)
    broken = replace(sealed, ciphertext=b"PRIVATE INVALID ENVELOPE")
    assert_private(lambda: repo.stage(broken), "preparation_custody_authentication")
    conn.cursor.assert_not_called()
    holds.load.assert_not_called()


def test_driver_error_is_redacted_and_poisoned(retained, cipher, monkeypatch):
    sealed, repo, conn, cursor, holds = repository_case(retained, cipher, monkeypatch)
    cursor.execute.side_effect = RuntimeError("PRIVATE driver credentials and XML")
    assert_private(lambda: repo.load(sealed.hold_id), "preparation_custody_storage")
    assert_private(lambda: repo.load(sealed.hold_id), "preparation_custody_transaction_unusable")
