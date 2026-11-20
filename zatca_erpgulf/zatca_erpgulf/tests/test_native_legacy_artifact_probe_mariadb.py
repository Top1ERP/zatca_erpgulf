"""Actual inactive review finds historical XML declarations in private SQL/files."""

import base64
import json
import os
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from lxml import etree
import pymysql
import pytest

from zatca_erpgulf.zatca_erpgulf import native_registration as registration, native_legacy_artifact_probe as probe
from zatca_erpgulf.zatca_erpgulf.tests.test_native_registration_mariadb import (
    legacy, boundary, materials, isolated_server, connections, tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_onboarding_mariadb import CONFIG
from zatca_erpgulf.zatca_erpgulf.tests.test_onboarding_response import issued_body


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Fixture-owned temporary SQL/files only')
NS = {'cbc':'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
    'cac':'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'ds':'http://www.w3.org/2000/09/xmldsig#'}


def archived_counter(t, doctype='Sales Invoice', *, certificate_text=None):
    identifier = str(uuid4())
    name, invoice_uuid = 'ARCHIVED-'+identifier, str(uuid4())
    unit, counter_name = 'company:RETIRED-'+identifier, '000-HISTORY-'+identifier
    root = etree.fromstring(t.xml)
    root.find('cbc:ID',NS).text = name
    root.find('cbc:UUID',NS).text = invoice_uuid
    root.xpath("./cac:AdditionalDocumentReference[cbc:ID='ICV']/cbc:UUID",namespaces=NS)[0].text = '10'
    if certificate_text is not None:
        root.find('.//ds:X509Certificate',NS).text = certificate_text
    content = etree.tostring(root)
    file_id, file_name = 'HISTORY-FILE-'+identifier, 'History-'+identifier+'.xml'
    path = t.path.parent/file_name;path.write_bytes(content)
    with t.connection.cursor() as cursor:
        cursor.execute('INSERT INTO `tab'+doctype+'` (name,company,docstatus,custom_uuid,custom_zatca_icv,'
            'custom_zatca_issuing_unit) VALUES (%s,%s,1,%s,%s,%s)', (name,t.source.company,invoice_uuid,'10',unit))
        cursor.execute('INSERT INTO `tabZATCA ICV Counter` (name,company,issuing_unit,environment,counter_key,'
            'active,last_issued_icv,last_invoice_doctype,last_invoice) VALUES (%s,%s,%s,%s,%s,0,%s,%s,%s)',
            (counter_name,t.source.company,unit,'Production',counter_name,'10',doctype,name))
        cursor.execute('INSERT INTO `tabFile` (name,attached_to_doctype,attached_to_name,is_private,file_name,file_url) '
            'VALUES (%s,%s,%s,1,%s,%s)', (file_id,doctype,name,file_name,'/private/files/'+file_name))
    t.connection.commit()
    # Header/certificate edits deliberately invalidate this synthetic signature.
    # Its declarations can HOLD review; they must never certify a history link.
    return dict(counter=counter_name,source=name,doctype=doctype,file=file_id,path=path,content=content)


@pytest.mark.parametrize('doctype', ['Sales Invoice','POS Invoice'])
def test_same_embedded_public_key_exposes_a_retired_counter_without_current_owner_pointer(legacy, doctype):
    t = legacy;old = archived_counter(t,doctype)
    with pytest.raises(registration.ChainRegistrationError,match='registration_history_counter_related') as failed:
        t.review()
    assert failed.value.__context__ is None and t.database.commits == 0
    assert t.runtime.get_doc(t.counter.doctype,t.counter.name).last_issued_icv == '27'
    assert old['path'].read_bytes() == old['content']
    t.b.request.assert_not_called()


def test_a_different_public_key_with_the_same_declared_full_unit_identity_also_holds(legacy):
    t = legacy;serial = '1-TEST|2-TEST|3-'+str(uuid4())
    t.change(t.selected,'custom_csr_config',CONFIG.replace('1-TEST|2-TEST|3-SYNTHETIC',serial))
    key = ec.generate_private_key(ec.SECP256K1())
    csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME,'SYNTHETIC-ROTATED-UNIT')])).sign(key,hashes.SHA256())
    body = json.loads(issued_body(csr,serial=serial))
    text = base64.b64decode(body['binarySecurityToken'],validate=True).decode()
    archived_counter(t,certificate_text=text)
    with pytest.raises(registration.ChainRegistrationError,match='registration_history_counter_related'):
        t.review()
    assert t.database.commits == 0


@pytest.mark.parametrize('fault', ['missing','unreadable','public','debug','remote','invalid_xml','wrong_uuid','wrong_icv','oversized'])
def test_unavailable_or_unmatched_archived_evidence_does_not_repair_or_activate(legacy, monkeypatch, fault):
    t = legacy;old = archived_counter(t)
    if fault == 'missing':old['path'].unlink()
    elif fault == 'invalid_xml':old['path'].write_bytes(b'NOT-XML')
    elif fault == 'unreadable':
        def permission(dt, operation, *, doc, user, raise_exception=True):return doc.name != old['file']
        t.runtime.has_permission = permission
    elif fault == 'oversized':monkeypatch.setattr(probe,'MAX_TOTAL_XML_BYTES',8)
    else:
        table,field,value = {
            'public':('File','is_private',0), 'debug':('File','file_name','DEBUG_history.xml'),
            'remote':('File','file_url','https://example.invalid/private.xml'),
            'wrong_uuid':(old['doctype'],'custom_uuid',str(uuid4())),
            'wrong_icv':(old['doctype'],'custom_zatca_icv','11')}[fault]
        with t.connection.cursor() as cursor:
            cursor.execute('UPDATE `tab'+table+'` SET `'+field+'`=%s WHERE name=%s',
                (value,old['file'] if table == 'File' else old['source']))
        t.connection.commit()
    result = t.review()
    assert result.last_icv == '27' and not result.active and t.database.commits == 1
    assert t.runtime.get_doc(t.counter.doctype,t.counter.name).last_issued_icv == '27'
    t.b.request.assert_not_called()


def test_a_different_certificate_declaration_does_not_merge_or_retire_its_counter(legacy):
    t = legacy;old = archived_counter(t,certificate_text=t.materials[1].text)
    result = t.review()
    assert result.last_icv == '27' and not result.active
    row = t.database.sql('SELECT active,last_issued_icv FROM `tabZATCA ICV Counter` WHERE name=%s',
        (old['counter'],),as_dict=True)[0]
    assert row == {'active':0,'last_issued_icv':'10'}


def test_a_database_failure_during_optional_history_aborts_the_whole_review(legacy, monkeypatch):
    t = legacy;archived_counter(t)
    sql = t.database.sql
    def broken(statement,values=(),**kwargs):
        if 'LOWER(file_name)' in statement:
            raise pymysql.OperationalError(1213,'PRIVATE-DEADLOCK-CONTEXT')
        return sql(statement,values,**kwargs)
    monkeypatch.setattr(t.database,'sql',broken)
    with pytest.raises(registration.ChainRegistrationError,match='registration_review_failed') as failed:
        t.review()
    assert failed.value.__context__ is None and 'PRIVATE' not in str(failed.value) and t.database.commits == 0


def test_archived_file_metadata_uses_a_current_read_even_after_the_initial_orm_view(legacy, monkeypatch):
    t = legacy;old = archived_counter(t,certificate_text=t.materials[1].text)
    current = etree.fromstring(old['content'])
    current.find('.//ds:X509Certificate',NS).text = t.selected.custom_certificate
    path = old['path'].with_name('Current-'+str(uuid4())+'.xml');path.write_bytes(etree.tostring(current))
    peer = t.connections();original=t.runtime.get_doc;injected=[]
    def get_doc(doctype,name,**kwargs):
        result=original(doctype,name,**kwargs)
        if (doctype,name)==(t.source.doctype,t.source.name) and not kwargs.get('for_update') and not injected:
            injected.append(True)
            with peer.cursor() as cursor:
                cursor.execute('UPDATE `tabFile` SET file_url=%s WHERE name=%s',
                    ('/private/files/'+path.name,old['file']))
            peer.commit()
        return result
    monkeypatch.setattr(t.runtime,'get_doc',get_doc)
    with pytest.raises(registration.ChainRegistrationError,match='registration_history_counter_related'):
        t.review()
    assert injected and t.database.commits == 0
