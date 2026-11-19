"""Bound initial CSID response parsing, without persistence or HTTP.

A successful status alone proves nothing. The caller owns request/receipt custody
and the TLS exchange. This checks the issued material against that request's CSR,
key and taxpayer. It performs no CA path, revocation or remote compliance check.
Unknown certificate profiles require review rather than an inferred EGS identity.
"""

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .credential_identity import require_certificate_taxpayer
from .credential_snapshot import authentication_certificate_der
from .native_onboarding import inspect_intent_csr


MAX_RESPONSE_BYTES = 1024 * 1024


class OnboardingResponseError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class IssuedCSID:
    request_id: str = field(repr=False)
    authorization: str = field(repr=False)
    certificate_text: str = field(repr=False)
    certificate_sha256: str
    public_key_sha256: str

    def __reduce_ex__(self, protocol):
        raise TypeError('onboarding_response_not_serializable')


def _pairs(items):
    values = {}
    for key, value in items:
        if key in values:
            raise ValueError
        values[key] = value
    return values


def _constant(value):
    raise ValueError


def _request_id(value):
    if type(value) is int:
        value = str(value)
    if (type(value) is not str or not 0 < len(value) <= 140
            or not value.isascii() or not value.isdecimal()
            or value.startswith('0')):
        raise ValueError
    return value


def is_retryable_rejection(endpoint, http_status, body):
    """Only two explicit nonissuance contracts permit a later new request.

    This does not retry the current invocation. A malformed/unknown/ambiguous
    response,401,5xx or a lost response cannot authorize another CSID request.
    """
    try:
        if (type(http_status) is not int or http_status != 400 or type(body) is not bytes
                or not 0 < len(body) <= 65536):
            return False
        data = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
        if type(data) is not dict:
            return False
        if endpoint == 'compliance':
            if set(data) != {'errors'} or type(data['errors']) is not list or len(data['errors']) != 1:
                return False
            item = data['errors'][0]
            code = 'Invalid-OTP'
        elif endpoint == 'production/csids':
            item, code = data, 'Missing-ComplianceSteps'
        else:
            return False
        return (type(item) is dict and set(item) == {'code', 'message'} and item['code'] == code
                and type(item['message']) is str and 0 < len(item['message']) <= 65536)
    except Exception:
        return False


def parse_issued_csid(http_status, body, *, intent, csr, observed_at):
    """Consume an exact retained response; return only transient secret material.

    The currently supported unit serial is the app's DirectoryName surname CSR
    profile. Do not match a free-text subject or guess another CA's serial OID.
    The response requestID identifies this issuance response; a Final-CSID's
    requestID need not equal the earlier Compliance requestID sent in its body.
    """
    failed = False
    try:
        if (type(http_status) is not int or http_status != 200 or type(body) is not bytes
                or not 0 < len(body) <= MAX_RESPONSE_BYTES
                or type(observed_at) is not datetime or observed_at.tzinfo is not timezone.utc):
            raise ValueError
        inspect_intent_csr(intent, csr)
        data = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
        required = {'requestID', 'dispositionMessage', 'binarySecurityToken', 'secret'}
        if (type(data) is not dict or not required <= set(data)
                or set(data) - required - {'errors', 'tokenType'}
                or data['dispositionMessage'] != 'ISSUED' or data.get('errors') not in (None, [])
                or 'tokenType' in data and (type(data['tokenType']) is not str or len(data['tokenType']) > 4096)):
            raise ValueError
        request_id = _request_id(data['requestID'])
        token, secret = data['binarySecurityToken'], data['secret']
        if (type(token) is not str or not 0 < len(token) <= 256 * 1024
                or type(secret) is not str or not 0 < len(secret) <= 4096
                or any(ord(c) < 33 or ord(c) > 126 for c in token + secret)
                or base64.b64encode(base64.b64decode(token, validate=True)).decode() != token):
            raise ValueError
        authorization = base64.b64encode((token + ':' + secret).encode('ascii')).decode('ascii')
        der = authentication_certificate_der('Basic ' + authorization)
        certificate = x509.load_der_x509_certificate(der)
        public = certificate.public_key()
        if not isinstance(public, ec.EllipticCurvePublicKey) or public.curve.name != 'secp256k1':
            raise ValueError
        public_sha = hashlib.sha256(public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        if public_sha != intent['public_key_sha256']:
            raise ValueError
        before = getattr(certificate, 'not_valid_before_utc', None)
        after = getattr(certificate, 'not_valid_after_utc', None)
        before = before if before is not None else certificate.not_valid_before.replace(tzinfo=timezone.utc)
        after = after if after is not None else certificate.not_valid_after.replace(tzinfo=timezone.utc)
        if not before <= observed_at <= after:
            raise ValueError
        require_certificate_taxpayer(certificate, intent['seller_tax_id'])
        alternative = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        serials = [attribute.value for name in alternative.get_values_for_type(x509.DirectoryName)
                   for attribute in name.get_attributes_for_oid(NameOID.SURNAME)]
        if len(serials) != 1 or serials[0] != intent['csr_serial']:
            raise ValueError
        result = IssuedCSID(request_id, authorization, base64.b64encode(der).decode('ascii'),
                            hashlib.sha256(der).hexdigest(), public_sha)
    except Exception:
        failed = True
    if failed:
        # Parser exceptions can contain the response (and its secret). Raise
        # outside their context and never interpolate the response into errors.
        raise OnboardingResponseError('onboarding_response_binding_review')
    return result
