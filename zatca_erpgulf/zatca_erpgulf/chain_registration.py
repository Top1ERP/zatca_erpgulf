"""Bounded legacy-continuity evidence; no genesis inference or activation.

The owned review service supplies saved-source observations. This codec only
binds those observations and exact original bytes; it cannot establish remote
acceptance, signature validity, complete history or a drained legacy dispatcher.
"""

import hashlib
from types import MappingProxyType

from .dispatch_record_codec import (
    DispatchRecordError, encode_record_header, decode_record_header, _identifier, MAX_HEADER_BYTES,
)
from .artifact_evidence import MAX_XML_BYTES


REGISTRATION_FIELDS = (
    'record_id', 'owner_key', 'owner_doctype', 'owner_name', 'company', 'environment',
    'seller_tax_id', 'registration_kind', 'certificate_sha256', 'public_key_sha256',
    'base_url_sha256', 'source_doctype', 'source_name', 'source_uuid', 'source_unit',
    'legacy_counter', 'icv', 'invoice_hash', 'file_id', 'xml_sha256', 'source_sha256',
    'reviewed_by', 'reviewed_at_utc', 'reason_sha256', 'payload_sha256', 'supersedes_review',
)
CHAIN_BINDING = ('record_id', 'owner_key', 'owner_doctype', 'owner_name', 'environment',
    'seller_tax_id', 'registration_kind', 'certificate_sha256', 'public_key_sha256')
MAX_REASON_BYTES = 4000


class ChainRegistrationError(DispatchRecordError):
    def __init__(self, code, *, commit_uncertain=False):
        self.code = code
        self.commit_uncertain = commit_uncertain
        super().__init__(code)


def reason_bytes(reason):
    if type(reason) is not str or not reason.strip() or len(reason) > 1000:
        raise ChainRegistrationError('registration_review_reason')
    failed = False
    try:
        value = reason.encode('utf-8')
    except UnicodeError:
        failed = True
    if failed or len(value) > MAX_REASON_BYTES:
        raise ChainRegistrationError('registration_review_reason')
    return value


def encode_registration_payload(xml, reason):
    if type(xml) is not bytes or not 0 < len(xml) <= MAX_XML_BYTES:
        raise ChainRegistrationError('registration_xml_size')
    text = reason_bytes(reason)
    return len(text).to_bytes(2, 'big') + text + xml


def validate_registration_header(header):
    from .dispatch_store import _counter, _fingerprint
    if type(header) is not dict or set(header) != set(REGISTRATION_FIELDS):
        raise ChainRegistrationError('registration_header_fields')
    _identifier(header['record_id'])
    _identifier(header['source_uuid'])
    _counter(header['icv'])
    if header['supersedes_review'] is not None:
        _identifier(header['supersedes_review'])
        if header['supersedes_review'] == header['record_id']:
            raise ChainRegistrationError('registration_supersedes_self')
    for key in ('owner_key', 'certificate_sha256', 'public_key_sha256', 'base_url_sha256',
            'xml_sha256', 'source_sha256', 'reason_sha256', 'payload_sha256'):
        _fingerprint(header[key])
    if (header['registration_kind'] != 'LEGACY_REVIEWED'
            or header['owner_doctype'] not in ('Company', 'ZATCA Multiple Setting')
            or header['source_doctype'] not in ('Sales Invoice', 'POS Invoice')
            or header['environment'] not in ('Sandbox', 'Simulation', 'Production')):
        raise ChainRegistrationError('registration_binding')
    for key in ('owner_name', 'company', 'seller_tax_id', 'source_name', 'source_unit',
            'legacy_counter', 'file_id', 'reviewed_by', 'invoice_hash'):
        value = header[key]
        if type(value) is not str or not 0 < len(value) <= 140 or value != value.strip() or any(ord(c) < 32 for c in value):
            raise ChainRegistrationError('registration_identity')
    from datetime import datetime
    value = header['reviewed_at_utc']
    try:
        parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%f')
    except (ValueError, TypeError):
        parsed = None
    if parsed is None or parsed.strftime('%Y-%m-%dT%H:%M:%S.%f') != value:
        raise ChainRegistrationError('registration_review_clock')
    return encode_record_header(header)


def open_registration_payload(header, payload):
    """Check exact framing/digests; do not normalize the reviewed XML/reason."""
    if type(payload) is not bytes or len(payload) < 4 or len(payload) > MAX_XML_BYTES + MAX_REASON_BYTES + 2:
        raise ChainRegistrationError('registration_payload_size')
    size = int.from_bytes(payload[:2], 'big')
    if not 0 < size <= MAX_REASON_BYTES or size + 2 >= len(payload):
        raise ChainRegistrationError('registration_payload_frame')
    text, xml = payload[2:2+size], payload[2+size:]
    failed = False
    try:
        reason = text.decode('utf-8')
        if reason_bytes(reason) != text:
            failed = True
    except (UnicodeError, ChainRegistrationError):
        failed = True
    if (failed or not 0 < len(xml) <= MAX_XML_BYTES
            or hashlib.sha256(text).hexdigest() != header['reason_sha256']
            or hashlib.sha256(xml).hexdigest() != header['xml_sha256']
            or hashlib.sha256(payload).hexdigest() != header['payload_sha256']):
        raise ChainRegistrationError('registration_payload_binding')
    return xml, reason


def decode_registration_header(encoded):
    if type(encoded) is not str or len(encoded) > MAX_HEADER_BYTES:
        raise ChainRegistrationError('registration_header_size')
    failed = False
    try:
        raw = encoded.encode('utf-8')
    except UnicodeError:
        failed = True
    if failed or len(raw) > MAX_HEADER_BYTES:
        raise ChainRegistrationError('registration_header_size')
    value = dict(decode_record_header(raw))
    validate_registration_header(value)
    return MappingProxyType(value), raw


def evidence_sha256(header_bytes, payload):
    return hashlib.sha256(b'zatca-chain-registration/v1\0' + header_bytes + b'\0' + payload).hexdigest()
