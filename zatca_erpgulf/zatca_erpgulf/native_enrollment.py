"""Fenced initial Compliance/Final-CSID custody for an owned fresh CSR.

Reservations commit before HTTP. Exact responses commit before material parsing
and owner projection, so a local failure recovers the receipt without resending.
No renewal, legacy adoption, automatic retry, namespace bootstrap or native-chain
activation is performed. FINAL_READY remains inactive pending reviewed adoption.
"""

import base64
from dataclasses import dataclass, field
from datetime import timezone
import hashlib
import json
from uuid import uuid4

from .api_routing import resolve_api_route
from .credential_material import NATIVE_OWNER_TABLES as OWNER_TABLES
from .dispatch_record_codec import encode_record_header
from .invoice_xml_core import INITIAL_PREVIOUS_HASH
from .native_dispatch import owner_key, _changed_once
from .native_onboarding import (
    MARKER, PROTECTED_FIELDS, WATCHED_OWNER_FIELDS, NativeOnboardingError, _load_initial_owner, _verify_saved_csr,
    _verify_saved_material, _columns, native_mode_enabled, intent_sha256,
)
from .native_transport import NativeResponse
from .onboarding_response import parse_issued_csid, is_retryable_rejection
from .onboarding_store import OnboardingStore, BEFORE, READY, RECEIVED, PENDING
from .onboarding_transport import OnboardingInvocation, invoke_onboarding_request
from .worker_transaction import owned_worker_transaction


@dataclass(frozen=True, repr=False)
class EnrollmentOutcome:
    record_id: str
    state: str
    reused: bool
    active: bool = False


@dataclass(frozen=True, repr=False)
class _Prepared:
    record_id: str
    invocation: object = field(default=None, repr=False)


def _repository(owner):
    return OnboardingStore(owner.database, storage_namespace=owner.storage_namespace,
        cipher=owner.cipher, owner_check=owner.owner_current)


def _body(endpoint, csr, compliance=None):
    values = {'csr': base64.b64encode(csr).decode('ascii')} if endpoint == 'compliance' else {
        'compliance_request_id': compliance.request_id}
    return json.dumps(values, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _observation(company, target, route):
    return (target.doctype, target.name, tuple(target.get(key) for key in WATCHED_OWNER_FIELDS),
            company.name, company.get('tax_id'), route)


def _recheck(runtime, owner, company_abbr, supplied, portal_type, observation):
    company, target, route = _load_initial_owner(runtime, owner, company_abbr, supplied, portal_type)
    if _observation(company, target, route) != observation:
        raise NativeOnboardingError('native_onboarding_source_changed')


def _load(runtime, owner, company_abbr, supplied, portal_type):
    if not native_mode_enabled(runtime):
        raise NativeOnboardingError('native_onboarding_disabled')
    company, target, route = _load_initial_owner(runtime, owner, company_abbr, supplied, portal_type)
    repo = _repository(owner)
    marker = target.get(MARKER)
    chain = repo.lock_recorded_chain(marker, owner_key(target.doctype, target.name, route.environment))
    intent, csr, state = repo.open_onboarding_intent(chain)
    if (intent['company'] != company.name or intent['seller_tax_id'] != company.get('tax_id')
            or intent['environment'] != route.environment
            or intent['base_url_sha256'] != hashlib.sha256(route.url.removesuffix('/'+route.endpoint).encode()).hexdigest()
            or intent_sha256(encode_record_header(dict(intent)), csr) != chain['registration_evidence_sha256']):
        raise NativeOnboardingError('native_onboarding_intent_review')
    _verify_saved_csr(target, intent, csr)
    if target.get('custom_pih') not in (None, '', INITIAL_PREVIOUS_HASH) or target.get('custom_zatca_icv_counter'):
        raise NativeOnboardingError('native_onboarding_existing_history_review')
    status = repo.state(chain)
    if status['onboarding_state'] != state:
        raise NativeOnboardingError('native_onboarding_state_review')
    return company, target, route, repo, chain, intent, csr, status


def _bound_attempt(repo, record_id, *, intent, csr, chain, endpoint, compliance=None):
    header, body, receipt, response = repo.open_attempt(record_id)
    expected = {key: intent[key] for key in ('owner_key', 'company', 'environment', 'base_url_sha256',
        'public_key_sha256', 'csr_sha256', 'configuration_sha256')}
    expected.update(chain=chain['record_id'], endpoint=endpoint, intent_sha256=chain['registration_evidence_sha256'])
    if (any(header[key] != value for key, value in expected.items())
            or body != _body(endpoint, csr, compliance)):
        raise NativeOnboardingError('native_onboarding_attempt_binding')
    return header, receipt, response


def _issued(repo, record_id, *, intent, csr, chain, endpoint, observed_at, compliance=None):
    header, receipt, response = _bound_attempt(repo, record_id, intent=intent, csr=csr, chain=chain,
        endpoint=endpoint, compliance=compliance)
    if receipt is None:
        raise NativeOnboardingError('native_onboarding_outcome_unknown')
    issued = parse_issued_csid(receipt['http_status'], response, intent=intent, csr=csr, observed_at=observed_at)
    return header, issued


def _writes(target, issued, endpoint):
    if endpoint == 'compliance':
        certificate = 'custom_certificate' if target.doctype == 'Company' else 'custom_certficate'
        return {certificate: issued.certificate_text, 'custom_basic_auth_from_csid': issued.authorization,
                'custom_compliance_request_id_': issued.request_id}
    authorization = 'custom_basic_auth_from_production' if target.doctype == 'Company' else 'custom_final_auth_csid'
    return {'custom_certificate': issued.certificate_text, authorization: issued.authorization}


def _matches_owner(target, writes, *, allow_compliance=False):
    allowed = {'custom_private_key', 'custom_csr_data', *writes}
    if allow_compliance:
        allowed.update(('custom_basic_auth_from_csid', 'custom_compliance_request_id_'))
        if target.doctype == 'ZATCA Multiple Setting':
            allowed.add('custom_certficate')
    if (any(target.get(key) != value for key, value in writes.items())
            or any(target.get(key) not in (None, '') for key in PROTECTED_FIELDS if key not in allowed)):
        raise NativeOnboardingError('native_onboarding_saved_response_review')


def _compliance(repo, status, *, target, intent, csr, chain, observed_at, final_saved=False):
    record_id = status['onboarding_compliance_attempt']
    if record_id is None:
        raise NativeOnboardingError('native_onboarding_compliance_required')
    _, issued = _issued(repo, record_id, intent=intent, csr=csr, chain=chain, endpoint='compliance', observed_at=observed_at)
    writes = _writes(target, issued, 'compliance')
    if final_saved and target.doctype == 'Company':
        # The existing Company schema has one certificate field; Final projection
        # replaces it. The immutable encrypted Compliance receipt remains intact.
        writes.pop('custom_certificate')
    if any(target.get(key) != value for key, value in writes.items()):
        raise NativeOnboardingError('native_onboarding_saved_response_review')
    if not final_saved:
        _matches_owner(target, writes)
        if chain['certificate_sha256'] != issued.certificate_sha256:
            raise NativeOnboardingError('native_onboarding_saved_response_review')
    return issued


def _prepare(company_abbr, supplied, endpoint, portal_type, *, runtime):
    with owned_worker_transaction(runtime) as owner:
        company, target, route, repo, chain, intent, csr, status = _load(
            runtime, owner, company_abbr, supplied, portal_type)
        observation = _observation(company, target, route)
        state = status['onboarding_state']
        if state == PENDING[endpoint]:
            # No lease/timeout can prove a certificate was not remotely issued.
            raise NativeOnboardingError('native_onboarding_outcome_unknown')
        if state == RECEIVED[endpoint]:
            compliance = (_compliance(repo, status, target=target, intent=intent, csr=csr, chain=chain,
                observed_at=owner.utc_now().replace(tzinfo=timezone.utc)) if endpoint == 'production/csids' else None)
            previous, receipt, body = _bound_attempt(repo, status['onboarding_attempt'], intent=intent,
                csr=csr, chain=chain, endpoint=endpoint, compliance=compliance)
            if receipt is not None and is_retryable_rejection(endpoint, receipt['http_status'], body):
                # Only a subsequent explicit service/button invocation gets here.
                # The receiving invocation returned a failure and never retried.
                repo.release_rejected(chain, dict(previous))
                chain = repo.lock_recorded_chain(chain['record_id'], chain['owner_key'])
                status = repo.state(chain)
                state = status['onboarding_state']
        if state in (RECEIVED[endpoint], READY[endpoint]):
            record_id = status['onboarding_attempt'] if state == RECEIVED[endpoint] else status[
                'onboarding_compliance_attempt' if endpoint == 'compliance' else 'onboarding_final_attempt']
            return _Prepared(record_id)
        if state != BEFORE[endpoint]:
            raise NativeOnboardingError('native_onboarding_step_required')
        now = owner.utc_now()
        compliance = None
        if endpoint == 'compliance':
            _verify_saved_material(target, intent, csr)
            otp = target.get('custom_otp')
            if type(otp) is not str or len(otp.strip()) != 6 or not otp.strip().isascii() or not otp.strip().isdecimal():
                raise NativeOnboardingError('native_onboarding_otp_required')
            otp, authorization = otp.strip(), ''
        else:
            compliance = _compliance(repo, status, target=target, intent=intent, csr=csr, chain=chain,
                observed_at=now.replace(tzinfo=timezone.utc))
            otp, authorization = '', 'Basic '+compliance.authorization
            route = resolve_api_route(vars(company) if not hasattr(company, 'as_dict') else company.as_dict(), endpoint,
                onboarding_only=True)
        body = _body(endpoint, csr, compliance)
        header = {key: intent[key] for key in ('owner_key', 'company', 'environment', 'base_url_sha256',
            'public_key_sha256', 'csr_sha256', 'configuration_sha256')}
        header.update(record_id=str(uuid4()), chain=chain['record_id'], endpoint=endpoint,
            intent_sha256=chain['registration_evidence_sha256'], request_sha256=hashlib.sha256(body).hexdigest(),
            previous_attempt=status['onboarding_attempt'], fence_token=str(uuid4()), created_by=owner.actor,
            created_at_utc=now.strftime('%Y-%m-%dT%H:%M:%S.%f'))
        _recheck(runtime, owner, company_abbr, supplied, portal_type, observation)
        repo.reserve(chain, header, body)
        invocation = OnboardingInvocation(header['record_id'], chain['record_id'], header['fence_token'],
            chain['owner_key'], owner.site, owner.actor, route, header['request_sha256'], body, otp, authorization)
        owner.commit()
        return _Prepared(header['record_id'], invocation)


def _retain(invocation, response, *, runtime):
    if (type(response) is not NativeResponse or runtime.local.site != invocation.site
            or runtime.session.user != invocation.actor):
        raise NativeOnboardingError('native_onboarding_transport_owner_review')
    with owned_worker_transaction(runtime) as owner:
        repo = _repository(owner)
        chain = repo.lock_recorded_chain(invocation.chain_id, invocation.owner_key)
        header, _, _, _ = repo.open_attempt(invocation.record_id)
        if (header['fence_token'] != invocation.fence_token or header['chain'] != invocation.chain_id
                or header['created_by'] != owner.actor or header['request_sha256'] != invocation.request_sha256):
            raise NativeOnboardingError('native_onboarding_transport_owner_review')
        if header['owner_key'] != invocation.owner_key:
            raise NativeOnboardingError('native_onboarding_transport_owner_review')
        changed = repo.retain_response(chain, dict(header), status=response.http_status,
            request_id=response.request_id, body=response.body)
        if changed:
            owner.commit()


def _admit(company_abbr, supplied, endpoint, portal_type, record_id, *, runtime, reused):
    with owned_worker_transaction(runtime) as owner:
        company, target, route, repo, chain, intent, csr, status = _load(runtime, owner, company_abbr, supplied, portal_type)
        observation = _observation(company, target, route)
        state = status['onboarding_state']
        if state not in (RECEIVED[endpoint], READY[endpoint]):
            raise NativeOnboardingError('native_onboarding_admission_review')
        pointer = 'onboarding_compliance_attempt' if endpoint == 'compliance' else 'onboarding_final_attempt'
        if record_id != status['onboarding_attempt' if state == RECEIVED[endpoint] else pointer]:
            raise NativeOnboardingError('native_onboarding_attempt_binding')
        now = owner.utc_now().replace(tzinfo=timezone.utc)
        compliance = None
        if endpoint == 'production/csids':
            compliance = _compliance(repo, status, target=target, intent=intent, csr=csr, chain=chain,
                observed_at=now, final_saved=state == READY[endpoint])
        header, issued = _issued(repo, record_id, intent=intent, csr=csr, chain=chain, endpoint=endpoint,
            compliance=compliance, observed_at=now)
        writes = _writes(target, issued, endpoint)
        if state == READY[endpoint]:
            _matches_owner(target, writes, allow_compliance=endpoint == 'production/csids')
            if chain['certificate_sha256'] != issued.certificate_sha256:
                raise NativeOnboardingError('native_onboarding_saved_response_review')
        else:
            if endpoint == 'compliance':
                _verify_saved_material(target, intent, csr)
            _columns(runtime, owner.database, target.doctype, writes)
            _recheck(runtime, owner, company_abbr, supplied, portal_type, observation)
            owner.database.sql('UPDATE '+OWNER_TABLES[target.doctype]+' SET '+
                ','.join('`'+key+'`=%s' for key in writes)+' WHERE name=%s', (*writes.values(), target.name))
            _changed_once(owner.database)
            repo.admit_response(chain, dict(header), certificate_sha256=issued.certificate_sha256)
            owner.commit()
        return EnrollmentOutcome(record_id, READY[endpoint], reused)


def request_initial_csid(company_abbr, supplied, endpoint, *, runtime, portal_type=None):
    """Internal owned service; native button adoption uses no caller success flag.

    A caller must not catch an uncertain outcome and invoke a legacy request.
    Pending and unknown/malformed receipts remain held. A later explicit call
    may reserve again after a retained Invalid-OTP/Missing-ComplianceSteps400.
    """
    failed = None
    uncertain = False
    try:
        if endpoint not in BEFORE:
            raise NativeOnboardingError('native_onboarding_operation')
        prepared = _prepare(company_abbr, supplied, endpoint, portal_type, runtime=runtime)
        if prepared.invocation is not None:
            response = invoke_onboarding_request(prepared.invocation, runtime=runtime)
            _retain(prepared.invocation, response, runtime=runtime)
        return _admit(company_abbr, supplied, endpoint, portal_type, prepared.record_id,
            runtime=runtime, reused=prepared.invocation is None)
    except Exception as error:
        failed = error.code if isinstance(error, NativeOnboardingError) else 'native_onboarding_response_review'
        uncertain = getattr(error, 'commit_uncertain', False) is True
    raise NativeOnboardingError(failed, commit_uncertain=uncertain)
