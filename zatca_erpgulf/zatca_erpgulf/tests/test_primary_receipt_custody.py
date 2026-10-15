"""Synthetic encrypted receipt custody; no site/config/HTTP discovery."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import inspect
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pytest

from zatca_erpgulf.zatca_erpgulf import primary_receipt_custody as custody
from zatca_erpgulf.zatca_erpgulf.tests.test_primary_receipt_persistence import prepared, retained
from zatca_erpgulf.zatca_erpgulf.tests.test_certificate_evidence import certificates
from zatca_erpgulf.zatca_erpgulf.tests.test_journal_repository import NAMESPACE


KEY = b"C" * 32  # Generated-fixture domain only, never deployment material.
OTHER_NAMESPACE = "50000000-0000-4000-8000-000000000001"


def cipher():
    return custody.PrimaryReceiptCustodyCipher({"synthetic-custody": KEY})


def seal(receipt):
    return cipher().seal(receipt, key_id="synthetic-custody")


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("status", [200, 202, 303, 400, 401, 403, 406, 409, 500])
@pytest.mark.parametrize("body", [b"", b' {"synthetic":"observation only"}\n', b"\x00\xffNOT JSON\r\n"])
def test_exact_codec_and_cipher_preserve_all_receipt_observations(prepared, unknown, status, body):
    receipt = retained(prepared, unknown=unknown, status=status, body=body)
    encoded = custody.encode_retained_receipt(receipt)
    recovered = custody.decode_retained_receipt(encoded)
    assert recovered == receipt and recovered is not receipt
    assert recovered.before.candidate.xml_bytes == prepared.xml_bytes
    assert recovered.response_event.response_bytes == body
    sealed = seal(receipt)
    assert cipher().open(sealed) == receipt
    assert sealed.receipt_sha256 == hashlib.sha256(encoded).hexdigest()
    assert encoded not in sealed.ciphertext
    assert len(sealed.ciphertext) == len(encoded) + 16
    assert recovered.before.diagnostic_projection()["replay_authorized"] is False


@pytest.mark.parametrize("fault", ["none", "text", "bytearray", "magic", "version", "header", "truncated", "trailing", "oversize"])
def test_malformed_payload_is_static_unchained_and_bounded(prepared, fault):
    encoded = custody.encode_retained_receipt(retained(prepared))
    value = {"none": None, "text": "PRIVATE", "bytearray": bytearray(encoded),
        "magic": b"PRIVATE" + encoded, "version": encoded.replace(custody.MAGIC, custody.MAGIC[:-1] + b"\x02", 1),
        "header": custody.MAGIC + b"\xff" * 4, "truncated": encoded[:-1], "trailing": encoded + b"PRIVATE",
        "oversize": b"x" * (custody.MAX_CUSTODY_BYTES + 1)}[fault]
    with pytest.raises(custody.PrimaryReceiptCustodyError, match="^receipt_custody_payload$") as error:
        custody.decode_retained_receipt(value)
    assert error.value.__context__ is None


@pytest.mark.parametrize("frame", range(7))
@pytest.mark.parametrize("fault", ["length", "content"])
def test_each_frame_is_validated_and_never_silently_normalized(prepared, frame, fault):
    encoded = bytearray(custody.encode_retained_receipt(retained(prepared, unknown=True)))
    offset = len(custody.MAGIC)
    for index in range(7):
        size = int.from_bytes(encoded[offset:offset + 4], "big")
        if index == frame:
            if fault == "length":
                encoded[offset:offset + 4] = (custody.FRAME_BOUNDS[index] + 1).to_bytes(4, "big")
            else:
                if frame == 0:
                    encoded[offset + 4] = 255  # Not a different structurally valid UUID.
                else:
                    encoded[offset + 4] ^= 1
            break
        offset += 4 + size
    with pytest.raises(custody.PrimaryReceiptCustodyError):
        custody.decode_retained_receipt(bytes(encoded))


@pytest.mark.parametrize("field,value", [("storage_namespace", OTHER_NAMESPACE), ("candidate_sha256", "0" * 64),
    ("attempt_id", OTHER_NAMESPACE), ("predecessor_sha256", "0" * 64), ("receipt_sha256", "0" * 64),
    ("key_id", "other-key"), ("nonce", b"0" * 12), ("ciphertext", b"0" * 20)])
def test_aad_and_ciphertext_tampering_is_rejected_without_raw_context(prepared, field, value):
    sealed = replace(seal(retained(prepared)), **{field: value})
    with pytest.raises(custody.PrimaryReceiptCustodyError, match="^receipt_custody_authentication$") as error:
        cipher().open(sealed)
    assert error.value.__context__ is None


@pytest.mark.parametrize("field,value", [("storage_namespace", OTHER_NAMESPACE), ("candidate_sha256", "0" * 64),
    ("attempt_id", OTHER_NAMESPACE), ("predecessor_sha256", "0" * 64), ("receipt_sha256", "0" * 64)])
def test_even_authenticated_payload_must_match_exact_envelope_declarations(prepared, field, value):
    receipt = retained(prepared)
    sealed = replace(seal(receipt), **{field: value})
    metadata = {name: getattr(sealed, name) for name in custody.AAD_FIELDS}
    forged = replace(sealed, ciphertext=AESGCM(KEY).encrypt(sealed.nonce,
        custody.encode_retained_receipt(receipt), custody._aad(metadata)))
    with pytest.raises(custody.PrimaryReceiptCustodyError, match="receipt_custody_authentication"):
        cipher().open(forged)


@pytest.mark.parametrize("fault", ["wrong-key", "malformed-plaintext", "different-domain", "unknown-key"])
def test_authentication_never_falls_back_to_another_key_or_codec(prepared, fault):
    sealed = seal(retained(prepared))
    selected = cipher()
    if fault == "wrong-key":
        selected = custody.PrimaryReceiptCustodyCipher({sealed.key_id: b"D" * 32})
    elif fault == "unknown-key":
        selected = custody.PrimaryReceiptCustodyCipher({"another-id": KEY})
    else:
        metadata = {name: getattr(sealed, name) for name in custody.AAD_FIELDS}
        content = b"PRIVATE invalid receipt" if fault == "malformed-plaintext" else custody.encode_retained_receipt(retained(prepared))
        aad = custody._aad(metadata) if fault == "malformed-plaintext" else b"another-domain/v1\0"
        sealed = replace(sealed, ciphertext=AESGCM(KEY).encrypt(sealed.nonce, content, aad))
    with pytest.raises(custody.PrimaryReceiptCustodyError) as error:
        selected.open(sealed)
    assert error.value.__context__ is None and "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("keys", [None, {}, {"id": b"x"}, {"bad key": KEY}, {"a": KEY, "b": KEY}])
def test_bad_keyrings_are_static_and_no_key_discovery_is_attempted(keys):
    with pytest.raises(custody.PrimaryReceiptCustodyError, match="^receipt_custody_keyring$") as error:
        custody.PrimaryReceiptCustodyCipher(keys)
    assert error.value.__context__ is None


def repository_case(monkeypatch, receipt, *, existing=None):
    sealed = seal(receipt)
    cursor = Mock()
    cursor.__enter__, cursor.__exit__ = Mock(return_value=cursor), Mock(return_value=False)
    case = SimpleNamespace(receipt=receipt, sealed=sealed, row=sealed if existing is None else existing,
        current=receipt.before, autocommit=(0,), cursor=cursor)
    case.connection = SimpleNamespace(cursor=Mock(return_value=cursor), commit=Mock(), rollback=Mock(), close=Mock())
    def execute(sql, values=None):
        if sql == "SELECT @@session.autocommit":
            cursor.fetchone.return_value = case.autocommit
        elif sql.startswith("INSERT INTO zatca_primary_receipt_custody_v1"):
            assert values == tuple(getattr(sealed, name) for name in (*custody.AAD_FIELDS, "nonce", "ciphertext"))
        elif sql.startswith("SELECT predecessor_sha256"):
            assert values == (custody.MAX_CUSTODY_BYTES + 17, receipt.storage_namespace, sealed.candidate_sha256, sealed.attempt_id)
            cursor.fetchone.return_value = None if case.row is False else tuple(getattr(case.row, name) for name in
                ("predecessor_sha256", "receipt_sha256", "key_id", "nonce", "ciphertext"))
        else:
            raise AssertionError("Unreviewed SQL")
    cursor.execute.side_effect = execute
    case.journal = Mock()
    case.journal.load.side_effect = lambda key: case.current
    case.journal_factory = Mock(return_value=case.journal)
    monkeypatch.setattr(custody, "MariaDBJournalRepository", case.journal_factory)
    case.repository = custody.MariaDBPrimaryReceiptCustodyRepository(case.connection, receipt.storage_namespace, cipher())
    return case


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("stored_after", [False, True])
def test_custody_requires_existing_exact_journal_but_never_appends_or_commits(prepared, monkeypatch, unknown, stored_after):
    case = repository_case(monkeypatch, retained(prepared, unknown=unknown))
    if stored_after:
        case.current = custody._validate_retained(case.receipt)
    assert case.repository.stage(case.sealed) == case.sealed
    assert case.repository.load(case.sealed.candidate_sha256, case.sealed.attempt_id) == case.sealed
    case.journal.load.assert_called_once_with(case.sealed.candidate_sha256)
    case.journal.append.assert_not_called()
    case.connection.commit.assert_not_called()
    case.connection.rollback.assert_not_called()
    case.connection.close.assert_not_called()


@pytest.mark.parametrize("fault", ["different-journal", "missing", "resealed", "autocommit", "bool-autocommit", "sql", "interrupt"])
def test_repository_failure_poisoning_never_retries_changes_or_cleans_caller_transaction(prepared, monkeypatch, fault):
    receipt = retained(prepared)
    case = repository_case(monkeypatch, receipt)
    exception = custody.PrimaryReceiptCustodyError
    if fault == "different-journal":
        case.current = custody.DispatchJournal(prepared)
    elif fault == "missing":
        case.row = False
    elif fault == "resealed":
        case.row = seal(receipt)
    elif fault in ("autocommit", "bool-autocommit"):
        case.autocommit = (1,) if fault == "autocommit" else (False,)
    else:
        exception = KeyboardInterrupt if fault == "interrupt" else custody.PrimaryReceiptCustodyError
        case.cursor.execute.side_effect = KeyboardInterrupt() if fault == "interrupt" else RuntimeError("PRIVATE SQL")
    with pytest.raises(exception) as error:
        case.repository.stage(case.sealed)
    if fault != "interrupt":
        assert error.value.__context__ is None and "PRIVATE" not in str(error.value)
    calls = case.cursor.execute.call_count
    with pytest.raises(custody.PrimaryReceiptCustodyError, match="transaction_unusable"):
        case.repository.load(case.sealed.candidate_sha256, case.sealed.attempt_id)
    assert case.cursor.execute.call_count == calls
    for method in (case.connection.commit, case.connection.rollback, case.connection.close):
        method.assert_not_called()


@pytest.mark.parametrize("fault", ["scope", "authentication", "type", "frozen-tampering"])
def test_bad_envelopes_do_not_acquire_sql(prepared, monkeypatch, fault):
    case = repository_case(monkeypatch, retained(prepared))
    sealed = case.sealed
    if fault == "scope":
        sealed = seal(retained(prepared, namespace=OTHER_NAMESPACE))
    elif fault == "authentication":
        sealed = replace(sealed, ciphertext=b"X" * 20)
    elif fault == "type":
        sealed = {"PRIVATE": True}
    else:
        object.__setattr__(sealed, "nonce", b"BAD")
    with pytest.raises(custody.PrimaryReceiptCustodyError):
        case.repository.stage(sealed)
    case.connection.cursor.assert_not_called()


@pytest.mark.parametrize("key,attempt", [(None, OTHER_NAMESPACE), ("0" * 64, "BAD"), ({}, None)])
def test_invalid_explicit_selection_cannot_query_anything(prepared, monkeypatch, key, attempt):
    case = repository_case(monkeypatch, retained(prepared))
    with pytest.raises(custody.PrimaryReceiptCustodyError) as error:
        case.repository.load(key, attempt)
    assert error.value.__context__ is None
    case.connection.cursor.assert_not_called()


def test_keyring_is_copied_and_envelopes_services_are_redacted_and_nonpickleable(prepared):
    keys = {"synthetic-custody": KEY}
    selected = custody.PrimaryReceiptCustodyCipher(keys)
    sealed = selected.seal(retained(prepared), key_id="synthetic-custody")
    keys.clear()
    assert selected.open(sealed) == retained(prepared)
    for value in (sealed, selected, custody.MariaDBPrimaryReceiptCustodyRepository(None, NAMESPACE, selected)):
        assert "TEST" not in repr(value) and NAMESPACE not in repr(value) and "synthetic-custody" not in repr(value)
        with pytest.raises(custody.PrimaryReceiptCustodyError, match="not_pickleable"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        sealed.ciphertext = b"REPLACE"


def test_plain_codec_is_not_an_authentication_claim(prepared):
    receipt = retained(prepared)
    encoded = custody.encode_retained_receipt(receipt)
    altered = encoded.replace(NAMESPACE.encode("ascii"), OTHER_NAMESPACE.encode("ascii"), 1)
    assert custody.decode_retained_receipt(altered).storage_namespace == OTHER_NAMESPACE
    # Structural validity alone cannot authenticate namespace/origin. The cipher
    # tests above reject AAD/payload rebinding, even with valid plaintext shapes.


def test_retrieval_does_not_reinterpret_current_journal_or_release_replay_rights(prepared, monkeypatch):
    case = repository_case(monkeypatch, retained(prepared))
    case.journal.load.side_effect = AssertionError("Custody load must not consult today's journal")
    sealed = case.repository.load(case.sealed.candidate_sha256, case.sealed.attempt_id)
    assert cipher().open(sealed) == case.receipt
    case.journal_factory.assert_not_called()
    assert case.receipt.before.diagnostic_projection()["dispatch_authorized"] is False


def test_no_runtime_activation_transport_discovery_schema_or_transaction_ownership():
    source = inspect.getsource(custody)
    for forbidden in ("import frappe", "import requests", "@frappe.whitelist", "CREATE TABLE", "DELETE FROM",
        "get_site_config", ".commit(", ".rollback(", ".close(", "utcnow(", "get_doc(", "get_password("):
        assert forbidden not in source
