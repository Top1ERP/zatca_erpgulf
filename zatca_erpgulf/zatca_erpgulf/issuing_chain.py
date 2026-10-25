"""Pure declared new-EGS state and exact-artifact chain transitions.

No Frappe, credentials, current settings, HTTP, clock, UUID allocation or reset
API. A declaration is NOT authenticated enrollment evidence. Future services
must verify enrollment/tenant/epoch provenance before adopting this contract.
Renewal and migration are intentionally not inferred from certificate changes.
"""

import base64
import binascii
from dataclasses import dataclass, field

from zatca_erpgulf.zatca_erpgulf.api_routing import ENVIRONMENT_FIELDS
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import (
    DeclaredCredentialEpoch, IssuanceContractError, PreparedIssuanceCandidate,
    _canonical_uuid, _fingerprint, _identity_text, _sha256,
)


MAX_CHAIN_ICV = 10**64 - 1  # Internal parser/storage bound, not a regulatory limit.


class IssuingChainError(ValueError):
    """Static English diagnostic code; never include raw XML/settings/errors."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _check(value, code, validator):
    try:
        validator(value, code)
    except IssuanceContractError:
        raise IssuingChainError(code) from None


def _digest(value):
    """Require an exact canonical binary SHA-256 digest for generated tails."""
    if type(value) is not str or len(value) != 44:
        raise IssuingChainError("chain_digest")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise IssuingChainError("chain_digest") from None
    if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != value:
        raise IssuingChainError("chain_digest")


@dataclass(frozen=True)
class DeclaredChainRegistration:
    """Explicit NEW_EGS binding, not proof that a certificate is new/authorized.

    registration_id and chain_id are opaque server mapping references, never
    hashes of auth text. Epoch rotation/renewal requires separate reviewed policy.
    The evidence fingerprint names retained enrollment evidence, not its truth.
    """

    chain_id: str
    registration_id: str
    company_name: str
    seller_tax_id: str
    environment: str
    credential_epoch: DeclaredCredentialEpoch
    enrollment_evidence_sha256: str
    origin: str = "NEW_EGS"

    def __post_init__(self):
        _check(self.chain_id, "chain_id", _canonical_uuid)
        _check(self.registration_id, "chain_registration_id", _canonical_uuid)
        _check(self.company_name, "chain_company", _identity_text)
        _check(self.seller_tax_id, "chain_seller", _identity_text)
        _check(self.enrollment_evidence_sha256, "chain_enrollment_evidence", _sha256)
        if type(self.environment) is not str or self.environment not in ENVIRONMENT_FIELDS:
            raise IssuingChainError("chain_environment")
        if type(self.credential_epoch) is not DeclaredCredentialEpoch:
            raise IssuingChainError("chain_epoch")
        if self.origin != "NEW_EGS":
            raise IssuingChainError("chain_origin_requires_review")

    def public_binding(self):
        """Storage declarations only; no secrets or claim of remote provenance."""
        return {
            "chain_id": self.chain_id, "registration_id": self.registration_id,
            "company_name": self.company_name, "seller_tax_id": self.seller_tax_id,
            "environment": self.environment, "origin": self.origin,
            "enrollment_evidence_sha256": self.enrollment_evidence_sha256,
            "credential_epoch": {name: getattr(self.credential_epoch, name) for name in (
                "owner_doctype", "owner_name", "version_id", "certificate_der_sha256",
                "public_key_sha256", "purpose",
            )},
        }


@dataclass(frozen=True)
class IssuingChainState:
    """Last locally recorded generated artifact, not last accepted response.

    Genesis is explicit zero position plus the published seed. A missing PIH or
    absent invoice file cannot construct genesis through a legacy fallback here.
    """

    registration: DeclaredChainRegistration = field(repr=False)
    last_icv: int
    previous_hash: str = field(repr=False)
    tail_key_sha256: str | None = None
    tail_manifest_sha256: str | None = None
    state_sha256: str = field(init=False)

    def __post_init__(self):
        if type(self.registration) is not DeclaredChainRegistration:
            raise IssuingChainError("chain_registration")
        if type(self.last_icv) is not int or not 0 <= self.last_icv <= MAX_CHAIN_ICV:
            raise IssuingChainError("chain_counter")
        if self.last_icv == 0:
            if self.previous_hash != INITIAL_PREVIOUS_HASH or self.tail_key_sha256 is not None or self.tail_manifest_sha256 is not None:
                raise IssuingChainError("chain_genesis")
        else:
            _digest(self.previous_hash)
            _check(self.tail_key_sha256, "chain_tail_key", _sha256)
            _check(self.tail_manifest_sha256, "chain_tail_manifest", _sha256)
        object.__setattr__(self, "state_sha256", _fingerprint(self.storage_projection()))

    def storage_projection(self):
        """Protected local storage material, NOT a UI/log dump."""
        return {
            "schema_version": 1, "registration": self.registration.public_binding(),
            "last_icv": self.last_icv, "previous_hash": self.previous_hash,
            "tail_key_sha256": self.tail_key_sha256,
            "tail_manifest_sha256": self.tail_manifest_sha256,
        }

    def diagnostic_projection(self):
        return {
            "chain_id": self.registration.chain_id, "last_icv": self.last_icv,
            "state_sha256": self.state_sha256,
            "registration_verified": False, "persistence_verified": False,
            "signature_verified": False, "dispatch_authorized": False,
        }


def initialize_declared_chain(registration):
    """Only initialize an explicitly supplied new-registration declaration."""
    return IssuingChainState(registration, 0, INITIAL_PREVIOUS_HASH)


def validate_chain_candidate(registration, candidate):
    """Bind source/environment/epoch without changing UUID, ICV or XML bytes."""
    if type(registration) is not DeclaredChainRegistration or type(candidate) is not PreparedIssuanceCandidate:
        raise IssuingChainError("chain_candidate")
    scope = candidate.context.scope
    if (
        scope.chain_id != registration.chain_id or scope.company_name != registration.company_name
        or scope.seller_tax_id != registration.seller_tax_id or scope.environment != registration.environment
    ):
        raise IssuingChainError("chain_candidate_scope")
    if candidate.context.credential_epoch != registration.credential_epoch:
        raise IssuingChainError("chain_candidate_epoch")


def record_generated_candidate(before, candidate):
    """Advance on local exact-artifact issuance, never HTTP acceptance/status.

    This validates declared digests, not the cryptographic signature/invoice hash.
    A repository must atomically retain the exact artifact and the resulting head.
    """
    if type(before) is not IssuingChainState:
        raise IssuingChainError("chain_state")
    validate_chain_candidate(before.registration, candidate)
    if before.last_icv == MAX_CHAIN_ICV:
        raise IssuingChainError("chain_counter_exhausted")
    if candidate.artifact.icv != before.last_icv + 1:
        raise IssuingChainError("chain_candidate_counter")
    if candidate.artifact.previous_hash != before.previous_hash:
        raise IssuingChainError("chain_candidate_previous_hash")
    return IssuingChainState(
        before.registration, candidate.artifact.icv, candidate.artifact.invoice_digest,
        candidate.key_sha256, candidate.manifest_sha256,
    )
