"""Correction history/clock adoption on private SQL; all authority HTTP mocked."""

import json
import os
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import native_dispatch as dispatch
from zatca_erpgulf.zatca_erpgulf import native_preparation
from zatca_erpgulf.zatca_erpgulf.native_transport import NativeResponse
from zatca_erpgulf.zatca_erpgulf.qr_xml_contract import _clock
from zatca_erpgulf.zatca_erpgulf.tests.test_exact_retry_mariadb import unknown,expire,register,execute
from zatca_erpgulf.zatca_erpgulf.tests.test_native_dispatch import signed_build
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_intent_mariadb import (
    handoff,case,boundary,materials,isolated_server,connections,tables,
)


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


@pytest.fixture(autouse=True)
def metadata_runtime(handoff,monkeypatch):
    # The broader route fixture replaces financial metadata with its synthetic
    # builder. This suite also executes the real metadata adapter, so bind its
    # framework and the synthetic builder's final fence to the same SQL runtime.
    from zatca_erpgulf.zatca_erpgulf import createxml,posxml
    for module in (createxml,posxml):
        monkeypatch.setattr(module,'frappe',handoff.runtime)
        monkeypatch.setattr(module,'_',lambda text:text)
    monkeypatch.setattr(handoff.b,'frappe',handoff.runtime)


def rejection_body():
    return json.dumps(dict(validationResults=dict(status='ERROR',infoMessages=[],warningMessages=[],
        errorMessages=[dict(type='ERROR',status='ERROR',code='SYNTHETIC',message='Rejected')]),reportingStatus='NOT_REPORTED')).encode()


def rejected(c):
    normal=c.adapter.send.side_effect
    def fail(prepared,**kwargs):
        response=normal(prepared,**kwargs)
        if prepared.url.endswith('invoices/reporting/single'):
            response.status_code=400;response.raw.read1=Mock(side_effect=[rejection_body(),b''])
        return response
    c.adapter.send.side_effect=fail
    result=c.run();assert result['outcome']=='VALIDATION_REJECTED'
    return dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)


def replace(c,view,*,build=None):
    def canonical_time(source):
        stamp=native_preparation.ACTIVE_PREPARATION.get().replacement_timestamp
        assert stamp is not None
        # Exercise the actual Sales/POS metadata adapter under the owned
        # lifetime before the synthetic financial/signing fixture composition.
        from zatca_erpgulf.zatca_erpgulf import createxml,posxml
        import xml.etree.ElementTree as ET
        adapter=createxml if source.doctype=='Sales Invoice' else posxml
        metadata,_uuid,loaded=adapter.salesinvoice_data(ET.Element('Invoice'),source.name)
        assert loaded.name==source.name and metadata.find('cbc:IssueDate').text==stamp.xml_date
        assert metadata.find('cbc:IssueTime').text==stamp.xml_time
        return signed_build(c.b,source,validation_type='Simplified Invoice' if c.customer.custom_b2c else 'Standard Invoice',
            endpoint='invoices/reporting/single' if c.customer.custom_b2c else 'invoices/clearance/single')
    return dispatch.prepare_corrected_rejection(c.source.doctype,c.source.name,runtime=c.runtime,translate=str,
        build=build or canonical_time,rejected_issuance_id=view.issuance_id,rejected_attempt_id=view.attempt_id,use_current_issue_time=True)


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),(0,'linked','Live',False)],indirect=True)
def test_explicit_server_clock_creates_only_one_linked_prepared_version_without_changing_posting_fields(handoff):
    c=handoff;view=rejected(c);before=c.runtime.get_doc(c.source.doctype,c.source.name).as_dict()
    calls=c.adapter.send.call_count
    result=replace(c,view);saved=c.database.sql('SELECT * FROM `tabZATCA Issuance` WHERE name=%s',(result.record_id,),as_dict=True)[0]
    assert result.state=='PREPARED' and saved['source_version']==2 and saved['replaces_issuance']==view.issuance_id
    assert saved['invoice_uuid']!=view.invoice_uuid and saved['icv']=='2' and saved['previous_hash']==view.invoice_hash
    assert saved['origin_ciphertext'] is None  # Preparation is not automatic send authorization.
    current=dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime,require_current_source=True)
    assert not current.accepted and current.attempt_id is None
    old_date,old_time=_clock(view.original_xml);new_date,new_time=_clock(current.original_xml)
    assert new_time!=old_time
    if c.customer.custom_b2c:assert new_date==old_date
    after=c.runtime.get_doc(c.source.doctype,c.source.name).as_dict()
    outputs={'custom_uuid','custom_zatca_icv','custom_zatca_issuing_unit','custom_zatca_status','custom_zatca_full_response'}
    assert {key:value for key,value in after.items() if key not in outputs}=={key:value for key,value in before.items() if key not in outputs}
    assert c.adapter.send.call_count==calls and c.head()=='2'
    build=Mock()
    with pytest.raises(Exception):replace(c,view,build=build)
    build.assert_not_called();assert c.head()=='2'


def test_builder_cannot_ignore_the_selected_current_clock_or_commit_a_different_one(handoff):
    c=handoff;view=rejected(c);before=c.head();calls=c.adapter.send.call_count
    from datetime import datetime,timezone
    with pytest.raises(dispatch.NativeDispatchError,match='selected_clock'):
        replace(c,view,build=lambda source:signed_build(c.b,source,issue_instant=datetime(2026,11,10,10,0,tzinfo=timezone.utc)))
    assert c.head()==before and c.adapter.send.call_count==calls
    assert dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime).issuance_id==view.issuance_id


@pytest.mark.parametrize('fault',['phase','rollout','role','write'])
def test_current_clock_generation_requires_current_company_and_operator_authority(handoff,monkeypatch,fault):
    c=handoff;view=rejected(c)
    if fault=='phase':c.company.custom_phase_1_or_2='Phase-1'
    elif fault=='rollout':c.runtime.conf['zatca_native_dispatch']=0
    elif fault=='role':monkeypatch.setattr(c.runtime,'get_roles',lambda user:[])
    else:
        permission=c.runtime.has_permission
        monkeypatch.setattr(c.runtime,'has_permission',lambda dt,op,**kwargs:False if op=='write' else permission(dt,op,**kwargs))
    build=Mock()
    with pytest.raises(Exception):replace(c,view,build=build)
    build.assert_not_called();assert c.head()=='1'


def earlier_then_rejected(c,monkeypatch,prior_status):
    captured=[];invoke=dispatch.invoke_saved_request
    def observed(invocation,**kwargs):captured.append(invocation);return invoke(invocation,**kwargs)
    monkeypatch.setattr(dispatch,'invoke_saved_request',observed)
    view,first=unknown(c);expire(c,first)
    request=register(c,view,first);c.database.commit();assert execute(c,request['request_id'])['status']=='REVIEW'
    assert dispatch.retain_dispatch_observation(captured[1],NativeResponse(400,'CURRENT-REJECT',rejection_body()),runtime=c.runtime)
    assessment,current=dispatch.assess_retained_dispatch(captured[1],runtime=c.runtime)
    assert current and assessment.outcome=='VALIDATION_REJECTED'
    if prior_status is not None:
        if prior_status==200:
            body=json.dumps(dict(validationResults=dict(status='PASS',warningMessages=[],infoMessages=[],errorMessages=[]),reportingStatus='REPORTED')).encode()
        else:body=rejection_body()
        assert not dispatch.retain_dispatch_observation(captured[0],NativeResponse(prior_status,'OLDER-RESPONSE',body),runtime=c.runtime)
    return dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime),first


@pytest.mark.parametrize('prior_status',[None,200,500,503])
def test_a_current400_cannot_replace_an_original_with_an_earlier_unknown_accepted_or_technical_attempt(handoff,monkeypatch,prior_status):
    c=handoff;view,first=earlier_then_rejected(c,monkeypatch,prior_status);build=Mock()
    with pytest.raises(Exception):replace(c,view,build=build)
    build.assert_not_called();assert c.head()=='1' and c.adapter.send.call_count==2


@pytest.mark.parametrize('prior_status',[400,401,403])
def test_all_known_nonaccepting_receipts_are_verified_even_if_old_outcome_is_unassessed(handoff,monkeypatch,prior_status):
    c=handoff;view,first=earlier_then_rejected(c,monkeypatch,prior_status)
    assert replace(c,view).state=='PREPARED' and c.head()=='2' and c.adapter.send.call_count==2


def test_missing_earlier_row_is_not_inferred_to_be_a_single_first_attempt(handoff,monkeypatch):
    c=handoff;view,first=earlier_then_rejected(c,monkeypatch,400)
    c.database.sql('DELETE FROM `tabZATCA Dispatch Attempt` WHERE name=%s',(first['name'],));c.database.commit()
    build=Mock()
    with pytest.raises(Exception):replace(c,view,build=build)
    build.assert_not_called();assert c.head()=='1'
