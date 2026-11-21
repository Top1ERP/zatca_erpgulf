"""Current exact-attempt retry evidence; no queue, signing, commit or transport."""

from .dispatch_store import DispatchStoreError
from .native_response import assess_native_receipt


def require_retry_evidence(repository,chain,issuance,*,attempt_id,expected_fence,now_utc):
    """Use the same lease/chain gate at inspection, finalization and reservation.

    A retained technical/authentication failure must be rederived from encrypted
    original/receipt custody. Mutable outcome/status labels alone cannot shorten
    a reservation. Unknown outcomes retain the exact original invoice identity.
    """
    prior=repository.require_uncertain_retry(chain,issuance,attempt_id=attempt_id,
        expected_fence=expected_fence,now_utc=now_utc)
    if prior['state']=='RESPONSE_RETAINED':
        header,original=repository.open_issuance(issuance['record_id'])
        receipt,body=repository.open_receipt(attempt_id)
        fallback=repository.open_clearance_fallback(issuance) if header['endpoint']!=receipt['endpoint'] else None
        assessment=assess_native_receipt(header,original,receipt,body,fallback_receipt=fallback)
        if (assessment.outcome not in ('AUTHORIZATION_FAILED','TECHNICAL_FAILURE')
                or assessment.outcome!=prior['outcome'] or receipt['fence_token']!=prior['fence_token']):
            raise DispatchStoreError('dispatch_retry_failure_unconfirmed')
    return prior
