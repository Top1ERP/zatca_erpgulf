"""Unissued/queued/issued print boundary on fixture-owned Unix SQL only."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import native_publication as publication
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider_mariadb import (
    case, boundary, materials, isolated_server, connections, tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_publication_mariadb import use_native_source
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import handoff


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Owned private SQL opt-in only')


def print_held(c, monkeypatch):
    monkeypatch.setattr(publication, 'frappe', c.runtime)
    monkeypatch.setattr(publication, '_', lambda text: 'AR:' + text)
    saved = c.runtime.get_doc(c.source.doctype, c.source.name)
    saved.ksa_einv_qr = '/private/files/OLD-PHASE1.png'
    before = (c.head(), c.database.commits, c.database.transaction_writes, len(c.sent), len(c.built))
    with pytest.raises(publication.NativePublicationError) as failed:
        publication.before_print(saved)
    assert failed.value.code == 'native_publication_unissued'
    assert str(failed.value) == 'AR:' + publication.UNISSUED
    assert saved.ksa_einv_qr == '/private/files/OLD-PHASE1.png'
    assert (c.head(), c.database.commits, c.database.transaction_writes, len(c.sent), len(c.built)) == before
    c.b.request.assert_not_called()


@pytest.mark.parametrize('case', [(n, 'device', 'Live', True) for n in range(6)] +
    [(0, 'company', 'Batches', True), (1, 'linked', 'Live', False)], indirect=True)
def test_actual_entry_cannot_print_legacy_qr_before_generation_but_can_print_after_verified_custody(case, monkeypatch):
    c = case; use_native_source(c, monkeypatch)
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    print_held(c, monkeypatch)
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: True
    c.run()
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    c.company.custom_phase_1_or_2 = 'Phase-1'; c.runtime.conf['zatca_native_dispatch'] = 0
    before = (c.head(), c.database.commits, c.database.transaction_writes, len(c.sent), len(c.built))
    saved = c.runtime.get_doc(c.source.doctype, c.source.name)
    publication.before_print(saved)
    assert saved.ksa_einv_qr.startswith('data:image/png;base64,')
    assert (c.head(), c.database.commits, c.database.transaction_writes, len(c.sent), len(c.built)) == before


@pytest.mark.parametrize('case', [(0, 'company', 'Batches', True), (1, 'device', 'Live', True)], indirect=True)
def test_queued_print_does_not_finalize_commit_enqueue_or_execute_the_parent_request(handoff, monkeypatch):
    c = handoff; c.register()
    assert c.rows()[0]['state'] == 'STAGED'
    print_held(c, monkeypatch)
    assert c.rows()[0]['state'] == 'STAGED'
    c.runtime.enqueue.assert_not_called()
    c.database.commit()
    assert c.rows()[0]['state'] == 'READY'
    c.runtime.enqueue.reset_mock()
    print_held(c, monkeypatch)
    assert c.rows()[0]['state'] == 'READY'
    c.runtime.enqueue.assert_not_called()
    assert c.execute()['status'] == 'COMPLETE'
    saved = c.runtime.get_doc(c.source.doctype, c.source.name)
    publication.before_print(saved)
    assert saved.ksa_einv_qr.startswith('data:image/png;base64,')
