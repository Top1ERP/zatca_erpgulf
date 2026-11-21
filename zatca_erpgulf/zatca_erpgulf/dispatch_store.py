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

from .dispatch_record_codec import (
    DispatchRecordCipher, DispatchRecordError, encode_record_header, decode_record_header, _identifier,
)


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
MAX_PUBLICATION_CIPHERTEXT_CHARS = 4096
ISSUANCE_STATE_SQL=(',state,active_attempt,state_version,'
    'SUBSTRING(late_acceptance_header,1,8193) AS late_acceptance_header,'
    'SUBSTRING(late_acceptance_ciphertext,1,8193) AS late_acceptance_ciphertext')


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

    def lock_chain_reference(self, chain_id):
        """Lock a saved source's opaque chain, without selecting current keys.

        The source service checks read/write ACL before this historical lookup.
        This is not registration, activation or permission to dispatch a request.
        """
        with self._operation():
            _identifier(chain_id)
            rows = self._sql('SELECT '+','.join('`'+field+'`' for field in CHAIN_FIELDS)+
                ' FROM '+TABLE_CHAIN+' WHERE name=%s FOR UPDATE NOWAIT', (chain_id,))
            if len(rows) != 1:
                raise DispatchStoreError('dispatch_registration_required')
            return self._remember_chain(rows, rows[0]['owner_key'], require_active=False)

    def reviewed_chain_for_owner(self, owner_key):
        """Find an existing review/registration, including an inactive candidate.

        The review coordinator first locks the saved credential owner. This is
        not an automatic choice between multiple historical registrations.
        """
        with self._operation():
            _fingerprint(owner_key)
            rows = self._sql('SELECT '+','.join('`'+field+'`' for field in CHAIN_FIELDS)+
                ' FROM '+TABLE_CHAIN+' WHERE owner_key=%s '
                'AND (active_owner_key IS NOT NULL OR registration_review_key IS NOT NULL) '
                'LIMIT 2 FOR UPDATE NOWAIT', (owner_key,))
            if not rows:
                history = self._sql('SELECT name FROM '+TABLE_CHAIN+
                    ' WHERE owner_key=%s LIMIT 1 LOCK IN SHARE MODE NOWAIT', (owner_key,))
                if history:
                    raise DispatchStoreError('dispatch_registration_history_review')
                return None
            if len(rows) != 1:
                raise DispatchStoreError('dispatch_registration_ambiguous')
            return self._remember_chain(rows, owner_key, require_active=False)

    def stage_reviewed_registration(self, header, payload, *, supersedes=None):
        """Retain a positive legacy anchor as INACTIVE, without cutover/reset.

        Saved source/owner/counter/File ACL and metadata checks belong to the
        service. Missing history can never reach this method with ICV zero.
        There is deliberately no activation/legacy retirement in this operation.
        """
        from .chain_registration import (
            validate_registration_header, open_registration_payload, evidence_sha256,
        )
        with self._operation():
            encoded = validate_registration_header(header)
            open_registration_payload(header, payload)
            occurred_at = datetime.strptime(header['reviewed_at_utc'], '%Y-%m-%dT%H:%M:%S.%f')
            existing = self.reviewed_chain_for_owner(header['owner_key'])
            if supersedes is None and (existing is not None or header['supersedes_review'] is not None):
                raise DispatchStoreError('dispatch_registration_already_exists')
            if supersedes is not None:
                if (existing is None or existing['record_id'] != supersedes['record_id']
                        or header['supersedes_review'] != existing['record_id']
                        or existing['active'] != 0 or existing['state_version'] != 0
                        or existing['active_owner_key'] is not None or existing['tail_issuance'] is not None
                        or existing['active_attempt'] is not None):
                    raise DispatchStoreError('dispatch_registration_supersedes_review')
                # Authenticate the older review before closing its mutable slot.
                # Its header/ciphertext and original chain anchor never change.
                self.open_reviewed_registration(existing)
                self._sql('UPDATE '+TABLE_CHAIN+' SET registration_review_key=NULL,state_version=state_version+1,'
                    'modified=%s,modified_by=%s '
                    'WHERE name=%s AND state_version=0 AND active=0 AND active_owner_key IS NULL '
                    'AND registration_review_key=%s',
                    (occurred_at,header['reviewed_by'],existing['record_id'],header['owner_key']))
                self._changed_once()
            encrypted = self._cipher.seal(header['record_id'], 'chain-registration', encoded, payload)
            chain = {key: header[key] for key in ('record_id','owner_key','owner_doctype','owner_name',
                'environment','seller_tax_id','registration_kind','certificate_sha256','public_key_sha256')}
            chain.update(active_owner_key=None, registration_evidence_sha256=evidence_sha256(encoded,payload),
                last_icv=header['icv'], previous_hash=header['invoice_hash'], tail_issuance=None,
                active_attempt=None, state_version=0, active=0)
            values = dict(chain, name=chain['record_id'], registration_review_key=header['owner_key'],
                registration_header=encoded.decode('utf-8'),
                registration_ciphertext=encrypted, owner=header['reviewed_by'], modified_by=header['reviewed_by'],
                creation=occurred_at, modified=occurred_at, docstatus=0)
            columns = tuple(values)
            self._sql('INSERT INTO '+TABLE_CHAIN+' ('+','.join('`'+key+'`' for key in columns)+
                ') VALUES ('+','.join('%s' for _ in columns)+')', tuple(values[key] for key in columns))
            return self._remember_chain([chain], header['owner_key'], require_active=False)

    def open_reviewed_registration(self, chain):
        """Decrypt exact review custody under this transaction's chain ticket."""
        from .chain_registration import (
            decode_registration_header, open_registration_payload, evidence_sha256, CHAIN_BINDING,
        )
        with self._operation():
            if self._locked_chains.get(chain['record_id']) is not chain:
                raise DispatchStoreError('dispatch_chain_lock_required')
            rows = self._sql('SELECT SUBSTRING(registration_header,1,32769) AS header,'
                'SUBSTRING(registration_ciphertext,1,%s) AS ciphertext FROM '+TABLE_CHAIN+
                ' WHERE name=%s LOCK IN SHARE MODE NOWAIT', (MAX_CIPHERTEXT_CHARS+1,chain['record_id']))
            if len(rows) != 1:
                raise DispatchStoreError('dispatch_registration_missing')
            header, encoded = decode_registration_header(rows[0]['header'])
            if any(header[key] != chain[key] for key in CHAIN_BINDING):
                raise DispatchStoreError('dispatch_registration_chain_binding')
            payload = self._cipher.open(chain['record_id'],'chain-registration',encoded,rows[0]['ciphertext'])
            if evidence_sha256(encoded,payload) != chain['registration_evidence_sha256']:
                raise DispatchStoreError('dispatch_registration_evidence_binding')
            xml, reason = open_registration_payload(header,payload)
            return header, xml, reason

    def stage_onboarding_intent(self, header, csr):
        """Reserve one inactive initial intent, without issuing a certificate.

        Only public CSR bytes are encrypted here; the private key belongs to the
        selected owner and the coordinator must write both in one transaction.
        An earlier owner history/registration is never adopted as a new intent.
        """
        from .native_onboarding import validate_intent_header, inspect_intent_csr, intent_sha256, egs_identity_key
        from .invoice_xml_core import INITIAL_PREVIOUS_HASH
        with self._operation():
            encoded = validate_intent_header(header)
            inspect_intent_csr(header,csr)
            rows = self._sql('SELECT name FROM '+TABLE_CHAIN+' WHERE owner_key=%s LIMIT 1 FOR UPDATE NOWAIT',
                (header['owner_key'],))
            if rows:
                raise DispatchStoreError('dispatch_onboarding_existing_owner_review')
            encrypted = self._cipher.seal(header['record_id'],'chain-onboarding',encoded,csr)
            chain = {key:header[key] for key in ('record_id','owner_key','owner_doctype','owner_name',
                'environment','seller_tax_id','public_key_sha256')}
            chain.update(active_owner_key=None,registration_kind='NEW_EGS',certificate_sha256='0'*64,
                registration_evidence_sha256=intent_sha256(encoded,csr),last_icv='0',
                previous_hash=INITIAL_PREVIOUS_HASH,tail_issuance=None,active_attempt=None,state_version=0,active=0)
            occurred_at = datetime.strptime(header['created_at_utc'],'%Y-%m-%dT%H:%M:%S.%f')
            values = dict(chain,name=header['record_id'],onboarding_header=encoded.decode('utf-8'),
                onboarding_ciphertext=encrypted,onboarding_owner_key=header['owner_key'],onboarding_state='CSR_READY',
                egs_identity_key=egs_identity_key(header['environment'],header['seller_tax_id'],header['csr_serial']),
                owner=header['created_by'],modified_by=header['created_by'],creation=occurred_at,modified=occurred_at,docstatus=0)
            columns = tuple(values)
            self._sql('INSERT INTO '+TABLE_CHAIN+' ('+','.join('`'+name+'`' for name in columns)+') '
                'VALUES ('+','.join('%s' for _ in columns)+')',tuple(values[name] for name in columns))
            return self._remember_chain([chain],header['owner_key'],require_active=False)

    def open_onboarding_intent(self, chain):
        """Read authenticated initial CSR custody, not a client intent claim."""
        from .native_onboarding import validate_intent_header, inspect_intent_csr, intent_sha256, egs_identity_key
        from .dispatch_record_codec import decode_record_header
        with self._operation():
            if self._locked_chains.get(chain['record_id']) is not chain:
                raise DispatchStoreError('dispatch_chain_lock_required')
            rows = self._sql('SELECT SUBSTRING(onboarding_header,1,32769) AS header,'
                'SUBSTRING(onboarding_ciphertext,1,%s) AS ciphertext,onboarding_state,onboarding_owner_key,egs_identity_key '
                'FROM '+TABLE_CHAIN+' WHERE name=%s LOCK IN SHARE MODE NOWAIT',
                (MAX_CIPHERTEXT_CHARS+1,chain['record_id']))
            if len(rows)!=1 or type(rows[0]['header']) is not str or len(rows[0]['header'])>32768:
                raise DispatchStoreError('dispatch_onboarding_intent_missing')
            encoded = rows[0]['header'].encode('utf-8')
            header = dict(decode_record_header(encoded))
            validate_intent_header(header)
            if (chain['registration_kind']!='NEW_EGS' or any(chain[key]!=header[key] for key in (
                    'record_id','owner_key','owner_doctype','owner_name','environment','seller_tax_id','public_key_sha256'))
                    or rows[0]['onboarding_owner_key']!=chain['owner_key']
                    or rows[0]['egs_identity_key']!=egs_identity_key(header['environment'],header['seller_tax_id'],header['csr_serial'])):
                raise DispatchStoreError('dispatch_onboarding_chain_binding')
            csr = self._cipher.open(chain['record_id'],'chain-onboarding',encoded,rows[0]['ciphertext'])
            inspect_intent_csr(header,csr)
            if rows[0]['onboarding_state']=='CSR_READY' and intent_sha256(encoded,csr)!=chain['registration_evidence_sha256']:
                raise DispatchStoreError('dispatch_onboarding_evidence_binding')
            return MappingProxyType(header),csr,rows[0]['onboarding_state']

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
                ISSUANCE_STATE_SQL+' FROM '+TABLE_ISSUANCE+
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
                ISSUANCE_STATE_SQL+' FROM '+TABLE_ISSUANCE+
                ' WHERE name=%s AND chain=%s FOR UPDATE NOWAIT',(record_id,chain['record_id']))
            if len(rows)!=1:raise DispatchStoreError('dispatch_issuance_missing')
            row=dict(rows[0])
            if row['record_id']!=record_id or type(row['state_version']) is not int:
                raise DispatchStoreError('dispatch_record_identity')
            locked=MappingProxyType(row)
            self._locked_issuances[record_id]=locked
            return locked

    def find_source_issuance(self,*,doctype,invoice_name,company,chain_id,invoice_uuid,icv):
        """Read one exact saved-source reference, without current credentials.

        A shared current read supports historical viewing after certificate
        expiry. Mutation methods still require the separate chain write ticket.
        Source/Company read ACL belongs to the service before this lookup.
        """
        with self._operation():
            _identifier(chain_id);_identifier(invoice_uuid);_counter(icv)
            if doctype not in ('Sales Invoice','POS Invoice'):
                raise DispatchStoreError('dispatch_source_identity')
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in ARTIFACT_FIELDS)+
                ISSUANCE_STATE_SQL+' FROM '+TABLE_ISSUANCE+
                ' WHERE source_doctype=%s AND source_name=%s AND chain=%s '
                'ORDER BY source_version DESC LIMIT 1 LOCK IN SHARE MODE NOWAIT',
                (doctype,invoice_name,chain_id))
            if (len(rows)!=1 or (rows[0]['company'],rows[0]['invoice_uuid'],rows[0]['icv'])
                    !=(company,invoice_uuid,icv)):
                raise DispatchStoreError('dispatch_source_custody_review')
            row=MappingProxyType(dict(rows[0]))
            self._locked_issuances[row['record_id']]=row
            return row

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
            endpoint=issuance['endpoint']
            if issuance['state']=='PREPARED':
                if previous or supersedes_attempt is not None or chain['active_attempt']:
                    raise DispatchStoreError('dispatch_attempt_busy')
                number=1
            elif issuance['state']=='REPORTING_FALLBACK_READY':
                if not previous or supersedes_attempt!=previous or chain['active_attempt']:
                    raise DispatchStoreError('dispatch_retry_review_required')
                prior=self._attempt(previous)
                if (issuance['endpoint']!=ENDPOINTS[1] or prior['issuance']!=issuance['record_id']
                        or prior['state']!='RESPONSE_RETAINED' or prior['outcome']!='CLEARANCE_DISABLED'
                        or prior['http_status']!=303 or prior['endpoint']!=ENDPOINTS[1]
                        or prior['request_sha256']!=issuance['artifact_sha256']):
                    raise DispatchStoreError('dispatch_fallback_receipt_required')
                self.open_clearance_fallback(issuance)
                endpoint=ENDPOINTS[0]
                number=prior['attempt_number']+1
            elif issuance['state'] in ('DISPATCHING','OUTCOME_UNKNOWN'):
                prior=self.require_uncertain_retry(chain,issuance,attempt_id=supersedes_attempt,now_utc=now_utc)
                number=prior['attempt_number']+1
                endpoint=prior['endpoint']
            else:raise DispatchStoreError('dispatch_attempt_state_review')
            if type(number) is not int or not 1<=number<=2147483647:
                raise DispatchStoreError('dispatch_attempt_number')
            if endpoint not in ENDPOINTS:
                raise DispatchStoreError('dispatch_attempt_endpoint')
            header=dict(record_id=record_id,issuance=issuance['record_id'],company=issuance['company'],
                source_doctype=issuance['source_doctype'],source_name=issuance['source_name'],
                environment=issuance['environment'],endpoint=endpoint,attempt_number=number,
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
            return MappingProxyType(header)

    def require_uncertain_retry(self,chain,issuance,*,attempt_id,now_utc,expected_fence=None):
        """Shared reservation eligibility; expiry alone never proves rejection.

        The owned coordinator separately authenticates any retained failure
        response. This repository check does not authorize transport or commit.
        """
        with self._operation():
            self._require_locked(chain,issuance)
            if any(issuance.get(key) is not None for key in ('late_acceptance_header','late_acceptance_ciphertext')):
                raise DispatchStoreError('dispatch_retry_resolved_acceptance')
            previous=issuance['active_attempt']
            if (issuance['state'] not in ('DISPATCHING','OUTCOME_UNKNOWN') or not previous
                    or attempt_id!=previous or chain['active_attempt'] not in (None,previous)
                    or type(now_utc) is not datetime or now_utc.tzinfo is not None):
                raise DispatchStoreError('dispatch_retry_review_required')
            prior=self._attempt(previous)
            retained_failure=(prior['state']=='RESPONSE_RETAINED'
                and prior['outcome'] in ('AUTHORIZATION_FAILED','TECHNICAL_FAILURE')
                and issuance['state']=='OUTCOME_UNKNOWN' and chain['active_attempt'] is None)
            if (prior['issuance']!=issuance['record_id'] or prior['request_sha256']!=issuance['artifact_sha256']
                    or expected_fence is not None and prior['fence_token']!=expected_fence
                    or (not retained_failure and (prior['state'] not in ('STARTED','OUTCOME_UNKNOWN')
                        or chain['active_attempt']!=previous or type(prior['lease_expires_at_utc']) is not datetime
                        or prior['lease_expires_at_utc']>now_utc))):
                raise DispatchStoreError('dispatch_attempt_busy')
            if prior['endpoint']!=issuance['endpoint']:
                if prior['endpoint']!=ENDPOINTS[0] or issuance['endpoint']!=ENDPOINTS[1]:
                    raise DispatchStoreError('dispatch_attempt_endpoint')
                self.open_clearance_fallback(issuance)
            return MappingProxyType(prior)

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
                ',SUBSTRING(receipt_ciphertext,1,%s) AS receipt_ciphertext FROM '+TABLE_ATTEMPT+
                ' WHERE name=%s LOCK IN SHARE MODE NOWAIT',
                (MAX_CIPHERTEXT_CHARS+1,attempt_id))
            if len(rows)!=1:raise DispatchStoreError('dispatch_attempt_missing')
            row=dict(rows[0]);encrypted=row.pop('receipt_ciphertext')
            if row['record_id']!=attempt_id:raise DispatchStoreError('dispatch_record_identity')
            row['lease_expires_at_utc']=row['lease_expires_at_utc'].strftime('%Y-%m-%dT%H:%M:%S.%f')
            opened=self._cipher.open(attempt_id,'receipt',_flat_header(row,RECEIPT_FIELDS),encrypted)
            if not opened.startswith(b'\x01') or hashlib.sha256(opened[1:]).hexdigest()!=row['response_sha256']:
                raise DispatchStoreError('dispatch_receipt_digest')
            return MappingProxyType(row),opened[1:]

    def open_clearance_fallback(self,issuance):
        """Decrypt the original303 evidence; a state/flag alone is insufficient."""
        with self._operation():
            if self._locked_issuances.get(issuance['record_id']) is not issuance:
                raise DispatchStoreError('dispatch_issuance_lock_required')
            rows=self._sql('SELECT name FROM '+TABLE_ATTEMPT+
                ' WHERE issuance=%s AND endpoint=%s AND http_status=303 AND outcome=%s '
                'AND state=%s ORDER BY attempt_number LIMIT 1 FOR UPDATE NOWAIT',
                (issuance['record_id'],ENDPOINTS[1],'CLEARANCE_DISABLED','RESPONSE_RETAINED'))
            if len(rows)!=1:raise DispatchStoreError('dispatch_fallback_receipt_required')
            header,body=self.open_receipt(rows[0]['name'])
            if (header['issuance']!=issuance['record_id'] or header['environment']!=issuance['environment']
                    or header['endpoint']!=ENDPOINTS[1] or header['http_status']!=303
                    or header['request_sha256']!=issuance['artifact_sha256']):
                raise DispatchStoreError('dispatch_fallback_receipt_required')
            return header,body

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

    def lock_attempt_history(self,chain,issuance):
        """Bounded current history for explicit replacement review, not replay."""
        with self._operation():
            self._require_locked(chain,issuance)
            rows=self._sql('SELECT name,record_id,attempt_number,state,request_sha256 FROM '+TABLE_ATTEMPT+
                ' WHERE issuance=%s ORDER BY attempt_number LIMIT 101 FOR UPDATE NOWAIT',(issuance['record_id'],))
            if not rows or len(rows)>100:
                raise DispatchStoreError('dispatch_attempt_history_review')
            for number,row in enumerate(rows,1):
                if (row['name']!=row['record_id'] or type(row['attempt_number']) is not int
                        or row['attempt_number']!=number or row['request_sha256']!=issuance['artifact_sha256']):
                    raise DispatchStoreError('dispatch_attempt_history_binding')
                _identifier(row['record_id'])
            return tuple(MappingProxyType(dict(row)) for row in rows)

    def open_late_acceptance(self,issuance,encoded,ciphertext):
        with self._operation():
            if self._locked_issuances.get(issuance['record_id']) is not issuance:
                raise DispatchStoreError('dispatch_issuance_lock_required')
            return self._cipher.open(issuance['record_id'],'late-acceptance',encoded,ciphertext)

    def stage_late_acceptance(self,chain,issuance,proof):
        """Save a server-assessed explicit decision; never rewind attempt history.

        The owned service has authenticated both receipts and current source.
        Shared retry eligibility is repeated under the same held locks before
        revoking an expired/received-failure attempt. No commit or HTTP occurs.
        """
        from .late_acceptance_evidence import validate_proof,BODY,require_attempt_bindings
        from .retry_evidence import require_retry_evidence
        with self._operation():
            self._require_locked(chain,issuance)
            encoded=validate_proof(proof)
            if (any(issuance.get(key) is not None for key in ('late_acceptance_header','late_acceptance_ciphertext'))
                    or any(proof[key]!=issuance[key] for key in ('record_id','chain','artifact_sha256'))
                    or proof['prior_attempt']!=issuance['active_attempt']
                    or proof['prior_state']!=issuance['state'] or proof['prior_state_version']!=issuance['state_version']
                    or not self._latest_source(issuance)):
                raise DispatchStoreError('late_acceptance_current_required')
            now=self._sql('SELECT UTC_TIMESTAMP(6) AS utc_now')[0]['utc_now']
            require_retry_evidence(self,chain,issuance,attempt_id=proof['prior_attempt'],
                expected_fence=proof['prior_fence'],now_utc=now)
            ciphertext=self._cipher.seal(issuance['record_id'],'late-acceptance',encoded,BODY)
            require_attempt_bindings(self,issuance,proof)
            self._sql('UPDATE '+TABLE_ISSUANCE+' SET state=%s,late_acceptance_header=%s,late_acceptance_ciphertext=%s,'
                'state_version=state_version+1 WHERE name=%s AND state_version=%s AND active_attempt=%s',
                (ASSESSMENT_STATES[proof['outcome']],encoded.decode(),ciphertext,issuance['record_id'],issuance['state_version'],proof['prior_attempt']))
            self._changed_once()
            if chain['active_attempt']==proof['prior_attempt']:
                self._sql('UPDATE '+TABLE_CHAIN+' SET active_attempt=NULL,state_version=state_version+1 '
                    'WHERE name=%s AND state_version=%s',(chain['record_id'],chain['state_version']))
                self._changed_once()

    def stage_issuance(self, chain, header, exact_request_bytes, *, actor, occurred_at, publication_sha256=None,generation_origin=None):
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
            publication=None
            if publication_sha256 is not None:
                from .publication_source import PROFILE
                _fingerprint(publication_sha256)
                evidence=encode_record_header(dict(profile=PROFILE,source_sha256=header['source_sha256'],
                    publication_sha256=publication_sha256))
                publication=self._cipher.seal(header['record_id'],'publication-source',encoded,evidence)
            origin=None;origin_indexes=dict(origin_actor=None,origin_action=None,origin_method=None)
            if generation_origin is not None:
                from .issuance_origin import validate_origin
                evidence=validate_origin(generation_origin)
                if (generation_origin['actor']!=actor
                        or generation_origin['created_at_utc']!=occurred_at.strftime('%Y-%m-%dT%H:%M:%S.%f')):
                    raise DispatchStoreError('dispatch_origin_server_binding')
                origin=self._cipher.seal(header['record_id'],'issuance-origin',encoded,evidence)
                origin_indexes=dict(origin_actor=actor,origin_action=generation_origin['action'],origin_method=generation_origin['method'])
            values=dict(header,artifact_ciphertext=encrypted,publication_ciphertext=publication,origin_ciphertext=origin,**origin_indexes,
                state='PREPARED',state_version=0,active_attempt=None)
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
        """Bound current read/decrypt; no re-sign or network decision.

        A worker's earlier namespace/source read can have opened a repeatable-
        read snapshot before another worker committed this row. A shared current
        read must see its committed custody, not silently treat it as missing.
        """
        with self._operation():
            _identifier(record_id)
            rows=self._sql('SELECT '+','.join('`'+field+'`' for field in ARTIFACT_FIELDS)+
                ',SUBSTRING(artifact_ciphertext,1,%s) AS artifact_ciphertext FROM '+TABLE_ISSUANCE+
                ' WHERE name=%s LOCK IN SHARE MODE NOWAIT',
                (MAX_CIPHERTEXT_CHARS+1,record_id))
            if len(rows)!=1:raise DispatchStoreError('dispatch_issuance_missing')
            row=dict(rows[0]);encrypted=row.pop('artifact_ciphertext')
            encoded=_flat_header(row,ARTIFACT_FIELDS)
            if row['record_id']!=record_id:raise DispatchStoreError('dispatch_record_identity')
            opened=self._cipher.open(record_id,'artifact',encoded,encrypted)
            if hashlib.sha256(opened).hexdigest()!=row['artifact_sha256']:
                raise DispatchStoreError('dispatch_request_digest')
            return MappingProxyType(row),opened

    def open_origin(self,header):
        """NULL means unrecorded origin, never an automatic send authorization."""
        from .issuance_origin import validate_origin
        with self._operation():
            encoded=_flat_header(dict(header),ARTIFACT_FIELDS)
            rows=self._sql('SELECT origin_actor,origin_action,origin_method,SUBSTRING(origin_ciphertext,1,8193) AS origin_ciphertext '
                'FROM '+TABLE_ISSUANCE+' WHERE name=%s LOCK IN SHARE MODE NOWAIT',(header['record_id'],))
            if len(rows)!=1:raise DispatchStoreError('dispatch_origin_missing')
            row=rows[0]
            if row['origin_ciphertext'] is None:
                if any(row[field] is not None for field in ('origin_actor','origin_action','origin_method')):
                    raise DispatchStoreError('dispatch_origin_missing')
                return None
            if type(row['origin_ciphertext']) is not str or not 0<len(row['origin_ciphertext'])<=8192:
                raise DispatchStoreError('dispatch_origin_envelope')
            origin=dict(decode_record_header(self._cipher.open(header['record_id'],'issuance-origin',encoded,row['origin_ciphertext'])))
            validate_origin(origin)
            if any(row['origin_'+field]!=origin[field] for field in ('actor','action','method')):
                raise DispatchStoreError('dispatch_origin_index')
            return origin

    def open_publication(self, header):
        """Optional immutable generation-time projection; never backfill history.

        Its separate domain authenticates the exact existing artifact header,
        leaving original v1 request custody/AAD and request bytes unchanged. NULL
        means the old full-source comparison, never a newly inferred exemption.
        """
        with self._operation():
            from .publication_source import PROFILE
            encoded=_flat_header(dict(header),ARTIFACT_FIELDS)
            rows=self._sql('SELECT SUBSTRING(publication_ciphertext,1,%s) AS publication_ciphertext '
                'FROM '+TABLE_ISSUANCE+' WHERE name=%s LOCK IN SHARE MODE NOWAIT',
                (MAX_PUBLICATION_CIPHERTEXT_CHARS+1,header['record_id']))
            if len(rows)!=1:
                raise DispatchStoreError('dispatch_publication_missing')
            ciphertext=rows[0]['publication_ciphertext']
            if ciphertext is None:
                return None
            if type(ciphertext) is not str or not 0<len(ciphertext)<=MAX_PUBLICATION_CIPHERTEXT_CHARS:
                raise DispatchStoreError('dispatch_publication_size')
            raw=self._cipher.open(header['record_id'],'publication-source',encoded,ciphertext)
            evidence=decode_record_header(raw)
            if (set(evidence)!={'profile','source_sha256','publication_sha256'}
                    or evidence['profile']!=PROFILE or evidence['source_sha256']!=header['source_sha256']):
                raise DispatchStoreError('dispatch_publication_binding')
            _fingerprint(evidence['publication_sha256'])
            return evidence['publication_sha256']
