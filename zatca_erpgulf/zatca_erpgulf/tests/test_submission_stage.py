"""Initial source binding is authenticated custody, never executable authority."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent import header


def stage_header():
    complete=header()
    stage={key:complete[key] for key in intent.STAGE_FIELDS if key!='request_kind'}
    return dict(stage,request_kind='submit-stage-v1')


@pytest.mark.parametrize('field,value',[
    ('extra',True),('record_id','bad'),('actor','Guest'),('source_key','f'*64),
    ('source_doctype','Quotation'),('source_name',' x '),('intent','retry'),
    ('request_kind','collection-v1'),('created_at_utc','2026-11-20T9:00:00.000000'),
    ('created_at_utc','2026-02-30T09:00:00.000000'),
])
def test_initial_header_requires_exact_source_actor_kind_and_clock(field,value):
    stage=stage_header();stage[field]=value
    with pytest.raises((ValueError,RuntimeError)):intent.validate_stage_header(stage)


@pytest.mark.parametrize('kind',['submission-stage','submission-intent','collection-intent','retry-intent','intent-retirement'])
def test_stage_is_a_separate_authenticated_domain_and_not_a_complete_header(kind):
    stage=stage_header();encoded=intent.validate_stage_header(stage)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    envelope=cipher.seal(stage['record_id'],kind,encoded,intent.STAGE_BODY)
    if kind=='submission-stage':
        assert cipher.open(stage['record_id'],'submission-stage',encoded,envelope)==intent.STAGE_BODY
    else:
        with pytest.raises(Exception):cipher.open(stage['record_id'],'submission-stage',encoded,envelope)
    with pytest.raises(intent.SubmissionIntentError):intent.validate_header(stage)
    runtime=SimpleNamespace(session=SimpleNamespace(user=stage['actor']))
    with pytest.raises(intent.SubmissionIntentError):
        with intent.execution_context(runtime,stage,str(uuid4())):pytest.fail('No execution authority')
    assert intent.envelope_kind(stage)=='submission-stage' and intent.envelope_body(stage)==intent.STAGE_BODY


@pytest.mark.parametrize('state',['READY','RUNNING','COMPLETE','REVIEW','WAITING'])
def test_mutable_state_cannot_promote_partial_stage_to_executable_request(state):
    stage=stage_header();cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    row=dict(stage,state=state,intent_header=intent.validate_stage_header(stage).decode(),
        intent_ciphertext='UNUSED',active_key=None,expected_issuance_id=None,operation=None,
        retry_attempt_id=None,retry_fence_token=None,fence_token=None,
        resolution_header=None,resolution_ciphertext=None)
    owner=SimpleNamespace(require_owner=Mock(),database=SimpleNamespace(sql=Mock(return_value=[row])),cipher=cipher)
    with pytest.raises(intent.SubmissionIntentError,match='stage_execution_forbidden'):
        intent.open_intent(owner,stage['record_id'],allow_staged=True)


def test_stage_retirement_proof_cannot_claim_ready_or_running_origin():
    import hashlib
    from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import encode_record_header
    stage=stage_header();encoded=intent.validate_stage_header(stage)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    proof=dict(record_id=stage['record_id'],intent_sha256=hashlib.sha256(encoded).hexdigest(),
        retired_by='operator@example.invalid',retired_at_utc='2026-11-21T10:00:00.000000',
        prior_state='READY',prior_fence=None,reason='unissued_request_retired')
    raw=encode_record_header(proof)
    row=dict(resolution_header=raw.decode(),resolution_ciphertext=cipher.seal(stage['record_id'],
        'intent-retirement',raw,intent.RETIREMENT_BODY),active_key=None,fence_token=None)
    owner=SimpleNamespace(cipher=cipher,require_owner=Mock())
    with pytest.raises(intent.SubmissionIntentError,match='stage_retirement_binding'):
        intent.open_retirement(owner,row,stage)
