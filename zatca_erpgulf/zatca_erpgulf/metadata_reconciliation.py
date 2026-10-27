"""Compare supplied raw field customizations with applied metadata declarations.

Uses only the installed framework's bounded non-date/time cast subset. No
record loading, DB/cache/defaults lookup, evaluation, metadata writes or HTTP.
Matching declarations is NOT committed/source/row-completeness provenance.
"""

from dataclasses import dataclass,field
import hashlib
import json

from frappe.utils.data import cast as _framework_cast
from frappe import __version__ as FRAMEWORK_VERSION

from .financial_source_observation import (
    MAX_PAYLOAD_BYTES,_canonical,_name,_scalar,_validate_projection,_validate_scalar,
)
from .source_metadata import (
    BASE_TYPES,PROPERTIES,SOURCE_FIELDS,PROFILE_FIELDS,SourceFieldDefinition,SourceMetadata,_pin_metadata,
)

PROFILE="source-field-customization-match/v1"
MAX_CUSTOM_FIELDS=128
MAX_SETTERS=256
EDITABLE=tuple(prop for prop in PROPERTIES if prop!="is_custom_field")
CUSTOM_FIELDS=("dt","fieldname",*EDITABLE)
SETTER_FIELDS=("doctype_or_field","doc_type","field_name","property","property_type","value")
CAST_TYPES=frozenset(("Data","Text","Small Text","Long Text","Text Editor","Select","Link",
    "Dynamic Link","Int","Check","Float","Currency","Percent"))


class MetadataReconciliationError(ValueError):
    """Static failures; no raw customization, defaults or framework exceptions."""

    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _validate_row(record,fields,identities):
    if (type(record) is not dict or set(record)!={"name","modified","header"}
        or _name(record["name"]) in identities):
        raise ValueError
    identities.add(record["name"])
    _validate_scalar(record["modified"])
    if record["modified"][0] not in ("str","datetime") or not record["modified"][1]:
        raise ValueError
    _validate_projection(record["header"],fields,fields)
    return {name:_validate_scalar(value) for name,value in record["header"]}


def _marker(value):
    if value is None: return False
    if type(value) in (bool,int) and value in (0,1): return bool(value)
    raise ValueError


def _compare(base,applied,custom_fields,setters):
    if (base.name!=applied.name or base.profile!=applied.profile
        or (base.issingle,base.istable)!=(applied.issingle,applied.istable)):
        raise ValueError
    if type(custom_fields) is not list or len(custom_fields)>MAX_CUSTOM_FIELDS or type(setters) is not list or len(setters)>MAX_SETTERS:
        raise ValueError
    expected={name:values for name,values in json.loads(base._payload)["fields"]}
    for name,values in expected.items():
        if values!=["absent"] and _marker(_validate_scalar(dict(values)["is_custom_field"])):
            raise ValueError  # Baseline must not already conceal Custom Fields.
    custom_names,identities=set(),set()
    order=[]
    for record in custom_fields:
        raw=_validate_row(record,CUSTOM_FIELDS,identities)
        name=raw["fieldname"]
        _name(name)
        if (raw["dt"]!=base.name or name not in expected or name in BASE_TYPES
            or name in custom_names or expected[name]!=["absent"]):
            raise ValueError
        values=[[prop,_scalar(1 if prop=="is_custom_field" else raw[prop])] for prop in PROPERTIES]
        SourceFieldDefinition(name,_canonical(values))
        expected[name]=values
        custom_names.add(name)
        order.append(record["name"])
    if order!=sorted(order):
        raise ValueError
    properties,identities,order=set(),set(),[]
    for record in setters:
        raw=_validate_row(record,SETTER_FIELDS,identities)
        name,prop=raw["field_name"],raw["property"]
        _name(name)
        if (raw["doctype_or_field"]!="DocField" or raw["doc_type"]!=base.name or name not in expected
            or name in BASE_TYPES or expected[name]==["absent"] or prop not in EDITABLE
            or raw["property_type"] not in CAST_TYPES or (name,prop) in properties):
            raise ValueError
        properties.add((name,prop))
        # Date/time cast paths are deliberately excluded: some consult clocks.
        value=_scalar(_framework_cast(raw["property_type"],raw["value"]))
        expected[name]=[[key,value if key==prop else encoded] for key,encoded in expected[name]]
        SourceFieldDefinition(name,_canonical(expected[name]))
        order.append(record["name"])
    if order!=sorted(order):
        raise ValueError
    observed=dict(json.loads(applied._payload)["fields"])
    if expected!=observed:
        raise ValueError


@dataclass(frozen=True,repr=False)
class FieldCustomizationMatch:
    """Protected declaration equality only, no replay/dispatch/provenance grant."""

    base:SourceMetadata=field(repr=False)
    applied:SourceMetadata=field(repr=False)
    _payload:bytes=field(repr=False)
    sha256:str=field(init=False)

    def __post_init__(self):
        try:
            base,applied=_pin_metadata(self.base),_pin_metadata(self.applied)
            if type(self._payload) is not bytes or not 0<len(self._payload)<=MAX_PAYLOAD_BYTES:
                raise ValueError
            body=json.loads(self._payload)
            if (type(body) is not dict or set(body)!={"profile","framework_version","base_sha256","applied_sha256","custom_fields","property_setters"}
                or body["profile"]!=PROFILE or body["base_sha256"]!=base.sha256
                or body["framework_version"]!=FRAMEWORK_VERSION
                or body["applied_sha256"]!=applied.sha256 or _canonical(body)!=self._payload):
                raise ValueError
            _compare(base,applied,body["custom_fields"],body["property_setters"])
        except Exception:
            invalid=True
        else:
            invalid=False
        if invalid:
            raise MetadataReconciliationError("metadata_customization_match")
        object.__setattr__(self,"base",base)
        object.__setattr__(self,"applied",applied)
        object.__setattr__(self,"sha256",hashlib.sha256(
            b"zatca-source-field-customization-match/v1\0"+self._payload).hexdigest())

    def __repr__(self):
        return "<FieldCustomizationMatch protected declarations consistent, NOT verified origin>"

    def __reduce__(self):
        raise TypeError("metadata_customization_not_serializable")


def _capture_row(document,doctype,fields):
    if document.doctype!=doctype:
        raise ValueError
    name=_name(document.name)
    modified=_scalar(document.get("modified"))
    if modified[0] not in ("str","datetime") or not modified[1]:
        raise ValueError
    return dict(name=name,modified=modified,header=[[key,_scalar(document.get(key))] for key in fields])


def reconcile_field_customizations(base,applied,*,custom_fields,property_setters):
    """Require complete explicit baseline and raw-row declarations for ONE type.

    Caller must authorize/acquire committed raw sources and prove query/metadata
    completeness. No missing-row discovery, automatic refresh or repair occurs.
    This matches declared property effects, NOT actual database provenance.
    """
    try:
        base,applied=_pin_metadata(base),_pin_metadata(applied)
        if (type(custom_fields) not in (list,tuple) or len(custom_fields)>MAX_CUSTOM_FIELDS
            or type(property_setters) not in (list,tuple) or len(property_setters)>MAX_SETTERS):
            raise ValueError
        captured=[]
        for document in custom_fields:
            # Scope/type checks precede reading a potentially sensitive default.
            if (document.get("dt")!=base.name or document.get("fieldname") not in PROFILE_FIELDS[base.profile][base.name]
                or document.get("fieldtype")=="Password"):
                raise ValueError
            captured.append(_capture_row(document,"Custom Field",CUSTOM_FIELDS))
        setters=[]
        for document in property_setters:
            if (document.get("doc_type")!=base.name or document.get("field_name") not in PROFILE_FIELDS[base.profile][base.name]
                or document.get("property") not in EDITABLE or document.get("property_type") not in CAST_TYPES):
                raise ValueError
            setters.append(_capture_row(document,"Property Setter",SETTER_FIELDS))
        result=FieldCustomizationMatch(base,applied,_canonical(dict(profile=PROFILE,framework_version=FRAMEWORK_VERSION,
            base_sha256=base.sha256,applied_sha256=applied.sha256,
            custom_fields=sorted(captured,key=lambda row:row["name"]),
            property_setters=sorted(setters,key=lambda row:row["name"]))))
    except Exception:
        invalid=True
    else:
        invalid=False
    if invalid:
        raise MetadataReconciliationError("metadata_customization_reconciliation")
    return result
