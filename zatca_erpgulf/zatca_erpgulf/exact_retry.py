"""Explicit exact-original retry commands; never automatic unknown-outcome replay.

Use the existing intent store/worker and source/attempt reservation fences. The
reviewer authorizes only one existing version and prior attempt. No invoice
generation, source repair, parent commit/rollback or transport occurs in staging.
"""

import frappe
from frappe import _

from .collection_intent import CollectionIntent,arm_collection_request,CollectionSubmissionError
from .dispatch_record_codec import _identifier
from .dispatch_store import DispatchStore
from .native_dispatch import SOURCE_TABLES,read_retained_in_transaction
from .native_onboarding import native_mode_enabled
from .native_provider import _permitted
from .operation_messages import mute_operation_messages
from .retry_evidence import require_retry_evidence
from .worker_transaction import owned_worker_transaction


REVIEW = 'The exact retry could not be registered safely. Review the saved original, current attempt, reservation expiry and response. No invoice was regenerated or sent by this action.'
REGISTERED = 'An explicit retry request for the same saved original was registered and will be queued after commit. The previous attempt may already have been received. This is not ZATCA acceptance; XML, UUID, hash and invoice counter stay unchanged.'
FLAG='_zatca_exact_retry_requests'


class ExactRetryError(RuntimeError):
    http_status_code=417
    def __init__(self,code,message=REVIEW):
        self.code=code;self.fatal=True
        super().__init__(message)


def _inspect_retry(issuance_id,attempt_id,fence_token,*,runtime):
    for value in (issuance_id,attempt_id,fence_token):_identifier(value)
    if not native_mode_enabled(runtime):raise ExactRetryError('exact_retry_rollout_disabled')
    with owned_worker_transaction(runtime) as owner:
        if 'System Manager' not in runtime.get_roles(owner.actor):raise ExactRetryError('exact_retry_access')
        rows=owner.database.sql('SELECT record_id,source_doctype,source_name,company,chain FROM `tabZATCA Issuance` '
            'WHERE name=%s LOCK IN SHARE MODE NOWAIT',(issuance_id,),as_dict=True)
        owner.require_owner()
        if len(rows)!=1 or rows[0]['record_id']!=issuance_id or rows[0]['source_doctype'] not in SOURCE_TABLES:
            raise ExactRetryError('exact_retry_identity')
        row=rows[0];source=runtime.get_doc(row['source_doctype'],row['source_name'])
        company=runtime.get_doc('Company',source.company)
        _permitted(runtime,source,write=True);_permitted(runtime,company)
        if source.company!=row['company']:raise ExactRetryError('exact_retry_source')
        repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        chain=repository.lock_chain_reference(row['chain'])
        view=read_retained_in_transaction(source.doctype,source.name,runtime=runtime,owner=owner,require_current_source=True)
        if view is None or view.issuance_id!=issuance_id or view.attempt_id!=attempt_id:
            raise ExactRetryError('exact_retry_version_or_attempt')
        issuance=repository.lock_issuance(chain,issuance_id)
        require_retry_evidence(repository,chain,issuance,attempt_id=attempt_id,
            expected_fence=fence_token,now_utc=owner.utc_now())
        return source.doctype,source.name


class RetryIntent(CollectionIntent):
    """Same callback/slot lifecycle, with a separate immutable retry envelope."""
    OPERATIONS=('retry',)
    REPLACE_REVIEW_OPERATIONS=('retry',)

    def __init__(self,runtime,doctype,name,*,issuance_id,attempt_id,fence_token):
        for value in (issuance_id,attempt_id,fence_token):_identifier(value)
        self.approved_attempt=attempt_id;self.approved_fence=fence_token
        super().__init__(runtime,doctype,name,intent='retry',expected_issuance_id=issuance_id)

    def snapshot(self):
        observed=super().snapshot()
        _source,_company,chain_id,_digest,latest=observed
        if latest is None or latest['record_id']!=self.expected_input:
            raise ExactRetryError('exact_retry_version_changed')
        if latest['state'] not in ('REPORTED','CLEARED'):
            repository=DispatchStore(self.database,storage_namespace=self.storage_namespace,
                cipher=self.cipher,owner_check=self.owner_current)
            chain=repository.lock_chain_reference(chain_id)
            issuance=repository.lock_issuance(chain,latest['record_id'])
            now=self.sql('SELECT UTC_TIMESTAMP(6) AS utc_now',())[0]['utc_now']
            require_retry_evidence(repository,chain,issuance,attempt_id=self.approved_attempt,
                expected_fence=self.approved_fence,now_utc=now)
        return observed

    def safe_latest(self):return self.latest is not None  # snapshot already proved eligibility or accepted race.

    def header_fields(self):
        return dict(super().header_fields(),request_kind='retry-v1',
            retry_attempt_id=self.approved_attempt,retry_fence_token=self.approved_fence)


def register_exact_retry(issuance_id,attempt_id,fence_token,*,runtime,translate):
    dt,name=_inspect_retry(issuance_id,attempt_id,fence_token,runtime=runtime)
    cache=runtime.flags.setdefault(FLAG,{})
    key=(runtime.local.site,runtime.session.user,issuance_id,attempt_id,fence_token)
    if key in cache:
        cache[key].require_owner();return dict(cache[key].result(),issuance_id=issuance_id)
    for event in ('before_commit','after_commit','after_rollback'):
        if not callable(getattr(getattr(runtime.db,event,None),'add',None)):
            raise ExactRetryError('exact_retry_callbacks_missing')
    request=RetryIntent(runtime,dt,name,issuance_id=issuance_id,attempt_id=attempt_id,fence_token=fence_token)
    result=arm_collection_request(request,runtime=runtime,translate=translate,cache=cache,key=key)
    return dict(result,issuance_id=issuance_id)


@frappe.whitelist(methods=['POST'])
def queue_exact_retry(issuance_id,attempt_id,fence_token):
    code=None;logged=False
    try:
        with mute_operation_messages(frappe):
            result=register_exact_retry(issuance_id,attempt_id,fence_token,runtime=frappe,translate=_)
    except Exception as error:
        code=error.code if isinstance(error,ExactRetryError) else 'exact_retry_unconfirmed'
        logged=isinstance(error,CollectionSubmissionError) and error.diagnostic_logged
    if code is not None:
        if not logged:
            try:frappe.log_error(title='ZATCA explicit exact retry review',message=code)
            except Exception:pass
        raise ExactRetryError(code,_(REVIEW))
    return dict(result,message=_(REGISTERED))
