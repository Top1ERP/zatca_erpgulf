"""Fixed-table onboarding custody inside an owned transaction.

One committed reservation permits one invocation. There is no lease expiry,
automatic retry, credential projection, chain activation or remote-status guess.
The coordinator retains a response before attempting local material admission.
An incomplete/unknown reservation therefore holds instead of issuing twice.
"""

from datetime import datetime
import hashlib
from types import MappingProxyType

from .dispatch_record_codec import _identifier, encode_record_header, decode_record_header
from .dispatch_store import DispatchStore, DispatchStoreError, TABLE_CHAIN, _fingerprint, MAX_CIPHERTEXT_CHARS
from .invoice_xml_core import INITIAL_PREVIOUS_HASH


TABLE = '`tabZATCA Onboarding Attempt`'
FIELDS = ('record_id', 'chain', 'owner_key', 'company', 'environment', 'endpoint',
          'base_url_sha256', 'public_key_sha256', 'csr_sha256', 'configuration_sha256',
          'intent_sha256', 'request_sha256', 'previous_attempt', 'fence_token',
          'created_by', 'created_at_utc')
RECEIPT_FIELDS = (*FIELDS, 'http_status', 'request_id', 'response_sha256')
PENDING = {'compliance': 'CCSID_PENDING', 'production/csids': 'FINAL_PENDING'}
RECEIVED = {'compliance': 'CCSID_RESPONSE', 'production/csids': 'FINAL_RESPONSE'}
READY = {'compliance': 'CCSID_READY', 'production/csids': 'FINAL_READY'}
BEFORE = {'compliance': 'CSR_READY', 'production/csids': 'CCSID_READY'}


def validate_request_header(header):
    if type(header) is not dict or set(header) != set(FIELDS):
        raise DispatchStoreError('onboarding_attempt_header_fields')
    for name in ('record_id', 'chain', 'fence_token'):
        _identifier(header[name])
    if header['previous_attempt'] is not None:
        _identifier(header['previous_attempt'])
    for name in ('owner_key', 'base_url_sha256', 'public_key_sha256', 'csr_sha256',
                 'configuration_sha256', 'intent_sha256', 'request_sha256'):
        _fingerprint(header[name])
    if header['endpoint'] not in PENDING or header['environment'] not in ('Sandbox', 'Simulation', 'Production'):
        raise DispatchStoreError('onboarding_attempt_operation')
    for name in ('company', 'created_by'):
        value = header[name]
        if (type(value) is not str or not 0 < len(value) <= 140 or value != value.strip()
                or any(ord(c) < 32 for c in value)):
            raise DispatchStoreError('onboarding_attempt_identity')
    try:
        clock = datetime.strptime(header['created_at_utc'], '%Y-%m-%dT%H:%M:%S.%f')
        valid = clock.strftime('%Y-%m-%dT%H:%M:%S.%f') == header['created_at_utc']
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise DispatchStoreError('onboarding_attempt_clock')
    return encode_record_header(header)


def _receipt(header, status, request_id, body):
    if (type(status) is not int or not 100 <= status <= 599
            or type(request_id) is not str or len(request_id) > 120
            or any(ord(c) < 32 or ord(c) > 126 for c in request_id)
            or type(body) is not bytes or len(body) >= 16 * 1024 * 1024):
        raise DispatchStoreError('onboarding_receipt_shape')
    result = dict(header, http_status=status, request_id=request_id,
                  response_sha256=hashlib.sha256(body).hexdigest())
    return result, encode_record_header(result)


class OnboardingStore(DispatchStore):
    """Share the dispatch lock/cipher lifetime, never its invoice-attempt table."""

    def _initial_locked(self, chain):
        if (self._locked_chains.get(chain['record_id']) is not chain
                or chain['registration_kind'] != 'NEW_EGS' or chain['active'] != 0
                or chain['active_owner_key'] is not None or chain['last_icv'] != '0'
                or chain['previous_hash'] != INITIAL_PREVIOUS_HASH
                or chain['tail_issuance'] is not None or chain['active_attempt'] is not None):
            raise DispatchStoreError('onboarding_initial_chain_required')

    def state(self, chain):
        with self._operation():
            self._initial_locked(chain)
            rows = self._sql('SELECT onboarding_state,onboarding_attempt,onboarding_compliance_attempt,'
                'onboarding_final_attempt FROM '+TABLE_CHAIN+' WHERE name=%s LOCK IN SHARE MODE NOWAIT',
                (chain['record_id'],))
            if len(rows) != 1:
                raise DispatchStoreError('onboarding_state_missing')
            for name in ('onboarding_attempt', 'onboarding_compliance_attempt', 'onboarding_final_attempt'):
                if rows[0][name] is not None:
                    _identifier(rows[0][name])
            return MappingProxyType(dict(rows[0]))

    def reserve(self, chain, header, body):
        with self._operation():
            state = self.state(chain)
            encoded = validate_request_header(header)
            if (header['chain'] != chain['record_id'] or header['owner_key'] != chain['owner_key']
                    or header['environment'] != chain['environment']
                    or header['public_key_sha256'] != chain['public_key_sha256']
                    or header['intent_sha256'] != chain['registration_evidence_sha256']
                    or state['onboarding_state'] != BEFORE[header['endpoint']]
                    or header['previous_attempt'] != state['onboarding_attempt']
                    or type(body) is not bytes or not 0 < len(body) <= 256 * 1024
                    or hashlib.sha256(body).hexdigest() != header['request_sha256']):
                raise DispatchStoreError('onboarding_reservation_binding')
            encrypted = self._cipher.seal(header['record_id'], 'onboarding-request', encoded, body)
            occurred = datetime.strptime(header['created_at_utc'], '%Y-%m-%dT%H:%M:%S.%f')
            values = {name: header[name] for name in ('record_id', 'chain', 'owner_key', 'environment',
                'endpoint', 'fence_token', 'previous_attempt', 'request_sha256')}
            values.update(name=header['record_id'], state='RESERVED', request_header=encoded.decode(),
                request_ciphertext=encrypted, owner=header['created_by'], modified_by=header['created_by'],
                creation=occurred, modified=occurred, docstatus=0)
            self._insert(TABLE, values)
            self._sql('UPDATE '+TABLE_CHAIN+' SET onboarding_state=%s,onboarding_attempt=%s,'
                'state_version=state_version+1 WHERE name=%s AND state_version=%s',
                (PENDING[header['endpoint']], header['record_id'], chain['record_id'], chain['state_version']))
            self._changed_once()

    def open_attempt(self, record_id):
        with self._operation():
            _identifier(record_id)
            rows = self._sql('SELECT record_id,chain,owner_key,environment,endpoint,fence_token,previous_attempt,'
                'request_sha256,state,SUBSTRING(request_header,1,32769) AS request_header,'
                'SUBSTRING(request_ciphertext,1,%s) AS request_ciphertext,'
                'SUBSTRING(receipt_header,1,32769) AS receipt_header,'
                'SUBSTRING(receipt_ciphertext,1,%s) AS receipt_ciphertext FROM '+TABLE+
                ' WHERE name=%s LOCK IN SHARE MODE NOWAIT',
                (MAX_CIPHERTEXT_CHARS+1, MAX_CIPHERTEXT_CHARS+1, record_id))
            if len(rows) != 1:
                raise DispatchStoreError('onboarding_attempt_missing')
            row = rows[0]
            encoded = row['request_header'].encode('utf-8')
            header = dict(decode_record_header(encoded))
            validate_request_header(header)
            if header['record_id'] != record_id or any(row[name] != header[name] for name in (
                    'record_id', 'chain', 'owner_key', 'environment', 'endpoint', 'fence_token',
                    'previous_attempt', 'request_sha256')):
                raise DispatchStoreError('onboarding_attempt_row_binding')
            body = self._cipher.open(record_id, 'onboarding-request', encoded, row['request_ciphertext'])
            if hashlib.sha256(body).hexdigest() != header['request_sha256']:
                raise DispatchStoreError('onboarding_attempt_body_binding')
            if row['state'] == 'RESERVED' and row['receipt_header'] is None and row['receipt_ciphertext'] is None:
                return MappingProxyType(header), body, None, None
            if row['state'] != 'RESPONSE_RETAINED':
                raise DispatchStoreError('onboarding_attempt_state_review')
            receipt_encoded = row['receipt_header'].encode('utf-8')
            receipt = dict(decode_record_header(receipt_encoded))
            if set(receipt) != set(RECEIPT_FIELDS) or any(receipt[name] != header[name] for name in FIELDS):
                raise DispatchStoreError('onboarding_receipt_header_binding')
            response = self._cipher.open(record_id, 'onboarding-response', receipt_encoded, row['receipt_ciphertext'])
            expected, _ = _receipt(header, receipt['http_status'], receipt['request_id'], response)
            if receipt != expected:
                raise DispatchStoreError('onboarding_receipt_body_binding')
            return MappingProxyType(header), body, MappingProxyType(receipt), response

    def retain_response(self, chain, header, *, status, request_id, body):
        with self._operation():
            state = self.state(chain)
            saved, _, receipt, response = self.open_attempt(header['record_id'])
            if dict(saved) != header or header['chain'] != chain['record_id'] or state['onboarding_attempt'] != header['record_id']:
                raise DispatchStoreError('onboarding_receipt_attempt_binding')
            received, encoded = _receipt(header, status, request_id, body)
            if receipt is not None:
                if dict(receipt) != received or response != body:
                    raise DispatchStoreError('onboarding_receipt_already_retained')
                return False
            if state['onboarding_state'] != PENDING[header['endpoint']]:
                raise DispatchStoreError('onboarding_receipt_state_review')
            encrypted = self._cipher.seal(header['record_id'], 'onboarding-response', encoded, body)
            self._sql('UPDATE '+TABLE+' SET receipt_header=%s,receipt_ciphertext=%s,state=%s '
                'WHERE name=%s AND state=%s', (encoded.decode(), encrypted, 'RESPONSE_RETAINED', header['record_id'], 'RESERVED'))
            self._changed_once()
            self._sql('UPDATE '+TABLE_CHAIN+' SET onboarding_state=%s,state_version=state_version+1 '
                'WHERE name=%s AND state_version=%s',
                (RECEIVED[header['endpoint']], chain['record_id'], chain['state_version']))
            self._changed_once()
            return True

    def admit_response(self, chain, header, *, certificate_sha256):
        """Persist the coordinator's verified projection; do not activate a unit."""
        with self._operation():
            state = self.state(chain)
            _fingerprint(certificate_sha256)
            if (state['onboarding_state'] != RECEIVED[header['endpoint']]
                    or state['onboarding_attempt'] != header['record_id'] or header['chain'] != chain['record_id']):
                raise DispatchStoreError('onboarding_admission_state_review')
            saved, _, receipt, _ = self.open_attempt(header['record_id'])
            if dict(saved) != header or receipt is None or receipt['http_status'] != 200:
                raise DispatchStoreError('onboarding_admission_receipt_review')
            pointer = 'onboarding_compliance_attempt' if header['endpoint']=='compliance' else 'onboarding_final_attempt'
            self._sql('UPDATE '+TABLE_CHAIN+' SET onboarding_state=%s,`'+pointer+'`=%s,certificate_sha256=%s,'
                'state_version=state_version+1 WHERE name=%s AND state_version=%s',
                (READY[header['endpoint']], header['record_id'], certificate_sha256, chain['record_id'], chain['state_version']))
            self._changed_once()

    def release_rejected(self, chain, header):
        """Preserve a known rejection and allow a later explicit new reservation."""
        from .onboarding_response import is_retryable_rejection
        with self._operation():
            state = self.state(chain)
            saved, _, receipt, body = self.open_attempt(header['record_id'])
            if (dict(saved) != header or header['chain'] != chain['record_id']
                    or state['onboarding_state'] != RECEIVED[header['endpoint']]
                    or state['onboarding_attempt'] != header['record_id'] or receipt is None
                    or not is_retryable_rejection(header['endpoint'], receipt['http_status'], body)):
                raise DispatchStoreError('onboarding_rejection_review')
            self._sql('UPDATE '+TABLE_CHAIN+' SET onboarding_state=%s,state_version=state_version+1 '
                'WHERE name=%s AND state_version=%s',
                (BEFORE[header['endpoint']], chain['record_id'], chain['state_version']))
            self._changed_once()
