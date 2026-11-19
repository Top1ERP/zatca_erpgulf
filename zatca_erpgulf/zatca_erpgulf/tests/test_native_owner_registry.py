"""Copied native material cannot become an unmarked legacy issuing identity."""

import base64
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.hazmat.primitives import serialization
import pytest

from zatca_erpgulf.zatca_erpgulf import native_owner_registry as registry, native_owner_guard as guard
from zatca_erpgulf.zatca_erpgulf import native_preparation, submission_context
from zatca_erpgulf.zatca_erpgulf.credential_material import CredentialConfigurationError
from zatca_erpgulf.zatca_erpgulf.credential_identity import declared_egs_identity_key
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import IssuingAttemptError
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_onboarding_response import material, parse
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import boundary, materials, setup, scope


@pytest.mark.parametrize('field',['custom_private_key','custom_public_key','custom_csr_data','custom_certificate',
    'custom_certficate','custom_basic_auth_from_csid','custom_basic_auth_from_production','custom_final_auth_csid'])
def test_known_public_key_is_found_through_each_legacy_material_field(material,field):
    issued=parse(material)
    values={'custom_private_key':material.key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),
        'custom_public_key':material.key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
        'custom_csr_data':base64.b64encode(material.raw).decode(),
        'custom_certificate':issued.certificate_text,'custom_certficate':issued.certificate_text,
        'custom_basic_auth_from_csid':issued.authorization,'custom_basic_auth_from_production':issued.authorization,
        'custom_final_auth_csid':issued.authorization}
    doc=Document(doctype='Company',name='COPY',**{field:values[field]})
    runtime=SimpleNamespace(get_meta=lambda dt:SimpleNamespace(has_field=lambda name:True),
        db=SimpleNamespace(sql=Mock(return_value=[{'name':'NATIVE-UNIT'}])))
    assert registry.has_registered_native_material(runtime,doc)
    assert runtime.db.sql.call_args.args[1]==(issued.public_key_sha256,)
    assert 'PRIVATE' not in runtime.db.sql.call_args.args[0]


def test_invalid_alias_cannot_hide_another_valid_registered_material_field(material):
    doc=Document(doctype='Company',name='COPY',custom_private_key='INVALID',custom_certificate=parse(material).certificate_text)
    assert registry._fingerprints(doc)==(material.header['public_key_sha256'],)


def test_certificate_unit_claims_are_checked_separately_from_the_public_key(material):
    doc=Document(doctype='Company',name='OTHER-OWNER',custom_certificate=parse(material).certificate_text)
    fingerprints,identities=registry._material_evidence(doc,'Production')
    assert fingerprints==(material.header['public_key_sha256'],)
    assert identities==(declared_egs_identity_key('Production',material.header['seller_tax_id'],material.header['csr_serial']),)
    assert registry._material_evidence(doc,'Simulation')[1]!=identities
    assert registry._material_evidence(doc,' Production ')[1]==identities


def test_unmigrated_metadata_and_empty_material_need_no_registry_query():
    doc=Document(doctype='Company',name='LEGACY',custom_private_key='INVALID')
    runtime=SimpleNamespace(get_meta=lambda dt:SimpleNamespace(has_field=lambda name:False),db=SimpleNamespace(sql=Mock()))
    assert not registry.has_registered_native_material(runtime,doc)
    runtime.get_meta=lambda dt:SimpleNamespace(has_field=lambda name:True)
    assert not registry.has_registered_native_material(runtime,doc)
    runtime.db.sql.assert_not_called()


def test_an_installed_registry_query_failure_is_review_with_no_secret_context(material):
    doc=Document(doctype='Company',name='COPY',custom_certificate=parse(material).certificate_text)
    runtime=SimpleNamespace(get_meta=lambda dt:SimpleNamespace(has_field=lambda name:True),
        db=SimpleNamespace(sql=Mock(side_effect=RuntimeError('PRIVATE-SQL-CONTEXT'))))
    with pytest.raises(CredentialConfigurationError) as failed:registry.has_registered_native_material(runtime,doc)
    assert failed.value.__context__ is None and 'PRIVATE' not in str(failed.value)


@pytest.mark.parametrize('operation',['uuid','icv','http','request_only'])
def test_copied_native_keys_or_auth_hold_legacy_generation_and_transport(boundary,materials,monkeypatch,operation):
    b=boundary;setup(b,monkeypatch,'company')
    b.frappe.get_meta=lambda dt:SimpleNamespace(has_field=lambda name:True)
    b.frappe.db.sql=Mock(return_value=[{'name':'REGISTERED-NATIVE-UNIT'}])
    if operation=='request_only':
        with pytest.raises(Exception):
            submission_context.get_submission_context('TC',b.sales,b.sales.name,'invoices/reporting/single')
    else:
        with scope(b,b.sales):
            with pytest.raises(IssuingAttemptError) as failed:
                if operation=='uuid':
                    from zatca_erpgulf.zatca_erpgulf import createxml
                    monkeypatch.setattr(createxml,'frappe',b.frappe)
                    createxml._get_or_create_sales_invoice_uuid(b.sales)
                elif operation=='icv':
                    from zatca_erpgulf.zatca_erpgulf import icv
                    monkeypatch.setattr(icv,'frappe',b.frappe)
                    icv.get_icv(b.sales)
                else:
                    native_preparation.reject_legacy_native_preparation(b.sales,b.frappe)
            assert failed.value.code=='native_dispatch_required'
    assert b.frappe.db.sql.call_count>=1
    assert 'public_key_sha256 IN' in b.frappe.db.sql.call_args.args[0]
    b.request.assert_not_called()
    b.frappe.db.commit.assert_not_called()


@pytest.mark.parametrize('registered',[True,False])
def test_an_unmarked_form_cannot_import_registered_keys_but_unregistered_legacy_edits_are_preserved(material,monkeypatch,registered):
    class Review(Exception):pass
    saved={name:None for name in guard.FIELDS}
    key=material.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    doc=Document(doctype='Company',name='UNMARKED-COPY',**(saved|{'custom_private_key':key}))
    def sql(statement,values=(),**kwargs):
        if 'FROM `tabCompany`' in statement:return [dict(saved)]
        assert 'public_key_sha256 IN' in statement
        return [{'name':'NATIVE-UNIT'}] if registered else []
    runtime=SimpleNamespace(get_meta=lambda dt:SimpleNamespace(has_field=lambda name:True),
        db=SimpleNamespace(sql=Mock(side_effect=sql)),
        throw=Mock(side_effect=lambda text:(_ for _ in ()).throw(Review(text))))
    monkeypatch.setattr(guard,'frappe',runtime);monkeypatch.setattr(guard,'_',lambda text:text)
    if registered:
        with pytest.raises(Review,match='Native ZATCA settings'):guard.validate_native_owner(doc)
    else:
        guard.validate_native_owner(doc)
        runtime.throw.assert_not_called()
