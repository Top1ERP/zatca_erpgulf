"""Explicit correction XML time and real metadata adapters; no ERP/site/HTTP."""

import base64
from datetime import datetime,timezone
import hashlib
import json
from unittest.mock import Mock
from uuid import uuid4
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import correction_clock as clock,createxml,posxml
from zatca_erpgulf.zatca_erpgulf.issue_timestamp import IssueTimestamp
from zatca_erpgulf.zatca_erpgulf.native_preparation import native_preparation,metadata_issue_timestamp,NativePreparationError
from zatca_erpgulf.zatca_erpgulf.invoice_xml_core import INITIAL_PREVIOUS_HASH
from zatca_erpgulf.zatca_erpgulf.tests.test_nonproduction_isolation import isolated
from zatca_erpgulf.zatca_erpgulf.tests.test_native_response import evidence
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import node


def original(*,standard=False,issue_time='09:05:42Z'):
    header,_body,xml=evidence(indicator='0100000' if standard else '0200000')
    root=etree.fromstring(xml)
    node(root,'cbc','IssueDate','2026-11-10');node(root,'cbc','IssueTime',issue_time)
    body=json.dumps(dict(invoiceHash=header['invoice_hash'],uuid=header['invoice_uuid'],
        invoice=base64.b64encode(etree.tostring(root)).decode())).encode()
    header['artifact_sha256']=hashlib.sha256(body).hexdigest()
    return header,body


@pytest.mark.parametrize('standard',[False,True])
def test_only_xml_correction_date_policy_changes_and_clock_is_whole_second(standard):
    header,body=original(standard=standard)
    selected=clock.corrected_issue_timestamp(header,body,generation_instant=datetime(2026,11,21,10,6,43,999999,tzinfo=timezone.utc))
    assert selected.qr_value==('2026-11-21' if standard else '2026-11-10')+'T10:06:43Z'
    assert selected.utc_instant.microsecond==0


@pytest.mark.parametrize('instant',[None,datetime(2026,11,21,10),datetime(2026,11,10,9,5,42,tzinfo=timezone.utc)])
def test_missing_naive_or_unchanged_clock_is_not_invented(instant):
    header,body=original()
    with pytest.raises(clock.CorrectionClockError):clock.corrected_issue_timestamp(header,body,generation_instant=instant)


def test_original_without_offset_or_with_damaged_custody_is_held():
    header,body=original(issue_time='09:05:42')
    with pytest.raises(clock.CorrectionClockError):
        clock.corrected_issue_timestamp(header,body,generation_instant=datetime(2026,11,21,10,tzinfo=timezone.utc))
    header,body=original();header['artifact_sha256']='a'*64
    with pytest.raises(Exception):clock.corrected_issue_timestamp(header,body,generation_instant=datetime(2026,11,21,10,tzinfo=timezone.utc))


@pytest.mark.parametrize('module,doctype',[(createxml,'Sales Invoice'),(posxml,'POS Invoice')])
@pytest.mark.parametrize('replacement',[False,True])
def test_real_metadata_adapter_uses_ticket_time_without_persisting_posting_fields(isolated,module,doctype,replacement):
    document,company,_customer,runtime,_files=isolated;document.doctype=doctype
    before=(document.posting_date,document.posting_time,document.custom_uuid)
    selected=IssueTimestamp(datetime(2026,11,21,10,6,43,tzinfo=timezone.utc)) if replacement else None
    chain=dict(record_id=str(uuid4()),environment='Production',last_icv='1',previous_hash=INITIAL_PREVIOUS_HASH,
        owner_doctype='Company',owner_name=company.name,certificate_sha256='a'*64,public_key_sha256='b'*64,seller_tax_id='TEST')
    with native_preparation(runtime,source_identity=(doctype,document.name),company_name=company.name,
        chain=chain,invoice_uuid=str(uuid4()),owner_check=lambda:True,replacement_timestamp=selected):
        root,_uuid,returned=module.salesinvoice_data(ET.Element('Invoice'),document.name)
    assert returned is document
    assert root.find('cbc:IssueDate').text==('2026-11-21' if replacement else '2026-10-09')
    assert root.find('cbc:IssueTime').text==('10:06:43Z' if replacement else '09:05:42Z')
    assert (document.posting_date,document.posting_time,document.custom_uuid)==before
    document.db_set.assert_not_called();document.save.assert_not_called();runtime.db.commit.assert_not_called()


@pytest.mark.parametrize('purpose',['debug','compliance'])
def test_correction_ticket_cannot_override_a_nonproduction_clock(isolated,purpose):
    document,company,_customer,runtime,_files=isolated
    chain=dict(record_id=str(uuid4()),environment='Production',last_icv='1',previous_hash=INITIAL_PREVIOUS_HASH,
        owner_doctype='Company',owner_name=company.name,certificate_sha256='a'*64,public_key_sha256='b'*64,seller_tax_id='TEST')
    fallback=Mock()
    with native_preparation(runtime,source_identity=(document.doctype,document.name),company_name=company.name,
        chain=chain,invoice_uuid=str(uuid4()),owner_check=lambda:True,
        replacement_timestamp=IssueTimestamp(datetime(2026,11,21,10,tzinfo=timezone.utc))):
        with pytest.raises(NativePreparationError):metadata_issue_timestamp(document,runtime=runtime,purpose=purpose,format_default=fallback)
    fallback.assert_not_called()
