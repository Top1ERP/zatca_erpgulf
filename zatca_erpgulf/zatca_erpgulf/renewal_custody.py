"""Encrypted pending renewal material, separate from active owner credentials.

Only the owned renewal service uses this fixed table. It retains exact old
settings and a new key/CSR, never an OTP, active-epoch decision or remote claim.
"""

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from types import MappingProxyType

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .chain_registration import reason_bytes
from .credential_identity import claimed_egs_identity_key, declared_egs_identity_key
from .credential_material import NATIVE_CREDENTIAL_FIELDS, CredentialOwner, authorization_for_owner
from .credential_snapshot import _bind_material, authentication_certificate_der
from .csr_draft import _configuration
from .csr_template import CSR_LABELS, csr_attributes, encode_customoid
from .dispatch_record_codec import DispatchRecordError, _identifier, encode_record_header, decode_record_header
from .dispatch_store import DispatchStore, _fingerprint
from .native_legacy_consumers import require_range_engines
from .response_json import parse_wire_response


TABLE = '`tabZATCA CSID Renewal`'
OLD_FIELDS = (*NATIVE_CREDENTIAL_FIELDS, 'custom_csr_config')
MAX_BYTES = 4 * 1024 * 1024
MAX_CIPHERTEXT = 3 + 4 * ((MAX_BYTES + 30) // 3)
FIELDS = ('record_id', 'owner_key', 'old_chain', 'owner_doctype', 'owner_name', 'company',
    'environment', 'seller_tax_id', 'egs_identity_key', 'old_certificate_sha256', 'old_public_key_sha256',
    'old_material_sha256', 'new_public_key_sha256', 'csr_sha256', 'configuration_sha256', 'base_url_sha256',
    'reason_sha256', 'payload_sha256', 'created_by', 'created_at_utc', 'http_method')
INDEX_FIELDS = ('record_id', 'owner_key', 'old_chain', 'environment', 'egs_identity_key',
    'old_certificate_sha256', 'new_public_key_sha256', 'csr_sha256')


class RenewalCustodyError(DispatchRecordError):
    pass


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError):
        raise RenewalCustodyError('renewal_payload_encoding') from None
    if not 0 < len(encoded) <= MAX_BYTES:
        raise RenewalCustodyError('renewal_payload_size')
    return encoded


def old_material(values):
    if set(values) != set(OLD_FIELDS):
        raise RenewalCustodyError('renewal_old_fields')
    if any(value is not None and (type(value) is not str or len(value) > 512 * 1024) for value in values.values()):
        raise RenewalCustodyError('renewal_old_material_size')
    return _json(values)


def encode_payload(old, private_key, csr, reason):
    old_material(old)
    if (type(private_key) is not str or not 0 < len(private_key) <= 65536
            or type(csr) is not bytes or not 0 < len(csr) <= 65536):
        raise RenewalCustodyError('renewal_new_material_size')
    reason_bytes(reason)
    return _json(dict(old=old, new_private_key=private_key, csr=base64.b64encode(csr).decode(), reason=reason))


def validate_header(header):
    if type(header) is not dict or set(header) != set(FIELDS):
        raise RenewalCustodyError('renewal_header_fields')
    for field in ('record_id', 'old_chain'):
        _identifier(header[field])
    for field in FIELDS:
        if field.endswith('_sha256') or field in ('owner_key', 'egs_identity_key'):
            _fingerprint(header[field])
    from .native_dispatch import owner_key
    from .native_registration import _name
    for field in ('owner_name', 'company', 'seller_tax_id', 'created_by'):
        _name(header[field])
    if (header['owner_doctype'] not in ('Company', 'ZATCA Multiple Setting')
            or header['environment'] not in CSR_LABELS or header['http_method'] != 'PATCH'
            or header['record_id'] == header['old_chain']
            or header['owner_key'] != owner_key(header['owner_doctype'], header['owner_name'], header['environment'])):
        raise RenewalCustodyError('renewal_header_binding')
    try:
        clock = datetime.strptime(header['created_at_utc'], '%Y-%m-%dT%H:%M:%S.%f')
        valid = clock.strftime('%Y-%m-%dT%H:%M:%S.%f') == header['created_at_utc']
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise RenewalCustodyError('renewal_header_clock')
    return encode_record_header(header)


@dataclass(frozen=True, repr=False)
class RenewalMaterial:
    old: object
    private_key: str
    csr: bytes
    reason: str

    def __reduce_ex__(self, protocol):
        raise TypeError('renewal_material_not_serializable')


def open_payload(header, payload):
    """Authenticate shape and local material bindings, without signing authority."""
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_BYTES or sha256(payload) != header['payload_sha256']:
        raise RenewalCustodyError('renewal_payload_binding')
    failed = False
    try:
        value = parse_wire_response(payload)
        if set(value) != {'old', 'new_private_key', 'csr', 'reason'} or _json(value) != payload:
            raise ValueError
        old = value['old']; encoded_old = old_material(old)
        csr = base64.b64decode(value['csr'], validate=True)
        if encode_payload(old, value['new_private_key'], csr, value['reason']) != payload:
            raise ValueError
        configuration = old['custom_csr_config']; values = _configuration(configuration)
        if (sha256(encoded_old) != header['old_material_sha256']
                or sha256(reason_bytes(value['reason'])) != header['reason_sha256']
                or sha256(csr) != header['csr_sha256'] or sha256(configuration.encode()) != header['configuration_sha256']
                or values['csr.organization.identifier'] != header['seller_tax_id'] or values['csr.country.name'] != 'SA'
                or declared_egs_identity_key(header['environment'], header['seller_tax_id'], values['csr.serial.number']) != header['egs_identity_key']):
            raise ValueError
        kind = 'company' if header['owner_doctype'] == 'Company' else 'multiple_setting'
        owner = CredentialOwner(header['company'], header['owner_doctype'], header['owner_name'], kind, old)
        auth = authorization_for_owner(owner, 'production')
        certificate_text = base64.b64encode(authentication_certificate_der(auth.header)).decode()
        bound = _bind_material(owner, 'production', certificate_text)
        if (sha256(bound.certificate_der) != header['old_certificate_sha256']
                or sha256(bound.public_key_der) != header['old_public_key_sha256']
                or claimed_egs_identity_key(bound.certificate, header['environment']) != header['egs_identity_key']):
            raise ValueError
        key = serialization.load_pem_private_key(value['new_private_key'].encode(), password=None)
        request = x509.load_pem_x509_csr(csr)
        public = request.public_key()
        options = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        subject, signing_label, alternative = csr_attributes(values, encode_customoid(CSR_LABELS[header['environment']]))
        if (not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != 'secp256k1'
                or not isinstance(public, ec.EllipticCurvePublicKey) or public.curve.name != 'secp256k1'
                or not request.is_signature_valid or not isinstance(request.signature_hash_algorithm, hashes.SHA256)
                or request.public_bytes(serialization.Encoding.PEM) != csr
                or key.public_key().public_bytes(*options) != public.public_bytes(*options)
                or sha256(public.public_bytes(*options)) != header['new_public_key_sha256']
                or header['new_public_key_sha256'] == header['old_public_key_sha256']
                or request.subject != subject or len(request.extensions) != 2
                or request.extensions.get_extension_for_oid(signing_label.oid).value != signing_label
                or request.extensions.get_extension_for_class(x509.SubjectAlternativeName).value != alternative
                or any(extension.critical for extension in request.extensions)):
            raise ValueError
    except Exception:
        failed = True
    if failed:
        raise RenewalCustodyError('renewal_material_binding')
    return RenewalMaterial(MappingProxyType(old), value['new_private_key'], csr, value['reason'])


class RenewalStore(DispatchStore):
    def __init__(self, owner):
        super().__init__(owner.database, storage_namespace=owner.storage_namespace,
            cipher=owner.cipher, owner_check=owner.owner_current)
        require_range_engines(owner, ('tabZATCA CSID Renewal',))
        columns = self._sql('SELECT COLUMN_NAME AS column_name,DATA_TYPE AS data_type,'
            'CHARACTER_MAXIMUM_LENGTH AS capacity FROM information_schema.columns '
            'WHERE table_schema=DATABASE() AND table_name=%s', ('tabZATCA CSID Renewal',))
        found = {row['column_name']: row for row in columns}
        if any(found.get(field, {}).get('data_type') != 'longtext' for field in ('preparation_header', 'preparation_ciphertext')):
            raise RenewalCustodyError('renewal_storage_columns')
        for field in (*INDEX_FIELDS, 'pending_owner_key', 'state'):
            column = found.get(field, {})
            if column.get('data_type') not in ('char', 'varchar') or type(column.get('capacity')) is not int or column['capacity'] < 64:
                raise RenewalCustodyError('renewal_storage_columns')
        indexes = self._sql('SELECT INDEX_NAME AS index_name,NON_UNIQUE AS non_unique,SEQ_IN_INDEX AS position,'
            'COLUMN_NAME AS column_name,SUB_PART AS prefix FROM information_schema.statistics '
            'WHERE table_schema=DATABASE() AND table_name=%s', ('tabZATCA CSID Renewal',))
        for field in ('record_id', 'pending_owner_key'):
            if not any(row['column_name'] == field and row['non_unique'] == 0 and row['position'] == 1 and row['prefix'] is None
                    and sum(other['index_name'] == row['index_name'] for other in indexes) == 1 for row in indexes):
                raise RenewalCustodyError('renewal_storage_index')

    def pending(self, owner_key):
        """Current owner-row lock in the service serializes this unique slot."""
        with self._operation():
            _fingerprint(owner_key)
            rows = self._sql('SELECT '+','.join(INDEX_FIELDS)+',pending_owner_key,state,'
                'SUBSTRING(preparation_header,1,32769) AS header,SUBSTRING(preparation_ciphertext,1,%s) AS ciphertext '
                'FROM '+TABLE+' WHERE pending_owner_key=%s LIMIT 2 FOR UPDATE NOWAIT', (MAX_CIPHERTEXT + 1, owner_key))
            if not rows:
                return None
            if len(rows) != 1:
                raise RenewalCustodyError('renewal_pending_ambiguous')
            row = rows[0]; encoded = row['header'].encode('utf-8')
            header = dict(decode_record_header(encoded)); validate_header(header)
            if (row['pending_owner_key'] != owner_key or row['state'] != 'CSR_READY'
                    or any(row[field] != header[field] for field in INDEX_FIELDS)
                    or len(row['ciphertext']) > MAX_CIPHERTEXT):
                raise RenewalCustodyError('renewal_pending_binding')
            payload = self._cipher.open(header['record_id'], 'csid-renewal', encoded, row['ciphertext'])
            return MappingProxyType(header), open_payload(header, payload)

    def stage(self, header, payload):
        with self._operation():
            encoded = validate_header(header); open_payload(header, payload)
            encrypted = self._cipher.seal(header['record_id'], 'csid-renewal', encoded, payload)
            clock = datetime.strptime(header['created_at_utc'], '%Y-%m-%dT%H:%M:%S.%f')
            values = {field: header[field] for field in INDEX_FIELDS}
            values.update(name=header['record_id'], pending_owner_key=header['owner_key'], state='CSR_READY',
                preparation_header=encoded.decode(), preparation_ciphertext=encrypted,
                owner=header['created_by'], modified_by=header['created_by'], creation=clock, modified=clock, docstatus=0)
            self._insert(TABLE, values)
