"""PARTIAL party/address dependency graph, never an address resolver.

Explicit supplied records/candidate declarations only. No Frappe, SQL, cache,
loads, ACL, writes, country normalization or tax-authority operation. Historical
invoice address refs are preserved even when disabled/currently unlinked.
"""

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from zatca_erpgulf.ksa_compliance.field_alias_registry import FIELD_ALIAS_GROUPS
from .financial_source_observation import (
    MAX_PAYLOAD_BYTES, _canonical, _capture_table, _name, _projection, _reference,
    _scalar, _validate_projection, _validate_scalar, _validate_table,
)
from .issuing_settings_observation import IssuingSettingsObservation, _pin_settings

PROFILE = "invoice-party-address/v1"
MAX_ADDRESSES = 64
MAX_LINK_ROWS = 256
COMPANY_FIELDS = ("company_name", "tax_id", "country", "custom_costcenter",
    "custom_registration_type", "custom_company_registration",
    *FIELD_ALIAS_GROUPS["company_arabic_name"]["aliases"])
CUSTOMER_FIELDS = ("customer_name", "customer_type", "tax_id", "customer_primary_address",
    *(alias for group in ("customer_arabic_name","customer_b2c","customer_buyer_id_type",
        "customer_buyer_id","customer_unn") for alias in FIELD_ALIAS_GROUPS[group]["aliases"]))
COST_CENTER_FIELDS = ("company", "custom_zatca_branch_address", "custom_zatca__registration_type",
    "custom_zatca__registration_number")
ADDRESS_FIELDS = ("address_title", "address_type", "address_line1", "address_line2",
    "city", "pincode", "state", "country", "po_box", "custom_building_number",
    "is_primary_address", "is_shipping_address", "disabled",
    "is_your_company_address", "creation", *FIELD_ALIAS_GROUPS["address_arabic"]["aliases"])
LINK_FIELDS = ("link_doctype", "link_name", "link_title")
FIELDS = MappingProxyType({"Company":COMPANY_FIELDS, "Customer":CUSTOMER_FIELDS,
    "Cost Center":COST_CENTER_FIELDS, "Address":ADDRESS_FIELDS})
REQUIRED = MappingProxyType({"Company":("company_name","tax_id"),
    "Customer":("customer_name","tax_id"), "Cost Center":("company",),
    "Address":("address_line1","city","pincode","country")})
ROLES = ("company", "customer")


class PartyAddressError(ValueError):
    """Static internal code, no customer/address/link payload disclosure."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _discovery(value):
    if type(value) is not dict or set(value) != set(ROLES):
        raise ValueError
    result = {}
    for role in ROLES:
        names = value[role]
        if type(names) not in (list,tuple) or len(names) > MAX_ADDRESSES:
            raise ValueError
        checked = [_name(name) for name in names]
        if len(set(checked)) != len(checked):
            raise ValueError
        result[role] = checked
    return result


def _binding(settings, records, discovery):
    source = dict(json.loads(settings.financial._payload)["header"])
    company, customer = _reference(source["company"]), _reference(source["customer"])
    if company is None or customer is None:
        raise ValueError
    expected = {("Company",company), ("Customer",customer)}
    company_record, customer_record = records["Company",company], records["Customer",customer]
    headers = {key:dict(record["header"]) for key,record in records.items()}
    # The overlapping Company values AND revision must match the parent settings
    # observation. Do not compose snapshots from inconsistent source versions.
    parent_company = next(record for record in json.loads(settings._payload)["records"]
        if (record["doctype"],record["name"]) == ("Company",company))
    parent_values = dict(parent_company["header"])
    if company_record["modified"] != parent_company["modified"] or any(
        value != parent_values[field] for field,value in company_record["header"] if field in parent_values):
        raise ValueError
    addresses = set()
    for encoded in (source["company_address"],source["customer_address"],
        dict(customer_record["header"])["customer_primary_address"]):
        name = _reference(encoded)
        if name is not None: addresses.add(name)
    cost_center = _reference(source["cost_center"])
    if cost_center is not None:
        key = ("Cost Center",cost_center)
        expected.add(key)
        if headers[key]["company"] != ["str",company]:
            raise ValueError
        branch = _reference(headers[key]["custom_zatca_branch_address"])
        if branch is not None: addresses.add(branch)
    for role in ROLES:
        addresses.update(discovery[role])
    if len(addresses) > MAX_ADDRESSES:
        raise ValueError
    expected.update(("Address",name) for name in addresses)
    if set(records) != expected:
        raise ValueError
    # Candidate enumeration is still a declaration, but must be internally
    # consistent with each Address's captured current Dynamic Link rows.
    for role,party_type,party_name in (("company","Company",company),("customer","Customer",customer)):
        for name in discovery[role]:
            links = records["Address",name]["links"]["rows"]
            if not any(dict(row[2])["link_doctype"] == ["str",party_type]
                and dict(row[2])["link_name"] == ["str",party_name] for row in links):
                raise ValueError
    return tuple(sorted(expected))


def _validate_records(settings, records, discovery):
    if type(records) is not list or not 2 <= len(records) <= MAX_ADDRESSES+3:
        raise ValueError
    mapped, keys, identities, count = {}, [], set(), 0
    for record in records:
        if type(record) is not dict:
            raise ValueError
        doctype, name = record.get("doctype"), _name(record.get("name"))
        if type(doctype) is not str or doctype not in FIELDS:
            raise ValueError
        key = doctype,name
        if key in mapped or set(record) != ({"doctype","name","modified","header","links"}
            if doctype == "Address" else {"doctype","name","modified","header"}):
            raise ValueError
        _validate_projection(record["header"],FIELDS[doctype],REQUIRED[doctype])
        _validate_scalar(record["modified"])
        if record["modified"][0] not in ("str","datetime") or not record["modified"][1]:
            raise ValueError
        if doctype == "Address":
            count += _validate_table(record["links"],"Dynamic Link",LINK_FIELDS,
                ("link_doctype","link_name"),identities)
            if count > MAX_LINK_ROWS:
                raise ValueError
        mapped[key] = record
        keys.append(key)
    if keys != list(_binding(settings,mapped,discovery)):
        raise ValueError


@dataclass(frozen=True, repr=False)
class PartyAddressObservation:
    """Protected graph and supplied discovery order; still PARTIAL/unverified."""

    settings: IssuingSettingsObservation = field(repr=False)
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            settings = _pin_settings(self.settings)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile","settings_sha256","records","discovery"}
                or body["profile"] != PROFILE or body["settings_sha256"] != settings.sha256
                or _canonical(body) != self._payload):
                raise ValueError
            discovered = _discovery(body["discovery"])
            if discovered != body["discovery"]:
                raise ValueError
            _validate_records(settings,body["records"],discovered)
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise PartyAddressError("party_address_observation")
        object.__setattr__(self,"settings",settings)
        object.__setattr__(self,"sha256",hashlib.sha256(
            b"zatca-invoice-party-address/v1\0"+self._payload).hexdigest())

    def __repr__(self):
        return "<PartyAddressObservation protected PARTIAL graph, not verified>"

    def __reduce__(self):
        raise TypeError("party_address_not_serializable")


def capture_party_address_observation(settings, *, records, discovery, link_meta):
    """Capture exact supplied records, never query, select or repair an address.

    discovery has company/customer lists in caller-observed query order. It is
    NOT proof of complete query membership, ordering, eligibility or ownership.
    Direct invoice/primary refs are retained independently of disabled/current
    links; missing records still require review, never guessed fallback.
    """
    try:
        settings = _pin_settings(settings)
        discovered = _discovery(discovery)
        if type(records) is not dict or not 2 <= len(records) <= MAX_ADDRESSES+3:
            raise ValueError
        has_addresses = any(type(key) is tuple and len(key)==2 and key[0]=="Address" for key in records)
        if has_addresses != (link_meta is not None):
            raise ValueError
        captured, mapped, identities, count = [], {}, set(), 0
        for doctype,name in sorted(records):
            _name(name)
            if type(doctype) is not str or doctype not in FIELDS:
                raise ValueError
            document = records[doctype,name]
            if (document.doctype,document.name,document.meta.name) != (doctype,name,doctype):
                raise ValueError
            header = _projection(document,document.meta,FIELDS[doctype],REQUIRED[doctype])
            modified = _scalar(document.get("modified"))
            if modified[0] not in ("str","datetime") or not modified[1]:
                raise ValueError
            record = dict(doctype=doctype,name=name,modified=modified,header=header)
            if doctype == "Address":
                record["links"] = _capture_table(document,link_meta,"links","Dynamic Link",LINK_FIELDS,
                    ("link_doctype","link_name"),identities,max_rows=MAX_LINK_ROWS-count)
                count += len(record["links"]["rows"])
            mapped[doctype,name] = record
            captured.append(record)
        _binding(settings,mapped,discovered)
        result = PartyAddressObservation(settings,_canonical(dict(profile=PROFILE,
            settings_sha256=settings.sha256,records=captured,discovery=discovered)))
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise PartyAddressError("party_address_capture")
    return result
