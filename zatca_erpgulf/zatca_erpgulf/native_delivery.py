"""Execution-local delivery policy, independently rechecked under owned locks.

This is a server operation context, never an RPC flag, queue document or an
authority acceptance claim. Native custody/fencing remains the dispatch service's
responsibility. Unknown outcomes need their explicit retry operation.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from frappe.utils import now_datetime

from zatca_erpgulf.ksa_compliance.field_compat import get_alias_value
from .credential_material import use_linked_company
from .issuing_reads import read_issuing_doc
from .permission_compat import saved_row_has_permission
from .scheduling import is_within_company_windows
from .zatca_runtime import get_b2c_submission_method,is_zatca_invoice_enabled,resolve_zatca_phase,PHASE_2_VALUE


CURRENT = ContextVar('zatca_native_delivery',default=None)
INTENTS = ('entry','submit','scheduled','manual')


class NativeDeliveryError(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


@dataclass(frozen=True)
class DeliveryDecision:
    action: str
    simplified: bool
    method: str


def delivery_decision(company,customer,intent):
    if intent not in INTENTS:
        raise NativeDeliveryError('native_delivery_intent')
    if not is_zatca_invoice_enabled(company) or resolve_zatca_phase(company)!=PHASE_2_VALUE:
        return DeliveryDecision('SKIP',False,'')
    simplified=use_linked_company(get_alias_value('customer_b2c',customer,0))
    method=get_b2c_submission_method(company)
    if simplified and method not in ('','Live','Batches','Background'):
        raise NativeDeliveryError('native_delivery_method')
    if intent=='scheduled':
        if method!='Background' or not is_within_company_windows(company,now_datetime().time()):
            return DeliveryDecision('SKIP',simplified,method)
        return DeliveryDecision('DISPATCH',simplified,method)
    if simplified and method in ('Batches','Background') and intent!='manual':
        return DeliveryDecision('PREPARE',simplified,method)
    return DeliveryDecision('DISPATCH',simplified,method)


@dataclass(repr=False)
class _Delivery:
    site: str
    actor: str
    source: tuple
    intent: str
    decision: DeliveryDecision
    closed: bool=False

    def require(self,runtime,source):
        if (self.closed or runtime.local.site!=self.site or runtime.session.user!=self.actor
                or (source.doctype,source.name)!=self.source):
            raise NativeDeliveryError('native_delivery_context')

    def __reduce_ex__(self,protocol):
        raise TypeError('native_delivery_not_serializable')


@contextmanager
def native_delivery(runtime,source,intent,decision):
    if CURRENT.get() is not None or intent not in INTENTS or type(decision) is not DeliveryDecision:
        raise NativeDeliveryError('native_delivery_nested')
    current=_Delivery(runtime.local.site,runtime.session.user,(source.doctype,source.name),intent,decision)
    token=CURRENT.set(current)
    try:
        yield
    finally:
        current.closed=True
        CURRENT.reset(token)


def confirm_delivery_policy(scope,owner,*,dispatch=False):
    """Current shared master locks precede generation/attempt commits.

    The fixed saved reads request FOR UPDATE, downgraded to shared NOWAIT by the
    owned read-only view. They do not trust an earlier worker discovery snapshot.
    Settings cannot change before that commit; no DB lock survives into HTTP.
    """
    current=CURRENT.get()
    if current is None:
        return
    runtime=scope.runtime;source=scope.prepared_source
    current.require(runtime,source)
    with owner.preparing(frozenset(('tabCompany','tabCustomer'))):
        company=read_issuing_doc(runtime,'Company',source.company,for_update=True)
        customer=read_issuing_doc(runtime,'Customer',source.customer,for_update=True)
        if not saved_row_has_permission(runtime.has_permission,'Customer','read',doc=customer,user=owner.actor):
            raise NativeDeliveryError('native_delivery_customer_access')
        decision=delivery_decision(company,customer,current.intent)
        if decision!=current.decision or decision.action=='SKIP' or dispatch and decision.action!='DISPATCH':
            raise NativeDeliveryError('native_delivery_policy_changed')
        scope.confirm_current()


def require_no_legacy_artifact(owner,source):
    """A first native generation cannot ignore an unattested attached original.

    File existence is an ambiguity check, never acceptance. Debug XML is local
    output and excluded. Existing XML admission/publication has its own service.
    """
    current=CURRENT.get()
    if current is None:
        return
    current.require(owner.runtime,source)
    owner.require_owner()
    rows=owner.database.sql('SELECT name FROM `tabFile` WHERE attached_to_doctype=%s AND attached_to_name=%s '
        'AND (LOWER(file_name) LIKE %s AND LEFT(UPPER(file_name),6)<>%s OR file_name LIKE %s) '
        'LIMIT 1 LOCK IN SHARE MODE NOWAIT',
        (source.doctype,source.name,'%.xml','DEBUG_','QR-Phase2-%'),as_dict=True)
    owner.require_owner()
    if rows:
        raise NativeDeliveryError('native_delivery_existing_artifact_review')
