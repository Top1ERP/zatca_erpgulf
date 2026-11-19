"""Accepted bookkeeping projection; real SQL coverage is in the private pipeline."""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_projection as projection
from zatca_erpgulf.zatca_erpgulf import native_dispatch as dispatch
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import (
    coordinator, retained_reader, boundary, materials,
)


@pytest.fixture
def target(coordinator, monkeypatch):
    c = coordinator
    _xml, saved, receipt = retained_reader(c)
    original_receipt, raw = c.repository.open_receipt.return_value
    raw = b' \n' + raw + b'\n '
    receipt['response_sha256'] = hashlib.sha256(raw).hexdigest()
    c.repository.open_receipt.return_value = (original_receipt, raw)
    c.repository.lock_chain_reference = Mock(return_value=c.chain)
    c.repository.lock_issuance = Mock(return_value=saved)
    c.repository.latest_issuance.return_value = saved
    c.worker.require_owner = lambda: None
    writes = []
    def sql(statement, values=(), **kwargs):
        if 'information_schema.columns' in statement:
            return [dict(fieldname=name, kind='longtext', max_chars=16000000, max_bytes=16000000)
                for name in ('custom_zatca_status', 'custom_zatca_full_response')]
        if statement.startswith('UPDATE'):
            writes.append((statement, values))
            c.b.sales.custom_zatca_status, c.b.sales.custom_zatca_full_response = values[:2]
        return [{'changed': 1}]
    c.worker.database.sql.side_effect = sql
    monkeypatch.setattr(projection, 'owned_worker_transaction', dispatch.owned_worker_transaction)
    monkeypatch.setattr(projection, 'DispatchStore', c.factory)
    return SimpleNamespace(c=c, saved=saved, receipt=receipt, body=raw, writes=writes)


def test_projection_preserves_raw_response_and_updates_only_status_fields(target):
    t = target
    t.c.b.company.custom_private_key = 'INVALID-NOT-REQUIRED'
    t.c.b.company.custom_phase_1_or_2 = 'Phase-1'
    result = projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe)
    assert result.updated and result.projected and result.status == 'REPORTED'
    assert t.c.b.sales.custom_zatca_full_response.encode() == t.body
    assert len(t.writes) == 1
    statement, values = t.writes[0]
    assert statement.startswith('UPDATE `tabSales Invoice` SET custom_zatca_status=')
    assert values[0] == 'REPORTED' and values[1].encode() == t.body
    assert 'custom_pih' not in statement and 'grand_total' not in statement and 'modified=' not in statement
    t.c.worker.commit.assert_called_once()
    t.c.b.request.assert_not_called()


def test_repeated_projection_is_a_read_only_noop(target):
    t = target
    projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe)
    second = projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe)
    assert second.projected and not second.updated
    assert len(t.writes) == 1 and t.c.worker.commit.call_count == 1


@pytest.mark.parametrize('state', ['PREPARED', 'DISPATCHING', 'OUTCOME_UNKNOWN', 'REJECTED', 'REVIEW_REQUIRED'])
def test_unaccepted_state_never_downgrades_or_claims_source_acceptance(target, state):
    t = target
    t.saved['state'] = state
    t.c.b.sales.custom_zatca_status = 'CLEARED'
    result = projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe)
    assert not result.projected and not result.updated
    assert t.c.b.sales.custom_zatca_status == 'CLEARED' and not t.writes
    t.c.repository.open_receipt.assert_not_called()


@pytest.mark.parametrize('skip', [False, True])
def test_readonly_viewer_cannot_project_but_cached_path_can_skip_quietly(target, skip):
    t = target
    t.c.b.frappe.has_permission = lambda doctype, operation, *, doc, user, raise_exception=True: operation == 'read'
    if skip:
        result = projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe, skip_if_readonly=True)
        assert result.skipped_readonly and not result.projected
    else:
        with pytest.raises(dispatch.NativeDispatchError) as caught:
            projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe)
        assert caught.value.code == 'native_source_permission'
    t.c.factory.assert_not_called()
    assert not t.writes


@pytest.mark.parametrize('fault', ['historical', 'body', 'identity', 'status'])
def test_inconsistent_identity_or_receipt_stops_before_source_update(target, fault):
    t = target
    if fault == 'historical':
        t.c.repository.latest_issuance.return_value = {'record_id': 'NEWER'}
    elif fault == 'body':
        t.receipt['response_sha256'] = '0' * 64
    elif fault == 'identity':
        t.c.b.sales.docstatus = 2
    elif fault == 'status':
        t.c.b.sales.custom_zatca_status = 'CLEARED'
    with pytest.raises(dispatch.NativeDispatchError):
        projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe)
    assert not t.writes
    t.c.worker.commit.assert_not_called()


@pytest.mark.parametrize('readonly',[False,True])
def test_expected_version_is_not_skipped_for_write_or_readonly_cached_viewers(target,readonly):
    t=target
    if readonly:
        t.c.b.frappe.has_permission=lambda dt,op,*,doc,user,raise_exception=True:op=='read'
    with pytest.raises(dispatch.NativeDispatchError,match='native_expected_issuance_changed'):
        projection.project_accepted_status('Sales Invoice','SI',runtime=t.c.b.frappe,
            skip_if_readonly=readonly,expected_issuance_id='DIFFERENT')
    assert not t.writes
    t.c.worker.commit.assert_not_called()


@pytest.mark.parametrize('fault', ['missing', 'short_chars', 'short_bytes', 'numeric'])
def test_source_storage_capacity_is_checked_without_truncation(target, fault):
    t = target
    rows = [dict(fieldname=name, kind='longtext', max_chars=16000000, max_bytes=16000000)
        for name in ('custom_zatca_status', 'custom_zatca_full_response')]
    if fault == 'missing':
        rows.pop()
    elif fault == 'short_chars':
        rows[1]['max_chars'] = 1
    elif fault == 'short_bytes':
        rows[1]['max_bytes'] = 1
    elif fault == 'numeric':
        rows[1]['kind'] = 'float'
    t.c.worker.database.sql.side_effect = None
    t.c.worker.database.sql.return_value = rows
    with pytest.raises(dispatch.NativeDispatchError):
        projection.project_accepted_status('Sales Invoice', 'SI', runtime=t.c.b.frappe)
    t.c.worker.commit.assert_not_called()
