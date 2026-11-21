"""A corrected preparation command cannot become retry/send authority."""

import csv
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import corrected_preparation as correction
from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_collection_intent import collection_header


def header():
    value=collection_header();value.update(request_kind='correction-v1',intent='correction',
        rejected_attempt_id=str(uuid4()),rejected_fence_token=str(uuid4()))
    value['active_key']=intent.collection_active_key(value);return value


@pytest.mark.parametrize('field,value',[('rejected_attempt_id',str(uuid4())),('rejected_fence_token',str(uuid4())),
    ('expected_issuance_id',None),('intent','manual'),('intent','retry'),('request_kind','retry-v1'),('request_kind','collection-v1')])
def test_command_binds_the_approved_rejected_version_attempt_fence_and_operation(field,value):
    h=header();intent.validate_header(h);h[field]=value
    with pytest.raises(Exception):intent.validate_header(h)


@pytest.mark.parametrize('kind',['correction-intent','retry-intent','collection-intent','submission-intent','artifact'])
def test_separate_cryptographic_domain_preserves_all_original_command_contracts(kind):
    h=header();raw=intent.validate_header(h)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    encrypted=cipher.seal(h['record_id'],kind,raw,intent.CORRECTION_BODY)
    if kind=='correction-intent':assert cipher.open(h['record_id'],kind,raw,encrypted)==intent.envelope_body(h)
    else:
        with pytest.raises(Exception):cipher.open(h['record_id'],'correction-intent',raw,encrypted)
    assert intent.envelope_kind(h)=='correction-intent'


@pytest.mark.parametrize('logging_fails',[False,True])
def test_public_failure_is_fresh_translated_and_redacts_child_context(monkeypatch,logging_fails):
    runtime=SimpleNamespace(log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if logging_fails else None),flags={})
    monkeypatch.setattr(correction,'frappe',runtime);monkeypatch.setattr(correction,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(correction,'register_corrected_preparation',Mock(side_effect=RuntimeError('PRIVATE SQL PASSWORD')))
    with pytest.raises(correction.CorrectedPreparationError) as caught:
        inspect.unwrap(correction.queue_corrected_preparation)('A','B','C')
    assert str(caught.value)=='AR:'+correction.REVIEW and caught.value.__context__ is None
    assert 'PRIVATE' not in repr(runtime.log_error.call_args)


def test_registration_is_pending_local_preparation_not_acceptance_or_a_second_popup(monkeypatch):
    runtime=SimpleNamespace(flags={},msgprint=Mock())
    monkeypatch.setattr(correction,'frappe',runtime);monkeypatch.setattr(correction,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(correction,'register_corrected_preparation',lambda *args,**kwargs:{'status':'DEFERRED','accepted':False,'request_id':'REQUEST'})
    result=inspect.unwrap(correction.queue_corrected_preparation)('A','B','C')
    assert result['status']=='DEFERRED' and not result['accepted'] and result['message']=='AR:'+correction.REGISTERED
    runtime.msgprint.assert_not_called()


def test_real_arabic_catalog_contains_all_new_display_templates():
    with (Path(__file__).resolve().parents[2]/'translations'/'ar.csv').open(encoding='utf-8',newline='') as handle:
        catalog={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    for message in (correction.REVIEW,correction.REGISTERED,'Prepare Corrected XML','Corrected XML Request',
        'Prepare a new corrected XML version locally from the current saved invoice? It will receive a new UUID and invoice counter while retaining the rejected original. Posting dates and amounts are not edited. This does not send anything to ZATCA.'):
        assert any('\u0600'<=letter<='\u06ff' for letter in catalog[message])
