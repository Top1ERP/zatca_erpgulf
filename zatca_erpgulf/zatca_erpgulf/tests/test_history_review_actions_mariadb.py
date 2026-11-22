"""Operator routes over the actual owned review/capture/audit and private SQL."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import history_review_actions as actions
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher
from zatca_erpgulf.zatca_erpgulf.worker_transaction import WorkerTransactionError
from zatca_erpgulf.zatca_erpgulf.tests.test_legacy_history_capture_mariadb import capturing
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned temporary SQL/files only')


def run(t, operation):
    return actions.run_saved_history_action(t.review_id, operation, runtime=t.runtime, translate=str)


@pytest.mark.parametrize('legacy', [('company', 0, '3'), ('device', 2, '3'), ('linked', 1, '3')], indirect=True)
def test_operator_derives_cursor_and_runs_capture_audit_replay_and_restart(capturing):
    t = capturing
    first = run(t, 'capture'); second = run(t, 'capture')
    assert first['capture']['current_cursor'] == '2' and second['capture']['current_cursor'] == '3'
    commits = t.database.commits
    exhausted = run(t, 'capture')
    assert exhausted['status'] == 'CAPTURE_EXHAUSTED' and t.database.commits == commits
    audited = run(t, 'audit')
    assert audited['audit']['traversal_complete'] and audited['audit']['missing_positions'] == '0'
    replay = run(t, 'audit')
    assert replay['audit']['reused'] and replay['audit']['audit_id'] == audited['audit']['audit_id']
    restarted = run(t, 'restart-audit')
    assert not restarted['audit']['reused'] and restarted['audit']['audit_id'] != audited['audit']['audit_id']
    assert len(t.pages()) == 2
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '3'
    assert 'PRIVATE' not in repr(audited)
    t.b.request.assert_not_called(); t.source.save.assert_not_called(); t.source.db_set.assert_not_called()


@pytest.mark.parametrize('target', ['chain', 'source', 'company', 'counter', 'file', 'owner-write', 'manager'])
def test_permissions_precede_root_xml_decryption_and_cannot_commit(capturing, monkeypatch, target):
    t = capturing
    denied = {'chain': ('ZATCA Issuing Chain', t.review_id), 'source': (t.source.doctype, t.source.name),
        'company': ('Company', t.source.company), 'counter': ('ZATCA ICV Counter', t.counter.name),
        'file': ('File', t.file_doc.name)}
    original = t.runtime.has_permission
    def allowed(dt, operation, *, doc, user, raise_exception=True):
        if target == 'owner-write' and operation == 'write': return False
        return (dt, doc.name) != denied.get(target) and original(dt, operation, doc=doc, user=user, raise_exception=raise_exception)
    t.runtime.has_permission = allowed
    if target == 'manager': t.runtime.get_roles = lambda actor: []
    opened = []; original_open = DispatchRecordCipher.open
    def opening(cipher, identifier, kind, header, body):
        opened.append(kind)
        return original_open(cipher, identifier, kind, header, body)
    monkeypatch.setattr(DispatchRecordCipher, 'open', opening)
    commits = t.database.commits
    with pytest.raises((actions.HistoryReviewActionError, ChainRegistrationError)): run(t, 'capture')
    assert t.database.commits == commits and not t.pages()
    assert 'chain-registration' not in opened and 'legacy-history-page' not in opened


def test_active_review_cannot_enter_capture_from_operator(capturing):
    t = capturing
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Issuing Chain` SET active=1 WHERE name=%s', (t.review_id,))
    t.connection.commit(); commits = t.database.commits
    with pytest.raises(actions.HistoryReviewActionError, match=actions.REVIEW): run(t, 'capture')
    assert t.database.commits == commits and not t.pages()


def test_preflight_does_not_grant_permission_after_source_access_changes(capturing, monkeypatch):
    t = capturing; preflight = actions._saved_arguments
    def changed(*args, **kwargs):
        result = preflight(*args, **kwargs)
        t.runtime.has_permission = lambda *args, **kwargs: False
        return result
    monkeypatch.setattr(actions, '_saved_arguments', changed)
    commits = t.database.commits
    with pytest.raises(ChainRegistrationError): run(t, 'capture')
    assert t.database.commits == commits and not t.pages()


@pytest.mark.parametrize('parent', ['write', 'callback'])
def test_dirty_parent_is_preserved_without_commit_or_rollback(capturing, parent):
    t = capturing; commits = t.database.commits
    if parent == 'write':
        t.database.sql('UPDATE `tabZATCA ICV Counter` SET last_issued_icv=%s WHERE name=%s', ('999', t.counter.name))
    else:
        t.database.before_commit._functions.append(lambda: None)
    with pytest.raises(WorkerTransactionError, match='parent_state'): run(t, 'capture')
    assert t.database.commits == commits
    if parent == 'write':
        assert t.database.sql('SELECT last_issued_icv FROM `tabZATCA ICV Counter` WHERE name=%s',
            (t.counter.name,), as_dict=True) == [{'last_issued_icv': '999'}]
        assert t.database.transaction_writes == 1
    else:
        assert len(t.database.before_commit._functions) == 1
