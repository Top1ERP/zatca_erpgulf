"""Frozen print parties from actual private custody; all HTTP remains mocked."""

import os

import pytest

from zatca_erpgulf.zatca_erpgulf import native_publication as publication,native_artifact
from zatca_erpgulf.zatca_erpgulf.issued_print import STAMP,PARTIES
from zatca_erpgulf.zatca_erpgulf.tests.test_native_provider_mariadb import (
    case,boundary,materials,isolated_server,connections,tables,
)
from zatca_erpgulf.zatca_erpgulf.tests.test_native_publication_mariadb import use_native_source


pytestmark=pytest.mark.skipif(os.environ.get('ZATCA_RUN_ISOLATED_MARIADB')!='1',reason='Owned private SQL opt-in only')


@pytest.mark.parametrize('case',[(n,'device','Live',True) for n in range(6)]+
    [(0,'company','Live',False),(1,'linked','Live',False)],indirect=True)
def test_all_native_entries_print_xml_party_data_after_master_changes_without_any_write_or_resend(case,monkeypatch):
    c=case;use_native_source(c,monkeypatch);assert c.run()['accepted']
    saved=c.runtime.get_doc(c.source.doctype,c.source.name)
    expected=native_artifact.read_native_artifact(saved.doctype,saved.name,runtime=c.runtime,for_publication=True,for_print=True)
    original=saved.as_dict().copy();before=(c.head(),c.database.commits,c.database.transaction_writes,len(c.sent),len(c.built))
    c.company.company_name='CHANGED CURRENT COMPANY';c.company.tax_id='CHANGED CURRENT VAT'
    c.selected.custom_private_key='UNAVAILABLE-CURRENT-KEY';c.runtime.conf['zatca_native_dispatch']=0
    c.runtime.has_permission=lambda dt,op,*,doc,user,raise_exception=True:op=='read'
    publication.before_print(saved)
    assert saved.company_name==expected.issued_parties.seller.registration_name
    assert saved.company_tax_id==expected.issued_parties.seller.vat_number
    assert saved.customer_name==expected.issued_parties.buyer.registration_name
    assert saved.company_address_display==expected.issued_parties.seller.address_html
    assert saved.address_display==expected.issued_parties.buyer.address_html
    assert saved.company==original['company'] and saved.customer==original['customer']
    publication.before_print(saved)  # Same-object reprint keeps strict native source comparison.
    changed={'company_name','company_tax_id','company_address_display','customer_name','tax_id','address_display',
        'ksa_einv_qr','custom_zatca_status','__link_titles',STAMP,PARTIES}
    assert {k:v for k,v in saved.as_dict().items() if k not in changed}=={k:v for k,v in original.items() if k not in changed}
    fresh=c.runtime.get_doc(c.source.doctype,c.source.name)
    assert fresh.as_dict()==original
    assert (c.head(),c.database.commits,c.database.transaction_writes,len(c.sent),len(c.built))==before


@pytest.mark.parametrize('field,value',[('grand_total',999),('customer_name','FORGED AFTER PRINT'),('unknown_financial_field',999)])
def test_same_object_stamp_never_exempts_later_financial_or_display_tampering(case,monkeypatch,field,value):
    c=case;use_native_source(c,monkeypatch);c.run();saved=c.runtime.get_doc(c.source.doctype,c.source.name)
    publication.before_print(saved);setattr(saved,field,value)
    with pytest.raises(publication.NativePublicationError):publication.before_print(saved)
    assert c.head()=='1' and c.database.transaction_writes==0
