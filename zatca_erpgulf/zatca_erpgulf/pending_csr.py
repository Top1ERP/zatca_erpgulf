"""Encrypted pending CSR declarations, not a vault or active credential service.

Callers supply protected AES keys/namespace; nothing is discovered from a site,
environment, clock, database or filesystem. Encryption authenticates these local
declarations, not saved-source provenance, row permissions or remote issuance.
"""

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialSlot, copy_storage_keys
from zatca_erpgulf.zatca_erpgulf.csr_draft import CSRPreparationContext, PreparedCSRDraft
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid
from zatca_erpgulf.zatca_erpgulf.response_json import parse_wire_response


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 8192
MAX_PLAINTEXT_BYTES = 256 * 1024
FINGERPRINTS = ("public_key_sha256", "csr_der_sha256", "configuration_sha256")
ERROR_CODES = frozenset("namespace key_id keyring key_unavailable manifest envelope encoding payload material authentication_failed cipher not_pickleable database_error autocommit missing row_format row_binding draft_conflict identity_collision transaction_unusable lock_timeout deadlock unique_conflict context".split())


class PendingCSRStorageError(ValueError):
    """Static allowlisted code only, never raw key/CSR/parser/driver details."""

    def __init__(self, code):
        self.code = "pending_csr_" + (code if type(code) is str and code in ERROR_CODES else "material")
        super().__init__(self.code)


def validate_namespace(value):
    valid = False
    try:
        if type(value) is str and len(value) == 36:
            _canonical_uuid(value, "namespace")
            valid = True
    except Exception:
        pass
    if not valid:
        raise PendingCSRStorageError("namespace")


def _key_id(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value) is None:
        raise PendingCSRStorageError("key_id")


def _encode(body, bound):
    result = None
    try:
        result = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except Exception:
        pass
    if result is None or not 0 < len(result) <= bound:
        raise PendingCSRStorageError("encoding")
    return result


def _context_body(context):
    return {"slot": vars(context.slot).copy(), "company_name": context.company_name,
            "source_kind": context.source_kind, "source_revision": context.source_revision,
            "draft_id": context.draft_id, "flow_id": context.flow_id,
            "prepared_at": context.prepared_at.isoformat(timespec="microseconds")}


def _copy_context(context):
    if type(context) is not CSRPreparationContext or type(context.slot) is not CredentialSlot:
        raise PendingCSRStorageError("context")
    slot = context.slot
    return CSRPreparationContext(CredentialSlot(slot.owner_doctype, slot.owner_name, slot.environment, slot.purpose),
        context.company_name, context.source_kind, context.source_revision, context.draft_id,
        context.flow_id, context.prepared_at)


@dataclass(frozen=True, repr=False)
class PendingCSRManifest:
    """Public declaration authenticated at rest, not a verified source epoch."""

    context: CSRPreparationContext = field(repr=False)
    public_key_sha256: str
    csr_der_sha256: str
    configuration_sha256: str

    def __post_init__(self):
        valid = False
        try:
            copied = _copy_context(self.context)
            if any(type(getattr(self, name)) is not str or re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)) is None
                   for name in FINGERPRINTS):
                raise PendingCSRStorageError("manifest")
            object.__setattr__(self, "context", copied)
            self.encode()
            valid = True
        except Exception:
            pass
        if not valid:
            raise PendingCSRStorageError("manifest")

    def encode(self):
        return _encode({"schema_version": SCHEMA_VERSION, "context": _context_body(self.context),
                        **{name: getattr(self, name) for name in FINGERPRINTS}}, MAX_MANIFEST_BYTES)

    def __repr__(self):
        return "PendingCSRManifest(<unverified local declaration>)"

    def diagnostic_projection(self):
        return {"state": "ENCRYPTED_PENDING_DECLARATION", "draft_id": self.context.draft_id,
                "flow_id": self.context.flow_id, "environment": self.context.slot.environment,
                **{name: getattr(self, name) for name in FINGERPRINTS},
                "source_verified": False, "credential_epoch_verified": False,
                "storage_confirmed": False, "remote_authorization_verified": False,
                "activation_authorized": False, "dispatch_authorized": False, "renewal_authorized": False}


def decode_pending_manifest(content):
    result = None
    try:
        if type(content) is not bytes or not 0 < len(content) <= MAX_MANIFEST_BYTES:
            raise PendingCSRStorageError("manifest")
        body = parse_wire_response(content)
        if (set(body) != {"schema_version", "context", *FINGERPRINTS}
                or type(body["schema_version"]) is not int or body["schema_version"] != SCHEMA_VERSION):
            raise PendingCSRStorageError("manifest")
        data = body["context"]
        if type(data) is not dict or set(data) != set(CSRPreparationContext.__dataclass_fields__):
            raise PendingCSRStorageError("manifest")
        slot = data["slot"]
        if type(slot) is not dict or set(slot) != set(CredentialSlot.__dataclass_fields__):
            raise PendingCSRStorageError("manifest")
        timestamp = data["prepared_at"]
        if type(timestamp) is not str or len(timestamp) != 32:
            raise PendingCSRStorageError("manifest")
        context = CSRPreparationContext(slot=CredentialSlot(**slot),
            **{name: value for name, value in data.items() if name not in ("slot", "prepared_at")},
            prepared_at=datetime.fromisoformat(timestamp))
        candidate = PendingCSRManifest(context, **{name: body[name] for name in FINGERPRINTS})
        if candidate.encode() != content:
            raise PendingCSRStorageError("manifest")
        result = candidate
    except Exception:
        pass
    if result is None:
        raise PendingCSRStorageError("manifest")
    return result


@dataclass(frozen=True, repr=False)
class SealedPendingCSR:
    storage_namespace: str = field(repr=False)
    manifest_bytes: bytes = field(repr=False)
    key_id: str = field(repr=False)
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)

    def __post_init__(self):
        validate_namespace(self.storage_namespace)
        _key_id(self.key_id)
        decode_pending_manifest(self.manifest_bytes)
        if (type(self.nonce) is not bytes or len(self.nonce) != 12
                or type(self.ciphertext) is not bytes or not 16 < len(self.ciphertext) <= MAX_PLAINTEXT_BYTES + 16):
            raise PendingCSRStorageError("envelope")

    @property
    def manifest(self):
        # Decode exact bytes afresh, not a caller-mutable cached interpretation.
        return decode_pending_manifest(self.manifest_bytes)

    @property
    def manifest_sha256(self):
        return hashlib.sha256(self.manifest_bytes).hexdigest()

    def __repr__(self):
        return "SealedPendingCSR(<encrypted material; not activated>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRStorageError("not_pickleable")


class PendingCSRCipher:
    """Caller-supplied AES-256-GCM keys; no discovery or key-management service.

    Use independent keys and an audited nonce/volume/rotation/recovery policy.
    AAD domain separation does NOT make reusing a nonce under a key safe.
    """

    def __init__(self, keys):
        copied = None
        try:
            copied = copy_storage_keys(keys)
        except Exception:
            pass
        if copied is None:
            raise PendingCSRStorageError("keyring")
        self._keys = copied

    def __repr__(self):
        return "PendingCSRCipher(<protected caller-supplied keys>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRStorageError("not_pickleable")

    def _cipher(self, key_id):
        if key_id not in self._keys:
            raise PendingCSRStorageError("key_unavailable")
        return AESGCM(self._keys[key_id])

    @staticmethod
    def _aad(namespace, key_id, manifest_bytes):
        return b"zatca-pending-csr/v1\0" + namespace.encode("ascii") + b"\0" + key_id.encode("ascii") + b"\0" + manifest_bytes

    def seal(self, draft, *, storage_namespace, key_id):
        """Encrypt once; retain this exact envelope for any local redelivery."""
        result, code = None, "material"
        try:
            if type(draft) is not PreparedCSRDraft:
                raise PendingCSRStorageError("material")
            copied = PreparedCSRDraft(_copy_context(draft.context), draft.config_text, draft.private_key_pem, draft.csr_pem)
            if any(getattr(copied, name) != getattr(draft, name) for name in FINGERPRINTS):
                raise PendingCSRStorageError("material")
            code = "envelope"
            validate_namespace(storage_namespace)
            _key_id(key_id)
            manifest = PendingCSRManifest(copied.context, **{name: getattr(copied, name) for name in FINGERPRINTS})
            plaintext = _encode({"schema_version": SCHEMA_VERSION, "config_text": copied.config_text,
                "private_key_pem": base64.b64encode(copied.private_key_pem).decode("ascii"),
                "csr_pem": base64.b64encode(copied.csr_pem).decode("ascii")}, MAX_PLAINTEXT_BYTES)
            cipher = self._cipher(key_id)
            nonce = secrets.token_bytes(12)
            if type(nonce) is not bytes or len(nonce) != 12:
                raise PendingCSRStorageError("envelope")
            metadata = manifest.encode()
            ciphertext = cipher.encrypt(nonce, plaintext, self._aad(storage_namespace, key_id, metadata))
            result = SealedPendingCSR(storage_namespace, metadata, key_id, nonce, ciphertext)
        except PendingCSRStorageError as error:
            code = error.code.removeprefix("pending_csr_")
        except Exception:
            pass
        if result is None:
            raise PendingCSRStorageError(code)
        return result

    def open(self, sealed):
        """Authenticate/revalidate exact material, not current source or readiness."""
        result, code = None, "envelope"
        try:
            if type(sealed) is not SealedPendingCSR:
                raise PendingCSRStorageError("envelope")
            checked = SealedPendingCSR(sealed.storage_namespace, sealed.manifest_bytes,
                                      sealed.key_id, sealed.nonce, sealed.ciphertext)
            manifest = checked.manifest
            cipher = self._cipher(checked.key_id)
            code = "authentication_failed"
            plaintext = cipher.decrypt(checked.nonce, checked.ciphertext,
                self._aad(checked.storage_namespace, checked.key_id, checked.manifest_bytes))
            code = "payload"
            if not 0 < len(plaintext) <= MAX_PLAINTEXT_BYTES:
                raise PendingCSRStorageError(code)
            body = parse_wire_response(plaintext)
            if (set(body) != {"schema_version", "config_text", "private_key_pem", "csr_pem"}
                    or type(body["schema_version"]) is not int or body["schema_version"] != SCHEMA_VERSION):
                raise PendingCSRStorageError(code)
            raw = []
            for name in ("private_key_pem", "csr_pem"):
                value = body[name]
                if type(value) is not str:
                    raise PendingCSRStorageError(code)
                decoded = base64.b64decode(value, validate=True)
                if base64.b64encode(decoded).decode("ascii") != value:
                    raise PendingCSRStorageError(code)
                raw.append(decoded)
            code = "material"
            draft = PreparedCSRDraft(manifest.context, body["config_text"], *raw)
            if any(getattr(draft, name) != getattr(manifest, name) for name in FINGERPRINTS):
                raise PendingCSRStorageError(code)
            result = draft
        except PendingCSRStorageError as error:
            code = error.code.removeprefix("pending_csr_")
        except Exception:
            pass
        if result is None:
            raise PendingCSRStorageError(code)
        return result
