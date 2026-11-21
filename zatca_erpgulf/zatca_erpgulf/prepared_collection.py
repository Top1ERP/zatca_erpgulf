"""Bounded first-send discovery from authenticated generation origin.

Immediate delivery resumes the original enabled actor/operation. A deferred
Background original gets the existing scheduler authorization. Missing origin,
changed policy, uncertain delivery and active commands never become blind retries.
No builder or authority transport runs in discovery.
"""

from .collection_intent import register_native_collection,CollectionSubmissionError
from .worker_transaction import owned_worker_transaction,current_database
from .native_onboarding import native_mode_enabled
from .native_provider import _permitted
from .native_dispatch import SOURCE_TABLES,read_retained_in_transaction
from .submission_intent_worker import _queue_as_actor,_enabled
from .permission_compat import saved_row_has_permission
from .zatca_runtime import is_zatca_invoice_enabled,resolve_zatca_phase,PHASE_2_VALUE,get_b2c_submission_method


MAX_BYTES=16*1024*1024


def _origin_access(runtime,source,company,actor):
    return all(saved_row_has_permission(runtime.has_permission,doc.doctype,operation,doc=doc,user=actor)
        for doc,operations in ((source,('read','write')),(company,('read',))) for operation in operations)


def _stage_candidate(runtime,database,candidate,provenance):
    """Only the clean post-discovery transaction is owned, for one fixed actor.

    Each candidate commits before actor restoration. No borrowed callback is
    carried into another actor, and no rollback follows an attempted COMMIT.
    """
    dt,name,expected,actor,operation=candidate
    if not provenance():raise CollectionSubmissionError('prepared_collection_owner_changed')
    with _queue_as_actor(runtime,actor):
        site=runtime.local.site;connection=database._conn;committing=False
        try:
            source=runtime.get_doc(dt,name)
            if not provenance():raise CollectionSubmissionError('prepared_collection_owner_changed')
            result=register_native_collection(source,runtime=runtime,translate=lambda s:s,
                intent=operation,expected_issuance_id=expected)
            count=int(result is not None and result['status']=='DEFERRED')
            if not provenance():raise CollectionSubmissionError('prepared_collection_owner_changed')
            committing=True
            database.commit()
            return count
        except Exception:
            failed=True
        if not committing:
            if (not provenance() or current_database(runtime) is not database or database._conn is not connection
                    or runtime.local.site!=site or runtime.session.user!=actor):
                raise CollectionSubmissionError('prepared_collection_owner_changed')
            database.rollback()  # Only this service's clean staging transaction.
        if failed:raise CollectionSubmissionError('prepared_collection_unconfirmed')


def discover_prepared_collections(*,runtime):
    """Internal cron only; no caller-selected actor, site, source or method."""
    if not native_mode_enabled(runtime):return 0
    database=current_database(runtime)
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise CollectionSubmissionError('prepared_collection_access')
        companies=database.sql('SELECT name FROM `tabCompany` ORDER BY name LIMIT 1025 LOCK IN SHARE MODE NOWAIT',as_dict=True)
        if len(companies)>1024:raise CollectionSubmissionError('prepared_collection_company_budget')
        policies=[]
        for row in companies:
            company=runtime.get_doc('Company',row['name']);_permitted(runtime,company)
            if is_zatca_invoice_enabled(company) and resolve_zatca_phase(company)==PHASE_2_VALUE:
                policies.append((company.name,get_b2c_submission_method(company)))
        if not policies:return 0
        clauses=' OR '.join('(i.company=%s AND i.origin_method=%s)' for _ in policies)
        parameters=tuple(value for pair in policies for value in pair)
        # Index fields only select candidates. Their protected capsule and normal
        # source ACLs must still agree before any actor switch or command staging.
        base=('SELECT i.record_id,i.source_doctype,i.source_name,i.company FROM `tabZATCA Issuance` i '
            'WHERE i.state=%s AND i.active_attempt IS NULL AND ('+clauses+') '
            'AND (i.origin_action=%s AND EXISTS (SELECT 1 FROM `tabUser` u WHERE u.name=i.origin_actor AND u.enabled=1) '
            'OR i.origin_action=%s AND i.origin_method=%s) '
            'AND NOT EXISTS (SELECT 1 FROM `tabZATCA Submission Intent` r WHERE r.expected_issuance_id=i.record_id '
            'AND r.active_key IS NOT NULL) ')
        values=('PREPARED',*parameters,'DISPATCH','PREPARE','Background')
        candidates=[];used=0;last=''
        for page in range(10):
            rows=database.sql(base+'AND i.name>%s ORDER BY i.name LIMIT 100 LOCK IN SHARE MODE NOWAIT',(*values,last),as_dict=True)
            if not rows:break
            for row in rows:
                last=row['record_id']
                if row['source_doctype'] not in SOURCE_TABLES:
                    raise CollectionSubmissionError('prepared_collection_identity')
                source=runtime.get_doc(row['source_doctype'],row['source_name'],for_update=True)
                company=runtime.get_doc('Company',source.company)
                _permitted(runtime,source,write=True);_permitted(runtime,company)
                if source.docstatus!=1 or source.company!=row['company']:
                    raise CollectionSubmissionError('prepared_collection_source')
                view=read_retained_in_transaction(source.doctype,source.name,runtime=runtime,owner=owner,
                    require_current_source=True,require_origin=True)
                if view is None or view.issuance_id!=row['record_id'] or view.state!='PREPARED' or view.attempt_id is not None:
                    raise CollectionSubmissionError('prepared_collection_original_changed')
                used+=len(view.original_xml)
                if used>MAX_BYTES:raise CollectionSubmissionError('prepared_collection_budget')
                origin=view.generation_origin
                if origin is None:raise CollectionSubmissionError('prepared_collection_origin_missing')
                if origin['method']!=get_b2c_submission_method(company):
                    raise CollectionSubmissionError('prepared_collection_policy_changed')
                if origin['action']=='DISPATCH':
                    actor=origin['actor'];operation='recovery'
                    if not _enabled(owner,actor) or not _origin_access(runtime,source,company,actor):continue
                elif origin['action']=='PREPARE' and origin['method']=='Background':
                    actor=owner.actor;operation='scheduled'
                else:continue
                candidates.append((source.doctype,source.name,view.issuance_id,actor,operation))
                if len(candidates)==100:break
            if len(candidates)==100 or len(rows)<100:break
        else:
            raise CollectionSubmissionError('prepared_collection_scan_budget')
        owner.require_owner()
        def provenance():
            connection=owner._connection
            return (current_database(runtime) is database and runtime.local.site==owner.site
                and runtime.conf.get('db_name')==owner.db_name
                and runtime.conf.get('encryption_key')==owner._encryption_text
                and database._conn is connection and connection._sock is owner._socket
                and connection.open and connection.get_autocommit() is False)
    count=0
    for candidate in candidates:
        if runtime.session.user!=owner.actor:raise CollectionSubmissionError('prepared_collection_actor_restore')
        count+=_stage_candidate(runtime,database,candidate,provenance)
    if not provenance() or runtime.session.user!=owner.actor:
        raise CollectionSubmissionError('prepared_collection_owner_changed')
    return count
