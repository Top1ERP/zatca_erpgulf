"""Pure immutable prepared-artifact contract, not a persisted issuance ledger.

Declarations are internally consistent, not trusted provenance. Never allocate,
sign, normalize XML, load credentials, write records, authorize replay or send
HTTP here. Persistence, locks, verified epochs and acceptance remain separate
implementation gates. This contract covers the application's signed preparation
format only; it is not a regulatory claim about every standard invoice format.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from uuid import UUID

from zatca_erpgulf.zatca_erpgulf.api_routing import (
    ENVIRONMENT_FIELDS, ApiConfigurationError, ApiRoute, resolve_api_route,
)
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import (
    NS, ArtifactEvidence, ArtifactEvidenceError, inspect_invoice_artifact,
    parse_diagnostic_xml,
)
from zatca_erpgulf.zatca_erpgulf.certificate_evidence import (
    EmbeddedCertificateEvidence, inspect_embedded_certificate,
)


SCHEMA_VERSION = 1
MAX_ISSUANCE_VERSION = 2**31 - 1
PHASE2_OPERATIONS = {"invoices/reporting/single", "invoices/clearance/single"}
INVOICE_TYPE_CODES = {"388", "381", "383", "386"}


class IssuanceContractError(ValueError):
    """Static code only; never include XML, keys, routes or caller values."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _identity_text(value, code):
    # An internal identity limit, not a ZATCA field-format validator. Slash and
    # Unicode names are legitimate identities; they are never used as filenames.
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or len(value) > 140 or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise IssuanceContractError(code)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise IssuanceContractError(code) from None


def _canonical_uuid(value, code):
    if not isinstance(value, str):
        raise IssuanceContractError(code)
    try:
        canonical = str(UUID(value))
    except ValueError:
        raise IssuanceContractError(code) from None
    if value != canonical or canonical == "00000000-0000-0000-0000-000000000000":
        raise IssuanceContractError(code)


def _sha256(value, code):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise IssuanceContractError(code)


def _fingerprint(value):
    """Versioned internal canonical JSON, never XML/invoice canonicalization."""
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuanceScope:
    """Declared invoice/version key with an explicitly mapped stable chain ID.

    chain_id must eventually come from controlled chain mapping, not raw auth or
    certificate text. legacy_issuing_unit preserves the historical reference;
    merely supplying these values does not verify that mapping.
    """

    doctype: str
    invoice_name: str
    company_name: str
    seller_tax_id: str
    environment: str
    chain_id: str
    legacy_issuing_unit: str
    issuance_version: int

    def __post_init__(self):
        if self.doctype not in ("Sales Invoice", "POS Invoice"):
            raise IssuanceContractError("source_doctype")
        for value, code in (
            (self.invoice_name, "invoice_name"), (self.company_name, "company_name"),
            (self.seller_tax_id, "seller_tax_id"),
            (self.legacy_issuing_unit, "issuing_unit_reference"),
        ):
            _identity_text(value, code)
        if not isinstance(self.environment, str) or self.environment not in ENVIRONMENT_FIELDS:
            raise IssuanceContractError("environment")
        _canonical_uuid(self.chain_id, "chain_id")
        if (
            type(self.issuance_version) is not int
            or not 1 <= self.issuance_version <= MAX_ISSUANCE_VERSION
        ):
            raise IssuanceContractError("issuance_version")

    def key_projection(self):
        """Exclude content/epoch/current settings so drift cannot hide as a new key."""
        return {
            "schema_version": SCHEMA_VERSION, "purpose": "production",
            "doctype": self.doctype, "invoice": self.invoice_name,
            "company": self.company_name, "environment": self.environment,
            "chain_id": self.chain_id, "issuance_version": self.issuance_version,
        }


@dataclass(frozen=True)
class DeclaredCredentialEpoch:
    """No keys/tokens: an unverified version reference and public fingerprints."""

    owner_doctype: str
    owner_name: str
    version_id: str
    certificate_der_sha256: str
    public_key_sha256: str
    purpose: str = "production"

    def __post_init__(self):
        if self.owner_doctype not in ("Company", "ZATCA Multiple Setting"):
            raise IssuanceContractError("credential_owner_doctype")
        _identity_text(self.owner_name, "credential_owner_name")
        _canonical_uuid(self.version_id, "credential_version_id")
        _sha256(self.certificate_der_sha256, "credential_certificate_fingerprint")
        _sha256(self.public_key_sha256, "credential_public_key_fingerprint")
        if self.purpose != "production":
            raise IssuanceContractError("credential_purpose")


@dataclass(frozen=True)
class PreparationContext:
    """Pinned declarations, not the live signing/HTTP credential snapshot.

    The source digest must eventually be computed from a versioned ERP snapshot
    by an adapter. A caller-provided digest cannot prove source accounting parity.
    """

    scope: IssuanceScope
    credential_epoch: DeclaredCredentialEpoch
    route: ApiRoute = field(repr=False)
    source_snapshot_sha256: str

    def __post_init__(self):
        if (
            type(self.scope) is not IssuanceScope
            or type(self.credential_epoch) is not DeclaredCredentialEpoch
        ):
            raise IssuanceContractError("preparation_context")
        _sha256(self.source_snapshot_sha256, "source_snapshot_fingerprint")
        if (
            type(self.route) is not ApiRoute or not isinstance(self.route.endpoint, str)
            or self.route.endpoint not in PHASE2_OPERATIONS
        ):
            raise IssuanceContractError("submission_operation")
        if self.route.environment != self.scope.environment:
            raise IssuanceContractError("route_environment")
        if self.route.required_credential != self.credential_epoch.purpose:
            raise IssuanceContractError("route_credential_purpose")
        suffix = "/" + self.route.endpoint
        if (
            not isinstance(self.route.url, str) or len(self.route.url) > 4096
            or not self.route.url.endswith(suffix)
        ):
            raise IssuanceContractError("route_configuration")
        try:
            self.route.url.encode("utf-8")
        except UnicodeEncodeError:
            raise IssuanceContractError("route_configuration") from None
        fieldname = ENVIRONMENT_FIELDS[self.scope.environment]
        try:
            resolved = resolve_api_route(
                {"custom_select": self.scope.environment, fieldname: self.route.url[:-len(suffix)]},
                self.route.endpoint,
            )
        except ApiConfigurationError:
            raise IssuanceContractError("route_configuration") from None
        if resolved != self.route:
            raise IssuanceContractError("route_configuration")


def _invoice_classification(content):
    root = parse_diagnostic_xml(content)
    nodes = root.xpath("./cbc:InvoiceTypeCode", namespaces=NS)
    if len(nodes) != 1 or len(nodes[0]):
        raise IssuanceContractError("invoice_type")
    code, indicator = (nodes[0].text or "").strip(), nodes[0].get("name")
    if code not in INVOICE_TYPE_CODES:
        raise IssuanceContractError("invoice_type_code")
    if not isinstance(indicator, str) or not re.fullmatch(r"(?:01|02)[01]{5}", indicator):
        raise IssuanceContractError("invoice_type_indicator")
    return code, indicator


@dataclass(frozen=True)
class PreparedIssuanceCandidate:
    """Internally consistent exact-byte candidate; no persistence or replay grant.

    Derived fields are recomputed on every construction, including dataclass
    replace. They cannot be supplied as independent caller claims. XML is hidden
    from repr; do not asdict/serialize this object into logs or user messages.
    """

    context: PreparationContext
    xml_bytes: bytes = field(repr=False)
    artifact: ArtifactEvidence = field(init=False, repr=False)
    certificate: EmbeddedCertificateEvidence = field(init=False)
    invoice_type_code: str = field(init=False)
    invoice_type_indicator: str = field(init=False)
    key_sha256: str = field(init=False)
    manifest_sha256: str = field(init=False)

    def __post_init__(self):
        if type(self.context) is not PreparationContext:
            raise IssuanceContractError("preparation_context")
        try:
            artifact = inspect_invoice_artifact(self.xml_bytes)
            code, indicator = _invoice_classification(self.xml_bytes)
            certificate = inspect_embedded_certificate(self.xml_bytes)
        except ArtifactEvidenceError as error:
            raise IssuanceContractError(error.code) from None
        scope, epoch = self.context.scope, self.context.credential_epoch
        # UUID/ICV come only from the immutable bytes, never current invoice fields.
        if artifact.invoice_id != scope.invoice_name:
            raise IssuanceContractError("invoice_id_mismatch")
        if artifact.seller_tax_id != scope.seller_tax_id:
            raise IssuanceContractError("seller_tax_id_mismatch")
        expected_operation = (
            "invoices/reporting/single" if indicator[:2] == "02"
            else "invoices/clearance/single"
        )
        if self.context.route.endpoint != expected_operation:
            raise IssuanceContractError("invoice_operation_mismatch")
        if epoch.certificate_der_sha256 != certificate.der_sha256:
            raise IssuanceContractError("credential_certificate_mismatch")
        if epoch.public_key_sha256 != certificate.public_key_sha256:
            raise IssuanceContractError("credential_public_key_mismatch")
        object.__setattr__(self, "artifact", artifact)
        object.__setattr__(self, "certificate", certificate)
        object.__setattr__(self, "invoice_type_code", code)
        object.__setattr__(self, "invoice_type_indicator", indicator)
        object.__setattr__(self, "key_sha256", _fingerprint(scope.key_projection()))
        object.__setattr__(self, "manifest_sha256", _fingerprint({
            **scope.key_projection(), "seller_tax_id": scope.seller_tax_id,
            "legacy_issuing_unit": scope.legacy_issuing_unit,
            "credential_owner_doctype": epoch.owner_doctype,
            "credential_owner_name": epoch.owner_name, "credential_version_id": epoch.version_id,
            "certificate_der_sha256": certificate.der_sha256,
            "public_key_sha256": certificate.public_key_sha256,
            "source_snapshot_sha256": self.context.source_snapshot_sha256,
            "route_url": self.context.route.url, "endpoint": self.context.route.endpoint,
            "file_sha256": artifact.file_sha256,
            "uuid": artifact.uuid, "icv": artifact.icv,
            "invoice_digest": artifact.invoice_digest, "previous_hash": artifact.previous_hash,
            "invoice_type_code": code, "invoice_type_indicator": indicator,
            "certificate_element_text_sha256": certificate.element_text_sha256,
        }))

    def diagnostic_projection(self):
        """Return bounded non-secret facts, explicitly without verification flags."""
        return {
            **self.context.scope.key_projection(), "key_sha256": self.key_sha256,
            "manifest_sha256": self.manifest_sha256,
            "uuid": self.artifact.uuid, "icv": self.artifact.icv,
            "invoice_type_code": self.invoice_type_code,
            "invoice_type_indicator": self.invoice_type_indicator,
            "file_sha256": self.artifact.file_sha256, "byte_length": self.artifact.byte_length,
            "certificate_der_sha256": self.certificate.der_sha256,
            "public_key_sha256": self.certificate.public_key_sha256,
            "source_snapshot_sha256": self.context.source_snapshot_sha256,
            "persistence_verified": False, "credential_epoch_verified": False,
            "chain_mapping_verified": False, "source_snapshot_verified": False,
            "counter_continuity_verified": False, "xsd_verified": False,
            "invoice_hash_verified": False, "qr_verified": False,
            "signature_verified": False, "remote_acceptance_verified": False,
            "replay_authorized": False,
        }


def compare_prepared_candidates(existing, proposed):
    """Describe drift without authorizing insertion, replacement, or replay."""
    if (
        type(existing) is not PreparedIssuanceCandidate
        or type(proposed) is not PreparedIssuanceCandidate
    ):
        raise IssuanceContractError("issuance_candidate")
    if (
        existing.key_sha256 != proposed.key_sha256
        or existing.context.scope.key_projection() != proposed.context.scope.key_projection()
    ):
        return ("different_issuance_key",)
    old_context, new_context = existing.context, proposed.context
    comparisons = (
        (existing.xml_bytes, proposed.xml_bytes, "issued_xml_bytes_changed"),
        (
            old_context.scope.seller_tax_id, new_context.scope.seller_tax_id,
            "seller_tax_id_changed",
        ),
        (
            old_context.scope.legacy_issuing_unit, new_context.scope.legacy_issuing_unit,
            "issuing_unit_reference_changed",
        ),
        (old_context.credential_epoch, new_context.credential_epoch, "credential_epoch_changed"),
        (old_context.route, new_context.route, "api_route_changed"),
        (
            old_context.source_snapshot_sha256, new_context.source_snapshot_sha256,
            "source_snapshot_changed",
        ),
    )
    return tuple(code for before, after, code in comparisons if before != after)
