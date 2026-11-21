"""Generation-origin shape and immutable server context; no site/SQL/transport."""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import issuance_origin as origin
from zatca_erpgulf.zatca_erpgulf import native_delivery as delivery
from zatca_erpgulf.zatca_erpgulf.submission_intent import execution_context,validate_header
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent import Source,header
from zatca_erpgulf.zatca_erpgulf.tests.test_publication_source import invoice


def example():
    return dict(profile=origin.PROFILE,actor='operator@example.invalid',intent='entry',action='DISPATCH',
        method='Live',simplified=True,created_at_utc='2026-11-21T10:00:00.000000',
        request_id=None,request_fence=None,request_sha256=None)


@pytest.mark.parametrize('field,value',[('profile','UNKNOWN'),('actor','Guest'),('intent','recovery'),
    ('action','SKIP'),('simplified',1),('method',None),('request_fence',str(uuid4())),
    ('created_at_utc','2026-11-21T9:00:00'),('created_at_utc','2026-02-30T10:00:00.000000')])
def test_origin_rejects_incomplete_or_ambiguous_authority(field,value):
    payload=example();payload[field]=value
    with pytest.raises(Exception):origin.validate_origin(payload)


@pytest.mark.parametrize('method',['Batches','Background'])
def test_prepared_origin_never_means_authority_to_send(method):
    payload=example();payload.update(method=method,action='PREPARE')
    origin.validate_origin(payload)
    payload['intent']='manual'
    with pytest.raises(origin.IssuanceOriginError):origin.validate_origin(payload)


def test_no_delivery_context_does_not_invent_automatic_authorization():
    doc=Source(**invoice())
    assert origin.capture_origin(object(),doc,chain_id=str(uuid4()),occurred_at=datetime(2026,11,21)) is None


def test_producer_captures_request_fence_actor_and_operation_without_mutating_header():
    import hashlib
    doc=Source(**invoice());h=header(doc);fence=str(uuid4());raw=validate_header(h)
    runtime=SimpleNamespace(local=SimpleNamespace(site='fictional.invalid'),session=SimpleNamespace(user=h['actor']))
    with execution_context(runtime,h,fence):
        with delivery.native_delivery(runtime,doc,'submit',delivery.DeliveryDecision('DISPATCH',True,'Live')):
            payload=origin.capture_origin(runtime,doc,chain_id=h['chain'],occurred_at=datetime(2026,11,21))
    assert payload['actor']==h['actor'] and payload['intent']=='submit' and payload['request_fence']==fence
    assert payload['request_id']==h['record_id'] and payload['request_sha256']==hashlib.sha256(raw).hexdigest()
    assert validate_header(h)==raw


@pytest.mark.parametrize('kind',['artifact','publication-source','submission-intent','issuance-origin'])
def test_origin_has_a_separate_cipher_domain(kind):
    from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    identifier=str(uuid4());raw=origin.validate_origin(example())
    encoded=validate_header(header())
    encrypted=cipher.seal(identifier,kind,encoded,raw)
    if kind=='issuance-origin':assert cipher.open(identifier,'issuance-origin',encoded,encrypted)==raw
    else:
        with pytest.raises(Exception):cipher.open(identifier,'issuance-origin',encoded,encrypted)
