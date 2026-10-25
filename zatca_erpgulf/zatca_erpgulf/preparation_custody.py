"""Dedicated encrypted custody of an exact preparation original, uninstalled.

No authority transport, key discovery, schema setup, commit or hold release.
Plain codecs preserve exact XML; AES-GCM authenticates storage declarations,
NOT invoice signatures, enrollment, tenant provenance or remote acceptance.
"""

from dataclasses import dataclass, field
import hashlib
import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .artifact_evidence import MAX_XML_BYTES
from .credential_bundle import _key_id, copy_storage_keys
from .credential_bundle_access import CredentialStorageScope
from .custody_frames import decode_frames, encode_frames
from .issuance_candidate import _canonical_uuid, _sha256
from .journal_storage import MAX_CONTEXT_BYTES, decode_candidate_context, encode_candidate_context
from .preparation_hold import (
    MAX_TICKET_BYTES, MariaDBPreparationHoldRepository, PreparationHold,
    decode_preparation_ticket, encode_preparation_ticket,
)
from .preparation_recovery_access import RetainedPreparationOriginal, _validated_parts


MAGIC = b"ZATCA-PREPARATION-ORIGINAL-CUSTODY\x00\x01"
FRAME_BOUNDS = (255, 36, 36, MAX_TICKET_BYTES, 64, MAX_CONTEXT_BYTES, MAX_XML_BYTES)
MAX_CUSTODY_BYTES = len(MAGIC) + 4 * len(FRAME_BOUNDS) + sum(FRAME_BOUNDS)
AAD_FIELDS = ("site", "storage_namespace", "hold_id", "ticket_sha256", "candidate_sha256",
              "manifest_sha256", "payload_sha256", "key_id")


class PreparationCustodyError(ValueError):
    """Static code only, no plaintext/driver/key/source disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def encode_preparation_original(retained):
    try:
        _validated_parts(retained)
        parts = (retained.scope.site.encode("ascii"), retained.scope.storage_namespace.encode("ascii"),
            retained.hold.hold_id.encode("ascii"), encode_preparation_ticket(retained.hold.ticket),
            (retained.hold.original_manifest_sha256 or "").encode("ascii"),
            encode_candidate_context(retained.candidate), retained.candidate.xml_bytes)
        content = encode_frames(MAGIC, FRAME_BOUNDS, parts)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PreparationCustodyError("preparation_custody_input")
    return content


def decode_preparation_original(content):
    try:
        site, namespace, hold_id, ticket, completed, context, xml = decode_frames(MAGIC, FRAME_BOUNDS, content)
        retained = RetainedPreparationOriginal(
            CredentialStorageScope(site.decode("ascii"), namespace.decode("ascii")),
            PreparationHold(hold_id.decode("ascii"), decode_preparation_ticket(ticket),
                completed.decode("ascii") if completed else None),
            decode_candidate_context(context, xml))
        if encode_preparation_original(retained) != content:
            raise ValueError
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PreparationCustodyError("preparation_custody_payload")
    return retained


def _metadata(retained, key_id, payload):
    return dict(site=retained.scope.site, storage_namespace=retained.scope.storage_namespace,
        hold_id=retained.hold.hold_id, ticket_sha256=retained.hold.ticket_sha256,
        candidate_sha256=retained.candidate.key_sha256, manifest_sha256=retained.candidate.manifest_sha256,
        payload_sha256=hashlib.sha256(payload).hexdigest(), key_id=key_id)


def _aad(metadata):
    return b"zatca-preparation-original-custody/v1\0" + json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


@dataclass(frozen=True, repr=False)
class SealedPreparationOriginal:
    """Protected exact envelope, not a log/UI/queue payload or commit receipt."""

    site: str
    storage_namespace: str
    hold_id: str
    ticket_sha256: str
    candidate_sha256: str
    manifest_sha256: str
    payload_sha256: str
    key_id: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)

    def __post_init__(self):
        try:
            CredentialStorageScope(self.site, self.storage_namespace)
            _canonical_uuid(self.hold_id, "preparation_custody_hold")
            for value in (self.ticket_sha256, self.candidate_sha256, self.manifest_sha256, self.payload_sha256):
                _sha256(value, "preparation_custody_fingerprint")
            _key_id(self.key_id)
            if (type(self.nonce) is not bytes or len(self.nonce) != 12 or type(self.ciphertext) is not bytes
                or not 16 < len(self.ciphertext) <= MAX_CUSTODY_BYTES + 16):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PreparationCustodyError("preparation_custody_envelope")

    def __repr__(self):
        return "<SealedPreparationOriginal protected exact encrypted custody>"

    def __reduce__(self):
        raise PreparationCustodyError("preparation_custody_not_pickleable")


class PreparationOriginalCipher:
    """Dedicated supplied AES-256-GCM keyring, NOT an installed vault.

    Provision independent keys from signing, credential and receipt domains.
    AAD alone cannot prevent cross-domain nonce reuse. Key rotation, volume,
    off-host recovery and authenticated key-provider provenance remain audits.
    """

    def __init__(self, keys):
        try:
            self._keys = copy_storage_keys(keys)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PreparationCustodyError("preparation_custody_keyring")

    def __repr__(self):
        return "<PreparationOriginalCipher protected dedicated keys>"

    def __reduce__(self):
        raise PreparationCustodyError("preparation_custody_not_pickleable")

    def seal(self, retained, *, key_id):
        content = encode_preparation_original(retained)
        try:
            _key_id(key_id)
            metadata = _metadata(retained, key_id, content)
            nonce = secrets.token_bytes(12)
            sealed = SealedPreparationOriginal(**metadata, nonce=nonce,
                ciphertext=AESGCM(self._keys[key_id]).encrypt(nonce, content, _aad(metadata)))
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PreparationCustodyError("preparation_custody_seal")
        return sealed

    def open(self, sealed):
        try:
            if type(sealed) is not SealedPreparationOriginal:
                raise ValueError
            sealed.__post_init__()
            metadata = {name: getattr(sealed, name) for name in AAD_FIELDS}
            content = AESGCM(self._keys[sealed.key_id]).decrypt(sealed.nonce, sealed.ciphertext, _aad(metadata))
            retained = decode_preparation_original(content)
            if _metadata(retained, sealed.key_id, content) != metadata:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PreparationCustodyError("preparation_custody_authentication")
        return retained


def sealed_preparation_sha256(sealed):
    """Protected exact-envelope binding; not a plaintext/custody-origin proof."""
    if type(sealed) is not SealedPreparationOriginal:
        raise PreparationCustodyError("preparation_custody_envelope")
    sealed.__post_init__()
    header = _aad({name: getattr(sealed, name) for name in AAD_FIELDS})
    return hashlib.sha256(len(header).to_bytes(4, "big") + header + sealed.nonce + sealed.ciphertext).hexdigest()


class MariaDBPreparationCustodyRepository:
    """Caller-transaction immutable ciphertext for ONE existing exact hold.

    Stage does NOT complete a hold or require a journal original to exist.
    Load is protected historical retrieval, not normal ACL or replay authority.
    Failed handles require whole caller rollback; no overwrite/delete/reseal.
    """

    def __init__(self, connection, storage_namespace, cipher):
        try:
            _canonical_uuid(storage_namespace, "preparation_custody_namespace")
            if type(cipher) is not PreparationOriginalCipher:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PreparationCustodyError("preparation_custody_dependencies")
        self._connection, self._namespace, self._cipher = connection, storage_namespace, cipher
        self._failed = False

    def __repr__(self):
        return "<MariaDBPreparationCustodyRepository protected explicit transaction>"

    def __reduce__(self):
        raise PreparationCustodyError("preparation_custody_not_pickleable")

    def _operation(self, work):
        if self._failed:
            raise PreparationCustodyError("preparation_custody_transaction_unusable")
        code = None
        try:
            result = work()
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
            code = error.code if type(error) is PreparationCustodyError else "preparation_custody_storage"
        if code is not None:
            raise PreparationCustodyError(code)
        return result

    @staticmethod
    def _transaction(cursor):
        cursor.execute("SELECT @@session.autocommit")
        row = cursor.fetchone()
        if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int or row != (0,):
            raise PreparationCustodyError("preparation_custody_autocommit")

    def stage(self, sealed):
        def work():
            retained = self._cipher.open(sealed)
            if sealed.storage_namespace != self._namespace:
                raise PreparationCustodyError("preparation_custody_scope")
            # Preserve source -> chain -> hold -> ciphertext lock order.
            MariaDBPreparationHoldRepository(self._connection, self._namespace).load(retained.hold)
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                cursor.execute("INSERT INTO zatca_preparation_custody_v1 "
                    "(site,storage_namespace,hold_id,ticket_sha256,candidate_sha256,manifest_sha256,payload_sha256,key_id,nonce,ciphertext) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE hold_id=hold_id",
                    tuple(getattr(sealed, name) for name in (*AAD_FIELDS, "nonce", "ciphertext")))
                stored = self._load(cursor, sealed.hold_id)
                if stored != sealed:
                    raise PreparationCustodyError("preparation_custody_conflict")
                return stored
        return self._operation(work)

    def load(self, hold_id):
        def work():
            _canonical_uuid(hold_id, "preparation_custody_hold")
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                return self._load(cursor, hold_id)
        return self._operation(work)

    def _load(self, cursor, hold_id):
        cursor.execute("SELECT site,ticket_sha256,candidate_sha256,manifest_sha256,payload_sha256,key_id,nonce,"
            "SUBSTRING(ciphertext,1,%s) FROM zatca_preparation_custody_v1 "
            "WHERE storage_namespace=%s AND hold_id=%s FOR UPDATE",
            (MAX_CUSTODY_BYTES + 17, self._namespace, hold_id))
        row = cursor.fetchone()
        if type(row) is not tuple or len(row) != 8:
            raise PreparationCustodyError("preparation_custody_missing_or_invalid")
        sealed = SealedPreparationOriginal(row[0], self._namespace, hold_id, *row[1:])
        self._cipher.open(sealed)
        return sealed
