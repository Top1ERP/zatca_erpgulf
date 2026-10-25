"""Opt-in encrypted LOCAL custody of exact retained primary HTTP observations.

No runtime registration, transport, discovery, schema setup or transaction commit.
Caller-owned transactions and independent protected keys are mandatory. A return
value is NOT durable until the caller commits/closes successfully. Never log,
pickle, enqueue or expose these protected objects as an operator JSON response.
"""

from dataclasses import dataclass, field
import hashlib
import json
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .artifact_evidence import MAX_XML_BYTES
from .credential_bundle import _key_id, copy_storage_keys
from .custody_frames import decode_frames, encode_frames
from .dispatch_journal import DispatchJournal
from .issuance_candidate import _canonical_uuid, _sha256
from .journal_repository import MariaDBJournalRepository
from .journal_storage import (
    MAX_CONTEXT_BYTES, MAX_EVENT_BYTES, decode_candidate_context,
    decode_dispatch_event, encode_candidate_context, encode_dispatch_event,
)
from .primary_receipt_persistence import RetainedPrimaryReceipt, _validate_retained
from .response_json import MAX_RESPONSE_BYTES


MAGIC = b"ZATCA-PRIMARY-RECEIPT-CUSTODY\x00\x01"
FRAME_BOUNDS = (36, MAX_CONTEXT_BYTES, MAX_XML_BYTES, MAX_EVENT_BYTES,
                MAX_EVENT_BYTES, MAX_EVENT_BYTES, MAX_RESPONSE_BYTES)
MAX_CUSTODY_BYTES = len(MAGIC) + 4 * len(FRAME_BOUNDS) + sum(FRAME_BOUNDS)
AAD_FIELDS = ("storage_namespace", "candidate_sha256", "attempt_id",
              "predecessor_sha256", "receipt_sha256", "key_id")


class PrimaryReceiptCustodyError(ValueError):
    """Static internal code only; no driver/plaintext/key/identity disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def encode_retained_receipt(receipt):
    """Protected bounded binary codec, NOT a log/API/queue payload."""
    try:
        _validate_retained(receipt)
        parts = (receipt.storage_namespace.encode("ascii"),
            encode_candidate_context(receipt.before.candidate), receipt.before.candidate.xml_bytes,
            encode_dispatch_event(receipt.before.events[0]),
            encode_dispatch_event(receipt.before.events[1]) if len(receipt.before.events) == 2 else b"",
            encode_dispatch_event(receipt.response_event), receipt.response_event.response_bytes)
        content = encode_frames(MAGIC, FRAME_BOUNDS, parts)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PrimaryReceiptCustodyError("receipt_custody_input")
    return content


def decode_retained_receipt(content):
    """Rebuild exact contracts, preserving empty response and lexical XML bytes."""
    try:
        namespace, context, xml, start, unknown, response, body = decode_frames(MAGIC, FRAME_BOUNDS, content)
        candidate = decode_candidate_context(context, xml)
        events = (decode_dispatch_event(start, None),)
        if unknown:
            events += (decode_dispatch_event(unknown, None),)
        receipt = RetainedPrimaryReceipt(namespace.decode("ascii"), DispatchJournal(candidate, events),
            decode_dispatch_event(response, body))
        if encode_retained_receipt(receipt) != content:
            raise ValueError
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PrimaryReceiptCustodyError("receipt_custody_payload")
    return receipt


def _aad(metadata):
    return b"zatca-primary-receipt-custody/v1\0" + json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


@dataclass(frozen=True, repr=False)
class SealedPrimaryReceipt:
    """Protected immutable envelope, not proof of remote receipt or SQL commit."""

    storage_namespace: str
    candidate_sha256: str
    attempt_id: str
    predecessor_sha256: str
    receipt_sha256: str
    key_id: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)

    def __post_init__(self):
        try:
            for value in (self.storage_namespace, self.attempt_id):
                _canonical_uuid(value, "receipt_custody_identity")
            for value in (self.candidate_sha256, self.predecessor_sha256, self.receipt_sha256):
                _sha256(value, "receipt_custody_fingerprint")
            _key_id(self.key_id)
            if (type(self.nonce) is not bytes or len(self.nonce) != 12
                    or type(self.ciphertext) is not bytes or not 16 < len(self.ciphertext) <= MAX_CUSTODY_BYTES + 16):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReceiptCustodyError("receipt_custody_envelope")

    def __repr__(self):
        return "SealedPrimaryReceipt(<protected exact local observation>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptCustodyError("receipt_custody_not_pickleable")


class PrimaryReceiptCustodyCipher:
    """Dedicated supplied AES-256-GCM keyring; NOT a vault or key discovery.

    Independent keys from signing, credentials, Compliance and other domains
    are a provisioning requirement. AAD does NOT prevent cross-domain nonce reuse.
    Global key/nonce-volume/rotation/recovery and secure custody remain audits.
    """

    def __init__(self, keys):
        try:
            self._keys = copy_storage_keys(keys)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReceiptCustodyError("receipt_custody_keyring")

    def __repr__(self):
        return "PrimaryReceiptCustodyCipher(<protected dedicated keys>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptCustodyError("receipt_custody_not_pickleable")

    def seal(self, receipt, *, key_id):
        """Seal ONCE; preserve this exact envelope across uncertain SQL outcomes."""
        content = encode_retained_receipt(receipt)
        try:
            _key_id(key_id)
            metadata = dict(storage_namespace=receipt.storage_namespace,
                candidate_sha256=receipt.before.candidate.key_sha256,
                attempt_id=receipt.response_event.attempt_id, predecessor_sha256=receipt.before.journal_sha256,
                receipt_sha256=hashlib.sha256(content).hexdigest(), key_id=key_id)
            nonce = secrets.token_bytes(12)
            ciphertext = AESGCM(self._keys[key_id]).encrypt(nonce, content, _aad(metadata))
            sealed = SealedPrimaryReceipt(**metadata, nonce=nonce, ciphertext=ciphertext)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReceiptCustodyError("receipt_custody_seal")
        return sealed

    def open(self, sealed):
        """Authenticate exact bytes/declarations; never attest their remote origin."""
        try:
            if type(sealed) is not SealedPrimaryReceipt:
                raise ValueError
            sealed.__post_init__()
            metadata = {name: getattr(sealed, name) for name in AAD_FIELDS}
            content = AESGCM(self._keys[sealed.key_id]).decrypt(sealed.nonce, sealed.ciphertext, _aad(metadata))
            receipt = decode_retained_receipt(content)
            if (receipt.storage_namespace != sealed.storage_namespace
                    or receipt.before.candidate.key_sha256 != sealed.candidate_sha256
                    or receipt.response_event.attempt_id != sealed.attempt_id
                    or receipt.before.journal_sha256 != sealed.predecessor_sha256
                    or hashlib.sha256(content).hexdigest() != sealed.receipt_sha256):
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReceiptCustodyError("receipt_custody_authentication")
        return receipt


class MariaDBPrimaryReceiptCustodyRepository:
    """Immutable custody on an explicit transaction; caller commits/cleans up.

    One exact envelope per existing candidate/attempt. No listing/latest fallback,
    delete, overwrite, reseal, journal append or HTTP. After ANY error discard the
    repository and roll back the WHOLE caller transaction. Runtime is not wired.
    """

    def __init__(self, connection, storage_namespace, cipher):
        try:
            _canonical_uuid(storage_namespace, "receipt_custody_namespace")
            if type(cipher) is not PrimaryReceiptCustodyCipher:
                raise ValueError
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PrimaryReceiptCustodyError("receipt_custody_dependencies")
        self._connection, self._namespace, self._cipher = connection, storage_namespace, cipher
        self._failed = False

    def __repr__(self):
        return "MariaDBPrimaryReceiptCustodyRepository(<protected explicit local transaction>)"

    def __reduce_ex__(self, protocol):
        raise PrimaryReceiptCustodyError("receipt_custody_not_pickleable")

    def _operation(self, work):
        """Catch outside a contextmanager exit so raw exception context is absent."""
        if self._failed:
            raise PrimaryReceiptCustodyError("receipt_custody_transaction_unusable")
        code = None
        try:
            result = work()
        except BaseException as error:
            self._failed = True
            if not isinstance(error, Exception):
                raise
            code = error.code if type(error) is PrimaryReceiptCustodyError else "receipt_custody_storage"
        if code is not None:
            raise PrimaryReceiptCustodyError(code)
        return result

    def _transaction(self, cursor):
        cursor.execute("SELECT @@session.autocommit")
        row = cursor.fetchone()
        if type(row) is not tuple or len(row) != 1 or type(row[0]) is not int or row != (0,):
            raise PrimaryReceiptCustodyError("receipt_custody_autocommit")

    def stage(self, sealed):
        """Authenticate before SQL; exact already-started journal is required.

        Returning this envelope is not a durable acknowledgment. Keep the input
        until caller commit AND close; unknown commits allow explicit identical
        LOCAL redelivery only. Differing/resealed evidence is never adopted.
        """
        def work():
            receipt = self._cipher.open(sealed)
            if sealed.storage_namespace != self._namespace:
                raise PrimaryReceiptCustodyError("receipt_custody_scope")
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                current = MariaDBJournalRepository(self._connection, self._namespace).load(sealed.candidate_sha256)
                if current not in (receipt.before, _validate_retained(receipt)):
                    raise PrimaryReceiptCustodyError("receipt_custody_predecessor")
                cursor.execute("INSERT INTO zatca_primary_receipt_custody_v1 "
                    "(storage_namespace,candidate_sha256,attempt_id,predecessor_sha256,receipt_sha256,key_id,nonce,ciphertext) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE candidate_sha256=candidate_sha256",
                    tuple(getattr(sealed, name) for name in (*AAD_FIELDS, "nonce", "ciphertext")))
                stored = self._load(cursor, sealed.candidate_sha256, sealed.attempt_id)
                if stored != sealed:
                    raise PrimaryReceiptCustodyError("receipt_custody_conflict")
                return stored
        return self._operation(work)

    def load(self, candidate_sha256, attempt_id):
        """Explicit local selection only, not permissioned export/replay authority.

        Custody remains readable if today's source/credential/journal has drifted;
        later journal persistence still enforces its exact predecessor contract.
        No fallback to other namespace/attempt or mutable current ERP settings.
        """
        def work():
            _sha256(candidate_sha256, "receipt_custody_candidate")
            _canonical_uuid(attempt_id, "receipt_custody_attempt")
            with self._connection.cursor() as cursor:
                self._transaction(cursor)
                return self._load(cursor, candidate_sha256, attempt_id)
        return self._operation(work)

    def _load(self, cursor, candidate_sha256, attempt_id):
        cursor.execute("SELECT predecessor_sha256,receipt_sha256,key_id,nonce,SUBSTRING(ciphertext,1,%s) "
            "FROM zatca_primary_receipt_custody_v1 WHERE storage_namespace=%s AND candidate_sha256=%s "
            "AND attempt_id=%s FOR UPDATE", (MAX_CUSTODY_BYTES + 17, self._namespace, candidate_sha256, attempt_id))
        row = cursor.fetchone()
        if row is None:
            raise PrimaryReceiptCustodyError("receipt_custody_missing")
        if type(row) is not tuple or len(row) != 5:
            raise PrimaryReceiptCustodyError("receipt_custody_row")
        sealed = SealedPrimaryReceipt(self._namespace, candidate_sha256, attempt_id, *row)
        self._cipher.open(sealed)
        return sealed
