"""Authenticate an explicit late-response decision without changing originals.

The current technical-attempt pointer stays intact. Only this separate protected
decision can select an older receipt for accepted publication/status projection.
This module grants no transport, generation, correction or counter authority.
"""

from datetime import datetime

from .dispatch_record_codec import _identifier,encode_record_header,decode_record_header
from .dispatch_store import ASSESSMENT_STATES,_fingerprint,DispatchStoreError
from .saved_form_source import saved_form_name


BODY=b'zatca-reviewed-late-acceptance/v1'
FIELDS=('record_id','chain','artifact_sha256','accepted_attempt','accepted_fence',
    'response_sha256','prior_attempt','prior_fence','prior_state','prior_state_version',
    'resolved_by','resolved_at_utc','outcome')
OUTCOMES=('REPORTING_MATCHED','REPORTING_DUPLICATE_MATCHED','CLEARANCE_MATCHED','CLEARANCE_DUPLICATE_MATCHED')


def validate_proof(proof):
    if type(proof) is not dict or set(proof)!=set(FIELDS):
        raise DispatchStoreError('late_acceptance_proof_shape')
    for key in ('record_id','chain','accepted_attempt','accepted_fence','prior_attempt','prior_fence'):
        _identifier(proof[key])
    for key in ('artifact_sha256','response_sha256'):_fingerprint(proof[key])
    saved_form_name(proof['resolved_by'])
    if (proof['resolved_by']=='Guest' or proof['outcome'] not in OUTCOMES
            or proof['accepted_attempt']==proof['prior_attempt']
            or proof['prior_state'] not in ('DISPATCHING','OUTCOME_UNKNOWN')
            or type(proof['prior_state_version']) is not int or not 0<=proof['prior_state_version']<2147483647):
        raise DispatchStoreError('late_acceptance_proof_binding')
    try:stamp=datetime.strptime(proof['resolved_at_utc'],'%Y-%m-%dT%H:%M:%S.%f')
    except (TypeError,ValueError):raise DispatchStoreError('late_acceptance_proof_clock') from None
    if stamp.strftime('%Y-%m-%dT%H:%M:%S.%f')!=proof['resolved_at_utc']:
        raise DispatchStoreError('late_acceptance_proof_clock')
    return encode_record_header(proof)


def open_resolution(repository,issuance):
    """NULL evidence keeps the original current-receipt policy unchanged."""
    raw,ciphertext=(issuance.get(key) for key in ('late_acceptance_header','late_acceptance_ciphertext'))
    if raw is None and ciphertext is None:return None
    if any(type(value) is not str or not 0<len(value)<=8192 for value in (raw,ciphertext)):
        raise DispatchStoreError('late_acceptance_envelope')
    proof=dict(decode_record_header(raw.encode()))
    encoded=validate_proof(proof)
    if (any(proof[key]!=issuance[key] for key in ('record_id','chain','artifact_sha256'))
            or issuance['active_attempt']!=proof['prior_attempt']
            or issuance['state']!=ASSESSMENT_STATES[proof['outcome']]):
        raise DispatchStoreError('late_acceptance_issuance_binding')
    if repository.open_late_acceptance(issuance,encoded,ciphertext)!=BODY:
        raise DispatchStoreError('late_acceptance_integrity')
    return proof


def accepted_receipt(repository,issuance):
    """Select custody for shared native publication and status projection.

    Both callers still rerun the canonical native response matcher against the
    exact original. The decision cannot bless a generic HTTP status or body.
    """
    proof=open_resolution(repository,issuance)
    if proof is None:return repository.open_receipt(issuance['active_attempt'])
    return require_attempt_bindings(repository,issuance,proof)


def require_attempt_bindings(repository,issuance,proof):
    """Shared selected/prior custody checks during staging and every read."""
    receipt,body=repository.open_receipt(proof['accepted_attempt'])
    prior=repository._attempt(proof['prior_attempt'])
    if (receipt['fence_token']!=proof['accepted_fence'] or receipt['response_sha256']!=proof['response_sha256']
            or prior['fence_token']!=proof['prior_fence'] or prior['issuance']!=issuance['record_id']
            or receipt['issuance']!=issuance['record_id']
            or prior['request_sha256']!=issuance['artifact_sha256']
            or receipt['request_sha256']!=issuance['artifact_sha256']
            or prior['endpoint']!=receipt['endpoint']
            or prior['attempt_number']<=receipt['attempt_number']):
        raise DispatchStoreError('late_acceptance_attempt_binding')
    return receipt,body
