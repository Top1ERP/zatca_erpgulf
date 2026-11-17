"""Ephemeral AES-GCM storage binding; no site key, database or connection."""

import base64
import pickle
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf import dispatch_record_codec as codec

SITE='fictional.invalid'
NAMESPACE='30000000-0000-4000-8000-000000000001'
RECORD='40000000-0000-4000-8000-000000000002'
KEY=b'T'*32
PAYLOAD=b'PRIVATE-ORIGINAL\x00\xff\r\n'
HEADER=codec.encode_record_header({'source_doctype':'Sales Invoice','source_name':'SYNTHETIC','version':1})


def cipher(*,site=SITE,namespace=NAMESPACE,key=KEY):
    return codec.DispatchRecordCipher(key,site=site,storage_namespace=namespace)


@pytest.mark.parametrize('kind',['artifact','receipt'])
def test_envelope_roundtrip_is_exact_randomized_and_not_exportable(kind):
    owner=cipher()
    first=owner.seal(RECORD,kind,HEADER,PAYLOAD)
    second=owner.seal(RECORD,kind,HEADER,PAYLOAD)
    assert first != second
    assert owner.open(RECORD,kind,HEADER,first)==PAYLOAD
    assert owner.open(RECORD,kind,HEADER,second)==PAYLOAD
    assert 'PRIVATE' not in first and 'PRIVATE' not in repr(owner)
    with pytest.raises(TypeError):pickle.dumps(owner)


@pytest.mark.parametrize('change',['site','namespace','key','record','kind','header','nonce','ciphertext'])
def test_record_envelope_cannot_move_between_bound_contexts(change):
    owner=cipher();encrypted=owner.seal(RECORD,'artifact',HEADER,PAYLOAD)
    other,record,kind,header=owner,RECORD,'artifact',HEADER
    if change=='site':other=cipher(site='different.invalid')
    if change=='namespace':other=cipher(namespace='30000000-0000-4000-8000-000000000003')
    if change=='key':other=cipher(key=b'X'*32)
    if change=='record':record='40000000-0000-4000-8000-000000000003'
    if change=='kind':kind='receipt'
    if change=='header':header=codec.encode_record_header({'source_name':'DIFFERENT'})
    if change in ('nonce','ciphertext'):
        raw=bytearray(base64.b64decode(encrypted[3:]));raw[0 if change=='nonce' else -1]^=1
        encrypted='v1.'+base64.b64encode(raw).decode()
    with pytest.raises(codec.DispatchRecordError) as caught:other.open(record,kind,header,encrypted)
    assert caught.value.code=='dispatch_record_integrity'
    assert 'PRIVATE' not in str(caught.value) and caught.value.__context__ is None


@pytest.mark.parametrize('header',[{},[],{'a':[]},{'a':object()},{'a':1.5},{'a':2**63},{'a':b'value'},{'a':'x'*4097}])
def test_header_does_not_stringify_or_accept_mutable_or_unbounded_values(header):
    with pytest.raises(codec.DispatchRecordError):codec.encode_record_header(header)


@pytest.mark.parametrize('raw',[b'',b'{}',b'{"a":1,"a":2}',b'{ "a":1}',b'{"a":NaN}',b'[]',b'\xff'])
def test_noncanonical_or_duplicate_header_is_not_repaired(raw):
    with pytest.raises(codec.DispatchRecordError):codec.decode_record_header(raw)


def test_header_view_is_immutable_and_input_dictionary_is_not_retained():
    source={'source_name':'INITIAL','version':1}
    raw=codec.encode_record_header(source);source['source_name']='CHANGED'
    observed=codec.decode_record_header(raw)
    assert observed['source_name']=='INITIAL'
    with pytest.raises(TypeError):observed['source_name']='OTHER'


@pytest.mark.parametrize('raw',['','v2.invalid','v1.%%%','v1.'+base64.b64encode(b'a'*28).decode(),'v1.\n'+base64.b64encode(b'a'*40).decode()])
def test_invalid_ciphertext_is_a_static_unchained_review(raw):
    with pytest.raises(codec.DispatchRecordError) as caught:cipher().open(RECORD,'artifact',HEADER,raw)
    assert caught.value.__context__ is None


@pytest.mark.parametrize('payload',[b'',bytearray(b'PRIVATE'),None,'PRIVATE'])
def test_payload_requires_original_immutable_bytes(payload):
    with pytest.raises(codec.DispatchRecordError):cipher().seal(RECORD,'receipt',HEADER,payload)
