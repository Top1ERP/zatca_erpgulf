"""Collection header domains and physical LocalProxy identity, without a site."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.local import LocalProxy

from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher,DispatchRecordError
from zatca_erpgulf.zatca_erpgulf.worker_transaction import current_database,WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent import header


def collection_header():
    h=header();h.update(request_kind='collection-v1',expected_issuance_id=str(uuid4()),intent='manual')
    h['source_key']=intent.collection_source_key(h['record_id']);h['active_key']=intent.collection_active_key(h)
    return h


@pytest.mark.parametrize('field,value',[('actor','other@example.invalid'),('chain',str(uuid4())),
    ('intent','scheduled'),('source_name','OTHER'),('company','OTHER'),('source_sha256','f'*64),
    ('expected_issuance_id',str(uuid4())),('request_kind','unknown'),('active_key','a'*64)])
def test_collection_slot_and_expected_version_are_authenticated_header_fields(field,value):
    h=collection_header();intent.validate_header(h);h[field]=value
    with pytest.raises((RuntimeError,ValueError)):intent.validate_header(h)


def test_collection_envelope_cannot_be_opened_as_an_original_submit_request():
    h=collection_header();raw=intent.validate_header(h)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    envelope=cipher.seal(h['record_id'],'collection-intent',raw,intent.COLLECTION_BODY)
    assert cipher.open(h['record_id'],'collection-intent',raw,envelope)==intent.COLLECTION_BODY
    with pytest.raises(DispatchRecordError):cipher.open(h['record_id'],'submission-intent',raw,envelope)


def test_recovery_command_requires_a_collection_slot_and_exact_existing_version():
    h=collection_header();h['intent']='recovery';h['active_key']=intent.collection_active_key(h)
    intent.validate_header(h)
    h['expected_issuance_id']=None;h['active_key']=intent.collection_active_key(h)
    with pytest.raises(intent.SubmissionIntentError):intent.validate_header(h)
    original=header();original['intent']='recovery'
    with pytest.raises(intent.SubmissionIntentError):intent.validate_header(original)


def test_localproxy_identity_is_not_physical_connection_identity():
    first,second=object(),object();local=SimpleNamespace(db=first)
    proxy=LocalProxy(lambda:local.db);runtime=SimpleNamespace(local=local,db=proxy)
    assert current_database(runtime) is first
    local.db=second
    assert runtime.db is proxy and current_database(runtime) is second
    runtime.db=first
    with pytest.raises(WorkerTransactionError):current_database(runtime)


@pytest.mark.parametrize('committed',[False,True])
def test_collection_boundary_remains_fatal_when_diagnostic_writer_fails(committed):
    from unittest.mock import Mock
    from zatca_erpgulf.zatca_erpgulf import collection_intent
    def throw(message,*,exc):raise exc
    runtime=SimpleNamespace(log_error=Mock(side_effect=RuntimeError('PRIVATE LOGGER')),throw=throw)
    with pytest.raises(collection_intent.CollectionSubmissionError) as caught:
        collection_intent._raise_review(runtime,lambda s:'AR:'+s,'collection_registration_unconfirmed',committed=committed)
    assert caught.value.fatal and caught.value.__context__ is None and 'PRIVATE' not in str(caught.value)


@pytest.mark.parametrize('template_name',['REVIEW','QUEUE_REVIEW'])
def test_collection_review_has_arabic_display_catalog(template_name):
    import csv
    from pathlib import Path
    from zatca_erpgulf.zatca_erpgulf import collection_intent
    with (Path(__file__).resolve().parents[2]/'translations/ar.csv').open(newline='') as stream:catalog=dict(csv.reader(stream))
    template=getattr(collection_intent,template_name)
    assert catalog[template]!=template and any('\u0600'<=char<='\u06ff' for char in catalog[template])
