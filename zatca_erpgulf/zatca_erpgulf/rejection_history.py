"""Require coherent original-attempt history before creating a corrected version.

A later400 cannot erase a previous unknown invocation or matching acceptance.
Expiry is no proof of nonreceipt. All known receipts are rederived from custody;
mutable outcome labels, including blank labels, are never the decision source.
"""

from .native_response import assess_native_receipt


class RejectionHistoryError(RuntimeError):
    def __init__(self,code):self.code=code;super().__init__(code)


def require_rejection_history(repository,chain,issuance,header,original,rejected_attempt_id):
    rows=repository.lock_attempt_history(chain,issuance)
    if not rows or rows[-1]['record_id']!=rejected_attempt_id:
        raise RejectionHistoryError('rejection_history_current_attempt')
    budget=16*1024*1024
    for row in rows:
        if row['state']!='RESPONSE_RETAINED':
            raise RejectionHistoryError('rejection_history_unknown_attempt')
        receipt,body=repository.open_receipt(row['record_id'])
        budget-=len(body)
        if budget<0:raise RejectionHistoryError('rejection_history_response_budget')
        fallback=repository.open_clearance_fallback(issuance) if receipt['endpoint']!=header['endpoint'] else None
        assessment=assess_native_receipt(header,original,receipt,body,fallback_receipt=fallback)
        if (assessment.outcome not in ('VALIDATION_REJECTED','AUTHORIZATION_FAILED','CLEARANCE_DISABLED')
                or row['record_id']==rejected_attempt_id and assessment.outcome!='VALIDATION_REJECTED'):
            raise RejectionHistoryError('rejection_history_conflicting_or_uncertain_receipt')
