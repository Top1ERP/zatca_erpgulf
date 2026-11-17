"""Native response metadata contracts, not valid signatures or remote receipts."""

import base64
import hashlib
import json

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import native_response as response
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import (
    artifact_root, node, xml_bytes, UUID, OTHER_UUID, DIGEST, PIH,
)


def evidence(*, indicator='0200000', code='388', environment='Production'):
    root = artifact_root()
    node(root, 'cbc', 'InvoiceTypeCode', code, name=indicator)
    xml = xml_bytes(root)
    original = json.dumps(dict(invoiceHash=DIGEST, uuid=UUID, invoice=base64.b64encode(xml).decode())).encode()
    header = dict(record_id='issuance', source_name='INV-TEST', invoice_uuid=UUID, invoice_hash=DIGEST,
        icv='77', previous_hash=PIH, artifact_sha256=hashlib.sha256(original).hexdigest(), environment=environment,
        endpoint=response.REPORTING if indicator.startswith('02') else response.CLEARANCE,
        base_url_sha256=response.STANDARD_PRODUCTION_BASE_SHA256)
    return header, original, xml


def success(header, xml):
    result = dict(validationResults=dict(status='PASS', errorMessages=[], warningMessages=[], infoMessages=[]))
    if header['endpoint'] == response.REPORTING:
        result['reportingStatus'] = 'REPORTED'
    else:
        result['clearanceStatus'] = 'CLEARED'
        result['clearedInvoice'] = base64.b64encode(xml).decode()
    return result


def assess(header, original, body, *, status=200, changes=None):
    raw = body if type(body) is bytes else json.dumps(body).encode()
    receipt = dict(issuance=header['record_id'], request_sha256=header['artifact_sha256'],
        environment=header['environment'], endpoint=header['endpoint'], http_status=status,
        response_sha256=hashlib.sha256(raw).hexdigest())
    receipt.update(changes or {})
    return response.assess_native_receipt(header, original, receipt, raw)


@pytest.mark.parametrize('indicator', ['0100000', '0200000'])
@pytest.mark.parametrize('code', ['388', '381', '383', '386'])
@pytest.mark.parametrize('environment', ['Sandbox', 'Simulation', 'Production'])
@pytest.mark.parametrize('status', [200, 202])
def test_native_types_and_environments_share_the_operation_contract(indicator, code, environment, status):
    header, original, xml = evidence(indicator=indicator, code=code, environment=environment)
    result = assess(header, original, success(header, xml), status=status)
    assert result.outcome == ('REPORTING_MATCHED' if indicator.startswith('02') else 'CLEARANCE_MATCHED')
    assert result.issues == () and result.has_warnings is (status == 202)
    assert result.returned_xml == (xml if indicator.startswith('01') else None)


@pytest.mark.parametrize('status', [200, 202])
@pytest.mark.parametrize('body', [b'{}', b'<html>PRIVATE</html>', b'{}{}', b'{"reportingStatus":"REPORTED","reportingStatus":"NOT_REPORTED"}'])
def test_generic_success_status_cannot_promote_an_invalid_body(status, body):
    header, original, _ = evidence()
    result = assess(header, original, body, status=status)
    assert result.outcome == 'UNCONFIRMED'
    assert 'PRIVATE' not in repr(result)


@pytest.mark.parametrize('attribute,value', [('issuance', 'OTHER'), ('request_sha256', '0' * 64),
    ('response_sha256', '0' * 64), ('environment', 'Sandbox'), ('endpoint', response.CLEARANCE)])
def test_receipt_cannot_be_assessed_against_another_artifact_or_operation(attribute, value):
    header, original, xml = evidence()
    result = assess(header, original, success(header, xml), changes={attribute: value})
    assert result.outcome == 'UNCONFIRMED' and result.issues == ('response_receipt_binding',)


@pytest.mark.parametrize('status', [200, 208])
def test_clearance_duplicate_requires_bound_returned_xml(status):
    header, original, xml = evidence(indicator='0100000')
    body = success(header, xml)
    expected = 'CLEARANCE_DUPLICATE_MATCHED' if status == 208 else 'CLEARANCE_MATCHED'
    assert assess(header, original, body, status=status).outcome == expected
    root = etree.fromstring(xml)
    root.find('{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}UUID').text = OTHER_UUID
    body['clearedInvoice'] = base64.b64encode(xml_bytes(root)).decode()
    result = assess(header, original, body, status=status)
    assert result.outcome == 'UNCONFIRMED' and 'response_xml_uuid_mismatch' in result.issues


def duplicate_body():
    return dict(reportingStatus='NOT_REPORTED', validationResults=dict(status='ERROR', infoMessages=[], warningMessages=[],
        errorMessages=[dict(type='ERROR', status='ERROR', code=None, category=None,
            message='Invoice was already Reported successfully earlier.')]))


@pytest.mark.parametrize('change', ['none', 'custom_gateway', 'simulation', 'wrong_hash', 'other_error', 'additional_error', 'cleared'])
def test_reporting409_is_restricted_to_exact_production_route_and_duplicate_diagnostic(change):
    header, original, _ = evidence()
    body = duplicate_body()
    if change == 'custom_gateway':
        header['base_url_sha256'] = 'f' * 64
    elif change == 'simulation':
        header['environment'] = 'Simulation'
    elif change == 'wrong_hash':
        body['invoiceHash'] = 'ANOTHER-INVOICE'
    elif change == 'other_error':
        body['validationResults']['errorMessages'][0]['message'] = 'Unrelated conflict'
    elif change == 'additional_error':
        body['validationResults']['errorMessages'].append(dict(type='ERROR', status='ERROR', message='Another issue'))
    elif change == 'cleared':
        body['clearanceStatus'] = 'CLEARED'
    result = assess(header, original, body, status=409)
    assert (result.outcome == 'REPORTING_DUPLICATE_MATCHED') is (change == 'none')


@pytest.mark.parametrize('status', [401, 403, 413, 429, 500, 503, 504])
def test_transport_or_auth_failure_never_becomes_a_corrected_rejection(status):
    header, original, _ = evidence()
    assert assess(header, original, b'NON-JSON-FAILURE', status=status).outcome in ('TECHNICAL_FAILURE', 'AUTHORIZATION_FAILED')


def test_validation400_is_distinct_from_a_plain_bad_gateway_request():
    header, original, _ = evidence()
    body = duplicate_body()
    body['validationResults']['errorMessages'] = [dict(type='ERROR', status='ERROR', code='QRCODE_INVALID', message='Validation failed')]
    assert assess(header, original, body, status=400).outcome == 'VALIDATION_REJECTED'
    assert assess(header, original, b'BAD REQUEST', status=400).outcome == 'UNCONFIRMED'


def test_clearance303_is_an_operation_specific_fallback_observation():
    header, original, _ = evidence(indicator='0100000')
    assert assess(header, original, b'Clearance disabled', status=303).outcome == 'CLEARANCE_DISABLED'
    header, original, _ = evidence()
    assert assess(header, original, b'Clearance disabled', status=303).outcome == 'UNCONFIRMED'
