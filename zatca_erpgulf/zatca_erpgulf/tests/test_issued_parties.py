"""Frozen XML parties and actual transient print integration; no site/HTTP."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import pickle

from lxml import etree
import pytest

from zatca_erpgulf.zatca_erpgulf import issued_parties as parties,native_publication as publication
from zatca_erpgulf.zatca_erpgulf.issued_print import STAMP,PARTIES
from zatca_erpgulf.zatca_erpgulf.artifact_evidence import NS
from zatca_erpgulf.zatca_erpgulf.tests.test_native_publication import view,coordinator,boundary,materials
from zatca_erpgulf.zatca_erpgulf.tests.test_artifact_evidence import node


def xml(c,**kwargs):return c.retain(**kwargs)[0]


def test_model_is_literal_frozen_and_retains_absent_buyer_vat_without_current_master_fallback(view):
    c=view;result=parties.extract_issued_parties(xml(c))
    assert result.seller.registration_name=='Issued seller' and result.buyer.registration_name=='Issued buyer'
    assert result.seller.vat_number and result.buyer.vat_number is None
    assert result.seller.address.street=='Issued street' and result.seller.address.country=='SA'
    with pytest.raises(FrozenInstanceError):result.seller.registration_name='FORGED'
    with pytest.raises(TypeError):pickle.dumps(result)


@pytest.mark.parametrize('target',['supplier','buyer','legal','name','address','country','tax','identifier','name_markup'])
def test_ambiguous_or_nested_party_fields_do_not_choose_the_first_value(view,target):
    root=etree.fromstring(xml(view))
    seller=root.find('cac:AccountingSupplierParty/cac:Party',NS)
    buyer=root.find('cac:AccountingCustomerParty/cac:Party',NS)
    if target=='supplier':root.append(deepcopy(root.find('cac:AccountingSupplierParty',NS)))
    elif target=='buyer':root.append(deepcopy(root.find('cac:AccountingCustomerParty',NS)))
    elif target=='legal':seller.append(deepcopy(seller.find('cac:PartyLegalEntity',NS)))
    elif target=='name':seller.find('cac:PartyLegalEntity',NS).append(deepcopy(seller.find('cac:PartyLegalEntity/cbc:RegistrationName',NS)))
    elif target=='address':seller.append(deepcopy(seller.find('cac:PostalAddress',NS)))
    elif target=='country':seller.find('cac:PostalAddress',NS).append(deepcopy(seller.find('cac:PostalAddress/cac:Country',NS)))
    elif target=='tax':seller.append(deepcopy(seller.find('cac:PartyTaxScheme',NS)))
    elif target=='identifier':
        identification=node(buyer,'cac','PartyIdentification');node(identification,'cbc','ID','ONE');node(identification,'cbc','ID','TWO')
    else:node(seller.find('cac:PartyLegalEntity/cbc:RegistrationName',NS),'cbc','Name','NESTED')
    with pytest.raises(parties.IssuedPartiesError):parties.extract_issued_parties(etree.tostring(root))


def test_address_html_escapes_xml_text_and_preserves_other_identifier_schemes(view):
    root=etree.fromstring(xml(view));seller=root.find('cac:AccountingSupplierParty/cac:Party',NS)
    seller.find('cac:PostalAddress/cbc:StreetName',NS).text='<script>PRIVATE</script> & "Street"'
    node(node(seller,'cac','PartyIdentification'),'cbc','ID','CRN<&>',schemeID='CRN')
    snapshot=parties.extract_issued_parties(etree.tostring(root))
    assert '<script>' not in snapshot.seller.address_html and '&lt;script&gt;' in snapshot.seller.address_html
    assert '&amp;' in snapshot.seller.address_html and '&quot;' in snapshot.seller.address_html
    assert snapshot.seller.identifiers==( ('CRN','CRN<&>'), )


def test_missing_buyer_is_empty_instead_of_invented_from_current_customer(view):
    root=etree.fromstring(xml(view));root.remove(root.find('cac:AccountingCustomerParty',NS))
    result=parties.extract_issued_parties(etree.tostring(root))
    assert result.buyer.registration_name is None and result.buyer.address_html==''


def test_actual_print_freezes_party_fields_retains_links_money_and_the_saved_record(view):
    c=view;c.b.sales.customer='SOURCE-CUSTOMER';c.b.sales.customer_name='Current customer display';c.b.sales.tax_id='CURRENT-VAT'
    c.b.sales.company_address_display='CURRENT ADDRESS';c.retain()
    before=deepcopy(vars(c.b.sales));rendered=deepcopy(c.b.sales)
    c.b.company.company_name='CHANGED MASTER NAME';c.b.company.tax_id='CHANGED MASTER VAT'
    publication.before_print(rendered)
    assert rendered.customer_name=='Issued buyer' and rendered.company_name=='Issued seller'
    assert rendered.tax_id=='' and rendered.company_tax_id!='CHANGED MASTER VAT'
    assert 'Issued street' in rendered.company_address_display and 'CURRENT ADDRESS' not in rendered.company_address_display
    assert rendered.company==before['company'] and rendered.customer==before['customer']
    assert getattr(rendered,'__link_titles')['Company::'+rendered.company]=='Issued seller'
    assert vars(c.b.sales)==before
    changed={'company_name','company_tax_id','company_address_display','customer_name','tax_id','address_display',
        'ksa_einv_qr','custom_zatca_status','__link_titles',STAMP,PARTIES}
    assert {k:v for k,v in vars(rendered).items() if k not in changed}=={k:v for k,v in before.items() if k not in changed}
    c.worker.commit.assert_not_called();c.b.request.assert_not_called()


def test_reprint_preserves_the_source_guard_without_requiring_fresh_signing_or_master_values(view):
    c=view;rendered=deepcopy(c.b.sales);publication.before_print(rendered)
    first=(rendered.ksa_einv_qr,rendered.customer_name,rendered.address_display)
    publication.before_print(rendered)
    assert (rendered.ksa_einv_qr,rendered.customer_name,rendered.address_display)==first
    with pytest.raises(TypeError):pickle.dumps(getattr(rendered,STAMP))


@pytest.mark.parametrize('target',['money','projected_name','titles','stamp','parties','actor'])
def test_reprint_cannot_hide_a_client_or_late_render_change(view,target):
    c=view;rendered=deepcopy(c.b.sales);publication.before_print(rendered)
    if target=='money':rendered.grand_total=900
    elif target=='projected_name':rendered.customer_name='FORGED'
    elif target=='titles':getattr(rendered,'__link_titles')['Company::'+rendered.company]='FORGED'
    elif target=='stamp':setattr(rendered,STAMP,{'forged':'JSON'})
    elif target=='parties':setattr(rendered,PARTIES,{'forged':'JSON'})
    else:c.b.frappe.session.user='OTHER'
    with pytest.raises(publication.NativePublicationError):publication.before_print(rendered)


def test_cleared_party_drift_cannot_become_the_print_source_even_with_matching_metadata(view):
    c=view;c.retain(state='CLEARED',indicator='0100000')
    import base64
    receipt,raw=c.repository.open_receipt.return_value;body=json.loads(raw)
    returned=etree.fromstring(base64.b64decode(body['clearedInvoice']))
    returned.find('cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName',NS).text='OTHER BUYER'
    body['clearedInvoice']=base64.b64encode(etree.tostring(returned)).decode();wire=json.dumps(body).encode()
    receipt['response_sha256']=hashlib.sha256(wire).hexdigest();c.repository.open_receipt.return_value=(receipt,wire)
    with pytest.raises(publication.NativePublicationError):publication.before_print(deepcopy(c.b.sales))


def test_utf16_and_utf8_project_the_same_party_values_without_serializing_the_original(view):
    source=xml(view);root=etree.fromstring(source)
    utf16=etree.tostring(root,encoding='UTF-16',xml_declaration=True)
    assert parties.extract_issued_parties(utf16)==parties.extract_issued_parties(source)


@pytest.mark.parametrize('payload',[b'<!DOCTYPE Invoice [<!ENTITY x SYSTEM "file:///PRIVATE">]><Invoice>&x;</Invoice>',b'<INVALID>'])
def test_parser_never_expands_external_entities_or_repairs_bad_xml(payload):
    with pytest.raises(Exception):parties.extract_issued_parties(payload)
