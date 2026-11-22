"""Atomic capture/recovery on fixture-owned private SQL/files; no authority API."""

import json
import os
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_history as history, native_registration as registration
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher
from zatca_erpgulf.zatca_erpgulf.legacy_history_capture import HistoryCaptureStore
from zatca_erpgulf.zatca_erpgulf.tests.test_native_legacy_history_mariadb import linked_files
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned temporary SQL/files only')


@pytest.fixture
def capturing(legacy, monkeypatch):
    t = legacy; files, checksum = linked_files(t)
    initial = t.review(expected_xml_sha256=checksum)
    monkeypatch.setattr(history, 'MAX_PAGE_SOURCES', 2)
    def capture(after='0'):
        return t.review(expected_xml_sha256=checksum, history_review_id=initial.record_id,
            history_page_after=after, history_capture=True)
    t.capture = capture; t.review_id = initial.record_id; t.history_files = files
    t.capture_checksum = checksum
    t.pages = lambda: t.database.sql('SELECT * FROM `tabZATCA Legacy History Page` WHERE review_id=%s ORDER BY page_number',
        (initial.record_id,), as_dict=True)
    return t


@pytest.mark.parametrize('legacy', [('company', 0, '3'), ('device', 2, '3'), ('linked', 1, '3')], indirect=True)
def test_two_pages_commit_exact_custody_and_current_head_once_without_counter_or_invoice_writes(capturing, monkeypatch):
    t = capturing; first = t.capture(); second = t.capture(first.history_page.next_after_icv)
    assert not first.capture.reused and not second.capture.reused and t.database.commits == 3
    assert second.capture.current_cursor == '3' and second.capture.head_page_number == 2
    assert second.capture.captured_sources == '3' and second.capture.unresolved_sources == '0'
    assert len(t.pages()) == 2
    for row in t.pages():
        assert 'Invoice' not in row['page_ciphertext'] and 'PRIVATE-FILE' not in row['access_ciphertext']
    for file in t.history_files: file['path'].write_bytes(b'CHANGED CURRENT FILE; SAVED COPY MUST SURVIVE')
    monkeypatch.setattr(history, '_older_xml', Mock(side_effect=AssertionError('No regeneration on retained retry')))
    replay = t.capture()
    assert replay.capture.reused and replay.capture.record_id == first.capture.record_id
    assert replay.capture.current_cursor == '3' and t.database.commits == 3 and len(t.pages()) == 2
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '3'
    t.source.save.assert_not_called(); t.source.db_set.assert_not_called(); t.b.request.assert_not_called()


def test_skipping_a_capture_position_cannot_create_a_disconnected_page(capturing):
    t = capturing
    with pytest.raises(registration.ChainRegistrationError, match='registration_capture_cursor'): t.capture('2')
    assert not t.pages() and t.database.commits == 1


def test_lost_commit_acknowledgment_recovers_same_captured_bytes_and_head(capturing, monkeypatch):
    t = capturing; commit = t.database.commit
    def lost(): commit(); raise RuntimeError('PRIVATE COMMIT ACK')
    monkeypatch.setattr(t.database, 'commit', lost)
    with pytest.raises(registration.ChainRegistrationError) as failed: t.capture()
    assert failed.value.commit_uncertain and 'PRIVATE' not in str(failed.value)
    monkeypatch.setattr(t.database, 'commit', commit)
    original = t.pages()[0]
    replay = t.capture()
    assert replay.capture.reused and replay.capture.record_id == original['record_id']
    assert len(t.pages()) == 1 and t.pages()[0]['page_ciphertext'] == original['page_ciphertext']
    assert t.database.commits == 2


@pytest.mark.parametrize('target', ['source', 'file'])
def test_current_read_denial_precedes_large_xml_decryption_on_retained_replay(capturing, monkeypatch, target):
    t = capturing; t.capture(); kinds = []; original = DispatchRecordCipher.open
    def opening(cipher, identifier, kind, header, body):
        kinds.append(kind); return original(cipher, identifier, kind, header, body)
    monkeypatch.setattr(DispatchRecordCipher, 'open', opening)
    denied = t.history_files[0]['source' if target == 'source' else 'file']
    t.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: doc.name != denied
    with pytest.raises(registration.ChainRegistrationError, match='registration_capture_read_permission'): t.capture()
    assert 'legacy-history-access' in kinds and 'legacy-history-page' not in kinds
    assert t.database.commits == 2


@pytest.mark.parametrize('fault', ['index', 'page-header', 'page-body', 'purpose', 'head-body', 'missing-page', 'orphan'])
def test_tampered_or_orphaned_custody_never_repairs_or_replaces_progress(capturing, fault):
    t = capturing; t.capture(); row = t.pages()[0]
    with t.connection.cursor() as cursor:
        if fault == 'index': cursor.execute('UPDATE `tabZATCA Legacy History Page` SET through_icv=%s WHERE name=%s', ('999', row['name']))
        elif fault == 'page-header':
            value = json.loads(row['header']); value['payload_sha256'] = '0'*64
            cursor.execute('UPDATE `tabZATCA Legacy History Page` SET header=%s WHERE name=%s',
                (json.dumps(value, sort_keys=True, separators=(',', ':')), row['name']))
        elif fault == 'page-body': cursor.execute('UPDATE `tabZATCA Legacy History Page` SET page_ciphertext=%s WHERE name=%s', ('v1.INVALID', row['name']))
        elif fault == 'purpose': cursor.execute('UPDATE `tabZATCA Legacy History Page` SET access_ciphertext=page_ciphertext WHERE name=%s', (row['name'],))
        elif fault == 'head-body': cursor.execute('UPDATE `tabZATCA Issuing Chain` SET legacy_history_ciphertext=%s WHERE name=%s', ('v1.INVALID', t.review_id))
        elif fault == 'missing-page': cursor.execute('DELETE FROM `tabZATCA Legacy History Page` WHERE name=%s', (row['name'],))
        else: cursor.execute('UPDATE `tabZATCA Issuing Chain` SET legacy_history_header=NULL,legacy_history_ciphertext=NULL WHERE name=%s', (t.review_id,))
    t.connection.commit()
    with pytest.raises(registration.ChainRegistrationError): t.capture()
    assert t.database.commits == 2
    t.b.request.assert_not_called()


def test_failed_head_compare_rolls_back_new_page_and_does_not_leave_an_orphan(capturing, monkeypatch):
    t = capturing; sql = t.database.sql
    def changed(statement, values=(), **kwargs):
        result = sql(statement, values, **kwargs)
        return [{'changed': 0}] if statement == 'SELECT ROW_COUNT() AS changed' else result
    monkeypatch.setattr(t.database, 'sql', changed)
    with pytest.raises(registration.ChainRegistrationError, match='registration_capture_head_compare'): t.capture()
    assert not t.pages() and t.database.commits == 1


def test_capture_requires_an_explicit_boolean_paged_operation(legacy):
    with pytest.raises(registration.ChainRegistrationError, match='registration_history_capture_operation'):
        legacy.review(history_capture=True)
    with pytest.raises(registration.ChainRegistrationError, match='registration_history_capture_operation'):
        legacy.review(history_capture='1')
    assert legacy.database.commits == 0


def test_unresolved_evidence_is_retained_and_counted_without_becoming_acceptance(capturing):
    t = capturing; t.history_files[0]['path'].unlink()
    first = t.capture(); second = t.capture(first.history_page.next_after_icv)
    assert second.capture.captured_sources == '3' and second.capture.unresolved_sources == '1'
    assert not second.active and second.history_page.remaining_sources == 0
    assert not hasattr(second.capture, 'accepted') and not hasattr(second.capture, 'complete')
    assert len(t.pages()) == 2


@pytest.mark.parametrize('fault', ['changed', 'missing'])
def test_continuation_cannot_substitute_a_changed_or_missing_captured_boundary(capturing, fault):
    t = capturing; first = t.capture()
    boundary = t.history_files[1]
    if fault == 'changed': boundary['path'].write_bytes(boundary['content']+b'\n')
    else: boundary['path'].unlink()
    with pytest.raises(registration.ChainRegistrationError, match='registration_capture_boundary_changed'):
        t.capture(first.history_page.next_after_icv)
    assert len(t.pages()) == 1 and t.database.commits == 2


def test_changed_census_holds_progress_instead_of_silently_adopting_new_slots(capturing):
    t = capturing; first = t.capture()
    with t.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tabPOS Invoice` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
            'custom_zatca_issuing_unit) VALUES (%s,%s,1,%s,%s,%s)',
            ('LATER-'+str(uuid4()), t.source.company, str(uuid4()), '5', t.source.custom_zatca_issuing_unit))
    t.connection.commit()
    with pytest.raises(registration.ChainRegistrationError, match='registration_capture_census_changed'):
        t.capture(first.history_page.next_after_icv)
    assert len(t.pages()) == 1 and t.database.commits == 2


def test_fixed_historical_file_needs_a_fresh_explicit_review_and_retains_the_old_capture(capturing):
    t = capturing; boundary = t.history_files[1]; boundary['path'].unlink()
    first = t.capture(); old = t.pages()[0].copy()
    boundary['path'].write_bytes(boundary['content'])
    with pytest.raises(registration.ChainRegistrationError, match='registration_capture_boundary_changed'):
        t.capture(first.history_page.next_after_icv)
    reason = 'Fresh explicit review after correcting the missing historical file'
    fresh = t.review(expected_xml_sha256=t.capture_checksum, reason=reason, supersedes_review_id=t.review_id)
    replacement = t.review(expected_xml_sha256=t.capture_checksum, reason=reason, history_review_id=fresh.record_id,
        history_page_after='0', history_capture=True)
    assert not replacement.capture.reused and replacement.capture.unresolved_sources == '0'
    assert replacement.record_id != t.review_id and t.pages()[0]['page_ciphertext'] == old['page_ciphertext']
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == t.counter.last_issued_icv


@pytest.mark.parametrize('column', ['legacy_history_header', 'legacy_history_ciphertext'])
def test_oversized_head_is_bounded_by_sql_before_parsing_or_decryption(capturing, monkeypatch, column):
    t = capturing; t.capture()
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET `'+column+'`=%s WHERE name=%s', ('x'*100000, t.review_id))
    t.connection.commit()
    original = HistoryCaptureStore.sql; observed = []
    def bounded(store, statement, values=()):
        rows = original(store, statement, values)
        if statement.startswith('SELECT SUBSTRING(legacy_history_header'):
            observed.append(True)
            assert rows[0]['header'] is None or len(rows[0]['header']) <= 32769
            assert rows[0]['ciphertext'] is None or len(rows[0]['ciphertext']) <= 513
        return rows
    monkeypatch.setattr(HistoryCaptureStore, 'sql', bounded)
    with pytest.raises(registration.ChainRegistrationError): t.capture()
    assert observed and t.database.commits == 2
