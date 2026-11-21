"""Authenticated durable native ERP handoff; no invoice generation or transport.

The parent writer borrows its existing connection and never commits/rolls back.
Only before-commit finalization makes an intent READY. Owned workers consume that
immutable source/actor/chain binding; queue delivery alone grants no authority.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from .dispatch_record_codec import _identifier, encode_record_header, decode_record_header
from .dispatch_storage_context import CONTROL, CONTROL_FIELDS, derive_storage_cipher, verify_storage_probe
from .dispatch_store import _fingerprint
from .issuing_observation import native_record_observation
from .publication_source import publication_source_sha256
from .saved_form_source import saved_form_name


TABLE = '`tabZATCA Submission Intent`'
METHOD = 'zatca_erpgulf.zatca_erpgulf.submission_intent_worker.execute_submission_intent'
BODY = b'zatca-committed-erp-handoff/v1'
FIELDS = ('record_id','source_key','source_doctype','source_name','company','actor','chain',
    'intent','source_sha256','created_at_utc')
COLLECTION_FIELDS = ('request_kind','active_key','expected_issuance_id')
COLLECTION_BODY = b'zatca-submitted-collection/v1'
CURRENT = ContextVar('zatca_submission_intent',default=None)


class SubmissionIntentError(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def source_key(doctype,name):
    if doctype not in ('Sales Invoice','POS Invoice'):
        raise SubmissionIntentError('submission_intent_source')
    saved_form_name(name)
    return hashlib.sha256((doctype+'\0'+name).encode()).hexdigest()


def fiscal_sha(source):
    value=publication_source_sha256((source.doctype,source.name),native_record_observation(source))
    if value is None:
        raise SubmissionIntentError('submission_intent_native_source_required')
    return value


def _chain(runtime,source,company):
    from .credential_settings import _resolve_owner_record_from_saved_company
    from .native_provider import _permitted
    hint=source.get('custom_zatca_issuing_unit')
    if type(hint) is str and hint.startswith('egs:'):
        return _identifier(hint[4:])
    def load(dt,name):
        record=runtime.get_doc(dt,name)
        if (record.doctype,record.name)!=(dt,name):
            raise SubmissionIntentError('submission_intent_owner')
        _permitted(runtime,record)
        return record
    selected,_kind=_resolve_owner_record_from_saved_company(company,source,load_doc=load)
    return _identifier(selected.get('custom_zatca_native_chain'))


def validate_header(header):
    if type(header) is not dict or set(header) not in (set(FIELDS),set(FIELDS+COLLECTION_FIELDS)):
        raise SubmissionIntentError('submission_intent_header')
    _identifier(header['record_id']);_identifier(header['chain'])
    for key in ('company','actor'):saved_form_name(header[key])
    if header['actor']=='Guest' or header['intent'] not in ('submit','scheduled','manual'):
        raise SubmissionIntentError('submission_intent_actor_or_operation')
    base_key=source_key(header['source_doctype'],header['source_name'])
    collection='request_kind' in header
    expected_key=collection_source_key(header['record_id']) if collection else base_key
    if expected_key!=header['source_key']:
        raise SubmissionIntentError('submission_intent_source_binding')
    if collection:
        if header['request_kind']!='collection-v1' or header['intent'] not in ('manual','scheduled'):
            raise SubmissionIntentError('submission_intent_collection_kind')
        if header['expected_issuance_id'] is not None:
            _identifier(header['expected_issuance_id'])
        if header['active_key']!=collection_active_key(header):
            raise SubmissionIntentError('submission_intent_active_binding')
    _fingerprint(header['source_sha256'])
    try:
        value=datetime.strptime(header['created_at_utc'],'%Y-%m-%dT%H:%M:%S.%f')
    except (ValueError,TypeError):
        raise SubmissionIntentError('submission_intent_clock') from None
    if value.strftime('%Y-%m-%dT%H:%M:%S.%f')!=header['created_at_utc']:
        raise SubmissionIntentError('submission_intent_clock')
    return encode_record_header(header)


def collection_source_key(record_id):
    return hashlib.sha256(('collection\0'+_identifier(record_id)).encode()).hexdigest()


def collection_active_key(header):
    values=[source_key(header['source_doctype'],header['source_name'])]
    values.extend(header[key] for key in ('company','actor','chain','intent','source_sha256'))
    values.append(header['expected_issuance_id'] or '')
    if any(type(value) is not str or '\0' in value for value in values):
        raise SubmissionIntentError('submission_intent_active_binding')
    return hashlib.sha256(('collection-v1\0'+'\0'.join(values)).encode()).hexdigest()


def envelope_kind(header):
    return 'collection-intent' if 'request_kind' in header else 'submission-intent'


def open_intent(owner,record_id,*,lock=False):
    _identifier(record_id);owner.require_owner()
    rows=owner.database.sql('SELECT record_id,source_key,source_doctype,source_name,actor,state,fence_token,'
        'active_key,expected_issuance_id,operation,'
        'SUBSTRING(intent_header,1,8193) AS intent_header,SUBSTRING(intent_ciphertext,1,8193) AS intent_ciphertext '
        'FROM '+TABLE+' WHERE name=%s'+(' FOR UPDATE NOWAIT' if lock else ' LOCK IN SHARE MODE NOWAIT'),
        (record_id,),as_dict=True)
    owner.require_owner()
    if len(rows)!=1:
        raise SubmissionIntentError('submission_intent_missing')
    row=rows[0]
    if row['state'] not in ('READY','WAITING','RUNNING','COMPLETE','REVIEW'):
        raise SubmissionIntentError('submission_intent_unfinalized')
    if any(type(row[key]) is not str or not 0<len(row[key])<=8192 for key in ('intent_header','intent_ciphertext')):
        raise SubmissionIntentError('submission_intent_envelope')
    header=dict(decode_record_header(row['intent_header'].encode()))
    encoded=validate_header(header)
    if any(row[key]!=header[key] for key in ('record_id','source_key','source_doctype','source_name','actor')) or header['record_id']!=record_id:
        raise SubmissionIntentError('submission_intent_index_binding')
    collection='request_kind' in header
    if collection:
        if (row['expected_issuance_id']!=header['expected_issuance_id'] or row['operation']!=header['intent']
                or row['active_key'] not in (None,header['active_key'])
                or row['state'] in ('READY','WAITING','RUNNING') and row['active_key']!=header['active_key']):
            raise SubmissionIntentError('submission_intent_collection_index')
    elif any(row[key] is not None for key in ('active_key','expected_issuance_id','operation')):
        raise SubmissionIntentError('submission_intent_collection_index')
    if owner.cipher.open(record_id,envelope_kind(header),encoded,row['intent_ciphertext'])!=(COLLECTION_BODY if collection else BODY):
        raise SubmissionIntentError('submission_intent_integrity')
    return row,header


def require_intent_schema(owner):
    """Inspect after opening table MDL; never repair an installed schema.

    Parent rollback must remove the staged row. Unique source/record slots and
    sufficient text capacity cannot depend on SQL mode or silent truncation.
    """
    sql = owner.sql
    rows = sql('SELECT table_name,engine FROM information_schema.tables '
        'WHERE table_schema=DATABASE() AND table_name IN (%s,%s)',
        ('tabZATCA Submission Intent', 'tabSingles'))
    if len(rows) != 2 or any(row['engine'] != 'InnoDB' for row in rows):
        raise SubmissionIntentError('submission_intent_transactional_schema')
    rows = sql('SELECT column_name,data_type,character_maximum_length AS max_chars,'
        'character_octet_length AS max_bytes FROM information_schema.columns '
        'WHERE table_schema=DATABASE() AND table_name=%s', ('tabZATCA Submission Intent',))
    columns = {row['column_name']: row for row in rows}
    required = dict.fromkeys(('name','record_id','source_key','source_doctype','source_name',
        'actor','state','fence_token','result_code','owner','modified_by'),140)
    required.update(intent_header=8192,intent_ciphertext=8192)
    for name, length in required.items():
        row = columns.get(name)
        if (row is None or row['data_type'] not in ('char','varchar','text','mediumtext','longtext')
                or type(row['max_chars']) is not int or row['max_chars'] < length
                or type(row['max_bytes']) is not int or row['max_bytes'] < length * 4):
            raise SubmissionIntentError('submission_intent_capacity')
    rows = sql('SELECT index_name,non_unique,GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns_used '
        'FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=%s '
        'GROUP BY index_name,non_unique', ('tabZATCA Submission Intent',))
    unique = {row['columns_used'] for row in rows if row['non_unique'] == 0}
    if not {'name','record_id','source_key'} <= unique:
        raise SubmissionIntentError('submission_intent_unique_slots')


class ParentIntent:
    """Pinned borrowed parent transaction; no ownership of fiscal commit/rollback."""
    def __init__(self,runtime,doctype,name,*,intent='submit'):
        self.bind_parent(runtime,doctype,name,intent=intent)
        self.stage_initial()

    def bind_parent(self,runtime,doctype,name,*,intent):
        """Shared borrowed connection/key acquisition, without staging a request."""
        from .worker_transaction import current_database
        self.runtime=runtime;self.database=current_database(runtime);self.site=runtime.local.site;self.actor=runtime.session.user
        self.key=runtime.conf.get('encryption_key');self.db_name=runtime.conf.get('db_name')
        self.connection=self.database._conn;self.socket=getattr(self.connection,'_sock',None)
        self.record_id=str(uuid4());self.source=(doctype,name);self.intent=intent
        self.finalized=False;self.closed=False
        self.require_owner()
        saved_form_name(self.actor)
        if self.actor == 'Guest' or intent not in ('submit','scheduled','manual'):
            raise SubmissionIntentError('submission_intent_actor_or_operation')
        rows=self.sql('SELECT DATABASE() AS db_name',())
        if len(rows)!=1 or rows[0].get('db_name')!=self.db_name:
            raise SubmissionIntentError('submission_intent_database')
        rows=self.sql('SELECT field,SUBSTRING(value,1,513) AS value FROM `tabSingles` '
            'WHERE doctype=%s AND field IN (%s,%s,%s) LOCK IN SHARE MODE NOWAIT',(CONTROL,*CONTROL_FIELDS))
        values={row['field']:row['value'] for row in rows}
        if len(rows)!=3 or set(values)!=set(CONTROL_FIELDS) or values['storage_version']!='1':
            raise SubmissionIntentError('submission_intent_storage')
        self.storage_namespace=values['storage_namespace']
        self.cipher=derive_storage_cipher(self.key,site=self.site,namespace=self.storage_namespace)
        verify_storage_probe(self.cipher,self.storage_namespace,values['storage_key_check'])

    def stage_initial(self):
        # Open table metadata without locking a missing-key gap: unrelated ERP
        # invoices must not deadlock solely because this outbox starts empty.
        # The unique source slot arbitrates a concurrent insert, even when an
        # older parent snapshot cannot see its existing committed row.
        rows=self.sql('SELECT name FROM '+TABLE+' WHERE source_key=%s LIMIT 1',(source_key(*self.source),))
        require_intent_schema(self)
        if rows:
            raise SubmissionIntentError('submission_intent_existing_review')
        stamp=datetime.now(timezone.utc).replace(tzinfo=None)
        self.created=stamp.strftime('%Y-%m-%dT%H:%M:%S.%f')
        self.sql('INSERT INTO '+TABLE+' (name,record_id,source_key,source_doctype,source_name,actor,state,'
            'state_version,owner,modified_by,creation,modified,docstatus) VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,0)',
            (self.record_id,self.record_id,source_key(*self.source),*self.source,self.actor,'STAGED',self.actor,self.actor,stamp,stamp))

    def require_owner(self):
        from .worker_transaction import current_database
        r=self.runtime;c=self.connection
        if (self.closed or current_database(r) is not self.database or r.local.site!=self.site
                or r.session.user!=self.actor or r.conf.get('db_name')!=self.db_name or r.conf.get('encryption_key')!=self.key
                or self.database.db_type!='mariadb' or self.database._conn is not c or c._sock is not self.socket
                or self.socket is None or not c.open or c.get_autocommit() is not False
                or getattr(self.database,'auto_commit_on_many_writes',None) not in (False,0)):
            raise SubmissionIntentError('submission_intent_parent_binding')

    def sql(self,statement,values):
        self.require_owner();rows=self.database.sql(statement,values,as_dict=True);self.require_owner();return rows

    def finalize(self,*,translate):
        from .deferred_submission import _require_source
        from .native_provider import _selection
        from .zatca_runtime import is_zatca_invoice_enabled,resolve_zatca_phase,PHASE_2_VALUE
        self.require_owner()
        if self.finalized:
            raise SubmissionIntentError('submission_intent_already_finalized')
        source,company=_require_source(self.runtime,translate,*self.source)
        if (not is_zatca_invoice_enabled(company) or resolve_zatca_phase(company)!=PHASE_2_VALUE
                or _selection(self.runtime,*self.source,source) is None):
            raise SubmissionIntentError('submission_intent_policy_changed')
        header=dict(record_id=self.record_id,source_key=source_key(*self.source),source_doctype=self.source[0],
            source_name=self.source[1],company=company.name,actor=self.actor,chain=_chain(self.runtime,source,company),
            intent=self.intent,source_sha256=fiscal_sha(source),created_at_utc=self.created)
        encoded=validate_header(header)
        sealed=self.cipher.seal(self.record_id,'submission-intent',encoded,BODY)
        self.sql('UPDATE '+TABLE+' SET state=%s,intent_header=%s,intent_ciphertext=%s,state_version=1 '
            'WHERE name=%s AND state=%s AND state_version=0',('READY',encoded.decode(),sealed,self.record_id,'STAGED'))
        if self.sql('SELECT ROW_COUNT() AS affected',())[0]['affected']!=1:
            raise SubmissionIntentError('submission_intent_finalize_changed')
        self.finalized=True

    def owner_current(self):
        try:self.require_owner()
        except Exception:return False
        return True


@dataclass(repr=False)
class _Execution:
    site: str
    actor: str
    header: dict
    closed: bool=False

    def __reduce_ex__(self,protocol):raise TypeError('submission_intent_context_not_serializable')


@contextmanager
def execution_context(runtime,header):
    if CURRENT.get() is not None or runtime.session.user!=header['actor']:
        raise SubmissionIntentError('submission_intent_execution_context')
    validate_header(header)
    current=_Execution(runtime.local.site,runtime.session.user,header);token=CURRENT.set(current)
    try:yield
    finally:current.closed=True;CURRENT.reset(token)


def require_bound_source(runtime,source,chain_id):
    current=CURRENT.get()
    if current is None:return
    h=current.header
    if (current.closed or runtime.local.site!=current.site or runtime.session.user!=current.actor
            or (source.doctype,source.name)!=(h['source_doctype'],h['source_name'])
            or source.company!=h['company'] or chain_id!=h['chain'] or fiscal_sha(source)!=h['source_sha256']):
        raise SubmissionIntentError('submission_intent_source_changed')
