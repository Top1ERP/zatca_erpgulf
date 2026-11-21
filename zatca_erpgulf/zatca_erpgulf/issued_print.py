"""Apply saved XML parties only to the validated transient print document.

Keep ERP link IDs and all money/posting/collection fields untouched. A private,
nonserializable stamp permits the same render object to be printed again without
treating our own presentation overrides as edits to the saved invoice. It does
not excuse client edits, bind a new source/version or bypass fresh custody reads.
"""

from dataclasses import dataclass,field

from .issued_parties import IssuedParties,IssuedPartiesError


STAMP='_zatca_issued_print'
PARTIES='zatca_issued_parties'
FIELDS=('company_name','company_tax_id','company_address_display','customer_name','tax_id','address_display')


@dataclass(frozen=True,repr=False)
class _PrintStamp:
    document: object=field(repr=False)
    site: str
    actor: str
    issuance_id: str
    original: tuple
    present: frozenset
    projected: tuple
    parties: IssuedParties
    titles: tuple
    def __reduce_ex__(self,protocol):raise TypeError('issued_print_not_serializable')


def _stamp(document,runtime,issuance_id):
    value=document.get(STAMP)
    if value is None:return None
    if (type(value) is not _PrintStamp or value.document is not document
            or value.site!=runtime.local.site or value.actor!=runtime.session.user
            or value.issuance_id!=issuance_id or document.get(PARTIES) is not value.parties
            or any(document.get(key)!=expected for key,expected in value.projected)):
        raise IssuedPartiesError('issued_print_changed_projection')
    titles=document.get('__link_titles') or {}
    if not isinstance(titles,dict) or any(titles.get(key)!=expected for key,expected in value.titles):
        raise IssuedPartiesError('issued_print_changed_titles')
    return value


class _RenderInput:
    """Native/fallback observation adapter; no source or render mutation."""
    def __init__(self,document,stamp):self.document=document;self.stamp=stamp

    def __getattr__(self,name):
        if name=='as_dict':
            return self.native_dict if callable(getattr(self.document,'as_dict',None)) else None
        return getattr(self.document,name)

    def get(self,name,default=None):
        if self.stamp is not None:
            values=dict(self.stamp.original)
            if name in values:return values[name]
        return self.document.get(name,default)

    def native_dict(self):
        body=dict(self.document.as_dict())
        # These are request-local presentation attributes, not ERP custom
        # fiscal fields. The stamp must authenticate before any omission.
        body.pop('__link_titles',None)
        if self.stamp is not None:
            for name in (STAMP,PARTIES):body.pop(name,None)
            for name in FIELDS:
                if name not in self.stamp.present:body.pop(name,None)
        return body


def render_input(document,*,runtime,issuance_id):
    return _RenderInput(document,_stamp(document,runtime,issuance_id))


def apply_issued_parties(document,parties,*,runtime,issuance_id):
    if type(parties) is not IssuedParties:raise IssuedPartiesError('issued_print_missing_parties')
    previous=_stamp(document,runtime,issuance_id)
    if previous is not None:
        if previous.parties!=parties:raise IssuedPartiesError('issued_print_changed_custody')
        return  # Existing projection is unchanged and fresh custody was verified.
    converter=getattr(document,'as_dict',None)
    present=frozenset(converter()) if callable(converter) else frozenset()
    if STAMP in present or PARTIES in present:raise IssuedPartiesError('issued_print_reserved_attribute')
    original=tuple((name,document.get(name)) for name in FIELDS)
    values=(parties.seller.registration_name or '',parties.seller.vat_number or '',parties.seller.address_html,
        parties.buyer.registration_name or '',parties.buyer.vat_number or '',parties.buyer.address_html)
    projected=tuple(zip(FIELDS,values))
    titles=document.get('__link_titles')
    if titles is not None and not isinstance(titles,dict):raise IssuedPartiesError('issued_print_titles')
    titles=dict(titles or {})
    selected=[]
    for doctype,name,value in (('Company',document.get('company'),values[0]),('Customer',document.get('customer'),values[3])):
        if type(name) is str and name:
            key=doctype+'::'+name;titles[key]=value;selected.append((key,value))
    stamp=_PrintStamp(document,runtime.local.site,runtime.session.user,issuance_id,original,present,projected,parties,tuple(selected))
    for name,value in projected:setattr(document,name,value)
    setattr(document,PARTIES,parties)
    setattr(document,'__link_titles',titles)
    setattr(document,STAMP,stamp)
