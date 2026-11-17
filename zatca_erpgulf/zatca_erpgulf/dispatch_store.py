"""Fixed-table native dispatch repository inside an owned server transaction.

No connection discovery, schema installation, commit, rollback, HTTP, enrollment
inference or acceptance writer. The worker coordinator must supply the owned DB,
namespace/cipher and live owner check. After any error, roll back the whole owned
transaction and discard this handle. This repository alone is not runtime adoption.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
from types import MappingProxyType

from .dispatch_record_codec import DispatchRecordCipher, DispatchRecordError, encode_record_header, _identifier


TABLE_CHAIN = '`tabZATCA Issuing Chain`'
TABLE_ISSUANCE = '`tabZATCA Issuance`'
TABLE_ATTEMPT = '`tabZATCA Dispatch Attempt`'
ARTIFACT_FIELDS = (
    'record_id','issuance_key','icv_key','chain','company','source_doctype','source_name',
    'environment','source_version','source_sha256','invoice_uuid','icv','invoice_hash',
    'previous_hash','certificate_sha256','public_key_sha256','endpoint','base_url_sha256','artifact_sha256',
    'replaces_issuance',
)
CHAIN_FIELDS = (
    'record_id','owner_key','active_owner_key','owner_doctype','owner_name','environment',
    'seller_tax_id','registration_kind','registration_evidence_sha256','certificate_sha256',
    'public_key_sha256','last_icv','previous_hash','tail_issuance','active_attempt','state_version','active',
)
ATTEMPT_FIELDS = (
    'record_id','issuance','company','source_doctype','source_name','environment','endpoint',
    'attempt_number','fence_token','lease_expires_at_utc','request_sha256',
)
RECEIPT_FIELDS = ATTEMPT_FIELDS+('http_status','response_sha256','request_id')
ENDPOINTS = ('invoices/reporting/single','invoices/clearance/single')
ASSESSMENT_STATES = {
    'REPORTING_MATCHED':'REPORTED','REPORTING_DUPLICATE_MATCHED':'REPORTED',
    'CLEARANCE_MATCHED':'CLEARED','CLEARANCE_DUPLICATE_MATCHED':'CLEARED',
    'VALIDATION_REJECTED':'REJECTED','CLEARANCE_DISABLED':'REPORTING_FALLBACK_READY',
    'AUTHORIZATION_FAILED':'OUTCOME_UNKNOWN','TECHNICAL_FAILURE':'OUTCOME_UNKNOWN',
    'UNCONFIRMED':'REVIEW_REQUIRED','DUPLICATE_REVIEW_REQUIRED':'REVIEW_REQUIRED',
}
MAX_COUNTER_DIGITS = 64
MAX_CIPHERTEXT_CHARS = 3+4*((16*1024*1024+28+2)//3)


class DispatchStoreError(RuntimeError):
    def __init__(self, code):
        self.code=code
        super().__init__(code)


def _counter(value, *, zero=False):
    if (type(value) is not str or not value.isascii() or not value.isdecimal()
            or len(value)>MAX_COUNTER_DIGITS or str(int(value))!=value
            or (not zero and value=='0')):
        raise DispatchStoreError('dispatch_counter_shape')
    return int(value)


def _fingerprint(value):
    if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise DispatchStoreError('dispatch_fingerprint_shape')


def _flat_header(header, fields):
    if type(header) is not dict or set(header)!=set(fields):
        raise DispatchStoreError('dispatch_record_fields')
    return encode_record_header(header)


class DispatchStore:
    """Stage exact encrypted originals and CAS chain/attempt observations.

    API arguments are internal server values, never a client storage namespace or
    approval flag. owner_check must verify the worker's current site/DB/transaction
    ownership. Its acknowledgment is not proof of a trusted epoch or enrollment.
    """
    def __init__(self, database, *, storage_namespace, cipher, owner_check):
        _identifier(storage_namespace)
        if type(cipher) is not DispatchRecordCipher or not callable(owner_check):
            raise DispatchStoreError('dispatch_store_context')
        cipher.require_namespace(storage_namespace)
        self._database=database
        self._namespace=storage_namespace
        self._cipher=cipher
        self._owner_check=owner_check
        self._failed=False
        self._locked_chains={}
        self._locked_issuances={}

    def __repr__(self):return '<DispatchStore protected transaction>'

    def __reduce_ex__(self, protocol):raise TypeError('dispatch_store_not_serializable')

    def _check(self):
        if self._failed:raise DispatchStoreError('dispatch_store_unusable')
        failed=None
        try:
            self._cipher.require_namespace(self._namespace)
            if self._owner_check() is not True:
                failed='dispatch_store_owner_changed'
        except DispatchRecordError as error:
            failed=error.code
        except Exception:
            failed='dispatch_store_owner_check_failed'
        if failed is not None:
            self._failed=True
            raise DispatchStoreError(failed)

    @contextmanager
    def _operation(self):
        self._check()
        try:
            yield
            self._check()
        except BaseException as error:
            self._failed=True
            if isinstance(error,(DispatchStoreError,DispatchRecordError)) or not isinstance(error,Exception):raise
            number=error.args[0] if error.args and type(error.args[0]) is int else None
            code={1062:'dispatch_store_conflict',1205:'dispatch_store_busy',1213:'dispatch_store_busy',
                  3572:'dispatch_store_busy',1146:'dispatch_store_schema_unavailable'}.get(number,'dispatch_store_operation_failed')
        else:
            return
        raise DispatchStoreError(code)

    def _sql(self, statement, values=()):
        self._check()
        rows=self._database.sql(statement,values,as_dict=True)
        self._check()
        return rows

    def _changed_once(self):
        rows=self._sql('SELECT ROW_COUNT() AS changed')
        if len(rows)!=1 or type(rows[0].get('changed')) is not int or rows[0]['changed']!=1:
            raise DispatchStoreError('dispatch_store_compare_failed')

    def lock_active_chain(self, owner_key):
        """NOWAIT avoids holding an ERP worker on another issuer's preparation."""
        with self._operation():
            _fingerprint(owner_key)
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in CHAIN_FIELDS)+
                ' FROM '+TABLE_CHAIN+' WHERE active_owner_key=%s FOR UPDATE NOWAIT',(owner_key,))
            return self._remember_chain(rows,owner_key,require_active=True)

    def lock_recorded_chain(self,chain_id,owner_key):
        """Receipt custody may outlive an active registration or credential."""
        with self._operation():
            _identifier(chain_id);_fingerprint(owner_key)
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in CHAIN_FIELDS)+
                ' FROM '+TABLE_CHAIN+' WHERE name=%s AND owner_key=%s FOR UPDATE NOWAIT',(chain_id,owner_key))
            return self._remember_chain(rows,owner_key,require_active=False)

    def _remember_chain(self,rows,owner_key,*,require_active):
        if len(rows)!=1:raise DispatchStoreError('dispatch_registration_required')
        chain=dict(rows[0])
        if (set(chain)!=set(CHAIN_FIELDS) or chain['owner_key']!=owner_key
                or chain['active'] not in (0,1) or (require_active and chain['active']!=1)):
            raise DispatchStoreError('dispatch_chain_binding')
        _identifier(chain['record_id']);_counter(chain['last_icv'],zero=True)
        for name in ('certificate_sha256','public_key_sha256','registration_evidence_sha256'):
            _fingerprint(chain[name])
        if (chain['environment'] not in ('Sandbox','Simulation','Production')
                or chain['owner_doctype'] not in ('Company','ZATCA Multiple Setting')
                or chain['registration_kind'] not in ('NEW_EGS','LEGACY_REVIEWED')):
            raise DispatchStoreError('dispatch_chain_binding')
        if type(chain['state_version']) is not int or chain['state_version']<0:
            raise DispatchStoreError('dispatch_chain_version')
        locked=MappingProxyType(chain)
        self._locked_chains[chain['record_id']]=locked
        return locked

    @staticmethod
    def _require_active(chain):
        if chain['active']!=1 or chain['active_owner_key']!=chain['owner_key']:
            raise DispatchStoreError('dispatch_chain_inactive')

    def latest_issuance(self, chain_id, doctype, invoice_name):
        with self._operation():
            _identifier(chain_id)
            if doctype not in ('Sales Invoice','POS Invoice') or type(invoice_name) is not str or not invoice_name:
                raise DispatchStoreError('dispatch_source_identity')
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in ARTIFACT_FIELDS)+
                ',state,active_attempt,state_version FROM '+TABLE_ISSUANCE+
                ' WHERE chain=%s AND source_doctype=%s AND source_name=%s ORDER BY source_version DESC LIMIT 1 FOR UPDATE NOWAIT',
                (chain_id,doctype,invoice_name))
            return MappingProxyType(dict(rows[0])) if rows else None

    def lock_issuance(self, chain, record_id):
        """Use the same lock order everywhere: chain, issuance, attempt."""
        with self._operation():
            if self._locked_chains.get(chain['record_id']) is not chain:
                raise DispatchStoreError('dispatch_chain_lock_required')
            _identifier(record_id)
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in ARTIFACT_FIELDS)+
                ',state,active_attempt,state_version FROM '+TABLE_ISSUANCE+
                ' WHERE name=%s AND chain=%s FOR UPDATE NOWAIT',(record_id,chain['record_id']))
            if len(rows)!=1:raise DispatchStoreError('dispatch_issuance_missing')
            row=dict(rows[0])
            if row['record_id']!=record_id or type(row['state_version']) is not int:
                raise DispatchStoreError('dispatch_record_identity')
            locked=MappingProxyType(row)
            self._locked_issuances[record_id]=locked
            return locked

    def _require_locked(self,chain,issuance):
        if (self._locked_chains.get(chain['record_id']) is not chain
                or self._locked_issuances.get(issuance['record_id']) is not issuance
                or issuance['chain']!=chain['record_id']):
            raise DispatchStoreError('dispatch_issuance_lock_required')

    def _attempt(self,record_id):
        _identifier(record_id)
        rows=self._sql('SELECT '+','.join('`'+field+'`' for field in ATTEMPT_FIELDS)+
            ',state,state_version,http_status,response_sha256,request_id,outcome FROM '+TABLE_ATTEMPT+
            ' WHERE name=%s FOR UPDATE NOWAIT',(record_id,))
        if len(rows)!=1:raise DispatchStoreError('dispatch_attempt_missing')
        row=dict(rows[0])
        if row['record_id']!=record_id:raise DispatchStoreError('dispatch_record_identity')
        return row

    def start_attempt(self,chain,issuance,*,record_id,fence_token,actor,now_utc,
                      lease_seconds=120,supersedes_attempt=None):
        """Reserve a fenced attempt, never send or authorize an arbitrary retry.

        Only PREPARED is automatic. A server retry decision must name the exact
        previous uncertain attempt, whose lease has expired. Expiry alone is not
        proof of failure and cannot create a new invoice or replace its bytes.
        The caller must commit this reservation before starting HTTP.
        """
        with self._operation():
            self._require_locked(chain,issuance)
            self._require_active(chain)
            _identifier(record_id);_identifier(fence_token)
            if (type(now_utc) is not datetime or now_utc.tzinfo is not None
                    or type(lease_seconds) is not int or not 1<=lease_seconds<=900
                    or type(actor) is not str or not actor):
                raise DispatchStoreError('dispatch_server_metadata')
            previous=issuance['active_attempt']
            if issuance['state']=='PREPARED':
                if previous or supersedes_attempt is not None or chain['active_attempt']:
                    raise DispatchStoreError('dispatch_attempt_busy')
                number=1
            elif issuance['state'] in ('DISPATCHING','OUTCOME_UNKNOWN'):
                if not previous or supersedes_attempt!=previous or chain['active_attempt'] not in (None,previous):
                    raise DispatchStoreError('dispatch_retry_review_required')
                prior=self._attempt(previous)
                retained_failure=(prior['state']=='RESPONSE_RETAINED'
                    and prior['outcome'] in ('AUTHORIZATION_FAILED','TECHNICAL_FAILURE')
                    and issuance['state']=='OUTCOME_UNKNOWN' and chain['active_attempt'] is None)
                if (prior['issuance']!=issuance['record_id'] or prior['request_sha256']!=issuance['artifact_sha256']
                        or (not retained_failure and (prior['state'] not in ('STARTED','OUTCOME_UNKNOWN')
                            or chain['active_attempt']!=previous
                            or type(prior['lease_expires_at_utc']) is not datetime
                            or prior['lease_expires_at_utc']>now_utc))):
                    raise DispatchStoreError('dispatch_attempt_busy')
                number=prior['attempt_number']+1
                if type(number) is not int or not 2<=number<=2147483647:
                    raise DispatchStoreError('dispatch_attempt_number')
            else:raise DispatchStoreError('dispatch_attempt_state_review')
            if issuance['endpoint'] not in ENDPOINTS:
                raise DispatchStoreError('dispatch_attempt_endpoint')
            header=dict(record_id=record_id,issuance=issuance['record_id'],company=issuance['company'],
                source_doctype=issuance['source_doctype'],source_name=issuance['source_name'],
                environment=issuance['environment'],endpoint=issuance['endpoint'],attempt_number=number,
                fence_token=fence_token,lease_expires_at_utc=(now_utc+timedelta(seconds=lease_seconds)).strftime('%Y-%m-%dT%H:%M:%S.%f'),
                request_sha256=issuance['artifact_sha256'])
            # Datetime is native in SQL and canonical text in authenticated flat
            # headers; all receipt reads use the same conversion below.
            row=dict(header,lease_expires_at_utc=now_utc+timedelta(seconds=lease_seconds),
                state='STARTED',state_version=0,name=record_id,owner=actor,modified_by=actor,
                creation=now_utc,modified=now_utc,docstatus=0)
            self._insert(TABLE_ATTEMPT,row)
            self._sql('UPDATE '+TABLE_ISSUANCE+' SET active_attempt=%s,state=%s,state_version=state_version+1 '
                'WHERE name=%s AND state_version=%s',
                (record_id,'DISPATCHING',issuance['record_id'],issuance['state_version']))
            self._changed_once()
            self._sql('UPDATE '+TABLE_CHAIN+' SET active_attempt=%s,state_version=state_version+1 '
                'WHERE name=%s AND state_version=%s',(record_id,chain['record_id'],chain['state_version']))
            self._changed_once()
            return record_id

    def mark_attempt_unknown(self,chain,issuance,*,attempt_id,fence_token):
        """An interrupted invocation is not a rejection or permission to reissue."""
        with self._operation():
            self._require_locked(chain,issuance)
            _identifier(fence_token)
            attempt=self._attempt(attempt_id)
            if (attempt['fence_token']!=fence_token or attempt['issuance']!=issuance['record_id']
                    or attempt['request_sha256']!=issuance['artifact_sha256']):
                raise DispatchStoreError('dispatch_receipt_binding')
            if attempt['state'] in ('RESPONSE_RETAINED','OUTCOME_UNKNOWN'):return False
            if attempt['state']!='STARTED':raise DispatchStoreError('dispatch_attempt_state_review')
            self._sql('UPDATE '+TABLE_ATTEMPT+' SET state=%s,state_version=state_version+1 '
                'WHERE name=%s AND state_version=%s',('OUTCOME_UNKNOWN',attempt_id,attempt['state_version']))
            self._changed_once()
            current=issuance['active_attempt']==attempt_id and chain['active_attempt']==attempt_id
            if current:
                self._sql('UPDATE '+TABLE_ISSUANCE+' SET state=%s,state_version=state_version+1 '
                    'WHERE name=%s AND state_version=%s',('OUTCOME_UNKNOWN',issuance['record_id'],issuance['state_version']))
                self._changed_once()
            return current

    def _insert(self,table,values):
        columns=tuple(values)
        self._sql('INSERT INTO '+table+' ('+','.join('`'+field+'`' for field in columns)+
            ') VALUES ('+','.join('%s' for _ in columns)+')',tuple(values[field] for field in columns))

    def retain_receipt(self,chain,issuance,*,attempt_id,fence_token,http_status,request_id,body):
        """Keep an immutable response even when this worker's fence is stale.

        This is custody only. No HTTP status, including200/208/409, becomes
        acceptance here. A current response moves to review until a separately
        bound classifier has verified its contract and any returned signed XML.
        """
        with self._operation():
            self._require_locked(chain,issuance)
            _identifier(fence_token)
            if (type(http_status) is not int or not 100<=http_status<=599
                    or type(request_id) is not str or len(request_id)>120
                    or any(ord(c)<32 or ord(c)>126 for c in request_id)
                    or type(body) is not bytes or len(body)>=16*1024*1024):
                raise DispatchStoreError('dispatch_receipt_shape')
            attempt=self._attempt(attempt_id)
            if (attempt['fence_token']!=fence_token or attempt['issuance']!=issuance['record_id']
                    or attempt['request_sha256']!=issuance['artifact_sha256']):
                raise DispatchStoreError('dispatch_receipt_binding')
            header={key:attempt[key] for key in ATTEMPT_FIELDS}
            header['lease_expires_at_utc']=attempt['lease_expires_at_utc'].strftime('%Y-%m-%dT%H:%M:%S.%f')
            header.update(http_status=http_status,response_sha256=hashlib.sha256(body).hexdigest(),request_id=request_id)
            encoded=_flat_header(header,RECEIPT_FIELDS)
            if attempt['state']=='RESPONSE_RETAINED':
                saved,original=self.open_receipt(attempt_id)
                if dict(saved)!=header or original!=body:
                    raise DispatchStoreError('dispatch_receipt_already_retained')
                return False
            if attempt['state'] not in ('STARTED','OUTCOME_UNKNOWN'):
                raise DispatchStoreError('dispatch_attempt_state_review')
            encrypted=self._cipher.seal(attempt_id,'receipt',encoded,b'\x01'+body)
            self._sql('UPDATE '+TABLE_ATTEMPT+' SET state=%s,http_status=%s,response_sha256=%s,request_id=%s,'
                'receipt_ciphertext=%s,state_version=state_version+1 WHERE name=%s AND state_version=%s',
                ('RESPONSE_RETAINED',http_status,header['response_sha256'],request_id,encrypted,
                 attempt_id,attempt['state_version']))
            self._changed_once()
            current=issuance['active_attempt']==attempt_id and chain['active_attempt']==attempt_id
            if current:
                self._sql('UPDATE '+TABLE_ISSUANCE+' SET state=%s,state_version=state_version+1 '
                    'WHERE name=%s AND state_version=%s',('REVIEW_REQUIRED',issuance['record_id'],issuance['state_version']))
                self._changed_once()
                self._sql('UPDATE '+TABLE_CHAIN+' SET active_attempt=NULL,state_version=state_version+1 '
                    'WHERE name=%s AND state_version=%s',(chain['record_id'],chain['state_version']))
                self._changed_once()
            return current

    def open_receipt(self,attempt_id):
        """Recover exact application response bytes, including an empty body."""
        with self._operation():
            _identifier(attempt_id)
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in RECEIPT_FIELDS)+
                ',SUBSTRING(receipt_ciphertext,1,%s) AS receipt_ciphertext FROM '+TABLE_ATTEMPT+' WHERE name=%s',
                (MAX_CIPHERTEXT_CHARS+1,attempt_id))
            if len(rows)!=1:raise DispatchStoreError('dispatch_attempt_missing')
            row=dict(rows[0]);encrypted=row.pop('receipt_ciphertext')
            if row['record_id']!=attempt_id:raise DispatchStoreError('dispatch_record_identity')
            row['lease_expires_at_utc']=row['lease_expires_at_utc'].strftime('%Y-%m-%dT%H:%M:%S.%f')
            opened=self._cipher.open(attempt_id,'receipt',_flat_header(row,RECEIPT_FIELDS),encrypted)
            if not opened.startswith(b'\x01') or hashlib.sha256(opened[1:]).hexdigest()!=row['response_sha256']:
                raise DispatchStoreError('dispatch_receipt_digest')
            return MappingProxyType(row),opened[1:]

    def record_assessment(self,chain,issuance,*,attempt_id,fence_token,outcome):
        """Record a server-computed assessment after committed receipt custody.

        The owned service must open/decrypt both original and receipt and run the
        native assessor first. This fixed repository method is not an RPC or an
        acceptance grant for a caller-supplied result. Late assessments are kept
        on their own attempt and never replace the current issuance state.
        """
        with self._operation():
            self._require_locked(chain,issuance)
            _identifier(fence_token)
            if outcome not in ASSESSMENT_STATES:
                raise DispatchStoreError('dispatch_assessment_outcome')
            attempt=self._attempt(attempt_id)
            if (attempt['issuance']!=issuance['record_id'] or attempt['fence_token']!=fence_token
                    or attempt['request_sha256']!=issuance['artifact_sha256']
                    or attempt['state']!='RESPONSE_RETAINED'):
                raise DispatchStoreError('dispatch_assessment_receipt_required')
            if attempt['outcome']:
                if attempt['outcome']!=outcome:
                    raise DispatchStoreError('dispatch_assessment_already_recorded')
                return (issuance['active_attempt']==attempt_id
                    and issuance['state']==ASSESSMENT_STATES[outcome] and self._latest_source(issuance))
            self._sql('UPDATE '+TABLE_ATTEMPT+' SET outcome=%s,state_version=state_version+1 '
                'WHERE name=%s AND state_version=%s',(outcome,attempt_id,attempt['state_version']))
            self._changed_once()
            current=(issuance['active_attempt']==attempt_id and issuance['state']=='REVIEW_REQUIRED'
                and self._latest_source(issuance))
            if current:
                self._sql('UPDATE '+TABLE_ISSUANCE+' SET state=%s,state_version=state_version+1 '
                    'WHERE name=%s AND state_version=%s',
                    (ASSESSMENT_STATES[outcome],issuance['record_id'],issuance['state_version']))
                self._changed_once()
            return current

    def _latest_source(self,issuance):
        rows=self._sql('SELECT name FROM '+TABLE_ISSUANCE+
            ' WHERE chain=%s AND source_doctype=%s AND source_name=%s '
            'ORDER BY source_version DESC LIMIT 1 FOR UPDATE NOWAIT',
            (issuance['chain'],issuance['source_doctype'],issuance['source_name']))
        return len(rows)==1 and rows[0]['name']==issuance['record_id']

    def stage_issuance(self, chain, header, exact_request_bytes, *, actor, occurred_at):
        """One local generation: store original + head; never remote acceptance.

        This method does not decide initial enrollment, validate signed XML,
        authorize corrected versions, commit or send. The coordinator validates
        the producer and current source before calling it under the same lock.
        """
        with self._operation():
            encoded=_flat_header(header,ARTIFACT_FIELDS)
            if self._locked_chains.get(header['chain']) is not chain:
                raise DispatchStoreError('dispatch_chain_lock_required')
            self._require_active(chain)
            if (type(actor) is not str or not actor or type(occurred_at) is not datetime
                    or occurred_at.tzinfo is not None):
                raise DispatchStoreError('dispatch_server_metadata')
            if (header['source_doctype'] not in ('Sales Invoice','POS Invoice')
                    or header['endpoint'] not in ('invoices/reporting/single','invoices/clearance/single')
                    or type(header['source_name']) is not str or not header['source_name']):
                raise DispatchStoreError('dispatch_source_identity')
            for name in ('issuance_key','icv_key','source_sha256','artifact_sha256','certificate_sha256','public_key_sha256','base_url_sha256'):
                _fingerprint(header[name])
            _identifier(header['record_id']);_identifier(header['invoice_uuid'])
            if header['chain']!=chain['record_id'] or header['environment']!=chain['environment']:
                raise DispatchStoreError('dispatch_chain_artifact_binding')
            if (header['certificate_sha256']!=chain['certificate_sha256']
                    or header['public_key_sha256']!=chain['public_key_sha256']):
                raise DispatchStoreError('dispatch_chain_material_changed')
            next_icv=_counter(chain['last_icv'],zero=True)+1
            if _counter(header['icv'])!=next_icv or header['previous_hash']!=chain['previous_hash']:
                raise DispatchStoreError('dispatch_predecessor_changed')
            if type(header['source_version']) is not int or header['source_version']<=0:
                raise DispatchStoreError('dispatch_source_version')
            if header['artifact_sha256']!=hashlib.sha256(exact_request_bytes).hexdigest():
                raise DispatchStoreError('dispatch_request_digest')
            encrypted=self._cipher.seal(header['record_id'],'artifact',encoded,exact_request_bytes)
            values=dict(header,artifact_ciphertext=encrypted,state='PREPARED',state_version=0,active_attempt=None)
            values.update(name=header['record_id'],owner=actor,modified_by=actor,creation=occurred_at,modified=occurred_at,docstatus=0)
            columns=tuple(values)
            self._sql('INSERT INTO '+TABLE_ISSUANCE+' ('+','.join('`'+field+'`' for field in columns)+
                      ') VALUES ('+','.join('%s' for _ in columns)+')',tuple(values[field] for field in columns))
            self._sql('UPDATE '+TABLE_CHAIN+' SET last_icv=%s,previous_hash=%s,tail_issuance=%s,'
                      'state_version=state_version+1,modified=%s,modified_by=%s '
                      'WHERE name=%s AND state_version=%s AND last_icv=%s AND previous_hash=%s',
                      (header['icv'],header['invoice_hash'],header['record_id'],occurred_at,actor,
                       chain['record_id'],chain['state_version'],chain['last_icv'],chain['previous_hash']))
            self._changed_once()
            return header['record_id']

    def open_issuance(self, record_id):
        """Bound read/decrypt; no re-sign, source mutation or network decision."""
        with self._operation():
            _identifier(record_id)
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in ARTIFACT_FIELDS)+
                ',SUBSTRING(artifact_ciphertext,1,%s) AS artifact_ciphertext FROM '+TABLE_ISSUANCE+' WHERE name=%s',
                (MAX_CIPHERTEXT_CHARS+1,record_id))
            if len(rows)!=1:raise DispatchStoreError('dispatch_issuance_missing')
            row=dict(rows[0]);encrypted=row.pop('artifact_ciphertext')
            encoded=_flat_header(row,ARTIFACT_FIELDS)
            if row['record_id']!=record_id:raise DispatchStoreError('dispatch_record_identity')
            opened=self._cipher.open(record_id,'artifact',encoded,encrypted)
            if hashlib.sha256(opened).hexdigest()!=row['artifact_sha256']:
                raise DispatchStoreError('dispatch_request_digest')
            return MappingProxyType(row),opened
