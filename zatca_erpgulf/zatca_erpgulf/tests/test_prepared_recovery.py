"""Saved-original request presentation and child-message ownership."""

import csv
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import prepared_recovery as recovery
from zatca_erpgulf.zatca_erpgulf.collection_intent import CollectionSubmissionError


@pytest.mark.parametrize('logging_fails',[False,True])
def test_one_translated_error_preserves_parent_flags_and_drops_private_context(monkeypatch,logging_fails):
    runtime=SimpleNamespace(flags={'mute_messages':False,'parent':1},log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if logging_fails else None))
    monkeypatch.setattr(recovery,'frappe',runtime);monkeypatch.setattr(recovery,'_',lambda text:'AR:'+text)
    def fail(*args,**kwargs):
        assert runtime.flags['mute_messages'] is True
        raise RuntimeError('PRIVATE XML OR SQL')
    monkeypatch.setattr(recovery,'register_prepared_original',fail)
    with pytest.raises(recovery.PreparedRecoveryError) as caught:
        inspect.unwrap(recovery.queue_saved_original)('ID')
    assert str(caught.value)=='AR:'+recovery.REVIEW and caught.value.__context__ is None and caught.value.fatal
    assert runtime.flags=={'mute_messages':False,'parent':1}
    assert 'PRIVATE' not in repr(runtime.log_error.call_args)


def test_already_logged_child_failure_has_no_duplicate_diagnostic_or_popup(monkeypatch):
    runtime=SimpleNamespace(flags={},log_error=Mock())
    monkeypatch.setattr(recovery,'frappe',runtime);monkeypatch.setattr(recovery,'_',lambda text:'AR:'+text)
    error=CollectionSubmissionError('safe_static_code');error.diagnostic_logged=True
    monkeypatch.setattr(recovery,'register_prepared_original',Mock(side_effect=error))
    with pytest.raises(recovery.PreparedRecoveryError):inspect.unwrap(recovery.queue_saved_original)('ID')
    runtime.log_error.assert_not_called();assert runtime.flags=={}


def test_request_registration_is_not_an_authority_acceptance_or_extra_server_popup(monkeypatch):
    runtime=SimpleNamespace(flags={},msgprint=Mock())
    monkeypatch.setattr(recovery,'frappe',runtime);monkeypatch.setattr(recovery,'_',lambda text:'AR:'+text)
    monkeypatch.setattr(recovery,'register_prepared_original',lambda *args,**kwargs:dict(status='DEFERRED',accepted=False))
    result=inspect.unwrap(recovery.queue_saved_original)('ID')
    assert result['status']=='DEFERRED' and result['accepted'] is False and result['message']=='AR:'+recovery.REGISTERED
    runtime.msgprint.assert_not_called();assert runtime.flags=={}


def test_all_display_templates_have_arabic_catalog_entries():
    root=Path(__file__).resolve().parents[2]
    with (root/'translations'/'ar.csv').open(newline='',encoding='utf-8') as handle:
        rows={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    for message in (recovery.REVIEW,recovery.REGISTERED,'Queue Saved Original','Saved Original Request','View Request',
            'Register an explicit manual request to send this exact saved original? No XML or invoice identity will be regenerated. This is not an unknown-outcome retry.'):
        assert any('\u0600'<=letter<='\u06ff' for letter in rows[message])
