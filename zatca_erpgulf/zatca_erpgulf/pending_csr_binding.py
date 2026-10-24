"""Restricted pending-source declarations and exact-envelope history codec.

No source/ACL/SQL/key discovery or historical attestation. A record preserves a
supplied declaration; its unkeyed hash does not prove who captured it or when.
Never expose these source/backing fingerprints through RPC, logs or exports.
"""

import base64
import hashlib
from dataclasses import dataclass

from .credential_bundle_access import CredentialStorageScope
from .issuance_candidate import _sha256
from .pending_csr import (
    PendingCSRManifest, PendingCSRStorageError, SealedPendingCSR, _encode, _key_id,
    decode_pending_manifest,
)
from .response_json import parse_wire_response


MAX_BINDING_BYTES = 16384
BINDING_SCHEMA = 1
SOURCE_SCHEMA = 2


class PendingCSRAccessError(ValueError):
    """Static internal failure only, not diagnostic/source/material export."""

    def __init__(self):
        super().__init__("pending_csr_access_unconfirmed")


@dataclass(frozen=True, repr=False)
class PendingCSRSourceBinding:
    """Server lookup declaration, not independently verified historic evidence."""

    scope: CredentialStorageScope
    manifest: PendingCSRManifest
    source_rows_sha256: str
    key_id: str
    password_state_sha256: str

    def __post_init__(self):
        if type(self.scope) is not CredentialStorageScope or type(self.manifest) is not PendingCSRManifest:
            raise PendingCSRAccessError()
        self.scope.__post_init__()
        _sha256(self.source_rows_sha256, "pending_csr_access_source")
        _sha256(self.password_state_sha256, "pending_csr_access_password_state")
        _key_id(self.key_id)
        object.__setattr__(self, "scope", CredentialStorageScope(self.scope.site, self.scope.storage_namespace))
        object.__setattr__(self, "manifest", decode_pending_manifest(self.manifest.encode()))

    def __repr__(self):
        return "PendingCSRSourceBinding(<server-selected exact declaration>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRAccessError()


def _copy_binding(binding):
    if type(binding) is not PendingCSRSourceBinding:
        raise PendingCSRStorageError("binding")
    return PendingCSRSourceBinding(binding.scope, binding.manifest, binding.source_rows_sha256,
                                   binding.key_id, binding.password_state_sha256)


def envelope_sha256(original):
    """Domain/length-bound fingerprint of ALL exact envelope fields, not plaintext."""
    if type(original) is not SealedPendingCSR:
        raise PendingCSRStorageError("binding")
    original.__post_init__()
    digest = hashlib.sha256(b"zatca-pending-csr-binding/envelope/v1\0")
    for part in (original.storage_namespace.encode("ascii"), original.manifest_bytes,
                 original.key_id.encode("ascii"), original.nonce, original.ciphertext):
        digest.update(len(part).to_bytes(4, "big"))
        digest.update(part)
    return digest.hexdigest()


@dataclass(frozen=True, repr=False)
class PendingCSRBindingRecord:
    """Immutable restricted declaration linked to exact retained ciphertext."""

    binding: PendingCSRSourceBinding
    envelope_sha256: str

    def __post_init__(self):
        valid = False
        try:
            object.__setattr__(self, "binding", _copy_binding(self.binding))
            _sha256(self.envelope_sha256, "pending_csr_binding_envelope")
            self.encode()
            valid = True
        except Exception:
            pass
        if not valid:
            raise PendingCSRStorageError("binding")

    @classmethod
    def capture(cls, binding, original):
        result = cls(binding, envelope_sha256(original))
        if not result.matches(original):
            raise PendingCSRStorageError("binding")
        return result

    def matches(self, original):
        fingerprint = envelope_sha256(original)
        return (self.binding.scope.storage_namespace == original.storage_namespace
                and self.binding.manifest.encode() == original.manifest_bytes
                and self.binding.key_id == original.key_id and self.envelope_sha256 == fingerprint)

    def encode(self):
        binding = self.binding
        return _encode({"schema_version": BINDING_SCHEMA, "source_schema": SOURCE_SCHEMA,
            "scope": {"site": binding.scope.site, "storage_namespace": binding.scope.storage_namespace},
            "manifest_b64": base64.b64encode(binding.manifest.encode()).decode("ascii"),
            "source_rows_sha256": binding.source_rows_sha256, "key_id": binding.key_id,
            "password_state_sha256": binding.password_state_sha256,
            "envelope_sha256": self.envelope_sha256}, MAX_BINDING_BYTES)

    def __repr__(self):
        return "PendingCSRBindingRecord(<restricted original-envelope declaration>)"

    def __reduce_ex__(self, protocol):
        raise PendingCSRStorageError("not_pickleable")


def decode_binding_record(content):
    """Canonical bounded bytes only; no schema upgrade, recovery or key discovery."""
    result = None
    try:
        if type(content) is not bytes or not 0 < len(content) <= MAX_BINDING_BYTES:
            raise PendingCSRStorageError("binding")
        body = parse_wire_response(content)
        if (set(body) != {"schema_version", "source_schema", "scope", "manifest_b64", "source_rows_sha256",
                          "key_id", "password_state_sha256", "envelope_sha256"}
                or type(body["schema_version"]) is not int or body["schema_version"] != BINDING_SCHEMA
                or type(body["source_schema"]) is not int or body["source_schema"] != SOURCE_SCHEMA
                or type(body["scope"]) is not dict or set(body["scope"]) != {"site", "storage_namespace"}
                or type(body["manifest_b64"]) is not str):
            raise PendingCSRStorageError("binding")
        manifest = decode_pending_manifest(base64.b64decode(body["manifest_b64"], validate=True))
        binding = PendingCSRSourceBinding(CredentialStorageScope(**body["scope"]), manifest,
            body["source_rows_sha256"], body["key_id"], body["password_state_sha256"])
        candidate = PendingCSRBindingRecord(binding, body["envelope_sha256"])
        if candidate.encode() != content:
            raise PendingCSRStorageError("binding")
        result = candidate
    except Exception:
        pass
    if result is None:
        raise PendingCSRStorageError("binding")
    return result
