"""Saved-result proof domain and aggregated translated operator boundaries."""

import csv
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf import submission_intent_reconciliation as reconciliation
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher,encode_record_header
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent import header


@pytest.mark.parametrize('accepted',[False,True])
def test_operator_returns_one_translated_result_with_explicit_acceptance(monkeypatch,accepted):
    runtime=SimpleNamespace(msgprint=Mock())
    monkeypatch.setattr(reconciliation,'frappe',runtime)
    monkeypatch.setattr(reconciliation,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(reconciliation,'reconcile_saved_result',lambda *args,**kwargs:{'status':'COMPLETE','accepted':accepted})
    result=inspect.unwrap(reconciliation.reconcile_request)('RECORD','RUNNING','FENCE')
    assert result['message']=='AR:'+(reconciliation.ACCEPTED if accepted else reconciliation.PREPARED)
    assert result['accepted'] is accepted;runtime.msgprint.assert_not_called()


@pytest.mark.parametrize('logging_fails',[False,True])
def test_operator_review_redacts_child_context_even_with_broken_diagnostics(monkeypatch,logging_fails):
    runtime=SimpleNamespace(log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if logging_fails else None))
    monkeypatch.setattr(reconciliation,'frappe',runtime)
    monkeypatch.setattr(reconciliation,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(reconciliation,'reconcile_saved_result',Mock(side_effect=RuntimeError('PRIVATE RECEIPT')))
    with pytest.raises(reconciliation.IntentReconciliationError) as caught:
        inspect.unwrap(reconciliation.reconcile_request)('RECORD','RUNNING','FENCE')
    assert str(caught.value)=='AR:'+reconciliation.REVIEW and caught.value.__context__ is None
    assert 'PRIVATE' not in repr(runtime.log_error.call_args)


@pytest.mark.parametrize('kind',['intent-reconciliation','intent-retirement','submission-intent','collection-intent','receipt'])
def test_saved_result_capsule_has_its_own_domain_in_the_shared_resolution_slot(kind):
    h=header();raw=intent.validate_header(h);fence=str(uuid4())
    proof=dict(record_id=h['record_id'],intent_sha256=hashlib.sha256(raw).hexdigest(),
        resolved_by='operator@example.invalid',resolved_at_utc='2026-11-21T10:00:00.000000',
        prior_state='RUNNING',prior_fence=fence,reason='reconciled_prepared',issuance_id=str(uuid4()),
        issuance_state='PREPARED',attempt_id=None,outcome='RETAINED_ORIGINAL',original_xml_sha256='a'*64)
    encoded=encode_record_header(proof)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    owner=SimpleNamespace(cipher=cipher,require_owner=Mock())
    row=dict(resolution_header=encoded.decode(),resolution_ciphertext=cipher.seal(h['record_id'],kind,encoded,intent.RECONCILIATION_BODY),
        active_key=None,fence_token=fence)
    if kind=='intent-reconciliation':assert intent.open_reconciliation(owner,row,h)==proof
    else:
        with pytest.raises(Exception):intent.open_reconciliation(owner,row,h)
    with pytest.raises(Exception):intent.open_retirement(owner,row,h)
    assert intent.validate_header(h)==raw


def test_all_display_templates_have_real_arabic_entries():
    root=Path(__file__).resolve().parents[2]
    with (root/'translations'/'ar.csv').open(newline='',encoding='utf-8') as handle:
        rows={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    for message in (reconciliation.REVIEW,reconciliation.ACCEPTED,reconciliation.PREPARED,
            'Reconcile Saved Result','Complete this stopped request only from its saved original and matching response, without generating or sending anything?'):
        assert any('\u0600'<=letter<='\u06ff' for letter in rows[message])
