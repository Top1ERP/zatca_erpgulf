"""Late acceptance proof shape, scalar review fence and aggregate translation."""

import csv
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import late_acceptance as operator
from zatca_erpgulf.zatca_erpgulf import late_acceptance_evidence as evidence
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher


def proof():
    return dict(record_id=str(uuid4()),chain=str(uuid4()),artifact_sha256='a'*64,
        accepted_attempt=str(uuid4()),accepted_fence=str(uuid4()),response_sha256='b'*64,
        prior_attempt=str(uuid4()),prior_fence=str(uuid4()),prior_state='OUTCOME_UNKNOWN',prior_state_version=4,
        resolved_by='operator@example.invalid',resolved_at_utc='2026-11-21T10:00:00.000000',outcome='REPORTING_MATCHED')


@pytest.mark.parametrize('field,value',[
    ('extra',1),('outcome','UNCONFIRMED'),('prior_state','REJECTED'),('prior_state_version',True),
    ('prior_state_version',-1),('resolved_by','Guest'),('record_id','bad'),
    ('artifact_sha256','BAD'),('resolved_at_utc','2026-11-21T9:00:00.000000'),
])
def test_only_exact_acceptance_review_can_be_authenticated(field,value):
    p=proof();p[field]=value
    with pytest.raises(Exception):evidence.validate_proof(p)


@pytest.mark.parametrize('value',[True,1.0,'01',' 1','1.0','+1','١',None,-1,2147483647])
def test_review_revision_is_not_coerced_to_another_claim(value):
    with pytest.raises(operator.LateAcceptanceError):operator._version(value)


@pytest.mark.parametrize('kind',['late-acceptance','receipt','artifact','intent-reconciliation'])
def test_decision_has_its_own_encrypted_domain(kind):
    p=proof();raw=evidence.validate_proof(p)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    encrypted=cipher.seal(p['record_id'],kind,raw,evidence.BODY)
    issuance=dict(p,state='REPORTED',active_attempt=p['prior_attempt'],
        late_acceptance_header=raw.decode(),late_acceptance_ciphertext=encrypted)
    repository=SimpleNamespace(open_late_acceptance=lambda row,aad,body:cipher.open(row['record_id'],'late-acceptance',aad,body))
    if kind=='late-acceptance':assert evidence.open_resolution(repository,issuance)==p
    else:
        with pytest.raises(Exception):evidence.open_resolution(repository,issuance)


@pytest.mark.parametrize('logging_fails',[False,True])
def test_public_failure_is_one_fresh_translated_message_and_static_english_diagnostic(monkeypatch,logging_fails):
    runtime=SimpleNamespace(log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if logging_fails else None),msgprint=Mock())
    monkeypatch.setattr(operator,'frappe',runtime);monkeypatch.setattr(operator,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(operator,'reconcile_late_acceptance',Mock(side_effect=RuntimeError('PRIVATE DB PASSWORD')))
    with pytest.raises(operator.LateAcceptanceError) as caught:
        inspect.unwrap(operator.reconcile_response)('A','B',1,'C')
    assert str(caught.value)=='AR:'+operator.REVIEW and caught.value.__context__ is None
    assert 'PRIVATE' not in repr(runtime.log_error.call_args);runtime.msgprint.assert_not_called()


def test_real_arabic_catalog_has_all_display_templates():
    path=Path(__file__).resolve().parents[2]/'translations'/'ar.csv'
    with path.open(encoding='utf-8',newline='') as handle:catalog={r[0]:r[1] for r in csv.reader(handle) if len(r)>1}
    for message in (operator.REVIEW,operator.SUCCESS,'Review Late Acceptance','Earlier Response Attempt',
        'Late Acceptance Review','Review Saved Response',
        'Resolve this original only from an earlier matching saved acceptance? The server will review the newer attempt and retain both histories. Nothing will be generated or sent.'):
        assert any('\u0600'<=letter<='\u06ff' for letter in catalog[message])


def test_null_optional_proof_keeps_current_receipt_policy():
    repository=SimpleNamespace(open_receipt=Mock(return_value=('HEADER',b'BODY')))
    assert evidence.accepted_receipt(repository,dict(active_attempt='CURRENT'))==('HEADER',b'BODY')
    repository.open_receipt.assert_called_once_with('CURRENT')
