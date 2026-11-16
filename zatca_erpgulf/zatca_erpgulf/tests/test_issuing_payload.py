"""Actual formatter, temporary files and request reader; no HTTP/site initialization."""

import base64
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import sign_invoice_first
from zatca_erpgulf.zatca_erpgulf.invoice_payload import read_invoice_payload
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import (
    IssuingAttemptError, confirm_issuing_transport,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_issuing_attempt import (
    boundary, materials, setup, scope,
)

XML = '<?xml version="1.0" encoding="UTF-8"?><Invoice><Value>115.00</Value></Invoice>'


def reader(path):
    return base64.b64encode(Path(path).read_text(encoding='utf-8').lstrip().encode()).decode()


@pytest.mark.parametrize('purpose', ['production', 'compliance'])
@pytest.mark.parametrize('change', ['none', 'content', 'uuid', 'hash', 'path', 'missing'])
def test_canonical_writer_and_request_value_binding(boundary, monkeypatch, tmp_path, purpose, change):
    b = boundary
    setup(b, monkeypatch, 'company')
    monkeypatch.setattr(sign_invoice_first, 'frappe', b.frappe)
    b.frappe.local = type('Local', (), {'site': str(tmp_path)})()
    (tmp_path/'private/files').mkdir(parents=True)
    with scope(b, b.sales, purpose) as current:
        current.expect_prepared_payload('U', 'H')
        path = sign_invoice_first.structuring_signedxml('LOCAL', XML)
        uuid, digest = 'U', 'H'
        original = Path(path).read_bytes()
        if change == 'content': Path(path).write_bytes(original.replace(b'115.00', b'999.00'))
        if change == 'uuid': uuid = 'CHANGED'
        if change == 'hash': digest = 'CHANGED'
        if change == 'path':
            copy = tmp_path/'copy.xml'
            copy.write_bytes(original)
            path = str(copy)
        counted = Mock(side_effect=reader)
        if change != 'missing':
            payload = read_invoice_payload(uuid, digest, path, read_xml=counted)
            counted.assert_called_once_with(path)
        if change == 'none':
            assert payload.xml_text() == original.decode()
            confirm_issuing_transport('TC', b.sales, runtime=b.frappe)
            assert current.transport_started
        else:
            with pytest.raises(IssuingAttemptError) as caught:
                confirm_issuing_transport('TC', b.sales, runtime=b.frappe)
            assert caught.value.code in ('issuing_payload_changed', 'issuing_payload_not_observed')
            assert not current.transport_started
    b.request.assert_not_called()
    b.frappe.db.commit.assert_not_called()


def test_existing_xml_same_metadata_content_replacement_is_rejected(boundary, monkeypatch, tmp_path):
    b = boundary
    setup(b, monkeypatch, 'company')
    path = tmp_path/'existing.xml'
    path.write_text(XML)
    with scope(b, b.sales) as current:
        current.seal_xml(str(path), path.read_bytes())
        path.write_text(XML.replace('115.00', '999.00'))
        read_invoice_payload('unchanged-uuid', 'unchanged-hash', str(path), read_xml=reader)
        with pytest.raises(IssuingAttemptError) as caught:
            confirm_issuing_transport('TC', b.sales, runtime=b.frappe)
        assert caught.value.code == 'issuing_payload_changed'
    b.request.assert_not_called()


def test_payload_is_captured_once_and_no_file_reread_is_needed_at_transport(boundary, monkeypatch, tmp_path):
    b = boundary
    setup(b, monkeypatch, 'company')
    path = tmp_path/'sample.xml'
    path.write_text(XML)
    with scope(b, b.sales, 'compliance') as current:
        current.seal_xml(str(path), XML, identity=('U', 'H'))
        payload = read_invoice_payload('U', 'H', str(path), read_xml=reader)
        path.unlink()
        confirm_issuing_transport('TC', b.sales, runtime=b.frappe)
        assert payload.xml_text() == XML
    b.request.assert_not_called()


def test_expired_child_context_blocks_before_reader(boundary, monkeypatch):
    from contextvars import copy_context
    b = boundary
    setup(b, monkeypatch, 'company')
    with scope(b, b.sales): child = copy_context()
    read = Mock()
    with pytest.raises(IssuingAttemptError):
        child.run(read_invoice_payload, 'U', 'H', 'unused', read_xml=read)
    read.assert_not_called()


@pytest.mark.parametrize('doctype', ['sales', 'pos'])
@pytest.mark.parametrize('kind,index', [('company', 0), ('device', 2), ('linked', 1)])
@pytest.mark.parametrize('validation_type', [
    'Simplified Invoice', 'Standard Invoice', 'Simplified Credit Note',
    'Standard Credit Note', 'Simplified Debit Note', 'Standard Debit Note',
])
def test_native_signature_qr_and_mocked_compliance_use_one_selected_bundle(
    boundary, materials, monkeypatch, tmp_path, doctype, kind, index, validation_type,
):
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from lxml import etree
    from zatca_erpgulf.zatca_erpgulf import sign_invoice as invoices
    from zatca_erpgulf.zatca_erpgulf.signed_xml_pipeline import SigningTools, sign_invoice_xml
    from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
    from zatca_erpgulf.zatca_erpgulf.tests.test_signed_xml_pipeline import decode_tags
    b = boundary
    owner = setup(b, monkeypatch, kind)
    source = getattr(b, doctype)
    source.custom_zatca_invoice_type = validation_type
    b.company.company_name = 'Synthetic issuer'
    address = Document(address_line1='Test Street', address_line2='Test District', city='Riyadh',
                       custom_building_number='1234', pincode='12345', state='')
    monkeypatch.setattr(invoices, '_onboarding_address', lambda *args:address)
    instant = datetime(2026, 11, 10, 9, 5, 42, tzinfo=timezone.utc)
    monkeypatch.setattr(sign_invoice_first, 'datetime', SimpleNamespace(utcnow=lambda:instant.replace(tzinfo=None)))
    uuid, xml = invoices._build_onboarding_invoice_xml(b.company, validation_type, issue_instant=instant)
    monkeypatch.setattr(sign_invoice_first, 'xml_base64_decode', reader)
    # The fixture owns requests.request: the native HTTP adapter runs offline.
    with scope(b, source, 'compliance') as current:
        material = current.signing_material()
        signed = sign_invoice_xml(xml, 'TC', source, tools=SigningTools.from_namespace(vars(sign_invoice_first)))
        formatted = sign_invoice_first.format_zatca_signed_xml(signed.xml)
        path = tmp_path/'sample.xml'
        path.write_text(formatted, encoding='utf-8')
        current.seal_xml(str(path), formatted, identity=(uuid, signed.encoded_hash))
        result = sign_invoice_first.compliance_api_call(uuid, signed.encoded_hash, str(path), 'TC', source)
        assert result['validationResults']['status'] == 'PASS'
        call = b.request.call_args
        assert call.args == ('POST',)
        assert call.kwargs['headers']['Authorization'] == material.authorization.header
        assert material.authorization.owner_name == owner.name
        sent = json.loads(call.kwargs['data'])
        assert sent['uuid'] == uuid and sent['invoiceHash'] == signed.encoded_hash
        assert base64.b64decode(sent['invoice']) == formatted.encode()
        root = etree.fromstring(formatted.encode())
        namespaces = {'ds':'http://www.w3.org/2000/09/xmldsig#'}
        assert root.find('.//ds:X509Certificate', namespaces).text == materials[index].text
        signature = root.find('.//ds:SignatureValue', namespaces).text
        materials[index].cert.public_key().verify(base64.b64decode(signature),
            base64.b64decode(signed.encoded_hash), ec.ECDSA(hashes.SHA256()))
        tags = dict(decode_tags(signed.qr_payload))
        assert tags[6] == signed.encoded_hash.encode() and tags[7] == signature.encode()
    b.request.assert_called_once()
    b.frappe.db.commit.assert_not_called()
    for record in (b.company, b.device, b.linked):
        record.save.assert_not_called()
        record.db_set.assert_not_called()


from zatca_erpgulf.zatca_erpgulf.tests.test_item_template_mode import (
    ROUTES, isolated, route_boundary,
)


@pytest.mark.parametrize('route', ROUTES[:6])
@pytest.mark.parametrize('substitution', ['different_invoice', 'same_invoice_changed_business'])
def test_metadata_return_is_rebound_before_party_or_counter_builders(route_boundary, monkeypatch, route, substitution):
    from copy import copy
    from inspect import unwrap
    b = route_boundary
    module, name, doctype, purpose = route
    b.doc.doctype = doctype
    def metadata(root, *args, **kwargs):
        changed = copy(b.doc) if substitution == 'different_invoice' else b.doc
        if substitution == 'different_invoice': changed.name = 'DIFFERENT-INVOICE'
        else: changed.grand_total = 999
        return root, 'TEST-UUID', changed
    monkeypatch.setattr(module, 'salesinvoice_data', metadata)
    parties = Mock(side_effect=AssertionError('party/counter preparation must not run'))
    monkeypatch.setattr(module, 'populate_invoice_parties', parties)
    with pytest.raises(IssuingAttemptError): unwrap(getattr(module, name))(b.doc.name)
    parties.assert_not_called()
    b.doc.db_set.assert_not_called()
    b.app.db.commit.assert_not_called()
