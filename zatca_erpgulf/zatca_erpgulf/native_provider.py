"""Adopt owned issuance from saved Sales/POS entry and worker identifiers.

Unmarked legacy owners retain their paths. Native markers are persistent opt-in;
turning rollout off never sends them through legacy counters/HTTP. This facade
does not install/activate a chain, create an ERP document, publish File/QR output,
repair history or authorize automatic unknown-outcome retries.
"""

from .credential_material import NATIVE_OWNER_MARKER as MARKER
from .credential_settings import _resolve_owner_record_from_saved_company
from .dispatch_record_codec import _identifier,DispatchRecordError
from .issuing_attempt import IssuingAttemptError
from .native_dispatch import (
    dispatch_saved_invoice,prepare_saved_invoice,read_retained_invoice,
    NativeDispatchOutcome,RetainedNativeIssuance,NativeDispatchError,
)
from .native_delivery import delivery_decision,native_delivery,NativeDeliveryError
from .native_onboarding import native_mode_enabled,NativeOnboardingError
from .native_preparation import active_preparation
from .dispatch_store import DispatchStoreError
from .worker_transaction import WorkerTransactionError
from .permission_compat import saved_row_has_permission
from .operation_messages import mute_operation_messages
from .zatca_runtime import is_zatca_invoice_enabled,resolve_zatca_phase,PHASE_2_VALUE


REVIEW='The native ZATCA invoice operation needs review. Check its saved issuance and response before retrying; no automatic replacement was performed.'
ACCEPTED=('REPORTING_MATCHED','REPORTING_DUPLICATE_MATCHED','CLEARANCE_MATCHED','CLEARANCE_DUPLICATE_MATCHED')


class NativeProviderError(IssuingAttemptError):
    def __init__(self,code):
        super().__init__(code)
        self.template=REVIEW
        self.args=(REVIEW,)


def _schema_available(runtime):
    getter=getattr(runtime,'get_meta',None)
    if not callable(getter):
        return False
    meta=getter('Company')
    has_field=getattr(meta,'has_field',None)
    return callable(has_field) and has_field(MARKER) is True


def _permitted(runtime,document,*,write=False):
    for operation in ('read','write') if write else ('read',):
        if not saved_row_has_permission(runtime.has_permission,document.doctype,operation,
                doc=document,user=runtime.session.user):
            raise NativeProviderError('native_provider_source_access')


def _selection(runtime,doctype,invoice_name,source):
    hint=source.get('custom_zatca_issuing_unit') if source is not None else None
    if not (type(hint) is str and hint.startswith('egs:')) and not _schema_available(runtime):
        return None
    source=runtime.get_doc(doctype,invoice_name)
    if source.doctype!=doctype or source.name!=invoice_name:
        raise NativeProviderError('native_provider_source_identity')
    _permitted(runtime,source,write=True)
    company=runtime.get_doc('Company',source.company)
    _permitted(runtime,company)
    source_marker=source.get('custom_zatca_issuing_unit')
    source_native=type(source_marker) is str and source_marker.startswith('egs:')
    if source_native:
        _identifier(source_marker[4:])
        return source,company  # Retained reads do not need current owner settings.
    if not source_native and not _schema_available(runtime):
        return None
    def load(doctype,name):
        value=runtime.get_doc(doctype,name)
        if (value.doctype,value.name)!=(doctype,name):
            raise NativeProviderError('native_provider_owner_identity')
        _permitted(runtime,value)
        return value
    selected,_kind=_resolve_owner_record_from_saved_company(company,source,load_doc=load)
    marker=selected.get(MARKER)
    if marker not in (None,''):
        _identifier(marker)
    if not source_native and marker in (None,''):
        return None
    _permitted(runtime,selected)
    return source,company


def _result(doctype,name,value):
    if type(value) is RetainedNativeIssuance:
        status='PREPARED' if value.state=='PREPARED' else 'ERROR' if value.state=='REJECTED' else 'REVIEW'
        return {'status':status,'accepted':False,'source_doctype':doctype,'source_name':name,
                'issuance_id':value.record_id,'state':value.state,'reused':value.reused}
    if type(value) is not NativeDispatchOutcome:
        raise NativeProviderError('native_provider_result_contract')
    accepted=value.current and value.outcome in ACCEPTED
    status='SUCCESS' if accepted else 'ERROR' if value.outcome=='VALIDATION_REJECTED' else 'REVIEW'
    return {'status':status,'accepted':accepted,'source_doctype':doctype,'source_name':name,
            'issuance_id':value.issuance_id,'attempt_id':value.attempt_id,'outcome':value.outcome,
            'current':value.current,'warning_count':value.warning_count,'has_warnings':value.has_warnings,
            'reused':value.reused_accepted,'source_projected':value.source_projected}


def _run(doctype,invoice_name,*,runtime,translate,build,intent,source,expected_issuance_id=None):
    if doctype not in ('Sales Invoice','POS Invoice') or type(invoice_name) is not str or not invoice_name or not callable(build):
        raise NativeProviderError('native_provider_source_identity')
    if active_preparation(runtime) is not None:
        return None  # The fixed generator now runs inside its owned preparation.
    selection=_selection(runtime,doctype,invoice_name,source)
    if selection is None:
        return None
    source,company=selection
    with mute_operation_messages(runtime):
        return _run_selected(doctype,invoice_name,runtime=runtime,translate=translate,build=build,
            intent=intent,source=source,company=company,expected_issuance_id=expected_issuance_id)


def _run_selected(doctype,invoice_name,*,runtime,translate,build,intent,source,company,expected_issuance_id=None):
    if not is_zatca_invoice_enabled(company) or resolve_zatca_phase(company)!=PHASE_2_VALUE:
        return {'status':'SKIPPED','accepted':False,'reason':'company_policy_changed'}
    retained=read_retained_invoice(doctype,invoice_name,runtime=runtime)
    if expected_issuance_id is not None and (retained is None or retained.issuance_id!=expected_issuance_id):
        raise NativeProviderError('native_expected_issuance_changed')
    expected={} if expected_issuance_id is None else {'expected_issuance_id':expected_issuance_id}
    if retained is not None and retained.accepted:
        value=dispatch_saved_invoice(doctype,invoice_name,runtime=runtime,translate=translate,build=build,**expected)
        return _result(doctype,invoice_name,value)
    if not native_mode_enabled(runtime):
        raise NativeProviderError('native_provider_rollout_disabled')
    if retained is not None and retained.state!='PREPARED':
        # A closed schedule cannot hide an already uncertain/rejected original
        # behind a harmless waiting result. Ordinary processing never retries it.
        return {'status':'ERROR' if retained.state=='REJECTED' else 'REVIEW','accepted':False,
            'source_doctype':doctype,'source_name':invoice_name,'issuance_id':retained.issuance_id,
            'state':retained.state,'reused':True}
    customer=runtime.get_doc('Customer',source.customer)
    _permitted(runtime,customer)
    original_xml=retained.original_xml if retained is not None and retained.state=='PREPARED' else None
    decision=delivery_decision(company,customer,intent,original_xml=original_xml)
    if decision.action=='SKIP':
        # This branch precedes preparation/reservation/transport. Only a still
        # enabled Background schedule outside its current window may wait; other
        # policy changes remain a review and cannot authorize automatic replay.
        reason='outside_company_window' if intent=='scheduled' and decision.method=='Background' else 'company_policy_changed'
        return {'status':'SKIPPED','accepted':False,'reason':reason}
    if retained is not None and decision.action=='PREPARE':
        return _result(doctype,invoice_name,RetainedNativeIssuance(retained.issuance_id,retained.state,True,doctype,invoice_name))
    # Bind ordinary retained dispatch as well as attached-XML admission to the
    # exact version supplying its classification; no newer version can replace it.
    if retained is not None and not expected:
        expected={'expected_issuance_id':retained.issuance_id}
    with native_delivery(runtime,source,intent,decision,original_xml=original_xml):
        operation=prepare_saved_invoice if decision.action=='PREPARE' else dispatch_saved_invoice
        value=operation(doctype,invoice_name,runtime=runtime,translate=translate,build=build,**expected)
    return _result(doctype,invoice_name,value)


def maybe_process_native_invoice(doctype,invoice_name,*,runtime,translate,build,intent='entry',source=None):
    """Internal fixed-callsite facade; None means the legacy path remains selected.

    All caller-supplied invoice/Company/credential content is ignored. The build
    callback belongs to the server entry, never a serialized or whitelisted input.
    No HTTP200/local status/UUID alone becomes a successful public result.
    """
    return reviewed_native_operation(lambda:_run(doctype,invoice_name,runtime=runtime,translate=translate,
        build=build,intent=intent,source=source),runtime=runtime,translate=translate)


def reviewed_native_operation(operation,*,runtime,translate):
    """One English diagnostic and translated review for fixed native adapters."""
    failed=None
    try:
        return operation()
    except Exception as error:
        failed=error.code if isinstance(error,(IssuingAttemptError,NativeDispatchError,NativeDeliveryError,
            NativeOnboardingError,DispatchStoreError,DispatchRecordError,WorkerTransactionError)) else 'native_provider_operation_review'
    review=NativeProviderError(failed)
    runtime.log_error(title='Native ZATCA invoice review',message=f'{failed}: {REVIEW}')
    review.diagnostic_logged=True
    runtime.throw(translate(REVIEW),exc=review)
    raise review


def process_native_saved_source(source,*,runtime,translate,intent):
    """Use the original fixed validator/route dispatcher inside native preparation."""
    if source.doctype=='Sales Invoice':
        from .sign_invoice import _process_submitted_invoice
    elif source.doctype=='POS Invoice':
        from .pos_sign import _process_submitted_invoice
    else:
        raise NativeProviderError('native_provider_doctype')
    return maybe_process_native_invoice(source.doctype,source.name,runtime=runtime,translate=translate,
        build=lambda locked:_process_submitted_invoice(locked,bypass_background_check=True),intent=intent,source=source)
