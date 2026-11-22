"""Local pending native renewal, without replacing an active certificate.

New key/CSR and exact old material commit in separate encrypted custody. No
PATCH, issuer drain, activation, invoice generation or counter reset occurs.
"""

import base64
from dataclasses import dataclass, field
from datetime import timezone
from uuid import uuid4

import frappe
from frappe import _
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .api_routing import resolve_api_route
from .chain_registration import reason_bytes
from .credential_identity import claimed_egs_identity_key, declared_egs_identity_key, require_certificate_taxpayer
from .credential_material import CredentialOwner, NATIVE_OWNER_MARKER, authorization_for_owner
from .credential_settings import _resolve_owner_record_from_saved_company
from .credential_snapshot import _bind_material, authentication_certificate_der
from .csr_draft import _configuration
from .csr_template import CSR_LABELS, csr_builder, encode_customoid
from .dispatch_record_codec import _identifier, DispatchRecordError
from .dispatch_store import DispatchStore, DispatchStoreError
from .native_dispatch import owner_key
from .native_onboarding import native_mode_enabled
from .native_registration import _saved
from .operation_messages import mute_operation_messages
from .renewal_custody import OLD_FIELDS, RenewalStore, old_material, encode_payload, sha256
from .worker_transaction import owned_worker_transaction, WorkerTransactionError


REVIEW = 'Certificate renewal preparation could not be confirmed. Review the retained renewal and saved issuer settings before repeating. No certificate request was sent and active credentials were not replaced.'
PREPARED = 'The renewal key and CSR were saved separately from the current certificate. Active credentials and invoice counters stay unchanged. This is local preparation only; renewal, compliance checks and activation have not been performed.'


class NativeRenewalError(RuntimeError):
    http_status_code = 417

    def __init__(self, code, message=REVIEW, *, commit_uncertain=False):
        self.code, self.commit_uncertain = code, commit_uncertain
        self.fatal = True
        super().__init__(message)


@dataclass(frozen=True, repr=False)
class PreparedRenewal:
    record_id: str
    old_chain: str
    csr_data: str = field(repr=False)
    reused: bool
    old_certificate_expired: bool

    def __reduce_ex__(self, protocol):
        raise TypeError('native_renewal_not_serializable')


def _load_current(chain_id, *, runtime, owner):
    """Authorize saved identities before parsing secrets; lock owner then chain."""
    rows = owner.database.sql('SELECT owner_doctype,owner_name FROM `tabZATCA Issuing Chain` WHERE name=%s',
        (chain_id,), as_dict=True)
    owner.require_owner()
    if len(rows) != 1 or rows[0]['owner_doctype'] not in ('Company', 'ZATCA Multiple Setting'):
        raise NativeRenewalError('native_renewal_chain_locator')
    target = _saved(runtime, rows[0]['owner_doctype'], rows[0]['owner_name'], owner.actor, write=True)
    company = target if target.doctype == 'Company' else _saved(runtime, 'Company', target.get('custom_linked_doctype'), owner.actor)
    selected, kind = _resolve_owner_record_from_saved_company(company, target,
        load_doc=lambda dt, name: _saved(runtime, dt, name, owner.actor))
    if (selected.doctype, selected.name) != (target.doctype, target.name):
        raise NativeRenewalError('native_renewal_shared_owner')
    settings = company.as_dict() if hasattr(company, 'as_dict') else vars(company)
    route = resolve_api_route(settings, 'production/csids', method='PATCH', onboarding_only=True)
    key = owner_key(target.doctype, target.name, route.environment)
    repository = DispatchStore(owner.database, storage_namespace=owner.storage_namespace,
        cipher=owner.cipher, owner_check=owner.owner_current)
    chain = repository.lock_active_chain(key)
    _saved(runtime, 'ZATCA Issuing Chain', chain_id, owner.actor)
    if (chain['record_id'] != chain_id or target.get(NATIVE_OWNER_MARKER) != chain_id
            or chain['active_owner_key'] != key or chain['seller_tax_id'] != company.get('tax_id')):
        raise NativeRenewalError('native_renewal_active_binding')
    old = {name: target.get(name) for name in OLD_FIELDS}
    encoded_old = old_material(old)
    credential = CredentialOwner(company.name, target.doctype, target.name, kind, old)
    authorization = authorization_for_owner(credential, 'production')
    certificate_text = base64.b64encode(authentication_certificate_der(authorization.header)).decode()
    material = _bind_material(credential, 'production', certificate_text)
    require_certificate_taxpayer(material.certificate, company.get('tax_id'))
    values = _configuration(old['custom_csr_config'])
    identity = declared_egs_identity_key(route.environment, company.get('tax_id'), values['csr.serial.number'])
    if (values['csr.organization.identifier'] != company.get('tax_id') or values['csr.country.name'] != 'SA'
            or claimed_egs_identity_key(material.certificate, route.environment) != identity
            or chain['certificate_sha256'] != sha256(material.certificate_der)
            or chain['public_key_sha256'] != sha256(material.public_key_der)):
        raise NativeRenewalError('native_renewal_material_binding')
    now = owner.utc_now().replace(tzinfo=timezone.utc)
    before = getattr(material.certificate, 'not_valid_before_utc', None) or material.certificate.not_valid_before.replace(tzinfo=timezone.utc)
    after = getattr(material.certificate, 'not_valid_after_utc', None) or material.certificate.not_valid_after.replace(tzinfo=timezone.utc)
    if now < before:
        raise NativeRenewalError('native_renewal_certificate_clock')
    binding = dict(owner_key=key, old_chain=chain_id, owner_doctype=target.doctype, owner_name=target.name,
        company=company.name, environment=route.environment, seller_tax_id=company.get('tax_id'), egs_identity_key=identity,
        old_certificate_sha256=sha256(material.certificate_der), old_public_key_sha256=sha256(material.public_key_der),
        old_material_sha256=sha256(encoded_old), configuration_sha256=sha256(old['custom_csr_config'].encode()),
        base_url_sha256=sha256(route.url.removesuffix('/production/csids').encode()), http_method='PATCH')
    return binding, old, values, now > after


def _prepare_renewal(chain_id, reason, *, runtime):
    _identifier(chain_id)
    reason_bytes(reason)
    if not native_mode_enabled(runtime):
        raise NativeRenewalError('native_renewal_disabled')
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise NativeRenewalError('native_renewal_manager_required')
        binding, old, values, expired = _load_current(chain_id, runtime=runtime, owner=owner)
        store = RenewalStore(owner)
        pending = store.pending(binding['owner_key'])
        if pending is not None:
            header, material = pending
            if (any(header[key] != value for key, value in binding.items())
                    or header['reason_sha256'] != sha256(reason_bytes(reason)) or material.reason != reason):
                raise NativeRenewalError('native_renewal_existing_preparation_review')
            return PreparedRenewal(header['record_id'], chain_id, base64.b64encode(material.csr).decode(), True, expired)
        builder = csr_builder(values, encode_customoid(CSR_LABELS[binding['environment']]))
        key = ec.generate_private_key(ec.SECP256K1())
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()).decode()
        csr = builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
        fresh, _old, _values, _expired = _load_current(chain_id, runtime=runtime, owner=owner)
        if fresh != binding:
            raise NativeRenewalError('native_renewal_source_changed')
        payload = encode_payload(old, private, csr, reason)
        header = dict(binding, record_id=str(uuid4()), reason_sha256=sha256(reason_bytes(reason)),
            payload_sha256=sha256(payload), new_public_key_sha256=sha256(key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)), csr_sha256=sha256(csr),
            created_by=owner.actor, created_at_utc=owner.utc_now().strftime('%Y-%m-%dT%H:%M:%S.%f'))
        store.stage(header, payload)
        owner.commit()
        return PreparedRenewal(header['record_id'], chain_id, base64.b64encode(csr).decode(), False, expired)


def prepare_renewal(chain_id, reason, *, runtime):
    """Unknown commit recovery reuses exact pending custody, never another key."""
    try:
        return _prepare_renewal(chain_id, reason, runtime=runtime)
    except Exception as error:
        code = error.code if isinstance(error, (NativeRenewalError, DispatchRecordError, DispatchStoreError,
            WorkerTransactionError)) else 'native_renewal_preparation_review'
        uncertain = getattr(error, 'commit_uncertain', False) is True
    raise NativeRenewalError(code, commit_uncertain=uncertain)


@frappe.whitelist(methods=['POST'])
def prepare_certificate_renewal(chain_id, reason):
    """One translated result with metadata only; no active material or CSR."""
    code = None
    uncertain = False
    try:
        with mute_operation_messages(frappe):
            result = prepare_renewal(chain_id, reason, runtime=frappe)
    except Exception as error:
        code = error.code if isinstance(error, NativeRenewalError) else 'native_renewal_preparation_review'
        uncertain = getattr(error, 'commit_uncertain', False) is True
    if code is not None:
        try:
            frappe.log_error(title='ZATCA certificate renewal preparation', message=code)
        except Exception:
            pass
        raise NativeRenewalError(code, _(REVIEW), commit_uncertain=uncertain)
    return dict(renewal_id=result.record_id, old_chain=result.old_chain, state='CSR_READY', reused=result.reused,
        old_certificate_expired=result.old_certificate_expired, message=_(PREPARED))
