"""Full captured-ledger checkpoint/coverage on fixture-owned private SQL only."""

import os
from unittest.mock import Mock
from uuid import uuid4

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import legacy_history_audit as audit
from zatca_erpgulf.zatca_erpgulf import native_registration as registration
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.tests.test_legacy_history_capture_mariadb import capturing
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_legacy_history_mariadb import digest


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned temporary SQL/files only')


def run_audit(t, **options):
    return t.review(expected_xml_sha256=t.capture_checksum, history_review_id=t.review_id,
        history_page_after='0', history_audit=True, **options).audit


def finish_capture(t):
    first = t.capture(); t.capture(first.history_page.next_after_icv)


@pytest.mark.parametrize('legacy', [('company', 0, '3'), ('device', 2, '3'), ('linked', 1, '3')], indirect=True)
def test_full_walk_authenticates_all_pages_and_does_not_grant_activation(capturing):
    t = capturing; finish_capture(t); before = t.database.commits
    result = run_audit(t)
    assert result.traversal_complete and result.capture_exhausted and result.checked_pages == '2' and result.checked_sources == '3'
    assert result.missing_positions == result.unresolved_sources == result.broken_links == result.rotated_sources == '0'
    assert result.genesis_match is True and not hasattr(result, 'accepted')
    assert t.database.commits == before+1
    replay = run_audit(t)
    assert replay.reused and replay.audit_id == result.audit_id and t.database.commits == before+1
    assert replay.checked_at_utc == result.checked_at_utc and result.checked_at_utc
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '3'
    t.b.request.assert_not_called()


def test_segments_resume_after_a_process_stop_without_recounting_the_boundary(capturing, monkeypatch):
    t = capturing; finish_capture(t); monkeypatch.setattr(audit, 'MAX_AUDIT_PAGES', 1)
    first = run_audit(t)
    assert not first.traversal_complete and first.checked_pages == '1' and first.checked_sources == '1'
    second = run_audit(t)
    assert second.traversal_complete and second.checked_sources == '3' and second.audit_id == first.audit_id
    assert second.missing_positions == '24'  # Default anchor27; gaps remain visible.


@pytest.mark.parametrize('fault', ['missing-prefix', 'prefix-body', 'prefix-index', 'orphan'])
def test_nonlatest_corruption_or_unreferenced_rows_cannot_hide_behind_a_valid_head(capturing, fault):
    t = capturing; finish_capture(t); rows = t.pages(); prefix = rows[0]
    with t.connection.cursor() as cursor:
        if fault == 'missing-prefix': cursor.execute('DELETE FROM `tabZATCA Legacy History Page` WHERE name=%s', (prefix['name'],))
        elif fault == 'prefix-body': cursor.execute('UPDATE `tabZATCA Legacy History Page` SET page_ciphertext=%s WHERE name=%s', ('v1.INVALID', prefix['name']))
        elif fault == 'prefix-index': cursor.execute('UPDATE `tabZATCA Legacy History Page` SET page_number=999 WHERE name=%s', (prefix['name'],))
        else:
            clone = prefix.copy(); clone.update(name=str(uuid4()), record_id=str(uuid4()), page_key='f'*64)
            columns = tuple(clone)
            cursor.execute('INSERT INTO `tabZATCA Legacy History Page` ('+','.join('`'+key+'`' for key in columns)+') VALUES ('+
                ','.join('%s' for _ in columns)+')', tuple(clone[key] for key in columns))
    t.connection.commit(); before = t.database.commits
    with pytest.raises(registration.ChainRegistrationError): run_audit(t)
    assert t.database.commits == before


def test_head_extension_requires_fresh_explicit_audit_and_preserves_checkpoint_until_then(capturing, monkeypatch):
    t = capturing; first_page = t.capture(); first = run_audit(t)
    assert first.traversal_complete and not first.capture_exhausted
    t.capture(first_page.history_page.next_after_icv)
    with pytest.raises(registration.ChainRegistrationError, match='audit_head_changed'): run_audit(t)
    restarted = run_audit(t, history_audit_restart=True)
    assert restarted.audit_id != first.audit_id and restarted.traversal_complete and restarted.capture_exhausted


def test_lost_audit_commit_ack_recovers_the_saved_checkpoint_without_running_pages_again(capturing, monkeypatch):
    t = capturing; finish_capture(t); commit = t.database.commit
    def lost(): commit(); raise RuntimeError('PRIVATE AUDIT ACK')
    monkeypatch.setattr(t.database, 'commit', lost)
    with pytest.raises(registration.ChainRegistrationError) as failed: run_audit(t)
    assert failed.value.commit_uncertain and 'PRIVATE' not in str(failed.value)
    monkeypatch.setattr(t.database, 'commit', commit)
    monkeypatch.setattr(audit, '_check_page', Mock(side_effect=AssertionError('Completed checkpoint replay is a saved report')))
    assert run_audit(t).reused


@pytest.mark.parametrize('kind', ['unresolved', 'broken-pih', 'genesis'])
def test_declared_history_issues_survive_a_complete_authenticated_traversal(capturing, kind):
    t = capturing; file = t.history_files[0]
    if kind == 'unresolved': file['path'].unlink()
    else:
        file = t.history_files[1] if kind == 'broken-pih' else file
        root = etree.fromstring(file['content'])
        root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
            namespaces=NS)[0].text = digest(999)
        file['path'].write_bytes(etree.tostring(root))
    finish_capture(t); result = run_audit(t)
    assert result.traversal_complete
    if kind == 'unresolved': assert result.unresolved_sources == '1'
    elif kind == 'broken-pih': assert result.broken_links == '1'
    else: assert result.genesis_match is False


def test_failed_checkpoint_compare_does_not_claim_progress(capturing, monkeypatch):
    t = capturing; finish_capture(t); before = t.database.commits; sql = t.database.sql
    def mismatch(statement, values=(), **kwargs):
        rows = sql(statement, values, **kwargs)
        return [{'changed': 0}] if statement == 'SELECT ROW_COUNT() AS changed' else rows
    monkeypatch.setattr(t.database, 'sql', mismatch)
    with pytest.raises(registration.ChainRegistrationError, match='audit_compare'): run_audit(t)
    assert t.database.commits == before


@pytest.mark.parametrize('restart', [False, True])
def test_corrupt_checkpoint_cannot_be_silently_reset_even_by_restart(capturing, restart):
    t = capturing; finish_capture(t); run_audit(t); before = t.database.commits
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET legacy_audit_ciphertext=%s WHERE name=%s', ('v1.INVALID', t.review_id))
    t.connection.commit()
    with pytest.raises(registration.ChainRegistrationError): run_audit(t, history_audit_restart=restart)
    assert t.database.commits == before


def test_current_old_source_read_denial_stops_resume_without_losing_checkpoint(capturing, monkeypatch):
    t = capturing; finish_capture(t); monkeypatch.setattr(audit, 'MAX_AUDIT_PAGES', 1)
    first = run_audit(t); before = t.database.commits
    t.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: doc.name != t.history_files[0]['source']
    with pytest.raises(registration.ChainRegistrationError, match='read_permission'): run_audit(t)
    assert t.database.commits == before
    t.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: True
    second = run_audit(t)
    assert second.audit_id == first.audit_id and second.traversal_complete and second.checked_sources == '3'


def test_completed_snapshot_can_be_replayed_but_fresh_restart_rechecks_body_integrity(capturing):
    t = capturing; finish_capture(t); snapshot = run_audit(t)
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Legacy History Page` SET page_ciphertext=%s WHERE name=%s', ('v1.INVALID', t.pages()[0]['name']))
    t.connection.commit()
    replay = run_audit(t)
    assert replay.reused and replay.checked_at_utc == snapshot.checked_at_utc
    with pytest.raises(registration.ChainRegistrationError): run_audit(t, history_audit_restart=True)


@pytest.mark.parametrize('options', [dict(history_audit='1'), dict(history_audit_restart=True),
    dict(history_audit=True, history_capture=True), dict(history_audit=True, history_page_after='2')])
def test_audit_mode_does_not_accept_mixed_or_implicit_operations(capturing, options):
    t = capturing; finish_capture(t)
    args = dict(expected_xml_sha256=t.capture_checksum, history_review_id=t.review_id, history_page_after='0')
    args.update(options)
    with pytest.raises(registration.ChainRegistrationError, match='registration_history_audit_operation'): t.review(**args)
