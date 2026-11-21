"""Age-independent native PREPARED discovery, without generation or transport.

Only a clean internal scheduler transaction is owned here. Saved-source ACLs,
current Company Background policy and authenticated native custody precede a
fixed collection request. Existing unknown/rejected/active commands are held.
"""

from .collection_intent import register_native_collection,CollectionSubmissionError
from .dispatch_store import DispatchStore
from .worker_transaction import owned_worker_transaction,current_database
from .native_onboarding import native_mode_enabled
from .native_provider import _permitted
from .zatca_runtime import is_zatca_invoice_enabled,resolve_zatca_phase,PHASE_2_VALUE,get_b2c_submission_method


MAX_BYTES=16*1024*1024


def discover_prepared_collections(*,runtime):
    """Internal scheduled action, no caller-selected actor/source/method or site."""
    if not native_mode_enabled(runtime):return 0
    database=current_database(runtime)
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):
            raise CollectionSubmissionError('prepared_collection_access')
        # Resolve policy through the existing alias reader, not a hard-coded
        # optional SQL column. Batches companies cannot occupy the first page
        # forever and hide older eligible Background issuances.
        companies=database.sql('SELECT name FROM `tabCompany` ORDER BY name LIMIT 1025 LOCK IN SHARE MODE NOWAIT',as_dict=True)
        if len(companies)>1024:raise CollectionSubmissionError('prepared_collection_company_budget')
        eligible=[]
        for row in companies:
            company=runtime.get_doc('Company',row['name']);_permitted(runtime,company)
            if (is_zatca_invoice_enabled(company) and resolve_zatca_phase(company)==PHASE_2_VALUE
                    and get_b2c_submission_method(company)=='Background'):
                eligible.append(company.name)
        if not eligible:return 0
        rows=database.sql('SELECT i.record_id FROM `tabZATCA Issuance` i WHERE i.state=%s '
            'AND i.company IN ('+','.join('%s' for _ in eligible)+') '
            'AND i.active_attempt IS NULL AND NOT EXISTS (SELECT 1 FROM `tabZATCA Submission Intent` r '
            'WHERE r.expected_issuance_id=i.record_id AND r.operation=%s AND r.actor=%s AND r.active_key IS NOT NULL) '
            'ORDER BY i.creation,i.name LIMIT 100 LOCK IN SHARE MODE NOWAIT',('PREPARED',*eligible,'scheduled',owner.actor),as_dict=True)
        repo=DispatchStore(database,storage_namespace=owner.storage_namespace,cipher=owner.cipher,owner_check=owner.owner_current)
        candidates=[];used=0
        for row in rows:
            header,body=repo.open_issuance(row['record_id']);used+=len(body)
            if used>MAX_BYTES:raise CollectionSubmissionError('prepared_collection_budget')
            source=runtime.get_doc(header['source_doctype'],header['source_name'])
            company=runtime.get_doc('Company',source.company)
            _permitted(runtime,source,write=True);_permitted(runtime,company)
            if source.docstatus!=1 or source.company!=header['company']:
                raise CollectionSubmissionError('prepared_collection_source')
            if (is_zatca_invoice_enabled(company) and resolve_zatca_phase(company)==PHASE_2_VALUE
                    and get_b2c_submission_method(company)=='Background'):
                candidates.append((source.doctype,source.name,header['record_id']))
    if not candidates:return 0
    # The preceding owned read scope rejected parent writes/callbacks and ended
    # its snapshot. Only this service's request staging follows on that same
    # pinned connection. Once COMMIT starts, its outcome is never compensated.
    site=runtime.local.site;actor=runtime.session.user;connection=database._conn
    committing=False
    try:
        count=0
        for dt,name,expected in candidates:
            source=runtime.get_doc(dt,name)
            result=register_native_collection(source,runtime=runtime,translate=lambda s:s,intent='scheduled',expected_issuance_id=expected)
            if result is not None and result['status']=='DEFERRED':count+=1
        committing=True
        database.commit()
        return count
    except Exception:
        failed=True
    if not committing:
        if (current_database(runtime) is not database or database._conn is not connection
                or runtime.local.site!=site or runtime.session.user!=actor):
            raise CollectionSubmissionError('prepared_collection_owner_changed')
        database.rollback()  # Only the clean transaction acquired by this service.
    if failed:raise CollectionSubmissionError('prepared_collection_unconfirmed')
