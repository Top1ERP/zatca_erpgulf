"""Execution scope with native credential helpers, entirely fake records/HTTP."""

import base64
import json
import pickle
from contextvars import copy_context
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives import serialization

from zatca_erpgulf.zatca_erpgulf import api_settings, credential_settings, submission_context
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import (
    ACTIVE, REVIEW, IssuingAttemptError, active_attempt, issuing_attempt,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import (
    boundary, materials as legacy_materials,
)


@pytest.fixture(scope='module')
def materials():
    """Ephemeral certificates declare the same test taxpayer as their saved rows."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID
    result = legacy_materials.__wrapped__()
    for material in result:
        key = serialization.load_pem_private_key(material.pem.encode(), password=None)
        cert = (x509.CertificateBuilder().subject_name(material.cert.subject)
            .issuer_name(material.cert.issuer).public_key(key.public_key())
            .serial_number(material.cert.serial_number)
            .not_valid_before(material.cert.not_valid_before_utc)
            .not_valid_after(material.cert.not_valid_after_utc)
            .add_extension(x509.SubjectAlternativeName([x509.DirectoryName(x509.Name([
                x509.NameAttribute(NameOID.USER_ID, 'TEST-VAT'),
            ]))]), critical=False).sign(key, hashes.SHA256()))
        material.cert = cert
        material.text = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
    return result


def setup(b, monkeypatch, kind):
    b.company.custom_select = 'Production'
    b.company.custom_production_url = 'https://example.invalid/core/'
    b.company.custom_simulation_url = 'https://example.invalid/simulation/'
    b.company.custom_sandbox_url = 'https://example.invalid/developer-portal/'
    b.frappe.log_error = Mock()
    for record in (b.company, b.device, b.linked):
        token = base64.b64encode(record.custom_certificate.encode())
        authorization = base64.b64encode(token + b':TEST-ONLY-SECRET').decode()
        record.custom_basic_auth_from_csid = authorization
        record.custom_basic_auth_from_production = authorization
        record.custom_final_auth_csid = authorization
    def throw(message, *, exc=None, **kwargs):
        raise exc if isinstance(exc, Exception) else AssertionError(message)
    b.frappe.throw = Mock(side_effect=throw)
    for module in (api_settings, submission_context):
        monkeypatch.setattr(module, 'frappe', b.frappe)
        monkeypatch.setattr(module, '_', lambda text:text)
    b.company.custom_pih = 'COMPANY-PIH'
    b.device.custom_pih = 'DEVICE-PIH'
    b.linked.custom_pih = 'LINKED-PIH'
    if kind == 'company':
        b.sales.custom_zatca_pos_name = None
        b.pos.custom_zatca_pos_name = None
        return b.company
    if kind == 'linked':
        b.device.custom_linked_doctype = 'B'
        b.device.custom__use_company_certificate__keys = 1
        return b.linked
    return b.device


def scope(b, source, purpose='production'):
    return issuing_attempt('TC', source, purpose=purpose, runtime=b.frappe, translate=lambda text:text)


@pytest.mark.parametrize('kind,index', [('company', 0), ('device', 2), ('linked', 1)])
@pytest.mark.parametrize('doctype', ['sales', 'pos'])
@pytest.mark.parametrize('purpose', ['production', 'compliance'])
@pytest.mark.parametrize('wire', ['object', 'dict', 'json'])
def test_native_helpers_keep_one_selected_material_and_route(boundary, materials, monkeypatch, kind, index, doctype, purpose, wire):
    b = boundary
    owner = setup(b, monkeypatch, kind)
    source = getattr(b, doctype)
    if wire != 'object':
        source = {'doctype':source.doctype, 'name':source.name, 'custom_private_key':'INJECTED'}
        if wire == 'json': source = json.dumps(source)
    with scope(b, source, purpose) as captured:
        assert credential_settings.resolve_credential_owner('TC', source) is captured.owner
        before = b.frappe.get_doc.call_count
        text = credential_settings.get_signing_certificate('TC', source)
        key = credential_settings.get_signing_key('TC', source)
        public = credential_settings.get_certificate_public_key('TC', source)
        assert text == materials[index].text
        assert key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) == public
        assert b.frappe.get_doc.call_count == before
        assert credential_settings.get_previous_invoice_hash('TC', source) == owner.custom_pih
        endpoint = 'compliance/invoices' if purpose == 'compliance' else 'invoices/reporting/single'
        auth = credential_settings.get_api_authorization('TC', source, purpose=purpose)
        route = api_settings.get_company_api_route('TC', endpoint)
        assert route.environment == 'Production'
        assert auth.owner_name == owner.name
        assert 'PRIVATE KEY' not in repr(captured) and owner.custom_private_key not in repr(captured)
        with pytest.raises(TypeError): pickle.dumps(captured)
    assert ACTIVE.get() is None and captured.closed
    b.request.assert_not_called()
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize('kind', ['company', 'device', 'linked'])
def test_rotation_keeps_signer_material_but_blocks_transport(boundary, materials, monkeypatch, kind):
    b = boundary
    owner = setup(b, monkeypatch, kind)
    with scope(b, b.sales):
        original = credential_settings.get_signing_certificate('TC', b.sales)
        owner.custom_certificate = materials[0 if kind != 'company' else 1].text
        owner.custom_private_key = 'ROTATED-PRIVATE-MATERIAL'
        assert credential_settings.get_signing_certificate('TC', b.sales) == original
        with pytest.raises(IssuingAttemptError) as caught:
            submission_context.get_submission_context('TC', b.sales, b.sales.name, 'invoices/reporting/single')
        assert caught.value.code == 'issuing_settings_changed'
        b.frappe.log_error.assert_called_once()
        assert 'ROTATED-PRIVATE' not in b.frappe.log_error.call_args.kwargs['message']
    b.request.assert_not_called()


@pytest.mark.parametrize('field,value', [
    ('company', 'OTHER'), ('custom_zatca_pos_name', 'OTHER-UNIT'),
    ('grand_total', 123), ('currency', 'USD'), ('posting_time', '10:00:00'),
])
def test_observed_source_business_changes_stop_selection(boundary, monkeypatch, field, value):
    b = boundary
    setup(b, monkeypatch, 'company')
    with scope(b, b.sales):
        setattr(b.sales, field, value)
        with pytest.raises(IssuingAttemptError):
            credential_settings.get_api_authorization('TC', b.sales, purpose='production')
    b.request.assert_not_called()


@pytest.mark.parametrize('field,value', [
    ('custom_uuid', 'GENERATED'), ('custom_zatca_status', 'Not Submitted'),
    ('custom_zatca_full_response', 'LOCAL'), ('ksa_einv_qr', '/private/test.png'),
    ('modified', '2026-11-16 18:00:00'),
])
def test_derived_output_changes_are_not_mistaken_for_business_change(boundary, monkeypatch, field, value):
    b = boundary
    setup(b, monkeypatch, 'company')
    with scope(b, b.sales):
        setattr(b.sales, field, value)
        credential_settings.get_api_authorization('TC', b.sales, purpose='production')
    b.request.assert_not_called()


@pytest.mark.parametrize('purpose', ['production', 'compliance', 'debug'])
def test_nested_same_scope_reuses_and_wrong_purpose_cannot_replace_it(boundary, monkeypatch, purpose):
    b = boundary
    setup(b, monkeypatch, 'company')
    with scope(b, b.sales, purpose) as captured:
        with scope(b, b.sales, purpose) as nested:
            assert nested is captured
        assert not captured.closed and ACTIVE.get() is captured
        with pytest.raises(IssuingAttemptError):
            with scope(b, b.sales, 'debug' if purpose != 'debug' else 'production'):
                pytest.fail('wrong-purpose context entered')
        assert ACTIVE.get() is captured
    assert ACTIVE.get() is None


def test_retained_child_context_cannot_use_material_after_parent_exit(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    with scope(b, b.sales):
        child = copy_context()
    with pytest.raises(IssuingAttemptError) as caught:
        child.run(credential_settings.get_signing_certificate, 'TC', b.sales)
    assert caught.value.code == 'issuing_context_lifetime'
    assert ACTIVE.get() is None


def test_cross_site_and_cross_source_are_rejected_before_material_read(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    b.frappe.local = SimpleNamespace(site='fictional-A')
    with scope(b, b.sales):
        with pytest.raises(IssuingAttemptError):
            credential_settings.get_signing_certificate('TC', b.pos)
        b.frappe.local.site = 'fictional-B'
        with pytest.raises(IssuingAttemptError):
            credential_settings.get_signing_certificate('TC', b.sales)
        b.frappe.local.site = 'fictional-A'
    assert ACTIVE.get() is None


def test_unrelated_context_does_not_leak_into_copied_empty_context(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    empty = copy_context()
    with scope(b, b.sales):
        assert empty.run(ACTIVE.get) is None
    assert ACTIVE.get() is None


def test_failure_resets_scope_and_next_attempt_reads_fresh_values(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    marker = RuntimeError('synthetic failure')
    with pytest.raises(RuntimeError) as caught:
        with scope(b, b.sales): raise marker
    assert caught.value is marker and ACTIVE.get() is None
    b.company.custom_basic_auth_from_production = 'NEXT-ATTEMPT'
    with scope(b, b.sales):
        auth = credential_settings.get_api_authorization('TC', b.sales, purpose='production')
        assert auth.header == 'Basic NEXT-ATTEMPT'


def test_native_v16_tax_child_changes_are_part_of_source_observation(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    class Row(SimpleNamespace):
        def get(self, key, default=None): return getattr(self, key, default)
    b.sales.item_wise_tax_details = [Row(name='tax-row', item_row='item-row', tax_row='tax', amount=15, rate=15)]
    with scope(b, b.sales):
        b.sales.item_wise_tax_details[0].rate = 5
        with pytest.raises(IssuingAttemptError):
            credential_settings.get_api_authorization('TC', b.sales, purpose='production')


def test_long_unchanged_native_text_does_not_inherit_diagnostic_projection_limits(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    class Row(SimpleNamespace):
        def get(self, key, default=None): return getattr(self, key, default)
    b.sales.items = [Row(description='x'*100000)]
    with scope(b, b.sales):
        credential_settings.get_api_authorization('TC', b.sales, purpose='production')


@pytest.mark.parametrize('language', ['en', 'ar'])
def test_scope_review_displays_translation_and_logs_only_canonical_english(boundary, monkeypatch, language):
    import csv
    from pathlib import Path

    b = boundary
    setup(b, monkeypatch, 'company')
    with (Path(__file__).resolve().parents[2] / 'translations/ar.csv').open(newline='') as stream:
        catalog = dict(csv.reader(stream))
    translate = lambda text:catalog.get(text, text) if language == 'ar' else text
    with issuing_attempt('TC', b.sales, purpose='production', runtime=b.frappe, translate=translate):
        with pytest.raises(IssuingAttemptError):
            credential_settings.get_api_authorization('TC', b.sales, purpose='compliance')
    b.frappe.throw.assert_called_once()
    assert b.frappe.throw.call_args.args[0] == translate(REVIEW)
    assert b.frappe.log_error.call_args.kwargs['message'].endswith(REVIEW)
    if language == 'ar': assert translate(REVIEW) != REVIEW


@pytest.mark.parametrize('purpose', ['production', 'compliance'])
def test_purpose_token_selects_its_certificate_without_overwriting_other_purpose(boundary, materials, monkeypatch, purpose):
    from datetime import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    b = boundary
    setup(b, monkeypatch, 'company')
    original = materials[0]
    key = serialization.load_pem_private_key(original.pem.encode(), password=None)
    renewed = (x509.CertificateBuilder().subject_name(original.cert.subject)
        .issuer_name(original.cert.issuer).public_key(key.public_key()).serial_number(4242)
        .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2030, 1, 1))
        .add_extension(original.cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value, critical=False)
        .sign(key, hashes.SHA256()))
    renewed_text = base64.b64encode(renewed.public_bytes(serialization.Encoding.DER)).decode()
    token = base64.b64encode(renewed_text.encode())
    renewed_auth = base64.b64encode(token + b':TEST-ONLY-SECRET').decode()
    b.company.custom_certificate = renewed_text
    b.company.custom_basic_auth_from_production = renewed_auth
    stored = dict(vars(b.company))
    with scope(b, b.sales, purpose):
        selected = credential_settings.get_signing_certificate('TC', b.sales)
        assert selected == (renewed_text if purpose == 'production' else original.text)
        credential_settings.get_signing_key('TC', b.sales)
        assert credential_settings.get_api_authorization('TC', b.sales, purpose=purpose).purpose == purpose
    assert vars(b.company) == stored
    b.company.save.assert_not_called()
    b.company.db_set.assert_not_called()


@pytest.mark.parametrize('legacy_text', [None, '', 'not-a-valid-certificate'])
def test_native_purpose_certificate_does_not_depend_on_a_generic_legacy_copy(boundary, materials, monkeypatch, legacy_text):
    b = boundary
    setup(b, monkeypatch, 'company')
    b.company.custom_certificate = legacy_text
    with scope(b, b.sales):
        assert credential_settings.get_signing_certificate('TC', b.sales) == materials[0].text
    assert b.company.custom_certificate == legacy_text
    b.company.db_set.assert_not_called()


@pytest.mark.parametrize('purpose', ['production', 'compliance'])
@pytest.mark.parametrize('taxpayer', [None, '', 'OTHER-TAXPAYER'])
def test_certificate_taxpayer_mismatch_cannot_reach_signing(boundary, monkeypatch, purpose, taxpayer):
    b = boundary
    setup(b, monkeypatch, 'company')
    b.company.tax_id = taxpayer
    with scope(b, b.sales, purpose):
        with pytest.raises(IssuingAttemptError) as caught:
            credential_settings.get_signing_key('TC', b.sales)
        assert caught.value.code in ('credential_taxpayer_missing', 'credential_taxpayer_mismatch')
    b.request.assert_not_called()
    b.company.db_set.assert_not_called()


def test_nested_batch_cannot_replace_prepared_invoice_baseline(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    with scope(b, b.company, 'compliance') as current:
        current.bind_prepared_invoice(b.sales)
        b.sales.grand_total = 150
        with pytest.raises(IssuingAttemptError) as caught:
            current.bind_prepared_invoice(b.sales)
        assert caught.value.code == 'issuing_prepared_source_changed'


@pytest.mark.parametrize('language', ['en', 'ar'])
def test_post_invocation_review_does_not_claim_no_request_was_sent(boundary, monkeypatch, language):
    import csv
    from pathlib import Path
    from zatca_erpgulf.zatca_erpgulf.issuing_attempt import UNCERTAIN
    b = boundary
    setup(b, monkeypatch, 'company')
    with (Path(__file__).resolve().parents[2] / 'translations/ar.csv').open(newline='') as stream:
        catalog = dict(csv.reader(stream))
    translate = lambda text:catalog.get(text, text) if language == 'ar' else text
    with issuing_attempt('TC', b.sales, purpose='production', runtime=b.frappe, translate=translate) as current:
        current.transport_started = True
        current.closed = True
        with pytest.raises(IssuingAttemptError) as caught:
            current.require_runtime(b.frappe)
        assert str(caught.value) == UNCERTAIN
        assert 'No request was sent' not in str(caught.value)
        assert b.frappe.throw.call_args.args[0] == translate(UNCERTAIN)
        assert b.frappe.log_error.call_args.kwargs['message'].endswith(UNCERTAIN)
        if language == 'ar': assert translate(UNCERTAIN) != UNCERTAIN


@pytest.mark.parametrize('phase,enabled,allowed', [
    ('Phase-2', 1, True), ('Phase-2', '1', True), ('Phase-1', 1, False),
    ('', 1, False), (None, 1, False), ('Phase-2', 0, False),
])
def test_ordinary_entry_phase_and_acl_precede_any_metadata(boundary, monkeypatch, phase, enabled, allowed):
    from zatca_erpgulf.zatca_erpgulf.issuing_attempt import invoice_issuing_attempt
    b = boundary
    setup(b, monkeypatch, 'company')
    b.company.custom_phase_1_or_2 = phase
    b.company.custom_zatca_invoice_enabled = enabled
    calls = []
    def engine(doctype, operation, *, doc, user, print_logs=True):
        assert print_logs is False
        calls.append((doctype, operation, doc.name, user))
        return True
    b.frappe.has_permission = engine
    def enter():
        with invoice_issuing_attempt('Sales Invoice', b.sales.name, runtime=b.frappe,
                                     translate=lambda text:text, namespace={}) as current:
            return current.company.name
    if allowed: assert enter() == b.company.name
    else:
        with pytest.raises(IssuingAttemptError) as caught: enter()
        assert caught.value.code == 'issuing_production_phase'
    assert [call[:2] for call in calls] == [('Sales Invoice','read'), ('Sales Invoice','write'), ('Company','read')]
    b.request.assert_not_called()
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize('denied', [('Sales Invoice','read'), ('Sales Invoice','write'), ('Company','read')])
def test_ordinary_source_access_cannot_be_replaced_by_issuer_credentials(boundary, monkeypatch, denied):
    from zatca_erpgulf.zatca_erpgulf.issuing_attempt import invoice_issuing_attempt
    b = boundary
    setup(b, monkeypatch, 'company')
    b.company.custom_phase_1_or_2 = 'Phase-2'
    b.company.custom_zatca_invoice_enabled = 1
    def engine(doctype, operation, *, doc, user, raise_exception=True):
        assert raise_exception is False
        return (doctype, operation) != denied
    b.frappe.has_permission = engine
    signer = Mock()
    with pytest.raises(IssuingAttemptError) as caught:
        with invoice_issuing_attempt('Sales Invoice', b.sales.name, runtime=b.frappe,
                                     translate=lambda text:text, namespace={'digital_signature':signer}):
            pytest.fail('denied source entered preparation')
    assert caught.value.code == 'issuing_source_access'
    signer.assert_not_called()
    b.request.assert_not_called()
    b.frappe.db.commit.assert_not_called()


def test_blank_preferred_phase_cannot_fall_back_to_legacy_phase2(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    b.company.custom_phase_1_or_2 = ''
    b.company.phase_1_or_2 = 'Phase-2'
    b.company.custom_zatca_invoice_enabled = 1
    with scope(b, b.sales) as current:
        with pytest.raises(IssuingAttemptError): current.require_production_configuration()


@pytest.mark.parametrize('subject,alternative,expected,code', [
    ('TEST-VAT', None, 'TEST-VAT', None),
    (None, 'TEST-VAT', 'TEST-VAT', None),
    ('TEST-VAT', 'TEST-VAT', 'TEST-VAT', None),
    (' TEST-VAT ', 'TEST-VAT', 'TEST-VAT', None),
    (None, None, 'TEST-VAT', 'credential_taxpayer_missing'),
    ('OTHER', None, 'TEST-VAT', 'credential_taxpayer_mismatch'),
    ('TEST-VAT', 'OTHER', 'TEST-VAT', 'credential_taxpayer_mismatch'),
])
def test_only_explicit_certificate_taxpayer_claims_are_used(materials, subject, alternative, expected, code):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID
    from zatca_erpgulf.zatca_erpgulf.credential_identity import (
        ORGANIZATION_IDENTIFIER, CredentialIdentityError, require_certificate_taxpayer,
    )
    material = materials[0]
    key = serialization.load_pem_private_key(material.pem.encode(), password=None)
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, 'TEST-VAT')]
    if subject is not None: attributes.append(x509.NameAttribute(ORGANIZATION_IDENTIFIER, subject))
    builder = (x509.CertificateBuilder().subject_name(x509.Name(attributes))
        .issuer_name(material.cert.issuer).public_key(key.public_key()).serial_number(123)
        .not_valid_before(material.cert.not_valid_before_utc).not_valid_after(material.cert.not_valid_after_utc))
    if alternative is not None:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DirectoryName(x509.Name([
            x509.NameAttribute(NameOID.USER_ID, alternative),
        ]))]), critical=False)
    certificate = builder.sign(key, hashes.SHA256())
    if code is None: require_certificate_taxpayer(certificate, expected)
    else:
        with pytest.raises(CredentialIdentityError) as caught:
            require_certificate_taxpayer(certificate, expected)
        assert caught.value.code == code


def test_company_scope_keeps_original_revision_as_provenance(boundary, monkeypatch):
    b = boundary
    setup(b, monkeypatch, 'company')
    b.company.modified = '2026-11-16 09:00:00'
    with scope(b, b.company, 'compliance') as current:
        assert current.source_revision == b.company.modified
        b.company.modified = 'later-output-or-unrelated-setting-save'
        current.confirm_current()  # Business observations, not an asserted DB epoch.
        assert current.source_revision == '2026-11-16 09:00:00'


@pytest.mark.parametrize('invalid', ['not-json', '{broken'])
def test_invalid_source_json_cannot_alias_an_automatic_company_scope(boundary, monkeypatch, invalid):
    b = boundary
    setup(b, monkeypatch, 'company')
    with scope(b, b.company, 'compliance') as current:
        current.require('TC', None, b.frappe)  # The explicit automatic-sample contract.
        with pytest.raises(IssuingAttemptError) as caught:
            current.require('TC', invalid, b.frappe)
        assert caught.value.code == 'issuing_context_source'
    b.request.assert_not_called()
