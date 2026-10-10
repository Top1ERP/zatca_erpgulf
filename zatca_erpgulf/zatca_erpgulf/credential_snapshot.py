"""Ephemeral signing/HTTP material binding, not a trusted credential epoch.

One copied owner projection supplies the private key and purpose-specific Basic
header. The header's certificate must equal the selected signing certificate in
DER, not merely share its key. No SQL, clock, HTTP, signing, serialization or
credential writes occur. Never persist/log/queue this secret-bearing object.
"""

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from zatca_erpgulf.zatca_erpgulf.api_routing import (
    ENVIRONMENT_FIELDS, ApiConfigurationError, ApiRoute, resolve_api_route,
)
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError
from zatca_erpgulf.zatca_erpgulf.certificate_evidence import (
    MAX_CERTIFICATE_DER_BYTES, MAX_CERTIFICATE_TEXT_BYTES, parse_public_certificate_text,
)
from zatca_erpgulf.zatca_erpgulf.credential_material import (
    CredentialConfigurationError, CredentialOwner, authorization_field_for_owner, authorization_for_owner,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import IssuanceContractError, _identity_text


MAX_AUTH_TEXT = 512 * 1024
MAX_PRIVATE_KEY_TEXT = 64 * 1024
OPERATIONS = {"compliance/invoices", "invoices/reporting/single", "invoices/clearance/single"}


class CredentialSnapshotError(ValueError):
    """Static internal code, never parser exceptions, auth, PEM or subject text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _route(route):
    if type(route) is not ApiRoute or type(route.endpoint) is not str or route.endpoint not in OPERATIONS:
        raise CredentialSnapshotError("snapshot_operation")
    if type(route.environment) is not str or route.environment not in ENVIRONMENT_FIELDS:
        raise CredentialSnapshotError("snapshot_route")
    suffix = "/" + route.endpoint
    if type(route.url) is not str or len(route.url) > 4096 or not route.url.endswith(suffix):
        raise CredentialSnapshotError("snapshot_route")
    try:
        route.url.encode("utf-8")
        resolved = resolve_api_route(
            {"custom_select": route.environment, ENVIRONMENT_FIELDS[route.environment]: route.url[:-len(suffix)]},
            route.endpoint,
        )
    except (ApiConfigurationError, UnicodeEncodeError):
        raise CredentialSnapshotError("snapshot_route") from None
    if resolved != route:
        raise CredentialSnapshotError("snapshot_route")


def _auth_certificate(header):
    """Decode the Basic username in bounded known certificate formats only.

    Support the app's Base64-of-Base64-DER token, direct DER token, and a single
    PEM token as explicit compatibility formats. No recursive format guessing.
    The password remains opaque; local parsing cannot verify it with ZATCA.
    """
    try:
        decoded = base64.b64decode(header.removeprefix("Basic "), validate=True)
        username, separator, password = decoded.partition(b":")
        if not separator or not username or not password or any(byte < 32 or byte == 127 for byte in decoded):
            raise ValueError
        token = base64.b64decode(username, validate=True)
        if not token or len(token) > MAX_CERTIFICATE_TEXT_BYTES:
            raise ValueError
        if token.startswith(b"-----BEGIN CERTIFICATE-----"):
            matched = re.fullmatch(
                rb"-----BEGIN CERTIFICATE-----[ \t\r\n]*([A-Za-z0-9+/= \t\r\n]+)[ \t\r\n]*-----END CERTIFICATE-----[ \t\r\n]*", token,
            )
            if matched is None:
                raise ValueError
            return parse_public_certificate_text(matched[1].decode("ascii"))[1]
        if token.startswith(b"\x30"):
            if len(token) > MAX_CERTIFICATE_DER_BYTES:
                raise ValueError
            cert = x509.load_der_x509_certificate(token)
            if cert.public_bytes(serialization.Encoding.DER) != token:
                raise ValueError
            return token
        return parse_public_certificate_text(token.decode("ascii"))[1]
    except (ValueError, TypeError, binascii.Error, ArtifactEvidenceError, UnsupportedAlgorithm):
        raise CredentialSnapshotError("snapshot_authorization_format") from None


@dataclass(frozen=True)
class CredentialSnapshot:
    """Locally bound material copied once, with safe fingerprint-only diagnostics.

    certificate_text is selected by the existing alias policy in the saved-source
    adapter, never rewritten here. observed_at is explicit UTC from the service.
    Certificate validity is a local time check, not trust/revocation/environment
    or taxpayer verification. Caller-supplied owner data is still a declaration.
    """

    owner: CredentialOwner = field(repr=False)
    route: ApiRoute = field(repr=False)
    certificate_text: str = field(repr=False)
    observed_at: datetime
    authorization: object = field(init=False, repr=False)
    private_key: object = field(init=False, repr=False)
    certificate: object = field(init=False, repr=False)
    certificate_der: bytes = field(init=False, repr=False)
    public_key_der: bytes = field(init=False, repr=False)
    certificate_der_sha256: str = field(init=False)
    public_key_sha256: str = field(init=False)

    def __post_init__(self):
        _route(self.route)
        if type(self.observed_at) is not datetime or self.observed_at.tzinfo is not timezone.utc:
            raise CredentialSnapshotError("snapshot_utc_timestamp")
        if type(self.owner) is not CredentialOwner or self.owner.doctype not in ("Company", "ZATCA Multiple Setting"):
            raise CredentialSnapshotError("snapshot_owner")
        if self.owner.source_kind not in ("company", "linked_company", "multiple_setting"):
            raise CredentialSnapshotError("snapshot_owner")
        if self.owner.source_kind == "company" and self.owner.name != self.owner.company_name:
            raise CredentialSnapshotError("snapshot_owner")
        if not isinstance(self.owner.values, Mapping):
            raise CredentialSnapshotError("snapshot_owner")
        try:
            for value in (self.owner.company_name, self.owner.name):
                _identity_text(value, "snapshot_owner")
            if (self.owner.doctype == "ZATCA Multiple Setting") != (self.owner.source_kind == "multiple_setting"):
                raise CredentialSnapshotError("snapshot_owner")
            # Keep only immutable scalar secret fields consumed by this purpose.
            auth_field = authorization_field_for_owner(self.owner, self.route.required_credential)
            values = {name: self.owner.values.get(name) for name in ("custom_private_key", auth_field)}
            if any(value is not None and type(value) is not str for value in values.values()):
                raise CredentialSnapshotError("snapshot_material_type")
            for name, value in values.items():
                bound = MAX_PRIVATE_KEY_TEXT if name == "custom_private_key" else MAX_AUTH_TEXT
                if value is not None and len(value) > bound:
                    raise CredentialSnapshotError("snapshot_material_size")
            owner = CredentialOwner(
                self.owner.company_name, self.owner.doctype, self.owner.name, self.owner.source_kind,
                MappingProxyType(values),
            )
            authorization = authorization_for_owner(owner, self.route.required_credential)
            certificate, der = parse_public_certificate_text(self.certificate_text)
            if _auth_certificate(authorization.header) != der:
                raise CredentialSnapshotError("snapshot_auth_certificate_mismatch")
            key_text = values["custom_private_key"]
            if not key_text:
                raise CredentialSnapshotError("snapshot_private_key")
            key = serialization.load_pem_private_key(key_text.encode("utf-8"), password=None)
            public_key = certificate.public_key()
            if (
                not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(public_key, ec.EllipticCurvePublicKey)
                or key.curve.name != "secp256k1" or public_key.curve.name != "secp256k1"
            ):
                raise CredentialSnapshotError("snapshot_algorithm")
            options = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            public_der = public_key.public_bytes(*options)
            if key.public_key().public_bytes(*options) != public_der:
                raise CredentialSnapshotError("snapshot_key_mismatch")
            before = getattr(certificate, "not_valid_before_utc", None)
            after = getattr(certificate, "not_valid_after_utc", None)
            before = before if before is not None else certificate.not_valid_before.replace(tzinfo=timezone.utc)
            after = after if after is not None else certificate.not_valid_after.replace(tzinfo=timezone.utc)
            if not before <= self.observed_at <= after:
                raise CredentialSnapshotError("snapshot_certificate_time")
        except CredentialSnapshotError:
            raise
        except (CredentialConfigurationError, ArtifactEvidenceError, IssuanceContractError):
            raise CredentialSnapshotError("snapshot_material_invalid") from None
        except (ValueError, TypeError, AttributeError, UnsupportedAlgorithm):
            raise CredentialSnapshotError("snapshot_private_key") from None
        for name, value in (
            ("owner", owner), ("authorization", authorization), ("private_key", key),
            ("certificate", certificate), ("certificate_der", der), ("public_key_der", public_der),
            ("certificate_der_sha256", hashlib.sha256(der).hexdigest()),
            ("public_key_sha256", hashlib.sha256(public_der).hexdigest()),
        ):
            object.__setattr__(self, name, value)

    def __reduce_ex__(self, protocol):
        raise CredentialSnapshotError("snapshot_not_serializable")

    def diagnostic_projection(self):
        return {
            "company": self.owner.company_name, "owner_doctype": self.owner.doctype,
            "owner_name": self.owner.name, "source_kind": self.owner.source_kind,
            "environment": self.route.environment, "operation": self.route.endpoint,
            "purpose": self.authorization.purpose, "authorization_field": self.authorization.fieldname,
            "observed_at": self.observed_at.isoformat(),
            "certificate_der_sha256": self.certificate_der_sha256, "public_key_sha256": self.public_key_sha256,
            "key_certificate_bound": True, "authentication_certificate_bound": True,
            "database_snapshot_verified": False, "credential_epoch_verified": False,
            "certificate_trust_verified": False, "revocation_verified": False,
            "taxpayer_verified": False, "remote_authorization_verified": False,
            "dispatch_authorized": False, "replay_authorized": False,
        }
