"""Pending renewal payload/route contracts; no site or authority transport."""

import base64
import csv
import inspect
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from zatca_erpgulf.zatca_erpgulf import native_renewal as renewal, renewal_custody as custody
from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route, ApiConfigurationError
from zatca_erpgulf.zatca_erpgulf.credential_identity import declared_egs_identity_key
from zatca_erpgulf.zatca_erpgulf.csr_draft import _configuration
from zatca_erpgulf.zatca_erpgulf.csr_template import csr_builder, encode_customoid, CSR_LABELS
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordError
from zatca_erpgulf.zatca_erpgulf.native_dispatch import owner_key
from zatca_erpgulf.zatca_erpgulf.tests.test_api_route_contract import settings
from zatca_erpgulf.zatca_erpgulf.tests.test_native_onboarding_mariadb import CONFIG
from zatca_erpgulf.zatca_erpgulf.tests.test_onboarding_response import material


@pytest.fixture
def prepared(material):
    body = json.loads(material.body)
    old = {name: None for name in custody.OLD_FIELDS}
    old.update(custom_private_key=material.key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode(),
        custom_certificate=base64.b64decode(body['binarySecurityToken']).decode(), custom_csr_config=CONFIG,
        custom_basic_auth_from_production=base64.b64encode((body['binarySecurityToken']+':'+body['secret']).encode()).decode())
    key = ec.generate_private_key(ec.SECP256K1())
    csr = csr_builder(_configuration(CONFIG), encode_customoid(CSR_LABELS['Production'])).sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode()
    payload = custody.encode_payload(old, private, csr, 'Reviewed renewal preparation')
    header = dict(record_id=str(uuid4()), old_chain=str(uuid4()), owner_key=owner_key('Company', 'SYNTHETIC', 'Production'),
        owner_doctype='Company', owner_name='SYNTHETIC', company='SYNTHETIC', environment='Production', seller_tax_id='TEST-VAT',
        egs_identity_key=declared_egs_identity_key('Production', 'TEST-VAT', '1-TEST|2-TEST|3-SYNTHETIC'),
        old_certificate_sha256=custody.sha256(base64.b64decode(old['custom_certificate'])),
        old_public_key_sha256=material.header['public_key_sha256'], old_material_sha256=custody.sha256(custody.old_material(old)),
        new_public_key_sha256=custody.sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)),
        csr_sha256=custody.sha256(csr), configuration_sha256=custody.sha256(CONFIG.encode()), base_url_sha256='a'*64,
        reason_sha256=custody.sha256(b'Reviewed renewal preparation'), payload_sha256=custody.sha256(payload),
        created_by='OPERATOR', created_at_utc='2026-11-22T12:00:00.000000', http_method='PATCH')
    return SimpleNamespace(header=header, payload=payload, old=old, csr=csr, private=private)


def test_exact_old_and_new_material_stay_separate_redacted_and_nonserializable(prepared):
    p = prepared
    custody.validate_header(p.header)
    value = custody.open_payload(p.header, p.payload)
    assert dict(value.old) == p.old and value.private_key == p.private and value.csr == p.csr
    assert value.private_key != value.old['custom_private_key'] and 'PRIVATE' not in repr(value)
    with pytest.raises(TypeError): pickle.dumps(value)


@pytest.mark.parametrize('fault', ['new-key', 'csr', 'wrong-old-token', 'wrong-identity', 'method', 'missing-field', 'wrong-label'])
def test_preparation_rejects_unbound_or_incomplete_material(prepared, fault):
    p = prepared; header = p.header.copy(); value = json.loads(p.payload)
    if fault == 'new-key': value['new_private_key'] = p.old['custom_private_key']
    elif fault == 'csr': value['csr'] = base64.b64encode(b'INVALID CSR').decode()
    elif fault == 'wrong-old-token': value['old']['custom_basic_auth_from_production'] = 'INVALID AUTH'
    elif fault == 'wrong-identity': header['egs_identity_key'] = 'f'*64
    elif fault == 'method': header['http_method'] = 'POST'
    elif fault == 'missing-field': del header['old_chain']
    else:
        key = serialization.load_pem_private_key(p.private.encode(), password=None)
        csr = csr_builder(_configuration(CONFIG), encode_customoid(CSR_LABELS['Sandbox'])).sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
        value['csr'] = base64.b64encode(csr).decode(); header['csr_sha256'] = custody.sha256(csr)
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    header['payload_sha256'] = custody.sha256(payload)
    with pytest.raises(DispatchRecordError):
        custody.validate_header(header); custody.open_payload(header, payload)


@pytest.mark.parametrize('environment', ['Sandbox', 'Simulation', 'Production'])
def test_same_path_keeps_initial_and_renewal_credential_purposes_distinct(environment):
    initial = resolve_api_route(settings(environment), 'production/csids', onboarding_only=True)
    renewed = resolve_api_route(settings(environment), 'production/csids', method='PATCH', onboarding_only=True)
    assert initial.url == renewed.url and initial.required_credential == 'compliance'
    assert renewed.required_credential == 'production'


@pytest.mark.parametrize('endpoint,method', [('compliance', 'PATCH'), ('compliance/invoices', 'PATCH'),
    ('invoices/reporting/single', 'PATCH'), ('production/csids', 'GET'), ('production/csids', True)])
def test_patch_cannot_be_repurposed_as_invoice_or_initial_compliance_transport(endpoint, method):
    with pytest.raises(ApiConfigurationError): resolve_api_route(settings('Production'), endpoint, method=method)


def test_public_success_exposes_one_translated_metadata_result_without_csr_or_keys(monkeypatch):
    runtime = SimpleNamespace(flags={'parent': True}, msgprint=Mock())
    monkeypatch.setattr(renewal, 'frappe', runtime); monkeypatch.setattr(renewal, '_', lambda text: 'AR:'+text)
    monkeypatch.setattr(renewal, 'prepare_renewal', lambda *args, **kwargs: renewal.PreparedRenewal('RENEWAL', 'CHAIN', 'PRIVATE CSR', False, True))
    result = inspect.unwrap(renewal.prepare_certificate_renewal)('CHAIN', 'REASON')
    assert result['state'] == 'CSR_READY' and result['message'] == 'AR:'+renewal.PREPARED
    assert 'PRIVATE' not in repr(result) and 'csr_data' not in result
    assert runtime.flags == {'parent': True}; runtime.msgprint.assert_not_called()


def test_public_error_preserves_unknown_commit_and_static_english_log(monkeypatch):
    runtime = SimpleNamespace(flags={}, log_error=Mock())
    monkeypatch.setattr(renewal, 'frappe', runtime); monkeypatch.setattr(renewal, '_', lambda text: 'AR:'+text)
    def failed(*args, **kwargs):
        assert runtime.flags['mute_messages'] is True
        raise renewal.NativeRenewalError('native_renewal_commit_unknown', commit_uncertain=True)
    monkeypatch.setattr(renewal, 'prepare_renewal', failed)
    with pytest.raises(renewal.NativeRenewalError) as caught: inspect.unwrap(renewal.prepare_certificate_renewal)('CHAIN', 'REASON')
    assert str(caught.value) == 'AR:'+renewal.REVIEW and caught.value.commit_uncertain
    assert caught.value.__context__ is None and runtime.flags == {}
    assert runtime.log_error.call_args.kwargs['message'] == 'native_renewal_commit_unknown'


def test_public_boundary_also_redacts_unexpected_message_scope_failure(monkeypatch):
    runtime = SimpleNamespace(log_error=Mock())
    monkeypatch.setattr(renewal, 'frappe', runtime); monkeypatch.setattr(renewal, '_', lambda text: 'AR:'+text)
    monkeypatch.setattr(renewal, 'mute_operation_messages', Mock(side_effect=ValueError('PRIVATE MESSAGE SCOPE')))
    with pytest.raises(renewal.NativeRenewalError) as caught:
        inspect.unwrap(renewal.prepare_certificate_renewal)('CHAIN', 'REASON')
    assert str(caught.value) == 'AR:'+renewal.REVIEW and caught.value.__context__ is None
    assert 'PRIVATE' not in repr(runtime.log_error.call_args)


def test_new_display_and_metadata_labels_have_arabic_translations():
    root = Path(__file__).resolve().parents[2]
    with (root/'translations/ar.csv').open(newline='', encoding='utf-8') as file:
        catalog = {row[0]: row[1] for row in csv.reader(file) if len(row) > 1}
    for text in (renewal.REVIEW, renewal.PREPARED, 'Prepare Certificate Renewal', 'Renewal Preparation Reason',
            'Certificate Renewal Preparation', 'View Pending Renewal', 'Prepare Renewal Locally', 'ZATCA CSID Renewal',
            'Pending Renewal Owner Key', 'Previous Issuing Chain', 'Declared EGS Identity Key', 'Previous Certificate Hash',
            'Renewal Public Key Hash', 'Renewal CSR Hash', 'Renewal Preparation State'):
        assert text in catalog and any('\u0600' <= letter <= '\u06ff' for letter in catalog[text])
