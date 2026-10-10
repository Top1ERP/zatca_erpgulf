"""Explicit, standard-gateway-only Compliance HTTPS adapter; not auto-installed.

Use only behind authorized source/tenant acquisition and the durable coordinator.
No Session/netrc/proxy/site-key/URL discovery, redirects, retries or JSON rewrite.
TLS uses Requests' verified public CA roots. Read bounds concern HTTP entity bytes,
not encrypted TLS packets or chunk framing. Timeouts are NOT a hard wall deadline.
No remote/source/CSR provenance or activation flag is asserted by this adapter.
"""

import math
import re
from contextlib import closing
from dataclasses import dataclass, field

from requests import Request
from requests.adapters import HTTPAdapter
from urllib3.response import HTTPResponse

from zatca_erpgulf.zatca_erpgulf.api_routing import ApiRoute, GATEWAY_PATHS
from zatca_erpgulf.zatca_erpgulf.compliance_capture import ComplianceTransportRequest, ComplianceTransportResponse
from zatca_erpgulf.zatca_erpgulf.compliance_evidence import _route
from zatca_erpgulf.zatca_erpgulf.response_json import MAX_RESPONSE_BYTES


READ_CHUNK_BYTES = 16 * 1024
MAX_RESPONSE_HEADER_BYTES = 32 * 1024


class ComplianceHttpsError(ValueError):
    """Static internal codes; never expose Requests errors/prepared headers."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _seconds(value, maximum):
    if type(value) not in (int, float) or not 0 < value <= maximum or not math.isfinite(value):
        raise ComplianceHttpsError("https_timeout_policy")


@dataclass(frozen=True)
class ComplianceHttpsPolicy:
    """Server-approved exact routes; constructing this is not tenant permission.

    Custom gateways are deliberately NOT supported by this new adapter until a
    reviewed destination/egress policy exists. Existing legacy routes are unchanged.
    Standard Production onboarding is permitted only when explicitly in routes.
    """

    routes: tuple = field(repr=False)
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    elapsed_budget: float = 30.0

    def __post_init__(self):
        if type(self.routes) is not tuple or not 1 <= len(self.routes) <= 3:
            raise ComplianceHttpsError("https_route_policy")
        environments = set()
        for route in self.routes:
            if (type(route) is not ApiRoute or type(route.environment) is not str or route.environment not in GATEWAY_PATHS
                    or route.environment in environments or route.endpoint != "compliance/invoices"
                    or route.required_credential != "compliance"
                    or route.base_url_field != "custom_" + route.environment.lower() + "_url"
                    or route.url != "https://gw-fatoora.zatca.gov.sa" + GATEWAY_PATHS[route.environment] + "/compliance/invoices"):
                raise ComplianceHttpsError("https_route_policy")
            environments.add(route.environment)
        _seconds(self.connect_timeout, 10)
        _seconds(self.read_timeout, 30)
        _seconds(self.elapsed_budget, 60)

    def __reduce_ex__(self, protocol):
        raise ComplianceHttpsError("https_not_pickleable")


class ComplianceHttpsTransport:
    """One owned HTTPAdapter per call, no default policy or ambient session.

    timer is an explicit trusted monotonic dependency. Budget checks surround I/O
    but cannot interrupt DNS, a stalled native call or trickled protocol framing.
    A separate reviewed process deadline would be needed for a hard wall bound.
    """

    def __init__(self, policy, *, timer):
        if type(policy) is not ComplianceHttpsPolicy or not callable(timer):
            raise ComplianceHttpsError("https_dependencies")
        self._policy, self._timer = policy, timer

    def __repr__(self):
        return "ComplianceHttpsTransport(<explicit approved HTTPS policy>)"

    def __reduce_ex__(self, protocol):
        raise ComplianceHttpsError("https_not_pickleable")

    def __call__(self, request):
        # Raise outside the exception handler so an error holding Authorization,
        # prepared request, configured URLs or body is not publicly chained.
        try:
            result = self._send(request)
        except ComplianceHttpsError as error:
            code = error.code
        except Exception:
            code = "https_exchange_unconfirmed"
        else:
            return result
        raise ComplianceHttpsError(code)

    def _send(self, request):
        if type(request) is not ComplianceTransportRequest or request.start.route not in self._policy.routes:
            raise ComplianceHttpsError("https_request_policy")
        if not callable(getattr(HTTPResponse, "read1", None)):
            raise ComplianceHttpsError("https_reader_dependency")
        # Revalidate the immutable locally bound request before releasing secrets.
        ComplianceTransportRequest(request.start, request.snapshot)
        _route(request.start.route, request.start.requirements.manifest)
        expected = request.headers()
        prepared = Request("POST", request.url, data=request.body, headers=expected).prepare()

        def check_prepared():
            if (prepared.method != "POST" or prepared.url != request.url or prepared.body != request.body
                    or set(prepared.headers) != set(expected) | {"Content-Length"}
                    or any(prepared.headers.get(name) != value for name, value in expected.items())
                    or prepared.headers["Content-Length"] != str(len(request.body))
                    or any(prepared.hooks.values())):
                raise ComplianceHttpsError("https_prepared_binding")

        check_prepared()
        first, previous = None, None

        def remaining():
            nonlocal first, previous
            now = self._timer()
            if type(now) not in (int, float) or not math.isfinite(now) or now < 0 or (previous is not None and now < previous):
                raise ComplianceHttpsError("https_monotonic_time")
            if first is None:
                first = now
            previous = now
            left = self._policy.elapsed_budget - (now - first)
            if left <= 0:
                raise ComplianceHttpsError("https_elapsed_budget")
            return left

        left = remaining()
        # Do NOT use Session.send: its allow_redirects=False path can consume a
        # redirect body while constructing Response.next, before our size bound.
        # HTTPAdapter.send uses urllib3 redirect=False and decode_content=False.
        with closing(HTTPAdapter(max_retries=0)) as adapter:
            with closing(adapter.send(prepared, stream=True, verify=True, cert=None, proxies={},
                                      timeout=(min(self._policy.connect_timeout, left), min(self._policy.read_timeout, left)))) as response:
                remaining()
                check_prepared()
                if response.request is not prepared or response.url != prepared.url or response.history:
                    raise ComplianceHttpsError("https_response_binding")
                if type(response.status_code) is not int or not 100 <= response.status_code <= 599:
                    raise ComplianceHttpsError("https_response_status")
                if len(response.headers) > 100 or sum(len(name) + len(value) for name, value in response.headers.items()) > MAX_RESPONSE_HEADER_BYTES:
                    raise ComplianceHttpsError("https_response_headers")
                encoding = response.headers.get("Content-Encoding", "").strip().lower()
                transfer = response.headers.get("Transfer-Encoding", "").strip().lower()
                if encoding not in ("", "identity") or transfer not in ("", "chunked"):
                    raise ComplianceHttpsError("https_response_encoding")
                length = response.headers.get("Content-Length")
                if length is not None:
                    if transfer or re.fullmatch(r"0|[1-9][0-9]{0,9}", length) is None:
                        raise ComplianceHttpsError("https_response_framing")
                    length = int(length)
                    if length > MAX_RESPONSE_BYTES:
                        raise ComplianceHttpsError("https_response_size")
                if not callable(getattr(response.raw, "read1", None)):
                    # No unbounded .content/.text/read-all or legacy reader
                    # fallback. Rehearse the actual dependency matrix first.
                    raise ComplianceHttpsError("https_raw_reader")
                body = bytearray()
                while True:
                    remaining()
                    amount = min(READ_CHUNK_BYTES, MAX_RESPONSE_BYTES - len(body) + 1)
                    chunk = response.raw.read1(amount, decode_content=False)
                    remaining()
                    if type(chunk) is not bytes or len(chunk) > amount:
                        raise ComplianceHttpsError("https_response_chunk")
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ComplianceHttpsError("https_response_size")
                if length is not None and len(body) != length:
                    raise ComplianceHttpsError("https_response_framing")
                remaining()
                check_prepared()
                result = ComplianceTransportResponse(response.status_code, bytes(body))
            # Cleanup exceptions leave the outcome unconfirmed; never retry.
        remaining()
        return result
