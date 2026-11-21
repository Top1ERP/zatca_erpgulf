"""Read-only preview classification before/after private native preparation."""

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


def preview(c):
    before = (c.head(), c.database.commits, c.database.transaction_writes, len(c.sent), len(c.built))
    result = publication.preview_result(c.source.doctype, c.source.name,
        runtime=c.runtime, translate=lambda text: 'AR:' + text)
    assert (c.head(), c.database.commits, c.database.transaction_writes, len(c.sent), len(c.built)) == before
    c.b.request.assert_not_called()
    return result


@pytest.mark.parametrize('case', [(n, 'device', 'Live', True) for n in range(6)] +
    [(0, 'company', 'Batches', True), (1, 'linked', 'Live', False)], indirect=True)
def test_actual_entry_preview_waits_for_original_then_reads_custody_without_issuing_again(case, monkeypatch):
    c = case; use_native_source(c, monkeypatch)
    saved = c.runtime.get_doc(c.source.doctype, c.source.name).as_dict()
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    assert preview(c) == {'status': 'UNISSUED', 'message': 'AR:' + publication.UNISSUED}
    assert c.runtime.get_doc(c.source.doctype, c.source.name).as_dict() == saved
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: True
    issued = c.run()
    c.company.custom_phase_1_or_2 = 'Phase-1'; c.runtime.conf['zatca_native_dispatch'] = 0
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    result = preview(c)
    assert result['status'] == 'READY' and result['accepted'] == issued['accepted']
    assert result['qr_data_uri'].startswith('data:image/png;base64,')


@pytest.mark.parametrize('case', [(0, 'company', 'Batches', True), (1, 'device', 'Live', True)], indirect=True)
def test_staged_and_ready_preview_never_finalizes_or_executes_the_saved_request(handoff):
    c = handoff; c.register()
    assert c.rows()[0]['state'] == 'STAGED'
    assert preview(c)['status'] == 'UNISSUED'
    assert c.rows()[0]['state'] == 'STAGED'
    c.runtime.enqueue.assert_not_called()
    c.database.commit()
    c.runtime.enqueue.reset_mock()
    assert c.rows()[0]['state'] == 'READY'
    assert preview(c)['status'] == 'UNISSUED'
    assert c.rows()[0]['state'] == 'READY'
    c.runtime.enqueue.assert_not_called()
    assert c.execute()['status'] == 'COMPLETE'
    assert preview(c)['status'] == 'READY'
