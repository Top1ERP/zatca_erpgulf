"""Owned saved-source legacy continuity review; never automatic live cutover.

Retain the reviewed last-generated anchor and exact private XML as an inactive
registration candidate. This operation does not retire legacy counters, alter
invoice/Company data, initialize genesis, activate credentials or call an API.
Complete history, drained legacy workers and activation remain separate gates.
"""

from dataclasses import dataclass
import hashlib
from uuid import uuid4

from .artifact_evidence import ArtifactEvidenceError, inspect_invoice_artifact
from .artifact_inventory import _read_local_attachment
from .certificate_evidence import inspect_embedded_certificate
from .chain_registration import (
    ChainRegistrationError, encode_registration_payload, reason_bytes,
)
from .dispatch_record_codec import DispatchRecordError, _identifier
from .dispatch_store import DispatchStore, DispatchStoreError, _counter, _fingerprint
from .icv import _counter_key
from .issuing_attempt import ACTIVE, IssuingAttemptError, issuing_attempt
from .native_dispatch import NativeDispatchError, SOURCE_TABLES, owner_key, _require_access
from .native_preparation import source_observation_sha256
from .native_legacy_tail import require_unambiguous_saved_tail
from .native_identity_inventory import IdentityInventoryError
from .native_legacy_consumers import require_single_legacy_counter
from .native_legacy_history import (
    inspect_known_legacy_history, LegacyHistoryInventory, inspect_known_legacy_page, LegacyHistoryPage,
)
from .legacy_history_capture import HistoryCaptureStore, HistoryCaptureResult
from .issuing_observation import freeze_native_value
from .permission_compat import PermissionCompatibilityError, saved_row_has_permission
from .worker_transaction import WorkerTransactionError, owned_worker_transaction


@dataclass(frozen=True, repr=False)
class LegacyRegistrationReview:
    record_id: str
    last_icv: str
    reused: bool
    active: bool = False
    history: LegacyHistoryInventory | None = None
    history_page: LegacyHistoryPage | None = None
    capture: HistoryCaptureResult | None = None


def _name(value):
    if (type(value) is not str or not 0 < len(value) <= 140 or value != value.strip()
            or any(ord(c) < 32 for c in value)):
        raise ChainRegistrationError('registration_source_identity')
    return value


def _readable(runtime, document, actor, *, write=False):
    for operation in ('read', 'write') if write else ('read',):
        if not saved_row_has_permission(runtime.has_permission,document.doctype,operation,doc=document,user=actor):
            raise ChainRegistrationError('registration_source_permission')


def _saved(runtime, doctype, name, actor, *, write=False):
    document = runtime.get_doc(doctype,name,for_update=True)
    if document.doctype != doctype or document.name != name:
        raise ChainRegistrationError('registration_source_identity')
    _readable(runtime,document,actor,write=write)
    return document


def _icv(value):
    if type(value) not in (int,str):
        raise ChainRegistrationError('registration_counter_precision')
    text = str(value)
    _counter(text)
    return text


def _require_current_issuer_records(runtime, owner, scope):
    """Compare captured issuer projections to current locking ORM reads.

    A prior invoice SELECT may have opened an older REPEATABLE-READ view. The
    scope's ordinary drift observations alone cannot upgrade that view. Include
    a delegated device's link/flag as well as the actual signing owner and route.
    """
    for (doctype, name), observed in scope.records.items():
        if doctype not in ('Company', 'ZATCA Multiple Setting'):
            raise ChainRegistrationError('registration_issuer_snapshot_changed')
        current = _saved(runtime,doctype,name,owner.actor)
        has_field = getattr(getattr(current,'meta',None),'has_field',None)
        present = frozenset(field for field in observed.values if (
            has_field(field) if callable(has_field) else hasattr(current,field)))
        if (present != observed.fields_present or any(freeze_native_value(current.get(field)) !=
                freeze_native_value(value) for field,value in observed.values.items())):
            raise ChainRegistrationError('registration_issuer_snapshot_changed')


def _legacy_anchor(runtime, owner, source, counter_name):
    counter = _saved(runtime,'ZATCA ICV Counter',counter_name,owner.actor)
    # Lock order: routing Company/selected owner, counter, source, File, review.
    source = _saved(runtime,source.doctype,source.name,owner.actor)
    unit = source.get('custom_zatca_issuing_unit')
    if type(unit) is not str or not unit or unit.startswith('egs:'):
        raise ChainRegistrationError('registration_legacy_unit_required')
    expected = _counter_key(source.company,unit,'Production')
    if (counter_name != expected or counter.get('counter_key') != expected
            or counter.get('company') != source.company or counter.get('issuing_unit') != unit
            or counter.get('environment') != 'Production' or counter.get('active') not in (1,'1')
            or counter.get('last_invoice_doctype') != source.doctype or counter.get('last_invoice') != source.name):
        raise ChainRegistrationError('registration_counter_binding')
    value = _icv(counter.get('last_issued_icv'))
    if _icv(source.get('custom_zatca_icv')) != value:
        raise ChainRegistrationError('registration_counter_tail_mismatch')
    # The old counter's environment is its credential PURPOSE, not API gateway.
    # Look across Companies too; a shared-unit duplicate must not be merged by
    # taking the maximum counter or selecting the last accepted invoice.
    rows = owner.database.sql('SELECT name FROM `tabZATCA ICV Counter` '
        'WHERE issuing_unit=%s AND environment=%s LIMIT 2 FOR UPDATE NOWAIT', (unit,'Production'),as_dict=True)
    if len(rows) != 1 or rows[0]['name'] != counter_name:
        raise ChainRegistrationError('registration_counter_ambiguous')
    _identifier(source.get('custom_uuid'))
    if source.get('docstatus') not in (1,2):
        raise ChainRegistrationError('registration_generated_source_review')
    require_unambiguous_saved_tail(owner,source,unit,value)
    return source, unit, value


def review_legacy_registration(doctype, invoice_name, counter_name, file_id, *,
                              runtime, translate, reason, expected_xml_sha256, supersedes_review_id=None,
                              history_review_id=None, history_page_after=None, history_capture=False):
    """Stage one exact reviewed anchor, preserving both existing systems.

    Internal service only, no RPC/worker hook or caller-supplied approval flag.
    Requires System Manager, source/Company/counter/File READ and actual selected
    credential-owner READ+WRITE. A caller provides the hash of the file they
    reviewed, not XML bytes, credentials, a counter seed or a namespace/key.
    Missing or inconsistent evidence stops; it never creates a NEW_EGS record.
    With both history_review_id and history_page_after, read one partial page
    of an unchanged existing inactive review. Paging cannot create/supersede a
    review or persist a cumulative history approval; no commit is performed.
    Explicit history_capture=True instead retains immutable encrypted page/XML
    bytes and its protected head atomically. It still grants no activation.
    """
    uncertain = False
    try:
        return _review_legacy_registration(doctype,invoice_name,counter_name,file_id,runtime=runtime,
            translate=translate,reason=reason,expected_xml_sha256=expected_xml_sha256,
            supersedes_review_id=supersedes_review_id,history_review_id=history_review_id,
            history_page_after=history_page_after,history_capture=history_capture)
    except (ChainRegistrationError,DispatchRecordError,DispatchStoreError,NativeDispatchError,
            ArtifactEvidenceError,IssuingAttemptError,IdentityInventoryError) as error:
        code = error.code
    except PermissionCompatibilityError:
        code = 'permission_engine_signature'
    except WorkerTransactionError as error:
        uncertain = error.commit_uncertain
        code = 'registration_commit_unknown' if uncertain else error.code
    except Exception:
        code = 'registration_review_failed'
    # Never chain raw ORM/driver/path/credential diagnostics into a public parent.
    raise ChainRegistrationError(code,commit_uncertain=uncertain)


def _review_legacy_registration(doctype, invoice_name, counter_name, file_id, *,
                               runtime, translate, reason, expected_xml_sha256, supersedes_review_id,
                               history_review_id, history_page_after, history_capture):
    if ACTIVE.get() is not None:
        raise ChainRegistrationError('registration_issuing_context_active')
    if doctype not in SOURCE_TABLES:
        raise ChainRegistrationError('registration_source_identity')
    for value in (invoice_name,counter_name,file_id):
        _name(value)
    _fingerprint(expected_xml_sha256)
    if supersedes_review_id is not None:
        _identifier(supersedes_review_id)
    paging = history_page_after is not None or history_review_id is not None
    if type(history_capture) is not bool or (history_capture and not paging):
        raise ChainRegistrationError('registration_history_capture_operation')
    if paging:
        _identifier(history_review_id); _counter(history_page_after, zero=True)
        if supersedes_review_id is not None:
            raise ChainRegistrationError('registration_history_page_supersedes')
    text = reason_bytes(reason)
    with owned_worker_transaction(runtime) as owner:
        roles = runtime.get_roles(owner.actor)
        if type(roles) not in (list,tuple) or 'System Manager' not in roles:
            raise ChainRegistrationError('registration_manager_required')
        source = runtime.get_doc(doctype,invoice_name)
        company = _saved(runtime,'Company',source.company,owner.actor)
        _require_access(runtime,source,company,owner.actor,write=False)
        with issuing_attempt(company.abbr,source,purpose='production',runtime=runtime,
                translate=translate,invoice_doc=source) as scope:
            scope.require_production_configuration()
            selected = _saved(runtime,scope.owner.doctype,scope.owner.name,owner.actor,write=True)
            _require_current_issuer_records(runtime,owner,scope)
            material = scope.signing_material()
            source, unit, value = _legacy_anchor(runtime,owner,source,counter_name)
            scope.bind_prepared_invoice(source)
            pointer = selected.get('custom_zatca_icv_counter')
            if pointer not in (None,'',counter_name):
                raise ChainRegistrationError('registration_counter_pointer_mismatch')
            file_doc = _saved(runtime,'File',file_id,owner.actor)
            xml = _read_local_attachment(file_doc,doctype,invoice_name,runtime=runtime)
            if hashlib.sha256(xml).hexdigest() != expected_xml_sha256:
                raise ChainRegistrationError('registration_reviewed_file_changed')
            observed = inspect_invoice_artifact(xml)
            certificate = inspect_embedded_certificate(xml)
            if (observed.invoice_id != invoice_name or observed.uuid != source.get('custom_uuid')
                    or str(observed.icv) != value or observed.seller_tax_id != company.get('tax_id')
                    or observed.invoice_digest != selected.get('custom_pih')):
                raise ChainRegistrationError('registration_generated_head_mismatch')
            if (certificate.der_sha256,certificate.public_key_sha256) != (
                    material.certificate_der_sha256,material.public_key_sha256):
                raise ChainRegistrationError('registration_certificate_review')
            require_single_legacy_counter(runtime,owner,selected,material.public_key_sha256,unit,counter_name)
            history = (None if paging else
                inspect_known_legacy_history(runtime,owner,source,unit,observed,material.public_key_sha256))
            scope.confirm_current()
            payload = encode_registration_payload(xml,reason)
            route = material.route
            header = {
                'record_id': str(uuid4()),
                'owner_key': owner_key(selected.doctype, selected.name, route.environment),
                'owner_doctype': selected.doctype,
                'owner_name': selected.name,
                'company': company.name,
                'environment': route.environment,
                'seller_tax_id': company.get('tax_id'),
                'registration_kind': 'LEGACY_REVIEWED',
                'certificate_sha256': material.certificate_der_sha256,
                'public_key_sha256': material.public_key_sha256,
                'base_url_sha256': hashlib.sha256(
                    route.url.removesuffix('/' + route.endpoint).encode()).hexdigest(),
                'source_doctype': doctype,
                'source_name': invoice_name,
                'source_uuid': source.get('custom_uuid'),
                'source_unit': unit,
                'legacy_counter': counter_name,
                'icv': value,
                'invoice_hash': observed.invoice_digest,
                'file_id': file_id,
                'xml_sha256': expected_xml_sha256,
                'source_sha256': source_observation_sha256(
                    scope.source_identity, scope.source_observation),
                'reviewed_by': owner.actor,
                'reviewed_at_utc': owner.utc_now().strftime('%Y-%m-%dT%H:%M:%S.%f'),
                'reason_sha256': hashlib.sha256(text).hexdigest(),
                'payload_sha256': hashlib.sha256(payload).hexdigest(),
                'supersedes_review': supersedes_review_id,
            }
            repository = DispatchStore(owner.database,storage_namespace=owner.storage_namespace,
                cipher=owner.cipher,owner_check=owner.owner_current)
            existing = repository.reviewed_chain_for_owner(header['owner_key'])
            if paging and (existing is None or existing['record_id'] != history_review_id):
                raise ChainRegistrationError('registration_history_review_changed')
            if existing is not None:
                if (existing['active'] != 0 or existing['state_version'] != 0 or existing['active_owner_key'] is not None
                        or existing['tail_issuance'] is not None or existing['active_attempt'] is not None):
                    raise ChainRegistrationError('registration_existing_chain_review')
                old, old_xml, old_reason = repository.open_reviewed_registration(existing)
                ignored = {'record_id','reviewed_by','reviewed_at_utc'}
                if supersedes_review_id is None:
                    ignored.add('supersedes_review')
                unchanged = (all(header[key] == old[key] for key in header.keys()-ignored)
                    and old_xml == xml and old_reason == reason and existing['last_icv'] == value
                    and existing['previous_hash'] == observed.invoice_digest)
                if unchanged:
                    if paging:
                        capture_store = HistoryCaptureStore(runtime,owner,old,existing) if history_capture else None
                        if capture_store is not None:
                            retained = capture_store.lookup(history_page_after)
                            if retained is not None:
                                captured, page = retained
                                scope.confirm_current()
                                return LegacyRegistrationReview(existing['record_id'],value,True,history_page=page,capture=captured)
                        capture_buffer = {} if history_capture else None
                        page = inspect_known_legacy_page(runtime,owner,source,unit,observed,material.public_key_sha256,
                            review_id=history_review_id,after_icv=history_page_after,
                            **({'capture_buffer':capture_buffer,'anchor_xml':xml,'anchor_file_id':file_doc.name}
                                if history_capture else {}))
                        captured = None if capture_store is None else capture_store.stage(page,capture_buffer)
                        scope.confirm_current()
                        if captured is not None:
                            owner.commit()
                        return LegacyRegistrationReview(existing['record_id'],value,True,history_page=page,capture=captured)
                    return LegacyRegistrationReview(existing['record_id'],value,True,history=history)
                if supersedes_review_id != existing['record_id']:
                    raise ChainRegistrationError('registration_review_changed')
            elif supersedes_review_id is not None:
                raise ChainRegistrationError('registration_supersedes_missing')
            reviewed = repository.stage_reviewed_registration(header,payload,supersedes=existing)
            owner.commit()
            return LegacyRegistrationReview(reviewed['record_id'],value,False,history=history)
