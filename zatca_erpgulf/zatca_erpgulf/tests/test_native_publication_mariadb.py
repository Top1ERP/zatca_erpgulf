"""Read-only print/download adoption over private SQL with mocked dispatch.

Registration is preseeded; a synthetic metadata/signing builder supplies UBL.
No installed ERP, real invoice, tax service, print engine or CA/SDK is involved.
"""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import native_publication as publication
from zatca_erpgulf.zatca_erpgulf import native_dispatch, native_artifact
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider_mariadb import (
    case, boundary, materials, isolated_server, connections, tables,
)


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Owned private SQL opt-in only')


@pytest.mark.parametrize('case', [(n, kind, mode, simplified)
    for n in range(6) for kind in ('company', 'device', 'linked')
    if not (n in (2, 4) and kind == 'company')
    # Four secondary generators are Simplified-only reporting adapters.
    for mode, simplified in (('Batches', True), ('Live', True), ('Live', False))
    if simplified or n in (0, 1)], indirect=True)
def test_all_entries_publish_current_custody_without_writes_new_files_or_another_request(case, monkeypatch):
    c = case
    result = c.run()
    assert result['status'] in ('SUCCESS', 'PREPARED')
    monkeypatch.setattr(publication, 'frappe', c.runtime)
    monkeypatch.setattr(publication, '_', lambda text: text)
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    c.selected.custom_private_key = 'INVALID-MUST-NOT-BE-PARSED'
    c.runtime.conf['zatca_native_dispatch'] = 0
    before = (c.head(), c.database.commits, len(c.sent), len(c.built))
    saved = c.runtime.get_doc(c.source.doctype, c.source.name)
    original = native_dispatch.read_retained_invoice(saved.doctype, saved.name, runtime=c.runtime)
    artifact = native_artifact.read_native_artifact(saved.doctype, saved.name, runtime=c.runtime)
    preview = publication.preview_result(saved.doctype, saved.name, runtime=c.runtime, translate=lambda s: s)
    assert preview['status'] == 'READY' and preview['accepted'] == result['accepted']
    response = publication.xml_response(saved.doctype, saved.name, original.issuance_id,
        runtime=c.runtime, translate=lambda s: s)
    assert response.get_data() == artifact.xml_bytes
    diagnostic = publication.xml_response(saved.doctype, saved.name, original.issuance_id,
        original=True, runtime=c.runtime, translate=lambda s: s)
    assert diagnostic.get_data() == original.original_xml
    saved.custom_zatca_status = 'FORGED-PRINT-STATUS'
    publication.before_print(saved, 'before_print', {})
    assert saved.ksa_einv_qr == preview['qr_data_uri']
    assert saved.custom_zatca_status == (original.state if original.accepted else 'Not Submitted')
    assert (c.head(), c.database.commits, len(c.sent), len(c.built)) == before
    unchanged = c.runtime.get_doc(saved.doctype, saved.name)
    assert unchanged.get('ksa_einv_qr') is None and unchanged.custom_zatca_status != 'FORGED-PRINT-STATUS'
    assert c.database.sql('SELECT COUNT(*) AS total FROM `tabFile`', as_dict=True)[0]['total'] == 0
    assert c.database.transaction_writes == 0
    c.b.request.assert_not_called()


def test_current_source_shared_lock_blocks_a_concurrent_change_and_never_repairs_history(case, monkeypatch):
    c = case
    result = c.run()
    assert result['accepted']
    other = c.connections()
    with other.cursor() as cursor:
        cursor.execute('UPDATE `tab'+c.source.doctype+'` SET docstatus=2 WHERE name=%s', (c.source.name,))
    before = (c.head(), len(c.sent), len(c.built))
    preview = publication.preview_result(c.source.doctype, c.source.name, runtime=c.runtime, translate=lambda s: s)
    assert preview['status'] == 'REVIEW' and 'qr_data_uri' not in preview
    other.commit()
    with pytest.raises(native_dispatch.NativeDispatchError, match='native_publication_source_review'):
        publication.load_publication(c.source.doctype, c.source.name, runtime=c.runtime)
    retained = native_dispatch.read_retained_invoice(c.source.doctype, c.source.name, runtime=c.runtime)
    assert retained.accepted
    assert (c.head(), len(c.sent), len(c.built)) == before
