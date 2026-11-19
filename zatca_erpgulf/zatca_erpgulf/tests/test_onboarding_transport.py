"""Mocked onboarding TLS adapter shares mechanical bounds, never invoice routes."""

from dataclasses import replace
import hashlib
import pickle

import pytest

from zatca_erpgulf.zatca_erpgulf import onboarding_transport as transport
from zatca_erpgulf.zatca_erpgulf.api_routing import resolve_api_route
from zatca_erpgulf.zatca_erpgulf.native_transport import NativeTransportError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_transport import exchange


def invocation(exchange, endpoint='compliance'):
    route = resolve_api_route({'custom_select': 'Production', 'custom_production_url': 'https://example.invalid/core'}, endpoint)
    body = b'{"csr":"SYNTHETIC"}'
    return transport.OnboardingInvocation('30000000-0000-4000-8000-000000000001',
        '30000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000003',
        'a'*64, 'fictional.invalid', 'operator', route, hashlib.sha256(body).hexdigest(), body,
        '123456' if endpoint == 'compliance' else '', '' if endpoint == 'compliance' else 'Basic PRIVATE')


@pytest.mark.parametrize('endpoint',['compliance','production/csids'])
def test_only_the_operation_specific_transient_header_is_sent_once(exchange, endpoint):
    value = invocation(exchange, endpoint)
    result = transport.invoke_onboarding_request(value, runtime=exchange.runtime)
    assert result.http_status == 200
    prepared = exchange.adapter.send.call_args.args[0]
    assert 'Clearance-Status' not in prepared.headers and prepared.body == value.request_bytes
    assert prepared.headers.get('OTP') == ('123456' if endpoint == 'compliance' else None)
    assert prepared.headers.get('Authorization') == (None if endpoint == 'compliance' else 'Basic PRIVATE')
    exchange.adapter.send.assert_called_once()
    with pytest.raises(TypeError):pickle.dumps(value)


@pytest.mark.parametrize('fault',['otp','auth','both','digest','site','actor','route','fence'])
def test_no_adapter_exists_until_the_transient_binding_is_valid(exchange, fault):
    value = invocation(exchange)
    changes = {'otp': {'otp': '12345\n'}, 'auth': {'authorization': 'Basic PRIVATE'},
        'both': {'otp': '', 'authorization': 'Basic PRIVATE'}, 'digest': {'request_sha256': 'WRONG'},
        'site': {'site': 'OTHER'}, 'actor': {'actor': 'OTHER'},
        'route': {'route': replace(value.route, endpoint='invoices/reporting/single')},
        'fence': {'fence_token': 'NOT-AN-ID'}}[fault]
    with pytest.raises(NativeTransportError) as failed:
        transport.invoke_onboarding_request(replace(value, **changes), runtime=exchange.runtime)
    assert not failed.value.invoked and failed.value.__context__ is None
    exchange.factory.assert_not_called()
