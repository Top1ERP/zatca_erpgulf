"""Read-only applied Meta adapter for explicit source profiles, not schema proof.

Frappe's ordinary Meta field map excludes default/base fields. Callers MUST
supply those definitions explicitly, e.g. from the framework's get_default_df.
No Frappe import, schema discovery, defaults/Property Setter lookup or writes.
"""

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from . import financial_source_observation as financial
from . import issuing_settings_observation as issuing
from . import party_address_observation as party
from . import calculation_settings_observation as calculation
from . import tax_dependency_observation as tax

PROFILE = "source-applied-field-metadata/v1"
FORMAT_PROFILE = "source-precision-format-metadata/v1"
CHILD_CURRENCY_PROFILE = "source-child-currency-metadata/v1"
PROPERTIES = ("fieldtype", "options", "precision", "default", "reqd", "read_only",
    "hidden", "non_negative", "allow_on_submit", "is_custom_field")
BASE_TYPES = MappingProxyType({"docstatus":"Int", "creation":"Datetime"})


def _profiles():
    fields={}
    def add(doctype,names):
        fields.setdefault(doctype,set()).update(names)
    for dt in ("Sales Invoice","POS Invoice"):
        add(dt,(*financial.HEADER_FIELDS,*financial.TABLE_FIELDS))
        for table,names in financial.TABLE_FIELDS.items(): add(financial._child_type(dt,table),names)
    for mapping in (issuing.FIELDS,party.FIELDS,calculation.FIELDS):
        for dt,names in mapping.items(): add(dt,names)
    for dt,(child,names,_required) in tax.TABLE_PROFILES.items():
        add(dt,(*tax.TEMPLATE_FIELDS,"taxes"))
        add(child,names)
    add("Address",("links",))
    add("Dynamic Link",party.LINK_FIELDS)
    add("POS Profile",("payments",))
    add("POS Payment Method",calculation.PAYMENT_FIELDS)
    return MappingProxyType({dt:tuple(sorted(names)) for dt,names in fields.items()})


SOURCE_FIELDS=_profiles()
FORMAT_FIELDS=MappingProxyType({
    "System Settings": ("use_number_format_from_currency",),
    "Language": ("number_format",),
    "Currency": ("number_format",),
})
CHILD_CURRENCY_FIELDS=MappingProxyType({
    dt: ("currency", "company")
    for dt in sorted({financial._child_type(root, table)
        for root in ("Sales Invoice", "POS Invoice") for table in financial.TABLE_FIELDS})
})
PROFILE_FIELDS=MappingProxyType({PROFILE: SOURCE_FIELDS, FORMAT_PROFILE: FORMAT_FIELDS,
    CHILD_CURRENCY_PROFILE: CHILD_CURRENCY_FIELDS})
SINGLETONS=calculation.SINGLETONS
CHILD_TYPES=frozenset({
    *(financial._child_type(dt,table) for dt in ("Sales Invoice","POS Invoice") for table in financial.TABLE_FIELDS),
    "Dynamic Link","POS Payment Method","Item Tax Template Detail",
})


class SourceMetadataError(ValueError):
    """Static errors only; no raw metadata defaults or source field disclosure."""

    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _properties(values):
    financial._validate_projection(values,PROPERTIES,PROPERTIES)
    decoded={name:financial._validate_scalar(value) for name,value in values}
    fieldtype=decoded["fieldtype"]
    financial._name(fieldtype)
    if fieldtype=="Password":
        raise ValueError
    return MappingProxyType(decoded)


@dataclass(frozen=True,repr=False)
class SourceFieldDefinition:
    """Immutable applied property lookup; NOT Custom Field/Setter provenance."""

    fieldname:str
    _payload:bytes=field(repr=False)
    _values:object=field(init=False,repr=False,compare=False)

    def __post_init__(self):
        try:
            financial._name(self.fieldname)
            if type(self._payload) is not bytes or not 0<len(self._payload)<=financial.MAX_PAYLOAD_BYTES:
                raise ValueError
            values=json.loads(self._payload)
            decoded=_properties(values)
            if financial._canonical(values)!=self._payload:
                raise ValueError
        except Exception:
            invalid=True
        else:
            invalid=False
        if invalid:
            raise SourceMetadataError("source_field_definition")
        object.__setattr__(self,"_values",decoded)

    def get(self,name,default=None):
        return self._values.get(name,default)

    @property
    def fieldtype(self):
        return self._values["fieldtype"]

    @property
    def options(self):
        return self._values["options"]

    def __repr__(self):
        return "<SourceFieldDefinition protected applied properties>"

    def __reduce__(self):
        raise TypeError("source_metadata_not_serializable")


@dataclass(frozen=True,repr=False)
class SourceMetadata:
    """Explicit profile allowlist and base fields; no physical-column assertion."""

    name:str
    _payload:bytes=field(repr=False)
    _fields:object=field(init=False,repr=False,compare=False)
    issingle:bool=field(init=False)
    istable:bool=field(init=False)
    sha256:str=field(init=False)
    profile:str=field(init=False)

    def __post_init__(self):
        try:
            if (type(self.name) is not str or type(self._payload) is not bytes
                or not 0<len(self._payload)<=financial.MAX_PAYLOAD_BYTES):
                raise ValueError
            body=json.loads(self._payload)
            if (type(body) is not dict or set(body)!={"profile","doctype","issingle","istable","fields"}
                or type(body["profile"]) is not str or body["profile"] not in PROFILE_FIELDS):
                raise ValueError
            selected=PROFILE_FIELDS[body["profile"]]
            if (self.name not in selected or body["doctype"]!=self.name
                or type(body["issingle"]) is not bool or body["issingle"]!=(self.name in SINGLETONS)
                or type(body["istable"]) is not bool or body["istable"]!=(self.name in CHILD_TYPES)
                or type(body["fields"]) is not list or len(body["fields"])!=len(selected[self.name])
                or financial._canonical(body)!=self._payload):
                raise ValueError
            fields={}
            for entry,name in zip(body["fields"],selected[self.name]):
                if type(entry) is not list or len(entry)!=2 or entry[0]!=name:
                    raise ValueError
                if entry[1]==["absent"]:
                    if name in BASE_TYPES:
                        raise ValueError
                    continue
                definition=SourceFieldDefinition(name,financial._canonical(entry[1]))
                if name in BASE_TYPES and definition.fieldtype!=BASE_TYPES[name]:
                    raise ValueError
                fields[name]=definition
        except Exception:
            invalid=True
        else:
            invalid=False
        if invalid:
            raise SourceMetadataError("source_metadata_projection")
        object.__setattr__(self,"_fields",MappingProxyType(fields))
        object.__setattr__(self,"profile",body["profile"])
        object.__setattr__(self,"issingle",body["issingle"])
        object.__setattr__(self,"istable",body["istable"])
        object.__setattr__(self,"sha256",hashlib.sha256(
            b"zatca-source-applied-field-metadata/v1\0"+self._payload).hexdigest())

    def has_field(self,name):
        return name in self._fields

    def get_field(self,name):
        return self._fields.get(name)

    def __repr__(self):
        return "<SourceMetadata protected explicit schema declaration, not verified>"

    def __reduce__(self):
        raise TypeError("source_metadata_not_serializable")


def _pin_metadata(metadata):
    """Independent validated declaration; never trust cached derived fields."""
    if type(metadata) is not SourceMetadata:
        raise ValueError
    pinned=SourceMetadata(metadata.name,metadata._payload)
    if pinned!=metadata:
        raise ValueError
    return pinned


def project_source_metadata(meta,*,base_fields,profile=PROFILE):
    """Capture selected applied definitions, explicitly supplement base fields.

    base_fields must contain EXACTLY the selected default/base field names.
    Do not infer a base field from doc attributes or an empty metadata lookup.
    Raw Meta and supplied base definitions may not shadow each other.
    """
    try:
        doctype=meta.name
        if type(profile) is not str or profile not in PROFILE_FIELDS:
            raise ValueError
        selected=PROFILE_FIELDS[profile]
        if type(doctype) is not str or doctype not in selected or type(base_fields) is not dict:
            raise ValueError
        expected=set(selected[doctype])&set(BASE_TYPES)
        if set(base_fields)!=expected:
            raise ValueError
        single,child=getattr(meta,"issingle",0),getattr(meta,"istable",0)
        if any(type(flag) not in (bool,int) or flag not in (0,1) for flag in (single,child)):
            raise ValueError
        entries=[]
        for name in selected[doctype]:
            present=financial._present(meta,name)
            if name in base_fields:
                if present: raise ValueError
                definition=base_fields[name]
            elif present:
                definition=meta.get_field(name)
            else:
                entries.append([name,["absent"]])
                continue
            if definition is None or definition.get("fieldname")!=name:
                raise ValueError
            fieldtype=definition.get("fieldtype")
            financial._name(fieldtype)
            if fieldtype=="Password": raise ValueError  # Before reading defaults.
            values=[[prop,financial._scalar(definition.get(prop))] for prop in PROPERTIES]
            entries.append([name,values])
        result=SourceMetadata(doctype,financial._canonical(dict(profile=profile,doctype=doctype,
            issingle=bool(single),istable=bool(child),fields=entries)))
    except Exception:
        invalid=True
    else:
        invalid=False
    if invalid:
        raise SourceMetadataError("source_metadata_capture")
    return result


@dataclass(frozen=True,repr=False)
class SourceDocumentView:
    """Narrow read interface, NOT immutable values, saved ACL or source locking."""

    _source:object=field(repr=False)
    meta:SourceMetadata
    doctype:str=field(init=False)
    name:str=field(init=False)

    def __post_init__(self):
        try:
            if type(self.meta) is not SourceMetadata or self._source.doctype!=self.meta.name:
                raise ValueError
            name=financial._name(self._source.name)
            meta=_pin_metadata(self.meta)
        except Exception:
            invalid=True
        else:
            invalid=False
        if invalid:
            raise SourceMetadataError("source_metadata_view")
        object.__setattr__(self,"meta",meta)
        object.__setattr__(self,"doctype",meta.name)
        object.__setattr__(self,"name",name)

    def get(self,name):
        allowed=(*PROFILE_FIELDS[self.meta.profile][self.doctype],"name","doctype","modified","creation",
            "docstatus","parent","parenttype","parentfield","idx")
        if type(name) is not str or name not in allowed:
            raise SourceMetadataError("source_metadata_field_access")
        if (self._source.doctype,self._source.name)!=(self.doctype,self.name):
            raise SourceMetadataError("source_metadata_view_drift")
        return self._source.get(name)

    def __repr__(self):
        return "<SourceDocumentView protected read-only interface, not a snapshot>"

    def __reduce__(self):
        raise TypeError("source_metadata_not_serializable")
