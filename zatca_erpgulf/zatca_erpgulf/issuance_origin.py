"""Authenticated generation intent for automatic first-send recovery.

This optional side capsule never changes invoice request bytes or artifact AAD.
Missing origin grants no automatic delivery. Only the owned producer captures it
from server execution contexts; caller fields and mutable ERP owner labels are
not a substitute for the original actor and operation.
"""

import hashlib

from .dispatch_record_codec import _identifier,encode_record_header
from .saved_form_source import saved_form_name


PROFILE='native-issuance-origin/v1'
FIELDS={'profile','actor','intent','action','method','simplified','created_at_utc',
    'request_id','request_fence','request_sha256'}


class IssuanceOriginError(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def validate_origin(origin):
    from datetime import datetime
    from .dispatch_store import _fingerprint
    if type(origin) is not dict or set(origin)!=FIELDS or origin['profile']!=PROFILE:
        raise IssuanceOriginError('issuance_origin_profile')
    saved_form_name(origin['actor'])
    if (origin['actor']=='Guest' or origin['intent'] not in ('entry','submit','manual','scheduled')
            or origin['action'] not in ('PREPARE','DISPATCH') or type(origin['simplified']) is not bool
            or type(origin['method']) is not str or len(origin['method'])>140):
        raise IssuanceOriginError('issuance_origin_policy')
    if origin['simplified'] and origin['method'] not in ('','Live','Batches','Background'):
        raise IssuanceOriginError('issuance_origin_method')
    if origin['action']=='PREPARE' and not (origin['simplified'] and origin['method'] in ('Batches','Background')
            and origin['intent'] in ('entry','submit')):
        raise IssuanceOriginError('issuance_origin_prepare')
    if origin['request_id'] is None:
        if origin['request_fence'] is not None or origin['request_sha256'] is not None:
            raise IssuanceOriginError('issuance_origin_request')
    else:
        _identifier(origin['request_id']);_identifier(origin['request_fence']);_fingerprint(origin['request_sha256'])
    try:stamp=datetime.strptime(origin['created_at_utc'],'%Y-%m-%dT%H:%M:%S.%f')
    except (ValueError,TypeError):raise IssuanceOriginError('issuance_origin_clock') from None
    if stamp.strftime('%Y-%m-%dT%H:%M:%S.%f')!=origin['created_at_utc']:
        raise IssuanceOriginError('issuance_origin_clock')
    return encode_record_header(origin)


def capture_origin(runtime,source,*,chain_id,occurred_at):
    from .native_delivery import CURRENT as DELIVERY
    from .submission_intent import CURRENT as REQUEST,validate_header
    delivery=DELIVERY.get()
    if delivery is None:return None  # Trusted internal preparation need not authorize delivery.
    delivery.require(runtime,source)
    request=REQUEST.get()
    if request is not None and (request.closed or request.site!=runtime.local.site
            or request.actor!=runtime.session.user or request.header['chain']!=chain_id
            or request.header['intent']!=delivery.intent
            or (request.header['source_doctype'],request.header['source_name'])!=(source.doctype,source.name)):
        raise IssuanceOriginError('issuance_origin_request_binding')
    origin=dict(profile=PROFILE,actor=runtime.session.user,intent=delivery.intent,
        action=delivery.decision.action,method=delivery.decision.method,simplified=delivery.decision.simplified,
        created_at_utc=occurred_at.strftime('%Y-%m-%dT%H:%M:%S.%f'),
        request_id=request.header['record_id'] if request is not None else None,
        request_fence=request.fence if request is not None else None,
        request_sha256=hashlib.sha256(validate_header(request.header)).hexdigest() if request is not None else None)
    validate_origin(origin)
    return origin


def verify_origin_request(owner,origin,header):
    """Retained original commands cannot be replaced or rearmed behind origin."""
    if origin['request_id'] is None:return
    from .submission_intent import open_intent,validate_header
    row,request=open_intent(owner,origin['request_id'])
    if (hashlib.sha256(validate_header(request)).hexdigest()!=origin['request_sha256']
            or row['state'] not in ('RUNNING','REVIEW','COMPLETE') or row['fence_token']!=origin['request_fence']
            or request['actor']!=origin['actor'] or request['intent']!=origin['intent']
            or any(request[key]!=header[key] for key in ('chain','company','source_doctype','source_name'))):
        raise IssuanceOriginError('issuance_origin_request_changed')
