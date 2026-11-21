"""An exact current400 is necessary but cannot erase prior original uncertainty."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf.rejection_history import require_rejection_history,RejectionHistoryError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_response import evidence,success


def history(status=400,*,state='RESPONSE_RETAINED'):
    header,original,xml=evidence()
    rejected=dict(validationResults=dict(status='ERROR',warningMessages=[],infoMessages=[],
        errorMessages=[dict(type='ERROR',status='ERROR',code='SYNTHETIC',message='Rejected')]),reportingStatus='NOT_REPORTED')
    bodies=[json.dumps(success(header,xml) if status==200 else rejected).encode(),json.dumps(rejected).encode()]
    receipts=[dict(issuance=header['record_id'],request_sha256=header['artifact_sha256'],environment=header['environment'],
        endpoint=header['endpoint'],http_status=code,response_sha256=hashlib.sha256(body).hexdigest())
        for code,body in zip((status,400),bodies)]
    rows=[dict(record_id='OLD',state=state,outcome='VALIDATION_REJECTED'),dict(record_id='CURRENT',state='RESPONSE_RETAINED')]
    repository=SimpleNamespace(lock_attempt_history=Mock(return_value=rows))
    pairs=dict(zip(('OLD','CURRENT'),zip(receipts,bodies)))
    repository.open_receipt=Mock(side_effect=lambda identifier:pairs[identifier])
    check=lambda:require_rejection_history(repository,'CHAIN','ISSUANCE',header,original,'CURRENT')
    return repository,rows,receipts,check


@pytest.mark.parametrize('status',[400,401,403])
def test_safe_prior_receipts_are_rederived_even_when_their_mutable_label_is_wrong(status):
    repository,rows,receipts,check=history(status);rows[0]['outcome']='REPORTING_MATCHED'
    check();assert repository.open_receipt.call_count==2


@pytest.mark.parametrize('status',[200,202,208,409,500,503])
def test_prior_acceptance_or_uncertain_response_holds_replacement_despite_a_later400(status):
    repository,rows,receipts,check=history(status)
    with pytest.raises(RejectionHistoryError):check()


@pytest.mark.parametrize('state',['STARTED','OUTCOME_UNKNOWN'])
def test_unreceived_attempt_never_becomes_rejected_by_age_or_a_later_response(state):
    repository,rows,receipts,check=history(state=state)
    with pytest.raises(RejectionHistoryError,match='unknown_attempt'):check()
    repository.open_receipt.assert_not_called()


def test_incomplete_or_wrong_latest_attempt_history_cannot_authorize_replacement():
    repository,rows,receipts,check=history();repository.lock_attempt_history.return_value=[]
    with pytest.raises(RejectionHistoryError):check()
    repository.lock_attempt_history.return_value=rows[:-1]
    with pytest.raises(RejectionHistoryError):check()


def test_corrupt_prior_receipt_is_not_ignored_as_a_diagnostic_failure():
    repository,rows,receipts,check=history();receipts[0]['response_sha256']='0'*64
    with pytest.raises(RejectionHistoryError):check()
