"""Flat authenticated envelopes for issuance, receipts and continuity reviews.

This codec owns neither a database nor permission/dispatch decisions. Record ID,
site/namespace, payload kind and exact public header bytes form authenticated
associated data. Services validate their fixed public header field sets. Private
keys never enter these records. Onboarding responses alone may contain issued
secrets, inside their separate encrypted domain; issuance/receipt records must
not contain credentials. Parse/decrypt at storage boundaries.
"""

import base64
import binascii
import hashlib
import json
from types import MappingProxyType
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os


VERSION = 'v1'
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_HEADER_BYTES = 32 * 1024
KINDS = frozenset(('legacy-history-audit', 'legacy-history-access', 'legacy-history-page', 'legacy-history-head', 'artifact', 'receipt', 'chain-registration', 'chain-onboarding',
                   'onboarding-request', 'onboarding-response', 'storage-probe', 'publication-source', 'submission-intent', 'collection-intent', 'intent-retirement', 'intent-reconciliation', 'issuance-origin', 'retry-intent', 'submission-stage', 'late-acceptance', 'correction-intent'))


class DispatchRecordError(RuntimeError):
    """Static internal codes; never include ciphertext/key/parser/driver values."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _identifier(value):
    if type(value) is not str or len(value) != 36:
        raise DispatchRecordError('dispatch_record_identity')
    try:
        canonical = str(UUID(value))
    except ValueError:
        canonical = None
    if canonical != value:
        raise DispatchRecordError('dispatch_record_identity')
    return value


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise DispatchRecordError('dispatch_header_duplicate_key')
        result[key] = value
    return result


def encode_record_header(header):
    """Only bounded flat scalar metadata; XML/raw responses stay in the payload.

    The service owns the exact allowed header field set and its cross-field
    business validation. This encoder is not a source or receipt attestation.
    """
    if type(header) is not dict or not header or len(header) > 64:
        raise DispatchRecordError('dispatch_header_shape')
    for key, value in header.items():
        if (type(key) is not str or not key or len(key) > 64
                or type(value) not in (str, int, bool, type(None))
                or (type(value) is str and len(value) > 4096)
                or (type(value) is int and not -(2**63) <= value < 2**63)):
            raise DispatchRecordError('dispatch_header_scalar')
    try:
        raw = json.dumps(header,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    except (ValueError, UnicodeError):
        failed = True
    else:
        failed = False
    if failed or len(raw) > MAX_HEADER_BYTES:
        raise DispatchRecordError('dispatch_header_encoding')
    return raw


def _reject_constant(value):
    raise DispatchRecordError('dispatch_header_scalar')


def decode_record_header(raw):
    """Reconstruct a protected immutable view; reject noncanonical/duplicate data."""
    if type(raw) is not bytes or not raw or len(raw) > MAX_HEADER_BYTES:
        raise DispatchRecordError('dispatch_header_size')
    try:
        header = json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,
                            parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        invalid = True
    else:
        invalid = False
    if invalid:
        raise DispatchRecordError('dispatch_header_encoding')
    if encode_record_header(header) != raw:
        raise DispatchRecordError('dispatch_header_noncanonical')
    return MappingProxyType(header)


class DispatchRecordCipher:
    """One operation's server-owned cipher, never a cached/exported key object.

    A server provider must acquire the site's key without generating or changing
    site configuration. The caller supplies that key; this codec cannot attest its
    origin, DB ownership, enrollment, remote acceptance or activation authority.
    """
    __slots__ = ('_key', '_site', '_namespace')

    def __init__(self, key, *, site, storage_namespace):
        if (type(key) is not bytes or len(key) != 32 or type(site) is not str
                or not site or len(site) > 512 or '\x00' in site):
            raise DispatchRecordError('dispatch_cipher_context')
        _identifier(storage_namespace)
        self._key, self._site, self._namespace = key, site, storage_namespace

    def __repr__(self):
        return '<DispatchRecordCipher protected>'

    def __reduce_ex__(self, protocol):
        raise TypeError('dispatch_cipher_not_serializable')

    def require_namespace(self, namespace):
        _identifier(namespace)
        if namespace != self._namespace:
            raise DispatchRecordError('dispatch_cipher_namespace')

    def _aad(self, record_id, kind, header):
        _identifier(record_id)
        if type(kind) is not str or kind not in KINDS:
            raise DispatchRecordError('dispatch_record_kind')
        decode_record_header(header)
        context = encode_record_header(dict(site=self._site,namespace=self._namespace,
            record_id=record_id,kind=kind,version=VERSION,header_sha256=hashlib.sha256(header).hexdigest()))
        return b'zatca-native-dispatch-record\0'+context

    def seal(self, record_id, kind, header, payload):
        if type(payload) is not bytes or not payload or len(payload) > MAX_PAYLOAD_BYTES:
            raise DispatchRecordError('dispatch_payload_size')
        aad = self._aad(record_id,kind,header)
        nonce = os.urandom(12)
        encrypted = AESGCM(self._key).encrypt(nonce,payload,aad)
        return VERSION+'.'+base64.b64encode(nonce+encrypted).decode('ascii')

    def open(self, record_id, kind, header, ciphertext):
        aad = self._aad(record_id,kind,header)
        if (type(ciphertext) is not str or not ciphertext.startswith(VERSION+'.')
                or len(ciphertext) > 3+4*((MAX_PAYLOAD_BYTES+28+2)//3)):
            raise DispatchRecordError('dispatch_ciphertext_size')
        try:
            raw = base64.b64decode(ciphertext[3:],validate=True)
        except (ValueError,binascii.Error):
            invalid = True
        else:
            invalid = (len(raw) <= 28 or len(raw) > MAX_PAYLOAD_BYTES+28
                       or base64.b64encode(raw).decode('ascii') != ciphertext[3:])
        if invalid:
            raise DispatchRecordError('dispatch_ciphertext_encoding')
        try:
            opened = AESGCM(self._key).decrypt(raw[:12],raw[12:],aad)
        except (InvalidTag,ValueError):
            failed = True
        else:
            failed = False
        if failed:
            raise DispatchRecordError('dispatch_record_integrity')
        return opened
