"""Versioned encrypted STAGING material, not a vault or active credential service.

Keys are supplied in memory by the caller, never discovered in site configuration.
AES-GCM binds namespace, key ID and exact public manifest to encrypted material.
No database, HTTP, clock, field migration or activation occurs. Encryption and
local material binding do not verify taxpayer/environment/remote provenance.
"""

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from zatca_erpgulf.zatca_erpgulf.api_routing import ApiRoute, ENVIRONMENT_FIELDS
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialOwner, authorization_field_for_owner
from zatca_erpgulf.zatca_erpgulf.credential_snapshot import (
    CredentialSnapshot, CredentialSnapshotError, validate_snapshot_owner, validate_snapshot_time,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    IssuanceContractError, _canonical_uuid, _identity_text, _sha256,
)
from zatca_erpgulf.zatca_erpgulf.response_json import parse_wire_response


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 8192
MAX_PLAINTEXT_BYTES = 1024 * 1024
ROUTE_FIELDS = ("environment", "endpoint", "base_url_field", "required_credential", "url")


class CredentialBundleError(ValueError):
    """Static code only; no plaintext, parser, DB or cryptographic error details."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _validate(value, code, validator):
    try:
        validator(value, code)
    except IssuanceContractError:
        raise CredentialBundleError(code) from None


def _key_id(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value) is None:
        raise CredentialBundleError("bundle_key_id")


def _json(body, bound):
    try:
        result = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise CredentialBundleError("bundle_json") from None
    if len(result) > bound:
        raise CredentialBundleError("bundle_payload_size")
    return result


def _decode(content, names, bound):
    if type(content) is not bytes or not content or len(content) > bound:
        raise CredentialBundleError("bundle_payload_size")
    try:
        body = parse_wire_response(content)
    except ArtifactEvidenceError:
        raise CredentialBundleError("bundle_json") from None
    if set(body) != set(names):
        raise CredentialBundleError("bundle_payload_fields")
    if type(body["schema_version"]) is not int or body["schema_version"] != SCHEMA_VERSION:
        raise CredentialBundleError("bundle_schema_version")
    return body


@dataclass(frozen=True)
class CredentialSlot:
    owner_doctype: str
    owner_name: str
    environment: str
    purpose: str

    def __post_init__(self):
        if self.owner_doctype not in ("Company", "ZATCA Multiple Setting"):
            raise CredentialBundleError("bundle_owner")
        _validate(self.owner_name, "bundle_owner", _identity_text)
        if type(self.environment) is not str or self.environment not in ENVIRONMENT_FIELDS:
            raise CredentialBundleError("bundle_environment")
        if self.purpose not in ("compliance", "production"):
            raise CredentialBundleError("bundle_purpose")

    @property
    def sha256(self):
        return hashlib.sha256(_json(vars(self), MAX_MANIFEST_BYTES)).hexdigest()


@dataclass(frozen=True)
class CredentialBundleManifest:
    """Public declarations, NOT trusted epoch, activation or remote completion."""

    slot: CredentialSlot
    version_id: str
    flow_id: str
    compliance_request_id: str
    parent_compliance_version_id: str | None
    company_name: str
    source_kind: str
    prepared_at: datetime
    certificate_der_sha256: str
    public_key_sha256: str
    certificate_text_sha256: str

    def __post_init__(self):
        if type(self.slot) is not CredentialSlot:
            raise CredentialBundleError("bundle_slot")
        for value, code in ((self.version_id, "bundle_version"), (self.flow_id, "bundle_flow")):
            _validate(value, code, _canonical_uuid)
        if type(self.compliance_request_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,140}", self.compliance_request_id) is None:
            raise CredentialBundleError("bundle_request_id")
        if self.slot.purpose == "compliance":
            if self.parent_compliance_version_id is not None:
                raise CredentialBundleError("bundle_parent")
        else:
            _validate(self.parent_compliance_version_id, "bundle_parent", _canonical_uuid)
            if self.parent_compliance_version_id == self.version_id:
                raise CredentialBundleError("bundle_parent")
        try:
            validate_snapshot_owner(CredentialOwner(self.company_name, self.slot.owner_doctype,
                                    self.slot.owner_name, self.source_kind, MappingProxyType({})))
            validate_snapshot_time(self.prepared_at)
        except CredentialSnapshotError:
            raise CredentialBundleError("bundle_owner_or_time") from None
        for value in (self.certificate_der_sha256, self.public_key_sha256, self.certificate_text_sha256):
            _validate(value, "bundle_fingerprint", _sha256)

    def encode(self):
        return _json({
            "schema_version": SCHEMA_VERSION, **{
                key: value for key, value in vars(self).items() if key not in ("slot", "prepared_at")
            }, "slot": vars(self.slot), "prepared_at": self.prepared_at.isoformat(timespec="microseconds"),
        }, MAX_MANIFEST_BYTES)

    def diagnostic_projection(self):
        return {
            "slot": vars(self.slot).copy(), "version_id": self.version_id,
            "flow_id": self.flow_id, "parent_compliance_version_id": self.parent_compliance_version_id,
            "certificate_der_sha256": self.certificate_der_sha256,
            "public_key_sha256": self.public_key_sha256,
            "state": "STAGED_DECLARATION", "credential_epoch_verified": False,
            "remote_authorization_verified": False, "compliance_completion_verified": False,
            "activation_authorized": False, "dispatch_authorized": False, "replay_authorized": False,
        }


def decode_bundle_manifest(content):
    body = _decode(content, ("schema_version", *CredentialBundleManifest.__dataclass_fields__), MAX_MANIFEST_BYTES)
    try:
        slot = body.pop("slot")
        if type(slot) is not dict or set(slot) != set(CredentialSlot.__dataclass_fields__):
            raise CredentialBundleError("bundle_slot")
        timestamp = body.pop("prepared_at")
        if type(timestamp) is not str or len(timestamp) != 32:
            raise CredentialBundleError("bundle_timestamp")
        body.pop("schema_version")
        manifest = CredentialBundleManifest(slot=CredentialSlot(**slot), prepared_at=datetime.fromisoformat(timestamp), **body)
    except (TypeError, ValueError) as error:
        if isinstance(error, CredentialBundleError):
            raise
        raise CredentialBundleError("bundle_manifest") from None
    if manifest.encode() != content:
        raise CredentialBundleError("bundle_manifest_representation")
    return manifest


@dataclass(frozen=True)
class SealedCredentialBundle:
    storage_namespace: str
    manifest_bytes: bytes = field(repr=False)
    key_id: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)
    manifest: CredentialBundleManifest = field(init=False, repr=False)

    def __post_init__(self):
        _validate(self.storage_namespace, "bundle_namespace", _canonical_uuid)
        _key_id(self.key_id)
        if type(self.nonce) is not bytes or len(self.nonce) != 12:
            raise CredentialBundleError("bundle_nonce")
        if type(self.ciphertext) is not bytes or not 16 < len(self.ciphertext) <= MAX_PLAINTEXT_BYTES + 16:
            raise CredentialBundleError("bundle_ciphertext_size")
        object.__setattr__(self, "manifest", decode_bundle_manifest(self.manifest_bytes))

    @property
    def manifest_sha256(self):
        return hashlib.sha256(self.manifest_bytes).hexdigest()

    def __reduce_ex__(self, protocol):
        raise CredentialBundleError("bundle_not_pickleable")


class CredentialBundleCipher:
    """Caller-owned AES-256-GCM keys; no environment/config/KMS discovery.

    This is NOT a key-management service. Random 96-bit nonces must never be
    reused under a key. Deployment must impose key/volume/rotation policy and
    protected recovery separately; no Python secure-erasure claim is made.
    """

    def __init__(self, keys):
        if not isinstance(keys, Mapping) or not 1 <= len(keys) <= 32:
            raise CredentialBundleError("bundle_keyring")
        copied = dict(keys)
        for key_id, key in copied.items():
            _key_id(key_id)
            if type(key) is not bytes or len(key) != 32:
                raise CredentialBundleError("bundle_key_material")
        if len(set(copied.values())) != len(copied):
            raise CredentialBundleError("bundle_duplicate_key_material")
        self._keys = MappingProxyType(copied)

    def __repr__(self):
        return "CredentialBundleCipher(<protected caller-supplied keys>)"

    def __reduce_ex__(self, protocol):
        raise CredentialBundleError("bundle_not_pickleable")

    def _cipher(self, key_id):
        if key_id not in self._keys:
            raise CredentialBundleError("bundle_key_unavailable")
        return AESGCM(self._keys[key_id])

    @staticmethod
    def _aad(namespace, key_id, manifest_bytes):
        return b"zatca-credential-bundle/v1\0" + namespace.encode("ascii") + b"\0" + key_id.encode("ascii") + b"\0" + manifest_bytes

    def seal(self, snapshot, *, storage_namespace, key_id, version_id, flow_id,
             compliance_request_id, parent_compliance_version_id=None):
        """Encrypt once; retries must retain this exact envelope, not reseal it."""
        if type(snapshot) is not CredentialSnapshot:
            raise CredentialBundleError("bundle_snapshot")
        _validate(storage_namespace, "bundle_namespace", _canonical_uuid)
        _key_id(key_id)
        manifest = CredentialBundleManifest(
            CredentialSlot(snapshot.owner.doctype, snapshot.owner.name, snapshot.route.environment, snapshot.authorization.purpose),
            version_id, flow_id, compliance_request_id, parent_compliance_version_id,
            snapshot.owner.company_name, snapshot.owner.source_kind, snapshot.observed_at,
            snapshot.certificate_der_sha256, snapshot.public_key_sha256,
            hashlib.sha256(snapshot.certificate_text.encode("ascii")).hexdigest(),
        )
        plaintext = _json({
            "schema_version": SCHEMA_VERSION, "private_key": snapshot.owner.values["custom_private_key"],
            "authorization": snapshot.owner.values[snapshot.authorization.fieldname], "certificate_text": snapshot.certificate_text,
            "route": {key: getattr(snapshot.route, key) for key in ROUTE_FIELDS},
        }, MAX_PLAINTEXT_BYTES)
        manifest_bytes, nonce = manifest.encode(), secrets.token_bytes(12)
        ciphertext = self._cipher(key_id).encrypt(nonce, plaintext, self._aad(storage_namespace, key_id, manifest_bytes))
        return SealedCredentialBundle(storage_namespace, manifest_bytes, key_id, nonce, ciphertext)

    def open(self, sealed, *, observed_at):
        """Authenticate/decrypt locally and recheck validity at explicit UTC time.

        Returns protected in-memory material, not an active/authorized credential.
        The stored route remains a declaration, not today's saved routing policy.
        """
        if type(sealed) is not SealedCredentialBundle:
            raise CredentialBundleError("bundle_envelope")
        try:
            validate_snapshot_time(observed_at)
            plaintext = self._cipher(sealed.key_id).decrypt(
                sealed.nonce, sealed.ciphertext, self._aad(sealed.storage_namespace, sealed.key_id, sealed.manifest_bytes),
            )
        except InvalidTag:
            raise CredentialBundleError("bundle_authentication_failed") from None
        except CredentialSnapshotError:
            raise CredentialBundleError("bundle_observation_time") from None
        body = _decode(plaintext, ("schema_version", "private_key", "authorization", "certificate_text", "route"), MAX_PLAINTEXT_BYTES)
        manifest = sealed.manifest
        try:
            route = body["route"]
            if type(route) is not dict or set(route) != set(ROUTE_FIELDS):
                raise CredentialBundleError("bundle_route_fields")
            slot = manifest.slot
            if route["environment"] != slot.environment or route["required_credential"] != slot.purpose:
                raise CredentialBundleError("bundle_slot_material")
            reference = CredentialOwner(manifest.company_name, slot.owner_doctype, slot.owner_name, manifest.source_kind, {})
            auth_field = authorization_field_for_owner(reference, slot.purpose)
            owner = CredentialOwner(manifest.company_name, slot.owner_doctype, slot.owner_name, manifest.source_kind,
                                    MappingProxyType({"custom_private_key": body["private_key"], auth_field: body["authorization"]}))
            snapshot = CredentialSnapshot(owner, ApiRoute(**route), body["certificate_text"], observed_at)
            if (
                snapshot.certificate_der_sha256 != manifest.certificate_der_sha256
                or snapshot.public_key_sha256 != manifest.public_key_sha256
                or hashlib.sha256(snapshot.certificate_text.encode("ascii")).hexdigest() != manifest.certificate_text_sha256
            ):
                raise CredentialBundleError("bundle_material_fingerprint")
        except (CredentialSnapshotError, TypeError, ValueError) as error:
            if isinstance(error, CredentialBundleError):
                raise
            raise CredentialBundleError("bundle_material_invalid") from None
        return snapshot
