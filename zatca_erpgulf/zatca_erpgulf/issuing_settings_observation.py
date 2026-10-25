"""Non-secret Company/device declarations bound to a PARTIAL source observation.

No Frappe, record loading, credential selection, HTTP, clock or writes. Explicit
records still need authorized committed acquisition before runtime adoption.
"""

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType

from zatca_erpgulf.ksa_compliance.field_alias_registry import FIELD_ALIAS_GROUPS
from .api_routing import ENVIRONMENT_FIELDS, resolve_api_route
from .credential_material import use_linked_company, validate_declared_linked_company_taxpayer
from .financial_source_observation import (
    InvoiceFinancialObservation, MAX_PAYLOAD_BYTES, _canonical, _name, _projection,
    _pin_financial, _reference, _scalar, _validate_projection, _validate_scalar,
)
from .scheduling import WINDOW_FIELDS

PROFILE = "invoice-issuing-settings/v1"
COMPANY_FIELDS = (
    "abbr", "company_name", "tax_id", "default_currency", "country",
    *FIELD_ALIAS_GROUPS["company_arabic_name"]["aliases"],
    "custom_zatca_invoice_enabled", "custom_phase_1_or_2", "phase_1_or_2",
    "custom_select", *ENVIRONMENT_FIELDS.values(), "custom_costcenter",
    "custom_send_einvoice_background", "custom_send_invoice_to_zatca",
    "custom_submit_or_not", "custom_submit_line_item_discount_to_zatca",
    *(name for window in WINDOW_FIELDS for name in window),
)
DEVICE_FIELDS = ("custom_linked_doctype", "custom__use_company_certificate__keys")
FIELDS = MappingProxyType({"Company": COMPANY_FIELDS, "ZATCA Multiple Setting": DEVICE_FIELDS})
REQUIRED = MappingProxyType({"Company": ("abbr", "tax_id"), "ZATCA Multiple Setting": DEVICE_FIELDS})


class IssuingSettingsError(ValueError):
    """Static internal code; never disclose record values, URLs or secrets."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _validate_company_urls(header):
    values = dict(header)
    for environment, field_name in ENVIRONMENT_FIELDS.items():
        encoded = values[field_name]
        if encoded in (["absent"], ["null"], ["str", ""]):
            continue
        if encoded[0] != "str":
            raise ValueError
        # String-only shared validation, NO request or credential resolution.
        # Reject query/userinfo secrets before any protected result is retained.
        resolve_api_route({"custom_select":environment, field_name:encoded[1]},
            "compliance/invoices", onboarding_only=True)


def _binding(financial, headers):
    source = dict(json.loads(financial._payload)["header"])
    company = _reference(source["company"])
    if company is None:
        raise ValueError
    company_key = ("Company", company)
    device = _reference(source["custom_zatca_pos_name"])
    expected = {company_key}
    owner = company_key
    if device is not None:
        device_key = ("ZATCA Multiple Setting", device)
        expected.add(device_key)
        setting = dict(headers[device_key])
        linked = _reference(setting["custom_linked_doctype"])
        if linked is None:
            raise ValueError
        linked_key = ("Company", linked)
        expected.add(linked_key)
        company_fields, linked_fields = dict(headers[company_key]), dict(headers[linked_key])
        validate_declared_linked_company_taxpayer(company,
            _validate_scalar(company_fields["tax_id"]), linked,
            _validate_scalar(linked_fields["tax_id"]))
        selected = use_linked_company(_validate_scalar(setting["custom__use_company_certificate__keys"]))
        owner = linked_key if selected else device_key
    if set(headers) != expected:
        raise ValueError
    return tuple(sorted(expected)), owner


def _validate_records(financial, records, owner):
    if type(records) is not list or not 1 <= len(records) <= 3:
        raise ValueError
    headers, keys = {}, []
    for record in records:
        if type(record) is not dict or set(record) != {"doctype", "name", "modified", "header"}:
            raise ValueError
        doctype, name = record["doctype"], _name(record["name"])
        if type(doctype) is not str or doctype not in FIELDS:
            raise ValueError
        key = doctype, name
        if key in headers:
            raise ValueError
        _validate_projection(record["header"], FIELDS[doctype], REQUIRED[doctype])
        _validate_scalar(record["modified"])
        if record["modified"][0] not in ("str", "datetime") or not record["modified"][1]:
            raise ValueError
        if doctype == "Company":
            _validate_company_urls(record["header"])
        headers[key] = record["header"]
        keys.append(key)
    expected, declared_owner = _binding(financial, headers)
    if keys != list(expected) or type(owner) is not list or owner != list(declared_owner):
        raise ValueError


@dataclass(frozen=True, repr=False)
class IssuingSettingsObservation:
    """Protected partial settings; declared owner is NOT credential provenance."""

    financial: InvoiceFinancialObservation = field(repr=False)
    _payload: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self):
        try:
            financial = _pin_financial(self.financial)
            if type(self._payload) is not bytes or not 0 < len(self._payload) <= MAX_PAYLOAD_BYTES:
                raise ValueError
            body = json.loads(self._payload)
            if (type(body) is not dict or set(body) != {"profile", "financial_sha256", "records", "declared_owner"}
                or body["profile"] != PROFILE or body["financial_sha256"] != financial.sha256
                or _canonical(body) != self._payload):
                raise ValueError
            _validate_records(financial, body["records"], body["declared_owner"])
        except Exception:
            invalid = True
        else:
            invalid = False
        if invalid:
            raise IssuingSettingsError("issuing_settings_observation")
        object.__setattr__(self, "financial", financial)
        object.__setattr__(self, "sha256", hashlib.sha256(
            b"zatca-invoice-issuing-settings/v1\0"+self._payload).hexdigest())

    def __repr__(self):
        return "<IssuingSettingsObservation protected PARTIAL declarations, not verified>"

    def __reduce__(self):
        raise TypeError("issuing_settings_not_serializable")


def _pin_settings(observation):
    """Independent validated settings/financial copy, not origin attestation."""
    if type(observation) is not IssuingSettingsObservation:
        raise ValueError
    pinned = IssuingSettingsObservation(observation.financial, observation._payload)
    if pinned != observation:
        raise ValueError
    return pinned


def capture_issuing_settings_observation(financial, *, records):
    """Require exact source Company, optional device and its linked Company.

    records is an explicit {(DocType, name): authorized saved record} map.
    Same-company links use one record; foreign linked Companies require equal
    nonempty stripped Tax IDs under the EXISTING shared declaration policy.
    No keys/certificates/auth/OTP/CSR/PIH/counters are requested from documents.
    Phase/name aliases are observed independently, never silently resolved here.
    """
    try:
        financial = _pin_financial(financial)
        if type(records) is not dict or not 1 <= len(records) <= 3:
            raise ValueError
        captured, headers = [], {}
        for doctype, name in sorted(records):
            _name(name)
            if type(doctype) is not str or doctype not in FIELDS:
                raise ValueError
            document = records[doctype, name]
            if (document.doctype, document.name, document.meta.name) != (doctype, name, doctype):
                raise ValueError
            header = _projection(document, document.meta, FIELDS[doctype], REQUIRED[doctype])
            if doctype == "Company":
                _validate_company_urls(header)
            modified = _scalar(document.get("modified"))
            if modified[0] not in ("str", "datetime") or not modified[1]:
                raise ValueError
            headers[doctype, name] = header
            captured.append(dict(doctype=doctype, name=name, modified=modified, header=header))
        _expected, owner = _binding(financial, headers)
        result = IssuingSettingsObservation(financial, _canonical(dict(profile=PROFILE,
            financial_sha256=financial.sha256, records=captured, declared_owner=list(owner))))
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise IssuingSettingsError("issuing_settings_capture")
    return result
