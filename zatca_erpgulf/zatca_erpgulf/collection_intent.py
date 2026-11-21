"""Borrowed durable requests for submitted native invoice collections.

Reuse the original parent connection, encrypted store and fixed worker. No ERP
commit/rollback, generation or transport occurs during collection registration.
The expected issuance and original actor are immutable; uncertain native delivery
is never converted to an ordinary retry by creating another request.
"""

from datetime import datetime,timezone

from .submission_intent import (
    ParentIntent,SubmissionIntentError,TABLE,METHOD,COLLECTION_BODY,validate_header,
    collection_source_key,collection_active_key,open_intent,fiscal_sha,require_intent_schema,
)
from .dispatch_store import DispatchStore
from .dispatch_record_codec import _identifier
from .permission_compat import saved_row_has_permission
from .zatca_runtime import is_zatca_invoice_enabled,resolve_zatca_phase,PHASE_2_VALUE


REVIEW='The invoice request could not be queued safely. Review the saved invoice and parent transaction before continuing the batch.'
QUEUE_REVIEW='The invoice transaction committed, but queue registration could not be confirmed. Review its saved request and issuance before retrying.'
FLAG='_zatca_native_collection_requests'


class CollectionSubmissionError(RuntimeError):
    def __init__(self,code,*,committed=False):
        self.code=code;self.fatal=True;self.diagnostic_logged=False
        self.template=QUEUE_REVIEW if committed else REVIEW
        super().__init__(self.template)


def _raise_review(runtime,translate,code,*,committed=False):
    review=CollectionSubmissionError(code,committed=committed)
    try:
        runtime.log_error(title='ZATCA collection request review',message=code)
        review.diagnostic_logged=True
    except Exception:
        pass  # A failed diagnostic writer must not erase the fatal boundary.
    try:
        runtime.throw(translate(review.template),exc=review)
    except CollectionSubmissionError:
        raise
    except Exception:
        pass
    raise review


def _current_chain(runtime,source,company):
    from .credential_settings import _resolve_owner_record_from_saved_company
    from .native_provider import _permitted
    hint=source.get('custom_zatca_issuing_unit')
    if type(hint) is str and hint.startswith('egs:'):
        return _identifier(hint[4:])
    def load(dt,name):
        doc=runtime.get_doc(dt,name,for_update=True)
        if (doc.doctype,doc.name)!=(dt,name):raise SubmissionIntentError('collection_owner_identity')
        _permitted(runtime,doc)
        return doc
    selected,_kind=_resolve_owner_record_from_saved_company(company,source,load_doc=load)
    return _identifier(selected.get('custom_zatca_native_chain'))


class CollectionIntent(ParentIntent):
    """A separate command slot, leaving original v1 submit custody unchanged."""
    def __init__(self,runtime,doctype,name,*,intent,expected_issuance_id=None):
        self.bind_parent(runtime,doctype,name,intent=intent)
        if intent not in ('manual','scheduled'):raise SubmissionIntentError('collection_operation')
        self.expected_input=expected_issuance_id
        if expected_issuance_id is not None:_identifier(expected_issuance_id)
        self.reused=False;self.state='STAGED';self.blocked=False
        self.source_doc,self.company,self.chain,self.digest,self.latest=self.snapshot()
        if expected_issuance_id is not None and (self.latest is None or self.latest['record_id']!=expected_issuance_id):
            raise SubmissionIntentError('collection_expected_issuance_changed')
        if not self.safe_latest():
            self.blocked=True;self.state='REVIEW';return
        # Open table MDL before inspecting its physical schema/index capacities.
        self.sql('SELECT name FROM '+TABLE+' LIMIT 0',())
        require_intent_schema(self);self.require_collection_schema()
        self.created=datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M:%S.%f')
        self.header=self.make_header()
        self.slot=self.header['active_key']
        generated=self.record_id
        # INSERT arbitrates the nullable unique slot using a current engine
        # lookup, even behind an older RR snapshot. A duplicate never overwrites
        # its actor/header/state, and missing-key gap locks are not taken first.
        self.insert(noop_duplicate=True)
        rows=self.sql('SELECT record_id,state FROM '+TABLE+' WHERE active_key=%s FOR UPDATE NOWAIT',(self.slot,))
        if len(rows)!=1:raise SubmissionIntentError('collection_slot_review')
        row=rows[0]
        if row['record_id']!=generated:
            old,header=open_intent(self,row['record_id'],lock=True)
            if any(header[key]!=self.header[key] for key in (
                    'active_key','expected_issuance_id','actor','chain','intent','source_sha256','company')):
                raise SubmissionIntentError('collection_slot_binding')
            if row['state']=='REVIEW' and intent=='manual' and self.safe_latest():
                # An explicit new manual action may release a failed command
                # only while native custody proves no uncertain/rejected send.
                self.sql('UPDATE '+TABLE+' SET active_key=NULL WHERE name=%s AND state=%s AND active_key=%s',
                    (row['record_id'],'REVIEW',self.slot))
                self.insert(noop_duplicate=False)
            else:
                self.record_id=row['record_id'];self.header=header;self.reused=True
                self.state=row['state'];self.finalized=True

    def require_collection_schema(self):
        rows=self.sql('SELECT column_name,character_maximum_length AS size,is_nullable FROM information_schema.columns '
            'WHERE table_schema=DATABASE() AND table_name=%s AND column_name IN (%s,%s,%s)',
            ('tabZATCA Submission Intent','active_key','expected_issuance_id','operation'))
        if (len(rows)!=3 or any(type(row['size']) is not int or row['size']<140 or row['is_nullable']!='YES' for row in rows)):
            raise SubmissionIntentError('collection_schema_review')
        rows=self.sql('SELECT index_name,non_unique,GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns_used '
            'FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=%s '
            'GROUP BY index_name,non_unique',('tabZATCA Submission Intent',))
        if not any(row['non_unique']==0 and row['columns_used']=='active_key' for row in rows):
            raise SubmissionIntentError('collection_slot_schema')

    def snapshot(self):
        self.require_owner();r=self.runtime
        source=r.get_doc(*self.source,for_update=True)
        company=r.get_doc('Company',source.company,for_update=True)
        if (source.doctype,source.name)!=self.source or source.docstatus!=1 or company.name!=source.company:
            raise SubmissionIntentError('collection_saved_source')
        for dt,operation,doc in ((source.doctype,'read',source),(source.doctype,'write',source),('Company','read',company)):
            if not saved_row_has_permission(r.has_permission,dt,operation,doc=doc,user=self.actor):
                raise SubmissionIntentError('collection_source_access')
        if not is_zatca_invoice_enabled(company) or resolve_zatca_phase(company)!=PHASE_2_VALUE:
            raise SubmissionIntentError('collection_company_policy')
        chain=_current_chain(r,source,company)
        repo=DispatchStore(self.database,storage_namespace=self.storage_namespace,cipher=self.cipher,owner_check=self.owner_current)
        latest=repo.latest_issuance(chain,*self.source)
        if latest is not None:
            header,_body=repo.open_issuance(latest['record_id'])
            if (header['company']!=company.name or header['chain']!=chain
                    or (header['source_doctype'],header['source_name'])!=self.source):
                raise SubmissionIntentError('collection_issuance_binding')
        return source,company,chain,fiscal_sha(source),latest

    def safe_latest(self):
        return (self.latest is None or self.latest['state'] in ('REPORTED','CLEARED')
            or self.latest['state']=='PREPARED' and self.latest['active_attempt'] is None)

    def make_header(self):
        expected=self.latest['record_id'] if self.latest is not None else None
        header=dict(record_id=self.record_id,source_key=collection_source_key(self.record_id),
            source_doctype=self.source[0],source_name=self.source[1],company=self.company.name,actor=self.actor,
            chain=self.chain,intent=self.intent,source_sha256=self.digest,created_at_utc=self.created,
            request_kind='collection-v1',expected_issuance_id=expected)
        header['active_key']=collection_active_key(header)
        validate_header(header)
        return header

    def insert(self,*,noop_duplicate):
        stamp=datetime.strptime(self.created,'%Y-%m-%dT%H:%M:%S.%f')
        self.sql('INSERT INTO '+TABLE+' (name,record_id,source_key,source_doctype,source_name,actor,active_key,'
            'expected_issuance_id,operation,state,state_version,owner,modified_by,creation,modified,docstatus) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,0)'+
            (' ON DUPLICATE KEY UPDATE name=name' if noop_duplicate else ''),
            (self.record_id,self.record_id,self.header['source_key'],*self.source,self.actor,self.slot,
             self.header['expected_issuance_id'],self.intent,'STAGED',self.actor,self.actor,stamp,stamp))

    def finalize(self,*,translate):
        self.require_owner()
        source,company,chain,digest,latest=self.snapshot()
        expected=latest['record_id'] if latest is not None else None
        if (company.name!=self.header['company'] or chain!=self.header['chain']
                or digest!=self.header['source_sha256'] or expected!=self.header['expected_issuance_id']):
            raise SubmissionIntentError('collection_source_changed_before_commit')
        if self.reused:return
        if self.finalized:raise SubmissionIntentError('collection_already_finalized')
        encoded=validate_header(self.header)
        cipher=self.cipher.seal(self.record_id,'collection-intent',encoded,COLLECTION_BODY)
        self.sql('UPDATE '+TABLE+' SET state=%s,state_version=1,intent_header=%s,intent_ciphertext=%s '
            'WHERE name=%s AND state=%s AND state_version=0 AND active_key=%s',
            ('READY',encoded.decode(),cipher,self.record_id,'STAGED',self.slot))
        if self.sql('SELECT ROW_COUNT() AS affected',())[0]['affected']!=1:
            raise SubmissionIntentError('collection_finalization_changed')
        self.finalized=True;self.state='READY'

    def result(self):
        return dict(status='REVIEW' if self.blocked or self.state=='REVIEW' else 'DEFERRED',accepted=False,
            request_id=None if self.blocked else self.record_id,source_doctype=self.source[0],source_name=self.source[1],
            reused=self.reused)


def _register(source,*,runtime,translate,intent,expected_issuance_id=None):
    from .native_provider import _selection
    selection=_selection(runtime,source.doctype,source.name,source)
    if selection is None:return None
    if not is_zatca_invoice_enabled(selection[1]) or resolve_zatca_phase(selection[1])!=PHASE_2_VALUE:
        return {'status':'SKIPPED','accepted':False,'reason':'company_policy_changed'}
    cache=runtime.flags.setdefault(FLAG,{})
    key=(runtime.local.site,runtime.session.user,source.doctype,source.name,intent)
    if key in cache:
        request=cache[key];request.require_owner()
        if expected_issuance_id is not None and request.header['expected_issuance_id']!=expected_issuance_id:
            raise SubmissionIntentError('collection_expected_issuance_changed')
        return request.result()
    for name in ('before_commit','after_commit','after_rollback'):
        if not callable(getattr(getattr(runtime.db,name,None),'add',None)):
            raise SubmissionIntentError('collection_callbacks_missing')
    request=CollectionIntent(runtime,source.doctype,source.name,intent=intent,expected_issuance_id=expected_issuance_id)
    if request.blocked:return request.result()
    armed={'ready':False,'cancelled':False}
    def cancel():
        armed['cancelled']=True;request.closed=True;cache.pop(key,None)
    def finalize():
        if armed['cancelled']:return
        failure=None
        try:
            if not armed['ready']:raise SubmissionIntentError('collection_early_commit')
            request.finalize(translate=translate)
        except Exception as error:
            failure=error.code if isinstance(error,SubmissionIntentError) else 'collection_finalization_unconfirmed'
        if failure is not None:_raise_review(runtime,translate,failure)
    def enqueue():
        if armed['cancelled']:return
        try:
            request.require_owner()
            if not armed['ready'] or not request.finalized:raise SubmissionIntentError('collection_unfinalized')
            if getattr(getattr(runtime.local,'flags',None),'in_migrate',False):raise SubmissionIntentError('collection_migration')
            if request.state in ('READY','WAITING'):
                runtime.enqueue(METHOD,queue='long',timeout=900,is_async=True,now=False,enqueue_after_commit=False,
                    job_id='zatca-intent-'+request.record_id,deduplicate=True,record_id=request.record_id)
        except Exception:
            failed=True
        else:failed=False
        request.closed=True;cache.pop(key,None)
        if failed:_raise_review(runtime,translate,'collection_queue_unknown',committed=True)
    try:
        runtime.db.before_commit.add(finalize);runtime.db.after_commit.add(enqueue);runtime.db.after_rollback.add(cancel)
        armed['ready']=True;cache[key]=request
    except Exception:
        cancel();raise
    return request.result()


def register_native_collection(source,*,runtime,translate,intent,expected_issuance_id=None):
    """Fixed internal collection callsites only; no RPC/build/actor override."""
    failure=None
    try:return _register(source,runtime=runtime,translate=translate,intent=intent,expected_issuance_id=expected_issuance_id)
    except Exception as error:
        failure=error.code if isinstance(error,SubmissionIntentError) else 'collection_registration_unconfirmed'
    _raise_review(runtime,translate,failure)
