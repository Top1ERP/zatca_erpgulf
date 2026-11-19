"""Initial server-owned CSR custody, never renewal or a genesis authorization.

A fresh key, exact CSR and saved owner marker commit together with an inactive
intent. Final-CSID admission must later bind an actual response to this intent;
absence of credentials/history alone never activates an EGS or its counter.
"""

import base64
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .api_routing import resolve_api_route
from .credential_settings import _resolve_owner_record_from_saved_company
from .credential_write_access import load_credential_write_source
from .csr_draft import _configuration
from .csr_template import CSR_LABELS, csr_builder, encode_customoid
from .dispatch_record_codec import encode_record_header, _identifier
from .dispatch_store import DispatchStore, _fingerprint
from .invoice_xml_core import INITIAL_PREVIOUS_HASH
from .native_dispatch import OWNER_TABLES, owner_key, _changed_once
from .native_registration import _saved, _name
from .worker_transaction import owned_worker_transaction
from .credential_material import NATIVE_OWNER_MARKER as MARKER, NATIVE_CREDENTIAL_FIELDS as PROTECTED_FIELDS


MODE = 'zatca_native_dispatch'
INTENT_FIELDS = ('record_id','owner_key','owner_doctype','owner_name','company','environment',
    'seller_tax_id','base_url_sha256','public_key_sha256','csr_sha256','configuration_sha256',
    'csr_serial','created_by','created_at_utc')


class NativeOnboardingError(RuntimeError):
    def __init__(self, code, *, commit_uncertain=False):
        self.code, self.commit_uncertain = code, commit_uncertain
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class PreparedNewUnit:
    record_id: str
    csr_data: str = field(repr=False)
    reused: bool

    def __reduce_ex__(self, protocol):
        raise TypeError('native_onboarding_not_serializable')


def native_mode_enabled(runtime):
    conf = getattr(runtime, 'conf', None)
    getter = getattr(conf, 'get', None)
    value = getter(MODE) if callable(getter) else None
    if value is None or value is False or type(value) is int and value == 0:
        return False
    if value is True or type(value) is int and value == 1:
        return True
    raise NativeOnboardingError('native_onboarding_mode_review')


def native_onboarding_selected(runtime, target):
    marker = target.get(MARKER)
    if marker not in (None, ''):
        _identifier(marker)
        return True
    return native_mode_enabled(runtime)


def validate_intent_header(header):
    if type(header) is not dict or set(header) != set(INTENT_FIELDS):
        raise NativeOnboardingError('native_onboarding_header_fields')
    _identifier(header['record_id'])
    for key in ('owner_key','public_key_sha256','csr_sha256','configuration_sha256','base_url_sha256'):
        _fingerprint(header[key])
    for key in ('owner_name','company','seller_tax_id','created_by','csr_serial'):
        _name(header[key])
    if (header['owner_doctype'] not in OWNER_TABLES or header['environment'] not in CSR_LABELS
            or header['owner_key'] != owner_key(header['owner_doctype'],header['owner_name'],header['environment'])):
        raise NativeOnboardingError('native_onboarding_header_binding')
    stamp = header['created_at_utc']
    try:
        instant = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%S.%f')
    except (ValueError, TypeError):
        instant = None
    if instant is None or instant.strftime('%Y-%m-%dT%H:%M:%S.%f') != stamp:
        raise NativeOnboardingError('native_onboarding_clock')
    return encode_record_header(header)


def intent_sha256(encoded, csr):
    return hashlib.sha256(b'zatca-initial-csr-intent/v1\0'+encoded+b'\0'+csr).hexdigest()


def inspect_intent_csr(header, csr):
    """Validate the retained public CSR; no key, certificate or remote claim."""
    invalid = False
    try:
        if type(csr) is not bytes or not 0 < len(csr) <= 65536:
            raise ValueError
        request = x509.load_pem_x509_csr(csr)
        public = request.public_key()
        if (not request.is_signature_valid or not isinstance(public, ec.EllipticCurvePublicKey)
                or public.curve.name != 'secp256k1' or not isinstance(request.signature_hash_algorithm, hashes.SHA256)
                or request.public_bytes(serialization.Encoding.PEM) != csr
                or hashlib.sha256(csr).hexdigest() != header['csr_sha256']
                or hashlib.sha256(public.public_bytes(serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest() != header['public_key_sha256']):
            raise ValueError
    except Exception:
        invalid = True
    if invalid:
        raise NativeOnboardingError('native_onboarding_csr_binding')


def _columns(runtime, database, doctype, values):
    meta = runtime.get_meta(doctype)
    for name in values:
        definition = meta.get_field(name)
        if definition is None or definition.fieldtype not in ('Data','Small Text','Text','Long Text','Code'):
            raise NativeOnboardingError('native_onboarding_owner_schema')
    names = tuple(values)
    rows = database.sql('SELECT column_name AS fieldname,data_type AS kind,'
        'character_maximum_length AS max_chars,character_octet_length AS max_bytes '
        'FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s '
        'AND column_name IN ('+','.join('%s' for _ in names)+')', ('tab'+doctype,*names),as_dict=True)
    found = {row['fieldname']: row for row in rows}
    if len(rows) != len(names) or set(found) != set(names):
        raise NativeOnboardingError('native_onboarding_owner_schema')
    for name,value in values.items():
        row = found[name]
        if (row['kind'] not in ('char','varchar','text','mediumtext','longtext')
                or type(row['max_chars']) is not int or type(row['max_bytes']) is not int
                or len(value) > row['max_chars'] or len(value.encode('utf-8')) > row['max_bytes']):
            raise NativeOnboardingError('native_onboarding_owner_capacity')


def _verify_saved_material(target, header, csr):
    """A retry reads its existing key/CSR; it cannot create a replacement key."""
    invalid = False
    try:
        key = serialization.load_pem_private_key(target.get('custom_private_key').encode(),password=None)
        public = key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        if (not isinstance(key,ec.EllipticCurvePrivateKey) or key.curve.name != 'secp256k1'
                or hashlib.sha256(public).hexdigest() != header['public_key_sha256']
                or target.get('custom_csr_data') != base64.b64encode(csr).decode()
                or hashlib.sha256(target.get('custom_csr_config').encode()).hexdigest() != header['configuration_sha256']):
            raise ValueError
        if (any(target.get(name) not in (None,'') for name in PROTECTED_FIELDS
                if name not in ('custom_private_key','custom_csr_data'))
                or target.get('custom_pih') not in (None,'',INITIAL_PREVIOUS_HASH)
                or target.get('custom_zatca_icv_counter')):
            raise ValueError
    except Exception:
        invalid = True
    if invalid:
        raise NativeOnboardingError('native_onboarding_saved_material_review')


def prepare_new_unit(company_abbr, supplied, portal_type, *, runtime, progress=None):
    """Own initial key/CSR/intent persistence with no HTTP or invoice required.

    Requires the explicit site rollout setting, installed metadata/storage and
    System Manager plus saved-owner READ+WRITE. Existing material/history is not
    silently adopted. The initial certificate workflow must complete separately.
    """
    try:
        return _prepare_new_unit(company_abbr,supplied,portal_type,runtime=runtime,progress=progress)
    except Exception as error:
        code = error.code if isinstance(error,NativeOnboardingError) else 'native_onboarding_preparation_review'
        uncertain = getattr(error,'commit_uncertain',False) is True
    raise NativeOnboardingError(code,commit_uncertain=uncertain)


def _prepare_new_unit(company_abbr, supplied, portal_type, *, runtime, progress):
    if not native_mode_enabled(runtime):
        raise NativeOnboardingError('native_onboarding_disabled')
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise NativeOnboardingError('native_onboarding_manager_required')
        loaded = load_credential_write_source(runtime,runtime.has_permission,company_abbr,supplied)
        company = _saved(runtime,'Company',loaded.company.name,owner.actor)
        target = _saved(runtime,loaded.target.doctype,loaded.target.name,owner.actor,write=True)
        selected,_kind = _resolve_owner_record_from_saved_company(company,target,
            load_doc=lambda dt,name:_saved(runtime,dt,name,owner.actor))
        if (selected.doctype,selected.name) != (target.doctype,target.name):
            raise NativeOnboardingError('native_onboarding_shared_owner')
        route = resolve_api_route(vars(company) if not hasattr(company,'as_dict') else company.as_dict(), 'compliance')
        if portal_type != route.environment:
            raise NativeOnboardingError('native_onboarding_environment')
        configuration = target.get('custom_csr_config')
        values = _configuration(configuration)
        if values['csr.organization.identifier'] != company.get('tax_id') or values['csr.country.name'] != 'SA':
            raise NativeOnboardingError('native_onboarding_taxpayer')
        repository = DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        marker = target.get(MARKER)
        if marker not in (None,''):
            chain = repository.lock_recorded_chain(marker,owner_key(target.doctype,target.name,route.environment))
            header,csr,state = repository.open_onboarding_intent(chain)
            if state != 'CSR_READY' or chain['active'] != 0 or header['company'] != company.name:
                raise NativeOnboardingError('native_onboarding_existing_state_review')
            base = route.url.removesuffix('/'+route.endpoint)
            if header['environment'] != route.environment or header['base_url_sha256'] != hashlib.sha256(base.encode()).hexdigest():
                raise NativeOnboardingError('native_onboarding_route_review')
            _verify_saved_material(target,header,csr)
            if progress is not None:
                progress.key_save_completed = progress.csr_save_completed = True
            return PreparedNewUnit(marker,base64.b64encode(csr).decode(),True)
        if any(target.get(name) not in (None,'') for name in PROTECTED_FIELDS):
            raise NativeOnboardingError('native_onboarding_existing_material_review')
        if target.get('custom_pih') not in (None,'',INITIAL_PREVIOUS_HASH) or target.get('custom_zatca_icv_counter'):
            raise NativeOnboardingError('native_onboarding_existing_history_review')
        watched = (*PROTECTED_FIELDS,MARKER,'custom_csr_config','custom_pih','custom_zatca_icv_counter',
            'custom_linked_doctype','custom__use_company_certificate__keys')
        source_values = {name:target.get(name) for name in watched}
        # Validate structure before acquiring a fresh key; never inherit a key
        # whose preparation history is unknown or rewrite the saved CSR config.
        builder = csr_builder(values,encode_customoid(CSR_LABELS[route.environment]))
        key = ec.generate_private_key(ec.SECP256K1())
        private = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()).decode()
        csr = builder.sign(key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
        record_id = str(uuid4())
        writes = {'custom_private_key':private,'custom_csr_data':base64.b64encode(csr).decode(),MARKER:record_id}
        _columns(runtime,owner.database,target.doctype,writes)
        fresh = _saved(runtime,target.doctype,target.name,owner.actor,write=True)
        fresh_company = fresh if target.doctype=='Company' and target.name==company.name else _saved(
            runtime,'Company',company.name,owner.actor)
        fresh_route = resolve_api_route(vars(fresh_company) if not hasattr(fresh_company,'as_dict') else fresh_company.as_dict(), 'compliance')
        if (any(fresh.get(name)!=value for name,value in source_values.items())
                or fresh_route!=route or fresh_company.get('tax_id')!=company.get('tax_id')):
            raise NativeOnboardingError('native_onboarding_source_changed')
        header = dict(record_id=record_id,owner_key=owner_key(target.doctype,target.name,route.environment),
            owner_doctype=target.doctype,owner_name=target.name,company=company.name,environment=route.environment,
            seller_tax_id=company.get('tax_id'),base_url_sha256=hashlib.sha256(route.url.removesuffix('/'+route.endpoint).encode()).hexdigest(),
            public_key_sha256=hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest(),csr_sha256=hashlib.sha256(csr).hexdigest(),
            configuration_sha256=hashlib.sha256(configuration.encode()).hexdigest(),
            csr_serial=values['csr.serial.number'],created_by=owner.actor,created_at_utc=owner.utc_now().strftime('%Y-%m-%dT%H:%M:%S.%f'))
        repository.stage_onboarding_intent(header,csr)
        if progress is not None:
            progress.key_save_started = progress.csr_save_started = True
        owner.database.sql('UPDATE '+OWNER_TABLES[target.doctype]+' SET '+','.join('`'+name+'`=%s' for name in writes)+
            ' WHERE name=%s',(*writes.values(),target.name))
        _changed_once(owner.database)
        owner.commit()
        if progress is not None:
            progress.key_save_completed = progress.csr_save_completed = True
        return PreparedNewUnit(record_id,writes['custom_csr_data'],False)
