"""Generated ephemeral audit material; no site, key file, live SQL or HTTP."""

import hashlib
import json
import pickle
import secrets
from dataclasses import FrozenInstanceError, replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf import compliance_archive as archive
from zatca_erpgulf.zatca_erpgulf.compliance_archive_repository import MariaDBComplianceArchiveRepository
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import STEP_CLASSIFICATION
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_bundle import cipher, record, connection, NAMESPACE, VERSION, NOW
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import materials, requirements, exchange
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import basic


@pytest.fixture
def archive_cipher():
    return archive.ComplianceArchiveCipher({"audit-test": secrets.token_bytes(32)})


def observations(material, cipher, *, environment="Production", step="SIMPLIFIED", status=200, **changes):
    req, bundle = requirements(material, cipher, environment=environment)
    receipt = exchange(req, material, step=step, status=status, **changes)
    start = replace(receipt, http_status=None, response_bytes=None, received_at=None)
    return bundle, start, receipt


def envelopes(archive_cipher, start, receipt):
    return (archive_cipher.seal(start, sequence=1, key_id="audit-test"),
            archive_cipher.seal(receipt, sequence=2, key_id="audit-test"))


def archive_record(sealed):
    return (sealed.version_id, sealed.manifest_sha256, sealed.observation_sha256,
            sealed.key_id, sealed.nonce, sealed.ciphertext)


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("step", list(STEP_CLASSIFICATION))
@pytest.mark.parametrize("status", [200, 202, 406, 401])
def test_exact_encrypted_start_receipt_roundtrip_all_types_and_environments(materials, cipher, archive_cipher, environment, step, status):
    bundle, start, receipt = observations(materials[0], cipher, environment=environment, step=step, status=status)
    left, right = envelopes(archive_cipher, start, receipt)
    assert archive_cipher.open(left) == start and archive_cipher.open(right) == receipt
    assert archive.decode_observation(archive.encode_observation(receipt)) == receipt
    history = archive.ComplianceArchiveHistory(start, receipt)
    assert history.current_observation == receipt
    report = history.diagnostic_projection()
    assert all(value is False for name, value in report.items() if name.endswith(("_verified", "_authorized")))
    for private in (materials[0].pem, materials[0].text, basic(materials[0]), "gw-fatoora", "PRIVATE-CSR-SUBJECT"):
        assert private not in json.dumps(report) + repr(history) + repr(left) + repr(right) + repr(archive_cipher)
    for private in (receipt.request_bytes, receipt.response_bytes, receipt.requirements.csr_der):
        assert private not in right.ciphertext
    assert left.manifest_sha256 == hashlib.sha256(bundle.manifest_bytes).hexdigest()


@pytest.mark.parametrize("status", [200, 401, 500])
def test_empty_body_and_absent_response_remain_distinct(materials, cipher, archive_cipher, status):
    _, start, receipt = observations(materials[0], cipher, status=status, response_bytes=b"")
    left, right = envelopes(archive_cipher, start, receipt)
    assert archive_cipher.open(left).response_bytes is None
    assert archive_cipher.open(right).response_bytes == b""
    assert archive_cipher.open(right).outcome != "PASS_MATCHED_OBSERVATION"


@pytest.mark.parametrize("field,value", [("storage_namespace", str(uuid4())), ("exchange_id", str(uuid4())),
    ("version_id", str(uuid4())), ("sequence", 2), ("manifest_sha256", "0" * 64),
    ("observation_sha256", "0" * 64), ("key_id", "rotated"), ("nonce", b"x" * 12)])
def test_every_public_binding_is_authenticated(materials, cipher, field, value):
    key = secrets.token_bytes(32)
    protected = archive.ComplianceArchiveCipher({"audit-test": key, "rotated": secrets.token_bytes(32)})
    _, start, receipt = observations(materials[0], cipher)
    sealed, _ = envelopes(protected, start, receipt)
    with pytest.raises(archive.ComplianceArchiveError, match="archive_authentication"):
        protected.open(replace(sealed, **{field: value}))


def test_ciphertext_corruption_missing_key_rotation_and_resealing(materials, cipher):
    old_key, new_key = secrets.token_bytes(32), secrets.token_bytes(32)
    old = archive.ComplianceArchiveCipher({"audit-test": old_key})
    rotated = archive.ComplianceArchiveCipher({"audit-test": old_key, "next": new_key})
    _, start, receipt = observations(materials[0], cipher)
    sealed, _ = envelopes(old, start, receipt)
    assert rotated.open(sealed) == start
    assert old.seal(start, sequence=1, key_id="audit-test") != sealed
    with pytest.raises(archive.ComplianceArchiveError, match="archive_key_unavailable"):
        archive.ComplianceArchiveCipher({"next": new_key}).open(sealed)
    damaged = replace(sealed, ciphertext=sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1]))
    with pytest.raises(archive.ComplianceArchiveError, match="archive_authentication"):
        rotated.open(damaged)


def frames(content):
    offset, result = len(archive.MAGIC), []
    while offset < len(content):
        size = int.from_bytes(content[offset:offset + 4], "big")
        offset += 4
        result.append(content[offset:offset + size])
        offset += size
    return result


def framed(parts):
    return archive.MAGIC + b"".join(len(part).to_bytes(4, "big") + part for part in parts)


@pytest.mark.parametrize("change", ["magic", "truncated", "trailing", "huge_frame", "duplicate_header", "header_fields",
    "schema", "has_response", "route", "noncanonical_header", "csr", "request", "response_presence", "timestamp"])
def test_strict_framed_codec_rejects_corruption_without_private_errors(materials, cipher, change):
    _, start, receipt = observations(materials[0], cipher)
    wire = archive.encode_observation(start if change == "response_presence" else receipt)
    parts = frames(wire)
    header = json.loads(parts[0])
    if change == "magic":
        wire = b"BAD" + wire
    elif change == "truncated":
        wire = wire[:-1]
    elif change == "trailing":
        wire += b"PRIVATE-SECRET"
    elif change == "huge_frame":
        wire = archive.MAGIC + b"\xff" * 4
    elif change == "duplicate_header":
        parts[0] = b'{"schema_version":1,"schema_version":1}'
        wire = framed(parts)
    elif change in ("csr", "request"):
        parts[1 if change == "csr" else 2] = b"PRIVATE-SECRET"
        wire = framed(parts)
    elif change == "response_presence":
        parts[3] = b"PRIVATE-SECRET"
        wire = framed(parts)
    elif change == "noncanonical_header":
        parts[0] += b" "
        wire = framed(parts)
    else:
        if change == "header_fields":
            header["activation_authorized"] = True
        elif change == "schema":
            header["schema_version"] = True
        elif change == "has_response":
            header["has_response"] = "yes"
        elif change == "route":
            header["route"]["extra"] = "PRIVATE-SECRET"
        else:
            header["started_at"] = "PRIVATE-SECRET"
        parts[0] = archive._json(header)
        wire = framed(parts)
    with pytest.raises(archive.ComplianceArchiveError) as error:
        archive.decode_observation(wire)
    assert "PRIVATE-SECRET" not in str(error.value)


@pytest.mark.parametrize("changed", ["stage", "exchange_id", "version", "hash"])
def test_authenticated_payload_still_rehydrates_and_rechecks_outer_identity(materials, cipher, changed):
    key = secrets.token_bytes(32)
    protected = archive.ComplianceArchiveCipher({"audit-test": key})
    _, start, receipt = observations(materials[0], cipher)
    sealed, _ = envelopes(protected, start, receipt)
    if changed == "stage":
        forged = replace(sealed, sequence=2)
    elif changed == "exchange_id":
        forged = replace(sealed, exchange_id=str(uuid4()))
    elif changed == "version":
        forged = replace(sealed, version_id=str(uuid4()))
    else:
        forged = replace(sealed, observation_sha256="0" * 64)
    ciphertext = AESGCM(key).encrypt(forged.nonce, archive.encode_observation(start), forged.aad())
    with pytest.raises(archive.ComplianceArchiveError, match="archive_binding"):
        protected.open(replace(forged, ciphertext=ciphertext))


@pytest.mark.parametrize("change", ["id", "started_at", "request", "requirements", "start_as_receipt", "receipt_as_start"])
def test_receipt_must_match_the_exact_prepared_request(materials, cipher, change):
    _, start, receipt = observations(materials[0], cipher)
    if change == "id":
        receipt = replace(receipt, exchange_id=str(uuid4()))
    elif change == "started_at":
        receipt = replace(receipt, started_at=NOW)
    elif change == "request":
        receipt = replace(receipt, request_bytes=receipt.request_bytes + b" ")
    elif change == "requirements":
        receipt = replace(receipt, requirements=replace(receipt.requirements,
            manifest=replace(receipt.requirements.manifest, compliance_request_id="OTHER_REQUEST")))
    elif change == "start_as_receipt":
        receipt = start
    else:
        start = receipt
    with pytest.raises(archive.ComplianceArchiveError):
        archive.ComplianceArchiveHistory(start, receipt)


@pytest.mark.parametrize("sequence,status", [(1, 200), (2, None), (True, None), (0, None), (3, 200)])
def test_stage_semantics_are_not_caller_verification_flags(materials, cipher, archive_cipher, sequence, status):
    _, start, receipt = observations(materials[0], cipher)
    with pytest.raises(archive.ComplianceArchiveError):
        archive_cipher.seal(start if status is None else receipt, sequence=sequence, key_id="audit-test")


@pytest.mark.parametrize("keys", [None, {}, {"bad key": b"x" * 32}, {"key": b"short"},
    {"a": b"x" * 32, "b": b"x" * 32}, {"key": "x" * 32}])
def test_archive_keyring_has_no_defaults_or_duplicate_key_aliases(keys):
    with pytest.raises(archive.ComplianceArchiveError, match="archive_keyring"):
        archive.ComplianceArchiveCipher(keys)


def test_start_and_receipt_sql_contain_only_ciphertext_and_public_references(materials, cipher, archive_cipher):
    bundle, start, receipt = observations(materials[0], cipher)
    left, right = envelopes(archive_cipher, start, receipt)
    database, cursor = connection([(0,), record(bundle), archive_record(left),
                                   (0,), record(bundle), archive_record(left), archive_record(right)])
    repository = MariaDBComplianceArchiveRepository(database, NAMESPACE, cipher, archive_cipher)
    assert repository.prepare(left) == left
    assert repository.append_receipt(right) == right
    inserts = [call for call in cursor.execute.call_args_list if call.args[0].startswith("INSERT")]
    assert len(inserts) == 2
    for call in inserts:
        assert all(private not in repr(call.args[1]) for private in (
            materials[0].pem, materials[0].text, basic(materials[0]), "gw-fatoora", "PRIVATE-CSR-SUBJECT"))
        assert call.args[1][-1] in (left.ciphertext, right.ciphertext)
    database.commit.assert_not_called()
    database.rollback.assert_not_called()


@pytest.mark.parametrize("with_receipt", [True, False])
def test_load_explicit_version_attempt_recovers_history_without_http_or_commits(materials, cipher, archive_cipher, with_receipt):
    bundle, start, receipt = observations(materials[0], cipher)
    left, right = envelopes(archive_cipher, start, receipt)
    database, _ = connection([(0,), record(bundle), archive_record(left), archive_record(right) if with_receipt else None])
    repository = MariaDBComplianceArchiveRepository(database, NAMESPACE, cipher, archive_cipher)
    history = repository.load(bundle.manifest.slot, VERSION, start.exchange_id)
    assert history.start == start and history.receipt == (receipt if with_receipt else None)
    assert history.current_observation == (receipt if with_receipt else start)
    database.commit.assert_not_called()


@pytest.mark.parametrize("change", ["namespace", "stage", "ciphertext", "version", "missing_start", "changed_start", "resealed", "autocommit", "bad_row", "driver"])
def test_repository_failure_poison_requires_whole_transaction_rollback(materials, cipher, archive_cipher, change):
    bundle, start, receipt = observations(materials[0], cipher)
    left, right = envelopes(archive_cipher, start, receipt)
    rows = [(0,), record(bundle), archive_record(left), archive_record(right)]
    if change == "namespace":
        right = replace(right, storage_namespace=str(uuid4()))
    elif change == "stage":
        right = left
    elif change == "ciphertext":
        right = replace(right, ciphertext=right.ciphertext[:-1] + bytes([right.ciphertext[-1] ^ 1]))
    elif change == "version":
        altered = replace(bundle.manifest, compliance_request_id="OTHER_REQUEST")
        bundle = replace(bundle, manifest_bytes=altered.encode())
        rows[1] = record(bundle)
    elif change == "missing_start":
        rows[2] = None
    elif change == "changed_start":
        other = replace(start, request_bytes=start.request_bytes + b" ")
        rows[2] = archive_record(archive_cipher.seal(other, sequence=1, key_id="audit-test"))
    elif change == "resealed":
        rows[3] = archive_record(archive_cipher.seal(receipt, sequence=2, key_id="audit-test"))
    elif change == "autocommit":
        rows[0] = (1,)
    elif change == "bad_row":
        rows[2] = ("bad",)
    database, cursor = connection(rows)
    if change == "driver":
        cursor.execute.side_effect = RuntimeError("PRIVATE-SECRET driver details")
    repository = MariaDBComplianceArchiveRepository(database, NAMESPACE, cipher, archive_cipher)
    with pytest.raises(archive.ComplianceArchiveError) as error:
        repository.append_receipt(right)
    assert "PRIVATE-SECRET" not in str(error.value)
    with pytest.raises(archive.ComplianceArchiveError, match="archive_transaction_unusable"):
        repository.prepare(left)
    database.commit.assert_not_called()


@pytest.mark.parametrize("field,value", [("nonce", b"short"), ("ciphertext", b"short"),
    ("sequence", True), ("version_id", "latest"), ("key_id", "bad key"), ("manifest_sha256", "bad")])
def test_sealed_record_is_bounded_and_typed(materials, cipher, archive_cipher, field, value):
    _, start, receipt = observations(materials[0], cipher)
    left, _ = envelopes(archive_cipher, start, receipt)
    with pytest.raises(archive.ComplianceArchiveError):
        replace(left, **{field: value})


def test_dedicated_key_domains_cannot_reuse_bundle_key_material_under_another_id():
    key = secrets.token_bytes(32)
    with pytest.raises(archive.ComplianceArchiveError, match="archive_key_domain_reuse"):
        MariaDBComplianceArchiveRepository(Mock(), NAMESPACE, CredentialBundleCipher({"bundle": key}),
                                           archive.ComplianceArchiveCipher({"archive": key}))


def test_private_objects_cannot_be_pickled_or_mutated(materials, cipher, archive_cipher):
    _, start, receipt = observations(materials[0], cipher)
    left, _ = envelopes(archive_cipher, start, receipt)
    history = archive.ComplianceArchiveHistory(start, receipt)
    repository = MariaDBComplianceArchiveRepository(Mock(), NAMESPACE, cipher, archive_cipher)
    for value in (archive_cipher, left, history, repository):
        with pytest.raises(archive.ComplianceArchiveError, match="archive_not_pickleable"):
            pickle.dumps(value)
    with pytest.raises(FrozenInstanceError):
        history.receipt = None


def test_sql_ciphertext_bound_matches_codec():
    from pathlib import Path
    schema = Path(__file__).resolve().parents[3] / "docs/zatca_unification/compliance_archive_rehearsal.sql"
    assert f"BETWEEN 17 AND {archive.MAX_ARCHIVE_BYTES + 16}" in schema.read_text()


@pytest.mark.parametrize("operation", ["encode", "decode", "seal", "open"])
def test_non_observation_inputs_never_become_protected_records(archive_cipher, operation):
    with pytest.raises(archive.ComplianceArchiveError):
        if operation == "encode":
            archive.encode_observation({"activation_authorized": True})
        elif operation == "decode":
            archive.decode_observation("PRIVATE-SECRET")
        elif operation == "seal":
            archive_cipher.seal({}, sequence=1, key_id="audit-test")
        else:
            archive_cipher.open(None)


def test_invalid_preflight_poison_does_not_touch_sql(cipher, archive_cipher):
    database = Mock()
    repository = MariaDBComplianceArchiveRepository(database, NAMESPACE, cipher, archive_cipher)
    with pytest.raises(archive.ComplianceArchiveError):
        repository.prepare(None)
    with pytest.raises(archive.ComplianceArchiveError, match="archive_transaction_unusable"):
        repository.prepare(None)
    database.cursor.assert_not_called()
    database.commit.assert_not_called()


def test_codec_cipher_never_discover_files_or_contact_http(materials, cipher, archive_cipher, monkeypatch):
    import builtins
    import requests

    _, start, receipt = observations(materials[0], cipher)
    def forbidden(*args, **kwargs):
        raise AssertionError("No file/key/HTTP discovery is permitted")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    left, right = envelopes(archive_cipher, start, receipt)
    assert archive_cipher.open(left) == start and archive_cipher.open(right) == receipt
