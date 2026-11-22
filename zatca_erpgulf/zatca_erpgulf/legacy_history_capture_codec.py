"""Bounded exact-byte history frames; no permissions, SQL or activation policy."""

from dataclasses import asdict, dataclass
import hashlib
import json

from .chain_registration import ChainRegistrationError
from .dispatch_record_codec import MAX_PAYLOAD_BYTES, _pairs, _reject_constant, _identifier
from .dispatch_store import _counter, _fingerprint
from .native_legacy_history import LegacyHistoryInventory, LegacyHistoryPage, MAX_SINGLE_XML_BYTES


MAX_MANIFEST = 512 * 1024
MAX_ACCESS = 256 * 1024
MAX_XML = 15 * 1024 * 1024
SOURCE_FIELDS = {'doctype', 'name', 'company', 'docstatus', 'custom_uuid', 'icv', 'unit'}
PAGE_FIELDS = {'review_id', 'after_icv', 'through_icv', 'next_after_icv', 'remaining_sources', 'boundary_unresolved', 'inventory'}
INVENTORY_FIELDS = {'sources_seen', 'source_scan_complete', 'inspected_sources', 'unresolved_sources', 'unprobed_sources',
    'missing_positions', 'matched_links', 'broken_links', 'genesis_match', 'tail_match', 'rotated_key_sources',
    'xml_bytes', 'known_positions'}


@dataclass(frozen=True, repr=False)
class CaptureContents:
    page: LegacyHistoryPage
    records: tuple

    def __reduce_ex__(self, protocol):
        raise TypeError('registration_capture_not_serializable')


def _fail():
    raise ChainRegistrationError('registration_capture_payload')


def _name(value):
    if type(value) is not str or not value.strip() or len(value) > 140 or any(ord(c) < 32 for c in value):
        _fail()


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail()


def _unjson(raw, limit):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        _fail()
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        _fail()
    if _json(result) != raw:
        _fail()
    return result


def _source(source):
    if type(source) is not dict or set(source) != SOURCE_FIELDS:
        _fail()
    if source['doctype'] not in ('Sales Invoice', 'POS Invoice') or type(source['docstatus']) is not int or source['docstatus'] not in (1, 2):
        _fail()
    for field in ('name', 'company', 'unit'):
        _name(source[field])
    _identifier(source['custom_uuid']); _counter(source['icv'])


def _page(data):
    if type(data) is not dict or set(data) != PAGE_FIELDS:
        _fail()
    _identifier(data['review_id']); start = _counter(data['after_icv'], zero=True); end = _counter(data['through_icv'], zero=True)
    if end < start or type(data['remaining_sources']) is not int or data['remaining_sources'] < 0 or type(data['boundary_unresolved']) is not bool:
        _fail()
    expected = data['through_icv'] if data['remaining_sources'] and end > start else None
    if data['next_after_icv'] != expected:
        _fail()
    inv = data['inventory']
    if type(inv) is not dict or set(inv) != INVENTORY_FIELDS:
        _fail()
    for field in INVENTORY_FIELDS - {'source_scan_complete', 'genesis_match', 'tail_match', 'missing_positions', 'known_positions'}:
        if type(inv[field]) is not int or inv[field] < 0:
            _fail()
    if type(inv['source_scan_complete']) is not bool:
        _fail()
    for field in ('genesis_match', 'tail_match'):
        if inv[field] is not None and type(inv[field]) is not bool:
            _fail()
    for field in ('missing_positions', 'known_positions'):
        if inv[field] is not None:
            _counter(inv[field], zero=True)
    return LegacyHistoryPage(**(data | {'inventory': LegacyHistoryInventory(**inv)}))


def access_bytes(records):
    value = [{'source': record['source'], 'files': [file['file_id'] for file in record['files']]} for record in records]
    raw = _json(value)
    if len(raw) > MAX_ACCESS:
        _fail()
    return raw


def decode_access(raw):
    records = _unjson(raw, MAX_ACCESS)
    if type(records) is not list or not 0 < len(records) <= 65:
        _fail()
    for record in records:
        if type(record) is not dict or set(record) != {'source', 'files'}:
            _fail()
        _source(record['source'])
        if type(record['files']) is not list or len(record['files']) > 4:
            _fail()
        for name in record['files']:
            _name(name)
    return records


def encode_capture(page, buffer):
    descriptors, frames = [], []
    for key, record in sorted(buffer.items(), key=lambda pair: int(pair[1]['source']['icv'])):
        if key != (record['source']['doctype'], record['source']['name']) or set(record) != {'source', 'observed', 'boundary', 'files'}:
            _fail()
        files = []
        for file in record['files']:
            if set(file) != {'file_id', 'xml'} or type(file['xml']) is not bytes:
                _fail()
            content = file['xml']
            files.append({'file_id': file['file_id'], 'length': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
            frames.extend((len(content).to_bytes(4, 'big'), content))
        descriptors.append(record | {'files': files})
    manifest = _json({'v': 1, 'page': asdict(page), 'records': descriptors})
    if len(manifest) > MAX_MANIFEST:
        _fail()
    payload = len(manifest).to_bytes(4, 'big') + manifest + b''.join(frames)
    # One parser owns the invariant set for both capture and retained reads.
    contents = decode_capture(payload)
    return payload, access_bytes(contents.records)


def decode_capture(payload):
    if type(payload) is not bytes or not 4 < len(payload) <= MAX_PAYLOAD_BYTES:
        _fail()
    length = int.from_bytes(payload[:4], 'big')
    manifest = _unjson(payload[4:4+length], MAX_MANIFEST)
    if type(manifest) is not dict or set(manifest) != {'v', 'page', 'records'} or type(manifest['v']) is not int or manifest['v'] != 1:
        _fail()
    page = _page(manifest['page']); records = manifest['records']
    if type(records) is not list or not 0 < len(records) <= 65:
        _fail()
    offset, total_xml, positions, decoded = 4+length, 0, set(), []
    for record in records:
        if type(record) is not dict or set(record) != {'source', 'observed', 'boundary', 'files'}:
            _fail()
        _source(record['source']); icv = int(record['source']['icv'])
        if icv in positions or type(record['observed']) is not bool or type(record['boundary']) is not bool:
            _fail()
        positions.add(icv)
        if record['boundary'] != (page.after_icv != '0' and str(icv) == page.after_icv):
            _fail()
        if not record['boundary'] and not int(page.after_icv) < icv <= int(page.through_icv):
            _fail()
        files = record['files']
        if type(files) is not list or len(files) > 4 or record['observed'] != bool(files):
            _fail()
        opened = []
        for file in files:
            if type(file) is not dict or set(file) != {'file_id', 'length', 'sha256'}:
                _fail()
            _name(file['file_id']); _fingerprint(file['sha256'])
            size = file['length']
            if type(size) is not int or not 0 < size <= MAX_SINGLE_XML_BYTES or int.from_bytes(payload[offset:offset+4], 'big') != size:
                _fail()
            offset += 4
            content = payload[offset:offset+size]; offset += size; total_xml += size
            if len(content) != size or hashlib.sha256(content).hexdigest() != file['sha256'] or total_xml > MAX_XML:
                _fail()
            opened.append({'file_id': file['file_id'], 'xml': content})
        decoded.append(record | {'files': opened})
    if offset != len(payload) or len(records) != page.inventory.inspected_sources or len(records) != page.inventory.sources_seen:
        _fail()
    if sum(not record['observed'] for record in records) != page.inventory.unresolved_sources:
        _fail()
    return CaptureContents(page, tuple(decoded))
