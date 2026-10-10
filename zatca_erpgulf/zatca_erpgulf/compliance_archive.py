"""Protected exact-byte Compliance observation storage, NOT trusted transport.

Separate archive keys must be supplied by a reviewed server provider. No signing
keys/site settings/HTTP/database/clock discovery, plaintext logs or activation.
Binary length-prefixed frames avoid Base64-expanding request/response bodies and
preserve empty HTTP bodies separately from absent responses. Never pickle.
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf.api_routing import ApiRoute
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import (
    MAX_CSR_BYTES, ComplianceExchangeObservation, ComplianceRequirements,
)
from zatca_erpgulf.zatca_erpgulf.credential_bundle import (
    ROUTE_FIELDS, _key_id, _validate, copy_storage_keys, decode_bundle_manifest,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid, _sha256
from zatca_erpgulf.zatca_erpgulf.response_json import MAX_RESPONSE_BYTES, parse_wire_response


MAGIC = b"ZATCA-COMPLIANCE-OBSERVATION\x00\x01"
MAX_HEADER_BYTES = 32 * 1024
MAX_ARCHIVE_BYTES = len(MAGIC) + 16 + MAX_HEADER_BYTES + MAX_CSR_BYTES + 2 * MAX_RESPONSE_BYTES
HEADER_FIELDS = ("schema_version", "storage_namespace", "manifest", "exchange_id", "route",
                 "started_at", "received_at", "http_status", "has_response")
AAD_FIELDS = ("storage_namespace", "exchange_id", "sequence", "version_id", "manifest_sha256",
              "observation_sha256", "key_id")


class ComplianceArchiveError(ValueError):
    """Static code only; callers must not render parser/driver/key exceptions."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _reference(value, code, validator):
    try:
        _validate(value, code, validator)
    except ValueError:
        raise ComplianceArchiveError(code) from None


def _json(body):
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _aad(body):
    return b"zatca-compliance-archive/v1\0" + _json(body)


def encode_observation(observation):
    """Internal protected storage bytes; NOT a log, queue or API response."""
    if type(observation) is not ComplianceExchangeObservation:
        raise ComplianceArchiveError("archive_observation")
    header = _json({"schema_version": 1, "storage_namespace": observation.requirements.storage_namespace,
        "manifest": base64.b64encode(observation.requirements.manifest.encode()).decode(),
        "exchange_id": observation.exchange_id, "route": {name: getattr(observation.route, name) for name in ROUTE_FIELDS},
        "started_at": observation.started_at.isoformat(timespec="microseconds"),
        "received_at": None if observation.received_at is None else observation.received_at.isoformat(timespec="microseconds"),
        "http_status": observation.http_status, "has_response": observation.response_bytes is not None})
    if len(header) > MAX_HEADER_BYTES:
        raise ComplianceArchiveError("archive_header_size")
    parts = (header, observation.requirements.csr_der, observation.request_bytes, observation.response_bytes or b"")
    return MAGIC + b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def decode_observation(content):
    """Strict rehydration recomputes all existing CSR/XML/response bindings."""
    if type(content) is not bytes or not len(MAGIC) < len(content) <= MAX_ARCHIVE_BYTES or not content.startswith(MAGIC):
        raise ComplianceArchiveError("archive_payload")
    offset, parts = len(MAGIC), []
    for bound in (MAX_HEADER_BYTES, MAX_CSR_BYTES, MAX_RESPONSE_BYTES, MAX_RESPONSE_BYTES):
        if len(content) - offset < 4:
            raise ComplianceArchiveError("archive_frame")
        size = int.from_bytes(content[offset:offset + 4], "big")
        offset += 4
        if size > bound or len(content) - offset < size:
            raise ComplianceArchiveError("archive_frame")
        parts.append(content[offset:offset + size])
        offset += size
    if offset != len(content):
        raise ComplianceArchiveError("archive_trailing_bytes")
    header, csr, request, response = parts
    try:
        body = parse_wire_response(header)
        if (set(body) != set(HEADER_FIELDS) or type(body["schema_version"]) is not int
                or body["schema_version"] != 1 or type(body["has_response"]) is not bool
                or type(body["route"]) is not dict or set(body["route"]) != set(ROUTE_FIELDS)):
            raise ComplianceArchiveError("archive_header_fields")
        if not body["has_response"] and response:
            raise ComplianceArchiveError("archive_response_presence")
        manifest_bytes = base64.b64decode(body["manifest"], validate=True)
        requirements = ComplianceRequirements(body["storage_namespace"], decode_bundle_manifest(manifest_bytes), csr)
        started = datetime.fromisoformat(body["started_at"])
        received = None if body["received_at"] is None else datetime.fromisoformat(body["received_at"])
        observation = ComplianceExchangeObservation(requirements, body["exchange_id"], ApiRoute(**body["route"]),
            started, received, request, body["http_status"], response if body["has_response"] else None)
        if encode_observation(observation) != content:
            raise ComplianceArchiveError("archive_representation")
        return observation
    except ComplianceArchiveError:
        raise
    except (ValueError, TypeError, OverflowError):
        raise ComplianceArchiveError("archive_decode") from None


@dataclass(frozen=True)
class SealedComplianceObservation:
    storage_namespace: str
    exchange_id: str
    sequence: int
    version_id: str
    manifest_sha256: str
    observation_sha256: str
    key_id: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)

    def __post_init__(self):
        for value in (self.storage_namespace, self.exchange_id, self.version_id):
            _reference(value, "archive_identity", _canonical_uuid)
        for value in (self.manifest_sha256, self.observation_sha256):
            _reference(value, "archive_fingerprint", _sha256)
        if type(self.sequence) is not int or self.sequence not in (1, 2):
            raise ComplianceArchiveError("archive_sequence")
        try:
            _key_id(self.key_id)
        except ValueError:
            raise ComplianceArchiveError("archive_key_id") from None
        if type(self.nonce) is not bytes or len(self.nonce) != 12:
            raise ComplianceArchiveError("archive_nonce")
        if type(self.ciphertext) is not bytes or not 16 < len(self.ciphertext) <= MAX_ARCHIVE_BYTES + 16:
            raise ComplianceArchiveError("archive_ciphertext_size")

    def aad(self):
        return _aad({name: getattr(self, name) for name in AAD_FIELDS})

    def __reduce_ex__(self, protocol):
        raise ComplianceArchiveError("archive_not_pickleable")


class ComplianceArchiveCipher:
    """Dedicated caller-supplied archive keyring, no CSID or key-discovery fallback.

    Deployment MUST use independent key material from credential-bundle storage
    and other namespaces/domains; AAD is not protection against nonce/key reuse.
    Global key custody/nonce-volume/rotation/recovery remain deployment gates.
    """

    def __init__(self, keys):
        try:
            self._keys = copy_storage_keys(keys)
        except ValueError:
            raise ComplianceArchiveError("archive_keyring") from None

    def __repr__(self):
        return "ComplianceArchiveCipher(<protected dedicated keys>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceArchiveError("archive_not_pickleable")

    def _cipher(self, key_id):
        if key_id not in self._keys:
            raise ComplianceArchiveError("archive_key_unavailable")
        return AESGCM(self._keys[key_id])

    def seal(self, observation, *, sequence, key_id):
        if type(observation) is not ComplianceExchangeObservation:
            raise ComplianceArchiveError("archive_observation")
        if (type(sequence) is not int or sequence not in (1, 2)
                or (sequence == 1) != (observation.http_status is None)):
            raise ComplianceArchiveError("archive_stage")
        plaintext = encode_observation(observation)
        try:
            _key_id(key_id)
        except ValueError:
            raise ComplianceArchiveError("archive_key_id") from None
        metadata = dict(storage_namespace=observation.requirements.storage_namespace, exchange_id=observation.exchange_id,
            sequence=sequence, version_id=observation.requirements.manifest.version_id,
            manifest_sha256=hashlib.sha256(observation.requirements.manifest.encode()).hexdigest(),
            observation_sha256=observation.observation_sha256, key_id=key_id)
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher(key_id).encrypt(nonce, plaintext, _aad(metadata))
        return SealedComplianceObservation(**metadata, nonce=nonce, ciphertext=ciphertext)

    def open(self, sealed):
        if type(sealed) is not SealedComplianceObservation:
            raise ComplianceArchiveError("archive_envelope")
        try:
            plaintext = self._cipher(sealed.key_id).decrypt(sealed.nonce, sealed.ciphertext, sealed.aad())
        except InvalidTag:
            raise ComplianceArchiveError("archive_authentication") from None
        observation = decode_observation(plaintext)
        if (observation.requirements.storage_namespace != sealed.storage_namespace
                or observation.exchange_id != sealed.exchange_id or observation.requirements.manifest.version_id != sealed.version_id
                or hashlib.sha256(observation.requirements.manifest.encode()).hexdigest() != sealed.manifest_sha256
                or observation.observation_sha256 != sealed.observation_sha256
                or (sealed.sequence == 1) != (observation.http_status is None)):
            raise ComplianceArchiveError("archive_binding")
        return observation


@dataclass(frozen=True)
class ComplianceArchiveHistory:
    start: ComplianceExchangeObservation = field(repr=False)
    receipt: ComplianceExchangeObservation | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.start) is not ComplianceExchangeObservation or self.start.http_status is not None:
            raise ComplianceArchiveError("archive_start")
        if self.receipt is not None:
            if type(self.receipt) is not ComplianceExchangeObservation or self.receipt.http_status is None:
                raise ComplianceArchiveError("archive_receipt")
            if any(getattr(self.start, name) != getattr(self.receipt, name) for name in
                   ("requirements", "exchange_id", "route", "started_at", "request_bytes")):
                raise ComplianceArchiveError("archive_receipt_binding")

    @property
    def current_observation(self):
        return self.receipt if self.receipt is not None else self.start

    def diagnostic_projection(self):
        return {"state": "RECEIPT_CAPTURED_OBSERVATION" if self.receipt is not None else "REQUEST_CAPTURED_OBSERVATION",
                "start": self.start.diagnostic_projection(),
                "receipt": None if self.receipt is None else self.receipt.diagnostic_projection(),
                "request_dispatched_verified": False, "remote_receipt_verified": False,
                "compliance_completion_verified": False, "activation_authorized": False, "replay_authorized": False}

    def __reduce_ex__(self, protocol):
        raise ComplianceArchiveError("archive_not_pickleable")
