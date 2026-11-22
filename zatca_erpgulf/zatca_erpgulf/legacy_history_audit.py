"""Resumable authenticated capture-ledger checks, never a cutover approval.

Each bounded segment pins the same protected capture head. It decrypts pages
only through the capture reader's current Source/File ACL and retains a small
authenticated checkpoint in the caller's owned transaction.
"""

from dataclasses import dataclass
from datetime import datetime

from .artifact_evidence import inspect_invoice_artifact
from .certificate_evidence import inspect_embedded_certificate
from .dispatch_record_codec import encode_record_header, decode_record_header, _identifier, MAX_PAYLOAD_BYTES
from .dispatch_store import _counter, _fingerprint
from .invoice_xml_core import INITIAL_PREVIOUS_HASH
from .legacy_history_capture import _sha


MAX_AUDIT_PAGES = 8
MAX_AUDIT_BYTES = 32 * 1024 * 1024
PAYLOAD = b'zatca-legacy-history-audit/v1'
FIELDS = {'audit_id', 'review_id', 'review_sha256', 'capture_head_sha256', 'next_page', 'next_sha256',
    'next_number', 'next_through', 'next_captured', 'next_unresolved', 'checked_pages', 'checked_sources',
    'unresolved_sources', 'broken_links', 'rotated_sources', 'genesis_match', 'boundary_source', 'boundary_observed',
    'boundary_xml_1', 'boundary_xml_2', 'boundary_xml_3', 'boundary_xml_4', 'traversal_complete', 'revision',
    'last_checked_by', 'checked_at_utc'}


@dataclass(frozen=True, repr=False)
class HistoryAuditResult:
    audit_id: str
    traversal_complete: bool
    reused: bool
    checked_pages: str
    checked_sources: str
    remaining_pages: int
    capture_exhausted: bool
    missing_positions: str
    unresolved_sources: str
    broken_links: str
    rotated_sources: str
    genesis_match: bool | None
    checked_at_utc: str


def _source_sha(source):
    # Cancellation status can change while a generated source retains its slot.
    return _sha(encode_record_header({field: source[field] for field in
        ('doctype', 'name', 'company', 'custom_uuid', 'icv', 'unit')}))


def _hint(record):
    return (_source_sha(record['source']), record['observed'],
        sorted({_sha(file['xml']) for file in record['files']}))


def _hints_match(expected, record):
    source, observed, hashes = _hint(record)
    return source == expected[0] and observed == expected[1] and (not observed or bool(set(hashes) & set(expected[2])))


def _validate(state, store):
    if set(state) != FIELDS:
        store.fail('audit_header')
    _identifier(state['audit_id'])
    from .legacy_history_capture_codec import _name
    _name(state['last_checked_by'])
    if state['checked_at_utc'] is not None:
        try:
            parsed = datetime.strptime(state['checked_at_utc'], '%Y-%m-%dT%H:%M:%S.%f')
            if parsed.strftime('%Y-%m-%dT%H:%M:%S.%f') != state['checked_at_utc']:
                store.fail('audit_clock')
        except (ValueError, TypeError):
            store.fail('audit_clock')
    if (state['review_id'], state['review_sha256']) != (store.review_id, store.review_sha):
        store.fail('audit_review')
    if state['capture_head_sha256'] != _sha(encode_record_header(store.head)):
        store.fail('audit_head_changed')
    for field in ('next_through', 'next_captured', 'next_unresolved', 'checked_pages', 'checked_sources',
            'unresolved_sources', 'broken_links', 'rotated_sources'):
        _counter(state[field], zero=True)
    if (type(state['next_number']) is not int or not 0 <= state['next_number'] <= store.head['page_number']
            or type(state['revision']) is not int or not 0 <= state['revision'] < 2**31
            or type(state['traversal_complete']) is not bool):
        store.fail('audit_header')
    for field in ('genesis_match', 'boundary_observed'):
        if state[field] is not None and type(state[field]) is not bool:
            store.fail('audit_header')
    for field in ('boundary_source', 'boundary_xml_1', 'boundary_xml_2', 'boundary_xml_3', 'boundary_xml_4'):
        if state[field] is not None:
            _fingerprint(state[field])
    if state['traversal_complete']:
        if (state['next_page'] is not None or state['next_sha256'] != '0'*64 or state['next_number'] != 0
                or any(state[field] != '0' for field in ('next_through', 'next_captured', 'next_unresolved'))):
            store.fail('audit_footer')
    else:
        _identifier(state['next_page']); _fingerprint(state['next_sha256'])
        if state['next_number'] == 0:
            store.fail('audit_header')
    if int(state['checked_pages'])+state['next_number'] != store.head['page_number']:
        store.fail('audit_coverage')
    if int(state['checked_sources'])+int(state['next_captured']) != int(store.head['captured_sources']):
        store.fail('audit_coverage')
    if int(state['unresolved_sources'])+int(state['next_unresolved']) != int(store.head['unresolved_sources']):
        store.fail('audit_coverage')


def _initial(store):
    from uuid import uuid4
    state = dict(audit_id=str(uuid4()), review_id=store.review_id, review_sha256=store.review_sha,
        capture_head_sha256=_sha(encode_record_header(store.head)), next_page=store.head['last_page'],
        next_sha256=store.head['last_page_sha256'], next_number=store.head['page_number'],
        next_through=store.head['through_icv'], next_captured=store.head['captured_sources'],
        next_unresolved=store.head['unresolved_sources'], checked_pages='0', checked_sources='0',
        unresolved_sources='0', broken_links='0', rotated_sources='0', genesis_match=None,
        boundary_source=None, boundary_observed=None, boundary_xml_1=None, boundary_xml_2=None,
        boundary_xml_3=None, boundary_xml_4=None, traversal_complete=False, revision=0,
        last_checked_by=store.owner.actor, checked_at_utc=None)
    return state


def _check_page(store, state, header, contents):
    if (header['page_number'], header['through_icv'], header['captured_sources'], header['unresolved_sources']) != (
            state['next_number'], state['next_through'], state['next_captured'], state['next_unresolved']):
        store.fail('audit_chain')
    page, records = contents.page, contents.records
    if page.inventory.known_positions != store.head['known_positions']:
        store.fail('audit_census')
    boundary = [record for record in records if record['boundary']]
    fresh = sorted((record for record in records if not record['boundary']), key=lambda record: int(record['source']['icv']))
    if (len(boundary) != (0 if header['after_icv'] == '0' else 1) or not fresh
            or fresh[-1]['source']['icv'] != header['through_icv']):
        store.fail('audit_window')
    if state['boundary_source'] is not None:
        hint = (state['boundary_source'], state['boundary_observed'],
            [state['boundary_xml_'+str(index)] for index in range(1, 5) if state['boundary_xml_'+str(index)] is not None])
        if not _hints_match(hint, fresh[-1]):
            store.fail('audit_boundary')
    unresolved = sum(not record['observed'] for record in fresh)
    prior_count = int(header['captured_sources'])-len(fresh)
    prior_unresolved = int(header['unresolved_sources'])-unresolved
    if prior_count < 0 or prior_unresolved < 0 or prior_unresolved > prior_count:
        store.fail('audit_counts')
    if page.remaining_sources != int(store.head['known_positions'])-int(header['captured_sources']):
        store.fail('audit_counts')
    positions = [int(record['source']['icv']) for record in records]
    if positions != sorted(set(positions)):
        store.fail('audit_order')
    evidence = {}
    for record in records:
        if record['observed']:
            content = record['files'][0]['xml']
            evidence[int(record['source']['icv'])] = (inspect_invoice_artifact(content),
                inspect_embedded_certificate(content).public_key_sha256)
    matched = broken = rotated = 0
    for record in fresh:
        icv = int(record['source']['icv']); current = evidence.get(icv); previous = evidence.get(icv-1)
        if current is None:
            continue
        rotated += current[1] != store.review['public_key_sha256']
        if icv == 1:
            state['genesis_match'] = current[0].previous_hash == INITIAL_PREVIOUS_HASH
        if previous is not None:
            if current[0].previous_hash == previous[0].invoice_digest:
                matched += 1
            else:
                broken += 1
    inv = page.inventory
    first = evidence.get(1); tail = evidence.get(int(store.review['icv']))
    genesis = None if first is None else first[0].previous_hash == INITIAL_PREVIOUS_HASH
    tail_match = None if tail is None else tail[0].invoice_digest == store.review['invoice_hash']
    if (inv.genesis_match, inv.tail_match, inv.rotated_key_sources, inv.source_scan_complete) != (
            genesis, tail_match, sum(key != store.review['public_key_sha256'] for _evidence, key in evidence.values()),
            header['after_icv'] == '0' and len(records) == int(store.head['known_positions'])):
        store.fail('audit_inventory')
    if (inv.matched_links, inv.broken_links, inv.sources_seen, inv.inspected_sources,
            inv.unresolved_sources, inv.unprobed_sources, inv.missing_positions) != (
            matched, broken, len(records), len(records), sum(not record['observed'] for record in records),
            int(store.head['known_positions'])-len(records), str(int(store.review['icv'])-int(store.head['known_positions']))):
        store.fail('audit_inventory')
    if header['page_number'] == 1:
        if header['after_icv'] != '0' or prior_count or prior_unresolved:
            store.fail('audit_footer')
    elif prior_count == 0 or header['after_icv'] == '0':
        store.fail('audit_chain')
    state.update(next_page=header['previous_page'], next_sha256=header['previous_sha256'],
        next_number=header['page_number']-1, next_through=header['after_icv'], next_captured=str(prior_count),
        next_unresolved=str(prior_unresolved), checked_pages=str(int(state['checked_pages'])+1),
        checked_sources=str(int(state['checked_sources'])+len(fresh)),
        unresolved_sources=str(int(state['unresolved_sources'])+unresolved),
        broken_links=str(int(state['broken_links'])+broken), rotated_sources=str(int(state['rotated_sources'])+rotated),
        traversal_complete=header['page_number'] == 1)
    hint = (None, None, []) if not boundary else _hint(boundary[0])
    state['boundary_source'], state['boundary_observed'] = hint[:2]
    for index in range(1, 5):
        state['boundary_xml_'+str(index)] = hint[2][index-1] if index <= len(hint[2]) else None
    _validate(state, store)


def _result(store, state, reused):
    exhausted = (store.head['through_icv'] == store.review['icv']
        and store.head['captured_sources'] == store.head['known_positions'])
    return HistoryAuditResult(state['audit_id'], state['traversal_complete'], reused, state['checked_pages'],
        state['checked_sources'], state['next_number'], exhausted,
        str(int(store.review['icv'])-int(store.head['known_positions'])), state['unresolved_sources'],
        state['broken_links'], state['rotated_sources'], state['genesis_match'], state['checked_at_utc'])


def audit_capture(store, *, restart=False):
    """Stage one bounded checkpoint segment; the owning review commits it.

    restart requests a fresh audit, never deletion/repair of captured pages.
    A completed report remains point-in-time; cutover must not treat it as a
    perpetual integrity or permissions lease.
    """
    if store.head is None:
        store.fail('audit_no_capture')
    from .legacy_history_capture import TABLE
    catalog = store.sql('SELECT COUNT(*) AS pages FROM '+TABLE+' WHERE review_id=%s LOCK IN SHARE MODE NOWAIT', (store.review_id,))
    if len(catalog) != 1 or type(catalog[0].get('pages')) is not int or catalog[0]['pages'] != store.head['page_number']:
        store.fail('audit_page_count')
    columns = store.sql('SELECT COLUMN_NAME AS column_name,DATA_TYPE AS data_type FROM information_schema.columns '
        'WHERE table_schema=DATABASE() AND table_name=%s AND column_name IN (%s,%s)',
        ('tabZATCA Issuing Chain', 'legacy_audit_header', 'legacy_audit_ciphertext'))
    if len(columns) != 2 or any(row['data_type'] != 'longtext' for row in columns):
        store.fail('audit_storage')
    rows = store.sql('SELECT SUBSTRING(legacy_audit_header,1,32769) AS header,'
        'SUBSTRING(legacy_audit_ciphertext,1,513) AS ciphertext FROM `tabZATCA Issuing Chain` '
        'WHERE name=%s FOR UPDATE NOWAIT', (store.review_id,))
    if len(rows) != 1:
        store.fail('audit_storage')
    before = rows[0]
    absent = before['header'] in (None, '') and before['ciphertext'] in (None, '')
    if absent:
        state = _initial(store)
    else:
        if type(before['header']) is not str:
            store.fail('audit_header')
        encoded = before['header'].encode('utf-8'); state = dict(decode_record_header(encoded))
        if store.owner.cipher.open(store.review_id, 'legacy-history-audit', encoded, before['ciphertext']) != PAYLOAD:
            store.fail('audit_payload')
        # Even an explicit restart must authenticate what it replaces. A changed
        # capture head is allowed only for that explicit fresh-audit operation.
        if restart:
            prior = state.copy(); prior['capture_head_sha256'] = _sha(encode_record_header(store.head))
            if prior['review_id'] != store.review_id or prior['review_sha256'] != store.review_sha or set(prior) != FIELDS:
                store.fail('audit_review')
            state = _initial(store)
        else:
            _validate(state, store)
    if state['traversal_complete']:
        return _result(store, state, True)
    # Current same-unit census must still match this capture epoch.
    from .native_legacy_history import _count_slots
    if str(_count_slots(store.owner, store.review['source_unit'])) != store.head['known_positions']:
        store.fail('audit_census')
    remaining, checked = MAX_AUDIT_BYTES, 0
    while not state['traversal_complete'] and checked < MAX_AUDIT_PAGES and remaining >= MAX_PAYLOAD_BYTES:
        meta = store.row('name', state['next_page'])
        if meta is None or _sha(meta[1]) != state['next_sha256']:
            store.fail('audit_page_missing')
        header, contents, size = store.opened(state['next_page'], with_size=True)
        _check_page(store, state, header, contents)
        remaining -= size; checked += 1
    if checked == 0:
        store.fail('audit_no_progress')
    state['revision'] += 1
    state['last_checked_by'] = store.owner.actor
    state['checked_at_utc'] = store.owner.utc_now().strftime('%Y-%m-%dT%H:%M:%S.%f')
    _validate(state, store)
    encoded = encode_record_header(state)
    encrypted = store.owner.cipher.seal(store.review_id, 'legacy-history-audit', encoded, PAYLOAD)
    store.sql('UPDATE `tabZATCA Issuing Chain` SET legacy_audit_header=%s,legacy_audit_ciphertext=%s '
        'WHERE name=%s AND active=0 AND state_version=0 AND registration_review_key=%s '
        'AND legacy_history_header <=> %s AND legacy_history_ciphertext <=> %s '
        'AND legacy_audit_header <=> %s AND legacy_audit_ciphertext <=> %s',
        (encoded.decode(), encrypted, store.review_id, store.review['owner_key'], store.before['header'],
            store.before['ciphertext'], before['header'], before['ciphertext']))
    if store.sql('SELECT ROW_COUNT() AS changed') != [{'changed': 1}]:
        store.fail('audit_compare')
    return _result(store, state, False)
