"""Pure legacy credential separation observations, never a migration or selector.

Certificate identity comes from each purpose's authentication token, not from
the spelling of a legacy certificate field. Generated canonical certificate
text is transient for local key/time checks only; never returned for signing or
stored as a replacement. No trust, epoch, remote completion or replay is inferred.
"""

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import ArtifactEvidenceError
from zatca_erpgulf.zatca_erpgulf.certificate_evidence import (
    MAX_CERTIFICATE_TEXT_BYTES, parse_public_certificate_text,
)
from zatca_erpgulf.zatca_erpgulf.credential_material import (
    CredentialConfigurationError, CredentialOwner, authorization_field_for_owner,
    authorization_for_owner, certificate_value,
)
from zatca_erpgulf.zatca_erpgulf.credential_snapshot import (
    MAX_AUTH_TEXT, CredentialSnapshot, CredentialSnapshotError,
    authentication_certificate_der, validate_snapshot_owner, validate_snapshot_time,
)


@dataclass(frozen=True)
class StoredCertificateObservation:
    fieldname: str
    status: str
    certificate_der_sha256: str | None = None
    exact_text_sha256: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class PurposeCredentialObservation:
    purpose: str
    authorization_field: str
    status: str
    certificate_der_sha256: str | None = None
    public_key_sha256: str | None = None
    matching_certificate_fields: tuple[str, ...] = ()
    error_code: str | None = None


@dataclass(frozen=True)
class CredentialLifecycleAssessment:
    """Safe observations only; deliberately contains no key, certificate or auth."""

    company_name: str
    owner_doctype: str
    owner_name: str
    source_kind: str
    environment: str
    observed_at: datetime
    stored_certificates: tuple[StoredCertificateObservation, ...]
    purposes: tuple[PurposeCredentialObservation, ...]
    legacy_selection_status: str
    certificate_relationship: str
    review_codes: tuple[str, ...]

    def diagnostic_projection(self):
        return {
            "company": self.company_name, "owner_doctype": self.owner_doctype,
            "owner_name": self.owner_name, "source_kind": self.source_kind,
            "environment": self.environment, "observed_at": self.observed_at.isoformat(),
            "stored_certificates": [vars(value).copy() for value in self.stored_certificates],
            "purposes": [vars(value).copy() for value in self.purposes],
            "legacy_selection_status": self.legacy_selection_status,
            "certificate_relationship": self.certificate_relationship,
            "review_codes": list(self.review_codes),
            "database_snapshot_verified": False, "credential_epoch_verified": False,
            "certificate_trust_verified": False, "taxpayer_verified": False,
            "revocation_verified": False,
            "environment_authorization_verified": False, "remote_authorization_verified": False,
            "compliance_completion_verified": False, "migration_authorized": False,
            "dispatch_authorized": False, "replay_authorized": False,
        }


def _stored_certificate(fieldname, value):
    if value is None or (type(value) is str and len(value) <= MAX_CERTIFICATE_TEXT_BYTES and not value.strip()):
        return StoredCertificateObservation(fieldname, "MISSING")
    try:
        _, der = parse_public_certificate_text(value)
    except ArtifactEvidenceError as error:
        return StoredCertificateObservation(fieldname, "INVALID", error_code=error.code)
    return StoredCertificateObservation(
        fieldname, "OBSERVED", hashlib.sha256(der).hexdigest(),
        hashlib.sha256(value.encode("ascii")).hexdigest(),
    )


def _purpose(owner, route, observed_at, stored):
    purpose = route.required_credential
    auth_field = authorization_field_for_owner(owner, purpose)
    value = owner.values.get(auth_field)
    if value is None or (type(value) is str and len(value) <= MAX_AUTH_TEXT and not value.strip()):
        return PurposeCredentialObservation(purpose, auth_field, "MISSING")
    fingerprint = None
    matching = ()
    try:
        if type(value) is not str or len(value) > MAX_AUTH_TEXT:
            raise CredentialSnapshotError("snapshot_material_type" if type(value) is not str else "snapshot_material_size")
        authorization = authorization_for_owner(owner, purpose)
        der = authentication_certificate_der(authorization.header)
        fingerprint = hashlib.sha256(der).hexdigest()
        matching = tuple(value.fieldname for value in stored if value.certificate_der_sha256 == fingerprint)
        # Canonical text is transient evidence for local binding, NOT the text
        # used by historical certificate digests or a replacement signing value.
        canonical_text = base64.b64encode(der).decode("ascii")
        snapshot = CredentialSnapshot(owner, route, canonical_text, observed_at)
    except (CredentialSnapshotError, CredentialConfigurationError) as error:
        return PurposeCredentialObservation(
            purpose, auth_field, "REVIEW_REQUIRED", fingerprint,
            matching_certificate_fields=matching, error_code=error.code,
        )
    return PurposeCredentialObservation(
        purpose, auth_field, "TOKEN_MATERIAL_LOCALLY_BOUND", fingerprint,
        snapshot.public_key_sha256, matching,
    )


def inspect_legacy_credential_lifecycle(owner, settings, *, certificate_fields, observed_at):
    """Assess declared projections with alias names from the existing registry.

    This does not select a certificate, recover secret/password provenance, infer
    remote compliance, or authorize migration. The adapter must supply saved
    projections and registered alias order; this pure function cannot prove that.
    """
    validate_snapshot_owner(owner)
    validate_snapshot_time(observed_at)
    if not isinstance(settings, Mapping):
        raise CredentialSnapshotError("lifecycle_settings")
    if (
        type(certificate_fields) is not tuple or not 1 <= len(certificate_fields) <= 2
        or any(type(name) is not str or name not in ("custom_certificate", "custom_certficate") for name in certificate_fields)
        or len(set(certificate_fields)) != len(certificate_fields)
    ):
        raise CredentialSnapshotError("lifecycle_certificate_fields")
    config = MappingProxyType({name: settings.get(name) for name in ("custom_select", *ENVIRONMENT_FIELDS.values())})
    routes = tuple(resolve_api_route(config, operation) for operation in (
        "compliance/invoices", "invoices/reporting/single",
    ))
    fields = tuple(dict.fromkeys((
        "custom_private_key", *certificate_fields,
        *(authorization_field_for_owner(owner, purpose) for purpose in ("compliance", "production")),
    )))
    owner = CredentialOwner(owner.company_name, owner.doctype, owner.name, owner.source_kind,
                            MappingProxyType({name: owner.values.get(name) for name in fields}))
    stored = tuple(_stored_certificate(name, owner.values[name]) for name in certificate_fields)
    # Bound all legacy certificate inputs before calling the old selector.
    if any(value.status == "INVALID" for value in stored):
        selection = "INVALID_CERTIFICATE_FIELD"
    else:
        try:
            certificate_value(owner.values, certificate_fields)
            selection = "SELECTABLE_BY_LEGACY_POLICY"
        except CredentialConfigurationError as error:
            selection = "CERTIFICATE_ALIAS_CONFLICT" if error.code == "certificate_conflict" else "MISSING_CERTIFICATE"
    purposes = tuple(_purpose(owner, route, observed_at, stored) for route in routes)
    fingerprints = [value.certificate_der_sha256 for value in purposes]
    relationship = (
        "INCOMPLETE_TOKEN_EVIDENCE" if any(value is None for value in fingerprints)
        else "SAME_AUTH_CERTIFICATE" if fingerprints[0] == fingerprints[1]
        else "DIFFERENT_AUTH_CERTIFICATES"
    )
    review = []
    if selection != "SELECTABLE_BY_LEGACY_POLICY":
        review.append(selection)
    if relationship == "DIFFERENT_AUTH_CERTIFICATES":
        review.append("PURPOSE_SEPARATION_REQUIRED")
    for value in purposes:
        if value.status == "REVIEW_REQUIRED":
            review.append(value.purpose.upper() + "_MATERIAL_REVIEW_REQUIRED")
        if value.certificate_der_sha256 is not None and not value.matching_certificate_fields:
            review.append(value.purpose.upper() + "_CERTIFICATE_NOT_STORED")
    known = {value for value in fingerprints if value is not None}
    if any(value.certificate_der_sha256 not in known for value in stored if value.status == "OBSERVED"):
        review.append("UNMATCHED_STORED_CERTIFICATE")
    return CredentialLifecycleAssessment(
        owner.company_name, owner.doctype, owner.name, owner.source_kind,
        routes[0].environment, observed_at, stored, purposes, selection,
        relationship, tuple(review),
    )
