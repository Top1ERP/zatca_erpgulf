"""Frozen display data from saved invoice XML, never current party masters.

This is a bounded namespace-aware projection, not XSD/crypto/tax validation.
Names and identifiers stay literal text; only address HTML is escaped here.
No money, timezone, country-name lookup, credential or transport is involved.
"""

from dataclasses import dataclass
from html import escape

from .artifact_evidence import NS,parse_diagnostic_xml


class IssuedPartiesError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def _one(parent,path,*,required=False):
    rows=parent.xpath(path,namespaces=NS)
    if len(rows)>1 or required and len(rows)!=1:raise IssuedPartiesError('issued_party_ambiguous_or_missing')
    return rows[0] if rows else None


def _text(parent,path,*,required=False):
    row=_one(parent,path,required=required)
    if row is None:return None
    if len(row) or type(row.text) is not str or not row.text.strip() or len(row.text)>4096:
        raise IssuedPartiesError('issued_party_text')
    return row.text


@dataclass(frozen=True,repr=False)
class IssuedAddress:
    street: str | None=None
    additional_street: str | None=None
    building: str | None=None
    plot: str | None=None
    district: str | None=None
    city: str | None=None
    postal_zone: str | None=None
    region: str | None=None
    country: str | None=None

    def html(self):
        values=(self.street,self.additional_street,self.building,self.plot,self.district,
            self.city,self.postal_zone,self.region,self.country)
        return '<br>'.join(escape(value,quote=True) for value in values if value is not None)


@dataclass(frozen=True,repr=False)
class IssuedParty:
    registration_name: str | None=None
    names: tuple=()
    identifiers: tuple=()
    vat_number: str | None=None
    address: IssuedAddress | None=None

    @property
    def address_html(self):return self.address.html() if self.address is not None else ''


@dataclass(frozen=True,repr=False)
class IssuedParties:
    seller: IssuedParty
    buyer: IssuedParty
    def __reduce_ex__(self,protocol):raise TypeError('issued_parties_not_serializable')


def _party(root,path,*,seller=False):
    accounting=_one(root,path,required=seller)
    if accounting is None:return IssuedParty()
    party=_one(accounting,'./cac:Party',required=seller)
    if party is None:return IssuedParty()
    legal=_one(party,'./cac:PartyLegalEntity',required=seller)
    name=_text(legal,'./cbc:RegistrationName',required=seller) if legal is not None else None
    name_rows=party.xpath('./cac:PartyName',namespaces=NS)
    id_rows=party.xpath('./cac:PartyIdentification',namespaces=NS)
    if len(name_rows)>8 or len(id_rows)>8:raise IssuedPartiesError('issued_party_list_budget')
    names=tuple(_text(row,'./cbc:Name',required=True) for row in name_rows)
    identifiers=[]
    for row in id_rows:
        value=_text(row,'./cbc:ID',required=True);scheme=_one(row,'./cbc:ID',required=True).get('schemeID')
        if scheme is not None and len(scheme)>64:raise IssuedPartiesError('issued_party_scheme')
        identifiers.append((scheme,value))
    tax=_one(party,"./cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']",required=seller)
    if tax is not None:
        scheme=_one(tax,'./cac:TaxScheme',required=True)
        if _text(scheme,'./cbc:ID',required=True)!='VAT':raise IssuedPartiesError('issued_party_tax_scheme')
    vat=_text(tax,'./cbc:CompanyID',required=seller) if tax is not None else None
    address=_one(party,'./cac:PostalAddress',required=seller)
    postal=None
    if address is not None:
        country=_one(address,'./cac:Country')
        postal=IssuedAddress(*(_text(address,'./cbc:'+tag) for tag in (
            'StreetName','AdditionalStreetName','BuildingNumber','PlotIdentification',
            'CitySubdivisionName','CityName','PostalZone','CountrySubentity')),
            country=_text(country,'./cbc:IdentificationCode') if country is not None else None)
    return IssuedParty(name,names,tuple(identifiers),vat,postal)


def extract_issued_parties(content):
    root=parse_diagnostic_xml(content)
    return IssuedParties(_party(root,'./cac:AccountingSupplierParty',seller=True),
        _party(root,'./cac:AccountingCustomerParty'))
