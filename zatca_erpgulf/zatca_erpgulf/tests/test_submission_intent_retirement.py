"""Translated explicit operator boundary and fixed retirement schema."""

import csv
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import submission_intent_retirement as retirement
from zatca_erpgulf.zatca_erpgulf import submission_intent as intent
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher,encode_record_header
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent import header


ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('logging_fails',[False,True])
def test_operator_error_is_one_translated_message_without_private_context(monkeypatch,logging_fails):
    runtime=SimpleNamespace(log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if logging_fails else None))
    monkeypatch.setattr(retirement,'frappe',runtime);monkeypatch.setattr(retirement,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(retirement,'retire_unissued_intent',Mock(side_effect=RuntimeError('PRIVATE SQL PASSWORD')))
    with pytest.raises(retirement.IntentRetirementError) as caught:
        inspect.unwrap(retirement.retire_request)('RECORD','READY')
    assert str(caught.value)=='AR:'+retirement.REVIEW and caught.value.__context__ is None
    assert 'PRIVATE' not in repr(runtime.log_error.call_args)


def test_retirement_success_does_not_claim_acceptance_or_send_an_extra_popup(monkeypatch):
    runtime=SimpleNamespace(msgprint=Mock());monkeypatch.setattr(retirement,'frappe',runtime)
    monkeypatch.setattr(retirement,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(retirement,'retire_unissued_intent',lambda *args,**kwargs:{'status':'RETIRED','accepted':False})
    result=inspect.unwrap(retirement.retire_request)('RECORD','READY')
    assert result['accepted'] is False and result['message']=='AR:'+retirement.SUCCESS
    runtime.msgprint.assert_not_called()


def test_proof_fields_are_hidden_owned_immutable_data_and_retired_is_a_terminal_state():
    path=ROOT/'zatca_erpgulf'/'doctype'/'zatca_submission_intent'/'zatca_submission_intent.json'
    body=json.loads(path.read_text());fields={row['fieldname']:row for row in body['fields']}
    for name in ('retirement_header','retirement_ciphertext'):
        assert all(fields[name][flag]==1 for flag in ('read_only','hidden','no_copy','print_hide'))
        assert fields[name]['fieldtype']=='Long Text'
    assert 'RETIRED' in fields['state']['options'].splitlines()


def test_display_catalog_contains_all_operator_templates():
    with (ROOT/'translations'/'ar.csv').open(newline='',encoding='utf-8') as handle:
        rows={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    for message in (retirement.REVIEW,retirement.SUCCESS,'Retire Unissued Request',
            'Retire this local request only if no invoice was generated? Its history will remain, and an issued document cannot be retired here.'):
        assert any('\u0600'<=letter<='\u06ff' for letter in rows[message])


@pytest.mark.parametrize('kind',['intent-retirement','submission-intent','collection-intent','artifact','receipt'])
def test_retirement_uses_its_own_authenticated_domain_without_rewriting_original_header(kind):
    h=header();raw=intent.validate_header(h)
    proof=dict(record_id=h['record_id'],intent_sha256=hashlib.sha256(raw).hexdigest(),
        retired_by='operator@example.invalid',retired_at_utc='2026-11-21T10:00:00.000000',
        prior_state='READY',prior_fence=None,reason='unissued_request_retired')
    encoded=encode_record_header(proof)
    cipher=DispatchRecordCipher(b'T'*32,site='fictional.invalid',storage_namespace=str(uuid4()))
    owner=SimpleNamespace(cipher=cipher,require_owner=Mock())
    row=dict(retirement_header=encoded.decode(),retirement_ciphertext=cipher.seal(h['record_id'],kind,encoded,intent.RETIREMENT_BODY),
        active_key=None,fence_token=None)
    if kind=='intent-retirement':assert intent.open_retirement(owner,row,h)==proof
    else:
        with pytest.raises(Exception):intent.open_retirement(owner,row,h)
    assert intent.validate_header(h)==raw
