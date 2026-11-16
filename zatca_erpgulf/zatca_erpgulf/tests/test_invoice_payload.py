"""One-read request observations with frozen adapters and entirely mocked HTTP.

No receipt authenticity, atomic file write, SDK validity or installed ORM claim.
The oracle is increment227, separate from the original financial baseline.
"""
import ast
import base64
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from zatca_erpgulf.zatca_erpgulf import sign_invoice, pos_sign, sign_invoice_first
from zatca_erpgulf.zatca_erpgulf.invoice_payload import read_invoice_payload
from zatca_erpgulf.zatca_erpgulf.tests.test_submission_context import boundary, select_owner
from zatca_erpgulf.zatca_erpgulf.tests.test_generation_routes import generation_boundary, ADAPTERS as GENERATED
from zatca_erpgulf.zatca_erpgulf.tests.test_legacy_submission_context import legacy_boundary, ADAPTERS as PRESIGNED
from zatca_erpgulf.zatca_erpgulf.tests.test_compliance_api_outcomes import (
    boundary as compliance_boundary, set_http_response, success_response, already_completed_response,
)

REFERENCE=Path(__file__).with_name('fixtures')/'invoice_payload_f524d06.py'
REFERENCE_SHA='45aa2515cbdeda2a99f17e27374f21a801c38d54e0a002c2f0d9c6ca9dd3b175'
PRIMARY=[(mod,op+'_api','sales' if mod is sign_invoice else 'pos','primary')
         for mod in (sign_invoice,pos_sign) for op in ('reporting','clearance')]
ADAPTERS=PRIMARY+[(r[0],r[1],r[2],'generated') for r in GENERATED]+[(r[0],r[1],r[3],'presigned') for r in PRESIGNED]
XML_A='''<?xml version="1.0" encoding="UTF-8"?>
<Invoice><Note>اختبار</Note><AdditionalDocumentReference><ID>QR</ID>
<EmbeddedDocumentBinaryObject> QR-A </EmbeddedDocumentBinaryObject>
</AdditionalDocumentReference></Invoice>'''
XML_B=XML_A.replace('QR-A','QR-B')


def encoded(text):
    return base64.b64encode(text.encode('utf-8')).decode('utf-8')


def previous(module,name):
    raw=REFERENCE.read_bytes();assert hashlib.sha256(raw).hexdigest()==REFERENCE_SHA
    sources=ast.literal_eval(ast.parse(raw).body[1].value)
    path='zatca_erpgulf/zatca_erpgulf/'+module.__name__.rsplit('.',1)[-1]+'.py'
    # The frozen functions still require their former Base64 import.
    namespace=dict(vars(module), base64=base64)
    exec(compile(sources[path],str(REFERENCE),'exec'),namespace)
    return namespace[name]


def fresh(monkeypatch,tmp_path,adapter):
    b=boundary.__wrapped__(monkeypatch)
    if adapter[3]=='primary':
        b.path=tmp_path/'primary.xml';b.path.write_bytes(base64.b64decode(b.xml))
        monkeypatch.setattr(sign_invoice,'_extract_qr_payload',sign_invoice._CANONICAL_REPORTED_QR_READER)
    if adapter[3]=='generated':b=generation_boundary.__wrapped__(b,monkeypatch)
    if adapter[3]=='presigned':b=legacy_boundary.__wrapped__(b,monkeypatch,tmp_path)
    return b


def invoke(b,adapter,fn):
    invoice=getattr(b,adapter[2])
    return fn('test-uuid','test-hash',str(getattr(b,'path','unused.xml')),invoice.name,invoice)


def observable(b,invoice):
    return {
        'request':b.post.call_args_list,
        'fields':[(key,getattr(invoice,key,None)) for key in (
            'custom_uuid','custom_zatca_status','custom_zatca_full_response',
            'custom_ksa_einvoicing_xml','ksa_einv_qr')],
        'invoice_writes':invoice.db_set.call_args_list,
        'invoice_saves':invoice.save.call_args_list,
        'files':[(f.file_name,f.content,f.is_private,f.attached_to_doctype,f.attached_to_name,
                  f.save.call_args_list) for f in b.files],
        'owners':[(d.custom_pih,d.save.call_args_list,d.db_set.call_args_list)
                  for d in (b.company,b.device,b.linked)],
        'commit':b.frappe.db.commit.call_args_list,
        'messages':b.frappe.msgprint.call_args_list,
    }


def outcome(call):
    try:return ('return',call())
    except Exception as error:return ('error',type(error).__name__,str(error))


@pytest.mark.parametrize('adapter',ADAPTERS)
@pytest.mark.parametrize('owner',['company','device','linked'])
@pytest.mark.parametrize('environment',['Sandbox','Simulation','Production'])
@pytest.mark.parametrize('status',[200,202,409,400])
def test_complete_parent_api_parity_with_stable_reader(monkeypatch,tmp_path,adapter,owner,environment,status):
    results=[]
    for old in (True,False):
        with monkeypatch.context() as patch:
            b=fresh(patch,tmp_path,adapter);invoice=getattr(b,adapter[2])
            select_owner(b,invoice,owner);b.company.custom_select=environment;b.response.status_code=status
            fn=previous(adapter[0],adapter[1]) if old else getattr(adapter[0],adapter[1])
            result=outcome(lambda:invoke(b,adapter,fn))
            results.append((result,observable(b,invoice)))
    assert results[0]==results[1]
    requires_unit = (
        adapter[3]=='generated' and next(r[3] for r in GENERATED if r[:2]==adapter[:2])
        or adapter[3]=='presigned' and next(r[4] for r in PRESIGNED if r[:2]==adapter[:2])
    )
    # Existing POS Clearance rejects409; this bundle does not redefine that policy.
    rejects_duplicate = status==409 and adapter[:2]==(pos_sign,'clearance_api')
    expected_error = status==400 or owner=='company' and requires_unit or rejects_duplicate
    assert results[1][0][0]==('error' if expected_error else 'return')


@pytest.mark.parametrize('adapter',[r for r in ADAPTERS if r[1].startswith('reporting') and r[3]!='presigned'])
@pytest.mark.parametrize('method',['Immediate','Batches','Background'])
def test_deferred_side_effect_order_is_preserved(monkeypatch,tmp_path,adapter,method):
    observed=[]
    for old in (True,False):
        with monkeypatch.context() as patch:
            b=fresh(patch,tmp_path,adapter);invoice=getattr(b,adapter[2]);select_owner(b,invoice,'linked')
            b.company.custom_send_invoice_to_zatca=method
            fn=previous(adapter[0],adapter[1]) if old else getattr(adapter[0],adapter[1])
            observed.append((outcome(lambda:invoke(b,adapter,fn)),observable(b,invoice)))
    assert observed[0]==observed[1]


@pytest.mark.parametrize('adapter',ADAPTERS)
@pytest.mark.parametrize('failure',[ValueError,TypeError,OSError])
def test_first_read_failure_retains_boundary_and_no_request(monkeypatch,tmp_path,adapter,failure):
    observed=[]
    for old in (True,False):
        with monkeypatch.context() as patch:
            b=fresh(patch,tmp_path,adapter);invoice=getattr(b,adapter[2]);select_owner(b,invoice,'linked')
            reader=Mock(side_effect=failure('local-reader-failure'))
            patch.setattr(adapter[0],'xml_base64_decode',reader)
            fn=previous(adapter[0],adapter[1]) if old else getattr(adapter[0],adapter[1])
            result=outcome(lambda:invoke(b,adapter,fn))
            reader.assert_called_once();b.post.assert_not_called();assert not b.files
            observed.append((result,observable(b,invoice)))
    assert observed[0]==observed[1]


@pytest.mark.parametrize('adapter',ADAPTERS)
def test_request_captures_reader_once(monkeypatch,tmp_path,adapter):
    b=fresh(monkeypatch,tmp_path,adapter);select_owner(b,getattr(b,adapter[2]),'linked')
    text = Path(b.path).read_text() if adapter[3]=='presigned' else XML_A
    reader=Mock(side_effect=[encoded(text),encoded(XML_B)])
    monkeypatch.setattr(adapter[0],'xml_base64_decode',reader)
    invoke(b,adapter,getattr(adapter[0],adapter[1]))
    reader.assert_called_once();assert b.post.call_args.kwargs['json']['invoice']==encoded(text)
    if adapter[1].startswith('reporting') and adapter[3]!='presigned':
        assert b.files[0].content==XML_A


@pytest.mark.parametrize('adapter',[r for r in ADAPTERS if r[3]=='generated' or r[:2]==(pos_sign,'reporting_api')])
def test_frozen_double_read_can_disagree_with_attachment(monkeypatch,tmp_path,adapter):
    b=fresh(monkeypatch,tmp_path,adapter);select_owner(b,getattr(b,adapter[2]),'linked')
    reader=Mock(side_effect=[encoded(XML_A),encoded(XML_B)])
    monkeypatch.setattr(adapter[0],'xml_base64_decode',reader)
    invoke(b,adapter,previous(adapter[0],adapter[1]))
    assert reader.call_count==2
    sent=base64.b64decode(b.post.call_args.kwargs['json']['invoice']).decode()
    assert {sent,b.files[0].content}=={XML_A,XML_B}


@pytest.mark.parametrize('status',[200,202,409])
@pytest.mark.parametrize('change',['replace','delete'])
def test_sales_reporting_archives_and_extracts_qr_from_sent_observation(boundary,monkeypatch,tmp_path,status,change):
    b=boundary;source=tmp_path/'signed.xml';source.write_text(XML_A)
    reader=Mock(side_effect=lambda path:encoded(Path(path).read_text().lstrip()))
    monkeypatch.setattr(sign_invoice,'xml_base64_decode',reader)
    monkeypatch.setattr(sign_invoice,'_extract_qr_payload',sign_invoice._CANONICAL_REPORTED_QR_READER)
    b.response.status_code=status
    def post(**kwargs):
        source.write_text(XML_B) if change=='replace' else source.unlink()
        return b.response
    b.post.side_effect=post
    sign_invoice.reporting_api('test-uuid','test-hash',str(source),b.sales.name,b.sales)
    reader.assert_called_once()
    assert b.files[0].content==XML_A
    assert base64.b64decode(b.post.call_args.kwargs['json']['invoice']).decode()==XML_A
    assert sign_invoice.attach_qr_image.call_args.args[0]=='QR-A'


@pytest.mark.parametrize('status',[200,202,409])
def test_frozen_sales_uses_changed_post_response_file(boundary,monkeypatch,tmp_path,status):
    b=boundary;source=tmp_path/'signed.xml';source.write_text(XML_A)
    monkeypatch.setattr(sign_invoice,'xml_base64_decode',lambda path:encoded(Path(path).read_text()))
    old=previous(sign_invoice,'reporting_api');b.response.status_code=status
    b.post.side_effect=lambda **kwargs:(source.write_text(XML_B),b.response)[1]
    old('test-uuid','test-hash',str(source),b.sales.name,b.sales)
    assert b.files[0].content==XML_B
    assert sign_invoice.attach_qr_image.call_args.args[0]=='QR-B'
    assert b.post.call_args.kwargs['json']['invoice']==encoded(XML_A)


def test_custom_helpers_keep_original_positional_arguments(boundary,monkeypatch):
    attach=Mock();qr=Mock(return_value='CUSTOM-QR')
    monkeypatch.setattr(sign_invoice,'_attach_reported_xml',attach)
    monkeypatch.setattr(sign_invoice,'_extract_qr_payload',qr)
    sign_invoice.reporting_api('test-uuid','test-hash','unused.xml',boundary.sales.name,boundary.sales)
    attach.assert_called_once_with('unused.xml',boundary.sales);qr.assert_called_once_with('unused.xml')
    assert sign_invoice.attach_qr_image.call_args.args[0]=='CUSTOM-QR'


@pytest.mark.parametrize('environment',['Sandbox','Simulation','Production'])
@pytest.mark.parametrize('status',[200,202,406,400,401])
def test_compliance_keeps_json_text_credentials_and_result(compliance_boundary,monkeypatch,environment,status):
    company,frappe,request=compliance_boundary;company.custom_select=environment
    body=already_completed_response() if status==406 else success_response()
    set_http_response(request,status,body)
    observed=[]
    for old in (True,False):
        request.reset_mock();frappe.msgprint.reset_mock()
        reader=Mock(return_value='MOCK_XML');monkeypatch.setattr(sign_invoice_first,'xml_base64_decode',reader)
        fn=previous(sign_invoice_first,'compliance_api_call') if old else sign_invoice_first.compliance_api_call
        result=outcome(lambda:fn('mock-uuid','mock-hash','unused.xml','TC',None))
        reader.assert_called_once_with('unused.xml')
        observed.append((result,request.call_args_list,frappe.msgprint.call_args_list))
    assert observed[0]==observed[1]
    assert request.call_args.kwargs['data']==json.dumps({'invoiceHash':'mock-hash','uuid':'mock-uuid','invoice':'MOCK_XML'})


@pytest.mark.parametrize('value',[encoded(XML_A),'MOCK_XML',None,object()])
def test_pure_capture_is_lazy_preserves_native_values_and_hides_repr(value):
    uuid=object();invoice_hash=object();reader=Mock(return_value=value)
    captured=read_invoice_payload(uuid,invoice_hash,'path',read_xml=reader)
    reader.assert_called_once_with('path')
    expected={'invoiceHash':invoice_hash,'uuid':uuid,'invoice':value}
    assert captured.as_payload()==expected and list(captured.as_payload())==list(expected)
    replacement=captured.as_payload();replacement['invoice']='MUTATED'
    assert captured.as_payload()['invoice'] is value
    assert not hasattr(captured,'path') and not hasattr(captured,'read_xml')
    assert 'Invoice>' not in repr(captured) and 'MOCK_XML' not in repr(captured)
    with pytest.raises(FrozenInstanceError):captured.uuid='new'


@pytest.mark.parametrize('value',[encoded(XML_A),base64.b64encode(b'\xff').decode(),'bad',None,b'YWJj!!'])
def test_lazy_decode_retains_legacy_base64_and_utf8_behavior(value):
    captured=read_invoice_payload('u','h','p',read_xml=lambda path:value)
    assert outcome(captured.xml_text)==outcome(lambda:base64.b64decode(value).decode('utf-8'))


@pytest.mark.parametrize('xml',[XML_A,'  '+XML_A,XML_A.replace('QR-A',''),'<Invoice/>'])
def test_private_helpers_keep_standalone_reader_and_parser_contract(boundary,monkeypatch,tmp_path,xml):
    source=tmp_path/'sample.xml';source.write_text(xml.lstrip())
    reader=Mock(side_effect=lambda path:encoded(Path(path).read_text().lstrip()))
    monkeypatch.setattr(sign_invoice,'xml_base64_decode',reader)
    assert outcome(lambda:previous(sign_invoice,'_extract_qr_payload')(str(source)))==outcome(
        lambda:sign_invoice._CANONICAL_REPORTED_QR_READER(str(source)))
    previous(sign_invoice,'_attach_reported_xml')(str(source),boundary.sales)
    sign_invoice._CANONICAL_REPORTED_XML_ATTACHMENT(str(source),boundary.sales)
    assert boundary.files[0].content==boundary.files[1].content==xml.lstrip()
