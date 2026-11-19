"""One fenced initial CSID call, distinct from invoice reporting/clearance.

OTP/auth remain transient. The owned service must commit its reservation first;
this adapter cannot persist, retry, repair, activate or infer issuance success.
"""

from dataclasses import dataclass, field
import hashlib
import re

from .api_routing import ApiRoute, ENVIRONMENT_FIELDS, resolve_api_route
from .dispatch_record_codec import _identifier
from .native_transport import NativeTransportError, _exchange
from .onboarding_response import MAX_RESPONSE_BYTES


@dataclass(frozen=True, repr=False)
class OnboardingInvocation:
    record_id: str
    chain_id: str
    fence_token: str
    owner_key: str
    site: str
    actor: str
    route: ApiRoute = field(repr=False)
    request_sha256: str
    request_bytes: bytes = field(repr=False)
    otp: str = field(default='', repr=False)
    authorization: str = field(default='', repr=False)

    def __reduce_ex__(self, protocol):
        raise TypeError('onboarding_invocation_not_serializable')


def invoke_onboarding_request(invocation, *, runtime):
    failed = False
    try:
        value = invocation
        if type(value) is not OnboardingInvocation or type(value.route) is not ApiRoute:
            raise ValueError
        for identifier in (value.record_id, value.chain_id, value.fence_token):
            _identifier(identifier)
        if type(value.owner_key) is not str or not re.fullmatch(r'[0-9a-f]{64}', value.owner_key):
            raise ValueError
        route = value.route
        if (route.endpoint not in ('compliance', 'production/csids') or type(route.url) is not str
                or len(route.url) > 4096 or not route.url.endswith('/'+route.endpoint)):
            raise ValueError
        resolved = resolve_api_route({'custom_select': route.environment,
            ENVIRONMENT_FIELDS[route.environment]: route.url[:-len('/'+route.endpoint)]}, route.endpoint,
            onboarding_only=True)
        if (route != resolved or type(value.request_bytes) is not bytes
                or not 0 < len(value.request_bytes) <= 256 * 1024
                or hashlib.sha256(value.request_bytes).hexdigest() != value.request_sha256
                or runtime.local.site != value.site or runtime.session.user != value.actor):
            raise ValueError
        headers = {'accept': 'application/json', 'accept-language': 'en', 'Accept-Version': 'V2',
                   'Content-Type': 'application/json', 'Accept-Encoding': 'identity'}
        if route.endpoint == 'compliance':
            if type(value.otp) is not str or not re.fullmatch(r'[0-9]{6}', value.otp) or value.authorization != '':
                raise ValueError
            headers['OTP'] = value.otp
        else:
            if (value.otp != '' or type(value.authorization) is not str
                    or not value.authorization.startswith('Basic ') or not 6 < len(value.authorization) <= 512 * 1024 + 6
                    or any(ord(c) < 33 or ord(c) > 126 for c in value.authorization.removeprefix('Basic '))):
                raise ValueError
            headers['Authorization'] = value.authorization
    except Exception:
        failed = True
    if failed:
        raise NativeTransportError('onboarding_transport_binding')
    return _exchange(route.url, value.request_bytes, headers, max_response_bytes=MAX_RESPONSE_BYTES)
