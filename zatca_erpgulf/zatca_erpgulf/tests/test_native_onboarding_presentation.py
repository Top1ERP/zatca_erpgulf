"""Native durable outcomes stay separate from legacy transient progress flags."""

import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client
from zatca_erpgulf.zatca_erpgulf.native_onboarding import PreparedNewUnit, NativeOnboardingError, ONBOARDING_REVIEW
from zatca_erpgulf.zatca_erpgulf.native_enrollment import EnrollmentOutcome
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import boundary, materials


class Review(Exception):
    pass


@pytest.fixture
def display(boundary,monkeypatch):
    b=boundary
    with (Path(__file__).resolve().parents[2]/'translations'/'ar.csv').open(encoding='utf-8',newline='') as handle:
        translations={row[0]:row[1] for row in csv.reader(handle) if len(row)>1}
    monkeypatch.setattr(client,'_',lambda value:translations.get(value,value))
    b.frappe.throw=Mock(side_effect=lambda text,**kwargs:(_ for _ in ()).throw(Review(text)))
    return b


def test_native_csr_recovery_returns_the_legacy_string_without_fake_save_flags(display):
    result=client._run_csr_operation('csr',lambda *args:PreparedNewUnit('UNIT','PUBLIC-CSR',True))
    assert result=='PUBLIC-CSR'
    display.frappe.throw.assert_not_called()
    display.frappe.msgprint.assert_not_called()


@pytest.mark.parametrize('purpose',['compliance','production'])
def test_native_success_is_one_arabic_notice_with_an_english_secret_free_result(display,purpose):
    def complete(progress):
        assert not any(vars(progress).values())
        return EnrollmentOutcome('ATTEMPT','FINAL_READY' if purpose=='production' else 'CCSID_READY',True)
    result=json.loads(client._run_csid_operation(purpose,complete))
    assert result['status']=='SUCCESS' and result['purpose']==purpose
    assert all(not any('\u0600'<=c<='\u06ff' for c in value) for value in result.values())
    display.frappe.msgprint.assert_called_once()
    message=display.frappe.msgprint.call_args.args[0]['message']
    assert 'غير مفعلة' in message and 'ATTEMPT' not in message


@pytest.mark.parametrize('purpose',['csr','compliance','production'])
def test_native_unknown_outcome_has_one_translated_review_and_no_child_context(display,purpose):
    def unknown(*args):
        raise NativeOnboardingError('native_onboarding_outcome_unknown',commit_uncertain=True)
    with pytest.raises(Review) as failed:
        if purpose=='csr':client._run_csr_operation(purpose,unknown)
        else:client._run_csid_operation(purpose,unknown)
    assert failed.value.__context__ is None
    assert 'تعذر تأكيد' in str(failed.value) and ONBOARDING_REVIEW not in str(failed.value)
    display.frappe.throw.assert_called_once()
    display.frappe.msgprint.assert_not_called()
