"""Exact Compliance exchange observations bound to ONE staged version and CSR.

No HTTP, database, clock, legacy status writes or activation. Matching supplied
bytes is not proof that ZATCA issued/received them. Future trusted capture and
protected durable storage are mandatory; never turn these diagnostics into an
activation flag. Raw CSR/request/response bytes are private audit material.
"""

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from zatca_erpgulf.zatca_erpgulf.api_routing import ApiRoute, ENVIRONMENT_FIELDS, resolve_api_route
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import MAX_XML_BYTES, inspect_invoice_artifact
from zatca_erpgulf.zatca_erpgulf.certificate_evidence import inspect_embedded_certificate
from zatca_erpgulf.zatca_erpgulf.compliance_result import compliance_result_status, is_already_completed_response
from zatca_erpgulf.zatca_erpgulf.compliance_types import COMPLIANCE_TYPES
from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialBundleManifest, _validate
from zatca_erpgulf.zatca_erpgulf.credential_snapshot import validate_snapshot_time
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid, _invoice_classification
from zatca_erpgulf.zatca_erpgulf.response_assessment import _validation
from zatca_erpgulf.zatca_erpgulf.response_json import MAX_RESPONSE_BYTES, parse_wire_response


MAX_CSR_BYTES = 64 * 1024
MAX_EXCHANGES = 64
MAX_CHECK_SET_BYTES = 32 * 1024 * 1024
# Labels/codes remain the existing application's six-type contract. Gateway step
# names are derived from XML, not a caller-supplied label or response marker.
STEP_CLASSIFICATION = {
    "SIMPLIFIED": ("Simplified Invoice", "388", "02"),
    "STANDARD": ("Standard Invoice", "388", "01"),
    "SIMPLIFIED_CREDIT_NOTE": ("Simplified Credit Note", "381", "02"),
    "STANDARD_CREDIT_NOTE": ("Standard Credit Note", "381", "01"),
    "SIMPLIFIED_DEBIT_NOTE": ("Simplified Debit Note", "383", "02"),
    "STANDARD_DEBIT_NOTE": ("Standard Debit Note", "383", "01"),
}


class ComplianceEvidenceError(ValueError):
    """Static code only, never response messages, CSR subjects or invoice bytes."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _reference(value, code, validator):
    try:
        _validate(value, code, validator)
    except ValueError:
        raise ComplianceEvidenceError(code) from None


def _time(value):
    try:
        validate_snapshot_time(value)
    except ValueError:
        raise ComplianceEvidenceError("compliance_time") from None


def _digest(value):
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class ComplianceRequirements:
    """Derive required steps from a bounded signature-valid CSR, not UI settings.

    Key equality does not prove this CSR generated the staged certificate: a
    renewal can reuse a key. Exact CSR-to-issuance provenance is still unverified.
    """

    storage_namespace: str
    manifest: CredentialBundleManifest = field(repr=False)
    csr_der: bytes = field(repr=False)
    csr_sha256: str = field(init=False)
    functionality_map: str = field(init=False)
    required_steps: tuple = field(init=False)
    seller_tax_id: str = field(init=False, repr=False)

    def __post_init__(self):
        _reference(self.storage_namespace, "compliance_namespace", _canonical_uuid)
        if type(self.manifest) is not CredentialBundleManifest or self.manifest.slot.purpose != "compliance":
            raise ComplianceEvidenceError("compliance_manifest")
        if type(self.csr_der) is not bytes or not 0 < len(self.csr_der) <= MAX_CSR_BYTES:
            raise ComplianceEvidenceError("compliance_csr_size")
        try:
            csr = x509.load_der_x509_csr(self.csr_der)
            if csr.public_bytes(serialization.Encoding.DER) != self.csr_der or not csr.is_signature_valid:
                raise ComplianceEvidenceError("compliance_csr_signature")
            public = csr.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            if _digest(public) != self.manifest.public_key_sha256:
                raise ComplianceEvidenceError("compliance_csr_key")
            names = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DirectoryName)
            titles = [attribute.value for name in names for attribute in name.get_attributes_for_oid(NameOID.TITLE)]
            if len(names) != 1 or len(titles) != 1 or titles[0] not in ("1000", "0100", "1100"):
                raise ComplianceEvidenceError("compliance_csr_functionality")
            identifiers = names[0].get_attributes_for_oid(NameOID.USER_ID)
            if len(identifiers) != 1 or re.fullmatch(r"3[0-9]{13}3", identifiers[0].value) is None:
                raise ComplianceEvidenceError("compliance_csr_taxpayer")
        except ComplianceEvidenceError:
            raise
        except (ValueError, TypeError, x509.ExtensionNotFound, x509.DuplicateExtension, UnsupportedAlgorithm):
            raise ComplianceEvidenceError("compliance_csr") from None
        functionality = titles[0]
        steps = tuple(step for step in STEP_CLASSIFICATION if (
            functionality[0] == "1" if step.startswith("STANDARD") else functionality[1] == "1"
        ))
        object.__setattr__(self, "csr_sha256", _digest(self.csr_der))
        object.__setattr__(self, "functionality_map", functionality)
        object.__setattr__(self, "required_steps", steps)
        object.__setattr__(self, "seller_tax_id", identifiers[0].value)

    def __reduce_ex__(self, protocol):
        raise ComplianceEvidenceError("compliance_not_pickleable")


def _route(route, manifest):
    if (type(route) is not ApiRoute or route.endpoint != "compliance/invoices"
            or route.required_credential != "compliance" or route.environment != manifest.slot.environment):
        raise ComplianceEvidenceError("compliance_route")
    try:
        suffix = "/compliance/invoices"
        if type(route.url) is not str or not route.url.endswith(suffix) or len(route.url) > 4096:
            raise ComplianceEvidenceError("compliance_route")
        checked = resolve_api_route({"custom_select": route.environment,
                                    ENVIRONMENT_FIELDS[route.environment]: route.url[:-len(suffix)]}, route.endpoint)
        if checked != route:
            raise ComplianceEvidenceError("compliance_route")
    except ValueError:
        raise ComplianceEvidenceError("compliance_route") from None


def _request(content, manifest):
    try:
        body = parse_wire_response(content)
        if set(body) != {"invoiceHash", "uuid", "invoice"} or any(type(value) is not str for value in body.values()):
            raise ComplianceEvidenceError("compliance_request_fields")
        encoded = body["invoice"].translate(str.maketrans("", "", " \t\r\n"))
        if len(encoded) > 4 * ((MAX_XML_BYTES + 2) // 3):
            raise ComplianceEvidenceError("compliance_request_xml_size")
        xml = base64.b64decode(encoded, validate=True)
        artifact = inspect_invoice_artifact(xml)
        certificate = inspect_embedded_certificate(xml)
        code, indicator = _invoice_classification(xml)
        if body["uuid"] != artifact.uuid or body["invoiceHash"] != artifact.invoice_digest:
            raise ComplianceEvidenceError("compliance_request_identity")
        if (certificate.der_sha256 != manifest.certificate_der_sha256
                or certificate.public_key_sha256 != manifest.public_key_sha256):
            raise ComplianceEvidenceError("compliance_request_certificate")
        matches = [step for step, (_, expected, prefix) in STEP_CLASSIFICATION.items()
                   if code == expected and indicator[:2] == prefix]
        if len(matches) != 1:
            raise ComplianceEvidenceError("compliance_request_type")
        return artifact, matches[0]
    except ComplianceEvidenceError:
        raise
    except (ValueError, TypeError, binascii.Error):
        raise ComplianceEvidenceError("compliance_request") from None


def _assess_response(status, content, step):
    if status is None:
        return "TRANSPORT_UNKNOWN", ()
    outcome = "AUTHORIZATION_FAILED" if status in (401, 403) else "HTTP_REJECTION_OBSERVED"
    try:
        body = parse_wire_response(content)
    except ValueError:
        return "UNCONFIRMED" if status in (200, 202, 406) else outcome, ("compliance_response_json",)
    validation, _, issues = _validation(body)
    if issues:
        return "UNCONFIRMED", issues
    if "_zatca_compliance_status" in body:
        return "UNCONFIRMED", ("compliance_response_local_marker",)
    if status in (200, 202) and compliance_result_status(body) == "PASS":
        return "PASS_MATCHED_OBSERVATION", ()
    if status == 406 and is_already_completed_response(status, body):
        expected = "Compliance check already completed for " + step + "."
        errors = body["validationResults"]["errorMessages"]
        if (not body["validationResults"].get("infoMessages", [])
                and not body["validationResults"].get("warningMessages", [])
                and all(error.get("category") == "Compliance-Check" and error.get("message") == expected for error in errors)):
            return "ALREADY_COMPLETED_MATCHED_OBSERVATION", ()
        return "UNCONFIRMED", ("compliance_previous_step_mismatch",)
    if status in (200, 202, 406):
        return "UNCONFIRMED", ("compliance_response_unconfirmed",)
    if status in (401, 403):
        return "AUTHORIZATION_FAILED", ()
    return "VALIDATION_REJECTION_MATCHED" if validation == "ERROR" else outcome, ()


@dataclass(frozen=True)
class ComplianceExchangeObservation:
    """One explicit attempt's exact wire bytes; no raw Authorization is retained.

    Fields are supplied observations, not verified transport provenance. A timeout
    cannot be replaced by a fabricated success; a late observation needs its own
    explicit identity until trusted durable capture defines reconciliation.
    """

    requirements: ComplianceRequirements = field(repr=False)
    exchange_id: str
    route: ApiRoute = field(repr=False)
    started_at: datetime
    received_at: datetime | None
    request_bytes: bytes = field(repr=False)
    http_status: int | None
    response_bytes: bytes | None = field(repr=False)
    step: str = field(init=False)
    request_sha256: str = field(init=False)
    response_sha256: str | None = field(init=False)
    observation_sha256: str = field(init=False)
    outcome: str = field(init=False)
    issues: tuple = field(init=False)
    invoice_uuid: str = field(init=False, repr=False)
    artifact_sha256: str = field(init=False)

    def __post_init__(self):
        if type(self.requirements) is not ComplianceRequirements:
            raise ComplianceEvidenceError("compliance_requirements")
        _reference(self.exchange_id, "compliance_exchange_id", _canonical_uuid)
        _time(self.started_at)
        if self.started_at < self.requirements.manifest.prepared_at:
            raise ComplianceEvidenceError("compliance_time_order")
        _route(self.route, self.requirements.manifest)
        artifact, step = _request(self.request_bytes, self.requirements.manifest)
        if artifact.seller_tax_id != self.requirements.seller_tax_id:
            raise ComplianceEvidenceError("compliance_request_taxpayer")
        if self.http_status is None:
            if self.response_bytes is not None or self.received_at is not None:
                raise ComplianceEvidenceError("compliance_receipt_fields")
        else:
            if type(self.http_status) is not int or not 100 <= self.http_status <= 599:
                raise ComplianceEvidenceError("compliance_http_status")
            if type(self.response_bytes) is not bytes or not 0 < len(self.response_bytes) <= MAX_RESPONSE_BYTES:
                raise ComplianceEvidenceError("compliance_receipt_size")
            _time(self.received_at)
            if self.received_at < self.started_at:
                raise ComplianceEvidenceError("compliance_time_order")
        outcome, issues = _assess_response(self.http_status, self.response_bytes, step)
        for name, value in (("step", step), ("outcome", outcome), ("issues", issues),
                            ("invoice_uuid", artifact.uuid), ("artifact_sha256", artifact.file_sha256),
                            ("request_sha256", _digest(self.request_bytes)),
                            ("response_sha256", None if self.response_bytes is None else _digest(self.response_bytes))):
            object.__setattr__(self, name, value)
        # Length-prefix every component: do not concatenate ambiguous declarations.
        parts = (self.requirements.storage_namespace.encode(), self.requirements.manifest.encode(),
                 self.requirements.csr_der, self.exchange_id.encode(), repr(self.route).encode(),
                 self.started_at.isoformat().encode(), str(self.received_at).encode(),
                 self.request_bytes, str(self.http_status).encode(), self.response_bytes or b"")
        digest = hashlib.sha256()
        for part in parts:
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
        object.__setattr__(self, "observation_sha256", digest.hexdigest())

    def diagnostic_projection(self):
        return {"exchange_id": self.exchange_id, "step": self.step,
                "validation_type": STEP_CLASSIFICATION[self.step][0],
                "legacy_type_code": COMPLIANCE_TYPES[STEP_CLASSIFICATION[self.step][0]],
                "http_status": self.http_status, "outcome": self.outcome, "issues": list(self.issues),
                "request_sha256": self.request_sha256, "response_sha256": self.response_sha256,
                "artifact_sha256": self.artifact_sha256, "observation_sha256": self.observation_sha256}

    def __reduce_ex__(self, protocol):
        raise ComplianceEvidenceError("compliance_not_pickleable")


@dataclass(frozen=True)
class ComplianceCheckSet:
    """Bound observations, never a remote-completion or activation certificate."""

    requirements: ComplianceRequirements = field(repr=False)
    exchanges: tuple = field(repr=False)

    def __post_init__(self):
        if type(self.requirements) is not ComplianceRequirements:
            raise ComplianceEvidenceError("compliance_requirements")
        if type(self.exchanges) is not tuple or len(self.exchanges) > MAX_EXCHANGES:
            raise ComplianceEvidenceError("compliance_exchanges")
        identities, invoice_artifacts, route, total_bytes = {}, {}, None, 0
        for exchange in self.exchanges:
            if type(exchange) is not ComplianceExchangeObservation or exchange.requirements != self.requirements:
                raise ComplianceEvidenceError("compliance_exchange_binding")
            if route is not None and exchange.route != route:
                raise ComplianceEvidenceError("compliance_exchange_gateway")
            route = exchange.route
            previous = identities.get(exchange.exchange_id)
            if previous is not None and previous != exchange:
                raise ComplianceEvidenceError("compliance_exchange_conflict")
            if previous is None:
                total_bytes += len(exchange.request_bytes) + len(exchange.response_bytes or b"")
                if total_bytes > MAX_CHECK_SET_BYTES:
                    raise ComplianceEvidenceError("compliance_check_set_size")
            identities[exchange.exchange_id] = exchange
            prior_artifact = invoice_artifacts.get(exchange.invoice_uuid)
            if prior_artifact is not None and prior_artifact != exchange.artifact_sha256:
                raise ComplianceEvidenceError("compliance_sample_uuid_conflict")
            invoice_artifacts[exchange.invoice_uuid] = exchange.artifact_sha256

    def diagnostic_projection(self):
        unique = {exchange.exchange_id: exchange for exchange in self.exchanges}
        matched = {exchange.step for exchange in unique.values() if exchange.outcome in (
            "PASS_MATCHED_OBSERVATION", "ALREADY_COMPLETED_MATCHED_OBSERVATION")}
        required = self.requirements.required_steps
        missing = [step for step in required if step not in matched]
        return {"state": "COMPLETE_MATCHED_OBSERVATIONS" if not missing else "INCOMPLETE_OBSERVATIONS",
                "version_id": self.requirements.manifest.version_id,
                "flow_id": self.requirements.manifest.flow_id, "csr_sha256": self.requirements.csr_sha256,
                "functionality_map": self.requirements.functionality_map, "required_steps": list(required),
                "missing_steps": missing, "exchanges": [exchange.diagnostic_projection() for exchange in unique.values()],
                "remote_receipt_verified": False, "csr_issuance_provenance_verified": False,
                "compliance_completion_verified": False, "activation_authorized": False,
                "dispatch_authorized": False, "replay_authorized": False}

    def __reduce_ex__(self, protocol):
        raise ComplianceEvidenceError("compliance_not_pickleable")
