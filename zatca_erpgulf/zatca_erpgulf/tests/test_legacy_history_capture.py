"""Capture framing/domain/source schema, not XML/signature/acceptance proof."""

from dataclasses import replace
import pickle

import pytest

from zatca_erpgulf.zatca_erpgulf import legacy_history_capture_codec as codec
from zatca_erpgulf.zatca_erpgulf.dispatch_record_codec import DispatchRecordCipher, DispatchRecordError, encode_record_header
from zatca_erpgulf.zatca_erpgulf.dispatch_store import DispatchStoreError
from zatca_erpgulf.zatca_erpgulf.chain_registration import ChainRegistrationError
from zatca_erpgulf.zatca_erpgulf.native_legacy_history import LegacyHistoryPage, LegacyHistoryInventory
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch_schema import metadata


ID = '10000000-0000-4000-8000-000000000001'
NS = '20000000-0000-4000-8000-000000000001'


def capture_input():
    inv = LegacyHistoryInventory(1, True, 1, 0, 0, '0', 0, 0, True, True, 0, 0, '1')
    page = LegacyHistoryPage(ID, '0', '1', None, 0, False, inv)
    source = dict(doctype='Sales Invoice', name='SYNTHETIC', company='COMPANY', docstatus=1,
        custom_uuid=ID, icv='1', unit='UNIT')
    buffer = {('Sales Invoice', 'SYNTHETIC'): dict(source=source, observed=True, boundary=False,
        files=[{'file_id': 'PRIVATE-FILE', 'xml': b'EXACT TEST BYTES\x00\xff'}])}
    return page, buffer


def test_frame_preserves_exact_immutable_bytes_and_access_manifest_without_stringifying():
    page, buffer = capture_input(); payload, access = codec.encode_capture(page, buffer)
    restored = codec.decode_capture(payload)
    assert restored.page == page and restored.records[0]['files'][0]['xml'] == b'EXACT TEST BYTES\x00\xff'
    assert codec.access_bytes(restored.records) == access
    assert codec.decode_access(access)[0]['files'] == ['PRIVATE-FILE']
    with pytest.raises(TypeError): pickle.dumps(restored)


@pytest.mark.parametrize('fault', ['truncated', 'extra', 'sha', 'length', 'empty'])
def test_bad_frames_are_not_repaired_or_exported_in_errors(fault):
    page, buffer = capture_input(); payload, _ = codec.encode_capture(page, buffer)
    if fault == 'truncated': payload = payload[:-1]
    elif fault == 'extra': payload += b'PRIVATE'
    elif fault == 'sha': payload = payload[:-1]+bytes([payload[-1] ^ 1])
    elif fault == 'length': payload = b'\xff'*4+payload[4:]
    else: payload = b''
    with pytest.raises((ChainRegistrationError, DispatchRecordError)) as failed: codec.decode_capture(payload)
    assert 'PRIVATE' not in str(failed.value)


@pytest.mark.parametrize('fault', ['extra-source', 'leading-icv', 'observed-empty', 'unknown-field', 'wrong-key', 'inventory'])
def test_capture_rejects_ambiguous_source_or_coverage_metadata(fault):
    page, buffer = capture_input(); record = next(iter(buffer.values()))
    if fault == 'extra-source': record['source']['private_key'] = 'PRIVATE'
    elif fault == 'leading-icv': record['source']['icv'] = '01'
    elif fault == 'observed-empty': record['files'] = []
    elif fault == 'unknown-field': record['extra'] = 'PRIVATE'
    elif fault == 'wrong-key': buffer = {('POS Invoice', 'OTHER'): record}
    else: page = replace(page, inventory=replace(page.inventory, inspected_sources=2))
    with pytest.raises((ChainRegistrationError, DispatchRecordError, DispatchStoreError)): codec.encode_capture(page, buffer)


@pytest.mark.parametrize('limit', ['MAX_MANIFEST', 'MAX_ACCESS', 'MAX_XML', 'MAX_SINGLE_XML_BYTES'])
def test_allocation_and_raw_byte_limits_are_shared_by_encode_and_decode(monkeypatch, limit):
    page, buffer = capture_input(); monkeypatch.setattr(codec, limit, 1)
    with pytest.raises(ChainRegistrationError): codec.encode_capture(page, buffer)


@pytest.mark.parametrize('kind,other', [('legacy-history-page', 'legacy-history-access'),
    ('legacy-history-access', 'legacy-history-head'), ('legacy-history-head', 'artifact')])
def test_new_custody_domains_cannot_be_relabelled(kind, other):
    cipher = DispatchRecordCipher(b'T'*32, site='fictional.invalid', storage_namespace=NS)
    header = encode_record_header({'test': 1}); value = cipher.seal(ID, kind, header, b'PRIVATE')
    assert cipher.open(ID, kind, header, value) == b'PRIVATE'
    with pytest.raises(DispatchRecordError): cipher.open(ID, other, header, value)


def test_source_schema_has_protected_unique_slots_and_nullable_private_head():
    fields = {field['fieldname']: field for field in metadata('ZATCA Legacy History Page')['fields']}
    assert fields['record_id']['unique'] == fields['page_key']['unique'] == 1
    assert fields['review_id']['search_index'] == 1
    assert fields['after_icv']['fieldtype'] == fields['through_icv']['fieldtype'] == 'Data'
    for name in ('header', 'access_ciphertext', 'page_ciphertext'):
        assert fields[name]['hidden'] == fields[name]['print_hide'] == fields[name]['no_copy'] == 1
    chain = {field['fieldname']: field for field in metadata('ZATCA Issuing Chain')['fields']}
    assert all(not chain[name].get('reqd') for name in ('legacy_history_header', 'legacy_history_ciphertext'))
