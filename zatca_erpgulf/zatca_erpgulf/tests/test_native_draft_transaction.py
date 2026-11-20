"""Collector propagation and translated draft boundary; no SQL/site/network."""

from contextlib import contextmanager
from unittest.mock import Mock
import csv
from pathlib import Path

import pytest

from zatca_erpgulf.zatca_erpgulf import native_draft_transaction as transaction
from zatca_erpgulf.zatca_erpgulf import draft_submission,background_worker
from zatca_erpgulf.zatca_erpgulf.tests.test_background_scheduling import worker_boundary
from zatca_erpgulf.zatca_erpgulf.tests.test_deferred_submission import boundary


@pytest.mark.parametrize('fatal',[False,True])
def test_actual_collector_only_continues_after_a_confirmed_local_rollback(worker_boundary,monkeypatch,fatal):
    b=worker_boundary;b.company('OPEN',custom_submit_or_not=1)
    bad=b.invoice('POS Invoice','BAD','OPEN',docstatus=0)
    good=b.invoice('POS Invoice','GOOD','OPEN',docstatus=1)
    error=transaction.NativeDraftTransactionError('native_draft_rollback_unconfirmed',fatal=fatal)
    monkeypatch.setattr(background_worker,'submit_draft',Mock(side_effect=error))
    def run():background_worker.run_pending_background_invoices('POS Invoice',b.callback)
    if fatal:
        with pytest.raises(transaction.NativeDraftTransactionError) as caught:run()
        assert caught.value is error
        b.callback.assert_not_called()
    else:
        run();b.callback.assert_called_once_with(good,bypass_background_check=True)
    bad.reload.assert_not_called();b.frappe.db.commit.assert_not_called()
    b.frappe.log_error.assert_called_once()
    assert b.frappe.log_error.call_args.kwargs['message']=='native_draft_rollback_unconfirmed'
    assert b.frappe.get_traceback.call_count==0


def test_native_draft_error_has_one_display_translation_and_english_static_diagnostic(boundary,monkeypatch):
    b=boundary;b.invoice.docstatus=0;b.invoice.submit=Mock()
    @contextmanager
    def protected(*args,**kwargs):
        raise transaction.NativeDraftTransactionError('native_draft_owner_changed')
        yield
    monkeypatch.setattr(transaction,'protect_native_draft',protected)
    with pytest.raises(transaction.NativeDraftTransactionError) as caught:
        draft_submission.submit_draft(b.invoice,runtime=b.app,translate=lambda s:'AR:'+s,operation='manual')
    assert caught.value.diagnostic_logged and caught.value.__context__ is None
    b.app.log_error.assert_called_once_with(title='ZATCA native draft transaction review',message='native_draft_owner_changed')
    assert b.app.throw.call_args.args[0]=='AR:'+transaction.REVIEW
    b.invoice.submit.assert_not_called();assert draft_submission.CURRENT.get() is None


def test_registration_bridge_is_inert_outside_a_native_draft_scope():
    cancel=Mock()
    assert transaction.bind_deferred_registration(object(),'Sales Invoice','SYNTHETIC',cancel,native=True,active=Mock()) is None
    cancel.assert_not_called()


@pytest.mark.parametrize('template',[transaction.REVIEW,transaction.SOURCE_REVIEW])
def test_transaction_review_has_a_real_arabic_catalog_entry(template):
    with (Path(__file__).resolve().parents[2]/'translations/ar.csv').open(newline='') as stream:
        catalog=dict(csv.reader(stream))
    value=catalog[template]
    assert value!=template and any('\u0600'<=char<='\u06ff' for char in value)


def test_native_transport_cannot_escape_after_hook_closed_while_draft_scope_is_active(boundary,monkeypatch):
    from zatca_erpgulf.zatca_erpgulf import native_transport,deferred_submission
    b=boundary;validate=Mock();exchange=Mock()
    monkeypatch.setattr(native_transport,'_validate',validate);monkeypatch.setattr(native_transport,'_exchange',exchange)
    assert deferred_submission.HOOK.get() is None
    token=transaction.CURRENT.set(object())
    try:
        with pytest.raises(deferred_submission.DeferredSubmissionError) as caught:
            native_transport.invoke_saved_request(object(),runtime=b.app)
        assert caught.value.code=='deferred_inline_transport'
    finally:transaction.CURRENT.reset(token)
    validate.assert_not_called();exchange.assert_not_called();b.app.db.commit.assert_not_called()
