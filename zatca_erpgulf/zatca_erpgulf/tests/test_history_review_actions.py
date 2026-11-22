"""Fixed operator admission/presentation doubles; no site or authority access."""

import csv
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import history_review_actions as actions
from zatca_erpgulf.zatca_erpgulf.legacy_history_audit import HistoryAuditResult
from zatca_erpgulf.zatca_erpgulf.legacy_history_capture import HistoryCaptureResult
from zatca_erpgulf.zatca_erpgulf.native_registration import LegacyRegistrationReview
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError


@pytest.mark.parametrize('operation', ['capture', 'audit', 'restart-audit'])
def test_only_fixed_operations_use_saved_arguments_and_expose_metadata(monkeypatch, operation):
    saved = dict(history_page_after='7', history_review_id='REVIEW', reason='PRIVATE REASON')
    monkeypatch.setattr(actions, '_saved_arguments', lambda *args, **kwargs: (saved.copy(), False))
    capture = HistoryCaptureResult('PAGE', False, '9', 2, '4', '1')
    audit = HistoryAuditResult('AUDIT', True, False, '2', '4', 0, True, '5', '1', '1', '0', False, '2026-11-22T12:00:00.000000')
    execute = Mock(return_value=LegacyRegistrationReview('REVIEW', '9', True, capture=capture, audit=audit))
    monkeypatch.setattr(actions, 'review_legacy_registration', execute)
    result = actions.run_saved_history_action('REVIEW', operation, runtime=object(), translate=lambda text: 'AR:' + text)
    args = execute.call_args.kwargs
    assert args['reason'] == 'PRIVATE REASON'
    assert args['history_page_after'] == ('7' if operation == 'capture' else '0')
    assert args.get('history_capture', False) == (operation == 'capture')
    assert args.get('history_audit_restart', False) == (operation == 'restart-audit')
    assert result['status'] == ('CAPTURED' if operation == 'capture' else 'AUDITED')
    assert 'PRIVATE' not in repr(result) and 'AR:' in result['message']


@pytest.mark.parametrize('operation', [None, True, 'reset', 'send', '<script>'])
def test_invalid_operations_do_not_enter_owned_storage(monkeypatch, operation):
    read = Mock(side_effect=AssertionError('No storage'))
    monkeypatch.setattr(actions, '_saved_arguments', read)
    with pytest.raises(actions.HistoryReviewActionError, match=actions.REVIEW):
        actions.run_saved_history_action('ID', operation, runtime=object(), translate=str)
    read.assert_not_called()


def test_exhausted_capture_is_not_an_audit_or_an_extra_append(monkeypatch):
    monkeypatch.setattr(actions, '_saved_arguments', lambda *args, **kwargs: ({}, True))
    execute = Mock(side_effect=AssertionError('No append'))
    monkeypatch.setattr(actions, 'review_legacy_registration', execute)
    result = actions.run_saved_history_action('ID', 'capture', runtime=object(), translate=str)
    assert result == dict(status='CAPTURE_EXHAUSTED', review_id='ID', message=actions.EXHAUSTED)
    execute.assert_not_called()


@pytest.mark.parametrize('logging_fails', [False, True])
def test_one_translated_error_keeps_uncertainty_and_english_diagnostic(monkeypatch, logging_fails):
    runtime = SimpleNamespace(flags={'parent': 1}, log_error=Mock(side_effect=RuntimeError('PRIVATE LOG') if logging_fails else None))
    monkeypatch.setattr(actions, 'frappe', runtime)
    monkeypatch.setattr(actions, '_', lambda text: 'AR:' + text)
    def failed(*args, **kwargs):
        assert runtime.flags['mute_messages'] is True
        raise ChainRegistrationError('registration_capture_audit_compare', commit_uncertain=True)
    monkeypatch.setattr(actions, 'run_saved_history_action', failed)
    with pytest.raises(actions.HistoryReviewActionError) as caught:
        inspect.unwrap(actions.review_saved_history)('ID', 'audit')
    assert str(caught.value) == 'AR:' + actions.REVIEW and caught.value.__context__ is None
    assert caught.value.commit_uncertain and runtime.flags == {'parent': 1}
    assert runtime.log_error.call_args.kwargs['message'] == 'registration_capture_audit_compare'


def test_all_operator_texts_have_arabic_entries():
    root = Path(__file__).resolve().parents[2]
    with (root / 'translations/ar.csv').open(newline='', encoding='utf-8') as file:
        catalog = {row[0]: row[1] for row in csv.reader(file) if len(row) > 1}
    values = [actions.REVIEW, actions.CAPTURED, actions.EXHAUSTED, actions.AUDITED, actions.COMPLETE,
        actions.CONTINUE, actions.SAVED, actions.GENESIS, 'Unknown', 'Yes', 'No', 'Saved History Review',
        'Capture Next History Page', 'Audit Captured History', 'Restart Captured History Audit',
        'Restart the local audit from the current captured head? The saved checkpoint will be replaced; captured pages remain retained. Nothing will be sent to ZATCA.']
    for text in values:
        assert text in catalog and any('\u0600' <= letter <= '\u06ff' for letter in catalog[text])
