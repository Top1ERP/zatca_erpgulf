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
from .credential_material import NATIVE_OWNER_TABLES as OWNER_TABLES


SOURCE_TABLES={'Sales Invoice':'`tabSales Invoice`','POS Invoice':'`tabPOS Invoice`'}


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
    source_projected: bool = False


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
    source_sha256: str | None = field(default=None, repr=False)
    invoice_uuid: str | None = field(default=None, repr=False)
    icv: str | None = field(default=None, repr=False)
    chain_id: str | None = field(default=None, repr=False)
    publication_sha256: str | None = field(default=None, repr=False)
    render_source_sha256: str | None = field(default=None, repr=False)
    invoice_hash: str | None = field(default=None, repr=False)
    generation_origin: dict | None = field(default=None,repr=False)

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
    marker=scope.owner.values.get('custom_zatca_native_chain')
    if marker not in (None,'') and marker!=chain['record_id']:
        raise NativeDispatchError('native_chain_marker_review')
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


def _require_retained_binding(header,chain,scope,material,doctype,invoice_name,*,check_source=True,repository=None):
    if (header['company']!=scope.company.name or header['environment']!=material.route.environment
            or header['chain']!=chain['record_id']
            or (header['source_doctype'],header['source_name'])!=(doctype,invoice_name)
            or header['certificate_sha256']!=material.certificate_der_sha256
            or header['public_key_sha256']!=material.public_key_sha256):
        raise NativeDispatchError('native_retained_issuance_binding')
    base=material.route.url.removesuffix('/'+material.route.endpoint)
    if header['base_url_sha256']!=hashlib.sha256(base.encode()).hexdigest():
        raise NativeDispatchError('native_retained_route_review')
    # Reuse only the retained original. A captured versioned projection permits
    # identified collection changes, never fiscal drift or regeneration.
    if check_source and header['source_sha256']!=source_observation_sha256(scope.source_identity,scope.source_observation):
        from .publication_source import publication_source_sha256
        retained=repository.open_publication(header) if repository is not None else None
        current=publication_source_sha256(scope.source_identity,scope.source_observation)
        if retained is None or current!=retained:
            raise NativeDispatchError('native_retained_source_review')


def prepare_saved_invoice(doctype,invoice_name,*,runtime,translate,build):
    """Initial generation or exact existing custody, with no automatic reissue.

    A corrected verified rejection needs a separate explicit version operation;
    a changed ERP source/credential does not grant it. Existing prepared/unknown
    originals are returned for the dispatch policy to review, never regenerated.
    """
    return _prepare_saved_invoice(doctype,invoice_name,runtime=runtime,translate=translate,build=build)


def prepare_corrected_rejection(doctype,invoice_name,*,runtime,translate,build,
                                rejected_issuance_id,rejected_attempt_id):
    """Explicit new local version after an exact retained validation rejection.

    No submission or business-data edit is performed. The canonical builder
    must supply corrected saved data and a distinct valid issue timestamp;
    Reporting retains the original transaction date. An unchanged clock fails
    locally rather than silently rewriting ERP posting dates or times.
    """
    from .dispatch_store import _identifier
    _identifier(rejected_issuance_id)
    _identifier(rejected_attempt_id)
    return _prepare_saved_invoice(doctype,invoice_name,runtime=runtime,translate=translate,build=build,
        rejection=(rejected_issuance_id,rejected_attempt_id))


def _rejected_original(repository,chain,latest,source,rejection):
    if latest is not None and any(latest.get(key) is not None for key in ('late_acceptance_header','late_acceptance_ciphertext')):
        raise NativeDispatchError('native_corrected_late_acceptance_review')
    if (latest is None or latest['record_id']!=rejection[0] or latest['state']!='REJECTED'
            or latest['active_attempt']!=rejection[1] or chain['active_attempt']):
        raise NativeDispatchError('native_corrected_rejection_current_required')
    latest=repository.lock_issuance(chain,latest['record_id'])
    header,original=repository.open_issuance(latest['record_id'])
    if type(header['source_version']) is not int or not 1<=header['source_version']<2147483647:
        raise NativeDispatchError('native_corrected_version_capacity')
    if (source.get('custom_uuid')!=header['invoice_uuid']
            or type(source.get('custom_zatca_icv')) not in (int,str)
            or str(source.get('custom_zatca_icv'))!=header['icv']
            or source.get('custom_zatca_issuing_unit')!='egs:'+chain['record_id']
            or source.get('custom_zatca_status') in ('REPORTED','CLEARED')):
        raise NativeDispatchError('native_source_issuance_outputs_review')
    receipt,body=repository.open_receipt(rejection[1])
    fallback=repository.open_clearance_fallback(latest) if header['endpoint']!=receipt['endpoint'] else None
    assessment=assess_native_receipt(header,original,receipt,body,fallback_receipt=fallback)
    if receipt['http_status']!=400 or assessment.outcome!='VALIDATION_REJECTED':
        raise NativeDispatchError('native_corrected_rejection_receipt_required')
    return header,original


def _require_corrected_artifact(previous,original,header,packet):
    """Check the new identity/time without calculating or editing ERP amounts."""
    from .issuance_candidate import _invoice_classification
    from .qr_xml_contract import _clock
    from .issue_timestamp import parse_issue_datetime
    old_xml,_=_original(previous,original)
    new_xml,_=_original(header,packet.request_bytes)
    old_clock,new_clock=_clock(old_xml),_clock(new_xml)
    old_instant=parse_issue_datetime(*old_clock)
    new_instant=parse_issue_datetime(*new_clock)
    if (header['invoice_uuid']==previous['invoice_uuid'] or header['invoice_hash']==previous['invoice_hash']
            or int(header['icv'])<=int(previous['icv']) or old_instant==new_instant
            or old_instant.utcoffset() is None or new_instant.utcoffset() is None
            or _invoice_classification(new_xml)!=_invoice_classification(old_xml)
            or header['endpoint']!=previous['endpoint']):
        raise NativeDispatchError('native_corrected_artifact_review')
    if header['endpoint']=='invoices/reporting/single' and new_clock[0]!=old_clock[0]:
        raise NativeDispatchError('native_corrected_reporting_date_review')


def _prepare_saved_invoice(doctype,invoice_name,*,runtime,translate,build,rejection=None):
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
            from .submission_intent import require_bound_source
            require_bound_source(runtime,locked,chain['record_id'],owner=owner)
            from .native_delivery import confirm_delivery_policy,require_no_legacy_artifact
            confirm_delivery_policy(scope,owner)
            latest=repository.latest_issuance(chain['record_id'],doctype,invoice_name)
            previous=None
            if rejection is not None:
                previous,old_original=_rejected_original(repository,chain,latest,locked,rejection)
                _require_retained_binding(previous,chain,scope,material,doctype,invoice_name,check_source=False)
            elif latest is not None:
                header,original=repository.open_issuance(latest['record_id'])
                _require_retained_binding(header,chain,scope,material,doctype,invoice_name,repository=repository)
                owner.commit()
                return RetainedNativeIssuance(latest['record_id'],latest['state'],True,doctype,invoice_name)
            else:
                _require_new_source(locked)
                require_no_legacy_artifact(owner,locked)
            # Pending is a local generation result, not acceptance. Normalize
            # empty imported status fields so scheduled discovery can find the
            # same committed original without generating another identity.
            from .native_projection import _status_columns
            _status_columns(owner.database,doctype,'Not Submitted','')
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
            version=1 if previous is None else previous['source_version']+1
            header=_header(packet,record_id,version)
            if previous is not None:
                header['replaces_issuance']=previous['record_id']
                _require_corrected_artifact(previous,old_original,header,packet)
            from .issuance_origin import capture_origin
            origin=capture_origin(runtime,locked,chain_id=chain['record_id'],occurred_at=occurred_at)
            repository.stage_issuance(chain,header,packet.request_bytes,
                actor=owner.actor,occurred_at=occurred_at,publication_sha256=packet.publication_sha256,generation_origin=origin)
            output=(packet.invoice_uuid,packet.icv,'egs:'+chain['record_id'],'Not Submitted','')
            owner.database.sql('UPDATE '+SOURCE_TABLES[doctype]+
                ' SET custom_uuid=%s,custom_zatca_icv=%s,custom_zatca_issuing_unit=%s,custom_zatca_status=%s,custom_zatca_full_response=%s WHERE name=%s',
                (*output,invoice_name))
            _changed_once(owner.database)
            owner.database.sql('UPDATE '+OWNER_TABLES[scope.owner.doctype]+' SET custom_pih=%s WHERE name=%s',
                (packet.invoice_hash,scope.owner.name))
            _changed_once(owner.database)
            owner.commit()
            return RetainedNativeIssuance(record_id,'PREPARED',False,doctype,invoice_name)


def reserve_saved_issuance(doctype,invoice_name,*,runtime,translate,supersedes_attempt=None,expected_issuance_id=None,expected_prior_fence=None):
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
            from .submission_intent import require_bound_source
            require_bound_source(runtime,locked,chain['record_id'],owner=owner)
            from .native_delivery import confirm_delivery_policy
            confirm_delivery_policy(scope,owner,dispatch=True)
            latest=repository.latest_issuance(chain['record_id'],doctype,invoice_name)
            if latest is None:raise NativeDispatchError('native_original_required')
            if expected_issuance_id is not None and latest['record_id']!=expected_issuance_id:
                raise NativeDispatchError('native_expected_issuance_changed')
            issuance=repository.lock_issuance(chain,latest['record_id'])
            header,original=repository.open_issuance(issuance['record_id'])
            _require_retained_binding(header,chain,scope,material,doctype,invoice_name,repository=repository)
            _require_source_output_capacity(owner.database,doctype,header['icv'])
            if (locked.get('custom_uuid')!=header['invoice_uuid']
                    or str(locked.get('custom_zatca_icv'))!=header['icv']
                    or locked.get('custom_zatca_issuing_unit')!='egs:'+chain['record_id']):
                raise NativeDispatchError('native_source_issuance_outputs_review')
            attempt_id,fence=str(uuid4()),str(uuid4())
            if expected_prior_fence is not None:
                prior=repository._attempt(supersedes_attempt)
                if prior['fence_token']!=expected_prior_fence:
                    raise NativeDispatchError('native_retry_prior_fence_changed')
            if supersedes_attempt is not None and issuance['state'] in ('DISPATCHING','OUTCOME_UNKNOWN'):
                from .retry_evidence import require_retry_evidence
                require_retry_evidence(repository,chain,issuance,attempt_id=supersedes_attempt,
                    expected_fence=expected_prior_fence,now_utc=owner.utc_now())
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
        assessment,current=assess_retained_in_transaction(repository,chain,issuance,
            attempt_id=invocation.attempt_id,request_sha256=invocation.request_sha256,fence_token=invocation.fence_token)
        owner.commit()
        return assessment,current


def assess_retained_in_transaction(repository,chain,issuance,*,attempt_id,request_sha256,fence_token):
    """Canonical assessment staging on a caller's already owned transaction.

    Only server-loaded encrypted custody is interpreted. The original invocation
    and explicit stopped-request review supply their own current binding. No
    commit, source projection, credentials or transport belongs to this helper.
    """
    header,original=repository.open_issuance(issuance['record_id'])
    receipt,body=repository.open_receipt(attempt_id)
    if header['artifact_sha256']!=request_sha256 or receipt['fence_token']!=fence_token:
        raise NativeDispatchError('native_observation_request_binding')
    fallback=repository.open_clearance_fallback(issuance) if header['endpoint']!=receipt['endpoint'] else None
    assessment=assess_native_receipt(header,original,receipt,body,fallback_receipt=fallback)
    current=repository.record_assessment(chain,issuance,attempt_id=attempt_id,
        fence_token=fence_token,outcome=assessment.outcome)
    return assessment,current


def read_retained_invoice(doctype,invoice_name,*,runtime,require_current_source=False,require_origin=False):
    """Read exact native custody using saved-source read ACL, not signing keys.

    No artifact generation, key/route/certificate lookup, source repair, current
    Company-phase requirement or HTTP occurs. Historical source identities must
    still match; a rename/rebind needs its explicit reviewed transition. Printing
    additionally requires the submitted saved business observation to match the
    original. Diagnostic reads deliberately retain access to changed originals.
    """
    if doctype not in SOURCE_TABLES or type(invoice_name) is not str or not invoice_name:
        raise NativeDispatchError('native_source_identity')
    with owned_worker_transaction(runtime) as owner:
        return read_retained_in_transaction(doctype,invoice_name,runtime=runtime,owner=owner,
            require_current_source=require_current_source,require_origin=require_origin)


def read_retained_in_transaction(doctype,invoice_name,*,runtime,owner,require_current_source=False,require_origin=False):
    """Use the canonical custody/receipt reader inside an already owned scope.

    This internal seam retains the same ACL, current source/projection, latest
    version and receipt matching rules; it neither acquires nor ends a transaction.
    """
    owner.require_owner()
    if doctype not in SOURCE_TABLES or type(invoice_name) is not str or not invoice_name:
        raise NativeDispatchError("native_source_identity")
    source=runtime.get_doc(doctype,invoice_name)
    company=runtime.get_doc('Company',source.company)
    _require_access(runtime,source,company,owner.actor,write=False)
    if require_current_source:
        # Current shared reads include native child rows, not the earlier
        # repeatable-read snapshot. Locks end with this read-only scope.
        with owner.preparing(_business_tables(runtime,source)):
            source=runtime.get_doc(doctype,invoice_name,for_update=True)
            company=runtime.get_doc('Company',source.company,for_update=True)
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
    from .late_acceptance_evidence import open_resolution
    open_resolution(repository,saved)  # Contradictory state cannot hide a saved resolution.
    publication=None
    observed_source=None
    render_source=None
    if require_current_source:
        from .issuing_attempt import _source_observation
        from .publication_source import publication_source_sha256,render_source_sha256
        observation=_source_observation(source)
        observed_source=source_observation_sha256((doctype,invoice_name),observation)
        render_source=render_source_sha256((doctype,invoice_name),observation)
        publication=repository.open_publication(header)
        current=(publication_source_sha256((doctype,invoice_name),observation) if publication is not None else
            observed_source)
        if source.get('docstatus') != 1 or current!=(publication if publication is not None else header['source_sha256']):
            raise NativeDispatchError('native_publication_source_review')
    xml,_evidence=_original(header,original)
    outcome='RETAINED_ORIGINAL';warnings=0;has_warnings=False;returned=None
    accepted=saved['state'] in ('REPORTED','CLEARED')
    accepted_attempt=saved['active_attempt']
    if accepted:
        if not saved['active_attempt']:
            raise NativeDispatchError('native_retained_acceptance_review')
        from .late_acceptance_evidence import accepted_receipt
        receipt,body=accepted_receipt(repository,saved)
        fallback=repository.open_clearance_fallback(saved) if header['endpoint']!=receipt['endpoint'] else None
        assessment=assess_native_receipt(header,original,receipt,body,fallback_receipt=fallback)
        required=('REPORTING_MATCHED','REPORTING_DUPLICATE_MATCHED') if saved['state']=='REPORTED' else (
            'CLEARANCE_MATCHED','CLEARANCE_DUPLICATE_MATCHED')
        if assessment.outcome not in required:
            raise NativeDispatchError('native_retained_acceptance_review')
        outcome=assessment.outcome;warnings=assessment.warning_count;has_warnings=assessment.has_warnings
        returned=assessment.returned_xml
        accepted_attempt=receipt['record_id']
    origin=None
    if require_origin:
        from .issuance_origin import verify_origin_request
        from .issuance_candidate import _invoice_classification
        origin=repository.open_origin(header)
        if origin is not None:
            if origin['simplified']!=_invoice_classification(xml)[1].startswith('02'):
                raise NativeDispatchError('native_origin_classification')
            verify_origin_request(owner,origin,header)
    return RetainedNativeView(saved['record_id'],accepted_attempt,saved['state'],outcome,
        accepted,warnings,has_warnings,xml,returned,header['source_sha256'],
        header['invoice_uuid'],header['icv'],header['chain'],publication,render_source,header['invoice_hash'],origin)


def _project_source_status(doctype, invoice_name, *, runtime, readonly_cache=False, expected_issuance_id=None):
    # Import at the coordinator boundary: the projector reuses source ACL and
    # identity helpers but cannot invoke transport or create another issuance.
    from .native_projection import project_accepted_status
    return project_accepted_status(doctype, invoice_name, runtime=runtime,
        skip_if_readonly=readonly_cache,expected_issuance_id=expected_issuance_id).projected


def dispatch_saved_invoice(doctype, invoice_name, *, runtime, translate, build, retry_attempt_id=None,
                           expected_issuance_id=None,retry_fence_token=None):
    """One native preparation, exact dispatch/custody and bounded303 fallback.

    Internal coordinator only, not a whitelisted RPC or public build callback.
    Each service owns and commits its separate transaction. The response is
    retained before assessment, and no legacy source-reset handler runs here.
    Accepted source status is projected after receipt assessment. QR/XML reading
    is separate; File publication and complete runtime qualification remain open.
    """
    retained=read_retained_invoice(doctype,invoice_name,runtime=runtime)
    if expected_issuance_id is not None and (retained is None or retained.issuance_id!=expected_issuance_id):
        raise NativeDispatchError('native_expected_issuance_changed')
    expected={} if expected_issuance_id is None else {'expected_issuance_id':expected_issuance_id}
    if retained is not None and retained.accepted:
        projection_failed = False
        try:
            projected = _project_source_status(doctype, invoice_name, runtime=runtime, readonly_cache=True,**expected)
        except Exception:
            projection_failed = True
        if projection_failed:
            raise NativeDispatchReview('native_source_projection_incomplete', issuance_id=retained.issuance_id,
                attempt_id=retained.attempt_id, invoked=False, receipt_retained=True)
        return NativeDispatchOutcome(retained.issuance_id,retained.attempt_id,retained.outcome,
            True,retained.warning_count,retained.has_warnings,True,projected)
    if retained is None:
        prepare_saved_invoice(doctype, invoice_name, runtime=runtime, translate=translate, build=build)
    supersedes = retry_attempt_id
    for step in range(2):
        invocation = reserve_saved_issuance(doctype, invoice_name, runtime=runtime,
            translate=translate, supersedes_attempt=supersedes,**expected,
            **({'expected_prior_fence':retry_fence_token} if step==0 and retry_fence_token is not None else {}))
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
        projected = False
        if current and assessment.outcome in ('REPORTING_MATCHED', 'REPORTING_DUPLICATE_MATCHED',
                'CLEARANCE_MATCHED', 'CLEARANCE_DUPLICATE_MATCHED'):
            projection_failed = False
            try:
                projected = _project_source_status(doctype, invoice_name, runtime=runtime,**expected)
            except Exception:
                projection_failed = True
            if projection_failed:
                raise NativeDispatchReview('native_source_projection_incomplete', issuance_id=invocation.issuance_id,
                    attempt_id=invocation.attempt_id, invoked=True, receipt_retained=True)
        return NativeDispatchOutcome(invocation.issuance_id, invocation.attempt_id, assessment.outcome,
            current, assessment.warning_count, assessment.has_warnings,source_projected=projected)
    raise NativeDispatchReview('native_fallback_limit', issuance_id=invocation.issuance_id,
        attempt_id=invocation.attempt_id, invoked=True, receipt_retained=True)
