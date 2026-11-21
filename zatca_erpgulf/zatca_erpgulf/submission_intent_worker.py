"""Fixed durable-intent worker and READY rediscovery; never blind HTTP retry.

Only authenticated committed headers select the original actor/source/chain.
RUNNING/REVIEW rows are not automatically reclaimed: native custody and explicit
operator recovery must resolve uncertain work. Ordinary worker role retries
cannot silently upgrade a saved actor to Administrator.
"""

from contextlib import contextmanager
from uuid import uuid4

from .submission_intent import (
    TABLE,METHOD,SubmissionIntentError,open_intent,execution_context,require_bound_source,_chain,
)
from .worker_transaction import owned_worker_transaction,current_database


def _enabled(owner,actor):
    owner.require_owner()
    rows=owner.database.sql('SELECT enabled FROM `tabUser` WHERE name=%s LOCK IN SHARE MODE NOWAIT',
        (actor,),as_dict=True)
    owner.require_owner()
    return len(rows)==1 and rows[0].get('enabled')==1


def _claim(runtime,record_id):
    with owned_worker_transaction(runtime) as owner:
        row,header=open_intent(owner,record_id,lock=True)
        if owner.actor!=header['actor']:
            raise SubmissionIntentError('submission_intent_actor_changed')
        if row['state'] not in ('READY','WAITING'):
            return header,None,row['state']
        if not _enabled(owner,header['actor']):
            owner.database.sql('UPDATE '+TABLE+' SET state=%s,result_code=%s,modified=UTC_TIMESTAMP(6),state_version=state_version+1 WHERE name=%s',
                ('REVIEW','actor_disabled',record_id))
            owner.commit()
            return header,None,'REVIEW'
        fence=str(uuid4())
        owner.database.sql('UPDATE '+TABLE+' SET state=%s,fence_token=%s,modified=UTC_TIMESTAMP(6),started_at_utc=UTC_TIMESTAMP(6),'
            'state_version=state_version+1 WHERE name=%s AND state=%s',('RUNNING',fence,record_id,row['state']))
        if owner.database.sql('SELECT ROW_COUNT() AS affected',as_dict=True)[0]['affected']!=1:
            raise SubmissionIntentError('submission_intent_claim_changed')
        owner.commit()
        return header,fence,'RUNNING'


def _finish(runtime,header,fence,state,code):
    if state not in ('COMPLETE','REVIEW','WAITING'):
        raise SubmissionIntentError('submission_intent_finish_state')
    with owned_worker_transaction(runtime) as owner:
        row,current=open_intent(owner,header['record_id'],lock=True)
        if (current!=header or owner.actor!=header['actor'] or row['state']!='RUNNING' or row['fence_token']!=fence):
            raise SubmissionIntentError('submission_intent_completion_fence')
        owner.database.sql('UPDATE '+TABLE+' SET state=%s,result_code=%s,modified=UTC_TIMESTAMP(6),finished_at_utc=UTC_TIMESTAMP(6),'
            'state_version=state_version+1 WHERE name=%s AND state=%s AND fence_token=%s',
            (state,code,header['record_id'],'RUNNING',fence))
        if owner.database.sql('SELECT ROW_COUNT() AS affected',as_dict=True)[0]['affected']!=1:
            raise SubmissionIntentError('submission_intent_completion_changed')
        if 'request_kind' in header and state=='COMPLETE':
            owner.database.sql('UPDATE '+TABLE+' SET active_key=NULL WHERE name=%s AND active_key=%s',
                (header['record_id'],header['active_key']))
        owner.commit()


def _process(runtime,translate,header,build,fence):
    # This worker owns the persistent review boundary. The ordinary facade and
    # deferred source reviewer insert Error Log rows outside owned transactions;
    # using those wrappers here would dirty the connection before _finish. Use
    # the same raw native policy, which still reloads normal source/Company ACLs,
    # and retain only the static English result in the fenced intent record.
    from .native_provider import _run
    source=runtime.get_doc(header['source_doctype'],header['source_name'])
    company=runtime.get_doc('Company',source.company)
    with execution_context(runtime,header,fence):
        require_bound_source(runtime,source,_chain(runtime,source,company))
        if header.get('request_kind')=='correction-v1':
            from .corrected_preparation import run_corrected_command
            result=run_corrected_command(header,runtime=runtime,translate=translate,build=build)
        else:
            result=_run(source.doctype,source.name,runtime=runtime,translate=translate,
                build=build,intent=header['intent'],source=source,
                **({'expected_issuance_id':header['expected_issuance_id']} if 'request_kind' in header else {}),
                **({field:header[field] for field in ('retry_attempt_id','retry_fence_token')} if header.get('request_kind')=='retry-v1' else {}))
    if result is None:
        raise SubmissionIntentError('submission_intent_native_owner_missing')
    return result


def run_submission_intent(record_id,*,runtime,translate,build):
    """Internal injectable test seam; the queue entry supplies a fixed builder."""
    header,fence,state=_claim(runtime,record_id)
    if fence is None:
        return {'status':state,'intent_id':record_id}
    try:
        result=_process(runtime,translate,header,build,fence)
        status=result.get('status')
        done=status=='PREPARED' or status=='SUCCESS' and result.get('accepted') is True
        code='prepared' if status=='PREPARED' else 'accepted' if done else 'native_operation_review'
        state='COMPLETE' if done else 'REVIEW'
        if (header['intent'] in ('scheduled','recovery') and type(result) is dict
                and result.get('accepted') is False
                and result=={'status':'SKIPPED','accepted':False,'reason':'outside_company_window'}):
            # The provider returned before generation/reservation/transport.
            # This is a fresh scheduled policy check, never an unknown retry.
            state,code='WAITING','outside_company_window'
    except Exception:
        # Raw framework/signing/HTTP child text may contain private data. Native
        # custody owns delivery outcome; a generic exception is never rejection.
        state,code='REVIEW','native_operation_review'
        result={'status':'REVIEW','accepted':False}
    _finish(runtime,header,fence,state,code)
    return {'status':state,'intent_id':record_id,'operation_status':result.get('status')}


def execute_submission_intent(record_id):
    """Internal queue target, no RPC and no caller-selected process or actor."""
    import frappe
    from frappe import _
    def build(source):
        if source.doctype=='Sales Invoice':
            from .sign_invoice import _process_submitted_invoice
        else:
            from .pos_sign import _process_submitted_invoice
        return _process_submitted_invoice(source,bypass_background_check=True)
    try:
        return run_submission_intent(record_id,runtime=frappe,translate=_,build=build)
    except Exception as error:
        code=error.code if isinstance(error,SubmissionIntentError) else 'submission_intent_worker_review'
    frappe.log_error(title='ZATCA durable submission review',message=code)
    raise SubmissionIntentError(code)


_MISSING=object()


@contextmanager
def _queue_as_actor(runtime,actor):
    """Trusted internal rediscovery only; restore inspected Frappe15/16 state."""
    fields=('cache','form_dict','jenv','role_permissions','new_doc_templates','user_perms')
    session=runtime.session;local=runtime.local;site=local.site;database=current_database(runtime)
    old_user=session.user
    saved_session={name:getattr(session,name,_MISSING) for name in ('user','sid','data')}
    saved_local={name:getattr(local,name,_MISSING) for name in fields}
    try:
        runtime.set_user(actor)
        if local.site!=site or current_database(runtime) is not database or runtime.session is not session or session.user!=actor:
            raise SubmissionIntentError('submission_intent_queue_context')
        yield
    finally:
        runtime.set_user(old_user)
        for target,values in ((session,saved_session),(local,saved_local)):
            for name,value in values.items():
                if value is _MISSING:
                    if hasattr(target,name):delattr(target,name)
                else:setattr(target,name,value)


def rediscover_ready_intents(*,runtime):
    """Bounded READY/WAITING recovery without an invoice-age horizon or transport.

    Authenticated actors are reloaded before enqueue. RUNNING/REVIEW and later
    Background/Batches dispatch are separate operator/discovery lifecycle work.
    No caller-configured method, site, source, credentials or actor is accepted.
    """
    from .native_onboarding import native_mode_enabled
    if not native_mode_enabled(runtime):return 0
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise SubmissionIntentError('submission_intent_recovery_access')
        rows=owner.database.sql('SELECT record_id FROM '+TABLE+' WHERE state IN (%s,%s) '
            'ORDER BY modified,name LIMIT 100 LOCK IN SHARE MODE NOWAIT',('READY','WAITING'),as_dict=True)
        headers=[]
        disabled=[]
        for row in rows:
            record,header=open_intent(owner,row['record_id'],lock=True)
            if record['state'] in ('READY','WAITING'):
                if _enabled(owner,header['actor']):
                    headers.append(header)
                else:
                    disabled.append(header['record_id'])
        # Authenticate the entire bounded batch before changing any state. A
        # disabled actor must not occupy a discoverable slot forever and starve
        # later work. This administrative hold changes no source or authority
        # outcome, and never changes the immutable original actor/header.
        for record_id in disabled:
            owner.database.sql('UPDATE '+TABLE+' SET state=%s,result_code=%s,modified=UTC_TIMESTAMP(6),'
                'modified_by=%s,state_version=state_version+1 WHERE name=%s AND state IN (%s,%s)',
                ('REVIEW','actor_disabled',owner.actor,record_id,'READY','WAITING'))
            if owner.database.sql('SELECT ROW_COUNT() AS affected',as_dict=True)[0]['affected']!=1:
                raise SubmissionIntentError('submission_intent_disabled_hold_changed')
        if disabled:
            owner.commit()
    count=0
    for header in headers:
        with _queue_as_actor(runtime,header['actor']):
            if getattr(getattr(runtime.local,'flags',None),'in_migrate',False):
                raise SubmissionIntentError('submission_intent_migration_context')
            runtime.enqueue(METHOD,queue='long',timeout=900,is_async=True,now=False,enqueue_after_commit=False,
                job_id='zatca-intent-'+header['record_id'],deduplicate=True,record_id=header['record_id'])
            count+=1
    return count


def recover_submission_intents():
    import frappe
    try:
        from .prepared_collection import discover_prepared_collections
        queued=rediscover_ready_intents(runtime=frappe)
        return queued+discover_prepared_collections(runtime=frappe)
    except Exception as error:
        code=error.code if isinstance(error,SubmissionIntentError) else 'submission_intent_recovery_review'
    frappe.log_error(title='ZATCA durable handoff recovery',message=code)
    raise SubmissionIntentError(code)
