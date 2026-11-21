"""Actual inactive legacy review audits older attached declarations on private SQL."""

import base64
import hashlib
import os
from uuid import uuid4
from unittest.mock import Mock

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import native_legacy_history as history
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.worker_transaction import owned_worker_transaction
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned temporary SQL/files only')


def digest(index):
    return base64.b64encode(hashlib.sha256(('SYNTHETIC-'+str(index)).encode()).digest()).decode()


def linked_files(t):
    """Tampered signed inputs deliberately test declarations, never crypto proof."""
    files = []
    for index, doctype in ((1, 'Sales Invoice'), (2, 'POS Invoice')):
        identifier = str(uuid4()); name, invoice_uuid = 'OLDER-'+identifier, str(uuid4())
        root = etree.fromstring(t.xml)
        root.find('cbc:ID', NS).text = name; root.find('cbc:UUID', NS).text = invoice_uuid
        root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID", namespaces=NS)[0].text = str(index)
        root.find('.//ds:Reference[@Id="invoiceSignedData"]/ds:DigestValue', NS).text = digest(index)
        root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
            namespaces=NS)[0].text = INITIAL_PREVIOUS_HASH if index == 1 else digest(1)
        content = etree.tostring(root)
        file_id, file_name = 'OLDER-FILE-'+identifier, 'Older-'+identifier+'.xml'
        path = t.path.parent/file_name; path.write_bytes(content)
        with t.connection.cursor() as cursor:
            cursor.execute('INSERT INTO `tab'+doctype+'` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
                'custom_zatca_issuing_unit) VALUES (%s,%s,1,%s,%s,%s)',
                (name, t.source.company, invoice_uuid, str(index), t.source.custom_zatca_issuing_unit))
            cursor.execute('INSERT INTO `tabFile` (name,attached_to_doctype,attached_to_name,is_private,file_name,file_url) '
                'VALUES (%s,%s,%s,1,%s,%s)', (file_id, doctype, name, file_name, '/private/files/'+file_name))
        files.append(dict(doctype=doctype, source=name, file=file_id, path=path, content=content))
    root = etree.fromstring(t.xml)
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
        namespaces=NS)[0].text = digest(2)
    anchor = etree.tostring(root); t.path.write_bytes(anchor); t.connection.commit()
    return files, hashlib.sha256(anchor).hexdigest()


@pytest.mark.parametrize('legacy', [('company', 0, '3'), ('device', 2, '3'), ('linked', 1, '3')], indirect=True)
def test_actual_review_reports_the_full_known_cross_doctype_declared_links_but_stays_inactive(legacy):
    t = legacy; files, checksum = linked_files(t)
    reviewed = t.review(expected_xml_sha256=checksum); result = reviewed.history
    assert not reviewed.active and result.source_scan_complete and result.missing_positions == '0'
    assert result.inspected_sources == 3 and result.unresolved_sources == result.unprobed_sources == 0
    assert result.matched_links == 2 and result.broken_links == 0 and result.genesis_match is True and result.tail_match is True
    assert result.rotated_key_sources == 0 and result.xml_bytes == sum(len(file['content']) for file in files)
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '3'
    assert t.database.commits == 1
    again = t.review(expected_xml_sha256=checksum)
    assert again.reused and again.history == result and t.database.commits == 1
    t.b.request.assert_not_called()


@pytest.mark.parametrize('legacy', [('company', 0, '3')], indirect=True)
@pytest.mark.parametrize('fault', ['missing', 'invalid', 'wrong-uuid', 'wrong-pih', 'broken-link', 'denied-source', 'denied-file',
    'conflicting-copy', 'byte-limit', 'cumulative-limit', 'source-limit', 'rotated-key'])
def test_missing_conflicting_rotated_or_limited_evidence_is_visible_without_repair_or_activation(legacy, monkeypatch, fault):
    t = legacy; files, checksum = linked_files(t); older = files[1] if fault == 'broken-link' else files[0]
    if fault == 'missing': older['path'].unlink()
    elif fault == 'invalid': older['path'].write_bytes(b'INVALID PRIVATE XML')
    elif fault in ('wrong-uuid', 'wrong-pih', 'broken-link', 'rotated-key'):
        root = etree.fromstring(older['content'])
        if fault == 'wrong-uuid': root.find('cbc:UUID', NS).text = str(uuid4())
        elif fault == 'rotated-key': root.find('.//ds:X509Certificate', NS).text = t.materials[1].text
        else:
            root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
                namespaces=NS)[0].text = digest(999)
        older['path'].write_bytes(etree.tostring(root))
    elif fault.startswith('denied'):
        denied = older['source'] if fault == 'denied-source' else older['file']
        t.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: doc.name != denied
    elif fault == 'byte-limit': monkeypatch.setattr(history, 'MAX_XML_BYTES', 1)
    elif fault == 'cumulative-limit': monkeypatch.setattr(history, 'MAX_XML_BYTES', len(files[0]['content'])+1)
    elif fault == 'source-limit': monkeypatch.setattr(history, 'MAX_SOURCES', 1)
    else:
        file_id, file_name = 'COPY-'+str(uuid4()), 'Conflicting-'+str(uuid4())+'.xml'
        root = etree.fromstring(older['content'])
        root.find('.//ds:Reference[@Id="invoiceSignedData"]/ds:DigestValue', NS).text = digest(999)
        (t.path.parent/file_name).write_bytes(etree.tostring(root))
        with t.connection.cursor() as cursor:
            cursor.execute('INSERT INTO `tabFile` (name,attached_to_doctype,attached_to_name,is_private,file_name,file_url) '
                'VALUES (%s,%s,%s,1,%s,%s)', (file_id, older['doctype'], older['source'], file_name, '/private/files/'+file_name))
        t.connection.commit()
    reviewed = t.review(expected_xml_sha256=checksum); result = reviewed.history
    assert not reviewed.active and t.database.commits == 1
    if fault == 'source-limit':
        assert not result.source_scan_complete and result.missing_positions == '0'
        assert result.known_positions == '3' and result.unprobed_sources == 2 and result.tail_match is True
    elif fault == 'wrong-pih': assert result.genesis_match is False
    elif fault == 'broken-link': assert result.broken_links == 1
    elif fault == 'rotated-key': assert result.rotated_key_sources == 1
    elif fault == 'byte-limit': assert result.unresolved_sources == 1 and result.unprobed_sources == 1
    elif fault == 'cumulative-limit':
        assert result.unresolved_sources == 1 and result.xml_bytes == len(files[0]['content'])
    else: assert result.unresolved_sources == 1
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '3'
    t.b.request.assert_not_called()


def test_anchor_only_does_not_hide_twenty_six_missing_positions(legacy):
    reviewed = legacy.review(); result = reviewed.history
    assert result.missing_positions == '26' and result.sources_seen == 1
    assert result.genesis_match is None and result.tail_match is True and result.matched_links == 0
    assert result.xml_bytes == 0 and not reviewed.active


@pytest.mark.parametrize('legacy', [('company', 0, '3')], indirect=True)
def test_reused_anchor_rechecks_changed_historical_files_instead_of_caching_a_green_report(legacy):
    t = legacy; files, checksum = linked_files(t)
    first = t.review(expected_xml_sha256=checksum)
    assert first.history.genesis_match is True
    root = etree.fromstring(files[0]['content'])
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject",
        namespaces=NS)[0].text = digest(999)
    files[0]['path'].write_bytes(etree.tostring(root))
    current = t.review(expected_xml_sha256=checksum)
    assert current.reused and current.record_id == first.record_id and not current.active
    assert current.history.genesis_match is False and t.database.commits == 1


@pytest.mark.parametrize('legacy', [('company', 0, '3000')], indirect=True)
def test_more_than_two_thousand_positions_are_counted_exactly_without_loading_older_xml(legacy, monkeypatch):
    t = legacy; rows = []
    for index in range(1, 2058):
        rows.append(('CENSUS-'+str(uuid4()), t.source.company, 2 if index % 5 == 0 else 1,
            str(uuid4()), str(index), t.source.custom_zatca_issuing_unit))
    with t.connection.cursor() as cursor:
        for doctype, subset in (('Sales Invoice', rows[::2]), ('POS Invoice', rows[1::2])):
            cursor.executemany('INSERT INTO `tab'+doctype+'` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
                'custom_zatca_issuing_unit) VALUES (%s,%s,%s,%s,%s,%s)', subset)
        cursor.execute('INSERT INTO `tabPOS Invoice` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
            'custom_zatca_issuing_unit) VALUES (%s,%s,0,%s,%s,%s)',
            ('INDEPENDENT-'+str(uuid4()), t.source.company, str(uuid4()), '9999', 'INDEPENDENT-UNIT'))
        cursor.execute('INSERT INTO `tabPOS Invoice` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
            'custom_zatca_issuing_unit) VALUES (%s,%s,1,%s,%s,%s)',
            ('DIFFERENT-CASE-'+str(uuid4()), t.source.company, str(uuid4()), '2999',
                t.source.custom_zatca_issuing_unit.upper()))
    t.connection.commit()
    older = Mock(side_effect=AssertionError('No older XML/body scan above the budget'))
    monkeypatch.setattr(history, '_older_xml', older)
    reviewed = t.review(); result = reviewed.history
    assert result.known_positions == '2058' and result.missing_positions == '942'
    assert result.sources_seen == result.inspected_sources == 1 and result.unprobed_sources == 2057
    assert not result.source_scan_complete and result.tail_match is True and result.genesis_match is None
    assert result.xml_bytes == 0 and not reviewed.active
    older.assert_not_called(); t.b.request.assert_not_called()
    assert t.runtime.get_doc(t.counter.doctype, t.counter.name).last_issued_icv == '3000'


def test_locked_census_sees_a_commit_hidden_from_an_older_repeatable_read_snapshot(legacy):
    t = legacy
    with owned_worker_transaction(t.runtime) as owner:
        stale = owner.database.sql('SELECT COUNT(*) AS slot_count FROM `tabPOS Invoice` '
            'WHERE custom_zatca_issuing_unit=%s', (t.source.custom_zatca_issuing_unit,), as_dict=True)
        assert stale == [{'slot_count': 0}]
        peer = t.connections()
        with peer.cursor() as cursor:
            cursor.execute('INSERT INTO `tabPOS Invoice` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
                'custom_zatca_issuing_unit) VALUES (%s,%s,1,%s,%s,%s)',
                ('FRESH-'+str(uuid4()), t.source.company, str(uuid4()), '26', t.source.custom_zatca_issuing_unit))
        peer.commit()
        assert owner.database.sql('SELECT COUNT(*) AS slot_count FROM `tabPOS Invoice` '
            'WHERE custom_zatca_issuing_unit=%s', (t.source.custom_zatca_issuing_unit,), as_dict=True) == stale
        assert history._count_slots(owner, t.source.custom_zatca_issuing_unit) == 2
    assert t.database.commits == 0
