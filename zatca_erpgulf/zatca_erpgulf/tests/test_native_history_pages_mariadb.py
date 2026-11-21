"""Review-pinned page reads; no new records, queues, counters or transport."""

import os
import pickle
from uuid import uuid4

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_history as history, native_registration as registration
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.tests.test_native_legacy_history_mariadb import linked_files, digest
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned private SQL/files only')


def setup_page(t, monkeypatch):
    files, checksum = linked_files(t)
    initial = t.review(expected_xml_sha256=checksum)
    monkeypatch.setattr(history, 'MAX_PAGE_SOURCES', 2)
    def page(after='0', **overrides):
        options = dict(expected_xml_sha256=checksum, history_review_id=initial.record_id, history_page_after=after)
        options.update(overrides)
        before = t.database.commits
        result = t.review(**options)
        assert result.reused and not result.active and result.record_id == initial.record_id
        assert result.history is None and result.history_page.review_id == initial.record_id
        assert t.database.commits == before
        t.b.request.assert_not_called()
        return result.history_page
    return files, initial, page


@pytest.mark.parametrize('legacy', [('company', 0, '3'), ('device', 2, '3'), ('linked', 1, '3')], indirect=True)
def test_saved_review_pages_resume_across_sales_pos_without_any_write_or_implicit_completion(legacy, monkeypatch):
    t = legacy; files, initial, page = setup_page(t, monkeypatch)
    first = page(); second = page(first.next_after_icv)
    assert first.through_icv == '2' and first.remaining_sources == 1 and first.inventory.matched_links == 1
    assert second.through_icv == '3' and second.remaining_sources == 0 and second.next_after_icv is None
    assert second.inventory.matched_links == 1 and not second.inventory.source_scan_complete
    assert second.inventory.xml_bytes == len(files[1]['content'])  # Boundary reread, no anchor reread.
    assert first == page() and t.database.commits == 1
    with pytest.raises(TypeError): pickle.dumps(first)
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '3'


@pytest.mark.parametrize('legacy', [('company', 0, '3')], indirect=True)
@pytest.mark.parametrize('fault', ['wrong-review', 'missing-review', 'missing-cursor', 'supersedes', 'range', 'shape',
    'reason', 'role', 'gap'])
def test_page_cannot_bootstrap_replace_rebind_or_silently_skip_a_missing_cursor(legacy, monkeypatch, fault):
    t = legacy; files, initial, page = setup_page(t, monkeypatch); overrides = {}; after = '0'
    if fault == 'wrong-review': overrides['history_review_id'] = str(uuid4())
    elif fault == 'missing-review': overrides['history_review_id'] = None
    elif fault == 'missing-cursor': after = None
    elif fault == 'supersedes': overrides['supersedes_review_id'] = initial.record_id
    elif fault == 'range': after = '4'
    elif fault == 'shape': after = '01'
    elif fault == 'reason': overrides['reason'] = 'Changed reviewed reason'
    elif fault == 'role': t.runtime.get_roles = lambda actor: ['Accounts User']
    else:
        after = '2'
        with t.connection.cursor() as cursor:
            cursor.execute('DELETE FROM `tabPOS Invoice` WHERE name=%s', (files[1]['source'],))
        t.connection.commit()
    with pytest.raises(registration.ChainRegistrationError): page(after, **overrides)
    assert t.database.commits == 1


@pytest.mark.parametrize('legacy', [('company', 0, '3')], indirect=True)
@pytest.mark.parametrize('fault', ['changed-boundary', 'denied-boundary', 'byte-limit'])
def test_resumed_boundary_is_fresh_permission_checked_and_never_fabricated(legacy, monkeypatch, fault):
    t = legacy; files, initial, page = setup_page(t, monkeypatch); first = page()
    if fault == 'changed-boundary':
        root = etree.fromstring(files[1]['content'])
        root.find('.//ds:Reference[@Id="invoiceSignedData"]/ds:DigestValue', NS).text = digest(999)
        files[1]['path'].write_bytes(etree.tostring(root))
    elif fault == 'denied-boundary':
        t.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: doc.name != files[1]['file']
    else: monkeypatch.setattr(history, 'MAX_XML_BYTES', 1)
    result = page(first.next_after_icv)
    if fault == 'changed-boundary': assert result.inventory.broken_links == 1
    else:
        assert result.boundary_unresolved and result.inventory.matched_links == 0
        if fault == 'byte-limit':
            assert result.through_icv == '2' and result.next_after_icv is None and result.remaining_sources == 1


@pytest.mark.parametrize('legacy', [('company', 0, '100')], indirect=True)
def test_real_page_limit_advances_over_large_unresolved_history_without_rescanning_all_old_files(legacy):
    t = legacy
    with t.connection.cursor() as cursor:
        for index in range(1, 81):
            doctype = 'Sales Invoice' if index % 2 else 'POS Invoice'
            cursor.execute('INSERT INTO `tab'+doctype+'` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
                'custom_zatca_issuing_unit) VALUES (%s,%s,1,%s,%s,%s)',
                ('PAGE-'+str(uuid4()), t.source.company, str(uuid4()), str(index), t.source.custom_zatca_issuing_unit))
    t.connection.commit()
    initial = t.review()
    first = t.review(history_review_id=initial.record_id, history_page_after='0').history_page
    assert first.through_icv == '64' and first.next_after_icv == '64' and first.remaining_sources == 17
    assert first.inventory.unresolved_sources == 64 and first.inventory.missing_positions == '19'
    second = t.review(history_review_id=initial.record_id, history_page_after='64').history_page
    assert second.through_icv == '100' and second.next_after_icv is None and second.remaining_sources == 0
    assert second.boundary_unresolved and second.inventory.unresolved_sources == 17
    assert not second.inventory.source_scan_complete and t.database.commits == 1
    t.b.request.assert_not_called()


def test_page_requires_an_existing_saved_review_and_cannot_create_one(legacy):
    t = legacy
    with pytest.raises(registration.ChainRegistrationError, match='registration_history_review_changed'):
        t.review(history_review_id=str(uuid4()), history_page_after='0')
    assert t.database.commits == 0
    t.b.request.assert_not_called()
