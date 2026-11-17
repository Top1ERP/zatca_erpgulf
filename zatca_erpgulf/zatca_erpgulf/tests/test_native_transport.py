"""Mocked direct-adapter exchange; the offline plugin denies real networking."""

from dataclasses import replace
import hashlib
import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests.structures import CaseInsensitiveDict

from zatca_erpgulf.zatca_erpgulf import native_transport as transport
from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route


@pytest.fixture
def exchange(monkeypatch):
    route = resolve_api_route({'custom_select': 'Production',
        'custom_production_url': 'https://example.invalid/core'}, 'invoices/reporting/single')
    body = b'{"invoiceHash": "ORIGINAL", "uuid": "SYNTHETIC", "invoice": "SYNTHETIC"}'
    runtime = SimpleNamespace(local=SimpleNamespace(site='fictional.invalid'), session=SimpleNamespace(user='operator'))
    invocation = transport.NativeInvocation('issuance', 'attempt', 'fence', 'owner', 'chain', 'fictional.invalid', 'operator',
        route, 'Basic PRIVATE-TEST-ONLY', hashlib.sha256(body).hexdigest(), body)
    response = SimpleNamespace(status_code=200, headers=CaseInsensitiveDict({'x-request-id': 'SYNTHETIC'}),
        history=[], raw=SimpleNamespace(read1=Mock(side_effect=[b' {"status":"PASS"} ', b''])), close=Mock())
    def send(prepared, **kwargs):
        response.request = prepared
        response.url = prepared.url
        return response
    adapter = SimpleNamespace(send=Mock(side_effect=send), close=Mock())
    factory = Mock(return_value=adapter)
    monkeypatch.setattr(transport, 'HTTPAdapter', factory)
    return SimpleNamespace(invocation=invocation, response=response, adapter=adapter, factory=factory, runtime=runtime)


@pytest.mark.parametrize('status', [200, 202, 208, 303, 400, 401, 409, 429, 503])
def test_one_exact_invocation_returns_original_response_without_status_inference(exchange, status):
    e = exchange
    e.response.status_code = status
    result = transport.invoke_saved_request(e.invocation, runtime=e.runtime)
    assert result.http_status == status and result.body == b' {"status":"PASS"} '
    assert result.request_id == 'SYNTHETIC'
    e.factory.assert_called_once_with(max_retries=0)
    prepared = e.adapter.send.call_args.args[0]
    assert prepared.body is e.invocation.request_bytes
    assert prepared.headers['Authorization'] == e.invocation.authorization
    assert prepared.headers['Clearance-Status'] == '0'
    assert e.adapter.send.call_args.kwargs == dict(stream=True, verify=True, cert=None, proxies={}, timeout=(10, 60))
    assert e.adapter.send.call_count == 1
    e.response.close.assert_called_once()
    e.adapter.close.assert_called_once()
    assert not hasattr(result, 'accepted')


def test_clearance_has_its_original_operation_header(exchange):
    e = exchange
    route = replace(e.invocation.route, endpoint='invoices/clearance/single',
        url='https://example.invalid/core/invoices/clearance/single')
    transport.invoke_saved_request(replace(e.invocation, route=route), runtime=e.runtime)
    assert e.adapter.send.call_args.args[0].headers['Clearance-Status'] == '1'


@pytest.mark.parametrize('change', ['digest', 'bytes', 'auth', 'http', 'endpoint'])
def test_binding_failure_does_not_construct_adapter_or_start_http(exchange, change):
    e = exchange
    changes = {'digest': dict(request_sha256='WRONG'), 'bytes': dict(request_bytes=b'CHANGED'),
        'auth': dict(authorization='Basic INVALID\r\nHEADER'),
        'http': dict(route=replace(e.invocation.route, url='http://example.invalid/core/invoices/reporting/single')),
        'endpoint': dict(route=replace(e.invocation.route, endpoint='production/csids'))}
    with pytest.raises(transport.NativeTransportError) as caught:
        transport.invoke_saved_request(replace(e.invocation, **changes[change]), runtime=e.runtime)
    assert not caught.value.invoked
    e.factory.assert_not_called()


@pytest.mark.parametrize('headers', [{'Content-Length': '16777216'}, {'Content-Length': '-1'},
    {'Content-Encoding': 'gzip'}, {'Transfer-Encoding': 'chunked', 'Content-Length': '1'},
    {'x-request-id': 'INVALID\r\nHEADER'}, {'Content-Length': '1'}])
def test_unsafe_or_incomplete_received_entity_is_unknown_without_unbounded_read(exchange, headers):
    e = exchange
    e.response.headers = CaseInsensitiveDict(headers)
    with pytest.raises(transport.NativeTransportError) as caught:
        transport.invoke_saved_request(e.invocation, runtime=e.runtime)
    assert caught.value.invoked and caught.value.code == 'native_transport_outcome_unknown'
    assert e.adapter.send.call_count == 1
    e.response.close.assert_called_once()
    assert caught.value.__context__ is None


def test_partial_read_failure_keeps_attempt_unknown_and_does_not_retry(exchange):
    e = exchange
    e.response.raw.read1.side_effect = [b'PARTIAL', RuntimeError('PRIVATE-RAW-ERROR')]
    with pytest.raises(transport.NativeTransportError) as caught:
        transport.invoke_saved_request(e.invocation, runtime=e.runtime)
    assert caught.value.invoked and caught.value.__context__ is None
    assert 'PRIVATE' not in str(caught.value)
    assert e.adapter.send.call_count == 1


def test_bound_is_enforced_even_without_content_length(exchange, monkeypatch):
    e = exchange
    monkeypatch.setattr(transport, 'MAX_RESPONSE_BYTES', 3)
    e.response.raw.read1.side_effect = [b'FOUR']
    with pytest.raises(transport.NativeTransportError):
        transport.invoke_saved_request(e.invocation, runtime=e.runtime)
    e.response.raw.read1.assert_called_once_with(4, decode_content=False)


def test_cleanup_failure_does_not_erase_a_complete_response(exchange):
    e = exchange
    e.response.close.side_effect = RuntimeError('PRIVATE-CLEANUP')
    e.adapter.close.side_effect = RuntimeError('PRIVATE-CLEANUP')
    assert transport.invoke_saved_request(e.invocation, runtime=e.runtime).http_status == 200


def test_connection_failure_after_send_entry_is_unknown_even_without_a_response(exchange):
    e = exchange
    e.adapter.send.side_effect = RuntimeError('PRIVATE-CONNECTION')
    with pytest.raises(transport.NativeTransportError) as caught:
        transport.invoke_saved_request(e.invocation, runtime=e.runtime)
    assert caught.value.invoked and caught.value.__context__ is None
    e.adapter.close.assert_called_once()


def test_transient_secret_and_response_are_not_pickleable_or_rendered(exchange):
    e = exchange
    for value in (e.invocation, transport.NativeResponse(200, '', b'PRIVATE-RECEIPT')):
        with pytest.raises(TypeError):
            pickle.dumps(value)
        assert 'PRIVATE' not in repr(value) and 'Basic' not in repr(value)


@pytest.mark.parametrize('field', ['site', 'actor'])
def test_changed_site_or_actor_cannot_release_saved_credentials(exchange, field):
    e = exchange
    if field == 'site':
        e.runtime.local.site = 'other.invalid'
    else:
        e.runtime.session.user = 'other-user'
    with pytest.raises(transport.NativeTransportError) as caught:
        transport.invoke_saved_request(e.invocation, runtime=e.runtime)
    assert not caught.value.invoked
    e.factory.assert_not_called()
