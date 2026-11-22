"""Atomic immutable XML pages and an authenticated current capture head.

Internal to the owned, unchanged inactive legacy review. Capturing declarations
does not grant cutover, credential activation, remote acceptance or SDK approval.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
from uuid import uuid4

from .artifact_evidence import inspect_invoice_artifact
from .certificate_evidence import inspect_embedded_certificate
from .chain_registration import ChainRegistrationError
from .dispatch_record_codec import encode_record_header, decode_record_header, _identifier, MAX_HEADER_BYTES
from .dispatch_store import _counter, _fingerprint, MAX_CIPHERTEXT_CHARS
from .legacy_history_capture_codec import encode_capture, decode_capture, decode_access, access_bytes, _name
from .native_identity_inventory import require_range_engines
from .permission_compat import saved_row_has_permission


TABLE = '`tabZATCA Legacy History Page`'
HEAD_PAYLOAD = b'zatca-legacy-history-head/v1'
PAGE_FIELDS = {'record_id', 'page_key', 'review_id', 'review_sha256', 'page_number', 'after_icv', 'through_icv',
    'previous_page', 'previous_sha256', 'known_positions', 'captured_sources', 'unresolved_sources',
    'payload_sha256', 'access_sha256', 'created_by', 'occurred_at_utc'}
HEAD_FIELDS = {'review_id', 'review_sha256', 'last_page', 'last_page_sha256', 'page_number', 'through_icv',
    'known_positions', 'captured_sources', 'unresolved_sources'}


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _key(review_id, after):
    return _sha(b'zatca-legacy-history-page/v1\0'+review_id.encode()+b'\0'+after.encode())


@dataclass(frozen=True, repr=False)
class HistoryCaptureResult:
    record_id: str
    reused: bool
    current_cursor: str
    head_page_number: int
    captured_sources: str
    unresolved_sources: str


class HistoryCaptureStore:
    """One owned transaction's capture capability, never a queued/RPC object."""

    def __init__(self, runtime, owner, review, chain):
        self.runtime, self.owner, self.review = runtime, owner, review
        self.review_id, self.review_sha = review['record_id'], chain['registration_evidence_sha256']
        self._storage()
        rows = self.sql('SELECT SUBSTRING(legacy_history_header,1,32769) AS header,'
            'SUBSTRING(legacy_history_ciphertext,1,513) AS ciphertext '
            'FROM `tabZATCA Issuing Chain` WHERE name=%s FOR UPDATE NOWAIT', (self.review_id,))
        if len(rows) != 1:
            self.fail('head_missing')
        self.before = rows[0]
        self.head = None
        if self.before['header'] in (None, '') and self.before['ciphertext'] in (None, ''):
            if self.sql('SELECT name FROM '+TABLE+' WHERE review_id=%s LIMIT 1 FOR UPDATE NOWAIT', (self.review_id,)):
                self.fail('orphan_pages')
        else:
            self.head, encoded = self.header(self.before['header'], head=True)
            if owner.cipher.open(self.review_id, 'legacy-history-head', encoded, self.before['ciphertext']) != HEAD_PAYLOAD:
                self.fail('head_payload')
            latest = self.row('name', self.head['last_page'])
            if latest is None or _sha(latest[1]) != self.head['last_page_sha256']:
                self.fail('head_page_missing')
            for field in ('page_number', 'through_icv', 'known_positions', 'captured_sources', 'unresolved_sources'):
                if latest[0][field] != self.head[field]:
                    self.fail('head_page_binding')

    def __reduce_ex__(self, protocol):
        raise TypeError('history_capture_store_not_serializable')

    @staticmethod
    def fail(code):
        raise ChainRegistrationError('registration_capture_'+code)

    def sql(self, statement, values=()):
        self.owner.require_owner()
        result = self.owner.database.sql(statement, values, as_dict=True)
        self.owner.require_owner()
        return result

    def _storage(self):
        self.sql('SELECT name FROM '+TABLE+' LIMIT 0')
        require_range_engines(self.owner, ('tabZATCA Issuing Chain', 'tabZATCA Legacy History Page'))
        columns = self.sql('SELECT TABLE_NAME AS table_name,COLUMN_NAME AS column_name,DATA_TYPE AS data_type,character_maximum_length AS capacity '
            'FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name IN (%s,%s)',
            ('tabZATCA Legacy History Page', 'tabZATCA Issuing Chain'))
        found = {(row['table_name'], row['column_name']): row for row in columns}
        for table, fields in (('tabZATCA Legacy History Page', ('header', 'access_ciphertext', 'page_ciphertext')),
                ('tabZATCA Issuing Chain', ('legacy_history_header', 'legacy_history_ciphertext'))):
            for field in fields:
                if found.get((table, field), {}).get('data_type') != 'longtext':
                    self.fail('storage_columns')
        for field, capacity in (('record_id', 36), ('page_key', 64), ('review_id', 36), ('after_icv', 64), ('through_icv', 64)):
            column = found.get(('tabZATCA Legacy History Page', field), {})
            if column.get('data_type') not in ('char', 'varchar') or type(column.get('capacity')) is not int or column['capacity'] < capacity:
                self.fail('storage_columns')
        if found.get(('tabZATCA Legacy History Page', 'page_number'), {}).get('data_type') not in ('int', 'bigint'):
            self.fail('storage_columns')
        indexes = self.sql('SELECT INDEX_NAME AS index_name,NON_UNIQUE AS non_unique,SEQ_IN_INDEX AS seq_in_index,'
            'COLUMN_NAME AS column_name,SUB_PART AS sub_part FROM information_schema.statistics '
            'WHERE table_schema=DATABASE() AND table_name=%s', ('tabZATCA Legacy History Page',))
        for field in ('page_key', 'record_id'):
            if not any(row['column_name'] == field and row['non_unique'] == 0 and row['seq_in_index'] == 1
                    and row['sub_part'] is None and sum(other['index_name'] == row['index_name'] for other in indexes) == 1
                    for row in indexes):
                self.fail('storage_index')
        if not any(row['column_name'] == 'review_id' and row['seq_in_index'] == 1 and row['sub_part'] is None for row in indexes):
            self.fail('storage_index')

    def header(self, value, *, head=False):
        if type(value) is not str:
            self.fail('header')
        encoded = value.encode('utf-8')
        header = dict(decode_record_header(encoded))
        if set(header) != (HEAD_FIELDS if head else PAGE_FIELDS):
            self.fail('header')
        if header['review_id'] != self.review_id or header['review_sha256'] != self.review_sha:
            self.fail('review_binding')
        _identifier(header['review_id']); _fingerprint(header['review_sha256'])
        if type(header['page_number']) is not int or not 0 < header['page_number'] < 2**31:
            self.fail('page_number')
        for field in ('through_icv', 'known_positions', 'captured_sources'):
            _counter(header[field])
        _counter(header['unresolved_sources'], zero=True)
        if not int(header['unresolved_sources']) <= int(header['captured_sources']) <= int(header['known_positions']):
            self.fail('coverage')
        if head:
            _identifier(header['last_page']); _fingerprint(header['last_page_sha256'])
        else:
            _identifier(header['record_id']); _counter(header['after_icv'], zero=True)
            for field in ('payload_sha256', 'access_sha256', 'previous_sha256', 'page_key'):
                _fingerprint(header[field])
            if header['page_key'] != _key(self.review_id, header['after_icv']) or int(header['through_icv']) <= int(header['after_icv']):
                self.fail('page_binding')
            if header['page_number'] == 1:
                if header['previous_page'] is not None or header['previous_sha256'] != '0'*64 or header['after_icv'] != '0':
                    self.fail('predecessor')
            else:
                _identifier(header['previous_page'])
            _name(header['created_by'])
            try:
                if datetime.strptime(header['occurred_at_utc'], '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%dT%H:%M:%S.%f') != header['occurred_at_utc']:
                    self.fail('clock')
            except (ValueError, TypeError):
                self.fail('clock')
        return header, encoded

    def row(self, column, value, *, body=False):
        if column not in ('name', 'page_key'):
            self.fail('lookup')
        extra = (',SUBSTRING(access_ciphertext,1,400000) AS access_ciphertext,'
            'SUBSTRING(page_ciphertext,1,%s) AS page_ciphertext' if body else '')
        values = (MAX_CIPHERTEXT_CHARS+1, value) if body else (value,)
        rows = self.sql('SELECT name,record_id,page_key,review_id,page_number,after_icv,through_icv,'
            'SUBSTRING(header,1,'+str(MAX_HEADER_BYTES+1)+') AS header'+extra+' FROM '+TABLE+' WHERE `'+column+'`=%s FOR UPDATE NOWAIT', values)
        if not rows:
            return None
        if len(rows) != 1:
            self.fail('ambiguous')
        row = rows[0]; header, encoded = self.header(row['header'])
        if row['name'] != header['record_id'] or any(row[field] != header[field] for field in
                ('record_id', 'page_key', 'review_id', 'page_number', 'after_icv', 'through_icv')):
            self.fail('index_binding')
        return header, encoded, row

    def access(self, references):
        for reference in references:
            source = reference['source']
            if source['company'] != self.review['company'] or source['unit'] != self.review['source_unit']:
                self.fail('source_binding')
            document = self.runtime.get_doc(source['doctype'], source['name'], for_update=True)
            self.owner.require_owner()
            if ((document.doctype, document.name, document.get('company'), document.get('custom_uuid'),
                    str(document.get('custom_zatca_icv')), document.get('custom_zatca_issuing_unit')) !=
                    (source['doctype'], source['name'], source['company'], source['custom_uuid'], source['icv'], source['unit'])
                    or document.get('docstatus') not in (1, 2)):
                self.fail('source_binding')
            documents = [document]
            for file_id in reference['files']:
                file = self.runtime.get_doc('File', file_id, for_update=True)
                if (file.doctype, file.name, file.get('attached_to_doctype'), file.get('attached_to_name'), file.get('is_private')) != (
                        'File', file_id, source['doctype'], source['name'], 1):
                    self.fail('file_binding')
                documents.append(file)
            for document in documents:
                if not saved_row_has_permission(self.runtime.has_permission, document.doctype, 'read', doc=document, user=self.owner.actor):
                    self.fail('read_permission')
                self.owner.require_owner()

    def declarations(self, records):
        for record in records:
            source, values = record['source'], set()
            for file in record['files']:
                observed = inspect_invoice_artifact(file['xml'])
                key = inspect_embedded_certificate(file['xml']).public_key_sha256
                if (observed.invoice_id, observed.uuid, str(observed.icv), observed.seller_tax_id) != (
                        source['name'], source['custom_uuid'], source['icv'], self.review['seller_tax_id']):
                    self.fail('xml_binding')
                values.add((observed.invoice_digest, observed.previous_hash, key))
            if len(values) > 1:
                self.fail('xml_conflict')

    def opened(self, identifier, *, with_size=False):
        result = self.row('name', identifier, body=True)
        if result is None:
            self.fail('page_missing')
        header, encoded, row = result
        access = self.owner.cipher.open(identifier, 'legacy-history-access', encoded, row['access_ciphertext'])
        if _sha(access) != header['access_sha256']:
            self.fail('access_binding')
        self.access(decode_access(access))  # No invoice-XML decryption before current saved-row READ.
        payload = self.owner.cipher.open(identifier, 'legacy-history-page', encoded, row['page_ciphertext'])
        if _sha(payload) != header['payload_sha256']:
            self.fail('payload_binding')
        contents = decode_capture(payload)
        if access_bytes(contents.records) != access or (contents.page.review_id, contents.page.after_icv, contents.page.through_icv,
                contents.page.inventory.known_positions) != (self.review_id, header['after_icv'], header['through_icv'], header['known_positions']):
            self.fail('payload_binding')
        self.declarations(contents.records)
        return (header, contents, len(payload)) if with_size else (header, contents)

    def lookup(self, after):
        row = self.row('page_key', _key(self.review_id, after))
        if row is None:
            expected = '0' if self.head is None else self.head['through_icv']
            if after != expected:
                self.fail('cursor')
            return None
        if self.head is None or row[0]['page_number'] > self.head['page_number'] or int(row[0]['through_icv']) > int(self.head['through_icv']):
            self.fail('orphan_pages')
        header, contents = self.opened(row[0]['record_id'])
        return self.result(header, reused=True), contents.page

    def result(self, header, *, reused):
        return HistoryCaptureResult(header['record_id'], reused, self.head['through_icv'], self.head['page_number'],
            self.head['captured_sources'], self.head['unresolved_sources'])

    def stage(self, page, buffer):
        expected = '0' if self.head is None else self.head['through_icv']
        if page.review_id != self.review_id or page.after_icv != expected or int(page.through_icv) <= int(page.after_icv):
            self.fail('no_progress')
        if self.head is not None and page.inventory.known_positions != self.head['known_positions']:
            self.fail('census_changed')
        payload, access = encode_capture(page, buffer)
        records = tuple(buffer.values())
        self.access(decode_access(access)); self.declarations(records)
        if self.head is not None:
            _previous, prior = self.opened(self.head['last_page'])
            old = [record for record in prior.records if record['source']['icv'] == expected]
            boundary = [record for record in records if record['boundary']]
            if len(old) != 1 or len(boundary) != 1:
                self.fail('boundary')
            old, boundary = old[0], boundary[0]
            fields = ('doctype', 'name', 'company', 'custom_uuid', 'icv', 'unit')
            if (any(old['source'][field] != boundary['source'][field] for field in fields)
                    or old['observed'] != boundary['observed'] or (old['observed'] and not
                    {_sha(file['xml']) for file in old['files']} & {_sha(file['xml']) for file in boundary['files']})):
                self.fail('boundary_changed')
        fresh = [record for record in records if not record['boundary']]
        count = (0 if self.head is None else int(self.head['captured_sources']))+len(fresh)
        unresolved = (0 if self.head is None else int(self.head['unresolved_sources']))+sum(not record['observed'] for record in fresh)
        if count > int(page.inventory.known_positions) or (page.remaining_sources == 0 and count != int(page.inventory.known_positions)):
            self.fail('coverage_changed')
        occurred = self.owner.utc_now()
        header = dict(record_id=str(uuid4()), page_key=_key(self.review_id, page.after_icv), review_id=self.review_id,
            review_sha256=self.review_sha, page_number=1 if self.head is None else self.head['page_number']+1,
            after_icv=page.after_icv, through_icv=page.through_icv, previous_page=None if self.head is None else self.head['last_page'],
            previous_sha256='0'*64 if self.head is None else self.head['last_page_sha256'], known_positions=page.inventory.known_positions,
            captured_sources=str(count), unresolved_sources=str(unresolved), payload_sha256=_sha(payload), access_sha256=_sha(access),
            created_by=self.owner.actor, occurred_at_utc=occurred.strftime('%Y-%m-%dT%H:%M:%S.%f'))
        encoded = encode_record_header(header); self.header(encoded.decode())
        values = {field: header[field] for field in ('record_id', 'page_key', 'review_id', 'page_number', 'after_icv', 'through_icv')}
        values.update(name=header['record_id'], header=encoded.decode(),
            access_ciphertext=self.owner.cipher.seal(header['record_id'], 'legacy-history-access', encoded, access),
            page_ciphertext=self.owner.cipher.seal(header['record_id'], 'legacy-history-page', encoded, payload),
            owner=self.owner.actor, modified_by=self.owner.actor, creation=occurred, modified=occurred, docstatus=0)
        columns = tuple(values)
        self.sql('INSERT INTO '+TABLE+' ('+','.join('`'+field+'`' for field in columns)+') VALUES ('+
            ','.join('%s' for _ in columns)+')', tuple(values[field] for field in columns))
        head = {field: header[field] for field in ('review_id', 'review_sha256', 'page_number', 'through_icv', 'known_positions', 'captured_sources', 'unresolved_sources')}
        head.update(last_page=header['record_id'], last_page_sha256=_sha(encoded))
        head_encoded = encode_record_header(head)
        encrypted = self.owner.cipher.seal(self.review_id, 'legacy-history-head', head_encoded, HEAD_PAYLOAD)
        self.sql('UPDATE `tabZATCA Issuing Chain` SET legacy_history_header=%s,legacy_history_ciphertext=%s,modified=%s,modified_by=%s '
            'WHERE name=%s AND active=0 AND state_version=0 AND active_owner_key IS NULL AND registration_review_key=%s '
            'AND tail_issuance IS NULL AND active_attempt IS NULL AND legacy_history_header <=> %s AND legacy_history_ciphertext <=> %s',
            (head_encoded.decode(), encrypted, occurred, self.owner.actor, self.review_id, self.review['owner_key'],
                self.before['header'], self.before['ciphertext']))
        if self.sql('SELECT ROW_COUNT() AS changed') != [{'changed': 1}]:
            self.fail('head_compare')
        self.head = head
        return self.result(header, reused=False)
