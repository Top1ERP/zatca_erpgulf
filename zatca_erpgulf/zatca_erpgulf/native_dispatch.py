"""Native source preparation under one current-site worker transaction.

No HTTP or installed-schema bootstrap. The internal queue coordinator supplies
its canonical build callback; this service retains exact originals before a later
attempt may dispatch. Legacy source history is never reinterpreted as new EGS.
"""

from dataclasses import dataclass,field
import hashlib
import json
from uuid import uuid4

from .dispatch_store import DispatchStore, _counter
from .issuing_attempt import issuing_attempt
from .issuing_reads import DEPENDENCIES
from .native_preparation import (
    native_preparation,PreparedRequestHandoff,PreparedNativeRequest,source_observation_sha256,
)
from .worker_transaction import owned_worker_transaction
from .permission_compat import saved_row_has_permission
from .api_routing import resolve_api_route
from .native_transport import NativeInvocation, NativeResponse, NativeTransportError, invoke_saved_request
from .native_response import assess_native_receipt, _original


SOURCE_TABLES={'Sales Invoice':'`tabSales Invoice`','POS Invoice':'`tabPOS Invoice`'}
OWNER_TABLES={'Company':'`tabCompany`','ZATCA Multiple Setting':'`tabZATCA Multiple Setting`'}


class NativeDispatchError(RuntimeError):
    def __init__(self,code):self.code=code;super().__init__(code)


class NativeDispatchReview(NativeDispatchError):
    """A stage-aware failure must never enter legacy identity-reset writers."""
    http_status_code = 417

    def __init__(self, code, *, issuance_id, attempt_id, invoked, receipt_retained):
        self.issuance_id = issuance_id
        self.attempt_id = attempt_id
        self.invoked = invoked
        self.receipt_retained = receipt_retained
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class NativeDispatchOutcome:
    issuance_id: str
    attempt_id: str
    outcome: str
    current: bool
    warning_count: int
    has_warnings: bool
    reused_accepted: bool = False


@dataclass(frozen=True, repr=False)
class RetainedNativeView:
    """Owned original bytes and a receipt-derived view, never a signing token."""
    issuance_id: str
    attempt_id: str | None
    state: str
    outcome: str
    accepted: bool
    warning_count: int
    has_warnings: bool
    original_xml: bytes = field(repr=False)
    returned_xml: bytes | None = field(repr=False)

    def __reduce_ex__(self, protocol):
        raise TypeError('retained_native_view_not_serializable')


@dataclass(frozen=True,repr=False)
class RetainedNativeIssuance:
    record_id: str
    state: str
    reused: bool
    source_doctype: str
    source_name: str
    def __reduce_ex__(self,protocol):raise TypeError('retained_native_issuance_not_serializable')


def owner_key(doctype,name,environment):
    raw=json.dumps((doctype,name,environment),ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(b'zatca-native-owner/v1\0'+raw).hexdigest()


def issuance_key(doctype,name,chain_id,version):
    raw=json.dumps((doctype,name,chain_id,version),ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(b'zatca-native-issuance/v1\0'+raw).hexdigest()


def _business_tables(runtime,source):
    """Source and child tables are schema-derived, never SQL identifiers from RPC."""
    names=set(DEPENDENCIES)
    for doctype in tuple(names):
        meta=runtime.get_meta(doctype)
        for item in meta.get_table_fields():names.add(item.options)
    names.add(source.doctype)
    return frozenset('tab'+name for name in names)


def _check_chain(chain,scope,material):
    if (chain['owner_doctype'],chain['owner_name'])!=(scope.owner.doctype,scope.owner.name):
        raise NativeDispatchError('native_chain_owner')
    if chain['environment']!=material.route.environment or chain['seller_tax_id']!=scope.company.get('tax_id'):
        raise NativeDispatchError('native_chain_taxpayer_or_environment')
    if (chain['certificate_sha256'],chain['public_key_sha256'])!=(material.certificate_der_sha256,material.public_key_sha256):
        raise NativeDispatchError('native_chain_credential_review')


def _require_new_source(source):
    """Unknown legacy identity/artifacts require continuity review, never reset."""
    placeholders=(None,'','Not Submitted','Not submitted','not submitted','0','false')
    if (source.get('custom_uuid') not in placeholders or source.get('custom_zatca_icv') not in (None,'',0,'0')
            or source.get('custom_zatca_issuing_unit') or source.get('custom_xml')
            or source.get('custom_zatca_status') not in placeholders
            or source.get('custom_zatca_full_response') not in placeholders):
        raise NativeDispatchError('native_legacy_issuance_review')


def _header(packet,record_id,version):
    return dict(record_id=record_id,
        issuance_key=issuance_key(packet.source_doctype,packet.source_name,packet.chain_id,version),
        icv_key=hashlib.sha256((packet.chain_id+'\0'+packet.icv).encode()).hexdigest(),
        chain=packet.chain_id,company=packet.company_name,source_doctype=packet.source_doctype,source_name=packet.source_name,
        environment=packet.environment,source_version=version,source_sha256=packet.source_sha256,
        invoice_uuid=packet.invoice_uuid,icv=packet.icv,invoice_hash=packet.invoice_hash,previous_hash=packet.previous_hash,
        certificate_sha256=packet.certificate_sha256,public_key_sha256=packet.public_key_sha256,
        endpoint=packet.endpoint,base_url_sha256=packet.base_url_sha256,
        artifact_sha256=packet.request_sha256,replaces_issuance=None)


def _require_access(runtime,source,company,actor,*,write=True):
    """Reused originals require the same saved-row ACL as new generation."""
    operations=('read','write') if write else ('read',)
    for document,operations in ((source,operations),(company,('read',))):
        for operation in operations:
            if not saved_row_has_permission(runtime.has_permission,document.doctype,
                    operation,doc=document,user=actor):
                raise NativeDispatchError('native_source_permission')


def _changed_once(database):
    rows=database.sql('SELECT ROW_COUNT() AS changed',as_dict=True)
    if len(rows)!=1 or type(rows[0].get('changed')) is not int or rows[0]['changed']!=1:
        raise NativeDispatchError('native_source_update_compare')


def _require_source_output_capacity(database, doctype, icv):
    """Read actual current-DB column capacity; never alter an ERP source schema.

    The journal's64-digit bound is not a promise that an installed ERP Int field
    can store that value. Stop before signing/staging rather than truncate or
    convert a counter through float. Installed UI/metadata parity remains5.
    """
    if doctype not in SOURCE_TABLES:
        raise NativeDispatchError('native_source_identity')
    number = _counter(icv)
    names = ('custom_uuid', 'custom_zatca_icv', 'custom_zatca_issuing_unit')
    rows = database.sql('SELECT column_name AS fieldname,data_type AS kind,'
        'character_maximum_length AS max_chars,column_type AS declaration '
        'FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s '
        'AND column_name IN (%s,%s,%s)', ('tab' + doctype, *names), as_dict=True)
    fields = {row['fieldname']: row for row in rows}
    if len(rows) != 3 or set(fields) != set(names):
        raise NativeDispatchError('native_source_output_schema_required')
    strings = ('char', 'varchar', 'tinytext', 'text', 'mediumtext', 'longtext')
    for name, minimum in (('custom_uuid', 36), ('custom_zatca_issuing_unit', 40)):
        column = fields[name]
        if (column['kind'] not in strings or type(column['max_chars']) is not int
                or column['max_chars'] < minimum):
            raise NativeDispatchError('native_source_output_schema_required')
    column = fields['custom_zatca_icv']
    bits = {'tinyint': 8, 'smallint': 16, 'mediumint': 24, 'int': 32, 'bigint': 64}.get(column['kind'])
    if bits is not None:
        if type(column['declaration']) is not str:
            raise NativeDispatchError('native_source_output_schema_required')
        unsigned = 'unsigned' in column['declaration'].split()
        fits = number <= 2 ** (bits if unsigned else bits - 1) - 1
    else:
        fits = (column['kind'] in strings and type(column['max_chars']) is int
            and len(icv) <= column['max_chars'])
    if not fits:
        raise NativeDispatchError('native_source_counter_capacity')


def _require_retained_binding(header,chain,scope,material,doctype,invoice_name):
    if (header['company']!=scope.company.name or header['environment']!=material.route.environment
            or header['chain']!=chain['record_id']
            or (header['source_doctype'],header['source_name'])!=(doctype,invoice_name)
            or header['certificate_sha256']!=material.certificate_der_sha256
            or header['public_key_sha256']!=material.public_key_sha256):
        raise NativeDispatchError('native_retained_issuance_binding')
    base=material.route.url.removesuffix('/'+material.route.endpoint)
    if header['base_url_sha256']!=hashlib.sha256(base.encode()).hexdigest():
        raise NativeDispatchError('native_retained_route_review')
    # Conservative until a documented fiscal projection permits specific
    # nonfiscal updates. Drift never grants permission to regenerate an original.
    if header['source_sha256']!=source_observation_sha256(scope.source_identity,scope.source_observation):
        raise NativeDispatchError('native_retained_source_review')


def prepare_saved_invoice(doctype,invoice_name,*,runtime,translate,build):
    """Initial generation or exact existing custody, with no automatic reissue.

    A corrected verified rejection needs a separate explicit version operation;
    a changed ERP source/credential does not grant it. Existing prepared/unknown
    originals are returned for the dispatch policy to review, never regenerated.
    """
    if doctype not in SOURCE_TABLES or type(invoice_name) is not str or not invoice_name:
        raise NativeDispatchError('native_source_identity')
    if not callable(build):raise NativeDispatchError('native_build_callback')
    with owned_worker_transaction(runtime) as owner:
        source=runtime.get_doc(doctype,invoice_name)
        company=runtime.get_doc('Company',source.company)
        if source.get('docstatus')!=1:raise NativeDispatchError('native_source_not_submitted')
        _require_access(runtime,source,company,owner.actor)
        # The same issuer scope spans preflight and preparation. The next HTTP
        # transaction must independently match the stored public binding.
        with issuing_attempt(company.abbr,source,purpose='production',runtime=runtime,
                             translate=translate,invoice_doc=source) as scope:
            scope.require_production_configuration()
            material=scope.signing_material()
            route=material.route
            repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
                cipher=owner.cipher,owner_check=owner.owner_current)
            chain=repository.lock_active_chain(owner_key(scope.owner.doctype,scope.owner.name,route.environment))
            _check_chain(chain,scope,material)
            # Lock current source after the issuer chain; reject observed drift
            # instead of mixing an earlier read snapshot with later metadata.
            locked=runtime.get_doc(doctype,invoice_name,for_update=True)
            scope.bind_prepared_invoice(locked)
            latest=repository.latest_issuance(chain['record_id'],doctype,invoice_name)
            if latest is not None:
                header,original=repository.open_issuance(latest['record_id'])
                _require_retained_binding(header,chain,scope,material,doctype,invoice_name)
                owner.commit()
                return RetainedNativeIssuance(latest['record_id'],latest['state'],True,doctype,invoice_name)
            _require_new_source(locked)
            _require_source_output_capacity(owner.database,doctype,str(int(chain['last_icv'])+1))
            tables=_business_tables(runtime,locked)
            proposed_uuid=str(uuid4())
            packet=None
            with native_preparation(runtime,source_identity=(doctype,invoice_name),company_name=scope.company.name,
                                    chain=chain,invoice_uuid=proposed_uuid,owner_check=owner.owner_current):
                with owner.preparing(tables):
                    try:build(locked)
                    except PreparedRequestHandoff as ready:packet=ready.packet
            if type(packet) is not PreparedNativeRequest:
                raise NativeDispatchError('native_preparation_did_not_handoff')
            scope.confirm_current()
            record_id=str(uuid4())
            occurred_at=owner.utc_now()
            repository.stage_issuance(chain,_header(packet,record_id,1),packet.request_bytes,
                actor=owner.actor,occurred_at=occurred_at)
            owner.database.sql('UPDATE '+SOURCE_TABLES[doctype]+
                ' SET custom_uuid=%s,custom_zatca_icv=%s,custom_zatca_issuing_unit=%s WHERE name=%s',
                (packet.invoice_uuid,packet.icv,'egs:'+chain['record_id'],invoice_name))
            _changed_once(owner.database)
            owner.database.sql('UPDATE '+OWNER_TABLES[scope.owner.doctype]+' SET custom_pih=%s WHERE name=%s',
                (packet.invoice_hash,scope.owner.name))
            _changed_once(owner.database)
            owner.commit()
            return RetainedNativeIssuance(record_id,'PREPARED',False,doctype,invoice_name)


def reserve_saved_issuance(doctype,invoice_name,*,runtime,translate,supersedes_attempt=None):
    """Commit the attempt reservation, then release a transient exact invocation.

    No public retry flag or artifact re-creation. An uncertain commit raises
    before the invocation can leave this function; recovery must freshly read
    the same issuance/attempt. All row locks are released before HTTP may start.
    """
    if doctype not in SOURCE_TABLES or type(invoice_name) is not str or not invoice_name:
        raise NativeDispatchError('native_source_identity')
    with owned_worker_transaction(runtime) as owner:
        source=runtime.get_doc(doctype,invoice_name)
        company=runtime.get_doc('Company',source.company)
        if source.get('docstatus')!=1:raise NativeDispatchError('native_source_not_submitted')
        _require_access(runtime,source,company,owner.actor)
        with issuing_attempt(company.abbr,source,purpose='production',runtime=runtime,
                             translate=translate,invoice_doc=source) as scope:
            scope.require_production_configuration()
            material=scope.signing_material()
            key=owner_key(scope.owner.doctype,scope.owner.name,material.route.environment)
            repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
                cipher=owner.cipher,owner_check=owner.owner_current)
            chain=repository.lock_active_chain(key)
            _check_chain(chain,scope,material)
            locked=runtime.get_doc(doctype,invoice_name,for_update=True)
            scope.bind_prepared_invoice(locked)
            latest=repository.latest_issuance(chain['record_id'],doctype,invoice_name)
            if latest is None:raise NativeDispatchError('native_original_required')
            issuance=repository.lock_issuance(chain,latest['record_id'])
            header,original=repository.open_issuance(issuance['record_id'])
            _require_retained_binding(header,chain,scope,material,doctype,invoice_name)
            _require_source_output_capacity(owner.database,doctype,header['icv'])
            if (locked.get('custom_uuid')!=header['invoice_uuid']
                    or str(locked.get('custom_zatca_icv'))!=header['icv']
                    or locked.get('custom_zatca_issuing_unit')!='egs:'+chain['record_id']):
                raise NativeDispatchError('native_source_issuance_outputs_review')
            attempt_id,fence=str(uuid4()),str(uuid4())
            reserved=repository.start_attempt(chain,issuance,record_id=attempt_id,fence_token=fence,
                actor=owner.actor,now_utc=owner.utc_now(),supersedes_attempt=supersedes_attempt)
            route=resolve_api_route(scope.company.values,reserved['endpoint'])
            scope.confirm_current()
            invocation=NativeInvocation(issuance['record_id'],attempt_id,fence,key,chain['record_id'],owner.site,owner.actor,route,
                material.authorization.header,header['artifact_sha256'],original)
            owner.commit()
            return invocation


def retain_dispatch_observation(invocation,response,*,runtime):
    """Commit original receipt or uncertainty before any derived invoice update.

    Do not require a still-valid certificate, unchanged source or current sender
    fence to retain an already received response. A late worker's receipt stays
    on its own attempt; the repository cannot overwrite the current outcome.
    None means the transport outcome is unknown, never a verified rejection.
    """
    if type(invocation) is not NativeInvocation or (response is not None and type(response) is not NativeResponse):
        raise NativeDispatchError('native_observation_shape')
    if runtime.local.site!=invocation.site:
        raise NativeDispatchError('native_observation_site_changed')
    with owned_worker_transaction(runtime) as owner:
        repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        chain=repository.lock_recorded_chain(invocation.chain_id,invocation.owner_key)
        issuance=repository.lock_issuance(chain,invocation.issuance_id)
        if issuance['artifact_sha256']!=invocation.request_sha256:
            raise NativeDispatchError('native_observation_request_binding')
        if response is None:
            current=repository.mark_attempt_unknown(chain,issuance,attempt_id=invocation.attempt_id,
                fence_token=invocation.fence_token)
        else:
            current=repository.retain_receipt(chain,issuance,attempt_id=invocation.attempt_id,
                fence_token=invocation.fence_token,http_status=response.http_status,
                request_id=response.request_id,body=response.body)
        owner.commit()
        return current


def assess_retained_dispatch(invocation,*,runtime):
    """Assess from committed encrypted custody, never from a display/RPC body."""
    if type(invocation) is not NativeInvocation or runtime.local.site!=invocation.site:
        raise NativeDispatchError('native_observation_site_changed')
    with owned_worker_transaction(runtime) as owner:
        repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        chain=repository.lock_recorded_chain(invocation.chain_id,invocation.owner_key)
        issuance=repository.lock_issuance(chain,invocation.issuance_id)
        header,original=repository.open_issuance(invocation.issuance_id)
        receipt,body=repository.open_receipt(invocation.attempt_id)
        if (header['artifact_sha256']!=invocation.request_sha256
                or receipt['fence_token']!=invocation.fence_token):
            raise NativeDispatchError('native_observation_request_binding')
        fallback=None
        if header['endpoint']!=receipt['endpoint']:
            fallback=repository.open_clearance_fallback(issuance)
        assessment=assess_native_receipt(header,original,receipt,body,fallback_receipt=fallback)
        current=repository.record_assessment(chain,issuance,attempt_id=invocation.attempt_id,
            fence_token=invocation.fence_token,outcome=assessment.outcome)
        owner.commit()
        return assessment,current


def read_retained_invoice(doctype,invoice_name,*,runtime):
    """Read exact native custody using saved-source read ACL, not signing keys.

    No artifact generation, key/route/certificate lookup, source repair, current
    Company-phase requirement or HTTP occurs. Historical source identities must
    still match; a rename/rebind needs its explicit reviewed transition.
    """
    if doctype not in SOURCE_TABLES or type(invoice_name) is not str or not invoice_name:
        raise NativeDispatchError('native_source_identity')
    with owned_worker_transaction(runtime) as owner:
        source=runtime.get_doc(doctype,invoice_name)
        company=runtime.get_doc('Company',source.company)
        _require_access(runtime,source,company,owner.actor,write=False)
        marker=source.get('custom_zatca_issuing_unit')
        if type(marker) is not str or not marker.startswith('egs:'):
            return None
        value=source.get('custom_zatca_icv')
        if type(value) not in (int,str):
            raise NativeDispatchError('native_retained_source_identity')
        repository=DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
            cipher=owner.cipher,owner_check=owner.owner_current)
        saved=repository.find_source_issuance(doctype=doctype,invoice_name=invoice_name,
            company=source.company,chain_id=marker[4:],invoice_uuid=source.get('custom_uuid'),icv=str(value))
        header,original=repository.open_issuance(saved['record_id'])
        xml,_evidence=_original(header,original)
        outcome='RETAINED_ORIGINAL';warnings=0;has_warnings=False;returned=None
        accepted=saved['state'] in ('REPORTED','CLEARED')
        if accepted:
            if not saved['active_attempt']:
                raise NativeDispatchError('native_retained_acceptance_review')
            receipt,body=repository.open_receipt(saved['active_attempt'])
            fallback=repository.open_clearance_fallback(saved) if header['endpoint']!=receipt['endpoint'] else None
            assessment=assess_native_receipt(header,original,receipt,body,fallback_receipt=fallback)
            required=('REPORTING_MATCHED','REPORTING_DUPLICATE_MATCHED') if saved['state']=='REPORTED' else (
                'CLEARANCE_MATCHED','CLEARANCE_DUPLICATE_MATCHED')
            if assessment.outcome not in required:
                raise NativeDispatchError('native_retained_acceptance_review')
            outcome=assessment.outcome;warnings=assessment.warning_count;has_warnings=assessment.has_warnings
            returned=assessment.returned_xml
        return RetainedNativeView(saved['record_id'],saved['active_attempt'],saved['state'],outcome,
            accepted,warnings,has_warnings,xml,returned)


def dispatch_saved_invoice(doctype, invoice_name, *, runtime, translate, build, retry_attempt_id=None):
    """One native preparation, exact dispatch/custody and bounded303 fallback.

    Internal coordinator only, not a whitelisted RPC or public build callback.
    Each service owns and commits its separate transaction. The response is
    retained before assessment, and no legacy source-reset handler runs here.
    Source/QR/File projection and public worker adoption remain separate work.
    """
    retained=read_retained_invoice(doctype,invoice_name,runtime=runtime)
    if retained is not None and retained.accepted:
        return NativeDispatchOutcome(retained.issuance_id,retained.attempt_id,retained.outcome,
            True,retained.warning_count,retained.has_warnings,True)
    if retained is None:
        prepare_saved_invoice(doctype, invoice_name, runtime=runtime, translate=translate, build=build)
    supersedes = retry_attempt_id
    for _ in range(2):
        invocation = reserve_saved_issuance(doctype, invoice_name, runtime=runtime,
            translate=translate, supersedes_attempt=supersedes)
        response = None
        transport_error = None
        try:
            response = invoke_saved_request(invocation, runtime=runtime)
        except NativeTransportError as error:
            transport_error = error
        if type(response) is not NativeResponse and transport_error is None:
            response = None
            transport_error = NativeTransportError('native_transport_contract_unknown', invoked=True)
        custody_failed = False
        try:
            retain_dispatch_observation(invocation, response, runtime=runtime)
        except Exception:
            custody_failed = True
        if custody_failed:
            raise NativeDispatchReview('native_response_custody_unknown', issuance_id=invocation.issuance_id,
                attempt_id=invocation.attempt_id, invoked=transport_error.invoked if transport_error else True,
                receipt_retained=False)
        if transport_error is not None:
            raise NativeDispatchReview(transport_error.code, issuance_id=invocation.issuance_id,
                attempt_id=invocation.attempt_id, invoked=transport_error.invoked, receipt_retained=False)
        assessment_failed = False
        try:
            assessment, current = assess_retained_dispatch(invocation, runtime=runtime)
        except Exception:
            assessment_failed = True
        if assessment_failed:
            raise NativeDispatchReview('native_response_processing_incomplete', issuance_id=invocation.issuance_id,
                attempt_id=invocation.attempt_id, invoked=True, receipt_retained=True)
        if assessment.outcome == 'CLEARANCE_DISABLED' and current:
            supersedes = invocation.attempt_id
            continue
        return NativeDispatchOutcome(invocation.issuance_id, invocation.attempt_id, assessment.outcome,
            current, assessment.warning_count, assessment.has_warnings)
    raise NativeDispatchReview('native_fallback_limit', issuance_id=invocation.issuance_id,
        attempt_id=invocation.attempt_id, invoked=True, receipt_retained=True)
