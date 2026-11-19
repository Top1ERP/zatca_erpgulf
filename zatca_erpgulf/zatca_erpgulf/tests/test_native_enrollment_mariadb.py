"""Fenced initial-CSID pipeline: private InnoDB, fake framework and HTTP only."""

import base64
import inspect
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography import x509
import pytest

from zatca_erpgulf.zatca_erpgulf import native_enrollment as enrollment, native_onboarding as onboarding
from zatca_erpgulf.zatca_erpgulf import sign_invoice_first as client, native_owner_guard, native_owner_registry
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.native_transport import NativeResponse, NativeTransportError
from zatca_erpgulf.zatca_erpgulf.tests.test_native_onboarding_mariadb import (
    target, boundary, materials, connections, isolated_server, tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_onboarding_response import issued_body


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1', reason='Owned private SQL opt-in only')


@pytest.fixture
def flow(target, monkeypatch):
    t = target;prepared = t.prepare()
    csr = x509.load_pem_x509_csr(base64.b64decode(prepared.csr_data))
    with t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tab'+t.selected.doctype+'` SET custom_otp=%s WHERE name=%s', ('123456', t.selected.name))
    t.connection.commit()
    calls = []
    def invoke(value, *, runtime):
        # A second physical connection sees the durable reservation before HTTP.
        observer = t.connections()
        with observer.cursor() as cursor:
            cursor.execute('SELECT state FROM `tabZATCA Onboarding Attempt` WHERE name=%s', (value.record_id,))
            assert cursor.fetchone() == ('RESERVED',)
        assert runtime is t.runtime
        calls.append(value)
        body = issued_body(csr, request_id=1001 if value.route.endpoint == 'compliance' else 2002)
        return NativeResponse(200, 'SYNTHETIC-REQUEST', body)
    sender = Mock(side_effect=invoke)
    monkeypatch.setattr(enrollment, 'invoke_onboarding_request', sender)
    def request(endpoint='compliance', **kwargs):
        return enrollment.request_initial_csid('TC', t.identity, endpoint, runtime=t.runtime, **kwargs)
    def state():
        return t.database.sql('SELECT active,active_owner_key,last_icv,onboarding_state,onboarding_attempt,'
            'onboarding_compliance_attempt,onboarding_final_attempt FROM `tabZATCA Issuing Chain` WHERE name=%s',
            (prepared.record_id,), as_dict=True)[0]
    return SimpleNamespace(t=t, prepared=prepared, csr=csr, sender=sender, calls=calls, request=request, state=state)


@pytest.mark.parametrize('target',['company','device'],indirect=True)
def test_initial_compliance_then_final_are_fenced_bound_and_inactive(flow):
    f=flow;t=f.t
    compliance=f.request();assert compliance.state=='CCSID_READY' and not compliance.active
    saved=t.runtime.get_doc(t.selected.doctype,t.selected.name)
    assert saved.custom_compliance_request_id_=='1001' and saved.custom_basic_auth_from_csid
    final=f.request('production/csids');state=f.state()
    assert final.state=='FINAL_READY' and not final.active and state['active']==0
    assert state['active_owner_key'] is None and state['last_icv']=='0'
    assert state['onboarding_compliance_attempt']==compliance.record_id and state['onboarding_final_attempt']==final.record_id
    assert f.calls[0].route.required_credential=='otp' and f.calls[0].otp=='123456'
    assert f.calls[1].route.required_credential=='compliance' and f.calls[1].authorization=='Basic '+saved.custom_basic_auth_from_csid
    assert json.loads(f.calls[1].request_bytes)=={'compliance_request_id':'1001'}
    assert len(f.calls)==2 and t.database.commits==7
    again=f.request('production/csids');assert again.reused and again.record_id==final.record_id
    assert len(f.calls)==2 and t.database.commits==7
    rows=t.database.sql('SELECT request_header,request_ciphertext,receipt_header,receipt_ciphertext FROM '
        '`tabZATCA Onboarding Attempt` WHERE chain=%s',(f.prepared.record_id,),as_dict=True)
    assert len(rows)==2 and all('PRIVATE-SYNTHETIC-SECRET' not in str(row) and '123456' not in str(row) for row in rows)
    t.b.request.assert_not_called()


def test_a_completed_compliance_button_recovers_without_reissuing_a_certificate(flow):
    f=flow;first=f.request();second=f.request()
    assert second.reused and first.record_id==second.record_id and f.sender.call_count==1
    assert f.t.database.commits==4


def test_existing_csid_buttons_use_the_owned_service_and_one_redacted_popup(flow):
    f=flow;t=f.t
    for method,purpose in ((client.create_csid,'compliance'),(client.production_csid,'production')):
        result=json.loads(inspect.unwrap(method)(t.identity,'TC'))
        assert result['status']=='SUCCESS' and result['purpose']==purpose
        assert 'secret' not in str(result) and '1001' not in str(result)
    assert f.sender.call_count==2 and t.runtime.msgprint.call_count==2
    assert all('remains inactive' in str(call) and 'PRIVATE' not in str(call) for call in t.runtime.msgprint.call_args_list)
    t.selected.save.assert_not_called()


@pytest.mark.parametrize('target',['company','device'],indirect=True)
def test_copied_initial_key_is_registered_and_cannot_enter_a_legacy_credential_writer(flow):
    f=flow;t=f.t;saved=t.runtime.get_doc(t.selected.doctype,t.selected.name)
    copied=Document(doctype='Company',name='UNMARKED-COPY',custom_private_key=saved.custom_private_key)
    t.runtime.conf[onboarding.MODE]=0
    assert native_owner_registry.has_registered_native_material(t.runtime,copied)
    with pytest.raises(onboarding.NativeOnboardingError,match='service_required'):
        native_owner_guard.reject_legacy_owner_credentials(t.runtime,copied)
    f.sender.assert_not_called()


@pytest.mark.parametrize('fault',['no_otp','role','write','flag','environment','final_before_compliance'])
def test_initial_request_denial_does_not_reserve_or_invoke(flow,fault):
    f=flow;t=f.t;kwargs={};endpoint='compliance'
    if fault=='no_otp':
        with t.connection.cursor() as cursor:
            cursor.execute('UPDATE `tab'+t.selected.doctype+'` SET custom_otp=NULL WHERE name=%s',(t.selected.name,))
        t.connection.commit()
    elif fault=='role':t.runtime.get_roles=lambda actor:[]
    elif fault=='write':t.runtime.has_permission=lambda dt,operation,**kw:operation!='write'
    elif fault=='flag':t.runtime.conf[onboarding.MODE]=0
    elif fault=='environment':kwargs={'portal_type':'Simulation'}
    else:endpoint='production/csids'
    with pytest.raises(onboarding.NativeOnboardingError):f.request(endpoint,**kwargs)
    f.sender.assert_not_called()
    assert t.database.commits==1 and f.state()['onboarding_state']=='CSR_READY'


def test_transport_interruption_is_not_a_rejection_or_permission_to_retry(flow):
    f=flow;f.sender.side_effect=NativeTransportError('native_transport_outcome_unknown',invoked=True)
    with pytest.raises(onboarding.NativeOnboardingError):f.request()
    with pytest.raises(onboarding.NativeOnboardingError,match='native_onboarding_outcome_unknown'):f.request()
    assert f.sender.call_count==1 and f.state()['onboarding_state']=='CCSID_PENDING'
    assert f.t.database.commits==2


def test_a_second_button_call_while_http_is_in_progress_cannot_reserve_another_attempt(flow):
    f=flow;send=f.sender.side_effect
    def competing(value,**kwargs):
        with pytest.raises(onboarding.NativeOnboardingError,match='outcome_unknown'):f.request()
        return send(value,**kwargs)
    f.sender.side_effect=competing
    assert f.request().state=='CCSID_READY'
    assert f.sender.call_count==1
    assert f.t.database.sql('SELECT COUNT(*) AS n FROM `tabZATCA Onboarding Attempt` WHERE chain=%s',
        (f.prepared.record_id,),as_dict=True)[0]['n']==1


@pytest.mark.parametrize('stage',['reservation','receipt','admission'])
def test_lost_commit_acknowledgments_never_cause_a_second_http_call(flow,monkeypatch,stage):
    f=flow;t=f.t;commit=t.database.commit
    at={'reservation':2,'receipt':3,'admission':4}[stage]
    def unknown():
        commit()
        if t.database.commits==at:raise RuntimeError('PRIVATE-LOST-ACK')
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'commit',unknown)
        with pytest.raises(onboarding.NativeOnboardingError) as failed:f.request()
    assert failed.value.commit_uncertain and failed.value.__context__ is None
    if stage=='reservation':
        with pytest.raises(onboarding.NativeOnboardingError,match='outcome_unknown'):f.request()
        f.sender.assert_not_called()
    else:
        recovered=f.request();assert recovered.reused and recovered.state=='CCSID_READY'
        assert f.sender.call_count==1


def test_owner_projection_failure_preserves_the_committed_response_for_recovery(flow,monkeypatch):
    f=flow;t=f.t;sql=t.database.sql
    def partial(statement,values=(),**kwargs):
        rows=sql(statement,values,**kwargs)
        if statement.startswith('UPDATE `tab'+t.selected.doctype+'` SET `custom_certificate`'):
            raise RuntimeError('PRIVATE-PROJECTION-FAILURE')
        return rows
    with monkeypatch.context() as patch:
        patch.setattr(t.database,'sql',partial)
        with pytest.raises(onboarding.NativeOnboardingError):f.request()
    assert f.state()['onboarding_state']=='CCSID_RESPONSE' and t.database.commits==3
    assert t.runtime.get_doc(t.selected.doctype,t.selected.name).custom_basic_auth_from_csid is None
    result=f.request();assert result.reused and result.state=='CCSID_READY' and f.sender.call_count==1


@pytest.mark.parametrize('fault',['bad_key','bad_vat','bad_serial','malformed','unauthorized','missing_steps'])
def test_nonissued_or_unbound_responses_are_retained_but_never_projected(flow,fault):
    f=flow
    if fault=='bad_key':
        from cryptography.hazmat.primitives.asymmetric import ec
        body=issued_body(f.csr,key=ec.generate_private_key(ec.SECP256K1()))
    elif fault=='bad_vat':body=issued_body(f.csr,taxpayer='OTHER-VAT')
    elif fault=='bad_serial':body=issued_body(f.csr,serial='OTHER-UNIT')
    elif fault=='malformed':body=b'{"secret":"PRIVATE-INVALID"}'
    elif fault=='unauthorized':body=b'{"message":"Unauthorized"}'
    else:body=b'{"code":"Missing-ComplianceSteps"}'
    status=401 if fault=='unauthorized' else 400 if fault=='missing_steps' else 200
    f.sender.side_effect=lambda value,**kw:NativeResponse(status,'SYNTHETIC-REQUEST',body)
    with pytest.raises(onboarding.NativeOnboardingError):f.request()
    with pytest.raises(onboarding.NativeOnboardingError):f.request()
    assert f.sender.call_count==1 and f.state()['onboarding_state']=='CCSID_RESPONSE'
    assert f.t.runtime.get_doc(f.t.selected.doctype,f.t.selected.name).custom_basic_auth_from_csid is None
    assert f.t.database.commits==3


def test_route_change_during_http_retains_the_response_and_requires_the_original_route_for_admission(flow):
    f=flow;t=f.t;send=f.sender.side_effect;original=t.b.company.custom_production_url
    def changed(value,**kwargs):
        result=send(value,**kwargs)
        t.b.company.custom_production_url='https://other.invalid/core'
        return result
    f.sender.side_effect=changed
    with pytest.raises(onboarding.NativeOnboardingError,match='intent_review'):f.request()
    assert f.state()['onboarding_state']=='CCSID_RESPONSE' and t.database.commits==3
    t.b.company.custom_production_url=original
    assert f.request().reused and f.sender.call_count==1


def test_tampered_retained_response_cannot_be_admitted_or_replaced_by_another_request(flow):
    f=flow;f.sender.side_effect=lambda value,**kw:NativeResponse(200,'SYNTHETIC',b'{"secret":"PRIVATE-INVALID"}')
    with pytest.raises(onboarding.NativeOnboardingError):f.request()
    attempt=f.state()['onboarding_attempt']
    with f.t.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabZATCA Onboarding Attempt` SET receipt_ciphertext=%s WHERE name=%s',('TAMPERED',attempt))
    f.t.connection.commit()
    with pytest.raises(onboarding.NativeOnboardingError):f.request()
    assert f.sender.call_count==1 and f.state()['onboarding_state']=='CCSID_RESPONSE'


@pytest.mark.parametrize('endpoint',['compliance','production/csids'])
def test_known400_is_retained_and_only_a_later_explicit_call_may_reserve_again(flow,endpoint):
    f=flow;t=f.t
    if endpoint=='production/csids':f.request()
    send=f.sender.side_effect
    body=(b'{"errors":[{"code":"Invalid-OTP","message":"Invalid OTP"}]}' if endpoint=='compliance' else
        b'{"code":"Missing-ComplianceSteps","message":"Not completed"}')
    before=f.sender.call_count
    f.sender.side_effect=lambda value,**kw:NativeResponse(400,'SYNTHETIC-REJECTION',body)
    with pytest.raises(onboarding.NativeOnboardingError):f.request(endpoint)
    assert f.sender.call_count==before+1  # The receiving invocation never retries.
    rejected=f.state()['onboarding_attempt']
    f.sender.side_effect=send
    completed=f.request(endpoint)
    assert completed.state==('CCSID_READY' if endpoint=='compliance' else 'FINAL_READY')
    assert f.sender.call_count==before+2 and completed.record_id!=rejected
    row=t.database.sql('SELECT previous_attempt FROM `tabZATCA Onboarding Attempt` WHERE name=%s',
        (completed.record_id,),as_dict=True)[0]
    assert row['previous_attempt']==rejected
    assert t.database.sql('SELECT state FROM `tabZATCA Onboarding Attempt` WHERE name=%s',
        (rejected,),as_dict=True)[0]['state']=='RESPONSE_RETAINED'


def test_a_metadata_callback_cannot_project_a_certificate_over_changed_owner_material(flow,monkeypatch):
    f=flow;t=f.t;get_meta=t.runtime.get_meta
    def changed(doctype):
        with t.connection.cursor() as cursor:
            cursor.execute('UPDATE `tab'+t.selected.doctype+'` SET custom_csr_config=CONCAT(custom_csr_config,%s) WHERE name=%s',
                ('\n',t.selected.name))
        return get_meta(doctype)
    with monkeypatch.context() as patch:
        patch.setattr(t.runtime,'get_meta',changed)
        with pytest.raises(onboarding.NativeOnboardingError,match='source_changed'):f.request()
    assert f.state()['onboarding_state']=='CCSID_RESPONSE'
    assert f.request().reused and f.sender.call_count==1
