"""Native custody reader and publication policy; no Files, API or SDK claims."""

import base64
from dataclasses import FrozenInstanceError
import hashlib
import json
import pickle

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import native_artifact as artifact
from zatca_erpgulf.zatca_erpgulf import native_dispatch as dispatch
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import (
    coordinator, boundary, materials, retained_reader,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_response import success
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import node, xml_bytes


QR_PATH = "./cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject"
ORIGINAL = base64.b64encode(b'PRIVATE-ORIGINAL-QR-NOT-A-SIGNED-TLV').decode()
RETURNED = base64.b64encode(b'PRIVATE-RETURNED-QR-NOT-A-SIGNED-TLV').decode()


def custody(c, *, state='PREPARED', indicator='0200000', code='388', fallback=False, clock='09:05:42Z'):
    _xml, saved, receipt = retained_reader(c, accepted=state in ('CLEARED', 'REPORTED'))
    header, _ = c.repository.open_issuance.return_value
    root = etree.fromstring(_xml)
    root.find('cbc:InvoiceTypeCode', NS).text = code
    root.find('cbc:InvoiceTypeCode', NS).set('name', indicator)
    node(root, 'cbc', 'IssueDate', '2026-09-27')
    node(root, 'cbc', 'IssueTime', '09:05:42Z')
    root.find(QR_PATH, NS).text = ORIGINAL
    original_xml = xml_bytes(root)
    header['endpoint'] = 'invoices/clearance/single' if indicator.startswith('01') else 'invoices/reporting/single'
    raw = json.dumps(dict(invoiceHash=header['invoice_hash'], uuid=header['invoice_uuid'],
        invoice=base64.b64encode(original_xml).decode())).encode()
    header['artifact_sha256'] = hashlib.sha256(raw).hexdigest()
    saved.update(header, state=state)
    c.repository.open_issuance.return_value = (header, raw)
    root.find(QR_PATH, NS).text = RETURNED
    root.find('cbc:IssueTime', NS).text = clock
    returned = xml_bytes(root)
    body = success(header, returned)
    receipt.update(endpoint=header['endpoint'], request_sha256=header['artifact_sha256'])
    if fallback:
        prior = dict(receipt, http_status=303, response_sha256=hashlib.sha256(b'disabled').hexdigest())
        c.repository.open_clearance_fallback = lambda saved: (prior, b'disabled')
        receipt['endpoint'] = 'invoices/reporting/single'
        body = {'validationResults': dict(status='PASS', errorMessages=[], warningMessages=[], infoMessages=[]),
            'reportingStatus': 'REPORTED'}
    raw_body = json.dumps(body).encode()
    receipt['response_sha256'] = hashlib.sha256(raw_body).hexdigest()
    c.repository.open_receipt.return_value = (receipt, raw_body)
    return original_xml, returned, receipt


@pytest.mark.parametrize('code', ['388', '381', '383', '386'])
@pytest.mark.parametrize('state', ['PREPARED', 'DISPATCHING', 'OUTCOME_UNKNOWN', 'REJECTED', 'REVIEW_REQUIRED', 'REPORTED'])
def test_simplified_reads_its_generated_original_without_claiming_acceptance(coordinator, state, code):
    c = coordinator
    xml, _, _ = custody(c, state=state, code=code)
    c.b.company.custom_private_key = 'INVALID-KEY-MUST-NOT-BE-READ'
    c.b.frappe.has_permission = lambda doctype, operation, *, doc, user, raise_exception=True: operation == 'read'
    result = artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert result.source_kind == 'SIMPLIFIED_GENERATED_XML' and result.xml_bytes == xml
    assert result.qr_payload == ORIGINAL and result.accepted is (state == 'REPORTED')
    assert result.xml_sha256 == hashlib.sha256(xml).hexdigest()
    assert result.qr_payload_sha256 == hashlib.sha256(ORIGINAL.encode()).hexdigest()
    assert (result.issue_date, result.issue_time) == ('2026-09-27', '09:05:42Z')
    assert not c.state.committed and c.state.rolled_back
    c.b.request.assert_not_called()


@pytest.mark.parametrize('code', ['388', '381', '383', '386'])
@pytest.mark.parametrize('fallback', [False, True])
def test_standard_uses_cleared_xml_or_verified_accepted_303_original(coordinator, code, fallback):
    c = coordinator
    original, returned, _ = custody(c, indicator='0100000', code=code,
        state='REPORTED' if fallback else 'CLEARED', fallback=fallback)
    result = artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe)
    assert result.accepted and result.xml_bytes == (original if fallback else returned)
    assert result.qr_payload == (ORIGINAL if fallback else RETURNED)
    assert result.source_kind == ('STANDARD_303_REPORTED_XML' if fallback else 'STANDARD_CLEARED_XML')


@pytest.mark.parametrize('state', ['PREPARED', 'DISPATCHING', 'OUTCOME_UNKNOWN', 'REJECTED',
    'REVIEW_REQUIRED', 'REPORTING_FALLBACK_READY'])
def test_standard_qr_presence_or_303_alone_never_grants_publication(coordinator, state):
    c = coordinator
    custody(c, indicator='0100000', state=state)
    with pytest.raises(dispatch.NativeDispatchError, match='native_standard_publication_unconfirmed'):
        artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe)


def test_changed_returned_clock_stops_without_substituting_original_standard_qr(coordinator):
    c = coordinator
    custody(c, indicator='0100000', state='CLEARED', clock='12:05:42+03:00')
    with pytest.raises(dispatch.NativeDispatchError, match='native_artifact_returned_clock_mismatch'):
        artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe)


@pytest.mark.parametrize('fault', ['source_acl', 'receipt', 'qr', 'legacy'])
def test_native_failures_do_not_fall_back_to_saved_attachments(coordinator, fault):
    c = coordinator
    custody(c, state='REPORTED')
    if fault == 'source_acl':
        c.b.frappe.has_permission = lambda doctype, operation, *, doc, user, raise_exception=True: False
    elif fault == 'receipt':
        receipt, raw = c.repository.open_receipt.return_value
        receipt['response_sha256'] = '0' * 64
    elif fault == 'qr':
        header, raw = c.repository.open_issuance.return_value
        body = json.loads(raw)
        body['invoice'] = base64.b64encode(base64.b64decode(body['invoice']).replace(ORIGINAL.encode(), b'not-base64')).decode()
        raw = json.dumps(body).encode()
        header['artifact_sha256'] = hashlib.sha256(raw).hexdigest()
        # No receipt is needed to detect a malformed QR in a local original.
        c.repository.find_source_issuance.return_value['state'] = 'PREPARED'
        c.repository.open_issuance.return_value = (header, raw)
    else:
        c.b.sales.custom_zatca_issuing_unit = None
        assert artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe) is None
        c.factory.assert_not_called()
        return
    with pytest.raises(dispatch.NativeDispatchError):
        artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe)


def test_artifact_view_is_immutable_redacted_and_cannot_be_queued(coordinator):
    c = coordinator
    custody(c)
    result = artifact.read_native_artifact('Sales Invoice', 'SI', runtime=c.b.frappe)
    with pytest.raises(FrozenInstanceError):
        result.qr_payload = 'changed'
    with pytest.raises(TypeError, match='not_serializable'):
        pickle.dumps(result)
    assert 'PRIVATE' not in repr(result) and ORIGINAL not in repr(result)
