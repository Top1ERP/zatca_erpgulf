"""Exact retry envelope authorization and translated aggregate display."""

import csv
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import exact_retry
from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_collection_intent import collection_header


def retry_header():
    h=collection_header();h.update(request_kind='retry-v1',intent='retry',retry_attempt_id=str(uuid4()),retry_fence_token=str(uuid4()))
    h['active_key']=intent.collection_active_key(h);return h


@pytest.mark.parametrize('field,value',[('retry_attempt_id',str(uuid4())),('retry_fence_token',str(uuid4())),
    ('expected_issuance_id',None),('intent','manual'),('request_kind','collection-v1')])
def test_retry_approval_is_exact_version_attempt_and_fence(field,value):
    h=retry_header();intent.validate_header(h);h[field]=value
    with pytest.raises(Exception):intent.validate_header(h)


def test_retry_capsule_cannot_be_read_as_ordinary_collection_authority():
    h=retry_header();encoded=intent.validate_header(h)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    body=cipher.seal(h['record_id'],intent.envelope_kind(h),encoded,intent.envelope_body(h))
    assert cipher.open(h['record_id'],'retry-intent',encoded,body)==intent.RETRY_BODY
    with pytest.raises(Exception):cipher.open(h['record_id'],'collection-intent',encoded,body)


@pytest.mark.parametrize('logging_fails',[False,True])
def test_error_is_one_translated_message_with_no_child_context(monkeypatch,logging_fails):
    runtime=SimpleNamespace(flags={},log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if logging_fails else None))
    monkeypatch.setattr(exact_retry,'frappe',runtime);monkeypatch.setattr(exact_retry,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(exact_retry,'register_exact_retry',Mock(side_effect=RuntimeError('PRIVATE BODY')))
    with pytest.raises(exact_retry.ExactRetryError) as caught:
        inspect.unwrap(exact_retry.queue_exact_retry)('ID','ATTEMPT','FENCE')
    assert str(caught.value)=='AR:'+exact_retry.REVIEW and caught.value.__context__ is None and caught.value.fatal
    assert 'PRIVATE' not in repr(runtime.log_error.call_args) and runtime.flags=={}


def test_registered_retry_does_not_claim_acceptance_or_popup_twice(monkeypatch):
    runtime=SimpleNamespace(flags={},msgprint=Mock())
    monkeypatch.setattr(exact_retry,'frappe',runtime);monkeypatch.setattr(exact_retry,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(exact_retry,'register_exact_retry',lambda *args,**kwargs:dict(status='DEFERRED',accepted=False))
    result=inspect.unwrap(exact_retry.queue_exact_retry)('ID','ATTEMPT','FENCE')
    assert result['message']=='AR:'+exact_retry.REGISTERED and result['accepted'] is False
    runtime.msgprint.assert_not_called()


def test_arabic_catalog_covers_retry_confirmation_and_result():
    with (Path(__file__).resolve().parents[2]/'translations'/'ar.csv').open(newline='',encoding='utf-8') as handle:
        rows={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    for message in (exact_retry.REVIEW,exact_retry.REGISTERED,'Request Exact Retry','Exact Retry Request',
            'The previous attempt may already have been received. Request a deliberate retry of the exact same XML, UUID and hash after server eligibility checks? No new invoice will be generated.'):
        assert any('\u0600'<=letter<='\u06ff' for letter in rows[message])
