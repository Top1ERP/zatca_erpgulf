"""Unactivated in-memory key/CSR preparation, never an active renewal service.

No saved source, existing key, secret store, HTTP, clock or filesystem is read.
The explicit context is only a declaration. A future coordinator must enforce
permissions, source/epoch provenance, protected custody and explicit activation.
Never log, queue, serialize as a dict, or return this protected object to a UI.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from cryptography import x509
from cryptography.x509.oid import ExtensionOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from zatca_erpgulf.zatca_erpgulf.credential_bundle import CredentialSlot
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialOwner
from zatca_erpgulf.zatca_erpgulf.credential_snapshot import validate_snapshot_owner, validate_snapshot_time
from zatca_erpgulf.zatca_erpgulf.csr_template import (
    CSR_LABELS, CSR_EXTENSION_OID, csr_attributes, csr_builder, encode_customoid,
)
from zatca_erpgulf.zatca_erpgulf.issuance_candidate import _canonical_uuid
from zatca_erpgulf.zatca_erpgulf.saved_form_source import saved_form_revision


CONFIG_FIELDS = (
    "csr.common.name", "csr.serial.number", "csr.organization.identifier",
    "csr.organization.unit.name", "csr.organization.name", "csr.country.name",
    "csr.invoice.type", "csr.location.address", "csr.industry.business.category",
)
MAX_CONFIG_BYTES = 16384
MAX_MATERIAL_BYTES = 65536
ERROR_CODES = frozenset(("csr_draft_context", "csr_draft_configuration", "csr_draft_generation",
                         "csr_draft_material", "csr_draft_preparation", "csr_draft_not_pickleable"))


class CSRDraftError(ValueError):
    """Static allowlisted code, never material or raw crypto/parser diagnostics."""

    def __init__(self, code):
        self.code = code if type(code) is str and code in ERROR_CODES else "csr_draft_preparation"
        super().__init__(self.code)


@dataclass(frozen=True, repr=False)
class CSRPreparationContext:
    """Declared source/version/time only; not saved-row or rotation authority."""

    slot: CredentialSlot
    company_name: str
    source_kind: str
    source_revision: str
    draft_id: str
    flow_id: str
    prepared_at: datetime

    def __post_init__(self):
        valid = False
        try:
            if (type(self.slot) is not CredentialSlot or type(self.slot.purpose) is not str
                    or self.slot.purpose != "compliance"
                    or any(type(value) is not str for value in
                           (self.company_name, self.source_kind, self.source_revision, self.draft_id, self.flow_id,
                            self.slot.owner_doctype, self.slot.owner_name, self.slot.environment))):
                raise CSRDraftError("csr_draft_context")
            self.slot.__post_init__()
            validate_snapshot_owner(CredentialOwner(self.company_name, self.slot.owner_doctype,
                                    self.slot.owner_name, self.source_kind, MappingProxyType({})))
            validate_snapshot_time(self.prepared_at)
            saved_form_revision(self.source_revision)
            _canonical_uuid(self.draft_id, "draft")
            _canonical_uuid(self.flow_id, "flow")
            valid = True
        except Exception:
            pass
        if not valid:
            raise CSRDraftError("csr_draft_context")

    def __repr__(self):
        return "CSRPreparationContext(<unverified source declaration>)"


def _configuration(content):
    """Strict new-draft profile; do not change the legacy parser implicitly.

    Exact known keys, one occurrence each, bounded UTF-8 single-line values.
    The shared x509 builder validates attribute construction before generation.
    This is local input hygiene, not a regulatory VAT/unit/functionality check.
    """
    if type(content) is not str or not content or len(content) > MAX_CONFIG_BYTES:
        raise CSRDraftError("csr_draft_configuration")
    if len(content.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise CSRDraftError("csr_draft_configuration")
    if any((ord(char) < 32 and char not in "\r\n") or ord(char) == 127
           or char in "\x85\u2028\u2029" for char in content):
        raise CSRDraftError("csr_draft_configuration")
    values = {}
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if (not separator or key not in CONFIG_FIELDS or key in values or not value
                or len(value.encode("utf-8")) > 1024):
            raise CSRDraftError("csr_draft_configuration")
        values[key] = value
    if set(values) != set(CONFIG_FIELDS):
        raise CSRDraftError("csr_draft_configuration")
    return values


def _private_key(key):
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256K1):
        raise CSRDraftError("csr_draft_material")
    return key


@dataclass(frozen=True, repr=False)
class PreparedCSRDraft:
    """Protected ephemeral material; fingerprints do not authorize persistence.

    Raw fields exist only for a future explicit protected-custody handoff. Python
    cannot guarantee secure erasure or stop intentional manual field disclosure.
    """

    context: CSRPreparationContext = field(repr=False)
    config_text: str = field(repr=False)
    private_key_pem: bytes = field(repr=False)
    csr_pem: bytes = field(repr=False)
    public_key_sha256: str = field(init=False)
    csr_der_sha256: str = field(init=False)
    configuration_sha256: str = field(init=False)

    def __post_init__(self):
        valid = False
        try:
            if type(self.context) is not CSRPreparationContext:
                raise CSRDraftError("csr_draft_material")
            # Revalidate declared fields even for an internally supplied context.
            self.context.__post_init__()
            values = _configuration(self.config_text)
            if any(type(value) is not bytes or not 0 < len(value) <= MAX_MATERIAL_BYTES
                   for value in (self.private_key_pem, self.csr_pem)):
                raise CSRDraftError("csr_draft_material")
            key = _private_key(serialization.load_pem_private_key(self.private_key_pem, password=None))
            csr = x509.load_pem_x509_csr(self.csr_pem)
            public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            csr_public = csr.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            expected_key = key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
            subject, custom, alternative = csr_attributes(values, encode_customoid(CSR_LABELS[self.context.slot.environment]))
            extensions = tuple((item.oid, item.critical, item.value) for item in csr.extensions)
            expected_extensions = ((CSR_EXTENSION_OID, False, custom),
                                   (ExtensionOID.SUBJECT_ALTERNATIVE_NAME, False, alternative))
            if (expected_key != self.private_key_pem or csr.public_bytes(serialization.Encoding.PEM) != self.csr_pem
                    or not csr.is_signature_valid or public != csr_public
                    or not isinstance(csr.signature_hash_algorithm, hashes.SHA256)
                    or csr.subject != subject or extensions != expected_extensions):
                raise CSRDraftError("csr_draft_material")
            object.__setattr__(self, "public_key_sha256", hashlib.sha256(public).hexdigest())
            object.__setattr__(self, "csr_der_sha256", hashlib.sha256(csr.public_bytes(serialization.Encoding.DER)).hexdigest())
            object.__setattr__(self, "configuration_sha256", hashlib.sha256(self.config_text.encode("utf-8")).hexdigest())
            valid = True
        except Exception:
            pass
        if not valid:
            raise CSRDraftError("csr_draft_material")

    def __repr__(self):
        return "PreparedCSRDraft(<protected local material; not activated>)"

    def __reduce_ex__(self, protocol):
        raise CSRDraftError("csr_draft_not_pickleable")

    def diagnostic_projection(self):
        return {"state": "LOCAL_CSR_DRAFT", "draft_id": self.context.draft_id,
                "flow_id": self.context.flow_id, "environment": self.context.slot.environment,
                "public_key_sha256": self.public_key_sha256, "csr_der_sha256": self.csr_der_sha256,
                "configuration_sha256": self.configuration_sha256,
                "source_verified": False, "credential_epoch_verified": False,
                "storage_confirmed": False, "remote_authorization_verified": False,
                "activation_authorized": False, "dispatch_authorized": False, "renewal_authorized": False}


def prepare_csr_draft(context, config_text):
    """Generate once in memory, without replacing any saved key or certificate.

    Not whitelisted or used by a button, hook, worker or signing selector. A
    failure does not trigger retry, saved-field repair or speculative cleanup.
    """
    code = "csr_draft_context"
    try:
        if type(context) is not CSRPreparationContext:
            raise CSRDraftError(code)
        context.__post_init__()
        code = "csr_draft_configuration"
        values = _configuration(config_text)
        template = csr_builder(values, encode_customoid(CSR_LABELS[context.slot.environment]))
        code = "csr_draft_generation"
        key = _private_key(ec.generate_private_key(ec.SECP256K1(), backend=default_backend()))
        pem = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
        csr = template.sign(key, hashes.SHA256(), backend=default_backend()).public_bytes(serialization.Encoding.PEM)
        code = "csr_draft_material"
        return PreparedCSRDraft(context, config_text, pem, csr)
    except Exception:
        pass
    # Never attach a raw child exception or its private locals to this error.
    raise CSRDraftError(code)
