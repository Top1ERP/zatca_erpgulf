"""Native metadata/signing/formatter/request capture, ephemeral keys only."""

import base64
from contextvars import copy_context
from datetime import datetime, timezone
import json
from pathlib import Path
import pickle
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from zatca_erpgulf.zatca_erpgulf import createxml,posxml,icv,qr_timestamp,sign_invoice,sign_invoice_first,credential_settings,submission_context
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.invoice_payload import read_invoice_payload
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import confirm_issuing_transport
from zatca_erpgulf.zatca_erpgulf.native_preparation import (
    ACTIVE_PREPARATION,NativePreparationError,PreparedRequestHandoff,native_preparation,source_observation_sha256,
)
from zatca_erpgulf.zatca_erpgulf.signed_xml_pipeline import SigningTools,sign_invoice_xml
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import boundary,materials,setup,scope

UUID='40000000-0000-4000-8000-000000000002'


def registration(b,owner,material):
    import hashlib
    from cryptography.hazmat.primitives import serialization
    return dict(record_id='30000000-0000-4000-8000-000000000001',environment='Production',last_icv='0',
        previous_hash=INITIAL_PREVIOUS_HASH,seller_tax_id=b.company.tax_id,
        owner_doctype=owner.doctype,owner_name=owner.name,
        certificate_sha256=hashlib.sha256(material.cert.public_bytes(serialization.Encoding.DER)).hexdigest(),
        public_key_sha256=hashlib.sha256(material.cert.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest())


def reader(path):
    return base64.b64encode(Path(path).read_text(encoding='utf-8').lstrip().encode()).decode()


@pytest.mark.parametrize('kind,index',[('company',0),('device',2),('linked',1)])
@pytest.mark.parametrize('doctype',['sales','pos'])
def test_native_producer_handoff_has_exact_request_without_http_or_invoice_writes(boundary,materials,monkeypatch,kind,index,doctype):
    b=boundary;owner=setup(b,monkeypatch,kind);source=getattr(b,doctype)
    b.company.company_name='Synthetic issuer'
    address=Document(address_line1='Test Street',address_line2='District',city='Riyadh',custom_building_number='1234',pincode='12345',state='')
    monkeypatch.setattr(sign_invoice,'_onboarding_address',lambda *args:address)
    instant=datetime(2026,11,10,9,5,42,tzinfo=timezone.utc)
    _unused,xml=sign_invoice._build_onboarding_invoice_xml(b.company,'Simplified Invoice',issue_instant=instant)
    from lxml import etree
    root=etree.fromstring(xml.encode())
    ns={'cbc':'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        'cac':'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'}
    root.find('cbc:ID',ns).text=source.name;root.find('cbc:UUID',ns).text=UUID
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID",namespaces=ns)[0].text='1'
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",namespaces=ns)[0].text=INITIAL_PREVIOUS_HASH
    xml=etree.tostring(root).decode()
    with pytest.raises(PreparedRequestHandoff) as caught:
        with native_preparation(b.frappe,source_identity=(source.doctype,source.name),company_name=b.company.name,
                                chain=registration(b,owner,materials[index]),invoice_uuid=UUID,owner_check=lambda:True) as ticket:
            with scope(b,source) as issuer:
                signed=sign_invoice_xml(xml,'TC',source,tools=SigningTools.from_namespace(vars(sign_invoice_first)))
                issuer.expect_prepared_payload(UUID,signed.encoded_hash)
                path=sign_invoice_first.structuring_signedxml(source.name,signed.xml)
                assert Path(path).is_file() and Path(path).stat().st_mode & 0o777==0o600
                selection=submission_context.get_submission_context('TC',source,source.name,'invoices/reporting/single',expected_doctype=source.doctype)
                payload=read_invoice_payload(UUID,signed.encoded_hash,path,read_xml=reader)
                try:confirm_issuing_transport('TC',source,runtime=b.frappe)
                except NativePreparationError as error:pytest.fail(error.code)
    packet=caught.value.packet
    assert json.loads(packet.request_bytes)==payload.as_payload()
    assert packet.source_doctype==source.doctype and packet.source_name==source.name
    assert packet.certificate_sha256==registration(b,owner,materials[index])['certificate_sha256']
    assert packet.icv=='1' and packet.previous_hash==INITIAL_PREVIOUS_HASH
    assert not Path(path).exists() and ticket.closed and ACTIVE_PREPARATION.get() is None
    assert not issuer.transport_started
    b.request.assert_not_called();b.frappe.db.commit.assert_not_called()
    with pytest.raises(TypeError):pickle.dumps(packet)
    assert 'PRIVATE KEY' not in repr(packet) and 'invoice' not in repr(packet).lower()


@pytest.mark.parametrize('doctype',['sales','pos'])
def test_native_metadata_and_counter_use_ticket_without_legacy_commits(boundary,materials,monkeypatch,doctype):
    b=boundary;owner=setup(b,monkeypatch,'company');source=getattr(b,doctype)
    source.posting_date='2026-11-16';source.posting_time='09:05:42';source.custom_uuid='OLD-LOCAL-VALUE';source.custom_zatca_icv=77
    source.db_set=Mock()
    monkeypatch.setattr(qr_timestamp,'get_system_timezone',lambda:'UTC')
    for module in (createxml,posxml,icv):
        monkeypatch.setattr(module,'frappe',b.frappe);monkeypatch.setattr(module,'_',lambda text:text)
    module=createxml if doctype=='sales' else posxml
    with native_preparation(b.frappe,source_identity=(source.doctype,source.name),company_name=b.company.name,
                            chain=registration(b,owner,materials[0]),invoice_uuid=UUID,owner_check=lambda:True):
        _root,actual,doc=module.salesinvoice_data(ET.Element('Invoice'),source.name)
        assert actual==UUID and doc is source
        assert icv.get_icv(source)=='1'
        assert credential_settings.get_previous_invoice_hash('TC',source)==INITIAL_PREVIOUS_HASH
    assert source.custom_uuid=='OLD-LOCAL-VALUE' and source.custom_zatca_icv==77
    source.db_set.assert_not_called();b.frappe.db.commit.assert_not_called()


def test_ticket_cannot_allow_a_standalone_http_helper_without_issuing_scope(boundary,materials,monkeypatch):
    b=boundary;owner=setup(b,monkeypatch,'company')
    with native_preparation(b.frappe,source_identity=(b.sales.doctype,b.sales.name),company_name=b.company.name,
                            chain=registration(b,owner,materials[0]),invoice_uuid=UUID,owner_check=lambda:True):
        with pytest.raises(NativePreparationError) as caught:confirm_issuing_transport('TC',b.sales,runtime=b.frappe)
        assert caught.value.code=='native_preparation_scope_missing'
    b.request.assert_not_called()


def test_retained_ticket_context_cannot_supply_identity_after_exit(boundary,materials,monkeypatch):
    b=boundary;owner=setup(b,monkeypatch,'company')
    with native_preparation(b.frappe,source_identity=(b.sales.doctype,b.sales.name),company_name=b.company.name,
                            chain=registration(b,owner,materials[0]),invoice_uuid=UUID,owner_check=lambda:True) as ticket:child=copy_context()
    with pytest.raises(NativePreparationError):child.run(ticket.require,b.frappe)


def test_native_source_fingerprint_is_typed_and_unambiguous_without_serializing_mutable_objects():
    identity=('Sales Invoice','SYNTHETIC')
    assert source_observation_sha256(identity,('1',))!=source_observation_sha256(identity,(1,))
    assert source_observation_sha256(identity,('ab','c'))!=source_observation_sha256(identity,('a','bc'))
    assert source_observation_sha256(identity,(b'1',))!=source_observation_sha256(identity,('1',))
    with pytest.raises(NativePreparationError):source_observation_sha256(identity,{'mutable':[]})
