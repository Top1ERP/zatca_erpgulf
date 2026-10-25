"""PARTIAL POS/currency/global calculation declarations, not a calculator.

No Frappe, site defaults, clock, cache, SQL, record discovery, normalization,
rounding, FX lookup or transport. Singleton fields have NO fabricated revision.
"""

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from .financial_source_observation import (
    MAX_PAYLOAD_BYTES, _canonical, _capture_table, _name, _projection, _reference,
    _scalar, _validate_projection, _validate_scalar, _validate_table,
)
from .issuing_settings_observation import IssuingSettingsObservation, _pin_settings
from .tax_dependency_observation import _capture_template_record, _validate_template_record

PROFILE = "invoice-calculation-settings/v1"
SINGLETONS = frozenset(("System Settings", "Global Defaults"))
SYSTEM_FIELDS = ("time_zone", "country", "date_format", "time_format", "number_format",
    "float_precision", "currency_precision", "rounding_method")
GLOBAL_FIELDS = ("default_company", "default_currency", "country", "disable_rounded_total")
CURRENCY_FIELDS = ("currency_name", "enabled", "fraction", "fraction_units",
    "smallest_currency_fraction_value", "number_format", "symbol", "symbol_on_right")
POS_FIELDS = ("company", "disabled", "currency", "country", "customer", "company_address",
    "cost_center", "taxes_and_charges", "tax_category", "apply_discount_on", "disable_rounded_total",
    "write_off_account", "write_off_cost_center", "write_off_limit", "account_for_change_amount",
    "income_account", "expense_account", "allow_rate_change", "allow_discount_change",
    "allow_partial_payment", "ignore_pricing_rule")
PAYMENT_FIELDS = ("mode_of_payment", "default", "allow_in_returns")
FIELDS = MappingProxyType({"System Settings":SYSTEM_FIELDS, "Global Defaults":GLOBAL_FIELDS,
    "Currency":CURRENCY_FIELDS, "POS Profile":POS_FIELDS})
REQUIRED = MappingProxyType({"System Settings":("time_zone","float_precision","currency_precision"),
    "Global Defaults":("default_currency",), "Currency":("currency_name",),
    "POS Profile":("company","currency","taxes_and_charges")})
MAX_RECORDS = 8
MAX_PAYMENT_ROWS = 128
MAX_TAX_ROWS = 512
TAX_TEMPLATE = "Sales Taxes and Charges Template"


class CalculationSettingsError(ValueError):
    """Static errors, no raw settings, business data or driver detail."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _binding(settings, records):
    source = dict(json.loads(settings.financial._payload)["header"])
    company, invoice_currency = _reference(source["company"]), _reference(source["currency"])
    if company is None or invoice_currency is None:
        raise ValueError
    expected = {(dt,dt) for dt in SINGLETONS}
    source_company = next(record for record in json.loads(settings._payload)["records"]
        if (record["doctype"],record["name"]) == ("Company",company))
    currencies = {invoice_currency}
    for encoded in (dict(source_company["header"])["default_currency"],
        dict(records["Global Defaults","Global Defaults"]["header"])["default_currency"]):
        currency = _reference(encoded)
        if currency is not None: currencies.add(currency)
    pos = _reference(source["pos_profile"])
    if pos is not None:
        expected.add(("POS Profile",pos))
        header = dict(records["POS Profile",pos]["header"])
        if header["company"] != ["str",company]:
            raise ValueError
        currency = _reference(header["currency"])
        if currency is not None: currencies.add(currency)
        template = _reference(header["taxes_and_charges"])
        if template is not None: expected.add((TAX_TEMPLATE,template))
    expected.update(("Currency",name) for name in currencies)
    if set(records) != expected:
        raise ValueError
    return tuple(sorted(expected)),company


def _validate_records(settings, records):
    if type(records) is not list or not 3 <= len(records) <= MAX_RECORDS:
        raise ValueError
    mapped,keys,identities = {},[],set()
    source_company = _reference(dict(json.loads(settings.financial._payload)["header"])["company"])
    for record in records:
        if type(record) is not dict:
            raise ValueError
        doctype,name = record.get("doctype"),_name(record.get("name"))
        key = doctype,name
        if type(doctype) is not str or key in mapped:
            raise ValueError
        if doctype == TAX_TEMPLATE:
            if _validate_template_record(record,key,source_company,identities)>MAX_TAX_ROWS:
                raise ValueError
        else:
            if doctype not in FIELDS:
                raise ValueError
            singleton = doctype in SINGLETONS
            shape = {"doctype","name","header","singleton"} if singleton else {"doctype","name","header","modified"}
            if doctype=="POS Profile": shape.add("payments")
            if set(record)!=shape:
                raise ValueError
            _validate_projection(record["header"],FIELDS[doctype],REQUIRED[doctype])
            if singleton:
                if name!=doctype or record["singleton"] is not True:
                    raise ValueError
            else:
                _validate_scalar(record["modified"])
                if record["modified"][0] not in ("str","datetime") or not record["modified"][1]:
                    raise ValueError
            if doctype=="POS Profile" and _validate_table(record["payments"],"POS Payment Method",
                PAYMENT_FIELDS,("mode_of_payment",),identities)>MAX_PAYMENT_ROWS:
                raise ValueError
        mapped[key]=record
        keys.append(key)
    expected,_company = _binding(settings,mapped)
    if keys!=list(expected):
        raise ValueError


@dataclass(frozen=True, repr=False)
class CalculationSettingsObservation:
    """Protected exact declarations; not effective precision or UTC validation."""

    settings: IssuingSettingsObservation = field(repr=False)
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            settings = _pin_settings(self.settings)
            if type(self._payload) is not bytes or not 0<len(self._payload)<=MAX_PAYLOAD_BYTES:
                raise ValueError
            body=json.loads(self._payload)
            if (type(body) is not dict or set(body)!={"profile","settings_sha256","records"}
                or body["profile"]!=PROFILE or body["settings_sha256"]!=settings.sha256
                or _canonical(body)!=self._payload):
                raise ValueError
            _validate_records(settings,body["records"])
        except Exception:
            invalid=True
        else:
            invalid=False
        if invalid:
            raise CalculationSettingsError("calculation_settings_observation")
        object.__setattr__(self,"settings",settings)
        object.__setattr__(self,"sha256",hashlib.sha256(
            b"zatca-invoice-calculation-settings/v1\0"+self._payload).hexdigest())

    def __repr__(self):
        return "<CalculationSettingsObservation protected PARTIAL declarations, not verified>"

    def __reduce__(self):
        raise TypeError("calculation_settings_not_serializable")


def capture_calculation_settings_observation(settings, *, records, child_metas):
    """Capture EXACT supplied settings/currencies/POS/profile-tax references.

    child_metas keys are POS Profile and/or Sales Taxes and Charges Template
    only when those records exist, including empty child tables.
    Singleton identities/storage kind are explicit; do not invent modified.
    No numeric defaults, timezone interpretation or template fallback is chosen.
    """
    try:
        settings=_pin_settings(settings)
        if type(records) is not dict or not 3<=len(records)<=MAX_RECORDS or type(child_metas) is not dict:
            raise ValueError
        expected_metas={dt for dt,_name_value in records if dt in ("POS Profile",TAX_TEMPLATE)}
        if set(child_metas)!=expected_metas:
            raise ValueError
        company=_reference(dict(json.loads(settings.financial._payload)["header"])["company"])
        captured,mapped,identities=[],{},set()
        for doctype,name in sorted(records):
            _name(name)
            document=records[doctype,name]
            if (document.doctype,document.name,document.meta.name)!=(doctype,name,doctype):
                raise ValueError
            flag=getattr(document.meta,"issingle",0)
            if type(flag) not in (bool,int) or flag not in (0,1) or bool(flag)!=(doctype in SINGLETONS):
                raise ValueError
            if doctype==TAX_TEMPLATE:
                record=_capture_template_record(document,(doctype,name),company,
                    child_metas[doctype],identities,max_rows=MAX_TAX_ROWS)
            else:
                if doctype not in FIELDS:
                    raise ValueError
                record=dict(doctype=doctype,name=name,header=_projection(
                    document,document.meta,FIELDS[doctype],REQUIRED[doctype]))
                if doctype in SINGLETONS:
                    if name!=doctype:
                        raise ValueError
                    record["singleton"]=True
                else:
                    modified=_scalar(document.get("modified"))
                    if modified[0] not in ("str","datetime") or not modified[1]:
                        raise ValueError
                    record["modified"]=modified
                if doctype=="POS Profile":
                    record["payments"]=_capture_table(document,child_metas[doctype],"payments",
                        "POS Payment Method",PAYMENT_FIELDS,("mode_of_payment",),identities,max_rows=MAX_PAYMENT_ROWS)
            mapped[doctype,name]=record
            captured.append(record)
        _binding(settings,mapped)
        result=CalculationSettingsObservation(settings,_canonical(dict(profile=PROFILE,
            settings_sha256=settings.sha256,records=captured)))
    except Exception:
        invalid=True
    else:
        invalid=False
    if invalid:
        raise CalculationSettingsError("calculation_settings_capture")
    return result
