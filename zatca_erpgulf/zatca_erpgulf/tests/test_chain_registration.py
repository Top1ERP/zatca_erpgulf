"""Registration envelope framing and bounds; no enrollment/activation claims."""

from datetime import datetime
import hashlib
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import chain_registration as registration
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher, DispatchRecordError
from zatca_erpgulf.zatca_erpgulf.dispatch_store import DispatchStoreError


def evidence():
    xml,reason=b'<Invoice>PRIVATE-EXACT-XML\r\n</Invoice>','Reviewed exact legacy original — مراجعة'
    payload=registration.encode_registration_payload(xml,reason)
    header=dict(record_id=str(uuid4()),owner_key='a'*64,owner_doctype='Company',owner_name='SYNTHETIC',
        company='SYNTHETIC',environment='Production',seller_tax_id='TEST-VAT',registration_kind='LEGACY_REVIEWED',
        certificate_sha256='b'*64,public_key_sha256='c'*64,base_url_sha256='d'*64,source_doctype='Sales Invoice',
        source_name='SYNTHETIC-INV',source_uuid=str(uuid4()),source_unit='company:legacy-unit',
        legacy_counter='SYNTHETIC-COUNTER',icv='430202400119',invoice_hash='DECLARED-INVOICE-HASH',file_id='PRIVATE-FILE',
        xml_sha256=hashlib.sha256(xml).hexdigest(),source_sha256='e'*64,reviewed_by='TEST-OPERATOR',
        reviewed_at_utc=datetime(2026,11,17,10,20,30,123456).strftime('%Y-%m-%dT%H:%M:%S.%f'),
        reason_sha256=hashlib.sha256(reason.encode()).hexdigest(),payload_sha256=hashlib.sha256(payload).hexdigest(),
        supersedes_review=None)
    return header,payload,xml,reason


def test_exact_xml_and_reason_round_trip_in_a_distinct_cipher_domain():
    header,payload,xml,reason=evidence()
    encoded=registration.validate_registration_header(header)
    decoded,raw=registration.decode_registration_header(encoded.decode())
    assert dict(decoded)==header and raw==encoded
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    sealed=cipher.seal(header['record_id'],'chain-registration',encoded,payload)
    opened=cipher.open(header['record_id'],'chain-registration',encoded,sealed)
    assert registration.open_registration_payload(decoded,opened)==(xml,reason)
    assert b'\r\n' in xml and 'PRIVATE' not in sealed
    with pytest.raises(DispatchRecordError,match='dispatch_record_integrity'):
        cipher.open(header['record_id'],'artifact',encoded,sealed)


@pytest.mark.parametrize('field,value',[('icv','0'),('icv','001'),('icv',1),('registration_kind','NEW_EGS'),
    ('owner_doctype','Customer'),('environment','production'),('source_doctype','Purchase Invoice'),
    ('source_uuid','not-a-uuid'),('xml_sha256','A'*64),('owner_name',' name '),
    ('source_unit',''),('reviewed_at_utc','2026-11-17T10:20:30Z')])
def test_no_genesis_guessing_or_unbounded_identity_values(field,value):
    header,_,_,_=evidence();header[field]=value
    with pytest.raises((DispatchRecordError,DispatchStoreError)) as caught:
        registration.validate_registration_header(header)
    expected={'icv':'dispatch_counter_shape','registration_kind':'registration_binding',
        'owner_doctype':'registration_binding','environment':'registration_binding','source_doctype':'registration_binding',
        'source_uuid':'dispatch_record_identity','xml_sha256':'dispatch_fingerprint_shape',
        'owner_name':'registration_identity','source_unit':'registration_identity','reviewed_at_utc':'registration_review_clock'}
    assert caught.value.code==expected[field]


@pytest.mark.parametrize('reason',[None,'','  ',b'PRIVATE','x'*1001,'\ud800'])
def test_invalid_review_reasons_never_reach_persistence(reason):
    with pytest.raises(registration.ChainRegistrationError,match='registration_review_reason') as caught:
        registration.encode_registration_payload(b'<Invoice/>',reason)
    assert caught.value.__context__ is None and 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('fault',['short','zero_length','large_length','changed_xml','changed_reason','digest'])
def test_framing_and_digests_prevent_substituting_a_reviewed_anchor(fault):
    header,payload,_,_=evidence()
    if fault=='short':payload=b'x'
    elif fault=='zero_length':payload=b'\0\0'+payload[2:]
    elif fault=='large_length':payload=b'\xff\xff'+payload[2:]
    elif fault=='changed_xml':payload=payload.replace(b'PRIVATE',b'CHANGED')
    elif fault=='changed_reason':payload=payload.replace(b'Reviewed',b'Changed')
    else:header['payload_sha256']='0'*64
    with pytest.raises(registration.ChainRegistrationError):
        registration.open_registration_payload(header,payload)


def test_evidence_digest_binds_metadata_payload_and_protocol_domain():
    header,payload,_,_=evidence();encoded=registration.validate_registration_header(header)
    first=registration.evidence_sha256(encoded,payload)
    header['company']='OTHER'
    assert registration.evidence_sha256(registration.validate_registration_header(header),payload)!=first
    assert registration.evidence_sha256(encoded,payload+b' ')!=first
