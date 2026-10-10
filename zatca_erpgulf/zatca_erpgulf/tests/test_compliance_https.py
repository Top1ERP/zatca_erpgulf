"""Real Requests preparation/adapter with synthetic urllib3 pools, NO sockets."""

import io
import json
import pickle
import socket
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from urllib3.response import HTTPResponse

from zatca_erpgulf.zatca_erpgulf import compliance_https as https
from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceTransportRequest
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import STEP_CLASSIFICATION
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_archive import observations, cipher
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_evidence import response
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import materials
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_snapshot import basic


def protected_request(material, cipher, *, environment="Production", step="SIMPLIFIED"):
    bundle, start, _ = observations(material, cipher, environment=environment, step=step)
    snapshot = cipher.open(bundle, observed_at=start.started_at)
    return ComplianceTransportRequest(start, snapshot)


@pytest.fixture
def network_guard(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real network and ambient Session access are forbidden")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "send", forbidden)
    monkeypatch.setattr(requests.sessions.Session, "prepare_request", forbidden)


def synthetic_pool(monkeypatch, *, body=b"", status=200, headers=None):
    context = SimpleNamespace(calls=[], raw=None, pool=None, response=None, close_calls=[])
    pool = SimpleNamespace()
    def urlopen(**kwargs):
        context.calls.append(kwargs)
        raw = HTTPResponse(body=io.BytesIO(body), status=status, reason="PRIVATE-REASON",
            headers=headers or {}, preload_content=False, decode_content=False, enforce_content_length=True)
        context.raw = raw
        return raw
    pool.urlopen = Mock(side_effect=urlopen)
    context.pool = pool
    def acquire(adapter, request, verify, *, proxies, cert):
        assert verify is True and proxies == {} and cert is None
        assert adapter.max_retries.total == 0 and adapter.max_retries.read is False
        return pool
    monkeypatch.setattr(https.HTTPAdapter, "get_connection_with_tls_context", acquire)
    original_build = https.HTTPAdapter.build_response
    def build(adapter, prepared, raw):
        result = original_build(adapter, prepared, raw)
        context.response = result
        original_close = result.close
        def close():
            context.close_calls.append("response")
            original_close()
        result.close = close
        return result
    monkeypatch.setattr(https.HTTPAdapter, "build_response", build)
    original_close = https.HTTPAdapter.close
    def close(adapter):
        context.close_calls.append("adapter")
        original_close(adapter)
    monkeypatch.setattr(https.HTTPAdapter, "close", close)
    return context


@pytest.mark.parametrize("environment", ["Sandbox", "Simulation", "Production"])
@pytest.mark.parametrize("step", list(STEP_CLASSIFICATION))
@pytest.mark.parametrize("status", [200, 202, 406, 401, 400, 302])
def test_one_verified_adapter_send_exact_body_no_redirect_or_ambient_auth(materials, cipher, monkeypatch, network_guard, environment, step, status):
    request = protected_request(materials[0], cipher, environment=environment, step=step)
    body = json.dumps(response(step=step, previous=status == 406)).encode()
    context = synthetic_pool(monkeypatch, body=body, status=status, headers={"Content-Length": str(len(body)), "Location": "https://private.invalid/redirect"})
    monkeypatch.setenv("HTTPS_PROXY", "https://PRIVATE-PROXY.invalid")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/PRIVATE-CA-FROM-ENV")
    monkeypatch.setenv("NETRC", "/PRIVATE-NETRC")
    policy = https.ComplianceHttpsPolicy((request.start.route,))
    transport = https.ComplianceHttpsTransport(policy, timer=lambda: 100.0)
    result = transport(request)
    assert result.http_status == status and result.body == body
    assert len(context.calls) == 1 and context.close_calls == ["response", "adapter"]
    sent = context.calls[0]
    assert sent["method"] == "POST" and sent["body"] == request.body
    assert sent["redirect"] is False and sent["preload_content"] is False and sent["decode_content"] is False
    assert sent["retries"].total == 0 and sent["chunked"] is False
    assert sent["headers"]["Authorization"] == "Basic " + basic(materials[0])
    assert sent["headers"]["Accept-Encoding"] == "identity"
    assert sent["timeout"].connect_timeout == 5.0 and sent["timeout"].read_timeout == 15.0
    assert context.pool.cert_reqs == "CERT_REQUIRED" and context.pool.ca_certs
    assert context.response.history == [] and context.response._content is False
    assert context.raw.closed
    public = repr(policy) + repr(transport) + repr(result)
    for private in (request.url, materials[0].pem, basic(materials[0]), body.decode()):
        assert private not in public


@pytest.mark.parametrize("headers,code", [
    ({"Content-Encoding": "gzip"}, "https_response_encoding"),
    ({"Content-Encoding": "br"}, "https_response_encoding"),
    ({"Transfer-Encoding": "gzip, chunked"}, "https_response_encoding"),
    ({"Content-Length": "1", "Transfer-Encoding": "chunked"}, "https_response_framing"),
    ({"Content-Length": "-1"}, "https_response_framing"),
    ({"Content-Length": "0001"}, "https_response_framing"),
    ({"Content-Length": "1, 1"}, "https_response_framing"),
    ({"Content-Length": str(https.MAX_RESPONSE_BYTES + 1)}, "https_response_size"),
    ({"X-Test": "x" * (https.MAX_RESPONSE_HEADER_BYTES + 1)}, "https_response_headers"),
])
def test_invalid_response_framing_encoding_and_size_are_closed_without_retry(materials, cipher, monkeypatch, network_guard, headers, code):
    request = protected_request(materials[0], cipher)
    context = synthetic_pool(monkeypatch, body=b"PRIVATE-BODY", headers=headers)
    transport = https.ComplianceHttpsTransport(https.ComplianceHttpsPolicy((request.start.route,)), timer=lambda: 0)
    with pytest.raises(https.ComplianceHttpsError, match=code) as error:
        transport(request)
    assert error.value.__context__ is None and len(context.calls) == 1
    assert context.close_calls[-1] == "adapter"
    if context.response is not None:
        assert context.close_calls[0] == "response"


@pytest.mark.parametrize("known_length", [False, True])
@pytest.mark.parametrize("size", [0, https.READ_CHUNK_BYTES + 7, https.MAX_RESPONSE_BYTES])
def test_exact_body_bounds_and_empty_responses_are_preserved(materials, cipher, monkeypatch, network_guard, known_length, size):
    request = protected_request(materials[0], cipher)
    body = b"x" * size
    context = synthetic_pool(monkeypatch, body=body, headers={"Content-Length": str(size)} if known_length else {})
    result = https.ComplianceHttpsTransport(https.ComplianceHttpsPolicy((request.start.route,)), timer=lambda: 0)(request)
    assert result.body == body and len(context.calls) == 1


@pytest.mark.parametrize("status", [200, 302, 401])
def test_unadvertised_oversize_is_detected_while_streaming_including_redirects(materials, cipher, monkeypatch, network_guard, status):
    request = protected_request(materials[0], cipher)
    context = synthetic_pool(monkeypatch, body=b"x" * (https.MAX_RESPONSE_BYTES + 1), status=status)
    with pytest.raises(https.ComplianceHttpsError, match="https_response_size"):
        https.ComplianceHttpsTransport(https.ComplianceHttpsPolicy((request.start.route,)), timer=lambda: 0)(request)
    assert len(context.calls) == 1 and context.close_calls == ["response", "adapter"]


@pytest.mark.parametrize("fault", ["route", "scheme", "hostname", "port", "credentials", "query", "path", "purpose", "base_field", "duplicate", "empty", "type", "env_type"])
def test_policy_is_explicit_standard_compliance_only(materials, cipher, fault):
    route = protected_request(materials[0], cipher).start.route
    routes = (route,)
    if fault in ("route", "scheme", "hostname", "port", "credentials", "query", "path"):
        url = {"route": route.url.replace("core", "simulation"), "scheme": route.url.replace("https", "http"),
               "hostname": route.url.replace("gw-fatoora.zatca.gov.sa", "127.0.0.1"),
               "port": route.url.replace(".sa/", ".sa:444/"),
               "credentials": route.url.replace("://", "://PRIVATE-SECRET@"),
               "query": route.url + "?query", "path": route.url.replace("compliance/invoices", "invoices/reporting/single")}[fault]
        routes = (replace(route, url=url),)
    elif fault == "purpose":
        routes = (replace(route, required_credential="production"),)
    elif fault == "base_field":
        routes = (replace(route, base_url_field="custom_simulation_url"),)
    elif fault == "duplicate":
        routes = (route, route)
    elif fault == "empty":
        routes = ()
    elif fault == "env_type":
        routes = (replace(route, environment=[]),)
    else:
        routes = [route]
    with pytest.raises(https.ComplianceHttpsError, match="https_route_policy"):
        https.ComplianceHttpsPolicy(routes)


@pytest.mark.parametrize("field", ["connect_timeout", "read_timeout", "elapsed_budget"])
@pytest.mark.parametrize("value", [None, True, 0, -1, float("nan"), float("inf"), 10**1000])
def test_timeout_policy_has_finite_bounded_values(materials, cipher, field, value):
    route = protected_request(materials[0], cipher).start.route
    with pytest.raises(https.ComplianceHttpsError, match="https_timeout_policy"):
        https.ComplianceHttpsPolicy((route,), **{field: value})


@pytest.mark.parametrize("times,code", [([0, 31], "https_elapsed_budget"), ([10, 9], "https_monotonic_time"),
    ([True], "https_monotonic_time"), ([float("nan")], "https_monotonic_time"),
    ([0, 0, 0, 31], "https_elapsed_budget")])
def test_time_budget_and_bad_monotonic_clock_stop_without_retry(materials, cipher, monkeypatch, network_guard, times, code):
    request = protected_request(materials[0], cipher)
    context = synthetic_pool(monkeypatch, body=b"PRIVATE-BODY")
    transport = https.ComplianceHttpsTransport(https.ComplianceHttpsPolicy((request.start.route,)), timer=Mock(side_effect=times))
    with pytest.raises(https.ComplianceHttpsError, match=code) as error:
        transport(request)
    assert error.value.__context__ is None
    assert len(context.calls) <= 1


@pytest.mark.parametrize("fault", ["tls", "timeout", "truncated", "reader", "chunk", "body_drift", "url_drift", "auth_drift", "history", "close"])
def test_protocol_and_binding_errors_are_static_and_resources_close(materials, cipher, monkeypatch, network_guard, fault):
    request = protected_request(materials[0], cipher)
    context = synthetic_pool(monkeypatch, body=b"PRIVATE-BODY", headers={"Content-Length": "50"} if fault == "truncated" else {})
    if fault in ("tls", "timeout"):
        context.pool.urlopen.side_effect = requests.exceptions.SSLError("PRIVATE-SECRET") if fault == "tls" else OSError("PRIVATE-SECRET timeout")
    else:
        original = https.HTTPAdapter.build_response
        def build(adapter, prepared, raw):
            result = original(adapter, prepared, raw)
            if fault == "reader":
                result.raw.read1 = None
            elif fault == "chunk":
                result.raw.read1 = lambda *args, **kwargs: "PRIVATE-SECRET"
            elif fault == "body_drift":
                prepared.body = b"PRIVATE-SECRET"
            elif fault == "url_drift":
                result.url = "https://PRIVATE-SECRET.invalid"
            elif fault == "auth_drift":
                prepared.headers["Authorization"] = "PRIVATE-SECRET"
            elif fault == "history":
                result.history = [requests.Response()]
            elif fault == "close":
                original_close = result.close
                def close():
                    original_close()
                    raise RuntimeError("PRIVATE-SECRET close")
                result.close = close
            return result
        monkeypatch.setattr(https.HTTPAdapter, "build_response", build)
    with pytest.raises(https.ComplianceHttpsError) as error:
        https.ComplianceHttpsTransport(https.ComplianceHttpsPolicy((request.start.route,)), timer=lambda: 0)(request)
    assert "PRIVATE-SECRET" not in str(error.value) and error.value.__context__ is None
    assert len(context.calls) <= 1 and context.close_calls[-1] == "adapter"


def test_no_environment_fallback_or_pickle_and_approval_before_pool_acquisition(materials, cipher, monkeypatch, network_guard):
    request = protected_request(materials[0], cipher)
    policy = https.ComplianceHttpsPolicy((request.start.route,))
    transport = https.ComplianceHttpsTransport(policy, timer=lambda: 0)
    forbidden = Mock(side_effect=AssertionError("Unapproved route must not acquire a pool"))
    monkeypatch.setattr(https, "HTTPAdapter", forbidden)
    other = protected_request(materials[0], cipher, environment="Sandbox")
    with pytest.raises(https.ComplianceHttpsError, match="https_request_policy"):
        transport(other)
    forbidden.assert_not_called()
    for protected in (policy, transport):
        with pytest.raises(https.ComplianceHttpsError, match="https_not_pickleable"):
            pickle.dumps(protected)


@pytest.mark.parametrize("fault", ["body", "auth", "url", "method", "hook", "extra_header"])
def test_prepared_mutation_is_rejected_before_any_adapter_acquisition(materials, cipher, monkeypatch, network_guard, fault):
    request = protected_request(materials[0], cipher)
    original = https.Request.prepare
    def prepare(value):
        result = original(value)
        if fault == "body":
            result.body += b"PRIVATE-SECRET"
        elif fault == "auth":
            result.headers["Authorization"] = "PRIVATE-SECRET"
        elif fault == "url":
            result.url = "https://PRIVATE-SECRET.invalid"
        elif fault == "method":
            result.method = "GET"
        elif fault == "hook":
            result.hooks["response"] = [lambda value: value]
        else:
            result.headers["Cookie"] = "PRIVATE-SECRET"
        return result
    monkeypatch.setattr(https.Request, "prepare", prepare)
    acquired = Mock(side_effect=AssertionError("Must reject before acquiring resources"))
    monkeypatch.setattr(https, "HTTPAdapter", acquired)
    with pytest.raises(https.ComplianceHttpsError, match="https_prepared_binding") as error:
        https.ComplianceHttpsTransport(https.ComplianceHttpsPolicy((request.start.route,)), timer=lambda: 0)(request)
    assert error.value.__context__ is None
    acquired.assert_not_called()


@pytest.mark.parametrize("fault", ["request_type", "policy_type", "timer_type", "header_count", "chunk_size", "status", "timer_exception"])
def test_dependency_and_response_boundaries(materials, cipher, monkeypatch, network_guard, fault):
    request = protected_request(materials[0], cipher)
    policy = https.ComplianceHttpsPolicy((request.start.route,))
    if fault in ("policy_type", "timer_type"):
        with pytest.raises(https.ComplianceHttpsError, match="https_dependencies"):
            https.ComplianceHttpsTransport(None if fault == "policy_type" else policy, timer=None if fault == "timer_type" else lambda: 0)
        return
    context = synthetic_pool(monkeypatch, headers={"X-Test-" + str(index): "x" for index in range(101)} if fault == "header_count" else {})
    timer = Mock(side_effect=RuntimeError("PRIVATE-SECRET")) if fault == "timer_exception" else lambda: 0
    if fault in ("chunk_size", "status"):
        original = https.HTTPAdapter.build_response
        def build(adapter, prepared, raw):
            result = original(adapter, prepared, raw)
            if fault == "chunk_size":
                result.raw.read1 = lambda amount, **kwargs: b"x" * (amount + 1)
            else:
                result.status_code = True
            return result
        monkeypatch.setattr(https.HTTPAdapter, "build_response", build)
    with pytest.raises(https.ComplianceHttpsError) as error:
        https.ComplianceHttpsTransport(policy, timer=timer)(object() if fault == "request_type" else request)
    assert error.value.__context__ is None and "PRIVATE-SECRET" not in str(error.value)
    assert len(context.calls) <= 1


def test_approved_three_environment_policy_is_explicit_not_sandbox_fallback(materials, cipher):
    routes = tuple(protected_request(materials[0], cipher, environment=environment).start.route
                   for environment in ("Sandbox", "Simulation", "Production"))
    assert https.ComplianceHttpsPolicy(routes).routes == routes


def test_unsupported_reader_dependency_is_rejected_before_releasing_credentials(materials, cipher, monkeypatch, network_guard):
    request = protected_request(materials[0], cipher)
    acquired = Mock(side_effect=AssertionError("Old dependency must not send first"))
    monkeypatch.setattr(https, "HTTPAdapter", acquired)
    monkeypatch.setattr(https.HTTPResponse, "read1", None)
    with pytest.raises(https.ComplianceHttpsError, match="https_reader_dependency"):
        https.ComplianceHttpsTransport(https.ComplianceHttpsPolicy((request.start.route,)), timer=lambda: 0)(request)
    acquired.assert_not_called()
