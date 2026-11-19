"""Locally signed initial-CSID response contracts; no authority or CA trust."""

import base64
from datetime import datetime, timezone
import hashlib
import json
import pickle
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import pytest

from zatca_erpgulf.zatca_erpgulf import onboarding_response as response


NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
SERIAL = '1-TEST|2-TEST|3-SYNTHETIC'
VAT = 'TEST-VAT'


def issued_body(csr, *, request_id=1001, key=None, taxpayer=VAT, serial=SERIAL,
                before=datetime(2020, 1, 1), after=datetime(2035, 1, 1), serial_present=True):
    """Synthetic CA response for exactly the supplied CSR's public key."""
    ca = ec.generate_private_key(ec.SECP256K1())
    directory = [x509.NameAttribute(NameOID.USER_ID, taxpayer)]
    if serial_present:
        directory.append(x509.NameAttribute(NameOID.SURNAME, serial))
    certificate = (x509.CertificateBuilder().subject_name(csr.subject).issuer_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SYNTHETIC-CA')]))
        .public_key(key.public_key() if key is not None else csr.public_key())
        .serial_number(100).not_valid_before(before).not_valid_after(after)
        .add_extension(x509.SubjectAlternativeName([x509.DirectoryName(x509.Name(directory))]), critical=False)
        .sign(ca, hashes.SHA256()))
    token = base64.b64encode(base64.b64encode(certificate.public_bytes(serialization.Encoding.DER))).decode()
    return json.dumps({'requestID': request_id, 'dispositionMessage': 'ISSUED',
        'binarySecurityToken': token, 'secret': 'PRIVATE-SYNTHETIC-SECRET', 'errors': None}).encode()


@pytest.fixture
def material():
    key = ec.generate_private_key(ec.SECP256K1())
    csr = (x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'SYNTHETIC-UNIT')])).sign(key, hashes.SHA256()))
    raw = csr.public_bytes(serialization.Encoding.PEM)
    header = {'public_key_sha256': hashlib.sha256(key.public_key().public_bytes(serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest(), 'csr_sha256': hashlib.sha256(raw).hexdigest(),
        'seller_tax_id': VAT, 'csr_serial': SERIAL}
    return SimpleNamespace(key=key, csr=csr, raw=raw, header=header, body=issued_body(csr))


def parse(material, body=None, status=200, observed_at=NOW):
    return response.parse_issued_csid(status, material.body if body is None else body,
        intent=material.header, csr=material.raw, observed_at=observed_at)


def test_matching_issued_response_is_transient_redacted_and_bound_to_csr(material):
    value = parse(material)
    assert value.request_id == '1001' and value.public_key_sha256 == material.header['public_key_sha256']
    assert value.certificate_sha256 == hashlib.sha256(base64.b64decode(value.certificate_text)).hexdigest()
    assert 'PRIVATE' not in repr(value) and '1001' not in repr(value)
    with pytest.raises(TypeError):pickle.dumps(value)


@pytest.mark.parametrize('fault', ['status', 'disposition', 'errors', 'token', 'secret', 'duplicate',
    'request_bool', 'request_zero', 'request_leading_zero', 'request_float', 'missing', 'extra',
    'wrong_key', 'wrong_vat', 'wrong_unit', 'missing_unit', 'expired', 'future', 'naive_time',
    'csr_changed', 'body_type', 'body_size'])
def test_success_requires_more_than_http200_and_never_leaks_response_material(material, fault):
    m = material;body = m.body;status = 200;clock = NOW
    data = json.loads(body)
    if fault == 'status':status = 202
    elif fault in ('disposition','errors','token','secret','request_bool','request_zero','request_leading_zero','request_float','extra'):
        key, value = {'disposition': ('dispositionMessage', 'PENDING'), 'errors': ('errors', [{'code': 'FAILED'}]),
            'token': ('binarySecurityToken', 'INVALID'), 'secret': ('secret', 'PRIVATE\nSECRET'),
            'request_bool': ('requestID', True), 'request_zero': ('requestID', 0),
            'request_leading_zero': ('requestID', '001'), 'request_float': ('requestID', 1.0),
            'extra': ('unknown', 'PRIVATE') }[fault]
        data[key] = value;body = json.dumps(data).encode()
    elif fault == 'missing':del data['secret'];body = json.dumps(data).encode()
    elif fault == 'duplicate':body = body[:-1] + b',"secret":"OTHER-PRIVATE"}'
    elif fault in ('wrong_key','wrong_vat','wrong_unit','missing_unit','expired','future'):
        options = {'wrong_key': {'key': ec.generate_private_key(ec.SECP256K1())}, 'wrong_vat': {'taxpayer': 'OTHER-VAT'},
            'wrong_unit': {'serial': 'OTHER-UNIT'}, 'missing_unit': {'serial_present': False},
            'expired': {'after': datetime(2026, 1, 1)}, 'future': {'before': datetime(2030, 1, 1)}}[fault]
        body = issued_body(m.csr, **options)
    elif fault == 'naive_time':clock = NOW.replace(tzinfo=None)
    elif fault == 'csr_changed':m.raw += b'\n'
    elif fault == 'body_type':body = body.decode()
    elif fault == 'body_size':body = b'X'*(response.MAX_RESPONSE_BYTES+1)
    with pytest.raises(response.OnboardingResponseError) as failed:parse(m, body, status, clock)
    assert failed.value.__context__ is None and 'PRIVATE' not in str(failed.value)


@pytest.mark.parametrize('request_id',[1001, '9007199254740993123456789'])
def test_request_id_remains_an_exact_string_without_float_conversion(material, request_id):
    assert parse(material, issued_body(material.csr, request_id=request_id)).request_id == str(request_id)


@pytest.mark.parametrize('endpoint,body',[
    ('compliance',b'{"errors":[{"code":"Invalid-OTP","message":"Invalid"}]}'),
    ('production/csids',b'{"code":"Missing-ComplianceSteps","message":"Not completed"}'),
])
def test_only_bounded_known_nonissuance_responses_allow_a_later_explicit_request(endpoint,body):
    assert response.is_retryable_rejection(endpoint,400,body)
    assert not response.is_retryable_rejection(endpoint,401,body)
    assert not response.is_retryable_rejection(endpoint,200,body)
    assert not response.is_retryable_rejection(endpoint,400,body[:-1]+b',"secret":"PRIVATE"}')
    assert not response.is_retryable_rejection(endpoint,400,body.replace(b'Invalid-OTP',b'UNKNOWN').replace(b'Missing-ComplianceSteps',b'UNKNOWN'))
    assert not response.is_retryable_rejection(endpoint,400,body.decode())
