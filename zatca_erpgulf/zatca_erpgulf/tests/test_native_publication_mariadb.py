"""Read-only print/download adoption over private SQL with mocked dispatch.

Registration is preseeded; a synthetic metadata/signing builder supplies UBL.
No installed ERP, real invoice, tax service, print engine or CA/SDK is involved.
"""

import os
from decimal import Decimal
from types import SimpleNamespace

import pytest

from zatca_erpgulf.zatca_erpgulf import native_publication as publication
from zatca_erpgulf.zatca_erpgulf import native_dispatch, native_artifact
from zatca_erpgulf.zatca_erpgulf import native_provider
from zatca_erpgulf.zatca_erpgulf.issuing_attempt import _source_observation
from zatca_erpgulf.zatca_erpgulf.tests.test_credential_selection import Document
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider_mariadb import (
    case, boundary, materials, isolated_server, connections, tables,
)


pytestmark = pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB') != '1',
    reason='Owned private SQL opt-in only')


@pytest.mark.parametrize('case', [(n, kind, mode, simplified)
    for n in range(6) for kind in ('company', 'device', 'linked')
    if not (n in (2, 4) and kind == 'company')
    # Four secondary generators are Simplified-only reporting adapters.
    for mode, simplified in (('Batches', True), ('Live', True), ('Live', False))
    if simplified or n in (0, 1)], indirect=True)
def test_all_entries_publish_current_custody_without_writes_new_files_or_another_request(case, monkeypatch):
    c = case
    result = c.run()
    assert result['status'] in ('SUCCESS', 'PREPARED')
    monkeypatch.setattr(publication, 'frappe', c.runtime)
    monkeypatch.setattr(publication, '_', lambda text: text)
    c.runtime.has_permission = lambda dt, op, *, doc, user, raise_exception=True: op == 'read'
    c.selected.custom_private_key = 'INVALID-MUST-NOT-BE-PARSED'
    c.runtime.conf['zatca_native_dispatch'] = 0
    before = (c.head(), c.database.commits, len(c.sent), len(c.built))
    saved = c.runtime.get_doc(c.source.doctype, c.source.name)
    original = native_dispatch.read_retained_invoice(saved.doctype, saved.name, runtime=c.runtime)
    artifact = native_artifact.read_native_artifact(saved.doctype, saved.name, runtime=c.runtime)
    preview = publication.preview_result(saved.doctype, saved.name, runtime=c.runtime, translate=lambda s: s)
    assert preview['status'] == 'READY' and preview['accepted'] == result['accepted']
    response = publication.xml_response(saved.doctype, saved.name, original.issuance_id,
        runtime=c.runtime, translate=lambda s: s)
    assert response.get_data() == artifact.xml_bytes
    diagnostic = publication.xml_response(saved.doctype, saved.name, original.issuance_id,
        original=True, runtime=c.runtime, translate=lambda s: s)
    assert diagnostic.get_data() == original.original_xml
    saved.custom_zatca_status = 'FORGED-PRINT-STATUS'
    publication.before_print(saved, 'before_print', {})
    assert saved.ksa_einv_qr == preview['qr_data_uri']
    assert saved.custom_zatca_status == (original.state if original.accepted else 'Not Submitted')
    assert (c.head(), c.database.commits, len(c.sent), len(c.built)) == before
    unchanged = c.runtime.get_doc(saved.doctype, saved.name)
    assert unchanged.get('ksa_einv_qr') is None and unchanged.custom_zatca_status != 'FORGED-PRINT-STATUS'
    assert c.database.sql('SELECT COUNT(*) AS total FROM `tabFile`', as_dict=True)[0]['total'] == 0
    assert c.database.transaction_writes == 0
    c.b.request.assert_not_called()


def test_current_source_shared_lock_blocks_a_concurrent_change_and_never_repairs_history(case, monkeypatch):
    c = case
    result = c.run()
    assert result['accepted']
    other = c.connections()
    with other.cursor() as cursor:
        cursor.execute('UPDATE `tab'+c.source.doctype+'` SET docstatus=2 WHERE name=%s', (c.source.name,))
    before = (c.head(), len(c.sent), len(c.built))
    preview = publication.preview_result(c.source.doctype, c.source.name, runtime=c.runtime, translate=lambda s: s)
    assert preview['status'] == 'REVIEW' and 'qr_data_uri' not in preview
    other.commit()
    with pytest.raises(native_dispatch.NativeDispatchError, match='native_publication_source_review'):
        publication.load_publication(c.source.doctype, c.source.name, runtime=c.runtime)
    retained = native_dispatch.read_retained_invoice(c.source.doctype, c.source.name, runtime=c.runtime)
    assert retained.accepted
    assert (c.head(), len(c.sent), len(c.built)) == before


class NativeSource(Document):
    """Native-shaped observation double; not an installed ERP metadata claim."""
    def as_dict(self):
        return {key:value for key,value in vars(self).items() if not callable(value)}


def use_native_source(c,monkeypatch):
    """Add fixture-owned accounting columns/child rows before any generation."""
    with c.connection.cursor() as cursor:
        for field,kind in (('outstanding_amount','DECIMAL(21,9)'),('status','VARCHAR(140)'),
                ('grand_total','DECIMAL(21,9)'),('paid_amount','DECIMAL(21,9)')):
            cursor.execute('ALTER TABLE `tab'+c.source.doctype+'` ADD COLUMN IF NOT EXISTS `'+field+'` '+kind)
        if c.source.doctype=='POS Invoice':
            cursor.execute('ALTER TABLE `tabPOS Invoice` ADD COLUMN IF NOT EXISTS consolidated_invoice VARCHAR(140)')
        cursor.execute('UPDATE `tab'+c.source.doctype+'` SET outstanding_amount=115,status=%s,grand_total=115,paid_amount=0 '
            'WHERE name=%s',('Unpaid',c.source.name))
        cursor.execute('CREATE TABLE IF NOT EXISTS `tabPayment Schedule` (name VARCHAR(140) PRIMARY KEY,'
            'parent VARCHAR(140),parenttype VARCHAR(140),parentfield VARCHAR(140),idx INT,payment_term VARCHAR(140),'
            'payment_amount DECIMAL(21,9),base_payment_amount DECIMAL(21,9),paid_amount DECIMAL(21,9),'
            'base_paid_amount DECIMAL(21,9),outstanding DECIMAL(21,9),base_outstanding DECIMAL(21,9),'
            'discounted_amount DECIMAL(21,9)) ENGINE=InnoDB')
        if c.source.doctype=='Sales Invoice':
            cursor.execute('INSERT INTO `tabPayment Schedule` VALUES (%s,%s,%s,%s,1,%s,115,115,0,0,115,115,0)',
                (c.identifier+'-TERM',c.source.name,c.source.doctype,'payment_schedule','NET30'))
    c.connection.commit()
    original=c.runtime.get_doc
    def get_doc(dt,name,**kwargs):
        doc=original(dt,name,**kwargs)
        if dt==c.source.doctype:
            doc=NativeSource(**vars(doc))
            if dt=='Sales Invoice':
                suffix=' FOR UPDATE NOWAIT' if kwargs.get('for_update') else ''
                rows=c.runtime.db.sql('SELECT * FROM `tabPayment Schedule` WHERE parent=%s ORDER BY idx'+suffix,
                    (name,),as_dict=True)
                doc.payment_schedule=[NativeSource(doctype='Payment Schedule',**row) for row in rows]
        return doc
    monkeypatch.setattr(c.runtime,'get_doc',get_doc)
    metadata=c.runtime.get_meta
    def get_meta(dt):
        meta=metadata(dt)
        if dt==c.source.doctype and dt=='Sales Invoice':
            meta=SimpleNamespace(**vars(meta))
            meta.get_table_fields=lambda:[SimpleNamespace(options='Payment Schedule')]
        return meta
    monkeypatch.setattr(c.runtime,'get_meta',get_meta)
    monkeypatch.setattr(publication,'frappe',c.runtime)
    monkeypatch.setattr(publication,'_',lambda text:text)


def collect(c,*,cancel=False):
    """Model the inspected ERP15/16 post-payment field writes, not ERP posting."""
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tab'+c.source.doctype+'` SET outstanding_amount=%s,status=%s WHERE name=%s',
            (115 if cancel else 0,'Unpaid' if cancel else 'Paid',c.source.name))
        if c.source.doctype=='Sales Invoice':
            cursor.execute('UPDATE `tabPayment Schedule` SET paid_amount=%s,base_paid_amount=%s,'
                'outstanding=%s,base_outstanding=%s,discounted_amount=%s WHERE parent=%s',
                (0 if cancel else 115,0 if cancel else 115,115 if cancel else 0,115 if cancel else 0,
                 0,c.source.name))
    c.connection.commit()


@pytest.mark.parametrize('case',[(0,'company','Live',True),(1,'device','Live',True),
    (0,'linked','Live',False),(0,'device','Batches',True),(1,'device','Batches',True)],indirect=True)
def test_collection_and_its_cancellation_keep_exact_issued_xml_qr_and_pending_dispatch(case,monkeypatch):
    c=case;use_native_source(c,monkeypatch)
    generated=c.run()
    saved=c.runtime.get_doc(c.source.doctype,c.source.name)
    original=native_dispatch.read_retained_invoice(saved.doctype,saved.name,runtime=c.runtime)
    first=publication.load_publication(saved.doctype,saved.name,runtime=c.runtime)[0]
    assert first.publication_sha256 is not None
    observed=_source_observation(saved)
    before=(len(c.built),len(c.sent),c.head())
    collect(c)
    paid=c.runtime.get_doc(saved.doctype,saved.name)
    assert paid.outstanding_amount==Decimal('0') and paid.status=='Paid' and _source_observation(paid)!=observed
    current,image=publication.load_publication(saved.doctype,saved.name,runtime=c.runtime,render_document=paid)
    assert current.xml_bytes==first.xml_bytes and current.qr_payload==first.qr_payload
    assert current.publication_sha256==first.publication_sha256
    publication.before_print(paid)
    assert paid.ksa_einv_qr==image
    assert (len(c.built),len(c.sent),c.head())==before
    if not generated['accepted']:
        # The same projection admits exact retained preparation/reservation;
        # payment changes never regenerate the body or consume a second ICV.
        result=native_provider.maybe_process_native_invoice(saved.doctype,saved.name,runtime=c.runtime,
            translate=lambda text:text,build=lambda locked:getattr(c.module,c.fn)(locked.name),intent='manual')
        assert result['accepted'] and len(c.built)==1 and len(c.sent)==1 and c.head()=='1'
        assert native_dispatch.read_retained_invoice(saved.doctype,saved.name,runtime=c.runtime).original_xml==original.original_xml
    collect(c,cancel=True)
    again=publication.load_publication(saved.doctype,saved.name,runtime=c.runtime)[0]
    assert again.xml_bytes==first.xml_bytes and c.head()=='1'


@pytest.mark.parametrize('fault',['grand_total','paid_amount','schedule','null-legacy','corrupt-evidence'])
def test_collection_exception_cannot_hide_fiscal_edits_or_reinterpret_legacy_evidence(case,monkeypatch,fault):
    c=case;use_native_source(c,monkeypatch);assert c.run()['accepted']
    original=native_dispatch.read_retained_invoice(c.source.doctype,c.source.name,runtime=c.runtime)
    collect(c)
    with c.connection.cursor() as cursor:
        if fault in ('grand_total','paid_amount'):
            cursor.execute('UPDATE `tab'+c.source.doctype+'` SET `'+fault+'`=114 WHERE name=%s',(c.source.name,))
        elif fault=='schedule':
            cursor.execute('UPDATE `tabPayment Schedule` SET payment_amount=114 WHERE parent=%s',(c.source.name,))
        else:
            cursor.execute('UPDATE `tabZATCA Issuance` SET publication_ciphertext=%s WHERE name=%s',
                (None if fault=='null-legacy' else 'v1.INVALID',original.issuance_id))
    c.connection.commit()
    result=publication.preview_result(c.source.doctype,c.source.name,runtime=c.runtime,translate=lambda text:text)
    assert result['status']=='REVIEW' and 'qr_data_uri' not in result
    response=publication.xml_response(c.source.doctype,c.source.name,original.issuance_id,original=True,
        runtime=c.runtime,translate=lambda text:text)
    assert response.get_data()==original.original_xml and len(c.built)==1 and len(c.sent)==1 and c.head()=='1'


@pytest.mark.parametrize('field,value',[('outstanding_amount',Decimal('900')),('status','FORGED')])
def test_rendered_collection_values_must_still_match_current_saved_data(case,monkeypatch,field,value):
    c=case;use_native_source(c,monkeypatch);assert c.run()['accepted'];collect(c)
    paid=c.runtime.get_doc(c.source.doctype,c.source.name)
    assert publication.preview_result(paid.doctype,paid.name,runtime=c.runtime,translate=lambda s:s)['status']=='READY'
    setattr(paid,field,value)
    with pytest.raises(publication.NativePublicationError,match=publication.REVIEW):
        publication.load_publication(paid.doctype,paid.name,runtime=c.runtime,render_document=paid)
    assert c.head()=='1' and len(c.sent)==1 and len(c.built)==1


@pytest.mark.parametrize('case',[(1,'device','Live',True)],indirect=True)
def test_pos_consolidation_reference_does_not_replace_the_issued_document(case,monkeypatch):
    c=case;use_native_source(c,monkeypatch);assert c.run()['accepted']
    before=publication.load_publication(c.source.doctype,c.source.name,runtime=c.runtime)[0]
    with c.connection.cursor() as cursor:
        cursor.execute('UPDATE `tabPOS Invoice` SET consolidated_invoice=%s,status=%s WHERE name=%s',
            ('SYNTHETIC-CONSOLIDATION','Consolidated',c.source.name))
    c.connection.commit()
    saved=c.runtime.get_doc(c.source.doctype,c.source.name)
    after,image=publication.load_publication(saved.doctype,saved.name,runtime=c.runtime,render_document=saved)
    publication.before_print(saved)
    assert saved.ksa_einv_qr==image and after.xml_bytes==before.xml_bytes
    assert after.publication_sha256==before.publication_sha256
    assert c.head()=='1' and len(c.sent)==1 and len(c.built)==1
