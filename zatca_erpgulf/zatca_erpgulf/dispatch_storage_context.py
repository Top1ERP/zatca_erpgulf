"""Pure site-key derivation and authenticated native storage readiness.

The probe detects an accidental key/site/namespace change before a worker appends
new custody under a different key. It is not key rotation, a root-admin sandbox,
an authority receipt, or proof that a cloned database is a distinct installation.
"""

import base64
import re

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .dispatch_record_codec import DispatchRecordCipher, _identifier, encode_record_header


CONTROL = 'ZATCA Dispatch Control'
CONTROL_FIELDS = ('storage_namespace', 'storage_version', 'storage_key_check')
PROBE_BYTES = b'zatca-native-storage-ready/v1'


class StorageContextError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def derive_storage_cipher(encryption_text, *, site, namespace):
    failed = False
    try:
        _identifier(namespace)
        if type(encryption_text) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{43}=', encryption_text):
            raise ValueError
        decoded = base64.urlsafe_b64decode(encryption_text)
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode() != encryption_text:
            raise ValueError
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
            info=b'zatca-native-dispatch/v1\0'+namespace.encode('ascii')).derive(decoded)
        result = DispatchRecordCipher(key, site=site, storage_namespace=namespace)
    except Exception:
        failed = True
    if failed:
        raise StorageContextError('storage_context_configuration')
    return result


def _header(namespace):
    _identifier(namespace)
    return encode_record_header({'record_id': namespace, 'storage_version': 1})


def make_storage_probe(cipher, namespace):
    cipher.require_namespace(namespace)
    return cipher.seal(namespace, 'storage-probe', _header(namespace), PROBE_BYTES)


def verify_storage_probe(cipher, namespace, value):
    failed = False
    try:
        cipher.require_namespace(namespace)
        if type(value) is not str or not 0 < len(value) <= 512:
            raise ValueError
        if cipher.open(namespace, 'storage-probe', _header(namespace), value) != PROBE_BYTES:
            raise ValueError
    except Exception:
        failed = True
    if failed:
        raise StorageContextError('storage_context_key_review')
