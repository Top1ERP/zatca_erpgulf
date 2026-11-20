"""One HTTP invocation of an already committed native request.

The owned coordinator supplies the saved bytes and current bound credentials.
This module owns no DB, regeneration, retry loop, status writer or enrollment.
No caller may use a returned HTTP status as acceptance without receipt custody
and the operation-specific response assessment.
"""

from dataclasses import dataclass, field
import hashlib
import time

from requests import Request
from requests.adapters import HTTPAdapter

from .api_routing import ApiRoute
from .credential_snapshot import _route, CredentialSnapshotError


MAX_RESPONSE_BYTES = 16 * 1024 * 1024 - 1
ENDPOINTS = ('invoices/reporting/single', 'invoices/clearance/single')


class NativeTransportError(RuntimeError):
    def __init__(self, code, *, invoked=False):
        self.code = code
        self.invoked = invoked
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class NativeInvocation:
    """Transient secret-bearing worker value; never persist, queue or print it."""
    issuance_id: str
    attempt_id: str
    fence_token: str
    owner_key: str
    chain_id: str
    site: str
    actor: str
    route: ApiRoute = field(repr=False)
    authorization: str = field(repr=False)
    request_sha256: str
    request_bytes: bytes = field(repr=False)

    def __reduce_ex__(self, protocol):
        raise TypeError('native_invocation_not_serializable')


@dataclass(frozen=True, repr=False)
class NativeResponse:
    http_status: int
    request_id: str
    body: bytes = field(repr=False)

    def __reduce_ex__(self, protocol):
        raise TypeError('native_response_not_serializable')


def _validate(invocation):
    if (type(invocation) is not NativeInvocation or type(invocation.route) is not ApiRoute
            or invocation.route.endpoint not in ENDPOINTS
            or invocation.route.required_credential != 'production'
            or type(invocation.authorization) is not str
            or not invocation.authorization.startswith('Basic ')
            or any(ord(c) < 32 or ord(c) > 126 for c in invocation.authorization)
            or type(invocation.request_bytes) is not bytes or not invocation.request_bytes
            or len(invocation.request_bytes) > 16 * 1024 * 1024
            or hashlib.sha256(invocation.request_bytes).hexdigest() != invocation.request_sha256):
        raise NativeTransportError('native_transport_binding')
    invalid = False
    try:
        _route(invocation.route)
    except CredentialSnapshotError:
        invalid = True
    if invalid:
        raise NativeTransportError('native_transport_binding')


def _close_quietly(resource):
    if resource is not None:
        try:
            resource.close()
        except Exception:
            # A cleanup failure must not erase a complete received response.
            pass


def invoke_saved_request(invocation, *, runtime):
    """Exact body once; TLS on, no env/netrc, redirects or implicit HTTP retry.

    A transport exception after entering send() is uncertain, even when the
    exception looks like a connection failure. Only the durable caller can mark
    that attempt unknown. Response bytes are application-body bytes from Requests;
    transfer framing and TLS records are not an authority receipt archive.
    Budget checks cannot interrupt DNS/native reads or enforce a hard wall limit.
    """
    from .deferred_submission import reject_submit_hook_transport
    reject_submit_hook_transport(runtime,lambda message:message)
    _validate(invocation)
    if (runtime.local.site != invocation.site or runtime.session.user != invocation.actor):
        raise NativeTransportError('native_transport_owner_changed')
    headers = {
        'accept': 'application/json', 'accept-language': 'en',
        'Accept-Version': 'V2', 'Content-Type': 'application/json',
        'Accept-Encoding': 'identity', 'Authorization': invocation.authorization,
        'Clearance-Status': '1' if invocation.route.endpoint == ENDPOINTS[1] else '0',
    }
    return _exchange(invocation.route.url, invocation.request_bytes, headers)


def _exchange(url, body, headers, *, max_response_bytes=None):
    """Internal bounded entity exchange; public callers validate their own type.

    Invoice and onboarding coordinators have distinct capabilities/routes. This
    helper shares only mechanical TLS/body handling and grants no dispatch right.
    """
    limit = MAX_RESPONSE_BYTES if max_response_bytes is None else max_response_bytes
    adapter = response = None
    failed = None
    invoked = False
    result = None
    try:
        prepared = Request('POST', url, data=body, headers=headers).prepare()
        if (type(limit) is not int or not 0 < limit <= MAX_RESPONSE_BYTES
                or prepared.url != url or prepared.body != body
                or set(prepared.headers) != set(headers) | {'Content-Length'}
                or any(prepared.headers.get(name) != value for name, value in headers.items())
                or prepared.headers.get('Content-Length') != str(len(body))
                or any(prepared.hooks.values())):
            raise ValueError
        # Direct adapter avoids Session's redirect-next construction, which may
        # consume a redirect body even with allow_redirects=False. There is no
        # ambient cookie/netrc/proxy/environment or automatic redirect handling.
        adapter = HTTPAdapter(max_retries=0)
        deadline = time.monotonic() + 90
        invoked = True
        response = adapter.send(prepared, stream=True, verify=True, cert=None, proxies={}, timeout=(10, 60))
        if response.request is not prepared or response.url != prepared.url or response.history:
            raise ValueError
        if type(response.status_code) is not int or not 100 <= response.status_code <= 599:
            raise ValueError
        if len(response.headers) > 100 or sum(len(k) + len(v) for k, v in response.headers.items()) > 32768:
            raise ValueError
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isascii() or not length.isdecimal()
                or len(length) > 10 or int(length) > limit):
            raise ValueError
        transfer = response.headers.get('Transfer-Encoding', '').strip().lower()
        if (response.headers.get('Content-Encoding', 'identity').strip().lower() not in ('', 'identity')
                or transfer not in ('', 'chunked') or (transfer and length is not None)):
            raise ValueError
        request_id = response.headers.get('x-request-id', '')
        if (type(request_id) is not str or len(request_id) > 120
                or any(ord(c) < 32 or ord(c) > 126 for c in request_id)):
            raise ValueError
        content = bytearray()
        if not callable(getattr(response.raw, 'read1', None)):
            raise ValueError
        while True:
            if time.monotonic() > deadline:
                raise ValueError
            amount = min(64 * 1024, limit - len(content) + 1)
            chunk = response.raw.read1(amount, decode_content=False)
            if type(chunk) is not bytes or len(chunk) > amount or time.monotonic() > deadline:
                raise ValueError
            if not chunk:
                break
            if len(content) + len(chunk) > limit:
                raise ValueError
            content.extend(chunk)
        if time.monotonic() > deadline or (length is not None and len(content) != int(length)):
            raise ValueError
        result = NativeResponse(response.status_code, request_id, bytes(content))
    except Exception:
        failed = 'native_transport_outcome_unknown' if invoked else 'native_transport_not_invoked'
    finally:
        _close_quietly(response)
        _close_quietly(adapter)
    if failed is not None:
        raise NativeTransportError(failed, invoked=invoked)
    return result
