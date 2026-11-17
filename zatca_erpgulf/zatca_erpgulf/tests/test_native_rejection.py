"""Explicit replacement admission; originals/receipts are synthetic local data."""

import base64
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import native_dispatch as dispatch, sign_invoice
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import (
    coordinator, boundary, materials, signed_build,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document


@pytest.fixture
def rejected(coordinator, monkeypatch):
    c = coordinator
    monkeypatch.setattr(sign_invoice, '_onboarding_address', lambda *args: Document(
        address_line1='Test Street', address_line2='District', city='Riyadh',
        custom_building_number='1234', pincode='12345', state=''))
    dispatch.prepare_saved_invoice('Sales Invoice', 'SI', runtime=c.b.frappe, translate=lambda text: text,
        build=lambda source: signed_build(c.b, source))
    _, header, raw = c.repository.stage_issuance.call_args.args
    attempt = str(uuid4())
    saved = dict(header, state='REJECTED', active_attempt=attempt)
    body = json.dumps(dict(validationResults=dict(status='ERROR', warningMessages=[], infoMessages=[],
        errorMessages=[dict(type='ERROR', status='ERROR', code='TEST', message='Synthetic rejection')]),
        reportingStatus='NOT_REPORTED')).encode()
    receipt = dict(issuance=header['record_id'], request_sha256=header['artifact_sha256'],
        environment=header['environment'], endpoint=header['endpoint'], http_status=400,
        response_sha256=hashlib.sha256(body).hexdigest())
    c.repository.latest_issuance.return_value = saved
    c.repository.open_issuance.return_value = (header, raw)
    c.repository.open_receipt = Mock(return_value=(receipt, body))
    c.repository.lock_issuance = Mock(return_value=saved)
    c.b.sales.custom_uuid = header['invoice_uuid']
    c.b.sales.custom_zatca_icv = header['icv']
    c.b.sales.custom_zatca_issuing_unit = 'egs:' + c.chain['record_id']
    c.b.sales.custom_zatca_full_response = body.decode()
    # Other documents have since been generated: replacement uses that current
    # local tail, never a predecessor copied from the old rejected version.
    c.chain.update(last_icv='9', previous_hash=base64.b64encode(b'x' * 32).decode(), active_attempt=None)
    c.worker.commit.reset_mock()
    c.repository.stage_issuance.reset_mock()
    c.state.committed = False
    sql = c.worker.database.sql.side_effect
    def capacity(statement, values=(), **kwargs):
        if 'information_schema.columns' in statement and 'custom_zatca_full_response' in values:
            return [dict(fieldname=name, kind='longtext', max_chars=16000000, max_bytes=16000000)
                for name in ('custom_zatca_status', 'custom_zatca_full_response')]
        return sql(statement, values, **kwargs)
    c.worker.database.sql.side_effect = capacity
    c.worker.database.sql.reset_mock()
    build = Mock(side_effect=lambda source: signed_build(c.b, source,
        issue_instant=datetime(2026, 11, 10, 9, 6, 42, tzinfo=timezone.utc)))
    def prepare():
        return dispatch.prepare_corrected_rejection('Sales Invoice', 'SI', runtime=c.b.frappe,
            translate=lambda text: text, build=build,
            rejected_issuance_id=header['record_id'], rejected_attempt_id=attempt)
    return SimpleNamespace(c=c, header=header, saved=saved, receipt=receipt, build=build, prepare=prepare)


def test_explicit_verified_rejection_gets_new_version_and_current_generated_tail(rejected):
    t = rejected
    result = t.prepare()
    _, new, _ = t.c.repository.stage_issuance.call_args.args
    assert not result.reused and result.state == 'PREPARED'
    assert new['source_version'] == 2 and new['replaces_issuance'] == t.header['record_id']
    assert new['invoice_uuid'] != t.header['invoice_uuid'] and new['invoice_hash'] != t.header['invoice_hash']
    assert new['icv'] == '10' and new['previous_hash'] == t.c.chain['previous_hash']
    source_updates = [call for call in t.c.worker.database.sql.call_args_list if call.args[0].startswith('UPDATE `tabSales Invoice`')]
    assert source_updates[0].args[1][-3:] == ('Not Submitted', '', 'SI')
    t.c.worker.commit.assert_called_once()
    t.c.b.request.assert_not_called()


@pytest.mark.parametrize('state', ['PREPARED', 'DISPATCHING', 'OUTCOME_UNKNOWN', 'REPORTED', 'CLEARED', 'REVIEW_REQUIRED'])
def test_only_current_rejected_state_authorizes_replacement(rejected, state):
    t = rejected
    t.saved['state'] = state
    with pytest.raises(dispatch.NativeDispatchError, match='native_corrected_rejection_current_required'):
        t.prepare()
    t.build.assert_not_called()
    t.c.repository.stage_issuance.assert_not_called()


@pytest.mark.parametrize('fault', ['newer_version', 'other_attempt', 'inflight_chain', 'source_uuid',
    'source_status', 'receipt_digest', 'authentication', 'technical', 'generic400', 'permission'])
def test_replacement_needs_exact_saved_source_and_retained_400_not_a_boolean(rejected, fault):
    t = rejected
    if fault == 'newer_version':
        t.saved['record_id'] = str(uuid4())
    elif fault == 'other_attempt':
        t.saved['active_attempt'] = str(uuid4())
    elif fault == 'inflight_chain':
        t.c.chain['active_attempt'] = str(uuid4())
    elif fault == 'source_uuid':
        t.c.b.sales.custom_uuid = str(uuid4())
    elif fault == 'source_status':
        t.c.b.sales.custom_zatca_status = 'REPORTED'
    elif fault == 'receipt_digest':
        t.receipt['response_sha256'] = '0' * 64
    elif fault in ('authentication', 'technical'):
        t.receipt['http_status'] = 401 if fault == 'authentication' else 503
    elif fault == 'generic400':
        t.receipt['response_sha256'] = hashlib.sha256(b'{}').hexdigest()
        t.c.repository.open_receipt.return_value = (t.receipt, b'{}')
    else:
        t.c.b.frappe.has_permission = lambda doctype, operation, *, doc, user, raise_exception=True: operation != 'write'
    with pytest.raises(dispatch.NativeDispatchError):
        t.prepare()
    t.build.assert_not_called()
    t.c.repository.stage_issuance.assert_not_called()
    t.c.worker.commit.assert_not_called()


@pytest.mark.parametrize('clock', [datetime(2026,11,10,9,5,42,tzinfo=timezone.utc),
    datetime(2026,11,11,9,6,42,tzinfo=timezone.utc)])
def test_unchanged_clock_or_changed_reporting_transaction_date_rolls_back(rejected, clock):
    t = rejected
    t.build.side_effect = lambda source: signed_build(t.c.b, source, issue_instant=clock)
    with pytest.raises(dispatch.NativeDispatchError, match='native_corrected_'):
        t.prepare()
    t.c.repository.stage_issuance.assert_not_called()
    t.c.worker.commit.assert_not_called()


def test_normal_prepare_never_replaces_a_rejected_original(rejected):
    t = rejected
    result = dispatch.prepare_saved_invoice('Sales Invoice', 'SI', runtime=t.c.b.frappe,
        translate=lambda text: text, build=t.build)
    assert result.reused and result.record_id == t.header['record_id']
    t.build.assert_not_called()
    t.c.repository.stage_issuance.assert_not_called()
