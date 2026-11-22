"""Checkpoint/chain arithmetic over explicit doubles, not installed/SDK proof."""

from types import SimpleNamespace
from datetime import datetime

import pytest

from zatca_erpgulf.zatca_erpgulf import legacy_history_audit as audit, native_legacy_history as history
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher, encode_record_header
from zatca_erpgulf.zatca_erpgulf.legacy_history_capture import _sha
from zatca_erpgulf.zatca_erpgulf.legacy_history_capture_codec import CaptureContents
from zatca_erpgulf.zatca_erpgulf.tests.test_native_legacy_history import records


REVIEW = '10000000-0000-4000-8000-000000000001'
ONE = '20000000-0000-4000-8000-000000000001'
TWO = '20000000-0000-4000-8000-000000000002'


@pytest.fixture
def ledger(monkeypatch):
    rows, evidence = records()
    for row in rows:
        row.update(company='COMPANY', docstatus=1, custom_uuid=REVIEW, unit='UNIT')
    lookup = {str(value[0].icv).encode(): value for value in evidence.values()}
    monkeypatch.setattr(audit, 'inspect_invoice_artifact', lambda content: lookup[content][0])
    monkeypatch.setattr(audit, 'inspect_embedded_certificate', lambda content: SimpleNamespace(public_key_sha256=lookup[content][1]))
    monkeypatch.setattr(history, '_count_slots', lambda owner, unit: 3)
    def contents(indices, after, through, remaining):
        selected = [rows[index-1] for index in indices]
        observed = {(row['doctype'], row['name']): evidence[row['doctype'], row['name']] for row in selected}
        inv = history.summarize_history(selected, observed, complete=False, attempted=set(observed), tail_icv='3',
            tail_digest='HASH-3', public_key='KEY', xml_bytes=0, known_positions=3)
        page = history.LegacyHistoryPage(REVIEW, after, through, through if remaining else None, remaining, False, inv)
        return CaptureContents(page, tuple(dict(source=row, boundary=row['icv']==after, observed=True,
            files=[dict(file_id='FILE-'+row['icv'], xml=row['icv'].encode())]) for row in selected))
    h1 = dict(page_number=1, after_icv='0', through_icv='2', captured_sources='2', unresolved_sources='0',
        known_positions='3', previous_page=None, previous_sha256='0'*64)
    h2 = dict(page_number=2, after_icv='2', through_icv='3', captured_sources='3', unresolved_sources='0',
        known_positions='3', previous_page=ONE, previous_sha256=_sha(encode_record_header(h1)))
    pages = {ONE: [h1, contents((1, 2), '0', '2', 1)], TWO: [h2, contents((2, 3), '2', '3', 0)]}
    head = dict(review_id=REVIEW, review_sha256='a'*64, last_page=TWO, last_page_sha256=_sha(encode_record_header(h2)),
        page_number=2, through_icv='3', known_positions='3', captured_sources='3', unresolved_sources='0')
    stored = dict(header=None, ciphertext=None)
    writes, opened = [], []
    def sql(statement, values=()):
        if statement.startswith('SELECT COUNT(*) AS pages'): return [{'pages': len(pages)}]
        if 'information_schema.columns' in statement: return [{'data_type':'longtext'}]*2
        if statement.startswith('SELECT SUBSTRING(legacy_audit_header'): return [stored.copy()]
        if statement.startswith('UPDATE `tabZATCA Issuing Chain`'):
            stored.update(header=values[0], ciphertext=values[1]); writes.append(values); return []
        assert statement == 'SELECT ROW_COUNT() AS changed'
        return [{'changed': 1}]
    def row(column, identifier):
        return None if identifier not in pages else (pages[identifier][0], encode_record_header(pages[identifier][0]), {})
    def opening(identifier, *, with_size=False):
        opened.append(identifier); pair = pages[identifier]
        return (*pair, 100) if with_size else tuple(pair)
    def fail(code): raise ChainRegistrationError('registration_capture_'+code)
    owner = SimpleNamespace(cipher=DispatchRecordCipher(b'T'*32, site='fictional.invalid', storage_namespace=REVIEW),
        actor='OPERATOR', utc_now=lambda: datetime(2026,11,22,10))
    store = SimpleNamespace(head=head, owner=owner, review_id=REVIEW, review_sha='a'*64,
        before=dict(header='CAPTURE-HEAD',ciphertext='CAPTURE-CIPHER'),
        review=dict(icv='3', invoice_hash='HASH-3', public_key_sha256='KEY', source_unit='UNIT',owner_key='c'*64),
        sql=sql, row=row, opened=opening, fail=fail)
    return SimpleNamespace(store=store, pages=pages, stored=stored, writes=writes, opened=opened)


def test_whole_walk_and_completed_replay_keep_their_snapshot_meaning(ledger):
    c = ledger; result = audit.audit_capture(c.store)
    assert result.traversal_complete and result.capture_exhausted
    assert result.checked_pages == '2' and result.checked_sources == '3' and result.remaining_pages == 0
    assert result.missing_positions == result.unresolved_sources == result.broken_links == result.rotated_sources == '0'
    assert result.genesis_match is True and c.opened == [TWO, ONE]
    assert not hasattr(result, 'accepted') and not hasattr(result, 'active')
    replay = audit.audit_capture(c.store)
    assert replay.reused and replay.audit_id == result.audit_id and len(c.writes) == 1


def test_checkpoint_resumes_backwards_and_counts_each_boundary_once(ledger, monkeypatch):
    c = ledger; monkeypatch.setattr(audit, 'MAX_AUDIT_PAGES', 1)
    first = audit.audit_capture(c.store)
    assert not first.traversal_complete and first.checked_sources == '1' and first.remaining_pages == 1
    second = audit.audit_capture(c.store)
    assert second.traversal_complete and second.checked_sources == '3' and second.audit_id == first.audit_id
    assert c.opened == [TWO, ONE] and len(c.writes) == 2


def test_payload_budget_reserves_room_before_opening_the_next_page(ledger, monkeypatch):
    c = ledger
    monkeypatch.setattr(audit, 'MAX_AUDIT_BYTES', audit.MAX_PAYLOAD_BYTES)
    first = audit.audit_capture(c.store)
    assert not first.traversal_complete and first.remaining_pages == 1
    assert c.opened == [TWO]
    second = audit.audit_capture(c.store)
    assert second.traversal_complete and second.audit_id == first.audit_id
    assert c.opened == [TWO, ONE]


@pytest.mark.parametrize('fault', ['missing-prefix', 'header-sha', 'number', 'cumulative', 'extra-row'])
def test_corrupt_or_unreachable_pages_cannot_complete_the_audit(ledger, fault):
    c = ledger
    if fault == 'missing-prefix': del c.pages[ONE]
    elif fault == 'extra-row': c.pages['EXTRA'] = c.pages[ONE]
    else:
        field = {'header-sha':'previous_sha256', 'number':'page_number', 'cumulative':'captured_sources'}[fault]
        c.pages[TWO][0][field] = 'b'*64 if fault == 'header-sha' else 1 if fault == 'number' else '99'
    with pytest.raises(ChainRegistrationError): audit.audit_capture(c.store)
    assert not c.writes


def test_changed_head_requires_explicit_restart_of_the_checkpoint(ledger, monkeypatch):
    c = ledger; monkeypatch.setattr(audit, 'MAX_AUDIT_PAGES', 1)
    old = audit.audit_capture(c.store)
    c.store.head['review_sha256'] = 'b'*64  # Changes the pinned capture-head digest.
    with pytest.raises(ChainRegistrationError, match='audit_head_changed'): audit.audit_capture(c.store)
    fresh = audit.audit_capture(c.store, restart=True)
    assert fresh.audit_id != old.audit_id and fresh.checked_sources == '1'
